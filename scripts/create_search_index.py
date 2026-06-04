"""
Create the `sharepoint-index` Azure AI Search index.

Defines the schema the retrieval pipeline depends on:
  - text fields (title/content/source_url),
  - a `contentVector` HNSW vector field with an Azure OpenAI *vectorizer* so queries
    can use integrated vectorization (no embedding call in the app),
  - the **ACL trimming fields** `allowedGroups` / `allowedUsers` (filterable), and
  - a semantic configuration for the semantic reranker.

Auth is identity-based (DefaultAzureCredential / Managed Identity) — no keys.

Usage:
    pip install -r scripts/requirements.txt
    AZURE_SEARCH_ENDPOINT=... AZURE_AI_SERVICES_ENDPOINT=... python scripts/create_search_index.py
"""

import os

from azure.identity import DefaultAzureCredential
from azure.search.documents.indexes import SearchIndexClient
from azure.search.documents.indexes.models import (
    AzureOpenAIVectorizer,
    AzureOpenAIVectorizerParameters,
    HnswAlgorithmConfiguration,
    SearchableField,
    SearchField,
    SearchFieldDataType,
    SearchIndex,
    SemanticConfiguration,
    SemanticField,
    SemanticPrioritizedFields,
    SemanticSearch,
    SimpleField,
    VectorSearch,
    VectorSearchProfile,
)

INDEX_NAME = os.getenv("AZURE_SEARCH_INDEX", "sharepoint-index")
SEMANTIC_CONFIG = os.getenv("AZURE_SEARCH_SEMANTIC_CONFIG", "default-semantic")
EMBEDDING_DEPLOYMENT = os.getenv("AZURE_EMBEDDING_DEPLOYMENT", "text-embedding-3-large")
EMBEDDING_DIMENSIONS = int(os.getenv("AZURE_EMBEDDING_DIMENSIONS", "3072"))  # 3-large = 3072


def build_index() -> SearchIndex:
    fields = [
        SimpleField(name="id", type=SearchFieldDataType.String, key=True),
        SearchableField(name="title", type=SearchFieldDataType.String),
        SearchableField(name="content", type=SearchFieldDataType.String),
        SimpleField(name="source_url", type=SearchFieldDataType.String, filterable=False),
        # ---- Security-trimming ACL fields ----
        SearchField(
            name="allowedGroups",
            type=SearchFieldDataType.Collection(SearchFieldDataType.String),
            filterable=True,
        ),
        SearchField(
            name="allowedUsers",
            type=SearchFieldDataType.Collection(SearchFieldDataType.String),
            filterable=True,
        ),
        # ---- Vector field (integrated vectorization) ----
        SearchField(
            name="contentVector",
            type=SearchFieldDataType.Collection(SearchFieldDataType.Single),
            searchable=True,
            vector_search_dimensions=EMBEDDING_DIMENSIONS,
            vector_search_profile_name="default-vector-profile",
        ),
    ]

    vector_search = VectorSearch(
        algorithms=[HnswAlgorithmConfiguration(name="default-hnsw")],
        profiles=[
            VectorSearchProfile(
                name="default-vector-profile",
                algorithm_configuration_name="default-hnsw",
                vectorizer_name="default-vectorizer",
            )
        ],
        vectorizers=[
            AzureOpenAIVectorizer(
                vectorizer_name="default-vectorizer",
                parameters=AzureOpenAIVectorizerParameters(
                    resource_url=os.environ["AZURE_AI_SERVICES_ENDPOINT"],
                    deployment_name=EMBEDDING_DEPLOYMENT,
                    model_name=EMBEDDING_DEPLOYMENT,
                ),
            )
        ],
    )

    semantic_search = SemanticSearch(
        configurations=[
            SemanticConfiguration(
                name=SEMANTIC_CONFIG,
                prioritized_fields=SemanticPrioritizedFields(
                    title_field=SemanticField(field_name="title"),
                    content_fields=[SemanticField(field_name="content")],
                ),
            )
        ]
    )

    return SearchIndex(
        name=INDEX_NAME,
        fields=fields,
        vector_search=vector_search,
        semantic_search=semantic_search,
    )


def main() -> None:
    endpoint = os.environ["AZURE_SEARCH_ENDPOINT"]
    client = SearchIndexClient(endpoint=endpoint, credential=DefaultAzureCredential())
    index = build_index()
    client.create_or_update_index(index)
    print(f"Created/updated index '{INDEX_NAME}' at {endpoint}")


if __name__ == "__main__":
    main()
