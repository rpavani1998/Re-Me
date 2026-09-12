import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select, func
from app.main import create_app
from app.core.config import Settings
from app.domain.models import RawCapture, Memory, Episode, Entity, Relationship, SemanticFact
from app.integrations.openai_client import DemoProvider


@pytest.fixture
def client(tmp_path):
    app = create_app(Settings(database_url=f"sqlite:///{tmp_path}/test.db", demo_mode=True,
                              api_token="test-token", _env_file=None))
    with TestClient(app, headers={"Authorization": "Bearer test-token"}) as c:
        yield c


def restaurant():
    return {"request_id": "restaurant", "source_url": "https://example.com/seoul", "page_title": "Seoul Kitchen",
            "visible_text": "Korean restaurant in Hyderabad.", "user_note": "Want to try this sometime"}


def test_capture_preserves_episode_graph_and_original(client):
    response = client.post("/api/captures", json=restaurant())
    assert response.status_code == 201, response.text
    memory = response.json()
    assert memory["intent"] == "want_to_try"
    detail = client.get(f"/api/memories/{memory['id']}").json()
    assert detail["raw_capture"]["visible_text"] == restaurant()["visible_text"]
    assert detail["episodes"][0]["event_type"] == "saved_content"
    with client.app.state.sessions() as db:
        assert db.scalar(select(func.count()).select_from(Relationship)) >= 3
        assert len(db.get(Memory, memory["id"]).embedding) == 1536
        assert db.scalar(select(func.count()).select_from(SemanticFact)) == 0
    assert client.post("/api/captures", json=restaurant()).json()["id"] == memory["id"]
    assert len(client.get("/api/memories").json()) == 1


def test_failure_keeps_raw_capture_and_allows_retry(client):
    class Broken(DemoProvider):
        def embed(self, text):
            raise RuntimeError("provider failed")
    client.app.state.ai = Broken()
    assert client.post("/api/captures", json=restaurant()).status_code == 502
    with client.app.state.sessions() as db:
        raw = db.scalar(select(RawCapture))
        assert raw.payload["page_title"] == "Seoul Kitchen"
        assert raw.status == "failed"
        assert db.scalar(select(func.count()).select_from(Memory)) == 0
    client.app.state.ai = DemoProvider()
    assert client.post("/api/captures", json=restaurant()).status_code == 201


def test_auth_and_input_bounds(client):
    assert client.get("/api/memories", headers={"Authorization": "Bearer wrong"}).status_code == 401
    assert client.post("/api/captures", json={"visible_text": "x" * 16001}).status_code == 422
    assert client.post("/api/captures", json={"source_url": "javascript:alert(1)"}).status_code == 422
