Ниже — как я бы переосмыслил API и архитектуру. Главная мысль: **разделить “sandbox runtime” и “language/runtime profile”**. Docker — это один backend. Python — один runtime profile. Потом можно будет добавить TypeScript, Bash, Ruby и т.д.

---

# 1. Ключевая архитектурная рекомендация

Я бы не делал библиотеку «про Python в Docker». Я бы сделал так:

```text
sandbox/
  core/
    SandboxManager
    SandboxBackend
    SandboxSession
    RunResult
    ResourceLimits
    VolumePolicy
    NetworkPolicy
  backends/
    DockerBackend
  runtimes/
    PythonRuntime
    TypeScriptRuntime
```

То есть верхний уровень говорит:

```python
manager.run(
    runtime="python",
    code="print(2 + 2)",
    session_id="chat-123",
)
```

А внутри:

```text
PythonRuntime готовит файлы/команду
DockerBackend создаёт/запускает контейнер
SandboxManager управляет сессиями, TTL, volumes, GC
```

Это сильно упростит расширение под TypeScript.

---

# 2. Важное изменение модели: session/container/job

Сейчас у тебя в API всё крутится вокруг `containerId`. Я бы разделил понятия:

## 1. `sessionId`

Логическая сессия пользователя/диалога.

Например:

```text
telegram-user-123/chat-456
```

В рамках сессии можно хранить:

- файлы;
- установленные библиотеки;
- кэш;
- историю;
- настройки;
- TTL.

## 2. `containerId`

Технический идентификатор конкретного Docker-контейнера.

Его лучше не отдавать наружу как основной API.

## 3. `runId`

Один конкретный запуск кода.

Например:

```text
run-2026-05-16T12:34:56-abc123
```

Так проще логировать, дебажить и ограничивать.

Я бы API строил вокруг **session_id**, а не вокруг containerId.

---

# 3. Главная рекомендация по состоянию контейнера

Есть два режима, и их лучше явно заложить в API.

## Режим 1. One-shot

```text
каждый запуск = новый контейнер
```

Это безопаснее.

Контейнер:

```text
создали → выполнили код → собрали stdout/stderr/артефакты → удалили
```

А volume с файлами сессии может жить дольше.

## Режим 2. Persistent session

```text
одна сессия = один долгоживущий контейнер
```

Это удобнее для интерактивного состояния, но менее безопасно.

Например:

```python
x = 10
```

потом:

```python
print(x)
```

В persistent-контейнере это может работать, если ты запускаешь интерактивный процесс или notebook-подобный executor.

Но для первой версии я бы сделал:

> **контейнеры одноразовые, volume сессии живёт по TTL.**

Это хороший баланс: контейнер чистый, но файлы могут сохраняться.

---

# 4. Что бы я изменил в твоих методах

## Было

```python
createContainer(containerId: int, ...)
runScript(containerId: int, ...)
dropContainer(containerId: int, ...)
```

## Лучше

```python
createSession(session_id: str, ...)
runCode(session_id: str, ...)
dropSession(session_id: str, ...)
```

Контейнер — деталь реализации.

---

# 5. Предлагаемый API

## 5.1. Инициализация

```python
manager = SandboxManager(config: SandboxConfig)
```

Лучше использовать не `Dict[str, Any]`, а dataclass/Pydantic-модель.

Например:

```python
@dataclass
class SandboxConfig:
    backend: BackendConfig
    runtimes: dict[str, RuntimeConfig]
    storage: StorageConfig
    defaults: ExecutionDefaults
    security: SecurityConfig
    gc: GarbageCollectorConfig
    logging: LoggingConfig
```

Если хочешь оставить dict — можно, но внутри всё равно валидировать и приводить к типизированной модели.

---

## 5.2. Создание сессии

Вместо:

```python
createContainer(...)
```

лучше:

```python
def createSession(
    session_id: str,
    runtime: str = "python",
    force_recreate: bool = False,
    required_libs: Optional[Sequence[str]] = None,
    ttl_minutes: Optional[int] = None,
    allow_network: bool = False,
    extra_config: Optional[SandboxOverrides] = None,
) -> SessionInfo:
    ...
```

Возвращать лучше не `bool`, а объект.

```python
@dataclass
class SessionInfo:
    session_id: str
    runtime: str
    created: bool
    reused: bool
    volume_path: str
    expires_at: datetime
    installed_libs: list[str]
    network_enabled: bool
```

Почему не `bool`: тебе почти всегда понадобится знать, что именно произошло.

---

## 5.3. Удаление сессии

```python
def dropSession(
    session_id: str,
    clean_volumes: bool = True,
    force: bool = True,
) -> DropSessionResult:
    ...
```

