# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

**ATLAS-RAG** is an enterprise Retrieval-Augmented Generation (RAG) agent accessible via **MS Teams** that enables natural-language question-and-answer over SharePoint content. Employees interact through Teams; the **Azure Bot Service** routes questions to the **Azure AI Foundry Agent Service** (GPT-4o), which retrieves documents from **Azure AI Search** (hybrid RAG) backed by **SharePoint** as the knowledge store. **Microsoft Entra ID On-Behalf-Of (OBO) flow** ensures users can only access SharePoint content they have permissions for.

### Key Technologies

- **User Interface**: MS Teams (employee interface via Bot Service)
- **Bot Service**: Azure Bot Service (routes messages + Entra ID authentication)
- **Backend**: Azure Container Apps (bot logic, FastAPI)
- **AI Agent**: Azure AI Foundry Agent Service (GPT-4o + SharePoint tool + File Search)
- **Search**: Azure AI Search (hybrid + semantic re-ranking)
- **Knowledge Store**: SharePoint (docs, FAQs, organizational knowledge)
- **Conversation Storage**: Azure Cosmos DB (threads & conversations containers)
- **File Storage**: Azure Blob Storage (agent files, attachments)
- **Authentication**: Microsoft Entra ID OBO flow for user-scoped SharePoint access
- **Identity**: User-Assigned Managed Identity (service-to-service auth, no connection strings in code)
- **Secrets**: Azure Key Vault
- **Observability**: Azure Application Insights + Log Analytics
- **Infrastructure**: Azure Developer CLI (AZD) + Bicep

---

## Commands

### Infrastructure & Deployment

```bash
# Authenticate with Azure
azd auth login

# Create a new environment (dev/prod)
azd env new rag-test-dev      # or rag-test-prod

# Provision all Azure resources (~15-20 min)
azd provision

# Build and deploy the container to Azure Container Apps
azd deploy

# Validate Bicep before deploying
az bicep build --file infra/main.bicep

# Preview infrastructure changes (what-if)
az deployment sub what-if \
  --location eastus2 \
  --template-file infra/main.bicep \
  --parameters infra/main.parameters.json
```

### Local Development

```bash
# Set up Python environment
cd src/bot
pip install -r requirements.txt

# Run the bot service locally (auto-reload enabled)
uvicorn main:app --reload --port 8000

# Build the container image locally
docker build -t atlas-rag-bot ./src/bot

# Run the container locally with environment file
docker run -p 8000:8000 --env-file ../.env atlas-rag-bot

# Test the bot locally with Bot Framework Emulator
# Download: https://github.com/Microsoft/BotFramework-Emulator
# Connect to: http://localhost:8000/api/messages
# (Use MICROSOFT_APP_ID and MICROSOFT_APP_PASSWORD from .env)
```

### MS Teams Integration (Local Testing)

1. Create an Entra ID app registration locally (for testing)
2. Configure Bot Service channels for MS Teams
3. Add the app to Teams for testing
4. Send messages in Teams → forwarded to bot webhook on localhost (via ngrok tunnel or similar)

---

## Message Flow

```
Question Flow (1→4):
  MS Teams → Bot Service → AI Foundry → AI Search (retrieves from SharePoint)

Answer Flow (5→7):
  AI Foundry → Bot Service → MS Teams (dashed chord: answer returns across the loop)
```

The Bot Service authenticates all requests via **Entra ID** and enforces **OBO flow** so each user can only query documents they have access to in SharePoint.

---

## Architecture & Key Conventions

### Authentication & Secrets

- **Service-to-Service**: Use `User-Assigned Managed Identity` for the Container App. Authentication is **never** via connection strings or shared keys in code.
- **In Production**: The Container App authenticates using `ManagedIdentityCredential` via the `AZURE_CLIENT_ID` environment variable injected at runtime.
- **In Local Dev**: Use `DefaultAzureCredential`, which chains: environment variables → `az login` → MSI. For service principal scenarios, set `AZURE_CLIENT_ID`, `AZURE_CLIENT_SECRET`, `AZURE_TENANT_ID`.
- **Secrets Storage**: All secrets (`client_secret`, connection strings, API keys) are stored in **Azure Key Vault**, never in code or `.env` files in production deployments.

### Environment & prod/dev Toggle

