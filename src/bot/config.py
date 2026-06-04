"""
Centralized configuration for the ATLAS-RAG bot.

Reads from environment variables (populated by `.env` locally or App Service
app settings in Azure). `APP_MODE=local` swaps every external Azure dependency
for an in-memory fake so the whole request path is runnable and unit-testable
without a live Azure / Teams / SharePoint tenant.
"""

import os
from functools import lru_cache


class Settings:
    """Strongly-typed view over the process environment."""

    def __init__(self) -> None:
        # "local" -> in-memory fakes; "azure" -> real Azure SDK clients.
        self.app_mode: str = os.getenv("APP_MODE", "azure").strip().lower()

        # Identity / tenant
        self.tenant_id: str | None = os.getenv("AZURE_TENANT_ID")
        self.managed_identity_client_id: str | None = os.getenv("AZURE_CLIENT_ID")

        # Bot Service (User-Assigned MSI auth — no password)
        self.bot_app_id: str | None = os.getenv("MICROSOFT_APP_ID") or self.managed_identity_client_id
        self.bot_app_type: str = os.getenv("MICROSOFT_APP_TYPE", "UserAssignedMSI")
        self.bot_app_tenant_id: str | None = os.getenv("MICROSOFT_APP_TENANT_ID") or self.tenant_id

        # Entra ID app registration used for the On-Behalf-Of (OBO) exchange.
        # Its client credential (secret or, in production, a federated MI credential)
        # is required by OBO — this is the one credential the flow genuinely needs.
        self.obo_client_id: str | None = os.getenv("ENTRA_APP_CLIENT_ID")
        self.obo_client_secret: str | None = os.getenv("ENTRA_APP_CLIENT_SECRET")

        # Downstream service endpoints
        self.search_endpoint: str | None = os.getenv("AZURE_SEARCH_ENDPOINT")
        self.search_index_name: str = os.getenv("AZURE_SEARCH_INDEX", "sharepoint-index")
        self.cosmos_endpoint: str | None = os.getenv("AZURE_COSMOS_ENDPOINT")
        self.cosmos_database: str = os.getenv("AZURE_COSMOS_DATABASE", "atlas-rag-db")
        self.ai_project_endpoint: str | None = os.getenv("AZURE_AI_PROJECT_ENDPOINT")
        self.ai_agent_id: str | None = os.getenv("AI_AGENT_ID")

        # Retrieval strategy: keyword | vector | hybrid | semantic | hybrid_semantic
        self.search_strategy: str = os.getenv("SEARCH_STRATEGY", "hybrid_semantic").strip().lower()
        self.semantic_config_name: str = os.getenv("AZURE_SEARCH_SEMANTIC_CONFIG", "default-semantic")
        self.embedding_deployment: str = os.getenv("AZURE_EMBEDDING_DEPLOYMENT", "text-embedding-3-large")

        # Microsoft Graph
        self.graph_base_url: str = os.getenv("GRAPH_BASE_URL", "https://graph.microsoft.com/v1.0")

        # Content safety (PR4)
        self.content_safety_endpoint: str | None = os.getenv("AZURE_CONTENT_SAFETY_ENDPOINT")
        self.enable_content_safety: bool = os.getenv("ENABLE_CONTENT_SAFETY", "false").strip().lower() == "true"

    @property
    def is_local(self) -> bool:
        return self.app_mode == "local"


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Process-wide singleton (cached)."""
    return Settings()