```python
@dataclass
class DropSessionResult:
    session_id: str
    container_removed: bool
    volumes_removed: bool
    existed: bool
    errors: list[str]
```

---

## 5.4. Запуск кода

Вместо:

```python
runScript(containerId, script, ...)
```

лучше:

```python
def runCode(
    session_id: str,
    code: str,
    runtime: str = "python",
    timeout_seconds: Optional[int] = None,
    required_libs: Optional[Sequence[str]] = None,
    allow_network: bool = False,
    mode: Literal["oneshot", "session"] = "oneshot",
    stdin: Optional[str] = None,
    env: Optional[dict[str, str]] = None,
    files: Optional[Sequence[InputFile]] = None,
    extra_config: Optional[SandboxOverrides] = None,
) -> RunResult:
    ...
```

`mode="oneshot"` — новый контейнер для запуска.

`mode="session"` — переиспользование контейнера сессии, если ты это захочешь поддержать позже.

---

## 5.5. Результат запуска

```python
@dataclass
class RunResult:
    run_id: str
    session_id: str
    runtime: str

    stdout: str
    stderr: str
    combined_output: str

    exit_code: Optional[int]
    signal: Optional[str]
    timed_out: bool
    oom_killed: bool

    started_at: datetime
    finished_at: datetime
    elapsed_ms: int

    artifacts: list[ArtifactInfo]

    limits: ResourceLimits
    usage: Optional[ResourceUsage]

    error: Optional[str]
```

Я бы добавил:

```python
oom_killed
timed_out
signal
```

Потому что `retCode=-1` часто недостаточно информативен.

---

## 5.6. Работа с файлами

Твой метод:

```python
getFileContent(containerId: int, fileName: str) -> Optional[str]
```

Я бы изменил на:

```python
def listFiles(
    session_id: str,
    path: str = "/",
    recursive: bool = False,
) -> list[FileInfo]:
    ...
```

```python
def readFile(
    session_id: str,
    path: str,
    max_bytes: Optional[int] = None,
    encoding: str = "utf-8",
) -> Optional[FileContent]:
    ...
```

```python
def writeFile(
    session_id: str,
    path: str,
    content: bytes | str,
    overwrite: bool = True,
) -> FileInfo:
    ...
```

```python
def deleteFile(
    session_id: str,
    path: str,
) -> bool:
    ...
```

```python
def downloadArtifact(
    session_id: str,
    artifact_id: str,
) -> bytes:
    ...
```

Файлы — важная часть песочницы. Лучше сразу сделать нормальную файловую модель.

---

## 5.7. Библиотеки

Твои методы:

```python
getInstalledLibs()
upgradeLibs(libs)
```

Нужно уточнить, где именно установлены библиотеки:

- глобально в образе?
- в volume конкретной сессии?
- в кэше runtime?
- в user-site директории?
- в virtualenv?

Я бы делал не `getInstalledLibs()`, а:

```python
def listInstalledPackages(
    session_id: Optional[str] = None,
    runtime: str = "python",
) -> list[PackageInfo]:
    ...
```

```python
def installPackages(
    session_id: str,
    packages: Sequence[str],
    runtime: str = "python",
    allow_network: bool = True,
    upgrade: bool = False,
    timeout_seconds: int = 300,
) -> PackageInstallResult:
    ...
```

```python
def removePackages(
    session_id: str,
    packages: Sequence[str],
    runtime: str = "python",
) -> PackageRemoveResult:
    ...
```

```python
def freezePackages(
    session_id: str,
    runtime: str = "python",
) -> str:
    ...
```

```python
def syncPackages(
    session_id: str,
    packages: Sequence[str],
    runtime: str = "python",
    strategy: Literal["install-missing", "exact", "upgrade"] = "install-missing",
) -> PackageSyncResult:
    ...
```

Для Python я бы хранил зависимости в отдельной директории сессии или runtime-cache.

Например:

```text
/storage/sessions/<session_id>/workspace
/storage/sessions/<session_id>/artifacts
/storage/sessions/<session_id>/python/userbase
/storage/sessions/<session_id>/metadata.json
```

И устанавливал бы так:

```bash
python -m pip install --user <libs>
```

или лучше:

```bash
python -m pip install --target /sandbox/deps <libs>
```

А затем при запуске:

```bash
PYTHONPATH=/sandbox/deps
```

Мне вариант с `--target` нравится больше, потому что он явнее.

---

# 6. Важное замечание про установку библиотек

Ты предлагаешь:

> Перед стартом контейнера оно стартует контейнер с доступом к сети для `pip --user install <REQUIRED LIBS>`. Потом home пользователя монтируется в контейнер read-only.

Идея рабочая, но я бы сделал жёстче:

```text
install-container:
  network enabled
  writable deps volume
  no user code
  command = pip install ...

run-container:
  network disabled by default
  deps volume mounted read-only
  workspace mounted writable или limited
  user code executes
```

