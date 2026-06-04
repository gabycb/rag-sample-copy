// Azure Bot Service Bicep Module
// Deploys:
// - Azure Bot Service resource
// - Entra ID app registration for bot authentication
// - Key Vault secrets for bot credentials

param location string
param prefix string
param resourceToken string
param tags object
param isProd bool

// References to other resources (should be passed as parameters)
param keyVaultId string
param managedIdentityClientId string

// ============================================================================
// Variables
// ============================================================================

var botName = '${prefix}-bot-${resourceToken}'
var botAppRegName = '${prefix}-bot-app-${resourceToken}'

// ============================================================================
// Azure Bot Service
// ============================================================================

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
    msaAppType: 'MultiTenant'
    msaAppId: botAppReg.appId
    msaAppTenantId: subscription().tenantId
    msaAppMSIResourceId: null
    configuredChannels: [
      'msteams'  // Enable MS Teams channel
    ]
    iconUrl: ''
    luisAppIds: []
  }
}

// ============================================================================
// Entra ID App Registration for Bot Service
// ============================================================================

// NOTE: In a real implementation, you would use Microsoft.AAD/applications
// However, the bicep module for app registration is limited. Consider:
// - Use az ad app create in post-deployment script
// - Or use a separate Terraform/PowerShell script
// - Store app ID and secret in Key Vault after creation

// Placeholder variables for app registration
var botAppId = 'TODO-create-via-az-cli-or-powershell'  // Set after creating app registration
var botAppSecret = 'TODO-store-in-key-vault'

// ============================================================================
// Bot Service Messaging Endpoint Configuration
// ============================================================================

resource botServiceMessaging 'Microsoft.BotService/botServices/channels@2023-09-15-preview' = {
  name: 'MsTeamsChannel'
  parent: botService
  location: location
  kind: 'MsTeamsChannel'
  properties: {
    properties: {
      isEnabled: true
    }
    channelName: 'MsTeamsChannel'
  }
}

// ============================================================================
// Outputs
// ============================================================================

output botServiceId string = botService.id
output botServiceName string = botService.name
output botAppId string = botAppId
output botServiceEndpoint string = 'https://${botService.name}.azurewebsites.net/api/messages'

/*
  DEPLOYMENT NOTES:

  1. Azure App Registration (Entra ID):
     Since Bicep's app registration support is limited, create the app manually or via script:

     ```powershell
     az ad app create --display-name "$prefix-bot-$resourceToken" \
       --available-to-other-tenants true \
       --reply-urls https://$botName.azurewebsites.net/auth/openid/return
     ```

  2. Store bot credentials in Key Vault:
     ```bash
     az keyvault secret set --vault-name kv-xxx --name BotAppId --value <app-id>
     az keyvault secret set --vault-name kv-xxx --name BotAppPassword --value <app-password>
     ```

  3. Configure Bot Service messaging endpoint in Container Apps:
     The container app needs the Bot Service endpoint to register the webhook.
     Pass this output to container-apps.bicep.

  4. Container App will need these environment variables:
     - MICROSOFT_APP_ID (from Key Vault reference)
     - MICROSOFT_APP_PASSWORD (from Key Vault reference)
     - BOT_SERVICE_ENDPOINT (this output)

  5. MS Teams Integration:
     After deployment, in Azure Portal:
     - Go to Bot Service → Channels
     - Enable "Microsoft Teams"
     - The Teams channel automatically routes Teams messages to the messaging endpoint
*/
