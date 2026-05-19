"""Sandbox handler for Gromozeka bot.

This module provides the SandboxHandler class which implements sandboxed code
execution functionality via slash commands. The handler integrates with the
lib.sandbox library to execute Python code in isolated Docker containers.

Commands implemented:
- /run <code>: Execute Python code in sandbox
- /sandbox files [path]: List files in sandbox workspace
- /sandbox read <path>: Read a file from sandbox workspace
- /sandbox status: Show sandbox session status
- /sandbox install <packages...>: Install Python packages (admin only)

Per-chat gating is supported via the `allow-sandbox` chat setting.
"""

import logging
from typing import Optional

from internal.bot.common.models import UpdateObjectType
from internal.bot.common.typing_manager import TypingManager
from internal.bot.models import (
    BotProvider,
    ChatSettingsKey,
    CommandCategory,
    CommandHandlerOrder,
    CommandPermission,
    EnsuredMessage,
    commandHandlerV2,
)
from internal.config.manager import ConfigManager
from internal.database import Database
from internal.database.models import MessageCategory
from lib.sandbox import (
    InvalidPackageSpec,
    PathOutsideWorkspace,
    RuntimeName,
    SandboxBusy,
    SandboxConfig,
    SandboxManager,
    SessionBusy,
    SessionNotFound,
)

from .base import BaseBotHandler, HandlerResultStatus

logger = logging.getLogger(__name__)


