"""Tests for uv_script.runner."""

import subprocess
from unittest.mock import patch

import pytest

from uv_script.config import ConfigError, ScriptDef
from uv_script.runner import _build_editables, resolve_steps, run_script


@pytest.fixture
def simple_scripts():
    return {
        "lint": ScriptDef(name="lint", commands=["ruff check ."]),
        "test": ScriptDef(name="test", commands=["pytest tests/"]),
        "check": ScriptDef(name="check", commands=["lint", "test"], is_composite=True),
    }


class TestResolveSteps:
    def test_simple_script(self, simple_scripts):
        result = resolve_steps(simple_scripts["test"], simple_scripts)
        assert result == [("pytest tests/", {})]

    def test_composite_script(self, simple_scripts):
        result = resolve_steps(simple_scripts["check"], simple_scripts)
        assert [cmd for cmd, _ in result] == ["ruff check .", "pytest tests/"]

    def test_raw_command_in_composite(self):
        scripts = {
            "all": ScriptDef(name="all", commands=["echo hello", "lint"], is_composite=True),
            "lint": ScriptDef(name="lint", commands=["ruff check ."]),
        }
        result = resolve_steps(scripts["all"], scripts)
        assert [cmd for cmd, _ in result] == ["echo hello", "ruff check ."]

    def test_circular_reference_raises(self):
        scripts = {
            "a": ScriptDef(name="a", commands=["b"], is_composite=True),
            "b": ScriptDef(name="b", commands=["a"], is_composite=True),
        }
        with pytest.raises(ConfigError, match="Circular reference"):
            resolve_steps(scripts["a"], scripts)

    def test_nested_composite(self):
        scripts = {
            "lint": ScriptDef(name="lint", commands=["ruff check ."]),
            "test": ScriptDef(name="test", commands=["pytest"]),
            "check": ScriptDef(name="check", commands=["lint", "test"], is_composite=True),
            "all": ScriptDef(name="all", commands=["check"], is_composite=True),
        }
        result = resolve_steps(scripts["all"], scripts)
        assert [cmd for cmd, _ in result] == ["ruff check .", "pytest"]

    def test_env_propagated_from_referenced_script(self):
        scripts = {
            "serve": ScriptDef(
                name="serve", commands=["flask run"], env={"FLASK_DEBUG": "1"}
            ),
            "all": ScriptDef(name="all", commands=["serve"], is_composite=True),
        }
        result = resolve_steps(scripts["all"], scripts)
        assert result == [("flask run", {"FLASK_DEBUG": "1"})]

    def test_raw_command_gets_parent_env(self):
        scripts = {
            "dev": ScriptDef(
                name="dev",
                commands=["echo starting", "serve"],
                is_composite=True,
                env={"MODE": "dev"},
            ),
            "serve": ScriptDef(name="serve", commands=["flask run"]),
        }
        result = resolve_steps(scripts["dev"], scripts)
        assert result == [("echo starting", {"MODE": "dev"}), ("flask run", {})]


class TestBuildEditables:
    @patch("uv_script.runner.subprocess.run")
    def test_builds_each_editable(self, mock_run):
        _build_editables(["/pkg1", "/pkg2"], "/tmp/build")
        assert mock_run.call_count == 2
        mock_run.assert_any_call(
            ["uv", "build", "--wheel", "--out-dir", "/tmp/build", "/pkg1"],
            check=True, capture_output=True, text=True,
        )
        mock_run.assert_any_call(
            ["uv", "build", "--wheel", "--out-dir", "/tmp/build", "/pkg2"],
            check=True, capture_output=True, text=True,
        )

    @patch("uv_script.runner.subprocess.run")
    def test_raises_on_build_failure(self, mock_run):
        mock_run.side_effect = subprocess.CalledProcessError(
            1, "uv build", stderr="build error"
        )
        with pytest.raises(subprocess.CalledProcessError):
            _build_editables(["/pkg1"], "/tmp/build")


