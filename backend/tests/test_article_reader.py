import socket
import pytest
from fastapi.testclient import TestClient
from app.core.config import Settings
from app.main import create_app
from app.integrations.article_reader import ArticleParser, public_address, image_url
from app.integrations.openai_client import DemoProvider


def test_extract_article_and_preferred_image():
    parser = ArticleParser('https://example.com/story')
    parser.feed('''<html><head><title>Article title</title><meta property="og:image" content="/hero.jpg"></head>
    <body><nav>Ignore navigation</nav><main><article><h1>Python research</h1><p>The useful article text.</p>
    <script>Ignore script</script><img src="/other.jpg"></article></main><footer>Ignore footer</footer></body></html>''')
    data = parser.result()
    assert data['title'] == 'Article title'
    assert data['image_url'] == 'https://example.com/hero.jpg'
    assert data['text'] == 'Python research\nThe useful article text.'


def test_fallback_to_main_and_article_image():
    parser = ArticleParser('https://example.com/story/')
    parser.feed('<nav>Menu</nav><main><p>Useful text</p><img src="photo.jpg"></main>')
    assert parser.result()['image_url'] == 'https://example.com/story/photo.jpg'
    assert parser.result()['text'] == 'Useful text'
    assert image_url('javascript:alert(1)') is None
    assert image_url('http://127.0.0.1/private') is None


@pytest.mark.parametrize('address', ['127.0.0.1', '10.0.0.1', '169.254.169.254', '::1'])
def test_private_resolved_addresses_rejected(monkeypatch, address):
    monkeypatch.setattr(socket, 'getaddrinfo', lambda *a, **k: [(socket.AF_INET, socket.SOCK_STREAM, 6, '', (address, 80))])
    with pytest.raises(ValueError, match='public'):
        public_address('http://public-looking.example/article')


def test_enrichment_reaches_ai_and_dashboard_and_keeps_original(tmp_path, monkeypatch):
    seen = []
    class Spy(DemoProvider):
        def extract(self, payload):
            seen.append(payload)
            return super().extract(payload)
    config = Settings(database_url=f'sqlite:///{tmp_path}/test.db', demo_mode=False,
                      openai_api_key='test', api_token='test', _env_file=None)
    monkeypatch.setattr('app.services.capture_service.read_article', lambda url: {
        'title': 'Python research', 'text': 'Python makes programming accessible.',
        'description': 'Research article', 'image_url': 'https://example.com/photo.jpg'})
    with TestClient(create_app(config, ai=Spy()), headers={'Authorization': 'Bearer test'}) as client:
        response = client.post('/api/captures', json={'source_url': 'https://example.com/article'})
        assert response.status_code == 201, response.text
        memory = response.json()
        assert seen[0]['visible_text'] == 'Python makes programming accessible.'
        assert memory['image_url'] == 'https://example.com/photo.jpg'
        assert memory['reading_status'] == 'read'
        assert 'Python' in memory['topics']
        detail = client.get('/api/memories/' + memory['id']).json()
        assert detail['raw_capture']['visible_text'] == ''
        assert detail['raw_capture']['article']['text'] == seen[0]['visible_text']
        assert client.get('/api/memories').json()[0]['image_url'] == memory['image_url']
        def unavailable(url):
            raise OSError('blocked')
        monkeypatch.setattr('app.services.capture_service.read_article', unavailable)
        failed = client.post('/api/captures', json={'source_url': 'https://example.com/blocked'}).json()
        assert failed['reading_status'] == 'unavailable'
        assert failed['image_url'] is None
        assert 'not been read' in failed['summary']
        browser = client.post('/api/captures', json={'source_url': 'https://example.com/private-article',
            'visible_text': 'Python article from the browser.', 'image_url': 'https://example.com/cover.jpg'}).json()
        assert browser['reading_status'] == 'provided_text'
        assert browser['image_url'] == 'https://example.com/cover.jpg'


def test_reader_pins_public_connection_and_rejects_private_redirect(monkeypatch):
    import app.integrations.article_reader as reader
    from email.message import Message
    connections = []
    addresses = []
    class Response:
        status = 200
        headers = Message()
        def getheader(self, name, default=None):
            return {'Content-Type': 'text/html', 'Location': 'http://127.0.0.1/secret'}.get(name, default)
        def read(self, size):
            if getattr(self, 'done', False):
                return b''
            self.done = True
            return b'<article><p>Actual article content.</p></article>'
    class Connection:
        def __init__(self, host, port, timeout):
            connections.append(self)
        def request(self, method, path, headers):
            assert method == 'GET'
            assert path == '/article'
        def getresponse(self):
            return Response()
        def close(self):
            pass
    def resolve(host, port, **kwargs):
        address = '127.0.0.1' if host == '127.0.0.1' else '93.184.216.34'
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, '', (address, port))]
    monkeypatch.setattr(socket, 'getaddrinfo', resolve)
    monkeypatch.setattr(socket, 'create_connection', lambda address, timeout: addresses.append(address))
    monkeypatch.setattr(reader.http.client, 'HTTPConnection', Connection)
    assert reader.read_article('http://example.com/article')['text'] == 'Actual article content.'
    assert addresses == [('93.184.216.34', 80)]
    Response.status = 302
    with pytest.raises(ValueError, match='public'):
        reader.read_article('http://example.com/article')
    assert len(connections) == 2