То есть установка библиотек и запуск пользовательского кода должны быть **разными контейнерами**.

Почему:

- во время установки есть сеть;
- пользовательский код не должен случайно выполняться в сетевом контейнере;
- проще аудит;
- проще кэшировать зависимости;
- проще запретить модификацию dependencies во время выполнения.

---

# 7. Нужен lock-файл / manifest сессии

Обязательно храни метаданные.

Например:

```json
{
  "session_id": "chat-123",
  "runtime": "python",
  "created_at": "2026-05-16T12:00:00Z",
  "updated_at": "2026-05-16T12:10:00Z",
  "expires_at": "2026-05-16T12:30:00Z",
  "network_allowed": false,
  "installed_packages": {
    "numpy": "2.0.0",
    "pandas": "2.2.0"
  },
  "limits": {
    "memory_mb": 512,
    "cpu_count": 1,
    "pids": 64,
    "timeout_seconds": 300
  }
}
```

Зачем:

- после рестарта сервиса можно восстановить состояние;
- можно понять, какие библиотеки уже установлены;
- можно делать GC;
- можно отлаживать;
- можно вести аудит.

---

# 8. Какие ещё методы нужны

## 8.1. `getSessionInfo`

```python
def getSessionInfo(session_id: str) -> Optional[SessionInfo]:
    ...
```

Нужно для отладки, UI, LLM tools, мониторинга.

---

## 8.2. `listSessions`

```python
def listSessions(
    runtime: Optional[str] = None,
    include_expired: bool = False,
) -> list[SessionInfo]:
    ...
```

---

## 8.3. `touchSession`

Продлить TTL при активности:

```python
def touchSession(
    session_id: str,
    ttl_minutes: Optional[int] = None,
) -> SessionInfo:
    ...
```

---

## 8.4. `resetSession`

Очистить рабочую директорию, но сохранить зависимости.

```python
def resetSession(
    session_id: str,
    keep_packages: bool = True,
    keep_artifacts: bool = False,
) -> ResetSessionResult:
    ...
```

---

## 8.5. `prepareRuntime`

Построить образ, проверить наличие образа, прогреть зависимости.

```python
def prepareRuntime(
    runtime: str,
    rebuild: bool = False,
    pull: bool = False,
) -> RuntimeInfo:
    ...
```

---

## 8.6. `buildImage`

Если Dockerfile управляется библиотекой:

```python
def buildImage(
    runtime: str,
    dockerfile_path: Optional[str] = None,
    tag: Optional[str] = None,
    no_cache: bool = False,
) -> ImageBuildResult:
    ...
```

---

## 8.7. `healthcheck`

```python
def healthcheck() -> HealthcheckResult:
    ...
```

Проверяет:

- доступен ли Docker;
- есть ли нужные образы;
- доступна ли storage-директория;
- хватает ли прав;
- можно ли создать тестовый контейнер.

---

## 8.8. `estimateUsage`

```python
def estimateUsage(
    session_id: Optional[str] = None,
) -> StorageUsage:
    ...
```

Полезно для GC и лимитов.

---

## 8.9. `getLogs`

```python
def getLogs(
    run_id: str,
    stream: Literal["stdout", "stderr", "combined"] = "combined",
) -> str:
    ...
```

---

## 8.10. `cancelRun`

Если запуски асинхронные:

```python
def cancelRun(run_id: str) -> bool:
    ...
```

---

## 8.11. Асинхронный API

Для чат-бота может быть полезно:

```python
async def runCodeAsync(...) -> RunResult:
    ...
```

Или job-модель:

```python
run_id = manager.submitCode(...)
result = manager.waitRun(run_id)
manager.cancelRun(run_id)
```

---

# 9. Нужен ли базовый класс?

Да. Я бы сделал несколько интерфейсов.

## 9.1. Backend

```python
class SandboxBackend(Protocol):
    def create_container(self, spec: ContainerSpec) -> ContainerHandle:
        ...

    def run_container(self, spec: ContainerSpec) -> RunResult:
        ...

    def remove_container(self, container_id: str, force: bool = True) -> None:
        ...

    def exec(self, container_id: str, command: Sequence[str], timeout: int) -> ExecResult:
        ...

    def copy_from(self, container_id: str, path: str) -> bytes:
        ...

    def healthcheck(self) -> HealthcheckResult:
        ...
```

Docker — просто реализация:

```python
class DockerBackend(SandboxBackend):
    ...
```

Потом можно добавить:

```python
class FirecrackerBackend(SandboxBackend):
    ...
```

---

## 9.2. Runtime

