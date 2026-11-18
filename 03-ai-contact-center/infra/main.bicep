// SwarmAI Contact Center ("Concierge") - subscription-scope entry point.
// Creates the resource group WITH the mandatory governance tags, then all resources inside it.
targetScope = 'subscription'

@minLength(1)
@maxLength(32)
@description('azd environment name (used for naming/tagging).')
param environmentName string

@description('Azure region for everything.')
param location string = 'swedencentral'

@description('Resource group name (must stay rg-swarmai-contactcenter).')
param resourceGroupName string = 'rg-swarmai-contactcenter'

@description('Object id of the deploying user (gets data-plane roles so local runs can use real Azure). Empty = skip.')
param principalId string = ''

@description('"true" when the container app already exists (azd sets SERVICE_API_RESOURCE_EXISTS) so provisioning keeps the deployed image.')
param apiAppExists string = 'false'

@description('Daily AI budget cap (USD) enforced by the application (fails closed).')
param dailyAiBudgetUsd string = '5'

@description('Optional: put Container Apps built-in Entra authentication in front of the app (requires entraClientId + secret setting).')
param enableEntraAuth bool = false

@description('Entra app registration (client) id used when enableEntraAuth = true.')
param entraClientId string = ''

@secure()
@description('Entra client secret, only used when enableEntraAuth = true (stored as a Container Apps secret).')
param entraClientSecret string = ''

@description('Deploy the secondary realtime model used as fallback.')
param deployRealtimeFallback bool = true

// Mandatory governance tags (authoritative: SecurityExemption=StorageAccountKeyAccess; no SecurityExemption=Cosmos).
// ONE object, applied to the resource group at creation AND to every taggable resource in resources.bicep.
var commonTags = {
  SecurityControl: 'Ignore'
  SecurityExemption: 'StorageAccountKeyAccess'
  project: 'SwarmAI'
  concept: 'contactcenter'
  owner: 'michalfu'
  environment: 'demo'
}

resource rg 'Microsoft.Resources/resourceGroups@2024-03-01' = {
  name: resourceGroupName
  location: location
  tags: union(commonTags, { 'azd-env-name': environmentName })
}

module resources 'resources.bicep' = {
  name: 'concierge-resources'
  scope: rg
  params: {
    location: location
    commonTags: commonTags
    environmentName: environmentName
    principalId: principalId
    apiAppExists: apiAppExists
    dailyAiBudgetUsd: dailyAiBudgetUsd
    enableEntraAuth: enableEntraAuth
    entraClientId: entraClientId
    entraClientSecret: entraClientSecret
    deployRealtimeFallback: deployRealtimeFallback
  }
}

output AZURE_LOCATION string = location
output AZURE_TENANT_ID string = tenant().tenantId
output AZURE_RESOURCE_GROUP string = rg.name
output AZURE_CONTAINER_REGISTRY_ENDPOINT string = resources.outputs.acrLoginServer
output AZURE_CONTAINER_REGISTRY_NAME string = resources.outputs.acrName
output AZURE_CONTAINER_APP_NAME string = resources.outputs.appName
output AZURE_COSMOS_ENDPOINT string = resources.outputs.cosmosEndpoint
output AZURE_OPENAI_ENDPOINT string = resources.outputs.openAiEndpoint
output AZURE_AI_SERVICES_NAME string = resources.outputs.aiName
output SERVICE_API_URI string = resources.outputs.appUrl
