from fastapi.testclient import TestClient
from app.core.config import Settings
from app.main import create_app
from app.integrations.openai_client import DemoProvider
from app.services.capture_queue import process_next


def test_save_returns_before_provider_and_worker_finishes_it(tmp_path, monkeypatch):
    monkeypatch.setattr('app.main.process_next', lambda *args: None)
    calls = []
    class Spy(DemoProvider):
        def extract(self, payload):
            calls.append(payload)
            return super().extract(payload)
    config = Settings(database_url=f'sqlite:///{tmp_path}/queue.db', api_token='test', demo_mode=True, _env_file=None)
    app = create_app(config, ai=Spy())
    body = {'request_id':'queue-test','page_title':'Python article','visible_text':'Python programming.'}
    with TestClient(app, headers={'Authorization':'Bearer test'}) as client:
        response = client.post('/api/captures?background=true', json=body)
        assert response.status_code == 202
        assert response.json()['status'] == 'queued'
        assert calls == []
        assert len(client.get('/api/captures/pending').json()) == 1
        assert client.post('/api/captures?background=true', json=body).json()['id'] == response.json()['id']
        process_next(app.state.sessions, app.state.ai, config)
        assert len(calls) == 1
        assert client.get('/api/captures/pending').json() == []
        assert len(client.get('/api/memories').json()) == 1
        assert client.post('/api/captures?background=true', json=body).status_code == 201
        assert len(calls) == 1


def test_failed_processing_preserves_save_and_can_retry(tmp_path, monkeypatch):
    monkeypatch.setattr('app.main.process_next', lambda *args: None)
    class Broken(DemoProvider):
        def extract(self, payload):
            raise RuntimeError('Provider unavailable')
    config = Settings(database_url=f'sqlite:///{tmp_path}/queue.db', api_token='test', demo_mode=True, _env_file=None)
    app = create_app(config, ai=Broken())
    with TestClient(app, headers={'Authorization':'Bearer test'}) as client:
        saved = client.post('/api/captures?background=true', json={'visible_text':'Python programming.'}).json()
        process_next(app.state.sessions, app.state.ai, config)
        assert client.get('/api/captures/pending').json()[0]['status'] == 'failed'
        assert client.get('/api/captures/' + saved['id']).json()['payload']['visible_text'] == 'Python programming.'
        assert client.post('/api/captures/' + saved['id'] + '/retry', headers={'Authorization':'Bearer wrong'}).status_code == 401
        assert client.post('/api/captures/' + saved['id'] + '/retry').status_code == 202
        process_next(app.state.sessions, DemoProvider(), config)
        assert len(client.get('/api/memories').json()) == 1