```python
class RuntimeProfile(Protocol):
    name: str

    def prepare_code(self, code: str, session: SessionInfo) -> PreparedRun:
        ...

    def install_packages_command(self, packages: Sequence[str], upgrade: bool) -> Sequence[str]:
        ...

    def run_command(self, prepared: PreparedRun) -> Sequence[str]:
        ...

    def detect_artifacts(self, workspace: Path) -> list[ArtifactInfo]:
        ...
```

Python:

```python
class PythonRuntime(RuntimeProfile):
    name = "python"
```

TypeScript:

```python
class TypeScriptRuntime(RuntimeProfile):
    name = "typescript"
```

---

# 10. Docker-настройки и ограничения

Вот список того, что я бы заложил в конфиг.

## 10.1. Пользователь

Не root:

```python
user="1000:1000"
```

В Dockerfile:

```dockerfile
RUN useradd -m -u 1000 sandbox
USER sandbox
```

---

## 10.2. Сеть

По умолчанию:

```python
network_disabled=True
```

Для установки пакетов — отдельный install-контейнер с сетью.

Для запуска кода:

```text
allowNetwork = false by default
```

Если сеть всё-таки нужна, лучше не давать полный интернет, а потом сделать proxy/allowlist.

---

## 10.3. Capabilities

```python
cap_drop=["ALL"]
```

---

## 10.4. Privilege escalation

```python
security_opt=["no-new-privileges"]
```

---

## 10.5. Read-only root filesystem

```python
read_only=True
```

А writable места только явно:

```python
tmpfs={
    "/tmp": "rw,nosuid,nodev,size=64m",
}
```

---

## 10.6. Memory limit

```python
mem_limit="512m"
```

В конфиге:

```yaml
memory_mb: 512
memory_swap_mb: 512
```

Хорошо бы отключать swap или ограничивать его.

---

## 10.7. CPU limit

```python
nano_cpus=1_000_000_000
```

или:

```python
cpu_quota
cpu_period
```

---

## 10.8. PIDs limit

```python
pids_limit=64
```

Защита от fork bomb.

---

## 10.9. Timeout

На уровне твоего runner'а:

```text
timeout_seconds: 300
```

Но для LLM-кода я бы по умолчанию ставил меньше:

```text
10–30 секунд
```

300 секунд — это много, если бот публичный.

---

## 10.10. Output limit

Обязательно:

```text
max_stdout_bytes
max_stderr_bytes
max_combined_output_bytes
```

Например:

```yaml
max_stdout_bytes: 65536
max_stderr_bytes: 65536
max_combined_output_bytes: 131072
```

---

## 10.11. Artifact limits

```yaml
max_artifact_size_mb: 20
max_total_artifacts_size_mb: 100
max_artifact_count: 50
```

---

## 10.12. Workspace size

Если workspace — bind mount, Docker сам не ограничит размер директории. Поэтому нужно контролировать руками.

Если tmpfs:

```python
tmpfs={
    "/workspace": "rw,nosuid,nodev,size=128m"
}
```

Но если нужно сохранять файлы после завершения контейнера, tmpfs внутри контейнера неудобен. Тогда host-volume + post-run quota check.

---

## 10.13. Запрет sensitive mounts

В коде библиотеки хорошо бы явно проверять, что пользователь не прокинул опасные mounts:

```text
/var/run/docker.sock
/
/etc
/proc
/sys
/dev
/home
/root
~/.ssh
.env
```

---

## 10.14. `privileged=False`

Явно:

```python
privileged=False
```

---

## 10.15. Devices

Не передавать devices.

```python
devices=[]
```

---

## 10.16. Auto-remove

Я бы не использовал `auto_remove=True`, если нужно собирать логи/артефакты после завершения.

Лучше:

```text
run → wait → collect logs → collect artifacts → remove
```

---

## 10.17. Docker labels

Очень полезно.

Каждый контейнер и volume маркировать:

```python
labels={
    "sandbox.managed": "true",
    "sandbox.session_id": session_id,
    "sandbox.run_id": run_id,
    "sandbox.runtime": runtime,
    "sandbox.created_at": "...",
}
```

Это поможет GC.

---

## 10.18. Names

Не использовать raw user input в имени контейнера. Делать safe slug/hash.

```text
sandbox-py-<session-hash>-<run-hash>
```

---

# 11. Конфиг: пример

Пример в YAML, но его можно представить как dict.

