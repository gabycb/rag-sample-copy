# ATLAS-RAG Architecture Update: MS Teams Bot Integration

This document summarizes the migration from a pure FastAPI backend to an **MS Teams Bot Service** architecture, based on the provided diagram.

## Changes Summary

### ✅ Documentation Updated

1. **CLAUDE.md** - Updated for Bot Service architecture
   - Added message flow diagram
   - Updated project overview with MS Teams
   - Reorganized environment variables (service-to-service vs. Bot Service)
   - Added local testing with Bot Framework Emulator
   - Updated development workflow

2. **README.md** - Comprehensive architecture refresh
   - New ASCII architecture diagram with MS Teams, Bot Service, and the complete flow
   - Updated technology table
   - Updated prerequisites (Bot Service, MS Teams access)
   - Updated repository structure
   - Enhanced local development section with Bot Framework Emulator instructions

3. **AGENTS.md** - Added Bot Service context
   - Updated architecture section with Bot Service layer
   - Added MS Teams Bot Service specifics section
   - Explained OBO (On-Behalf-Of) flow for user-scoped SharePoint access
   - Updated file structure with bot module organization

4. **.env.example** - Added Bot Service variables
   - Organized into two sections: service-to-service and Teams bot
   - Documented all Bot Service credentials
   - Documented OBO flow variables

5. **azure.yaml** - Updated service naming
   - Changed from `api` service to `bot` service
   - Points to `./src/bot/Dockerfile`

### ✅ Bot Service Code Structure Created

New `src/bot/` directory with implementation stubs:

1. **src/bot/Dockerfile** - Container image definition (comments explain webhook flow)

2. **src/bot/requirements.txt** - Python dependencies
   - botbuilder-core, botbuilder-integration-aiohttp (Microsoft Bot Framework)
   - msal (for OBO token exchange)
   - azure-identity, azure-ai-projects, azure-search-documents (Azure SDK)
   - azure-cosmos, azure-keyvault-secrets (storage & secrets)
   - azure-monitor-opentelemetry (observability)

3. **src/bot/main.py** - FastAPI entry point
   - `/api/messages` webhook for Bot Service
   - Validates Bot Service credentials
   - Extracts user context (ID, name, conversation)
   - Handles message routing to AI agent
   - Returns reply through Bot Service
   - Health check endpoint

4. **src/bot/bot_handler.py** - Bot Service & Entra ID OBO logic
   - `validate_auth_header()` - Verifies Bot Service JWT tokens
   - `get_obo_token()` - Exchanges user's token for SharePoint-scoped token
   - `send_reply()` - Sends answer back through Bot Service
   - Comments explain where JWT signature verification needs production hardening

5. **src/bot/ai_foundry_client.py** - AI orchestration
   - `query_agent()` - Main entry point for bot's AI queries
   - `_search_sharepoint()` - Hybrid search on AI Search (user-scoped via OBO token)
   - `_build_context()` - Formats search results for agent
   - `_store_conversation()` - Persists Q&A to Cosmos DB for history
   - Decouples Teams/bot logic from AI/RAG logic

### ✅ Infrastructure as Code Started

1. **infra/modules/bot-service.bicep** - Bot Service deployment module
   - Creates Azure Bot Service resource
   - Configures MS Teams channel
   - Notes on Entra ID app registration (manual step via CLI)
   - Documents Key Vault integration for bot credentials
   - Explains messaging endpoint configuration for Container App webhook
   - Deployment notes with example PowerShell/Bash commands

## Message Flow (from diagram)

```
Question Flow (1→4):
  User types in MS Teams
  → Azure Bot Service receives message
  → Routes to Container App webhook (/api/messages)
  → bot_handler.py validates credentials + extracts user token
  → ai_foundry_client.py queries AI Foundry agent
  → Agent uses AI Search for retrieval (scoped to user permissions via OBO token)
  → Agent synthesizes answer with GPT-4o

Answer Flow (5→7):
  AI Foundry returns answer
  → Container App sends reply through Bot Service API
  → Bot Service forwards to MS Teams
  → User sees answer in Teams conversation
```

## What Still Needs Implementation

### High Priority

