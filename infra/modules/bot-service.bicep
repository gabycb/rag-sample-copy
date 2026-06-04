// ---------------------------------------------------------------------------
// Module: bot-service.bicep
// Creates: Azure Bot Service (MS Teams channel) using User-Assigned MSI auth.
// Phase: 4 — Compute
//
// MSI-based bot auth (msaAppType: 'UserAssignedMSI') means the bot authenticates
// to the Bot Framework with the User-Assigned Managed Identity — there is NO
// app password/secret to create, store, or rotate. This removes the previous
// module's broken `botAppReg.appId` reference and the Key Vault bot-secret flow.
// ---------------------------------------------------------------------------

param location string = 'global' // Bot Service is a global resource
param prefix string
param resourceToken string
param tags object
param isProd bool

@description('Client ID of the User-Assigned Managed Identity (msaAppId).')
param identityClientId string

@description('Resource ID of the User-Assigned Managed Identity (msaAppMSIResourceId).')
param identityResourceId string

@description('Entra ID tenant ID the identity belongs to.')
param tenantId string

@description('Public HTTPS messaging endpoint of the FastAPI app, e.g. https://app.../api/messages')
param messagingEndpoint string

var botName = '${prefix}-bot-${resourceToken}'

resource botService 'Microsoft.BotService/botServices@2023-09-15-preview' = {
  name: botName
  location: location
  kind: 'azurebot'
  sku: {
    name: isProd ? 'S1' : 'F0'
  }
  tags: tags
  properties: {
    displayName: 'ATLAS-RAG Bot'
    description: 'MS Teams RAG bot for SharePoint Q&A'
    endpoint: messagingEndpoint
    msaAppType: 'UserAssignedMSI'
    msaAppId: identityClientId
    msaAppMSIResourceId: identityResourceId
    msaAppTenantId: tenantId
  }
}

// MS Teams channel
resource teamsChannel 'Microsoft.BotService/botServices/channels@2023-09-15-preview' = {
  parent: botService
  name: 'MsTeamsChannel'
  location: location
  properties: {
    channelName: 'MsTeamsChannel'
    properties: {
      isEnabled: true
    }
  }
}

// Outputs
output botServiceId string = botService.id
output botServiceName string = botService.name
output messagingEndpoint string = messagingEndpoint
