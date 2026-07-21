"""Pytest configuration for pybmap tests."""

import pytest


def pytest_addoption(parser):
    parser.addoption(
        "--integration", action="store_true", default=False,
        help="Run integration tests (requires paired Bluetooth device)",
    )


def pytest_collection_modifyitems(config, items):
    if not config.getoption("--integration"):
        skip = pytest.mark.skip(reason="Need --integration flag to run")
        for item in items:
            if "integration" in item.keywords:
                item.add_marker(skip)