class TestRunScript:
    @patch("uv_script.runner.subprocess.run")
    def test_delegates_to_uv_run(self, mock_run, simple_scripts):
        mock_run.return_value.returncode = 0
        exit_code = run_script(simple_scripts["test"], simple_scripts)
        assert exit_code == 0
        mock_run.assert_called_once()
        call_args = mock_run.call_args[0][0]
        assert call_args == ["uv", "run", "pytest", "tests/"]

    @patch("uv_script.runner.subprocess.run")
    def test_stops_on_failure(self, mock_run, simple_scripts):
        mock_run.return_value.returncode = 1
        exit_code = run_script(simple_scripts["check"], simple_scripts)
        assert exit_code == 1
        assert mock_run.call_count == 1

    @patch("uv_script.runner.subprocess.run")
    def test_chains_on_success(self, mock_run, simple_scripts):
        mock_run.return_value.returncode = 0
        exit_code = run_script(simple_scripts["check"], simple_scripts)
        assert exit_code == 0
        assert mock_run.call_count == 2

    @patch("uv_script.runner.subprocess.run")
    def test_extra_args_appended_to_last(self, mock_run, simple_scripts):
        mock_run.return_value.returncode = 0
        run_script(simple_scripts["test"], simple_scripts, extra_args=["-k", "foo"])
        call_args = mock_run.call_args[0][0]
        assert call_args == ["uv", "run", "pytest", "tests/", "-k", "foo"]

    @patch("uv_script.runner.subprocess.run")
    def test_env_vars_merged(self, mock_run):
        mock_run.return_value.returncode = 0
        script = ScriptDef(name="s", commands=["echo"], env={"MY_VAR": "hello"})
        run_script(script, {"s": script})
        call_kwargs = mock_run.call_args[1]
        assert call_kwargs["env"]["MY_VAR"] == "hello"

    @patch("uv_script.runner.subprocess.run")
    def test_no_env_passes_none(self, mock_run):
        mock_run.return_value.returncode = 0
        script = ScriptDef(name="s", commands=["echo"])
        run_script(script, {"s": script})
        call_kwargs = mock_run.call_args[1]
        assert call_kwargs["env"] is None

    @patch("uv_script.runner.subprocess.run")
    def test_composite_uses_referenced_env(self, mock_run):
        mock_run.return_value.returncode = 0
        scripts = {
            "serve": ScriptDef(
                name="serve",
                commands=["flask run"],
                env={"FLASK_DEBUG": "1"},
            ),
            "all": ScriptDef(name="all", commands=["serve"], is_composite=True),
        }
        run_script(scripts["all"], scripts)
        call_kwargs = mock_run.call_args[1]
        assert call_kwargs["env"]["FLASK_DEBUG"] == "1"

    @patch("uv_script.runner.subprocess.run")
    def test_editable_flags_in_command(
        self, mock_run, simple_scripts, mock_editable_build
    ):
        mock_run.return_value.returncode = 0
        run_script(
            simple_scripts["test"],
            simple_scripts,
            editable=["/path/to/pkg1", "/path/to/pkg2"],
        )
        call_args = mock_run.call_args[0][0]
        assert call_args == [
            "uv", "run",
            "--find-links", mock_editable_build.editable_dir,
            "--with-editable", "/path/to/pkg1",
            "--with-editable", "/path/to/pkg2",
            "pytest", "tests/",
        ]

    @patch("uv_script.runner.subprocess.run")
    def test_no_editable_no_flags(self, mock_run, simple_scripts):
        mock_run.return_value.returncode = 0
        run_script(simple_scripts["test"], simple_scripts)
        call_args = mock_run.call_args[0][0]
        assert call_args == ["uv", "run", "pytest", "tests/"]

    @patch("uv_script.runner.subprocess.run")
    def test_editable_with_extra_args(self, mock_run, simple_scripts, mock_editable_build):
        mock_run.return_value.returncode = 0
        run_script(
            simple_scripts["test"],
            simple_scripts,
            extra_args=["-k", "foo"],
            editable=["/pkg1"],
        )
        call_args = mock_run.call_args[0][0]
        assert call_args == [
            "uv", "run",
            "--find-links", mock_editable_build.editable_dir,
            "--with-editable", "/pkg1",
            "pytest", "tests/", "-k", "foo",
        ]

    @patch("uv_script.runner.subprocess.run")
    def test_editable_applied_to_all_composite_steps(
        self, mock_run, simple_scripts, mock_editable_build
    ):
        mock_run.return_value.returncode = 0
        run_script(
            simple_scripts["check"],
            simple_scripts,
            editable=["/pkg1"],
        )
        assert mock_run.call_count == 2
        for call in mock_run.call_args_list:
            cmd = call[0][0]
            assert cmd[0:6] == [
                "uv", "run",
                "--find-links", mock_editable_build.editable_dir,
                "--with-editable", "/pkg1",
            ]
        mock_editable_build.assert_called_once()

    @patch("uv_script.runner.subprocess.run")
    def test_editable_overlaps_with_project_dependency(
        self, mock_run, simple_scripts, mock_editable_build
    ):
        """Verify editables are built locally and passed via --find-links to satisfy dependencies."""
        mock_run.return_value.returncode = 0
        run_script(
            simple_scripts["test"],
            simple_scripts,
            editable=["/workspace/X"],
        )
        call_args = mock_run.call_args[0][0]
        assert call_args == [
            "uv", "run",
            "--find-links", mock_editable_build.editable_dir,
            "--with-editable", "/workspace/X",
            "pytest", "tests/",
        ]

    @patch("uv_script.runner.subprocess.run")
    def test_features_flags_in_command(self, mock_run, simple_scripts):
        mock_run.return_value.returncode = 0
        run_script(
            simple_scripts["test"],
            simple_scripts,
            features=["speedups", "cli"],
        )
        call_args = mock_run.call_args[0][0]
        assert call_args == [
            "uv", "run",
            "--extra", "speedups",
            "--extra", "cli",
            "pytest", "tests/",
        ]

    @patch("uv_script.runner.subprocess.run")
    def test_features_with_editable(self, mock_run, simple_scripts, mock_editable_build):
        mock_run.return_value.returncode = 0
        run_script(
            simple_scripts["test"],
            simple_scripts,
            editable=["/pkg1"],
            features=["speedups"],
        )
        call_args = mock_run.call_args[0][0]
        assert call_args == [
            "uv", "run",
            "--find-links", mock_editable_build.editable_dir,
            "--with-editable", "/pkg1",
            "--extra", "speedups",
            "pytest", "tests/",
        ]

    @patch("uv_script.runner.subprocess.run")
    def test_features_applied_to_all_composite_steps(self, mock_run, simple_scripts):
        mock_run.return_value.returncode = 0
        run_script(
            simple_scripts["check"],
            simple_scripts,
            features=["speedups"],
        )
        assert mock_run.call_count == 2
        for call in mock_run.call_args_list:
            cmd = call[0][0]
            assert cmd[0:4] == ["uv", "run", "--extra", "speedups"]

    @patch("uv_script.runner.subprocess.run")
    def test_verbose_prints_command_to_stderr(self, mock_run, simple_scripts, capsys):
        mock_run.return_value.returncode = 0
        run_script(simple_scripts["test"], simple_scripts, verbose=True)
        err = capsys.readouterr().err
        assert "$ uv run pytest tests/" in err

    @patch("uv_script.runner.subprocess.run")
    def test_verbose_with_env_prints_env_prefix(self, mock_run, capsys):
        mock_run.return_value.returncode = 0
        script = ScriptDef(name="s", commands=["echo"], env={"MY_VAR": "hello"})
        run_script(script, {"s": script}, verbose=True)
        err = capsys.readouterr().err
        assert "MY_VAR=" in err
        assert "uv run echo" in err

    @patch("uv_script.runner.subprocess.run")
    def test_build_failure_returns_error(
        self, mock_run, simple_scripts, mock_editable_build, capsys
    ):
        mock_editable_build.side_effect = subprocess.CalledProcessError(
            1, "uv build", stderr="some build error"
        )
        exit_code = run_script(
            simple_scripts["test"],
            simple_scripts,
            editable=["/pkg1"],
        )
        assert exit_code == 1
        err = capsys.readouterr().err
        assert "failed to build editable" in err
        assert "some build error" in err
        mock_run.assert_not_called()
