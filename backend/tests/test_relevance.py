from datetime import timedelta
from sqlalchemy import select,func,delete
from app.domain.models import ContextSession,ContextEvent,Memory,MemoryEntity,Entity,Episode,User,now
from app.services.retrieval import candidates
from app.integrations.openai_client import DemoProvider
from test_capture import client,restaurant


def browsing(client,title="Korean restaurants Hyderabad"):
    client.put("/api/context/mode",json={"enabled":True})
    result=client.post("/api/context/events",json={"events":[
        {"event_type":"PAGE_ENTERED","source_url":f"https://example.com/search/{i}","page_title":title,
         "dwell_seconds":15} for i in range(2)]})
    assert result.status_code==200,result.text
    assert result.json()["analyzed"]


def test_restaurant_returns_in_useful_context(client):
    memory=client.post("/api/captures",json=restaurant()).json()
    browsing(client)
    result=client.post("/api/relevance/evaluate").json()
    assert result["suggest_now"]
    assert result["suggestion"]["memory"]["id"]==memory["id"]
    assert not client.post("/api/relevance/evaluate").json()["suggest_now"]


def test_unrelated_python_article_stays_quiet(client):
    client.post("/api/captures",json={"page_title":"Python decorators","visible_text":"Python programming guide"})
    browsing(client)
    assert not client.post("/api/relevance/evaluate").json()["suggest_now"]


def test_graph_retains_tokyo_candidate_without_vectors_or_direct_japan_link(client):
    memory=client.post("/api/captures",json={"page_title":"Tokyo café","visible_text":"A quiet Tokyo café","user_note":"For my trip"}).json()
    with client.app.state.sessions() as db:
        japan=db.scalar(select(Entity).where(Entity.name=="Japan"))
        db.execute(delete(MemoryEntity).where(MemoryEntity.memory_id==memory["id"],MemoryEntity.entity_id==japan.id))
        db.commit()
        result=candidates(db,"demo-user",{"entities":["Japan"],"topics":[],"intent":"travel_planning"})
        assert result[0]["id"]==memory["id"]
        assert result[0]["signals"]["graph"] and not result[0]["signals"]["entity"]


def test_dismissal_is_idempotent_and_suppresses(client):
    memory=client.post("/api/captures",json=restaurant()).json()
    browsing(client)
    suggestion=client.post("/api/relevance/evaluate").json()["suggestion"]
    for _ in range(2):
        client.post(f"/api/relevance/{suggestion['id']}/feedback",json={"outcome":"dismissed"})
    with client.app.state.sessions() as db:
        m=db.get(Memory,memory["id"])
        assert m.dismiss_count==1
        m.last_surfaced_at=now()-timedelta(days=1)
        db.commit()
        state=db.scalar(select(ContextSession)).state
        assert candidates(db,"demo-user",state)==[]
        m.dismiss_count=3
        for e in db.scalars(select(Episode).where(Episode.event_type=="dismissed")):
            e.occurred_at=now()-timedelta(days=30)
        db.commit()
        assert candidates(db,"demo-user",state)==[]


def test_context_off_never_calls_model_or_stores_events(client):
    class Spy(DemoProvider):
        def context(self,pages):
            raise AssertionError("Must not analyze when off")
    client.app.state.ai=Spy()
    response=client.post("/api/context/events",json={"events":[{"event_type":"PAGE_ENTERED","source_url":"https://example.com","page_title":"private","dwell_seconds":15}]})
    assert response.json()["reason"]=="context_mode_off"
    assert not client.post("/api/relevance/evaluate").json()["suggest_now"]
    with client.app.state.sessions() as db:
        assert db.scalar(select(func.count()).select_from(ContextEvent))==0
        assert db.scalar(select(func.count()).select_from(ContextSession))==0


def test_turning_off_clears_working_memory_and_hides_card(client):
    client.post("/api/captures",json=restaurant())
    browsing(client)
    assert client.post("/api/relevance/evaluate").json()["suggest_now"]
    client.put("/api/context/mode",json={"enabled":False})
    assert client.get("/api/relevance/current").json()["suggestion"] is None
    with client.app.state.sessions() as db:
        assert db.scalar(select(func.count()).select_from(ContextEvent))==0
        assert db.scalar(select(func.count()).select_from(ContextSession))==0
        assert db.scalar(select(func.count()).select_from(Memory))==1


def test_expiry_deletes_working_content_and_one_page_is_insufficient(client):
    client.put("/api/context/mode",json={"enabled":True})
    result=client.post("/api/context/events",json={"events":[{"event_type":"PAGE_ENTERED","source_url":"https://example.com","page_title":"Korean restaurants","dwell_seconds":20}]}).json()
    assert not result["analyzed"]
    with client.app.state.sessions() as db:
        db.scalar(select(ContextSession)).expires_at=now()-timedelta(seconds=1)
        db.commit()
    assert client.get("/api/context/current").json()["session"] is None
    with client.app.state.sessions() as db:
        assert db.scalar(select(func.count()).select_from(ContextEvent))==0


def test_other_user_memory_is_inaccessible(client):
    with client.app.state.sessions() as db:
        db.add(User(id="another-user"))
        db.commit()
    m=client.post("/api/captures",json=restaurant()).json()
    with client.app.state.sessions() as db:
        db.get(Memory,m["id"]).user_id="another-user"
        db.commit()
    assert client.get(f"/api/memories/{m['id']}").status_code==404
    assert client.get("/api/memories").json()==[]
