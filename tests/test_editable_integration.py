"""Integration tests for editable installs with project dependencies.

These tests create real Python packages on disk and run uv to verify
editable install behaviour. They require a working uv installation.

Run with: uv run pytest tests/ -v --run-integration
"""

from __future__ import annotations

import subprocess
import textwrap

import pytest

pytestmark = pytest.mark.integration


@pytest.fixture
def workspace(tmp_path):
    """Create a workspace with packages X and Y, plus a local wheel index.

    Layout:
        workspace/
          X/
            pyproject.toml
            src/uvscript_test_x/__init__.py   (MARKER = "editable")
          Y/
            pyproject.toml
            src/uvscript_test_y/__init__.py
          wheels/
            uvscript_test_x-0.1.2-*.whl       (MARKER = "source")
    """
    # -- Package X --
    x_dir = tmp_path / "X"
    x_src = x_dir / "src" / "uvscript_test_x"
    x_src.mkdir(parents=True)
    (x_src / "__init__.py").write_text('MARKER = "source"\n')
    (x_dir / "pyproject.toml").write_text(textwrap.dedent("""\
        [project]
        name = "uvscript-test-x"
        version = "0.1.2"
        requires-python = ">=3.12"

        [build-system]
        requires = ["uv_build>=0.8.7,<0.9.0"]
        build-backend = "uv_build"
    """))

    # Build X into a wheel (contains MARKER = "source")
    wheels_dir = tmp_path / "wheels"
    wheels_dir.mkdir()
    result = subprocess.run(
        ["uv", "build", "--wheel", "--out-dir", str(wheels_dir)],
        cwd=str(x_dir),
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, f"Failed to build X wheel: {result.stderr}"

    # Create a PEP 503 simple repository pointing to the wheel
    wheel_name = next(wheels_dir.glob("*.whl")).name
    simple_dir = tmp_path / "simple" / "uvscript-test-x"
    simple_dir.mkdir(parents=True)
    (simple_dir / "index.html").write_text(
        f'<a href="../../wheels/{wheel_name}">{wheel_name}</a>\n'
    )

    # Now modify X's source so it differs from the wheel
    (x_src / "__init__.py").write_text('MARKER = "editable"\n')

    # -- Package Y --
    y_dir = tmp_path / "Y"
    y_src = y_dir / "src" / "uvscript_test_y"
    y_src.mkdir(parents=True)
    (y_src / "__init__.py").write_text("")

    return tmp_path


def _write_y_pyproject(
    workspace,
    *,
    depend_on_x: bool,
    index_mode: str = "none",
):
    """Write Y's pyproject.toml with configurable dependency and index settings.

    index_mode:
        "none"       — no index configured (uv uses default PyPI)
        "find-links" — flat wheel directory via [tool.uv] find-links
        "pep503"     — local PEP 503 simple repository via [[tool.uv.index]]
    """
    y_dir = workspace / "Y"
    wheels_dir = workspace / "wheels"
    simple_dir = workspace / "simple"

    deps = '["uvscript-test-x>=0.1.2"]' if depend_on_x else "[]"

    uv_section = ""
    if index_mode == "find-links":
        uv_section = textwrap.dedent(f"""\

            [tool.uv]
            no-index = true
            find-links = ["{wheels_dir}"]
        """)
    elif index_mode == "pep503":
        index_url = simple_dir.as_uri()
        uv_section = textwrap.dedent(f"""\

            [[tool.uv.index]]
            name = "local"
            url = "{index_url}"
            default = true
        """)

    (y_dir / "pyproject.toml").write_text(textwrap.dedent(f"""\
        [project]
        name = "uvscript-test-y"
        version = "0.0.1"
        requires-python = ">=3.12"
        dependencies = {deps}

        [build-system]
        requires = ["uv_build>=0.8.7,<0.9.0"]
        build-backend = "uv_build"
    """) + uv_section + textwrap.dedent("""\

        [tool.uvs]
        editable = ["../X"]

        [tool.uvs.scripts]
        check = "python -c 'import uvscript_test_x; print(uvscript_test_x.MARKER)'"
    """))


def _run_with_editable(workspace):
    """Run the command that uvs would generate: uv run --with-editable X ..."""
    y_dir = workspace / "Y"
    x_dir = workspace / "X"
    return subprocess.run(
        [
            "uv", "run",
            "--with-editable", str(x_dir),
            "python", "-c",
            "import uvscript_test_x; print(uvscript_test_x.MARKER)",
        ],
        capture_output=True,
        text=True,
        cwd=str(y_dir),
    )


class TestEditableDependencyClash:
    def test_editable_fails_when_dep_not_on_any_index(self, workspace):
        """--with-editable cannot satisfy a declared dependency.

        When Y depends on X but X is not on any index, uv fails with a
        resolution error even though --with-editable points to a valid
        X source tree. This proves --with-editable does not participate
        in dependency resolution.
        """
        _write_y_pyproject(workspace, depend_on_x=True, index_mode="none")
        result = _run_with_editable(workspace)

        assert result.returncode != 0, (
            "Expected uv to fail resolving dependency, but it succeeded. "
            f"stdout={result.stdout!r}"
        )
        assert "was not found in the package registry" in result.stderr

    def test_editable_with_local_index_uses_editable(self, workspace):
        """When X is on a local index AND --with-editable, editable wins.

        This is a control showing that when the dependency CAN be resolved
        (via find-links), --with-editable correctly provides the live source.
        """
        _write_y_pyproject(workspace, depend_on_x=True, index_mode="find-links")
        result = _run_with_editable(workspace)

        assert result.returncode == 0, f"uv run failed: {result.stderr}"
        assert result.stdout.strip() == "editable"

    def test_editable_with_pep503_index(self, workspace):
        """Test with a PEP 503 simple repository (closer to a real PyPI-like index).

        This simulates the user's real scenario: a private index that behaves
        like PyPI. The dependency is resolvable from the index, and
        --with-editable is also specified for the same package.
        """
        _write_y_pyproject(workspace, depend_on_x=True, index_mode="pep503")
        result = _run_with_editable(workspace)

        assert result.returncode == 0, f"uv run failed: {result.stderr}"
        assert result.stdout.strip() == "editable", (
            f"Expected editable source but got {result.stdout.strip()!r}. "
            "The index version may have shadowed the editable install."
        )

    def test_editable_without_dependency(self, workspace):
        """Control: editable works when X is NOT in project dependencies."""
        _write_y_pyproject(workspace, depend_on_x=False, index_mode="none")
        result = _run_with_editable(workspace)

        assert result.returncode == 0, f"uv run failed: {result.stderr}"
        assert result.stdout.strip() == "editable"
