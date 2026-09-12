from datetime import timedelta
from fastapi.testclient import TestClient
from sqlalchemy import select
from app.core.config import Settings
from app.main import create_app
from app.integrations.openai_client import DemoProvider
from app.domain.schemas import EventDetails
from app.domain.models import Trigger, now
from app.services.trigger_service import dispatch_reminders


def test_events_calendar_feed_and_retryable_dispatch(tmp_path, monkeypatch):
    class AI(DemoProvider):
        def extract(self, payload):
            result = super().extract(payload)
            result.event = EventDetails(title='Community fair', date_text='Tomorrow', location='Hyderabad',
                starts_at=(now()+timedelta(days=1)).isoformat(), ends_at=None,
                needs_confirmation=False, clarification=None)
            return result
    config = Settings(database_url=f'sqlite:///{tmp_path}/events.db', demo_mode=True,
        api_token='test', trigger_secret_key='trigger-test', public_api_url='https://api.example.com', _env_file=None)
    app = create_app(config, ai=AI())
    with TestClient(app, headers={'Authorization':'Bearer test'}) as client:
        memory = client.post('/api/captures', json={'visible_text':'A fair tomorrow'}).json()
        assert memory['event']['title'] == 'Community fair'
        feed_url = client.get('/api/calendar/subscription').json()['url'].replace('https://api.example.com','')
        feed = client.get(feed_url)
        assert 'X-WR-CALNAME:Re:Me Events' in feed.text
        assert 'SUMMARY:Community fair' in feed.text
        assert 'VALARM' not in feed.text
        assert client.get(feed_url.split('?')[0]+'?token=wrong').status_code == 401
        with app.state.sessions() as db:
            reminder = db.scalar(select(Trigger))
            assert reminder.external_reference == 'awaiting-trigger'
            monkeypatch.setattr('app.services.trigger_service.schedule_wakeup', lambda *a, **k: (_ for _ in ()).throw(RuntimeError('offline')))
            dispatch_reminders(db, config)
            assert reminder.external_reference == 'awaiting-trigger'
            monkeypatch.setattr('app.services.trigger_service.schedule_wakeup', lambda *a, **k: 'run_test')
            dispatch_reminders(db, config)
            assert reminder.external_reference == 'run_test'
            from app.integrations.trigger_client import callback_signature
            auth = {'Authorization':'Bearer '+callback_signature(config,memory['id'],reminder.id)}
            assert client.post('/api/triggers/callback', json={'memory_id':memory['id'],'trigger_id':reminder.id},headers=auth).status_code == 409
        event = {**memory['event'], 'needs_confirmation': True, 'starts_at':None}
        assert client.put('/api/calendar/events/'+memory['id'], json=event).status_code == 422


def test_ambiguous_event_requires_confirmation_before_calendar_or_reminder(tmp_path):
    class AI(DemoProvider):
        def extract(self, payload):
            result = super().extract(payload)
            result.event = EventDetails(title='Jalsa', date_text='Saturday 13 September', location='Hyderabad',
                starts_at=None, ends_at=None, needs_confirmation=True, clarification='Which year?')
            return result
    app = create_app(Settings(database_url=f'sqlite:///{tmp_path}/events.db', demo_mode=True,
        api_token='test', _env_file=None), ai=AI())
    with TestClient(app, headers={'Authorization':'Bearer test'}) as client:
        memory = client.post('/api/captures', json={'visible_text':'Event poster'}).json()
        with app.state.sessions() as db:
            assert db.scalar(select(Trigger)) is None
        url = client.get('/api/calendar/subscription').json()['url'].replace('http://localhost:8000','')
        assert 'BEGIN:VEVENT' not in client.get(url).text
        body = {**memory['event'], 'starts_at':(now()+timedelta(days=1)).isoformat(), 'needs_confirmation':False,'clarification':None}
        for _ in range(2):
            assert client.put('/api/calendar/events/'+memory['id'], json=body).status_code == 200
        with app.state.sessions() as db:
            assert len(db.scalars(select(Trigger)).all()) == 1
        assert 'SUMMARY:Jalsa' in client.get(url).text


def test_partial_event_metadata_preserved_without_scheduling(tmp_path):
    from app.domain.schemas import EventMetadata
    from app.domain.models import Action
    class AI(DemoProvider):
        def extract(self, payload):
            result = super().extract(payload)
            result.event = EventDetails(title='Jalsa', date_text='Saturday 13 September, 3 PM–10 PM',
                location='Hyderabad', starts_at='2026-09-13T15:00:00+05:30',
                ends_at='2026-09-13T22:00:00+05:30', needs_confirmation=False, clarification=None,
                metadata=EventMetadata(year=None, month=9, day=13, start_time='15:00', end_time='22:00',
                    timezone=None, venue='Ramky One Kosmos', address=None, organizer=None,
                    registration_url=None, evidence=['Saturday 13 September', '3 PM–10 PM'], missing_fields=[]))
            return result
    app = create_app(Settings(database_url=f'sqlite:///{tmp_path}/partial.db', demo_mode=True,
        api_token='test', _env_file=None), ai=AI())
    with TestClient(app, headers={'Authorization': 'Bearer test'}) as client:
        memory = client.post('/api/captures', json={'visible_text': 'Jalsa poster'}).json()
        assert memory['event']['metadata']['month'] == 9
        assert memory['event']['metadata']['missing_fields'] == ['year', 'timezone']
        assert memory['event']['needs_confirmation'] is True
        assert memory['event_date'] is None
        with app.state.sessions() as db:
            assert db.scalar(select(Trigger)) is None
            assert db.scalar(select(Action).where(Action.type == 'add_to_calendar')).status == 'needs_confirmation'
        confirmed = {**memory['event'], 'starts_at': (now()+timedelta(days=2)).isoformat(),
                     'ends_at': (now()+timedelta(days=2, hours=2)).isoformat(),
                     'needs_confirmation': False, 'clarification': None}
        response = client.put('/api/calendar/events/'+memory['id'], json=confirmed)
        assert response.status_code == 200
        assert response.json()['event']['needs_confirmation'] is False
        with app.state.sessions() as db:
            assert db.scalar(select(Trigger)) is not None
