"""Test setup: import path, and keeping hardware tests opt-in."""

import sys
from pathlib import Path

import pytest

ENGINE_DIR = Path(__file__).resolve().parents[1]
if str(ENGINE_DIR) not in sys.path:
    sys.path.insert(0, str(ENGINE_DIR))


def pytest_addoption(parser):
    parser.addoption(
        "--camera",
        action="store_true",
        default=False,
        help="run tests that need a real camera attached",
    )


def pytest_collection_modifyitems(config, items):
    """Skip `@pytest.mark.camera` tests unless they are asked for.

    They need hardware that may not be present, they are slow, and they fail
    confusingly when something else already holds the device — a running engine
    grabbing webcam:0 makes them look like a code regression when they are not.

        python -m pytest --camera        run them
        python -m pytest -m camera       run only them
    """
    if config.getoption("--camera") or "camera" in (config.getoption("-m") or ""):
        return

    skip = pytest.mark.skip(reason="needs a camera; run with --camera")
    for item in items:
        if "camera" in item.keywords:
            item.add_marker(skip)
