"""Phase 0 import smoke tests."""

from importlib import import_module


def test_engine_import_smoke() -> None:
    """The calculation package and its initialization module are importable."""
    assert import_module("engine")
    assert import_module("engine.init")
