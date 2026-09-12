from sqlalchemy import select, func
from test_capture import client, restaurant
from app.domain.models import (
    Action, Entity, Episode, Memory, MemoryEntity, RawCapture, Relationship,
    RelevanceEvent, SemanticFact, Trigger, now,
)


def test_delete_removes_content_and_dependents_but_preserves_shared_entities(client):
    first = client.post('/api/captures', json=restaurant()).json()
    second = client.post('/api/captures', json={**restaurant(), 'request_id': 'second'}).json()
    with client.app.state.sessions() as db:
        memory = db.get(Memory, first['id'])
        raw_id = memory.raw_capture_id
        episode = db.scalar(select(Episode).where(Episode.memory_id == memory.id))
        trigger = Trigger(user_id=memory.user_id, memory_id=memory.id, scheduled_at=now())
        db.add(trigger)
        db.flush()
        db.add(RelevanceEvent(user_id=memory.user_id, memory_id=memory.id, trigger_id=trigger.id,
                              relevance_score=.9, reason='Deadline'))
        db.add(Action(user_id=memory.user_id, memory_id=memory.id, type='draft_email'))
        db.add(SemanticFact(user_id=memory.user_id, subject='person', predicate='likes', object='restaurant',
                            confidence=.9, source_episode_ids=[episode.id]))
        db.commit()
    assert client.delete(f"/api/memories/{first['id']}").status_code == 204
    assert client.get(f"/api/memories/{first['id']}").status_code == 404
    assert client.get(f'/api/captures/{raw_id}').status_code == 404
    assert [m['id'] for m in client.get('/api/memories').json()] == [second['id']]
    with client.app.state.sessions() as db:
        for model in (Action, Trigger, RelevanceEvent, Episode, MemoryEntity):
            assert not db.scalar(select(model).where(model.memory_id == first['id']))
        assert db.scalar(select(func.count()).select_from(Entity)) > 0
        assert db.scalar(select(func.count()).select_from(SemanticFact)) == 0
    assert client.delete(f"/api/memories/{second['id']}").status_code == 204
    with client.app.state.sessions() as db:
        for model in (Memory, RawCapture, Entity, Relationship):
            assert db.scalar(select(func.count()).select_from(model)) == 0


def test_delete_requires_owner_and_unknown_memory_is_404(client):
    memory = client.post('/api/captures', json=restaurant()).json()
    url = f"/api/memories/{memory['id']}"
    assert client.delete(url, headers={'Authorization': 'Bearer wrong'}).status_code == 401
    account = client.post('/api/auth/signup', json={'email': 'other@example.com', 'password': 'long test password'}).json()
    assert client.delete(url, headers={'Authorization': 'Bearer ' + account['token']}).status_code == 404
    assert client.get(url).status_code == 200
    assert client.delete('/api/memories/does-not-exist').status_code == 404
