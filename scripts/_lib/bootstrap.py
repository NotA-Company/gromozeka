"""Bootstrap helpers for standalone scripts under ``scripts/``.

Each script that constructs ``ConfigManager`` and then builds any
proxy-consuming service (``LLMManager``, ``Database`` with sqlink,
``OpenrouterProvider``, ``BasicOpenAIProvider``, any httpx client that
resolves proxy via ``ProxyConfig``) MUST initialise the global
``ProxyHelper`` singleton first. Otherwise ``ProxyConfig.getCombined()``
raises ``TypeError("need to call setGlobalProxyConfig() first")`` from
inside ``BasicOpenAIProvider._initClient()`` (which runs in the provider's
``__init__``), every provider fails to register, and the script silently
exits with "0 text-capable models".

Centralising the call here prevents the "forgot one site" regression that
originally bit ``scripts/check_image_parsing.py`` and (at the time this
helper was introduced) was also latent in ``check_structured_output.py``,
``check_tool_calling.py``, ``run_llm_debug_query.py``, and ``list_models.py``.

Production code (``main.py:78``) achieves the same effect via
``ProxyService.getInstance().initialize(configManager.getProxyConfig(), loop=loop)``,
which internally calls ``ProxyHelper.getInstance().setGlobalProxyConfig(...)``
at ``internal/services/proxy/service.py:103``. Scripts do not need the full
``ProxyService`` machinery (CRON health checks, lifecycle hooks, event-loop
registration), so they call the lower-level helper directly.
"""

from internal.config.manager import ConfigManager
from lib.proxy import ProxyHelper


def bootstrapProxy(configManager: ConfigManager) -> None:
    """Initialise the global ``ProxyHelper`` singleton from config.

    Must be called AFTER ``ConfigManager`` is constructed and BEFORE any
    proxy-consuming service is built (``LLMManager(...)``, ``Database(...)``
    with the sqlink backend, ``ProviderClass(...)``, ``httpx.AsyncClient(...)``
    using ``ProxyConfig.toKwargs()``). The call is idempotent: subsequent
    calls just overwrite the stored global config (the underlying
    ``setGlobalProxyConfig`` is a plain attribute assignment, not init-guarded),
    so re-running a script that calls this multiple times is safe.

    Args:
        configManager: The initialised ``ConfigManager`` whose ``[proxy]``
            section will seed the global proxy config.

    Returns:
        None; this call is invoked for its side effect on the
        ``ProxyHelper`` singleton.
    """
    ProxyHelper.getInstance().setGlobalProxyConfig(configManager.getProxyConfig())
