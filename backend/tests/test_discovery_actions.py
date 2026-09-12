from types import SimpleNamespace
import pytest
from fastapi import HTTPException
from sqlalchemy import select, func
from app.domain.models import Action, Memory
from app.domain.schemas import DiscoveryRanking, EmailDraft
from app.services.capture_service import capture
from app.services.discovery import discover
from app.services.action_service import create_draft_email, approve_draft_email
from app.integrations.openai_client import DemoProvider
from app.domain.schemas import CaptureInput
from test_capture import client


def saved_memory(db, user_id, request_id="opportunity", text="AI Agent Engineer role at Sarvam. Apply by 2030-01-01."):
    payload = CaptureInput(request_id=request_id, source_url=f"https://example.com/{request_id}",
                           page_title="AI Agent Engineer", visible_text=text, user_note="I want to apply")
    return capture(db, user_id, payload, DemoProvider(), SimpleNamespace(public_api_url="", trigger_secret_key=""))


class FakeExa:
    received_query = None

    def __init__(self, _key):
        pass

    def search(self, query, limit):
        self.__class__.received_query = query
        assert limit == 6
        return [
            {"title": "Role details", "url": "https://jobs.example/role", "summary": "Role page"},
            {"title": "Company", "url": "https://company.example", "summary": "Company details"},
            {"title": "Irrelevant", "url": "https://other.example", "summary": "Other"},
        ]


class Ranker(DemoProvider):
    def rank_discovery(self, memory, results):
        return DiscoveryRanking(ordered_indices=[1, 0, 10])


def test_discovery_is_grounded_bounded_and_never_creates_memories(client):
    with client.app.state.sessions() as db:
        selected = saved_memory(db, "demo-user")
        other = saved_memory(db, "demo-user", "unrelated", "A quiet cafe in Tokyo")
        before = db.scalar(select(func.count()).select_from(Memory))
        result = discover(db, "demo-user", selected["id"], SimpleNamespace(exa_api_key="test"), Ranker(), FakeExa)
        after = db.scalar(select(func.count()).select_from(Memory))
    assert before == after == 2
    assert result["memory_id"] == selected["id"]
    assert [item["title"] for item in result["suggestions"]] == ["Company", "Role details"]
    assert all(item["external"] for item in result["suggestions"])
    assert selected["title"] in FakeExa.received_query
    assert "A quiet cafe in Tokyo" not in FakeExa.received_query


def test_discovery_requires_exa_key(client):
    with client.app.state.sessions() as db:
        memory = saved_memory(db, "demo-user")
        with pytest.raises(ValueError, match="EXA_API_KEY"):
            discover(db, "demo-user", memory["id"], SimpleNamespace(exa_api_key=""), DemoProvider(), FakeExa)


def test_discovery_endpoint_reports_unconfigured_provider(client):
    memory = client.post("/api/captures", json={"request_id": "discover-api", "page_title": "Saved role",
                                                  "visible_text": "An AI agent engineering role"}).json()
    response = client.post(f"/api/memories/{memory['id']}/discover")
    assert response.status_code == 503
    assert "EXA_API_KEY" in response.json()["detail"]


def test_approval_generates_editable_draft_and_never_sends(client):
    with client.app.state.sessions() as db:
        memory = saved_memory(db, "demo-user")
        action = create_draft_email(db, "demo-user", memory["id"])
        assert action["status"] == "awaiting_approval"
        assert action["result"] is None
        completed = approve_draft_email(db, "demo-user", action["id"], DemoProvider())
        stored = db.get(Action, action["id"])
    assert completed["status"] == "completed"
    assert completed["result"]["subject"].startswith("Application:")
    assert "[Hiring Manager]" in completed["result"]["body"]
    assert stored.external_reference is None
    assert approve_draft_email(db, "demo-user", action["id"], DemoProvider())["id"] == action["id"]


def test_action_endpoints_create_then_approve(client):
    memory = client.post("/api/captures", json={"request_id": "action-api", "page_title": "Application role",
                                                  "visible_text": "AI agent engineer role", "user_note": "I want to apply"}).json()
    created = client.post(f"/api/memories/{memory['id']}/actions")
    assert created.status_code == 201
    assert created.json()["status"] == "awaiting_approval"
    approved = client.post(f"/api/actions/{created.json()['id']}/approve")
    assert approved.status_code == 200
    assert approved.json()["status"] == "completed"
    assert approved.json()["result"]["body"]


def test_actions_are_owned_by_the_request_user(client):
    with client.app.state.sessions() as db:
        memory = saved_memory(db, "demo-user")
        action = create_draft_email(db, "demo-user", memory["id"])
        with pytest.raises(HTTPException) as error:
            approve_draft_email(db, "another-user", action["id"], DemoProvider())
    assert error.value.status_code == 404
