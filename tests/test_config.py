"""Tests for uv_script.config."""

import pytest

from uv_script.config import ConfigError, ScriptDef, UvsConfig, _parse_script, find_pyproject, load_config


class TestParseScript:
    def test_simple_string(self):
        result = _parse_script("test", "pytest tests/")
        assert result == ScriptDef(name="test", commands=["pytest tests/"])
        assert not result.is_composite

    def test_array_of_strings(self):
        result = _parse_script("check", ["lint", "test"])
        assert result == ScriptDef(name="check", commands=["lint", "test"], is_composite=True)
        assert result.is_composite

    def test_table_with_cmd(self):
        result = _parse_script("serve", {"cmd": "flask run", "env": {"PORT": "8080"}, "help": "Run server"})
        assert result.name == "serve"
        assert result.commands == ["flask run"]
        assert result.env == {"PORT": "8080"}
        assert result.help_text == "Run server"
        assert not result.is_composite

    def test_table_minimal(self):
        result = _parse_script("serve", {"cmd": "flask run"})
        assert result.env == {}
        assert result.help_text == ""

    def test_table_missing_cmd_raises(self):
        with pytest.raises(ConfigError, match="requires a 'cmd' string"):
            _parse_script("bad", {"env": {"A": "1"}})

    def test_table_cmd_not_string_raises(self):
        with pytest.raises(ConfigError, match="requires a 'cmd' string"):
            _parse_script("bad", {"cmd": 123})

    def test_array_non_string_items_raises(self):
        with pytest.raises(ConfigError, match="array items must all be strings"):
            _parse_script("bad", ["lint", 123])

    def test_invalid_type_raises(self):
        with pytest.raises(ConfigError, match="must be a string, array, or table"):
            _parse_script("bad", 42)

    def test_env_values_cast_to_string(self):
        result = _parse_script("s", {"cmd": "echo", "env": {"PORT": 8080}})
        assert result.env == {"PORT": "8080"}


class TestFindPyproject:
    def test_finds_in_current_dir(self, tmp_path):
        (tmp_path / "pyproject.toml").write_text("[project]\nname = 'test'\n")
        result = find_pyproject(tmp_path)
        assert result == tmp_path / "pyproject.toml"

    def test_finds_in_parent_dir(self, tmp_path):
        (tmp_path / "pyproject.toml").write_text("[project]\nname = 'test'\n")
        child = tmp_path / "subdir"
        child.mkdir()
        result = find_pyproject(child)
        assert result == tmp_path / "pyproject.toml"

    def test_raises_when_not_found(self, tmp_path):
        empty = tmp_path / "empty"
        empty.mkdir()
        with pytest.raises(ConfigError, match="No pyproject.toml found"):
            find_pyproject(empty)


class TestLoadConfig:
    def test_loads_all_forms(self, tmp_path):
        toml = tmp_path / "pyproject.toml"
        toml.write_text(
            '[tool.uvs.scripts]\n'
            'test = "pytest"\n'
            'check = ["lint", "test"]\n'
            '\n'
            '[tool.uvs.scripts.serve]\n'
            'cmd = "flask run"\n'
            'help = "Run server"\n'
        )
        config = load_config(toml)
        assert isinstance(config, UvsConfig)
        scripts = config.scripts
        assert "test" in scripts
        assert "check" in scripts
        assert "serve" in scripts
        assert scripts["test"].commands == ["pytest"]
        assert scripts["check"].is_composite
        assert scripts["serve"].help_text == "Run server"

    def test_no_scripts_section_raises(self, tmp_path):
        toml = tmp_path / "pyproject.toml"
        toml.write_text("[project]\nname = 'test'\n")
        with pytest.raises(ConfigError, match="No \\[tool.uvs.scripts\\] section"):
            load_config(toml)

    def test_empty_scripts_section_raises(self, tmp_path):
        toml = tmp_path / "pyproject.toml"
        toml.write_text("[tool.uvs.scripts]\n")
        with pytest.raises(ConfigError, match="No \\[tool.uvs.scripts\\] section"):
            load_config(toml)

    def test_editable_paths_resolved_relative_to_pyproject(self, tmp_path):
        project = tmp_path / "project"
        project.mkdir()
        pkg1 = tmp_path / "pkg1"
        pkg1.mkdir()
        toml = project / "pyproject.toml"
        toml.write_text(
            '[tool.uvs]\n'
            'editable = ["../pkg1"]\n'
            '\n'
            '[tool.uvs.scripts]\n'
            'test = "pytest"\n'
        )
        config = load_config(toml)
        assert config.editable == [str(pkg1.resolve())]

    def test_no_editable_defaults_to_empty(self, tmp_path):
        toml = tmp_path / "pyproject.toml"
        toml.write_text('[tool.uvs.scripts]\ntest = "pytest"\n')
        config = load_config(toml)
        assert config.editable == []

    def test_editable_not_a_list_raises(self, tmp_path):
        toml = tmp_path / "pyproject.toml"
        toml.write_text(
            '[tool.uvs]\n'
            'editable = "../pkg1"\n'
            '\n'
            '[tool.uvs.scripts]\n'
            'test = "pytest"\n'
        )
        with pytest.raises(ConfigError, match="must be an array"):
            load_config(toml)

    def test_editable_non_string_item_raises(self, tmp_path):
        toml = tmp_path / "pyproject.toml"
        toml.write_text(
            '[tool.uvs]\n'
            'editable = [123]\n'
            '\n'
            '[tool.uvs.scripts]\n'
            'test = "pytest"\n'
        )
        with pytest.raises(ConfigError, match="must be strings"):
            load_config(toml)

