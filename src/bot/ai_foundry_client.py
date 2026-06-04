"""
AI Foundry Agent Client

Orchestrates queries to the Azure AI Foundry Agent Service.
The agent:
- Takes a user's question + their OBO token (for SharePoint access)
- Invokes the SharePoint tool to retrieve relevant documents
- Uses AI Search for hybrid + semantic retrieval (scoped to user permissions)
- Invokes GPT-4o to synthesize an answer
- Returns the answer

This keeps the AI/retrieval logic separate from Teams/bot specifics.
"""

import os
import logging
from typing import Optional
from azure.identity import DefaultAzureCredential, ManagedIdentityCredential
from azure.ai.projects import AIProjectClient
from azure.search.documents import SearchClient
from azure.search.documents.models import HybridSearch, SemanticConfiguration

logger = logging.getLogger(__name__)


class AIFoundryClient:
    """
    Client for Azure AI Foundry Agent Service.

    Handles:
    - Connecting to AI Foundry with Managed Identity
    - Invoking the AI agent with user context
    - Passing user's OBO token for SharePoint-scoped retrieval
    - Streaming/awaiting responses
    """

    def __init__(self):
        """Initialize AI Foundry and AI Search clients."""
        self.ai_project_endpoint = os.getenv("AZURE_AI_PROJECT_ENDPOINT")
        self.search_endpoint = os.getenv("AZURE_SEARCH_ENDPOINT")
        self.cosmos_endpoint = os.getenv("AZURE_COSMOS_ENDPOINT")
        self.tenant_id = os.getenv("AZURE_TENANT_ID")

        # Use Managed Identity in production, DefaultAzureCredential in local dev
        try:
            self.credential = ManagedIdentityCredential()
        except Exception:
            self.credential = DefaultAzureCredential()

        # Initialize AI Foundry client
        # https://learn.microsoft.com/en-us/azure/ai-studio/how-to/develop-with-agents-sdk
        self.ai_client = AIProjectClient.from_config(
            credential=self.credential,
            project_connection_string=self.ai_project_endpoint
        )

        # Initialize AI Search client
        self.search_client = SearchClient(
            endpoint=self.search_endpoint,
            index_name="sharepoint-index",  # TODO: update with actual index name
            credential=self.credential
        )

    async def query_agent(
        self,
        query: str,
        user_token: str,
        conversation_id: str,
        user_id: str
    ) -> str:
        """
        Query the AI Foundry agent for an answer to the user's question.

        Args:
            query: User's question
            user_token: OBO token for SharePoint access (user-scoped)
            conversation_id: Teams conversation ID (for thread store)
            user_id: User's ID (for context)

        Returns:
            Agent's answer
        """
        try:
            logger.info(f"Querying agent for: {query}")

            # Retrieve relevant documents from AI Search using user's token
            # This ensures only documents the user has permission to see are returned
            search_results = await self._search_sharepoint(query, user_token)

            # Build context from search results
            context = self._build_context(search_results)

            # Invoke AI Foundry agent
            # The agent is configured with:
            # - GPT-4o as the LLM
            # - SharePoint tool (uses user_token)
            # - File Search tool (searches retrieved documents)
            agent_message = {
                "role": "user",
                "content": f"""
                Question: {query}

                Relevant documents (from SharePoint):
                {context}

                Please provide a concise answer based on the documents above.
                If the answer is not in the documents, say "I don't have information about this."
                """
            }

            # TODO: Implement actual agent invocation
            # response = await self.ai_client.agents.invoke(
            #     agent_id=os.getenv("AI_AGENT_ID"),
            #     messages=[agent_message],
            #     thread_id=conversation_id  # Persist conversation
            # )

            # For now, return a placeholder
            answer = f"Processing: {query}"

            # Store conversation in Cosmos DB
            await self._store_conversation(
                conversation_id=conversation_id,
                user_id=user_id,
                question=query,
                answer=answer
            )

            return answer

        except Exception as e:
            logger.error(f"Agent query failed: {e}", exc_info=True)
            return f"I encountered an error: {str(e)}"

    async def _search_sharepoint(self, query: str, user_token: str) -> list:
        """
        Search AI Search index for documents matching the query.

        The user's OBO token is passed to ensure only user-accessible documents are returned.
        Uses hybrid search (keyword + semantic) for better relevance.

        Args:
            query: Search query
            user_token: User's OBO token (for permission scoping)

        Returns:
            List of document results
        """
        try:
            # Construct hybrid search
            # TODO: update index name and filter for user permissions
            results = self.search_client.search(
                search_text=query,
                search_mode="all",
                # Filter by user permissions (if indexed)
                filter="user_permissions/any(p: search.in(p, 'user_id_list'))"
            )

            documents = [
                {
                    "id": result.get("id"),
                    "title": result.get("title"),
                    "content": result.get("content"),
                    "source": result.get("source_url"),
                    "score": result.get("@search.score")
                }
                for result in results
            ]

            logger.info(f"Found {len(documents)} documents for query")
            return documents

        except Exception as e:
            logger.error(f"Search failed: {e}")
            return []

    def _build_context(self, documents: list) -> str:
        """Build a context string from search results."""
        if not documents:
            return "No relevant documents found."

        context = "Found documents:\n"
        for i, doc in enumerate(documents[:5], 1):  # Top 5 results
            context += f"\n{i}. {doc.get('title', 'Untitled')}\n"
            context += f"   Source: {doc.get('source', 'Unknown')}\n"
            context += f"   Preview: {doc.get('content', '')[:200]}...\n"

        return context

    async def _store_conversation(
        self,
        conversation_id: str,
        user_id: str,
        question: str,
        answer: str
    ):
        """
        Store conversation turn in Cosmos DB for history and analytics.

        TODO: Implement Cosmos DB storage using conversation_id as partition key
        """
        try:
            logger.info(f"Storing conversation: {conversation_id}")
            # TODO: implement Cosmos DB insert
            # conversation_item = {
            #     "id": f"{conversation_id}_{timestamp}",
            #     "conversation_id": conversation_id,
            #     "user_id": user_id,
            #     "timestamp": datetime.utcnow().isoformat(),
            #     "question": question,
            #     "answer": answer
            # }
            # await cosmos_client.create_item(conversation_item)
        except Exception as e:
            logger.error(f"Failed to store conversation: {e}")