The `isProd` flag in `infra/main.bicep` is automatically derived from the environment name:

```bicep
var isProd = contains(environmentName, 'prod')
```

This controls:
- **Cosmos DB**: Serverless (dev) / Autoscale (prod)
- **AI Search**: Free tier (dev) / Standard (prod)
- **Networking**: No private endpoints (dev) / Private endpoints + VNet (prod)
- **Monitoring**: Standard retention (dev) / Extended retention + alerts (prod)

---

## Repository Structure

```
fullRAG/
├── README.md                       # Full architecture & deployment guide
├── AGENTS.md                       # Copilot coding instructions
├── .env.example                    # Environment variable template (local dev only)
├── azure.yaml                      # AZD service definitions (bot service + ai services)
│
├── infra/
│   ├── main.bicep                  # Subscription-scoped entry point (creates resource group)
│   ├── main.parameters.json        # AZD-injected parameters
│   ├── abbreviations.json          # Azure resource naming abbreviations
│   └── modules/
│       ├── monitoring.bicep        # Log Analytics + Application Insights
│       ├── managed-identity.bicep  # User-Assigned Managed Identity
│       ├── key-vault.bicep         # Key Vault (RBAC, soft delete enabled)
│       ├── container-registry.bicep# Azure Container Registry
│       ├── bot-service.bicep       # Azure Bot Service + App Registration
│       ├── ai-services.bicep       # Azure AI Services (GPT-4o + embeddings)
│       ├── ai-foundry.bicep        # AI Hub + AI Project + Agent capability host
│       ├── ai-search.bicep         # Azure AI Search (hybrid + semantic ranking)
│       ├── cosmos-db.bicep         # Cosmos DB (serverless/autoscale toggle)
│       ├── storage-account.bicep   # Blob Storage (agent files)
│       ├── container-apps.bicep    # Container Apps Environment + bot backend
│       └── security.bicep          # All RBAC role assignments (centralized)
│
└── src/
    └── bot/
        ├── Dockerfile              # Python 3.11 slim, uvicorn on port 8000
        ├── main.py                 # FastAPI bot service entry point
        ├── requirements.txt        # Python dependencies (botframework, azure-ai-foundry)
        ├── bot_handler.py          # MS Teams message routing + Entra ID OBO
        ├── ai_foundry_client.py    # AI Foundry agent orchestration
        └── [other bot modules]
```

### Bicep Module Dependencies

**main.bicep** deploys in phases:

1. **Shared Services**: Monitoring, Managed Identity, Key Vault, Container Registry
2. **Bot Service**: Azure Bot Service + Entra ID App Registration (for MS Teams)
3. **AI & Data**: Azure AI Services, AI Foundry, AI Search, Cosmos DB, Storage Account
4. **Compute**: Container Apps (bot backend, references managed identity for auth)
5. **Security**: RBAC assignments (references all previous resources)

All role assignments are centralized in `security.bicep` for auditability.

**Bot Service specifics:**
- Creates an Entra ID app registration for OBO flow
- Stores app registration credentials in Key Vault
- Passes Bot Service endpoint to Container App for webhook configuration
- Container App registers the message endpoint with the Bot Service

---

## Naming Conventions & Environment Variables

### Environment Naming

| Environment | AZD env name | Resource Group | isProd flag |
|---|---|---|---|
| Development | `rag-test-dev` | `rg-rag-test-dev` | `false` |
| Production | `rag-test-prod` | `rg-rag-test-prod` | `true` |

### Container App Environment Variables

Container Apps are **not** deployed with secrets as environment variables. Instead:

- **Service Endpoints** (non-secret): Passed as env vars (e.g., `AZURE_AI_PROJECT_ENDPOINT`, `AZURE_SEARCH_ENDPOINT`)
- **Secrets**: Retrieved from Key Vault at runtime via Key Vault references or injected as Managed Identity credentials
- In local dev, load `.env` file: `export $(grep -v '^#' .env | xargs)`

### Key Variables

**Service-to-Service (Managed Identity):**