```yaml
backend:
  type: docker
  docker:
    base_url: unix:///var/run/docker.sock
    image_pull_policy: if-not-present
    container_name_prefix: sandbox
    labels:
      sandbox.managed: "true"

storage:
  root_dir: /var/lib/mybot/sandbox
  sessions_dir: /var/lib/mybot/sandbox/sessions
  cache_dir: /var/lib/mybot/sandbox/cache
  artifacts_dir: /var/lib/mybot/sandbox/artifacts
  metadata_file: metadata.json
  file_permissions:
    dir_mode: "0700"
    file_mode: "0600"

defaults:
  mode: oneshot
  ttl_minutes: 30
  hard_ttl_minutes: 120
  run_timeout_seconds: 30
  install_timeout_seconds: 300
  allow_network: false

resources:
  memory_mb: 512
  memory_swap_mb: 512
  cpu_count: 1.0
  pids_limit: 64
  tmpfs_size_mb: 64
  workspace_size_mb: 256
  max_stdout_bytes: 65536
  max_stderr_bytes: 65536
  max_combined_output_bytes: 131072
  max_artifact_size_mb: 20
  max_total_artifacts_size_mb: 100
  max_artifact_count: 50

security:
  user: "1000:1000"
  read_only_rootfs: true
  no_new_privileges: true
  drop_capabilities: ["ALL"]
  privileged: false
  network_disabled_by_default: true
  allow_docker_socket_mount: false
  allowed_mount_roots:
    - /var/lib/mybot/sandbox
  denied_mounts:
    - /
    - /etc
    - /proc
    - /sys
    - /dev
    - /var/run/docker.sock
    - /root
    - /home
  seccomp_profile: null
  apparmor_profile: null

gc:
  enabled: true
  interval_seconds: 60
  remove_expired_sessions: true
  session_idle_ttl_minutes: 30
  session_hard_ttl_minutes: 120
  deleted_volume_retention_minutes: 60
  orphan_container_retention_minutes: 10
  orphan_volume_retention_minutes: 60

runtimes:
  python:
    image: my-sandbox-python:3.12
    dockerfile: ./runtimes/python/Dockerfile
    workdir: /sandbox/workspace
    code_filename: main.py
    command:
      - python
      - /sandbox/workspace/main.py
    env:
      PYTHONUNBUFFERED: "1"
      MPLBACKEND: Agg
      PYTHONDONTWRITEBYTECODE: "1"
    package_manager:
      type: pip
      deps_dir: /sandbox/deps
      install_command:
        - python
        - -m
        - pip
        - install
        - --target
        - /sandbox/deps
      freeze_command:
        - python
        - -m
        - pip
        - freeze
        - --path
        - /sandbox/deps
    default_packages:
      - numpy
      - pandas
      - matplotlib
      - scipy
      - sympy
    allowed_packages: null
    denied_packages:
      - docker
      - kubernetes
    artifacts:
      output_dir: /sandbox/workspace/output
      allowed_extensions:
        - .txt
        - .json
        - .csv
        - .png
        - .jpg
        - .svg
        - .html

  typescript:
    image: my-sandbox-typescript:latest
    dockerfile: ./runtimes/typescript/Dockerfile
    workdir: /sandbox/workspace
    code_filename: main.ts
    command:
      - node
      - --loader
      - ts-node/esm
      - /sandbox/workspace/main.ts
    env: {}
    package_manager:
      type: npm
      deps_dir: /sandbox/node_modules
```

---

# 12. Dockerfile для Python

Я бы не брал Alpine для первой версии. Лучше `python:3.12-slim` или `python:3.13-slim`.

Причина: с Alpine чаще возникают проблемы с Python-пакетами, бинарными wheel, numpy/pandas/scipy и зависимостями.

Пример:

```dockerfile
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1
ENV MPLBACKEND=Agg

RUN useradd -m -u 1000 sandbox

WORKDIR /sandbox

RUN python -m pip install --no-cache-dir --upgrade pip setuptools wheel

RUN python -m pip install --no-cache-dir \
    numpy \
    pandas \
    matplotlib \
    scipy \
    sympy \
    scikit-learn \
    pillow

RUN mkdir -p /sandbox/workspace /sandbox/deps /sandbox/tmp \
    && chown -R sandbox:sandbox /sandbox

USER sandbox

CMD ["python"]
```

---

# 13. Как организовать директории на хосте

Например:

```text
/var/lib/mybot/sandbox/
  sessions/
    <session_id_hash>/
      metadata.json
      workspace/
        main.py
        output/
      deps/
      deleted_at
  cache/
    pip/
    images/
  runs/
    <run_id>/
      stdout.txt
      stderr.txt
      result.json
```

Лучше не использовать `session_id` напрямую как имя директории. Лучше:

```python
session_hash = sha256(session_id.encode()).hexdigest()[:32]
```

---

# 14. Стоит ли хранить библиотеки между сессиями?

Есть три стратегии.

## Вариант A. Всё в образе

Самый простой и безопасный.

```text
numpy, pandas, matplotlib уже в Docker image
```

Плюсы:

- нет сетевой установки во время работы;
- воспроизводимо;
- безопаснее.

Минусы:

