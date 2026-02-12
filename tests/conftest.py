"""Shared pytest configuration and fixtures."""

from unittest.mock import patch

import pytest

@pytest.fixture
def mock_editable_build(tmp_path):
    editable_dir = str(tmp_path / "uvs-editable")
    with (
        patch("uv_script.runner._build_editables") as mock_build,
        patch("uv_script.runner.tempfile.TemporaryDirectory") as mock_tmpdir,
    ):
        mock_tmpdir.return_value.__enter__.return_value = editable_dir
        mock_build.editable_dir = editable_dir
        yield mock_build


def pytest_addoption(parser):
    parser.addoption(
        "--run-integration",
        action="store_true",
        default=False,
        help="Run integration tests (requires uv, network access)",
    )


def pytest_collection_modifyitems(config, items):
    if config.getoption("--run-integration"):
        return
    skip_integration = pytest.mark.skip(reason="needs --run-integration option")
    for item in items:
        if "integration" in item.keywords:
            item.add_marker(skip_integration)
