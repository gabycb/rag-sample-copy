"""
Seed the search index with ACL-tagged sample documents.

Embeds each document's content with Azure OpenAI (text-embedding-3-large) and uploads
it with its `allowedGroups` / `allowedUsers` ACL so security trimming is demonstrable:
alice (grp-engineering) and bob (grp-sales) retrieve different documents.

Auth is identity-based (DefaultAzureCredential). Usage:
    pip install -r scripts/requirements.txt
    AZURE_SEARCH_ENDPOINT=... AZURE_AI_SERVICES_ENDPOINT=... python scripts/upload_sample_docs.py
"""

import os
import sys

from azure.identity import DefaultAzureCredential, get_bearer_token_provider
from azure.search.documents import SearchClient
from openai import AzureOpenAI

# Import the canonical corpus shared with the app's local mode.
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src", "bot"))
from sample_corpus import SAMPLE_DOCS  # noqa: E402

INDEX_NAME = os.getenv("AZURE_SEARCH_INDEX", "sharepoint-index")
EMBEDDING_DEPLOYMENT = os.getenv("AZURE_EMBEDDING_DEPLOYMENT", "text-embedding-3-large")
_COGNITIVE_SCOPE = "https://cognitiveservices.azure.com/.default"


def main() -> None:
    credential = DefaultAzureCredential()

    aoai = AzureOpenAI(
        azure_endpoint=os.environ["AZURE_AI_SERVICES_ENDPOINT"],
        azure_ad_token_provider=get_bearer_token_provider(credential, _COGNITIVE_SCOPE),
        api_version="2024-10-21",
    )

    docs = []
    for doc in SAMPLE_DOCS:
        embedding = aoai.embeddings.create(
            input=doc["content"], model=EMBEDDING_DEPLOYMENT
        ).data[0].embedding
        docs.append({**doc, "contentVector": embedding})

    search = SearchClient(
        endpoint=os.environ["AZURE_SEARCH_ENDPOINT"],
        index_name=INDEX_NAME,
        credential=credential,
    )
    result = search.upload_documents(documents=docs)
    succeeded = sum(1 for r in result if r.succeeded)
    print(f"Uploaded {succeeded}/{len(docs)} documents to '{INDEX_NAME}'")


if __name__ == "__main__":
    main()
