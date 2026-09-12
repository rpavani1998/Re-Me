import json
import httpx
import pytest
from app.integrations.ambiguous_client import AmbiguousClient


def test_authenticated_mcp_handshake_and_tool_call():
    seen = []
    def respond(request):
        assert request.headers['authorization'] == 'Bearer test-key'
        body = json.loads(request.content)
        seen.append(body['method'])
        if body['method'] == 'initialize':
            return httpx.Response(200, headers={'mcp-session-id':'session'}, json={'jsonrpc':'2.0','id':body['id'], 'result':{'protocolVersion':'2024-11-05'}})
        assert request.headers['mcp-session-id'] == 'session'
        if body['method'] == 'notifications/initialized':
            return httpx.Response(202)
        data = {'jsonrpc':'2.0','id':body['id'],'result':{'content':[{'type':'text','text':json.dumps({'data':[{'id':'calendar'}]})}]}}
        return httpx.Response(200, headers={'content-type':'text/event-stream'}, text='event: message\ndata: '+json.dumps(data)+'\n\n')
    with AmbiguousClient('test-key', transport=httpx.MockTransport(respond)) as client:
        assert client.call('list_calendars')['data'][0]['id'] == 'calendar'
    assert seen == ['initialize','notifications/initialized','tools/call']


def test_tool_errors_do_not_leak_provider_messages():
    def respond(request):
        body=json.loads(request.content)
        return httpx.Response(200,json={'jsonrpc':'2.0','id':body['id'],'result':{'isError':True,'content':[{'type':'text','text':'sensitive provider details'}]}})
    client=AmbiguousClient('test-key',transport=httpx.MockTransport(respond))
    try:
        with pytest.raises(ValueError, match='could not complete list_calendars'):
            client.call('list_calendars')
    finally: client.http.close()


def test_sync_is_account_scoped_and_does_not_repeat_writes(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient
    from app.main import create_app
    from app.core.config import Settings
    from app.domain.models import Account
    calls=[]
    class Remote:
        def __init__(self, key): pass
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def call(self, name, arguments):
            calls.append((name,arguments))
            return {'id':'remote-task'}
    monkeypatch.setattr('app.services.ambiguous_sync.AmbiguousClient',Remote)
    config=Settings(database_url=f'sqlite:///{tmp_path}/test.db',demo_mode=True,api_token='test',
        ambiguous_api_key='test-key',ambiguous_owner_email='owner@example.com',_env_file=None)
    with TestClient(create_app(config),headers={'Authorization':'Bearer test'}) as client:
        memory=client.post('/api/captures',json={'visible_text':'Apply by 2030-01-02.'}).json()
        path=f'/api/integrations/ambiguous/memories/{memory["id"]}/sync'
        assert client.post(path).status_code==403
        with client.app.state.sessions() as db:
            db.add(Account(user_id=config.user_id,email='owner@example.com'))
            db.commit()
        assert client.post(path).json()['status']=='completed'
        assert client.post(path).json()['status']=='completed'
        assert len(calls)==1
        assert calls[0][0]=='create_task'


def test_background_sync_only_processes_owners_ready_events(tmp_path, monkeypatch):
    from app.core.config import Settings
    from app.core.database import make_database, initialize
    from app.domain.models import Account, User, Memory, RawCapture, Action
    from app.services.ambiguous_sync import sync_pending_events
    config=Settings(database_url=f'sqlite:///{tmp_path}/sync.db', demo_mode=True, ambiguous_api_key='key',
                    ambiguous_calendar_id='calendar', ambiguous_owner_email='owner@example.com', _env_file=None)
    engine,sessions=make_database(config.database_url);initialize(engine)
    with sessions() as db:
        for uid,email in [('owner','owner@example.com'),('other','other@example.com')]:
            db.add(User(id=uid));db.flush();db.add(Account(user_id=uid,email=email))
            raw=RawCapture(user_id=uid,request_id=uid,payload={},status='complete');db.add(raw);db.flush()
            memory=Memory(user_id=uid,raw_capture_id=raw.id,type='event',title='Event',summary='Event',embedding=[0.0]*1536,
                          embedding_model='test',interpretation_provider='test')
            db.add(memory);db.flush();db.add(Action(user_id=uid,memory_id=memory.id,type='add_to_calendar',status='ready',payload={}))
        db.commit()
    calls=[]
    def sync(db,user_id,memory_id,config):
        calls.append(user_id)
        db.add(Action(user_id=user_id,memory_id=memory_id,type='ambiguous_sync',status='completed',payload={}))
        db.commit()
    monkeypatch.setattr('app.services.ambiguous_sync.sync_memory',sync)
    sync_pending_events(sessions,config);sync_pending_events(sessions,config)
    assert calls==['owner']
    engine.dispose()
