import dataclasses
import importlib

import pytest
from fastapi.testclient import TestClient

from settle.config import load_config
from settle.db import connect
from settle.engine import World

EXTERNAL_KEYS = (
    "ANTHROPIC_API_KEY",
    "ANTHROPIC_AUTH_TOKEN",
    "ANTHROPIC_WORKSPACE_ID",
    "MOSS_PROJECT_ID",
    "MOSS_PROJECT_KEY",
    "BITDEER_API_KEY",
    "SETTLE_REPLAY",
    "SETTLE_PERSONA_LLM",
    "SETTLE_USERS",
    "SETTLE_SECRET",
)


@pytest.fixture(autouse=True)
def hermetic_env(monkeypatch):
    """Tests never touch live services. Empty (not deleted) so load_dotenv can't re-read backend/.env."""
    for k in EXTERNAL_KEYS:
        monkeypatch.setenv(k, "")
    monkeypatch.setenv("SETTLE_ALLOW_DEMO_USERS", "1")


@pytest.fixture
def cfg(tmp_path):
    return dataclasses.replace(
        load_config(),
        agent_kind="heuristic",
        persona_llm=False,
        moss_project_id=None,
        moss_project_key=None,
        bitdeer_api_key=None,
        anthropic_workspace_id=None,
        replay=False,
        cache_dir=tmp_path / "cache",
        db_path=str(tmp_path / "t.db"),
    )


def make_world(cfg, memory=True, oracle=False):
    w = World(cfg, connect(":memory:"), oracle=oracle)
    w.reset(memory=memory)
    return w


@pytest.fixture
def world(cfg):
    return make_world(cfg)


@pytest.fixture
def anon(cfg, monkeypatch):
    """A TestClient on a fresh app with no credentials."""
    monkeypatch.setenv("SETTLE_DB", cfg.db_path)
    monkeypatch.setenv("SETTLE_AGENT", "heuristic")
    monkeypatch.setenv("SETTLE_CACHE_DIR", str(cfg.cache_dir))
    import settle.api as api

    api = importlib.reload(api)
    with TestClient(api.app) as c:
        yield c


def auth_headers(c, username: str, password: str = "demo") -> dict:
    r = c.post("/api/login", json={"username": username, "password": password})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['token']}"}


@pytest.fixture
def client(anon):
    """Logged in as the demo controller."""
    anon.headers.update(auth_headers(anon, "dana"))
    return anon
