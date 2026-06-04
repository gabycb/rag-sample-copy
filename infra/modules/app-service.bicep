// ---------------------------------------------------------------------------
// Module: app-service.bicep
// Creates: Linux App Service Plan + Web App running the FastAPI bot (uvicorn)
// Phase: 4 — Compute (replaces Container Apps; the bot runs as a plain FastAPI app)
// ---------------------------------------------------------------------------

param location string
param prefix string
param resourceToken string
param tags object
param isProd bool

// Identity + dependencies
param identityId string
param identityClientId string

// Service endpoints (injected as app settings — never secrets)
param cosmosEndpoint string
param searchEndpoint string
param aiProjectEndpoint string
param keyVaultUri string
param appInsightsConnectionString string

// Behaviour
@description('App runtime mode: "azure" (real Azure clients) or "local" (in-memory fakes for dev/test).')
param appMode string = 'azure'

@description('Default AI Search query strategy: keyword | vector | hybrid | semantic | hybrid_semantic')
param searchStrategy string = 'hybrid_semantic'

var planName = 'plan-${prefix}-${resourceToken}'
var appName = 'app-${prefix}-${resourceToken}'

// ---------------------------------------------------------------------------
// App Service Plan (Linux)
// ---------------------------------------------------------------------------
resource appServicePlan 'Microsoft.Web/serverfarms@2023-12-01' = {
  name: planName
  location: location
  tags: tags
  kind: 'linux'
  sku: {
    name: isProd ? 'P1v3' : 'B1'
  }
  properties: {
    reserved: true // required for Linux
  }
}

// ---------------------------------------------------------------------------
// Web App (FastAPI via uvicorn)
// ---------------------------------------------------------------------------
resource webApp 'Microsoft.Web/sites@2023-12-01' = {
  name: appName
  location: location
  // azd matches the service in azure.yaml to this resource via this tag
  tags: union(tags, { 'azd-service-name': 'bot' })
  kind: 'app,linux'
  identity: {
    type: 'UserAssigned'
    userAssignedIdentities: {
      '${identityId}': {}
    }
  }
  properties: {
    serverFarmId: appServicePlan.id
    httpsOnly: true
    keyVaultReferenceIdentity: identityId
    siteConfig: {
      linuxFxVersion: 'PYTHON|3.11'
      ftpsState: 'Disabled'
      minTlsVersion: '1.2'
      // FastAPI listens on 8000; uvicorn started explicitly so we are not
      // dependent on the platform's default gunicorn detection.
      appCommandLine: 'python -m uvicorn main:app --host 0.0.0.0 --port 8000'
      healthCheckPath: '/health'
      appSettings: [
        { name: 'APP_MODE', value: appMode }
        { name: 'SEARCH_STRATEGY', value: searchStrategy }
        // Build the venv + install requirements.txt on deploy (Oryx).
        { name: 'SCM_DO_BUILD_DURING_DEPLOYMENT', value: 'true' }
        { name: 'WEBSITES_PORT', value: '8000' }
        // Identity used by DefaultAzureCredential(managed_identity_client_id=...)
        { name: 'AZURE_CLIENT_ID', value: identityClientId }
        // Service endpoints (identity-based auth — no keys/connection strings)
        { name: 'AZURE_COSMOS_ENDPOINT', value: cosmosEndpoint }
        { name: 'AZURE_SEARCH_ENDPOINT', value: searchEndpoint }
        { name: 'AZURE_AI_PROJECT_ENDPOINT', value: aiProjectEndpoint }
        { name: 'AZURE_KEY_VAULT_URL', value: keyVaultUri }
        { name: 'APPLICATIONINSIGHTS_CONNECTION_STRING', value: appInsightsConnectionString }
      ]
    }
  }
}

// Outputs
output appServiceName string = webApp.name
output appServiceUrl string = 'https://${webApp.properties.defaultHostName}'
output appServiceMessagingEndpoint string = 'https://${webApp.properties.defaultHostName}/api/messages'
