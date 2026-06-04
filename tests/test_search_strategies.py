"""PR3 — strategy parsing/selection and the Azure query shape (with fake SDK)."""

import sys
import types

import pytest

from graph_client import CallerIdentity
from search_client import SearchService, SearchStrategy


# --------------------------------------------------------------- parsing / flags
def test_parse_known_and_unknown():
    assert SearchStrategy.parse("hybrid") is SearchStrategy.HYBRID
    assert SearchStrategy.parse("KEYWORD") is SearchStrategy.KEYWORD
    assert SearchStrategy.parse("nonsense") is SearchStrategy.HYBRID_SEMANTIC  # default


@pytest.mark.parametrize(
    "strategy,text,vector,semantic",
    [
        (SearchStrategy.KEYWORD, True, False, False),
        (SearchStrategy.VECTOR, False, True, False),
        (SearchStrategy.HYBRID, True, True, False),
        (SearchStrategy.SEMANTIC, True, False, True),
        (SearchStrategy.HYBRID_SEMANTIC, True, True, True),
    ],
)
def test_strategy_flag_matrix(strategy, text, vector, semantic):
    assert strategy.uses_text is text
    assert strategy.uses_vector is vector
    assert strategy.uses_semantic is semantic


# ---------------------------------------------------- azure query shape (mocked)
class _FakeAsyncResults:
    def __init__(self, docs):
        self._docs = docs

    def __aiter__(self):
        async def gen():
            for d in self._docs:
                yield d

        return gen()


class _FakeSearchClient:
    def __init__(self, recorder):
        self._recorder = recorder

    async def search(self, **kwargs):
        self._recorder.update(kwargs)
        return _FakeAsyncResults([])

    async def close(self):
        pass


@pytest.fixture
def fake_search_models(monkeypatch):
    """Inject a fake azure.search.documents.models so _search_azure can import it."""
    models = types.ModuleType("azure.search.documents.models")

    class VectorizableTextQuery:
        def __init__(self, **kw):
            self.kw = kw

    models.VectorizableTextQuery = VectorizableTextQuery
    monkeypatch.setitem(sys.modules, "azure.search.documents.models", models)
    return models


async def _run_azure(monkeypatch, strategy) -> dict:
    monkeypatch.setenv("APP_MODE", "azure")
    import config

    config.get_settings.cache_clear()

    svc = SearchService(strategy=strategy)
    recorder: dict = {}
    fake = _FakeSearchClient(recorder)
    monkeypatch.setattr(svc, "_ensure_client", lambda: _coro(fake))
    await svc.search("hello world", CallerIdentity(oid="u-1", group_ids=["g1"]), top=3)
    return recorder


async def _coro(value):
    return value


async def test_azure_keyword_sets_text_filter_no_vector(monkeypatch, fake_search_models):
    rec = await _run_azure(monkeypatch, SearchStrategy.KEYWORD)
    assert rec["search_text"] == "hello world"
    assert "vector_queries" not in rec
    assert "query_type" not in rec
    assert "allowedGroups/any" in rec["filter"]  # trimming always present


async def test_azure_vector_has_vector_no_text(monkeypatch, fake_search_models):
    rec = await _run_azure(monkeypatch, SearchStrategy.VECTOR)
    assert rec["search_text"] is None
    assert len(rec["vector_queries"]) == 1
    assert "allowedUsers/any" in rec["filter"]


async def test_azure_hybrid_semantic_has_everything(monkeypatch, fake_search_models):
    rec = await _run_azure(monkeypatch, SearchStrategy.HYBRID_SEMANTIC)
    assert rec["search_text"] == "hello world"
    assert len(rec["vector_queries"]) == 1
    assert rec["query_type"] == "semantic"
    assert rec["semantic_configuration_name"]
    assert rec["filter"]  # trimming always present
