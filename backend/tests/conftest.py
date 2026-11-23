from __future__ import annotations

import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.config import get_settings  # noqa: E402
from app.database import init_db  # noqa: E402
from app.main import create_app  # noqa: E402


@pytest.fixture()
def make_client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    def _factory(
        *,
        password: str = "",
        mock_mode: bool = True,
    ) -> TestClient:
        db_file = tmp_path / f"test_{id(password)}_{mock_mode}.db"
        monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db_file}")
        monkeypatch.setenv("APP_ACCESS_PASSWORD", password)
        monkeypatch.setenv("APP_SESSION_SECRET", "unit-test-secret-key-1234567890")
        monkeypatch.setenv("ENABLE_MOCK_MODE", "true" if mock_mode else "false")
        get_settings.cache_clear()
        init_db(f"sqlite:///{db_file}")
        app = create_app()
        return TestClient(app)

    yield _factory
    get_settings.cache_clear()