- если нужна новая библиотека, надо пересобирать образ.

---

## Вариант B. Deps per session

```text
каждая сессия имеет свой deps/
```

Плюсы:

- изоляция;
- разные пользователи не мешают друг другу.

Минусы:

- много места;
- дольше установка.

---

## Вариант C. Shared package cache

```text
общий readonly cache зависимостей
```

Плюсы:

- быстрее;
- меньше места.

Минусы:

- сложнее;
- возможны конфликты версий;
- нужно аккуратно управлять правами.

Для первой версии я бы сделал:

```text
часто используемые библиотеки — в образ
дополнительные библиотеки — в session deps
```

---

# 15. Что делать с `requiredLibs`

Я бы не принимал от LLM произвольные строки вида:

```text
["some-package>=1.0; rm -rf /"]
```

Даже если ты передаёшь список аргументами, всё равно нужен validation.

Минимум:

```python
def validate_package_spec(spec: str) -> bool:
    ...
```

Разрешать только package spec в формате Python packaging.

Также можно ввести политики:

```yaml
packages:
  allow_install: true
  allowed:
    - numpy
    - pandas
    - requests
    - beautifulsoup4
  denied:
    - docker
    - kubernetes
    - paramiko
    - scapy
```

Для публичного LLM-бота я бы сделал allowlist.

---

# 16. Что ещё предусмотреть

## 16.1. Конкурентный доступ

Если два сообщения одновременно запускают код в одной сессии, что делать?

Нужен lock:

```text
session lock
```

Политики:

```text
reject
queue
parallel
```

Для начала:

```text
один run на session_id одновременно
```

---

## 16.2. Idempotency

Методы установки библиотек и создания сессии должны быть идемпотентными.

```python
createSession(...)
```

повторно не должен ломать существующую сессию.

---

## 16.3. Аудит

Логировать:

- кто запросил запуск;
- какой session_id;
- какой runtime;
- какой код;
- какие библиотеки;
- allow_network;
- лимиты;
- stdout/stderr;
- exit_code;
- duration;
- artifacts;
- errors.

Но осторожно с персональными данными и секретами.

---

## 16.4. Secret handling

Не пробрасывать секреты окружения основного приложения в контейнер.

Не делать:

```python
environment=os.environ
```

Только allowlist env-переменных.

---

## 16.5. Размер кода

Ограничить:

```yaml
max_code_bytes: 100000
```

---

## 16.6. Размер stdin

```yaml
max_stdin_bytes: 100000
```

---

## 16.7. Количество запусков

На уровне LLM/tools:

```text
max runs per minute per user
max runs per day per user
max package installs per day
```

---

## 16.8. Очистка после crash

При старте сервиса нужно делать recovery:

```python
manager.recover()
```

Он должен найти:

- старые контейнеры с label `sandbox.managed=true`;
- orphan volumes;
- незавершённые run records;
- session metadata.

---

## 16.9. Версионирование runtime

Важно:

```text
python:3.12-v1
python:3.12-v2
typescript:node22-v1
```

Иначе после обновления образа старые сессии могут неожиданно поменять поведение.

---

## 16.10. Политика сети

Не просто `allowNetwork: bool`, а лучше:

```python
NetworkPolicy(
    mode="none" | "full" | "proxy" | "allowlist",
    allowed_hosts=[...],
)
```

Для начала можно оставить bool, но в конфиге заложить расширение.

---

# 17. Возможная модель классов

```python
@dataclass
class ResourceLimits:
    memory_mb: int = 512
    memory_swap_mb: Optional[int] = 512
    cpu_count: float = 1.0
    pids_limit: int = 64
    timeout_seconds: int = 30
    tmpfs_size_mb: int = 64
    workspace_size_mb: int = 256
    max_stdout_bytes: int = 65536
    max_stderr_bytes: int = 65536
    max_artifact_size_mb: int = 20
    max_total_artifacts_size_mb: int = 100
    max_artifact_count: int = 50
```

```python
@dataclass
class NetworkPolicy:
    enabled: bool = False
    mode: Literal["none", "full", "proxy", "allowlist"] = "none"
    allowed_hosts: list[str] = field(default_factory=list)
```

```python
@dataclass
class RunRequest:
    session_id: str
    runtime: str
    code: str
    timeout_seconds: Optional[int] = None
    required_packages: list[str] = field(default_factory=list)
    network: NetworkPolicy = field(default_factory=NetworkPolicy)
    stdin: Optional[str] = None
    env: dict[str, str] = field(default_factory=dict)
    files: list[InputFile] = field(default_factory=list)
    mode: Literal["oneshot", "session"] = "oneshot"
    limits: Optional[ResourceLimits] = None
```

