import pytest
from fastapi.testclient import TestClient

from app.config import get_settings
from app.main import app
from app.state import state


@pytest.fixture
def client():
    # TestClient as a context manager so lifespan startup/shutdown actually run.
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture(autouse=True)
def reset_state():
    """Readiness is process-global; leaking it between tests would cross-talk."""
    state.ready = True
    yield
    state.ready = True


@pytest.fixture(autouse=True)
def clear_settings_cache():
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()
