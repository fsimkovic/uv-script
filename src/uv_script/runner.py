"""Execute scripts by delegating to uv run."""

from __future__ import annotations

import contextlib
import os
import shlex
import subprocess
import sys
import tempfile

from uv_script.config import ConfigError, ScriptDef


def run_script(
    script: ScriptDef,
    all_scripts: dict[str, ScriptDef],
    extra_args: list[str] | None = None,
    verbose: bool = False,
    editable: list[str] | None = None,
    features: list[str] | None = None,
) -> int:
    """Execute a script definition. Returns exit code (0 = success)."""
    steps = resolve_steps(script, all_scripts)

    find_links: str | None = None

    with (
        tempfile.TemporaryDirectory(prefix="uvs-") if editable else contextlib.nullcontext()
    ) as tmp_dir:
        if editable and tmp_dir:
            try:
                _build_editables(editable, tmp_dir)
            except subprocess.CalledProcessError as exc:
                print(
                    f"uvs: failed to build editable: {exc.stderr}",
                    file=sys.stderr,
                )
                return 1
            find_links = tmp_dir

        for i, (cmd_str, env) in enumerate(steps):
            if extra_args and i == len(steps) - 1:
                cmd_str = cmd_str + " " + " ".join(shlex.quote(a) for a in extra_args)

            exit_code = _exec_one(
                cmd_str, env, verbose,
                editable=editable, features=features, find_links=find_links,
            )
            if exit_code != 0:
                return exit_code

    return 0


def resolve_steps(
    script: ScriptDef,
    all_scripts: dict[str, ScriptDef],
    _seen: set[str] | None = None,
) -> list[tuple[str, dict[str, str]]]:
    """Resolve a script into a flat list of (command, env) pairs.

    Handles references to other scripts and detects cycles.
    """
    if _seen is None:
        _seen = set()

    if script.name in _seen:
        raise ConfigError(f"Circular reference detected: {script.name}")
    _seen.add(script.name)

    if not script.is_composite:
        return [(cmd, script.env) for cmd in script.commands]

    result: list[tuple[str, dict[str, str]]] = []
    for item in script.commands:
        if item in all_scripts:
            referenced = all_scripts[item]
            result.extend(resolve_steps(referenced, all_scripts, _seen.copy()))
        else:
            result.append((item, script.env))

    return result


def _build_editables(editable: list[str], build_dir: str) -> None:
    """Build a wheel for each editable package into build_dir.

    Raises subprocess.CalledProcessError if any build fails.
    """
    for path in editable:
        subprocess.run(
            ["uv", "build", "--wheel", "--out-dir", build_dir, path],
            check=True,
            capture_output=True,
            text=True,
        )


def _exec_one(
    cmd_str: str,
    env: dict[str, str],
    verbose: bool,
    editable: list[str] | None = None,
    features: list[str] | None = None,
    find_links: str | None = None,
) -> int:
    """Execute a single command string via uv run."""
    parts = shlex.split(cmd_str)
    find_links_flags: list[str] = []
    if find_links:
        find_links_flags.extend(["--find-links", find_links])
    editable_flags: list[str] = []
    for path in editable or []:
        editable_flags.extend(["--with-editable", path])
    features_flags: list[str] = []
    for name in features or []:
        features_flags.extend(["--extra", name])
    full_cmd = ["uv", "run"] + find_links_flags + editable_flags + features_flags + parts

    if verbose:
        env_prefix = " ".join(f"{k}={shlex.quote(v)}" for k, v in env.items())
        display = f"{env_prefix} {' '.join(full_cmd)}".strip()
        print(f"$ {display}", file=sys.stderr)

    run_env = None
    if env:
        run_env = {**os.environ, **env}

    result = subprocess.run(full_cmd, env=run_env)
    return result.returncode
