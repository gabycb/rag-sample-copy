"""
AI pipeline client (PR2 stage).

This stage wires the *resolved caller identity* (from OBO + Graph group resolution)
into a real AI Search **security-trimming filter**. Retrieval, the Azure AI Foundry
agent call, and Cosmos-backed conversation threads are implemented in PR3 — here the
focus is proving that every query is scoped to the signed-in user's principals.

`APP_MODE=local` returns a deterministic, identity-revealing answer so per-user
trimming is observable end-to-end without Azure.
"""

import logging

from config import get_settings
from graph_client import CallerIdentity

logger = logging.getLogger(__name__)


def build_security_filter(identity: CallerIdentity) -> str:
    """
    OData filter that trims results to documents the caller may see.

    A document is visible if its `allowedGroups` intersects the caller's groups OR
    its `allowedUsers` contains the caller's object id. `search.in` is used (rather
    than string concatenation of `eq`s) so the list is passed as data, not query text.
    """
    groups_csv = ",".join(identity.group_ids)
    user_oid = identity.oid
    clauses = []
    if groups_csv:
        clauses.append(f"allowedGroups/any(g: search.in(g, '{groups_csv}', ','))")
    clauses.append(f"allowedUsers/any(u: search.in(u, '{user_oid}', ','))")
    return " or ".join(clauses)


class AIFoundryClient:
    """Identity-scoped AI pipeline. Retrieval/agent/storage arrive in PR3."""

    def __init__(self) -> None:
        self.settings = get_settings()

    async def query_agent(
        self,
        query: str,
        caller_identity: CallerIdentity,
        conversation_id: str,
        user_id: str,
    ) -> str:
        security_filter = build_security_filter(caller_identity)
        logger.info(
            "Query from %s scoped by filter: %s",
            caller_identity.upn or caller_identity.oid,
            security_filter,
        )

        if self.settings.is_local:
            groups = ", ".join(caller_identity.group_ids) or "(none)"
            return (
                f"[local] You are {caller_identity.upn or caller_identity.oid} "
                f"(groups: {groups}). Search would be trimmed with: {security_filter}. "
                f"You asked: {query}"
            )

        # PR3 implements real retrieval + the Foundry agent call here.
        raise NotImplementedError(
            "Retrieval pipeline is implemented in PR3 (search_client + Foundry agent)."
        )
