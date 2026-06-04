"""
Conversation persistence (Cosmos DB).

Maps a Teams `conversation_id` to a durable Azure AI Foundry `thread_id` so multi-turn
context survives across messages, and records each Q&A turn.

Schema (matches infra/modules/cosmos-db.bicep):
  - container `threads`        (partition key /userId): one item per Teams conversation,
                                holding the Foundry thread id.
  - container `conversations`  (partition key /threadId): one item per Q&A turn.

`APP_MODE=local` uses in-memory dicts so the mapping + turn history are testable
without a Cosmos account.
"""

import logging
import time
import uuid

from config import get_settings

logger = logging.getLogger(__name__)

_THREADS = "threads"
_CONVERSATIONS = "conversations"


class ConversationStore:
    """Thread mapping + turn history backed by Cosmos DB (or in-memory locally)."""

    def __init__(self) -> None:
        self.settings = get_settings()
        self._client = None
        self._threads = None
        self._conversations = None
        # local fakes
        self._local_threads: dict[str, dict] = {}
        self._local_turns: list[dict] = []

    async def _ensure_containers(self):
        if self._threads is not None:
            return
        from azure.cosmos.aio import CosmosClient
        from azure.identity.aio import DefaultAzureCredential

        credential = DefaultAzureCredential(
            managed_identity_client_id=self.settings.managed_identity_client_id
        )
        self._client = CosmosClient(self.settings.cosmos_endpoint, credential=credential)
        db = self._client.get_database_client(self.settings.cosmos_database)
        self._threads = db.get_container_client(_THREADS)
        self._conversations = db.get_container_client(_CONVERSATIONS)

    async def get_thread_id(self, conversation_id: str, user_id: str) -> str | None:
        """Return the Foundry thread id mapped to this conversation, or None."""
        if self.settings.is_local:
            item = self._local_threads.get(conversation_id)
            return item["threadId"] if item else None

        await self._ensure_containers()
        try:
            item = await self._threads.read_item(item=conversation_id, partition_key=user_id)
            return item.get("threadId")
        except Exception:
            return None

    async def save_thread_id(self, conversation_id: str, user_id: str, thread_id: str) -> None:
        """Persist the conversation -> thread mapping."""
        item = {
            "id": conversation_id,
            "userId": user_id,
            "threadId": thread_id,
            "updatedAt": _now_iso(),
        }
        if self.settings.is_local:
            self._local_threads[conversation_id] = item
            return
        await self._ensure_containers()
        await self._threads.upsert_item(item)

    async def append_turn(
        self, thread_id: str, user_id: str, question: str, answer: str
    ) -> None:
        """Record a single Q&A turn under its thread."""
        item = {
            "id": str(uuid.uuid4()),
            "threadId": thread_id,
            "userId": user_id,
            "question": question,
            "answer": answer,
            "timestamp": _now_iso(),
        }
        if self.settings.is_local:
            self._local_turns.append(item)
            return
        await self._ensure_containers()
        await self._conversations.create_item(item)

    async def get_turns(self, thread_id: str) -> list[dict]:
        """Return stored turns for a thread (used for history/analytics; ordered)."""
        if self.settings.is_local:
            return [t for t in self._local_turns if t["threadId"] == thread_id]

        await self._ensure_containers()
        query = "SELECT * FROM c WHERE c.threadId = @tid ORDER BY c.timestamp ASC"
        params = [{"name": "@tid", "value": thread_id}]
        return [
            item
            async for item in self._conversations.query_items(
                query=query, parameters=params, partition_key=thread_id
            )
        ]

    async def close(self) -> None:
        if self._client is not None:
            await self._client.close()


def _now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
