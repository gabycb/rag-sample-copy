"""PR3 — Cosmos-backed conversation/thread mapping (offline, in-memory)."""

from conversation_store import ConversationStore


async def test_thread_mapping_round_trips():
    store = ConversationStore()
    assert await store.get_thread_id("conv-1", "alice") is None

    await store.save_thread_id("conv-1", "alice", "thread-abc")
    assert await store.get_thread_id("conv-1", "alice") == "thread-abc"


async def test_turns_are_recorded_per_thread():
    store = ConversationStore()
    await store.append_turn("thread-abc", "alice", "q1", "a1")
    await store.append_turn("thread-abc", "alice", "q2", "a2")
    await store.append_turn("thread-xyz", "bob", "q3", "a3")

    abc = await store.get_turns("thread-abc")
    xyz = await store.get_turns("thread-xyz")

    assert [t["question"] for t in abc] == ["q1", "q2"]
    assert [t["answer"] for t in xyz] == ["a3"]


async def test_unknown_thread_has_no_turns():
    store = ConversationStore()
    assert await store.get_turns("nope") == []
