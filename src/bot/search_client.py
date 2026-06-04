"""
Security-trimmed retrieval over Azure AI Search.

Every query is scoped to the signed-in user with an OData filter built from their
resolved identity (object id + transitive groups). Five strategies are supported so
the tradeoffs are easy to compare:

  keyword          - lexical BM25 only
  vector           - pure ANN vector similarity (integrated vectorization)
  hybrid           - keyword + vector (RRF fusion)
  semantic         - keyword + semantic L2 reranker
  hybrid_semantic  - keyword + vector + semantic reranker (best relevance; default)

`APP_MODE=local` runs the same trimming + strategy selection against the in-memory
sample corpus so per-user trimming is testable without an Azure AI Search instance.
"""

import logging
from dataclasses import dataclass
from enum import Enum

from config import get_settings
from graph_client import CallerIdentity
from sample_corpus import SAMPLE_DOCS

logger = logging.getLogger(__name__)

_SELECT_FIELDS = ["id", "title", "content", "source_url"]
_VECTOR_FIELD = "contentVector"


class SearchStrategy(str, Enum):
    KEYWORD = "keyword"
    VECTOR = "vector"
    HYBRID = "hybrid"
    SEMANTIC = "semantic"
    HYBRID_SEMANTIC = "hybrid_semantic"

    @classmethod
    def parse(cls, value: str) -> "SearchStrategy":
        try:
            return cls(value.strip().lower())
        except ValueError:
            logger.warning("Unknown SEARCH_STRATEGY '%s'; defaulting to hybrid_semantic", value)
            return cls.HYBRID_SEMANTIC

    @property
    def uses_vector(self) -> bool:
        return self in (SearchStrategy.VECTOR, SearchStrategy.HYBRID, SearchStrategy.HYBRID_SEMANTIC)

    @property
    def uses_text(self) -> bool:
        return self is not SearchStrategy.VECTOR

    @property
    def uses_semantic(self) -> bool:
        return self in (SearchStrategy.SEMANTIC, SearchStrategy.HYBRID_SEMANTIC)


@dataclass
class SearchResult:
    id: str
    title: str
    content: str
    source_url: str
    score: float = 0.0


def build_security_filter(identity: CallerIdentity) -> str:
    """
    OData filter trimming results to documents the caller may see.

    Visible if `allowedGroups` intersects the caller's groups OR `allowedUsers`
    contains the caller's object id. `search.in` passes the id list as data (not
    query text), avoiding filter-injection and the per-id `eq` explosion.
    """
    clauses = []
    if identity.group_ids:
        groups_csv = ",".join(identity.group_ids)
        clauses.append(f"allowedGroups/any(g: search.in(g, '{groups_csv}', ','))")
    clauses.append(f"allowedUsers/any(u: search.in(u, '{identity.oid}', ','))")
    return " or ".join(clauses)


class SearchService:
    """Wraps Azure AI Search with always-on security trimming and strategy selection."""

    def __init__(self, strategy: SearchStrategy | None = None) -> None:
        self.settings = get_settings()
        self.strategy = strategy or SearchStrategy.parse(self.settings.search_strategy)
        self._client = None  # lazily constructed azure.search.documents.aio.SearchClient

    async def search(
        self, query: str, identity: CallerIdentity, top: int = 5
    ) -> list[SearchResult]:
        security_filter = build_security_filter(identity)
        logger.info("Search strategy=%s filter=%s", self.strategy.value, security_filter)
        if self.settings.is_local:
            return self._search_local(query, identity, top)
        return await self._search_azure(query, security_filter, top)

    # ------------------------------------------------------------------- azure
    async def _ensure_client(self):
        if self._client is None:
            from azure.identity.aio import DefaultAzureCredential
            from azure.search.documents.aio import SearchClient

            credential = DefaultAzureCredential(
                managed_identity_client_id=self.settings.managed_identity_client_id
            )
            self._client = SearchClient(
                endpoint=self.settings.search_endpoint,
                index_name=self.settings.search_index_name,
                credential=credential,
            )
        return self._client

    async def _search_azure(
        self, query: str, security_filter: str, top: int
    ) -> list[SearchResult]:
        from azure.search.documents.models import VectorizableTextQuery

        client = await self._ensure_client()

        kwargs: dict = {
            "filter": security_filter,  # security trimming — applied on EVERY query
            "top": top,
            "select": _SELECT_FIELDS,
        }
        kwargs["search_text"] = query if self.strategy.uses_text else None
        if self.strategy.uses_vector:
            # Integrated vectorization: the index vectorizer embeds the text server-side,
            # so no embedding call is needed in the app.
            kwargs["vector_queries"] = [
                VectorizableTextQuery(
                    text=query, k_nearest_neighbors=top, fields=_VECTOR_FIELD
                )
            ]
        if self.strategy.uses_semantic:
            kwargs["query_type"] = "semantic"
            kwargs["semantic_configuration_name"] = self.settings.semantic_config_name

        results: list[SearchResult] = []
        async for doc in await client.search(**kwargs):
            results.append(
                SearchResult(
                    id=doc.get("id", ""),
                    title=doc.get("title", "Untitled"),
                    content=doc.get("content", ""),
                    source_url=doc.get("source_url", ""),
                    score=doc.get("@search.reranker_score") or doc.get("@search.score", 0.0),
                )
            )
        return results

    async def close(self) -> None:
        if self._client is not None:
            await self._client.close()

    # ------------------------------------------------------------------- local
    def _search_local(
        self, query: str, identity: CallerIdentity, top: int
    ) -> list[SearchResult]:
        """
        In-memory security trimming + lexical scoring over the sample corpus.

        Local mode approximates ALL strategies with lexical matching — true vector /
        semantic ranking requires a real Azure AI Search index. The point exercised
        offline is security trimming (ACL ∩ caller principals) and result ordering.
        """
        principals = set(identity.principal_ids)
        terms = {t for t in query.lower().split() if len(t) > 2}

        scored: list[SearchResult] = []
        for doc in SAMPLE_DOCS:
            acl = set(doc.get("allowedGroups", [])) | set(doc.get("allowedUsers", []))
            if not (acl & principals):
                continue  # security trimming: caller has no overlapping principal
            haystack = f"{doc['title']} {doc['content']}".lower()
            score = float(sum(haystack.count(t) for t in terms))
            if score > 0:
                scored.append(
                    SearchResult(
                        id=doc["id"],
                        title=doc["title"],
                        content=doc["content"],
                        source_url=doc["source_url"],
                        score=score,
                    )
                )

        scored.sort(key=lambda r: r.score, reverse=True)
        return scored[:top]
