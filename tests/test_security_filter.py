"""PR3 — security trimming is always applied and correctly scopes per user."""

from ai_foundry_client import AIFoundryClient
from graph_client import CallerIdentity, GraphClient
from search_client import SearchService, build_security_filter


def test_filter_groups_and_user_use_search_in():
    ident = CallerIdentity(oid="u-1", group_ids=["g1", "g2"])
    f = build_security_filter(ident)
    assert "allowedGroups/any(g: search.in(g, 'g1,g2', ','))" in f
    assert "allowedUsers/any(u: search.in(u, 'u-1', ','))" in f


def test_filter_without_groups_still_scopes_by_user():
    f = build_security_filter(CallerIdentity(oid="u-1", group_ids=[]))
    assert "allowedGroups" not in f
    assert "allowedUsers/any(u: search.in(u, 'u-1', ','))" in f


async def _identity(key: str) -> CallerIdentity:
    return await GraphClient().get_caller_identity(f"local-graph-token:{key}")


async def test_local_search_trims_engineering_doc_to_alice_only():
    svc = SearchService()
    alice = await _identity("alice")
    bob = await _identity("bob")

    alice_hits = {r.id for r in await svc.search("deploy process", alice)}
    bob_hits = {r.id for r in await svc.search("deploy process", bob)}

    assert "doc-deploy-runbook" in alice_hits   # alice is in grp-engineering
    assert "doc-deploy-runbook" not in bob_hits  # bob is not — trimmed out


async def test_pipeline_answer_is_grounded_and_trimmed():
    client = AIFoundryClient()
    alice = await _identity("alice")
    bob = await _identity("bob")

    alice_answer = await client.query_agent("deploy process", alice, "c-a", "alice")
    bob_answer = await client.query_agent("deploy process", bob, "c-b", "bob")

    # alice gets the engineering runbook with a citation; bob cannot access it.
    assert "Runbook.aspx" in alice_answer
    assert "Runbook.aspx" not in bob_answer
    assert "don't have information" in bob_answer
