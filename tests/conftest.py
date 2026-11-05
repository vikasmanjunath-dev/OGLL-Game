"""pytest configuration: make the repo root importable and run headless-safe unit tests without a display."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("PYGAME_HIDE_SUPPORT_PROMPT", "1")


def pytest_collection_modifyitems(config, items):
    """The smoke test needs a real OpenGL context; skip it when there is no display (set LUMEN_SMOKE=1 to force)."""
    if os.environ.get("LUMEN_SMOKE") == "1" or os.environ.get("DISPLAY") or sys.platform in ("darwin", "win32"):
        return
    import pytest
    skip = pytest.mark.skip(reason="no display: run under xvfb-run, or set LUMEN_SMOKE=1")
    for item in items:
        if "test_smoke" in item.nodeid:
            item.add_marker(skip)
