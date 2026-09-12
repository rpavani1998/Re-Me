from datetime import timedelta
from fastapi.testclient import TestClient
from sqlalchemy import select
from app.core.config import Settings
from app.main import create_app
from app.domain.models import Trigger, RelevanceEvent, now
from app.services.trigger_service import deliver_due_reminders


def test_schedule_and_deliver_reminder_without_context(tmp_path):
    app = create_app(Settings(database_url=f'sqlite:///{tmp_path}/reminder.db',
                             api_token='test', trigger_secret_key='trigger-test', demo_mode=True, _env_file=None))
    with TestClient(app, headers={'Authorization': 'Bearer test'}) as client:
        m = client.post('/api/captures', json={'visible_text': 'Event poster'}).json()
        url = f'/api/memories/{m["id"]}/reminders'
        assert client.post(url, json={'scheduled_at': '2020-01-01T10:00:00Z'}).status_code == 422
        assert client.post(url, json={'scheduled_at': '2099-01-01T10:00:00'}).status_code == 422
        body = {'scheduled_at': (now() + timedelta(hours=1)).isoformat()}
        assert client.post(url, json=body, headers={'Authorization': 'Bearer wrong'}).status_code == 401
        response = client.post(url, json=body)
        assert response.status_code == 201
        assert client.get(f'/api/memories/{m["id"]}').json()['reminders'][0]['status'] == 'pending'
        with app.state.sessions() as db:
            t = db.get(Trigger, response.json()['id'])
            t.scheduled_at = now() - timedelta(seconds=1)
            db.commit()
        from app.integrations.trigger_client import callback_signature
        token = callback_signature(app.state.config, m["id"], response.json()["id"])
        for _ in range(2):
            assert client.post("/api/triggers/callback", json={"memory_id": m["id"], "trigger_id": response.json()["id"]}, headers={"Authorization": "Bearer " + token}).status_code == 200
        with app.state.sessions() as db:
            assert len(db.scalars(select(RelevanceEvent)).all()) == 1
        assert client.get('/api/relevance/current').json()['suggestion']['memory']['id'] == m['id']


def test_deadline_reminder_is_early_and_manual_change_replaces_it(tmp_path):
    from datetime import datetime, timezone
    app = create_app(Settings(database_url=f'sqlite:///{tmp_path}/early.db', api_token='test', demo_mode=True, _env_file=None))
    with TestClient(app, headers={'Authorization':'Bearer test'}) as client:
        memory = client.post('/api/captures', json={'visible_text':'Apply by 2030-01-02.'}).json()
        with app.state.sessions() as db:
            original = db.scalar(select(Trigger))
            original_id = original.id
            assert original.scheduled_at.replace(tzinfo=timezone.utc) == datetime(2030,1,1,tzinfo=timezone.utc)
        changed = client.post(f'/api/memories/{memory["id"]}/reminders', json={'scheduled_at':'2030-01-01T12:00:00Z'})
        assert changed.status_code == 201
        with app.state.sessions() as db:
            assert db.get(Trigger, original_id).status == 'cancelled'
            assert len(db.scalars(select(Trigger).where(Trigger.status == 'pending')).all()) == 1