| Variable | Purpose | Secret? | Where Set |
|---|---|---|---|
| `ENVIRONMENT` | Determines dev/prod behavior | No | Container App env var |
| `AZURE_CLIENT_ID` | Managed Identity client ID | No | Container App env var |
| `AZURE_AI_PROJECT_ENDPOINT` | AI Foundry endpoint | No | Container App env var |
| `AZURE_SEARCH_ENDPOINT` | AI Search endpoint | No | Container App env var |
| `AZURE_COSMOS_ENDPOINT` | Cosmos DB endpoint | No | Container App env var |
| `AZURE_TENANT_ID` | Entra ID tenant | No | Container App env var |
| `APPLICATIONINSIGHTS_CONNECTION_STRING` | App Insights telemetry | Yes | Key Vault only |

**MS Teams Bot Service (OBO flow):**

| Variable | Purpose | Secret? | Where Set |
|---|---|---|---|
| `MICROSOFT_APP_ID` | Bot app registration ID | No | Container App env var |
| `MICROSOFT_APP_PASSWORD` | Bot app registration password | Yes | Key Vault only |
| `BOT_SERVICE_ENDPOINT` | Bot Service webhook URL | No | Container App env var |
| `ENTRA_APP_CLIENT_ID` | Entra ID app for OBO (user delegation) | No | Container App env var |
| `ENTRA_APP_CLIENT_SECRET` | OBO client secret | Yes | Key Vault only |

---

## Development Workflow

### Adding a New Python Dependency

1. Edit `src/api/requirements.txt` and add the dependency
2. Run locally: `pip install -r src/api/requirements.txt`
3. Test locally: `uvicorn main:app --reload --port 8000`
4. Push and deploy: `azd deploy`

### Modifying Infrastructure (Bicep)

1. Edit the relevant module in `infra/modules/*.bicep`
2. Validate the Bicep: `az bicep build --file infra/main.bicep`
3. Preview changes: `az deployment sub what-if ...` (see Commands above)
4. Deploy: `azd provision` to update Azure resources

### Adding a New Azure Service

1. Create a new Bicep module in `infra/modules/service-name.bicep`
2. Define the resource with appropriate SKU/tier parameters (referencing `isProd`)
3. Add the module invocation in `infra/main.bicep` with proper dependencies
4. Add RBAC role assignments to `infra/modules/security.bicep` (use `principalId` from the managed identity)
5. If the service needs identity credentials, pass endpoint URLs as environment variables to the Container App (in `container-apps.bicep`)
6. Document the new service in this file and in README.md

---

## Key Design Decisions

- **User-Assigned Managed Identity** over service principals: Avoids storing secrets in code; RBAC is pre-assigned at provisioning time.
- **RBAC centralized in `security.bicep`**: All role assignments in one place for auditability and easier updates.
- **Bicep modules over nested templates**: Each service has one module for clarity and reuse.
- **Cosmos DB serverless (dev) / autoscale (prod)**: Optimizes cost for development without sacrificing throughput predictability in production.
- **Private endpoints in prod only**: Balances security for regulated environments with development agility (no complex networking setup needed locally).
- **No connection strings in code**: All service-to-service auth is via Managed Identity + RBAC, secrets are in Key Vault.

---

## Common Tasks

### Debugging the FastAPI App

```bash
# Check logs from the running Container App
azd monitor  # Opens Application Insights

# Or tail logs directly in the terminal
az containerapp logs show --resource-group rg-rag-test-dev --name api
```

### Accessing Key Vault Secrets

```bash
# List secrets in Key Vault
az keyvault secret list --vault-name kv-rag-test-dev-xxx

# Retrieve a secret value
az keyvault secret show --vault-name kv-rag-test-dev-xxx --name mySecret
```

### Verifying Managed Identity Permissions

```bash
# List role assignments for the managed identity
az role assignment list \
  --assignee-object-id <managed-identity-principal-id> \
  --resource-group rg-rag-test-dev
```

---

## References

- **Azure Developer CLI (AZD)**: https://learn.microsoft.com/en-us/azure/developer/azure-developer-cli/
- **Bicep Documentation**: https://learn.microsoft.com/en-us/azure/azure-resource-manager/bicep/
- **Azure AI Foundry**: https://learn.microsoft.com/en-us/azure/ai-studio/
- **FastAPI**: https://fastapi.tiangolo.com/
- **Managed Identity**: https://learn.microsoft.com/en-us/entra/identity/managed-identities-azure-resources/
