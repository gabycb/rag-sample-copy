"""
AI orchestration: security-trimmed retrieval -> grounded answer -> persisted turn.

For each user message:
  1. Retrieve documents from Azure AI Search, scoped to the caller (security trimming).
  2. Get-or-create a durable Azure AI Foundry thread for the Teams conversation.
  3. Run the Foundry agent (GPT-4o) over the question + retrieved context.
  4. Persist the turn in Cosmos and return a grounded answer with citations.

`APP_MODE=local` skips the Foundry call and synthesizes a grounded answer directly
from the (trimmed) retrieved sample docs, so the whole flow runs offline.
"""

import logging

from config import get_settings
from content_safety import ContentSafetyGuard
from conversation_store import ConversationStore
from graph_client import CallerIdentity
from search_client import SearchResult, SearchService, build_security_filter  # noqa: F401 (re-export)

logger = logging.getLogger(__name__)

_NO_ANSWER = "I don't have information you have access to about this."
_BLOCKED = "I can't help with that request."

_SYSTEM_INSTRUCTIONS = (
    "You are ATLAS-RAG, an enterprise assistant. Answer ONLY from the provided "
    "SharePoint documents. If the answer is not in them, say you don't have access "
    "to that information. Always cite the document titles you used."
)


class AIFoundryClient:
    """Identity-scoped RAG pipeline over Azure AI Search + Azure AI Foundry."""

    def __init__(self) -> None:
        self.settings = get_settings()
        self.search = SearchService()
        self.store = ConversationStore()
        self.guard = ContentSafetyGuard()
        self._project = None  # lazily constructed azure.ai.projects.aio.AIProjectClient

    async def query_agent(
        self,
        query: str,
        caller_identity: CallerIdentity,
        conversation_id: str,
        user_id: str,
    ) -> str:
        # 1. Retrieve (always security-trimmed to the caller).
        results = await self.search.search(query, caller_identity, top=5)

        # 2. Prompt Shields: check the user prompt AND the (attacker-influenceable)
        #    retrieved documents for injection before they reach the model.
        shield = await self.guard.check_input(query, [r.content for r in results])
        if shield.blocked:
            logger.warning("Blocked by content safety: %s", shield.reason)
            return _BLOCKED

        # 3. Durable thread for this Teams conversation.
        thread_id = await self.store.get_thread_id(conversation_id, user_id)

        # 4. Generate the answer.
        if self.settings.is_local:
            thread_id = thread_id or f"local-thread-{conversation_id}"
            answer = self._synthesize_local(query, results)
        else:
            thread_id, answer = await self._run_foundry_agent(query, results, thread_id)

        # 5. Persist.
        await self.store.save_thread_id(conversation_id, user_id, thread_id)
        await self.store.append_turn(thread_id, user_id, query, answer)
        return answer

    # ------------------------------------------------------------- context/cite
    @staticmethod
    def _build_context(results: list[SearchResult]) -> str:
        if not results:
            return "No accessible documents were found."
        blocks = []
        for i, r in enumerate(results, 1):
            blocks.append(f"[{i}] {r.title} ({r.source_url})\n{r.content}")
        return "\n\n".join(blocks)

    @staticmethod
    def _citations(results: list[SearchResult]) -> str:
        return "\n".join(f"- {r.title}: {r.source_url}" for r in results)

    # -------------------------------------------------------------- local synth
    def _synthesize_local(self, query: str, results: list[SearchResult]) -> str:
        if not results:
            return _NO_ANSWER
        top = results[0]
        return (
            f"Based on {len(results)} document(s) you can access:\n\n"
            f"{top.content}\n\nSources:\n{self._citations(results)}"
        )

    # -------------------------------------------------------------- foundry call
    async def _ensure_project(self):
        if self._project is None:
            from azure.ai.projects.aio import AIProjectClient
            from azure.identity.aio import DefaultAzureCredential

            credential = DefaultAzureCredential(
                managed_identity_client_id=self.settings.managed_identity_client_id
            )
            # NOTE: AZURE_AI_PROJECT_ENDPOINT must be the Foundry project endpoint
            # (https://<resource>.services.ai.azure.com/api/projects/<project>).
            self._project = AIProjectClient(
                endpoint=self.settings.ai_project_endpoint, credential=credential
            )
        return self._project

    async def _run_foundry_agent(
        self, query: str, results: list[SearchResult], thread_id: str | None
    ) -> tuple[str, str]:
        """Run the Foundry agent over the retrieved context. Returns (thread_id, answer)."""
        project = await self._ensure_project()
        agents = project.agents

        if not thread_id:
            thread = await agents.threads.create()
            thread_id = thread.id

        prompt = (
            f"{_SYSTEM_INSTRUCTIONS}\n\nQuestion: {query}\n\n"
            f"Documents:\n{self._build_context(results)}"
        )
        await agents.messages.create(thread_id=thread_id, role="user", content=prompt)
        run = await agents.runs.create_and_process(
            thread_id=thread_id, agent_id=self.settings.ai_agent_id
        )
        if getattr(run, "status", None) == "failed":
            logger.error("Foundry run failed: %s", getattr(run, "last_error", None))
            return thread_id, "Sorry, I couldn't generate an answer just now."

        answer = await self._latest_assistant_text(agents, thread_id)
        if results:
            answer = f"{answer}\n\nSources:\n{self._citations(results)}"
        return thread_id, answer or _NO_ANSWER

    @staticmethod
    async def _latest_assistant_text(agents, thread_id: str) -> str:
        async for message in agents.messages.list(thread_id=thread_id, order="desc"):
            if getattr(message, "role", None) == "assistant":
                for part in getattr(message, "text_messages", []) or []:
                    return part.text.value
                break
        return ""

    async def close(self) -> None:
        await self.search.close()
        await self.store.close()
        if self._project is not None:
            await self._project.close()