1. **Entra ID App Registration Setup**
   - Manually create app registration (or automate via post-deployment script)
   - Store app ID and password in Key Vault
   - Configure OAuth redirects for OBO flow
   - See: `infra/modules/bot-service.bicep` deployment notes

2. **Complete bot_handler.py**
   - Implement JWT signature verification with Microsoft's OpenID config
   - Implement actual OBO token exchange (msal.acquire_token_on_behalf_of)
   - Implement Bot Service API calls for sending replies (bot_connector_client)
   - Extract user token from Teams activity correctly

3. **Complete ai_foundry_client.py**
   - Implement actual AI Foundry agent invocation (using AI Projects SDK)
   - Configure agent with SharePoint tool + File Search tool
   - Pass user's OBO token to agent
   - Implement Cosmos DB conversation storage
   - Update AI Search index name and user permission filters

4. **Bicep module integration**
   - Add bot-service.bicep module invocation to main.bicep
   - Update container-apps.bicep to:
     - Accept bot endpoint as parameter
     - Add MICROSOFT_APP_ID, MICROSOFT_APP_PASSWORD env vars (from Key Vault)
     - Add BOT_SERVICE_ENDPOINT env var
   - Ensure RBAC in security.bicep grants Container App access to Key Vault for bot credentials

5. **AI Foundry Agent Configuration**
   - Create AI Foundry agent with:
     - Model: GPT-4o
     - Tools: SharePoint tool + File Search tool
     - Instructions for RAG behavior
   - Configure SharePoint tool with user's OBO token scope
   - Store agent ID in Key Vault or as environment variable

### Medium Priority

1. **Local Testing Setup**
   - Test bot_handler.py OBO flow with mock tokens
   - Test bot_handler.py Bot Service credential validation
   - Test ai_foundry_client.py with mock AI Search results
   - Add unit tests for message parsing and context building

2. **Conversation Storage**
   - Finalize Cosmos DB schema (threads container)
   - Implement conversation history retrieval (multi-turn Q&A)
   - Implement thread persistence via AI Foundry

3. **Error Handling & Logging**
   - Add structured logging to all modules
   - Add retry logic for transient failures
   - Add user-friendly error messages for Teams display

4. **Monitoring & Observability**
   - Wire up Application Insights
   - Add custom metrics for Q&A latency, agent success rate
   - Add alerts for bot failures

### Low Priority

1. **Advanced Features**
   - File attachments in Teams (upload documents to agent)
   - Proactive notifications (e.g., "new FAQ added")
   - User feedback loop (thumbs up/down on answers)
   - Search analytics (most common questions)

2. **Hardening**
   - Rate limiting on bot webhook
   - Input validation & sanitization
   - Prevent prompt injection in queries
   - GDPR compliance for conversation storage

## Next Steps

1. **Review & Approve Architecture**
   - Confirm the message flow diagram matches your needs
   - Approve the split between bot_handler.py (Teams) and ai_foundry_client.py (AI)

2. **Setup Entra ID**
   - Create app registration for bot (or use provided PowerShell scripts)
   - Create app registration for OBO flow (user delegation)
   - Store credentials in Key Vault

3. **Implement bot_handler.py & ai_foundry_client.py**
   - Fill in the TODO comments with actual Azure SDK calls
   - Test OBO token exchange
   - Test AI Search retrieval with user scoping

4. **Finalize Bicep Infrastructure**
   - Complete bot-service.bicep module invocation in main.bicep
   - Update container-apps.bicep with bot credentials + endpoint
   - Deploy and test with `azd provision && azd deploy`

5. **End-to-End Testing**
   - Test in Bot Framework Emulator (without Teams)
   - Test with actual MS Teams (add bot to Teams channel)
   - Verify OBO flow (user can only access their SharePoint docs)
   - Verify RAG retrieval (AI Search returns relevant docs)

## Files Preserved

- All original architecture patterns (Managed Identity, Key Vault, RBAC centralization, etc.)
- All original Bicep modules (ai-services, ai-foundry, ai-search, cosmos-db, storage, etc.)
- All original AI/RAG logic patterns (hybrid search, semantic re-ranking, etc.)

The update **adds** the Bot Service layer without changing how the existing backend services work.
