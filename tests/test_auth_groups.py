"""PR2 — auth, OBO, and Entra group-resolution behavior (offline, APP_MODE=local)."""

import pytest

from ai_foundry_client import build_security_filter
from bot_handler import BotHandler
from graph_client import CallerIdentity, GraphClient


# ----------------------------------------------------------------- group resolution
async def test_local_directory_users_resolve_to_different_groups():
    g = GraphClient()
    alice = await g.get_caller_identity("local-graph-token:alice")
    bob = await g.get_caller_identity("local-graph-token:bob")

    assert "grp-engineering" in alice.group_ids
    assert "grp-sales" in bob.group_ids
    assert alice.oid != bob.oid


async def test_identity_is_cached():
    g = GraphClient()
    first = await g.get_caller_identity("local-graph-token:alice")
    second = await g.get_caller_identity("local-graph-token:alice")
    assert first is second


async def test_unknown_user_gets_minimal_membership():
    g = GraphClient()
    ident = await g.get_caller_identity("local-graph-token:carol")
    assert ident.group_ids == ["grp-allstaff"]


# ------------------------------------------------------------------ security filter
def test_security_filter_uses_search_in_for_groups_and_user():
    ident = CallerIdentity(oid="user-1", group_ids=["g1", "g2"])
    f = build_security_filter(ident)
    assert "allowedGroups/any(g: search.in(g, 'g1,g2', ','))" in f
    assert "allowedUsers/any(u: search.in(u, 'user-1', ','))" in f
    assert " or " in f


def test_security_filter_without_groups_still_scopes_by_user():
    ident = CallerIdentity(oid="user-1", group_ids=[])
    f = build_security_filter(ident)
    assert "allowedGroups" not in f
    assert "allowedUsers/any(u: search.in(u, 'user-1', ','))" in f


# ------------------------------------------------------------------------- OBO flow
async def test_obo_exchange_local_is_deterministic():
    handler = BotHandler()
    token = await handler.exchange_obo("alice", ["https://graph.microsoft.com/.default"])
    assert token == "local-graph-token:alice"


# --------------------------------------------------------------------- turn routing
async def test_message_turn_runs_pipeline_with_resolved_identity():
    handler = BotHandler()
    captured = {}

    async def pipeline(query, identity, conversation_id, user_id):
        captured["identity"] = identity
        captured["conversation_id"] = conversation_id
        return f"answer to {query}"

    body = {
        "type": "message",
        "text": "  hello  ",
        "from": {"id": "u1", "aadObjectId": "bob"},
        "conversation": {"id": "c1"},
    }
    result = await handler.handle_turn(body, "", pipeline)

    assert result.status_code == 200
    assert result.body["text"] == "answer to hello"
    assert "grp-sales" in captured["identity"].group_ids
    assert captured["conversation_id"] == "c1"


async def test_token_exchange_invoke_is_acknowledged():
    handler = BotHandler()

    async def pipeline(*_):
        raise AssertionError("pipeline must not run on a token-exchange invoke")

    body = {
        "type": "invoke",
        "name": "signin/tokenExchange",
        "from": {"id": "u1"},
        "value": {"token": "alice"},
    }
    result = await handler.handle_turn(body, "", pipeline)
    assert result.status_code == 200
    assert result.body["status"] == "tokenExchanged"


async def test_non_message_activity_is_a_noop():
    handler = BotHandler()

    async def pipeline(*_):
        raise AssertionError("pipeline must not run for non-message activities")

    body = {"type": "conversationUpdate", "from": {"id": "u1"}}
    result = await handler.handle_turn(body, "", pipeline)
    assert result.status_code == 200


async def test_empty_message_is_a_noop():
    handler = BotHandler()

    async def pipeline(*_):
        raise AssertionError("pipeline must not run for empty text")

    body = {"type": "message", "text": "   ", "from": {"id": "u1", "aadObjectId": "alice"}}
    result = await handler.handle_turn(body, "", pipeline)
    assert result.status_code == 200
