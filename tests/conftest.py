import pytest


@pytest.fixture(autouse=True)
def cache_home(tmp_path_factory, monkeypatch):
    """Keep kg's cache (validated stores) out of the user's home."""
    path = tmp_path_factory.mktemp("cache")
    monkeypatch.setenv("XDG_CACHE_HOME", str(path))
    return path
