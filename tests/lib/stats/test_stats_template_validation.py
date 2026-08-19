"""Test for stats.toml default template validation.

Ensures the shipped default generate-command template in configs/00-defaults/stats.toml
parses correctly under the CLI's argparse (no unrecognized args after placeholder
substitution). This is a regression test for the seam bug where the template had
--user-id/--chat-id/--platform flags that the CLI didn't accept.
"""

import argparse
from pathlib import Path

# Compute repo root at module top for portability
# tests/lib/stats/test_stats_template_validation.py → parents[3] = repo root
repoRoot = Path(__file__).resolve().parents[3]


class TestStatsTemplateValidation:
    """Test stats.toml default template validation."""

    def test_default_generate_command_template_parses_correctly(self) -> None:
        """Test that the shipped default generate-command template parses correctly.

        Reads configs/00-defaults/stats.toml, extracts the generate-command,
        strips placeholder substitutions, and validates it against the CLI's
        argparse setup. The CLI only accepts --base-url and --output-dir for
        the generate subcommand; other flags cause SystemExit.

        This is a regression test for the seam bug where the template had
        --user-id/--chat-id/--platform flags that the CLI doesn't accept
        (the CLI reads these values from the stdin JSON payload).
        """
        # Read the default stats config
        statsConfigPath = repoRoot / "configs" / "00-defaults" / "stats.toml"
        assert statsConfigPath.exists(), f"Config not found: {statsConfigPath}"

        import tomli  # tomllib is Python 3.11+, tomli is the backport

        with statsConfigPath.open("rb") as f:
            config = tomli.load(f)

        # Extract generate-command from [stats.pages]
        statsPagesConfig = config.get("stats", {}).get("pages", {})
        generateCommand = statsPagesConfig.get("generate-command")

        assert generateCommand is not None, "[stats.pages] generate-command not found in config"
        assert isinstance(generateCommand, list), "generate-command must be a list"

        # Strip placeholder substitutions (simulating what StatsHandler does)
        # Placeholders are: {user_id}, {chat_id}, {platform}
        placeholders = {"user_id": "123", "chat_id": "456", "platform": "telegram"}

        resolvedArgv = []
        for arg in generateCommand:
            try:
                resolvedArg = arg.format_map(placeholders)
            except (KeyError, AttributeError):
                # If an arg doesn't have placeholders, keep it as-is
                resolvedArg = arg
            resolvedArgv.append(resolvedArg)

        # Extract only the subcommand and its arguments (skip Python invocation)
        # The template is: ["./venv/bin/python3", "-m", "lib.stats.stats_pages", "generate"]
        # We want: ["generate"]
        try:
            pythonIndex = resolvedArgv.index("python3")
            # Find "-m" and skip the module name after it
            if "-m" in resolvedArgv:
                dashMIndex = resolvedArgv.index("-m")
                cliArgs = resolvedArgv[dashMIndex + 2:]  # Skip "-m", "lib.stats.stats_pages"
            else:
                cliArgs = resolvedArgv[pythonIndex + 1:]
        except ValueError:
            # Fallback: skip the first 3 elements (python, -m, module)
            cliArgs = resolvedArgv[3:]

        # Now build the same argparse setup as generator.py::main()
        # and parse the resolved argv
        parser = argparse.ArgumentParser(
            description="Generate and delete statistics pages for Gromozeka.",
            prog="python -m lib.stats.stats_pages",
        )

        subparsers = parser.add_subparsers(dest="command", required=True, help="Command to execute")

        # Generate command (must match generator.py)
        generateParser = subparsers.add_parser("generate", help="Generate a statistics page from stdin JSON")
        generateParser.add_argument(
            "--base-url",
            dest="baseUrl",
            help="Base URL for constructing full URLs (e.g., https://example.com/pages)",
            default=None,
            type=str,
        )
        generateParser.add_argument(
            "--output-dir",
            dest="outputDir",
            help="Output directory for generated HTML files",
            default=".",
            type=str,
        )

        # Delete command
        deleteParser = subparsers.add_parser("delete", help="Delete a statistics page by ID")
        deleteParser.add_argument(
            "pageId",
            help="Page ID (UUID filename stem)",
            type=str,
        )
        deleteParser.add_argument(
            "--output-dir",
            dest="outputDir",
            help="Directory containing the page files",
            default=".",
            type=str,
        )

        # Parse the resolved argv
        # If this raises SystemExit, the template has unrecognized arguments
        try:
            args = parser.parse_args(cliArgs)
            assert args.command == "generate", f"Expected 'generate' command, got '{args.command}'"
        except SystemExit as e:
            # SystemExit with code 2 means argparse error (unrecognized args)
            if e.code == 2:
                raise AssertionError(
                    f"Default generate-command template has unrecognized arguments. "
                    f"Template: {generateCommand}. "
                    f"Resolved: {resolvedArgv}. "
                    f"CLI only accepts --base-url and --output-dir for generate command."
                )
            else:
                raise

    def test_default_delete_command_template_parses_correctly(self) -> None:
        """Test that the shipped default delete-command template parses correctly."""
        # Read the default stats config
        statsConfigPath = repoRoot / "configs" / "00-defaults" / "stats.toml"
        assert statsConfigPath.exists(), f"Config not found: {statsConfigPath}"

        import tomli

        with statsConfigPath.open("rb") as f:
            config = tomli.load(f)

        # Extract delete-command from [stats.pages]
        statsPagesConfig = config.get("stats", {}).get("pages", {})
        deleteCommand = statsPagesConfig.get("delete-command")

        assert deleteCommand is not None, "[stats.pages] delete-command not found in config"
        assert isinstance(deleteCommand, list), "delete-command must be a list"

        # Strip placeholder substitutions (page_id is the only placeholder)
        placeholders = {"page_id": "some-uuid-1234567890abcdef"}

        resolvedArgv = []
        for arg in deleteCommand:
            try:
                resolvedArg = arg.format_map(placeholders)
            except (KeyError, AttributeError):
                resolvedArg = arg
            resolvedArgv.append(resolvedArg)

        # Extract only the subcommand and its arguments (skip Python invocation)
        try:
            dashMIndex = resolvedArgv.index("-m")
            cliArgs = resolvedArgv[dashMIndex + 2:]  # Skip "-m", "lib.stats.stats_pages"
        except ValueError:
            cliArgs = resolvedArgv[3:]  # Fallback: skip first 3 elements

        # Build argparse setup (same as above)
        parser = argparse.ArgumentParser(
            description="Generate and delete statistics pages for Gromozeka.",
            prog="python -m lib.stats.stats_pages",
        )

        subparsers = parser.add_subparsers(dest="command", required=True, help="Command to execute")

        # Generate command
        generateParser = subparsers.add_parser("generate", help="Generate a statistics page from stdin JSON")
        generateParser.add_argument("--base-url", dest="baseUrl", default=None, type=str)
        generateParser.add_argument("--output-dir", dest="outputDir", default=".", type=str)

        # Delete command
        deleteParser = subparsers.add_parser("delete", help="Delete a statistics page by ID")
        deleteParser.add_argument("pageId", help="Page ID (UUID filename stem)", type=str)
        deleteParser.add_argument("--output-dir", dest="outputDir", default=".", type=str)

        # Parse the resolved argv
        try:
            args = parser.parse_args(cliArgs)
            assert args.command == "delete", f"Expected 'delete' command, got '{args.command}'"
            assert args.pageId == "some-uuid-1234567890abcdef", "pageId placeholder not substituted"
        except SystemExit as e:
            if e.code == 2:
                raise AssertionError(
                    f"Default delete-command template has unrecognized arguments. "
                    f"Template: {deleteCommand}. "
                    f"Resolved: {resolvedArgv}."
                )
            else:
                raise
