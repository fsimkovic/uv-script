"""CLI entry point for uvs."""

from __future__ import annotations

import argparse
import sys

from uv_script import __version__
from uv_script.config import ConfigError, ScriptDef, load_config
from uv_script.runner import run_script


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        prog="uvs",
        description="Run scripts defined in [tool.uvs.scripts] via uv run",
    )
    parser.add_argument(
        "-V",
        "--version",
        action="version",
        version=f"%(prog)s {__version__}",
    )
    parser.add_argument(
        "-l",
        "--list",
        action="store_true",
        help="List available scripts",
    )
    parser.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="Print commands before executing",
    )
    parser.add_argument(
        "--no-editable",
        action="store_true",
        help="Ignore editable installs from config",
    )
    parser.add_argument(
        "script",
        nargs="?",
        metavar="SCRIPT",
        help="Name of the script to run",
    )
    parser.add_argument(
        "args",
        nargs=argparse.REMAINDER,
        metavar="...",
        help="Additional arguments passed to the script",
    )

    parsed = parser.parse_args(argv)

    try:
        config = load_config()
    except ConfigError as e:
        print(f"uvs: {e}", file=sys.stderr)
        sys.exit(1)

    scripts = config.scripts

    if parsed.list:
        _print_list(scripts)
        return

    if not parsed.script:
        parser.print_help()
        sys.exit(1)

    if parsed.script not in scripts:
        print(f"uvs: unknown script '{parsed.script}'", file=sys.stderr)
        print(f"Available scripts: {', '.join(sorted(scripts))}", file=sys.stderr)
        sys.exit(1)

    script = scripts[parsed.script]

    extra_args = parsed.args
    if extra_args and extra_args[0] == "--":
        extra_args = extra_args[1:]

    editable = None if parsed.no_editable else (config.editable or None)

    exit_code = run_script(
        script,
        all_scripts=scripts,
        extra_args=extra_args or None,
        verbose=parsed.verbose,
        editable=editable,
    )
    sys.exit(exit_code)


def _print_list(scripts: dict[str, ScriptDef]) -> None:
    if not scripts:
        print("No scripts defined.")
        return

    max_name = max(len(name) for name in scripts)

    for name in sorted(scripts):
        script = scripts[name]
        help_text = script.help_text
        if not help_text:
            help_text = (
                " -> ".join(script.commands) if script.is_composite else script.commands[0]
            )

        print(f"  {name:<{max_name}}  {help_text}")