```python
@dataclass
class ArtifactInfo:
    id: str
    path: str
    name: str
    size_bytes: int
    mime_type: Optional[str] = None
    sha256: Optional[str] = None
```

```python
@dataclass
class RunResult:
    run_id: str
    session_id: str
    runtime: str
    stdout: str
    stderr: str
    exit_code: Optional[int]
    timed_out: bool
    oom_killed: bool
    elapsed_ms: int
    artifacts: list[ArtifactInfo]
    error: Optional[str] = None
```

---

# 18. Переработанный набор методов

Я бы предложил такой публичный API.

```python
class SandboxManager:
    def __init__(self, config: SandboxConfig):
        ...

    def prepareRuntime(self, runtime: str, rebuild: bool = False) -> RuntimeInfo:
        ...

    def createSession(
        self,
        session_id: str,
        runtime: str = "python",
        force_recreate: bool = False,
        required_packages: Optional[Sequence[str]] = None,
        ttl_minutes: Optional[int] = None,
        network: Optional[NetworkPolicy] = None,
        limits: Optional[ResourceLimits] = None,
    ) -> SessionInfo:
        ...

    def getSessionInfo(self, session_id: str) -> Optional[SessionInfo]:
        ...

    def listSessions(self) -> list[SessionInfo]:
        ...

    def touchSession(self, session_id: str, ttl_minutes: Optional[int] = None) -> SessionInfo:
        ...

    def resetSession(
        self,
        session_id: str,
        keep_packages: bool = True,
        keep_artifacts: bool = False,
    ) -> ResetSessionResult:
        ...

    def dropSession(
        self,
        session_id: str,
        clean_volumes: bool = True,
        force: bool = True,
    ) -> DropSessionResult:
        ...

    def runCode(
        self,
        request: RunRequest,
    ) -> RunResult:
        ...

    def installPackages(
        self,
        session_id: str,
        packages: Sequence[str],
        runtime: str = "python",
        upgrade: bool = False,
    ) -> PackageInstallResult:
        ...

    def listInstalledPackages(
        self,
        session_id: str,
        runtime: str = "python",
    ) -> list[PackageInfo]:
        ...

    def freezePackages(
        self,
        session_id: str,
        runtime: str = "python",
    ) -> str:
        ...

    def listFiles(
        self,
        session_id: str,
        path: str = "/",
        recursive: bool = False,
    ) -> list[FileInfo]:
        ...

    def readFile(
        self,
        session_id: str,
        path: str,
        max_bytes: Optional[int] = None,
        encoding: Optional[str] = "utf-8",
    ) -> FileContent:
        ...

    def writeFile(
        self,
        session_id: str,
        path: str,
        content: bytes | str,
        overwrite: bool = True,
    ) -> FileInfo:
        ...

    def deleteFile(
        self,
        session_id: str,
        path: str,
    ) -> bool:
        ...

    def collectGarbage(self) -> GarbageCollectionResult:
        ...

    def recover(self) -> RecoveryResult:
        ...

    def healthcheck(self) -> HealthcheckResult:
        ...

    def shutdown(self, clean_volumes: bool = False) -> ShutdownResult:
        ...
```

---

# 19. Что оставить из твоих методов

Твои методы по смыслу хорошие, но я бы переименовал и уточнил:

| Текущий метод | Что сделать |
|---|---|
| `__init__(config)` | оставить, но конфиг типизировать |
| `createContainer` | заменить на `createSession` |
| `dropContainer` | заменить на `dropSession` |
| `collectGarbage` | оставить |
| `shutdown` | оставить |
| `runScript` | заменить на `runCode(RunRequest)` |
| `getFileContent` | заменить на `readFile` + `listFiles` |
| `getInstalledLibs` | заменить на `listInstalledPackages(session_id)` |
| `upgradeLibs` | заменить на `installPackages(..., upgrade=True)` |

---

# 20. Важное про `allowNetwork`

Не стоит молча пересоздавать контейнер, если `allowNetwork` не совпал.

Вот это:

> если контейнера не было или allowNetwork не совпадает с тем, что у контейнера то оно его [пере]создает

Может быть опасным и неочевидным.

Лучше:

```python
runCode(..., network=NetworkPolicy(enabled=True))
```

И внутри:

- для one-shot — создать контейнер с нужной network policy;
- для persistent session — если политика несовместима, вернуть ошибку или явно создать новый container generation.

То есть не делать скрытый security downgrade/upgrade.

---

# 21. Что делать с garbage collection

GC должен чистить:

1. Контейнеры, управляемые библиотекой.
2. Сессии с истёкшим TTL.
3. Run records старше retention.
4. Артефакты старше retention.
5. Orphan volumes/directories.
6. Пакетные кэши, если превышен размер.
7. Docker images, если библиотека ими управляет — осторожно.