class SandboxHandler(BaseBotHandler):
    """Sandboxed code execution handler for Gromozeka bot.

    Provides commands for executing Python code in isolated Docker containers,
    managing workspace files, and installing Python packages. All operations
    are scoped per-chat via session IDs derived from chat IDs.

    Attributes:
        sandboxEnabled: Whether sandbox functionality is enabled (config section exists).
    """

    def __init__(self, *, configManager: ConfigManager, database: Database, botProvider: BotProvider) -> None:
        """Initialize the sandbox handler.

        Args:
            configManager: Configuration manager instance.
            database: Database wrapper instance.
            botProvider: Bot provider type (Telegram/Max).
        """
        super().__init__(configManager=configManager, database=database, botProvider=botProvider)

        # Inject sandbox config into SandboxManager singleton if present
        sandboxRaw = self.configManager.get("sandbox")
        if sandboxRaw:
            try:
                sandboxConfig = SandboxConfig.fromDict(sandboxRaw)
                SandboxManager.injectConfig(sandboxConfig)
                self.sandboxEnabled = True
                logger.info("Sandbox config injected successfully")
            except Exception as e:
                logger.error(f"Failed to parse sandbox config: {e}")
                self.sandboxEnabled = False
        else:
            logger.error("Sandbox config section not found — sandbox commands will not work")
            self.sandboxEnabled = False

    def getSessionId(self, ensuredMessage:EnsuredMessage) -> str:
        return f"chat#{ensuredMessage.recipient.id}"


    @commandHandlerV2(
        commands=("run", "python"),
        shortDescription="<code> - Execute Python code in sandbox",
        helpMessage=" <код>: Выполняет Python код в изолированной песочнице.\n"
        "Использование: /run <код> или /run в ответ на сообщение с кодом.",
        visibility={CommandPermission.PRIVATE},
        availableFor={CommandPermission.DEFAULT},
        helpOrder=CommandHandlerOrder.NORMAL,
        category=CommandCategory.TOOLS,
    )
    async def run_command(
        self,
        ensuredMessage: EnsuredMessage,
        command: str,
        args: str,
        updateObj: UpdateObjectType,
        typingManager: Optional[TypingManager],
    ) -> None:
        """Handle the /run command to execute Python code.

        Executes the provided code in a sandboxed Docker container. Code can be
        provided as command arguments or from a replied-to message.

        Args:
            ensuredMessage: The ensured message object containing message context.
            command: The command that was triggered (e.g., "run").
            args: Additional arguments passed with the command (the code to execute).
            updateObj: The update object from the messaging platform.
            typingManager: Optional typing manager for showing typing indicators.

        Returns:
            None

        Note:
            The session ID is derived from the chat ID, ensuring per-chat isolation.
            Output is truncated at approximately 3000 characters to avoid hitting
            message size limits.
        """
        if not self.sandboxEnabled:
            await self.sendMessage(
                ensuredMessage,
                messageText="Sandbox is not configured.",
                messageCategory=MessageCategory.BOT_ERROR,
            )
            return

        # Extract code from args or replied-to message
        code = args.strip() if args else ""
        if not code and ensuredMessage.replyText:
            if ensuredMessage.quoteText:
                code = ensuredMessage.quoteText
            else:
                code = ensuredMessage.replyText

        code = code.strip()
        if not code:
            await self.sendMessage(
                ensuredMessage,
                messageText="Usage: /run <code> or /run in reply to a message with code",
                messageCategory=MessageCategory.BOT_ERROR,
            )
            return

        manager = SandboxManager.getInstance()
        sessionId = self.getSessionId(ensuredMessage)

        try:
            result = await manager.runCode(sessionId=sessionId, code=code, runtime=RuntimeName.PYTHON)

            # Format response
            lines = [f"Exit code: {result.exitCode}"]

            if result.stdoutBytes > 0:
                lines.append("Stdout:")
                lines.append("```")

            # Build output message with truncation
            outputLines = []
            maxLength = 3000
            currentLength = 0

            for line in lines:
                if currentLength + len(line) + 1 > maxLength:
                    break
                outputLines.append(line)
                currentLength += len(line) + 1

            # Add actual output from result
            if result.stdoutBytes > 0:
                try:
                    # Read stdout file
                    stdoutContent = await manager.readFile(sessionId, result.stdoutPath)
                    stdoutText = (
                        stdoutContent.content if isinstance(stdoutContent.content, str) else str(stdoutContent.content)
                    )
                    truncateMarker = "..." if stdoutContent.truncated else ""
                    stdoutSnippet = stdoutText[: maxLength - currentLength - len(truncateMarker)] + truncateMarker
                    outputLines.append(stdoutSnippet)
                    currentLength += len(stdoutSnippet) + 1  # +1 for newline
                except Exception as e:
                    logger.error(f"Failed to read stdout: {e}")
                    outputLines.append("[Failed to read output]")

            outputLines.append("```")
            currentLength += 4  # +1 for newline, +3 for "```"

            if result.stderrBytes > 0:
                outputLines.append("Stderr:")
                outputLines.append("```")
                try:
                    # Read stderr file
                    stderrContent = await manager.readFile(sessionId, result.stderrPath)
                    stderrText = (
                        stderrContent.content if isinstance(stderrContent.content, str) else str(stderrContent.content)
                    )
                    truncateMarker = "..." if stderrContent.truncated else ""
                    outputLines.append(stderrText[: maxLength - currentLength - len(truncateMarker)] + truncateMarker)
                except Exception as e:
                    logger.error(f"Failed to read stderr: {e}")
                    outputLines.append("[Failed to read stderr]")
                outputLines.append("```")

            if result.error:
                outputLines.append(f"Error: {result.error}")

            response = "\n".join(outputLines)

            await self.sendMessage(
                ensuredMessage,
                messageText=response,
                messageCategory=MessageCategory.BOT_COMMAND_REPLY,
                typingManager=typingManager,
            )

        except SessionBusy:
            await self.sendMessage(
                ensuredMessage,
                messageText="Session is busy, try again later",
                messageCategory=MessageCategory.BOT_ERROR,
            )
        except SandboxBusy:
            await self.sendMessage(
                ensuredMessage,
                messageText="All sandbox workers are busy, try again later",
                messageCategory=MessageCategory.BOT_ERROR,
            )
        except Exception as e:
            logger.error(f"Error running code: {e}")
            await self.sendMessage(
                ensuredMessage,
                messageText=f"Error: {e}",
                messageCategory=MessageCategory.BOT_ERROR,
            )

    @commandHandlerV2(
        commands=("sandbox",),
        shortDescription="Sandbox file management commands",
        helpMessage=" <files|read|status|install> [args]: Manage sandbox workspace files.",
        visibility={CommandPermission.PRIVATE},
        availableFor={CommandPermission.DEFAULT},
        helpOrder=CommandHandlerOrder.NORMAL,
        category=CommandCategory.TOOLS,
    )
    async def sandbox_command(
        self,
        ensuredMessage: EnsuredMessage,
        command: str,
        args: str,
        updateObj: UpdateObjectType,
        typingManager: Optional[TypingManager],
    ) -> None:
        """Handle the /sandbox command as a dispatcher for subcommands.

        Routes to the appropriate subcommand handler based on the first argument.

        Args:
            ensuredMessage: The ensured message object containing message context.
            command: The command that was triggered (e.g., "sandbox").
            args: Additional arguments passed with the command.
            updateObj: The update object from the messaging platform.
            typingManager: Optional typing manager for showing typing indicators.

        Returns:
            None
        """
        if not self.sandboxEnabled:
            await self.sendMessage(
                ensuredMessage,
                messageText="Sandbox is not configured.",
                messageCategory=MessageCategory.BOT_ERROR,
            )
            return

        argsList = args.strip().split(maxsplit=1)
        if not argsList or not argsList[0]:
            await self.sendMessage(
                ensuredMessage,
                messageText=(
                    "Usage: /sandbox <subcommand> [args]\n"
                    "Subcommands:\n"
                    "  files [path] - List files in workspace (default: root)\n"
                    "  read <path> - Read a file from workspace\n"
                    "  status - Show sandbox session status\n"
                    "  install <packages...> - Install Python packages (admin only)"
                ),
                messageCategory=MessageCategory.BOT_ERROR,
            )
            return

        subcommand = argsList[0].lower()
        subArgs = argsList[1] if len(argsList) > 1 else ""

        sessionId = self.getSessionId(ensuredMessage)
        manager = SandboxManager.getInstance()

        if subcommand == "files":
            await self._handleFilesCommand(ensuredMessage, sessionId, subArgs, manager, typingManager)
        elif subcommand == "read":
            await self._handleReadCommand(ensuredMessage, sessionId, subArgs, manager, typingManager)
        elif subcommand == "status":
            await self._handleStatusCommand(ensuredMessage, sessionId, manager, typingManager)
        elif subcommand == "install":
            await self._handleInstallCommand(ensuredMessage, sessionId, subArgs, manager, typingManager)
        else:
            await self.sendMessage(
                ensuredMessage,
                messageText=f"Unknown subcommand: {subcommand}",
                messageCategory=MessageCategory.BOT_ERROR,
            )

    async def _handleFilesCommand(
        self,
        ensuredMessage: EnsuredMessage,
        sessionId: str,
        path: str,
        manager: SandboxManager,
        typingManager: Optional[TypingManager],
    ) -> None:
        """Handle the 'files' subcommand to list workspace files.

        Args:
            ensuredMessage: The ensured message object containing message context.
            sessionId: The sandbox session ID (derived from chat ID).
            path: The path to list files from (empty for root).
            manager: The SandboxManager instance.
            typingManager: Optional typing manager for showing typing indicators.

        Returns:
            None
        """
        listPath = path if path.strip() else "/"

        try:
            files = await manager.listFiles(sessionId, path=listPath)

            if not files:
                await self.sendMessage(
                    ensuredMessage,
                    messageText=f"No files found in {listPath}",
                    messageCategory=MessageCategory.BOT_COMMAND_REPLY,
                    typingManager=typingManager,
                )
                return

            # Format files as list with indicators
            lines = [f"Files in {listPath}:"]
            for file in files:
                if file.isDirectory:
                    lines.append(f"  [DIR]  {file.path}/")
                else:
                    sizeKb = file.sizeBytes / 1024
                    lines.append(f"  [FILE] {file.path} ({sizeKb:.1f} KB)")

            response = "\n".join(lines)
            await self.sendMessage(
                ensuredMessage,
                messageText=response,
                messageCategory=MessageCategory.BOT_COMMAND_REPLY,
                typingManager=typingManager,
            )

        except SessionNotFound:
            await self.sendMessage(
                ensuredMessage,
                messageText="No active sandbox session. Run /run <code> to create one.",
                messageCategory=MessageCategory.BOT_ERROR,
            )
        except PathOutsideWorkspace:
            await self.sendMessage(
                ensuredMessage,
                messageText="Access denied: path outside workspace",
                messageCategory=MessageCategory.BOT_ERROR,
            )
        except Exception as e:
            logger.error(f"Error listing files: {e}")
            await self.sendMessage(
                ensuredMessage,
                messageText=f"Error: {e}",
                messageCategory=MessageCategory.BOT_ERROR,
            )

    async def _handleReadCommand(
        self,
        ensuredMessage: EnsuredMessage,
        sessionId: str,
        path: str,
        manager: SandboxManager,
        typingManager: Optional[TypingManager],
    ) -> None:
        """Handle the 'read' subcommand to read a file from workspace.

        Args:
            ensuredMessage: The ensured message object containing message context.
            sessionId: The sandbox session ID (derived from chat ID).
            path: The path to the file to read.
            manager: The SandboxManager instance.
            typingManager: Optional typing manager for showing typing indicators.

        Returns:
            None
        """
        if not path.strip():
            await self.sendMessage(
                ensuredMessage,
                messageText="Usage: /sandbox read <path>",
                messageCategory=MessageCategory.BOT_ERROR,
            )
            return

        try:
            fileContent = await manager.readFile(sessionId, path=path, maxBytes=3000, encoding="utf-8")

            lines = [
                f"File: {path}",
                f"Size: {fileContent.sizeBytes} bytes",
                "```",
            ]

            if isinstance(fileContent.content, str):
                lines.append(fileContent.content)
            else:
                lines.append(str(fileContent.content))

            if fileContent.truncated:
                lines.append("...")
                lines.append(f"[Truncated at {fileContent.bytesRead} bytes]")

            lines.append("```")

            response = "\n".join(lines)
            await self.sendMessage(
                ensuredMessage,
                messageText=response,
                messageCategory=MessageCategory.BOT_COMMAND_REPLY,
                typingManager=typingManager,
            )

        except SessionNotFound:
            await self.sendMessage(
                ensuredMessage,
                messageText="No active sandbox session. Run /run <code> to create one.",
                messageCategory=MessageCategory.BOT_ERROR,
            )
        except PathOutsideWorkspace:
            await self.sendMessage(
                ensuredMessage,
                messageText="Access denied: path outside workspace",
                messageCategory=MessageCategory.BOT_ERROR,
            )
        except FileNotFoundError:
            await self.sendMessage(
                ensuredMessage,
                messageText=f"File not found: {path}",
                messageCategory=MessageCategory.BOT_ERROR,
            )
        except Exception as e:
            logger.error(f"Error reading file: {e}")
            await self.sendMessage(
                ensuredMessage,
                messageText=f"Error: {e}",
                messageCategory=MessageCategory.BOT_ERROR,
            )

    async def _handleStatusCommand(
        self,
        ensuredMessage: EnsuredMessage,
        sessionId: str,
        manager: SandboxManager,
        typingManager: Optional[TypingManager],
    ) -> None:
        """Handle the 'status' subcommand to show sandbox session status.

        Args:
            ensuredMessage: The ensured message object containing message context.
            sessionId: The sandbox session ID (derived from chat ID).
            manager: The SandboxManager instance.
            typingManager: Optional typing manager for showing typing indicators.

        Returns:
            None
        """
        try:
            # Check if session exists by trying to list runs
            runs = await manager.listRunsForSession(sessionId)

            if not runs:
                await self.sendMessage(
                    ensuredMessage,
                    messageText="No active sandbox session. Run /run <code> to create one.",
                    messageCategory=MessageCategory.BOT_COMMAND_REPLY,
                    typingManager=typingManager,
                )
                return

            # Session exists, build status
            lastRun = runs[-1] if runs else None

            lines = [
                f"Sandbox session: {sessionId}",
                f"Total runs: {len(runs)}",
            ]

            if lastRun:
                lines.append(f"Last run status: {lastRun.status.value}")
                lines.append(f"Last run runtime: {lastRun.runtime.value}")
                if lastRun.exitCode is not None:
                    lines.append(f"Last run exit code: {lastRun.exitCode}")

            response = "\n".join(lines)
            await self.sendMessage(
                ensuredMessage,
                messageText=response,
                messageCategory=MessageCategory.BOT_COMMAND_REPLY,
                typingManager=typingManager,
            )

        except SessionNotFound:
            await self.sendMessage(
                ensuredMessage,
                messageText="No active sandbox session. Run /run <code> to create one.",
                messageCategory=MessageCategory.BOT_COMMAND_REPLY,
                typingManager=typingManager,
            )
        except Exception as e:
            logger.error(f"Error getting status: {e}")
            await self.sendMessage(
                ensuredMessage,
                messageText=f"Error: {e}",
                messageCategory=MessageCategory.BOT_ERROR,
            )

    async def _handleInstallCommand(
        self,
        ensuredMessage: EnsuredMessage,
        sessionId: str,
        packagesArg: str,
        manager: SandboxManager,
        typingManager: Optional[TypingManager],
    ) -> None:
        """Handle the 'install' subcommand to install Python packages (admin only).

        Args:
            ensuredMessage: The ensured message object containing message context.
            sessionId: The sandbox session ID (derived from chat ID).
            packagesArg: Space-separated list of package names to install.
            manager: The SandboxManager instance.
            typingManager: Optional typing manager for showing typing indicators.

        Returns:
            None

        Note:
            This command is restricted to bot owners only.
        """
        # Check if user is bot owner
        if not self.isBotOwner(ensuredMessage.sender):
            await self.sendMessage(
                ensuredMessage,
                messageText="This command is restricted to bot owners only.",
                messageCategory=MessageCategory.BOT_ERROR,
            )
            return

        if not packagesArg.strip():
            await self.sendMessage(
                ensuredMessage,
                messageText="Usage: /sandbox install <packages...>",
                messageCategory=MessageCategory.BOT_ERROR,
            )
            return

        packages = packagesArg.strip().split()

        try:
            await self.sendMessage(
                ensuredMessage,
                messageText=f"Installing packages: {', '.join(packages)}",
                messageCategory=MessageCategory.BOT_COMMAND_REPLY,
                typingManager=typingManager,
            )

            success = await manager.installRuntimeLibraries(packages=packages, runtime=RuntimeName.PYTHON)

            if success:
                await self.sendMessage(
                    ensuredMessage,
                    messageText="Done. Packages installed successfully.",
                    messageCategory=MessageCategory.BOT_COMMAND_REPLY,
                    typingManager=typingManager,
                )
            else:
                await self.sendMessage(
                    ensuredMessage,
                    messageText="Failed to install packages. Check logs for details.",
                    messageCategory=MessageCategory.BOT_ERROR,
                )

        except InvalidPackageSpec as e:
            await self.sendMessage(
                ensuredMessage,
                messageText=f"Invalid package spec: {e}",
                messageCategory=MessageCategory.BOT_ERROR,
            )
        except Exception as e:
            logger.error(f"Error installing packages: {e}")
            await self.sendMessage(
                ensuredMessage,
                messageText=f"Error: {e}",
                messageCategory=MessageCategory.BOT_ERROR,
            )
