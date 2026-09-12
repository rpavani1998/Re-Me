"""Small, bounded adapter for Exa search. Results are never persisted as memories."""
import httpx


class ExaClient:
    endpoint = "https://api.exa.ai/search"

    def __init__(self, api_key: str, client=None):
        if not api_key:
            raise ValueError("EXA_API_KEY is required for discovery")
        self.api_key = api_key
        self.client = client or httpx.Client(timeout=20)

    def search(self, query: str, limit: int = 6):
        response = self.client.post(self.endpoint, headers={"x-api-key": self.api_key}, json={
            "query": query[:4000], "type": "auto", "numResults": max(1, min(limit, 6)),
            "contents": {"text": {"maxCharacters": 1200}},
        })
        response.raise_for_status()
        results = response.json().get("results", [])
        return [{"title": str(item.get("title") or "Untitled")[:500],
                 "url": str(item.get("url") or "")[:2000],
                 "summary": str((item.get("text") or item.get("highlights") or ""))[:1200]}
                for item in results if item.get("url")][:6]
