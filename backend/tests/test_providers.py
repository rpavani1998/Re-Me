import json
import httpx
import pytest
from openai import OpenAI
from app.core.config import Settings
from app.integrations.openai_client import provider, OpenRouterProvider, OpenAIProvider, DemoProvider
from app.domain.schemas import ContextUnderstanding


def test_openrouter_only_key_is_sufficient():
    config = Settings(llm_provider="openrouter", openrouter_api_key="or-test", openai_api_key="",
                      api_token="test", _env_file=None)
    config.validate_runtime()
    assert isinstance(provider(config), OpenRouterProvider)


def test_openai_requires_its_own_key():
    with pytest.raises(RuntimeError, match="OPENAI_API_KEY"):
        Settings(llm_provider="openai", openrouter_api_key="or-test", api_token="test", _env_file=None).validate_runtime()


def test_demo_needs_no_ai_key():
    config = Settings(demo_mode=True, api_token="test", _env_file=None)
    config.validate_runtime()
    assert isinstance(provider(config), DemoProvider)


def test_openrouter_structured_and_embedding_requests():
    requests = []
    def respond(request):
        requests.append((request.url.path, json.loads(request.content)))
        assert request.headers["authorization"] == "Bearer or-test"
        if request.url.path.endswith("/embeddings"):
            return httpx.Response(200, json={"data": [{"index": 0, "object": "embedding", "embedding": [0.1] * 1536}],
                                            "model": "openai/text-embedding-3-small", "object": "list", "usage": {"prompt_tokens": 1, "total_tokens": 1}})
        return httpx.Response(200, json={"id": "test", "object": "chat.completion", "created": 1, "model": "test",
            "choices": [{"index": 0, "finish_reason": "stop", "message": {"role": "assistant", "content": json.dumps({
                "activity": "browsing", "intent": None, "topics": [], "entities": [], "confidence": 0.2})}}]})
    ai = provider(Settings(llm_provider="openrouter", openrouter_api_key="or-test", _env_file=None))
    ai.client = OpenAI(api_key="or-test", base_url="https://openrouter.ai/api/v1",
                       http_client=httpx.Client(transport=httpx.MockTransport(respond)))
    ai.embedding_client = ai.client
    assert ai.context([]).confidence == 0.2
    assert len(ai.embed("test")) == 1536
    assert requests[0][0] == "/api/v1/chat/completions"
    assert requests[0][1]["response_format"]["json_schema"]["strict"] is True
    assert requests[0][1]["provider"]["require_parameters"] is True
    assert requests[1][1]["model"] == "openai/text-embedding-3-small"


@pytest.mark.parametrize('provider_class', [OpenRouterProvider, OpenAIProvider])
def test_image_extraction_sends_pixels_without_surrounding_page(provider_class):
    from types import SimpleNamespace
    result = DemoProvider().extract({'page_title': 'Visible scene'})
    requests = []
    def respond(**kwargs):
        requests.append(kwargs)
        return SimpleNamespace(output_parsed=result, choices=[SimpleNamespace(
            finish_reason='stop', message=SimpleNamespace(refusal=None, content=result.model_dump_json()))])
    ai = provider_class(Settings(openai_api_key='test', openrouter_api_key='test', _env_file=None))
    ai.client = SimpleNamespace(responses=SimpleNamespace(parse=respond),
                               chat=SimpleNamespace(completions=SimpleNamespace(create=respond)))
    ai.extract({'source_type': 'image', 'image_url': 'https://example.com/photo.jpg',
                'page_title': 'Unrelated article', 'visible_text': 'Unrelated article body'})
    request = requests[0]
    messages = request.get('messages', request.get('input'))
    content = messages[1]['content']
    assert isinstance(content, list)
    assert 'Unrelated article' not in json.dumps(messages)
    assert 'https://example.com/photo.jpg' in json.dumps(content[1])
    assert 'only what is visibly present' in messages[0]['content']
    with pytest.raises(ValueError, match='public image URL'):
        ai.extract({'source_type': 'image', 'image_url': 'http://localhost/private'})


def test_event_metadata_strict_schema_requires_nested_nullable_fields():
    from app.domain.schemas import Extraction
    from app.integrations.openai_client import strict_schema
    schema = strict_schema(Extraction)
    assert 'event' in schema['required']
    details = schema['$defs']['EventDetails']
    assert 'metadata' in details['required']
    metadata = schema['$defs']['EventMetadata']
    assert set(metadata['required']) == set(metadata['properties'])
    assert metadata['additionalProperties'] is False
    assert 'default' not in details['properties']['metadata']
