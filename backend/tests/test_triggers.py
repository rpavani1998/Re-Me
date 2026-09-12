from fastapi.testclient import TestClient
from sqlalchemy import select, func

from app.core.config import Settings
from app.domain.models import Episode, RelevanceEvent, Trigger
from app.integrations.trigger_client import hosted_trigger_ready
from app.main import create_app


def make_client(tmp_path, **settings):
    config = Settings(database_url=f"sqlite:///{tmp_path}/triggers.db", demo_mode=True,
                      api_token="test-token", _env_file=None, **settings)
    return TestClient(create_app(config), headers={"Authorization": "Bearer test-token"})


def future_deadline_capture():
    return {
        "request_id": "future-deadline",
        "page_title": "Role application",
        "visible_text": "AI engineer opportunity. Apply by 2030-01-02.",
        "user_note": "I want to apply",
    }


def test_local_deadline_is_simulated_without_outbound_trigger(tmp_path, monkeypatch):
    def outbound(*args, **kwargs):
        raise AssertionError("local trigger scheduling must not call Trigger.dev")

    monkeypatch.setattr("app.services.trigger_service.schedule_wakeup", outbound)
    with make_client(tmp_path) as client:
        response = client.post("/api/captures", json=future_deadline_capture())
        assert response.status_code == 201, response.text
        with client.app.state.sessions() as db:
            trigger = db.scalar(select(Trigger))
            assert trigger.status == "pending"
            assert trigger.external_reference == f"simulated:{trigger.id}"


def test_hosted_trigger_requires_key_token_and_https_url():
    base = dict(demo_mode=True, api_token="test", _env_file=None,
                trigger_secret_key="secret", trigger_callback_token="callback")
    assert not hosted_trigger_ready(Settings(**base, public_api_url="http://localhost:8000"))
    assert not hosted_trigger_ready(Settings(**base, public_api_url=""))
    assert hosted_trigger_ready(Settings(demo_mode=True, api_token="test", _env_file=None,
                                             trigger_secret_key="secret", public_api_url="https://api.example.com"))
    assert hosted_trigger_ready(Settings(**base, public_api_url="https://api.example.com"))


def test_callback_rejects_bad_token_and_is_idempotent(tmp_path):
    with make_client(tmp_path, trigger_callback_token="callback-token") as client:
        memory = client.post("/api/captures", json=future_deadline_capture()).json()
        with client.app.state.sessions() as db:
            trigger = db.scalar(select(Trigger))
            trigger_id = trigger.id

        from datetime import timedelta
        from app.domain.models import now
        with client.app.state.sessions() as db:
            db.get(Trigger, trigger_id).scheduled_at = now() - timedelta(seconds=1)
            db.commit()
        body = {"memory_id": memory["id"], "trigger_id": trigger_id}
        assert client.post("/api/triggers/callback", json=body).status_code == 401
        headers = {"Authorization": "Bearer callback-token"}
        first = client.post("/api/triggers/callback", json=body, headers=headers)
        second = client.post("/api/triggers/callback", json=body, headers=headers)
        assert first.status_code == 200
        assert first.json()["status"] == "fired"
        assert second.json() == {"status": "fired"}
        with client.app.state.sessions() as db:
            assert db.scalar(select(Trigger).where(Trigger.id == trigger_id)).status == "fired"
            assert db.scalar(select(func.count()).select_from(RelevanceEvent)) == 1
            assert db.scalar(select(func.count()).select_from(Episode).where(Episode.event_type == "deadline_fired")) == 1


def test_callback_memory_must_match_trigger(tmp_path):
    with make_client(tmp_path, trigger_callback_token="callback-token") as client:
        memory = client.post("/api/captures", json=future_deadline_capture()).json()
        with client.app.state.sessions() as db:
            trigger = db.scalar(select(Trigger))
        response = client.post("/api/triggers/callback", headers={"Authorization": "Bearer callback-token"},
                               json={"memory_id": "wrong-memory", "trigger_id": trigger.id})
        assert response.status_code == 404
        with client.app.state.sessions() as db:
            assert db.get(Trigger, trigger.id).status == "pending"


def test_callback_rejects_unconfigured_key(tmp_path):
    with make_client(tmp_path) as client:
        for authorization in ("", "Bearer ", "Bearer wrong"):
            response = client.post("/api/triggers/callback",
                                   headers={"Authorization": authorization},
                                   json={"memory_id": "missing", "trigger_id": "missing"})
            assert response.status_code == 401