Результат лучше возвращать:

```python
@dataclass
class GarbageCollectionResult:
    removed_containers: int
    removed_sessions: int
    removed_volumes: int
    removed_artifacts: int
    freed_bytes: int
    errors: list[str]
```

---

# 22. Санитайзинг: где его место

Ты правильно пишешь, что LLM-facing функции будут поверх этой либы.

Я бы разделил:

```text
sandbox library:
  механически безопасно запускает код с лимитами

LLM tool wrapper:
  решает, можно ли запускать этот код
  решает, можно ли ставить эти библиотеки
  решает, можно ли включать сеть
  rate limits
  moderation / policy checks
```

Не надо слишком много LLM-логики пихать в sandbox-lib.

Но sandbox-lib всё равно должна иметь свои hard security limits, потому что верхний слой может ошибиться.

---

# 23. Самые важные ограничения Docker для твоего случая

Короткий список must-have:

```python
network_disabled=True  # default
mem_limit="512m"
memswap_limit="512m"
nano_cpus=1_000_000_000
pids_limit=64
read_only=True
cap_drop=["ALL"]
security_opt=["no-new-privileges"]
user="1000:1000"
privileged=False
tmpfs={
    "/tmp": "rw,nosuid,nodev,size=64m"
}
```

Также:

```text
не монтировать docker.sock
не монтировать чувствительные директории
не пробрасывать env всего приложения
ограничивать stdout/stderr
ограничивать artifacts
делать timeout
делать session lock
использовать labels
```

---

# 24. Самое спорное место: persistent containers

Если у тебя LLM будет часто запускать короткие куски кода, persistent container кажется привлекательным. Но для первой версии я бы сделал так:

```text
container: ephemeral
workspace volume: persistent by session
deps volume: persistent by session
```

То есть:

```text
run 1:
  create container
  mount workspace
  mount deps readonly
  execute
  delete container

run 2:
  create fresh container
  mount same workspace
  mount same deps readonly
  execute
  delete container
```

Так ты сохраняешь файлы и зависимости, но не сохраняешь процессы, переменные памяти и скрытое состояние контейнера.

Это более предсказуемо.

---

# 25. Очень краткий план библиотеки для обсуждения с командой

## Цель

Создать переиспользуемую библиотеку для безопасного запуска пользовательского кода в изолированной sandbox-среде с поддержкой разных runtime: Python, TypeScript и других.

## Основные сущности

1. **SandboxManager** — главный интерфейс библиотеки.
2. **Backend** — слой исполнения, первая реализация: Docker.
3. **RuntimeProfile** — описание языка/среды: Python, TypeScript и т.д.
4. **Session** — логическая рабочая область пользователя или диалога.
5. **Run** — один конкретный запуск кода.
6. **Artifacts** — файлы, созданные во время выполнения.
7. **Package Manager** — установка и учёт зависимостей runtime.

## Базовый сценарий

1. Создать или получить sandbox-сессию.
2. При необходимости установить зависимости в отдельном install-контейнере.
3. Запустить код в одноразовом контейнере с ограничениями.
4. Собрать stdout, stderr, exit code, elapsed time и artifacts.
5. Удалить контейнер.
6. Сохранить workspace/deps до истечения TTL.
7. Периодически выполнять garbage collection.

## Требования безопасности

- код запускается не от root;
- сеть выключена по умолчанию;
- root filesystem read-only;
- capabilities сброшены;
- запрещён privileged mode;
- Docker socket не монтируется;
- заданы лимиты CPU, RAM, PID, timeout;
- ограничены stdout/stderr и размер artifacts;
- зависимости монтируются read-only во время выполнения;
- установка зависимостей и запуск пользовательского кода разделены.

## Публичный API

- `createSession`
- `dropSession`
- `runCode`
- `installPackages`
- `listInstalledPackages`
- `listFiles`
- `readFile`
- `writeFile`
- `collectGarbage`
- `recover`
- `healthcheck`
- `shutdown`

## Конфигурация

Конфиг описывает:

- backend Docker;
- директории хранения;
- default resource limits;
- security policy;
- network policy;
- garbage collection policy;
- runtime profiles;
- package policies;
- artifact limits.

## Первый этап реализации

1. Docker backend.
2. Python runtime.
3. One-shot containers.
4. Persistent workspace/deps per session.
5. Установка Python-пакетов через отдельный install-container.
6. Базовый GC.
7. Лимиты ресурсов и выводов.
8. Логирование и healthcheck.

## Второй этап

1. TypeScript runtime.
2. Асинхронный запуск и cancel.
3. Network proxy/allowlist.
4. Package allowlist/denylist.
5. Расширенный мониторинг usage.
6. Поддержка альтернативных backend: gVisor, Firecracker, Kubernetes Jobs.

