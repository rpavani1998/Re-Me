"""Authenticated Ambiguous MCP client; credentials never enter logs or responses."""
import json
import httpx


class AmbiguousClient:
    def __init__(self, key, transport=None):
        if not key:
            raise ValueError('Ambiguous API key is not configured')
        self.http = httpx.Client(base_url='https://app.ambiguous.ai', timeout=25, transport=transport,
            headers={'Authorization':'Bearer '+key, 'Accept':'application/json, text/event-stream'})
        self.sequence = 0

    def __enter__(self):
        result = self.rpc('initialize', {'protocolVersion':'2024-11-05', 'capabilities':{},
            'clientInfo':{'name':'reme','version':'0.1.0'}})
        self.http.headers['MCP-Protocol-Version'] = result.get('protocolVersion','2024-11-05')
        self.http.post('/mcp', json={'jsonrpc':'2.0','method':'notifications/initialized'})
        return self

    def __exit__(self, *args):
        self.http.close()

    def rpc(self, method, params):
        self.sequence += 1
        response = self.http.post('/mcp', json={'jsonrpc':'2.0','id':self.sequence,'method':method,'params':params})
        response.raise_for_status()
        if response.headers.get('mcp-session-id'):
            self.http.headers['mcp-session-id'] = response.headers['mcp-session-id']
        if 'text/event-stream' in response.headers.get('content-type',''):
            messages = [json.loads(line[5:].strip()) for line in response.text.splitlines() if line.startswith('data:')]
            result = next((m for m in messages if m.get('id') == self.sequence), {})
        else:
            result = response.json()
        if 'error' in result:
            raise ValueError('Ambiguous rejected the request')
        if 'result' not in result:
            raise ValueError('Ambiguous returned no result')
        return result['result']

    def call(self, name, arguments=None):
        result = self.rpc('tools/call', {'name':name, 'arguments':arguments or {}})
        if result.get('isError'):
            raise ValueError('Ambiguous could not complete '+name)
        if result.get('structuredContent') is not None:
            return result['structuredContent']
        for item in result.get('content', []):
            if item.get('type') == 'text':
                try:
                    return json.loads(item['text'])
                except (ValueError, KeyError):
                    continue
        raise ValueError('Ambiguous returned no structured data')
