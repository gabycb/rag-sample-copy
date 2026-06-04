# ATLAS-RAG SharePoint Agent — Coding Instructions

## Project Overview
Enterprise RAG agent using Azure AI Foundry Agent Service with SharePoint tool for natural-language Q&A over SharePoint content. Uses Entra ID OBO for user-scoped retrieval.

## Architecture
- **User Interface**: MS Teams (via Azure Bot Service)
- **Bot Service**: Azure Bot Service (message routing, Entra ID authentication)
- **Backend**: FastAPI on Azure Container Apps (bot handler, AI orchestration)
- **Agent**: Azure AI Foundry Agent Service (GPT-4o + SharePoint tool + File Search)
- **Search**: Azure AI Search (hybrid + semantic re-ranking)
- **Storage**: Cosmos DB (conversation threads), Azure Storage (agent files)
- **Auth**: Microsoft Entra ID with On-Behalf-Of (OBO) flow for user-scoped SharePoint access
- **IaC**: AZD + Bicep (`infra/` directory)

## Key Conventions
- All service-to-service auth uses **User-Assigned Managed Identity** — no connection strings in code
- Use `ManagedIdentityCredential` in production, `DefaultAzureCredential` only in local dev
- Secrets go in **Azure Key Vault**, never in code or environment variables
- RBAC assignments are centralized in `infra/modules/security.bicep`
- Bicep modules use `isProd` parameter to toggle SKU tiers and networking
- Container App env vars inject service endpoints (not secrets)

## MS Teams Bot Service Specifics
- Bot Service creates an Entra ID app registration for Teams integration
- Bot credentials (`MICROSOFT_APP_ID`, `MICROSOFT_APP_PASSWORD`) are stored in Key Vault
- Container App runs the bot handler that registers the webhook with Bot Service
- All user-to-bot messages flow through Bot Service → Container App webhook
- Bot Service enforces authentication; Container App validates Bot Service credentials in incoming messages

## OBO (On-Behalf-Of) Flow for SharePoint
- When a user sends a message in Teams, the Bot Service receives it with the user's identity token
- Container App exchanges the user's token for a SharePoint-scoped token using OBO flow
- AI Foundry uses this token to query AI Search, which retrieves only documents the user can access
- This ensures user permissions are respected: no connection strings, no hardcoded service accounts

## File Structure
```
infra/main.bicep                → Subscription-scoped entry point (resource group creation + module orchestration)
infra/modules/*.bicep           → One module per Azure service (bot-service.bicep, ai-foundry.bicep, etc.)
infra/modules/bot-service.bicep → Azure Bot Service + Entra ID app registration provisioning
infra/modules/security.bicep    → Centralized RBAC for Managed Identity
azure.yaml                      → AZD service definitions (bot service → Container Apps)
src/bot/                        → FastAPI bot backend
src/bot/Dockerfile              → Container image definition
src/bot/main.py                 → FastAPI entry point (webhook handler for Bot Service)
src/bot/bot_handler.py          → MS Teams message routing + OBO token exchange
src/bot/ai_foundry_client.py    → AI Foundry agent orchestration
```

## Deployment
```bash
azd auth login
azd env new rag-test-dev
azd provision    # Creates all Azure resources
azd deploy       # Builds and deploys the container
```

## Environment Prefix
- Dev: `rag-test-dev` → Resource group `rg-rag-test-dev`
- Prod: `rag-test-prod` → Resource group `rg-rag-test-prod`
