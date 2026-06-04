"""Shared test setup: force APP_MODE=local so no real Azure dependency is touched."""

import os

import pytest

# Set before any module reads it. Individual tests re-assert via the fixture below.
os.environ.setdefault("APP_MODE", "local")


@pytest.fixture(autouse=True)
def local_mode(monkeypatch):
    """Guarantee APP_MODE=local and a fresh Settings singleton per test."""
    import config

    monkeypatch.setenv("APP_MODE", "local")
    config.get_settings.cache_clear()
    yield
    config.get_settings.cache_clear()
