"""Load and parse script definitions from pyproject.toml."""

from __future__ import annotations

import tomllib
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class ScriptDef:
    """Normalized representation of a script definition."""

    name: str
    commands: list[str]
    env: dict[str, str] = field(default_factory=dict)
    help_text: str = ""
    is_composite: bool = False


@dataclass
class UvsConfig:
    """Top-level configuration from [tool.uvs]."""

    scripts: dict[str, ScriptDef]
    editable: list[str] = field(default_factory=list)


class ConfigError(Exception):
    """Raised when pyproject.toml is missing or malformed."""


def find_pyproject(start: Path | None = None) -> Path:
    """Walk up from start (default: cwd) to find pyproject.toml."""
    current = start or Path.cwd()
    for directory in [current, *current.parents]:
        candidate = directory / "pyproject.toml"
        if candidate.is_file():
            return candidate
    raise ConfigError("No pyproject.toml found in current directory or any parent")


def load_config(pyproject_path: Path | None = None) -> UvsConfig:
    """Load the full [tool.uvs] configuration.

    Paths in 'editable' are resolved relative to the pyproject.toml directory.
    """
    path = pyproject_path or find_pyproject()
    project_dir = path.parent

    with path.open("rb") as f:
        data = tomllib.load(f)

    uvs_table = data.get("tool", {}).get("uvs", {})
    scripts_table = uvs_table.get("scripts", {})
    if not scripts_table:
        raise ConfigError(f"No [tool.uvs.scripts] section found in {path}")

    scripts: dict[str, ScriptDef] = {}
    for name, value in scripts_table.items():
        scripts[name] = _parse_script(name, value)

    raw_editable = uvs_table.get("editable", [])
    if not isinstance(raw_editable, list):
        raise ConfigError("'editable' must be an array of path strings")
    editable: list[str] = []
    for entry in raw_editable:
        if not isinstance(entry, str):
            raise ConfigError(f"'editable' items must be strings, got: {entry!r}")
        editable.append(str((project_dir / entry).resolve()))

    return UvsConfig(scripts=scripts, editable=editable)


def _parse_script(name: str, value: str | list | dict) -> ScriptDef:
    """Parse a single script value into a ScriptDef."""
    if isinstance(value, str):
        return ScriptDef(name=name, commands=[value])

    if isinstance(value, list):
        if not all(isinstance(v, str) for v in value):
            raise ConfigError(f"Script '{name}': array items must all be strings")
        return ScriptDef(name=name, commands=value, is_composite=True)

    if isinstance(value, dict):
        cmd = value.get("cmd")
        if not cmd or not isinstance(cmd, str):
            raise ConfigError(f"Script '{name}': table form requires a 'cmd' string")
        env = value.get("env", {})
        if not isinstance(env, dict):
            raise ConfigError(f"Script '{name}': 'env' must be a table of strings")
        help_text = value.get("help", "")
        return ScriptDef(
            name=name,
            commands=[cmd],
            env={str(k): str(v) for k, v in env.items()},
            help_text=help_text,
        )

    raise ConfigError(f"Script '{name}': value must be a string, array, or table")
