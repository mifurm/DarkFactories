// SwarmAI Commercial Studio ("Spotlight") — subscription-scope deployment.
// Creates the resource group WITH the mandatory MCAPS governance tags, then every resource
// inside it (keyless: managed identity + RBAC only; no keys / connection secrets in outputs).
targetScope = 'subscription'

@minLength(1)
@maxLength(40)
@description('azd environment name (also used for the azd-env-name tag).')
param environmentName string = 'studio'

@description('Azure region for every resource.')
param location string = 'swedencentral'

@description('Resource group name (created by this template).')
param resourceGroupName string = 'rg-swarmai-studio'

@description('Object id of the deploying user (az ad signed-in-user show --query id -o tsv). Gets data-plane roles for local runs against real Azure.')
param principalId string = ''

@description('azd sets this to true when the container app already exists (keeps the deployed image on re-provision).')
param webAppExists bool = false

@description('Explicit container image (overrides placeholder / existing image). Leave empty for azd flows.')
param appImage string = ''

@description('Daily AI budget cap in USD enforced by the app (fails closed).')
param dailyAiBudgetUsd string = '5'

@description('Per-campaign AI budget cap in USD.')
param campaignAiBudgetUsd string = '2'

@description('Optional hardening: put Entra ID authentication (Container Apps built-in auth) in front of the app. Requires entraClientId (app registration with a federated credential for the app identity).')
param enableEntraAuth bool = false
param entraClientId string = ''

@description('Container app CPU / memory (consumption profile combinations).')
param appCpu string = '1.0'
param appMemory string = '2Gi'
param appMaxReplicas int = 2

// Mandatory MCAPS governance tags (RG at creation time + EVERY taggable resource via this one object).
// SecurityExemption=StorageAccountKeyAccess: shared-key access on Storage is *permitted* by governance;
// this deployment still keeps it OFF (Entra-only) because nothing needs account keys.
var commonTags = {
  SecurityControl: 'Ignore'
  SecurityExemption: 'StorageAccountKeyAccess'
  project: 'SwarmAI'
  concept: 'studio'
  owner: 'michalfu'
  environment: 'demo'
  'azd-env-name': environmentName
}

var token = toLower(uniqueString(subscription().id, resourceGroupName))

resource rg 'Microsoft.Resources/resourceGroups@2024-03-01' = {
  name: resourceGroupName
  location: location
  tags: commonTags
}

module monitoring 'modules/monitoring.bicep' = {
  name: 'monitoring'
  scope: rg
  params: { location: location, commonTags: commonTags, token: token }
}

module identity 'modules/identity.bicep' = {
  name: 'identity'
  scope: rg
  params: { location: location, commonTags: commonTags }
}

module registry 'modules/registry.bicep' = {
  name: 'registry'
  scope: rg
  params: { location: location, commonTags: commonTags, token: token, appPrincipalId: identity.outputs.principalId }
}

module data 'modules/data.bicep' = {
  name: 'data'
  scope: rg
  params: { location: location, commonTags: commonTags, token: token, appPrincipalId: identity.outputs.principalId, userPrincipalId: principalId }
}

module ai 'modules/ai.bicep' = {
  name: 'ai'
  scope: rg
  params: { location: location, commonTags: commonTags, token: token, appPrincipalId: identity.outputs.principalId, userPrincipalId: principalId }
}

module telemetryRoles 'modules/telemetry-roles.bicep' = {
  name: 'telemetry-roles'
  scope: rg
  params: { appInsightsName: monitoring.outputs.appInsightsName, appPrincipalId: identity.outputs.principalId, userPrincipalId: principalId }
}

module app 'modules/app.bicep' = {
  name: 'app'
  scope: rg
  dependsOn: [telemetryRoles]
  params: {
    location: location
    commonTags: commonTags
    token: token
    identityId: identity.outputs.id
    identityClientId: identity.outputs.clientId
    logAnalyticsId: monitoring.outputs.logAnalyticsId
    appInsightsConnectionString: monitoring.outputs.appInsightsConnectionString
    acrName: registry.outputs.name
    acrLoginServer: registry.outputs.loginServer
    cosmosEndpoint: data.outputs.cosmosEndpoint
    cosmosDatabase: data.outputs.cosmosDatabase
    blobAccountUrl: data.outputs.blobAccountUrl
    blobContainer: data.outputs.blobContainer
    openAiEndpoint: ai.outputs.openAiEndpoint
    aiEndpoint: ai.outputs.aiEndpoint
    deployments: ai.outputs.deployments
    webAppExists: webAppExists
    appImage: appImage
    dailyAiBudgetUsd: dailyAiBudgetUsd
    campaignAiBudgetUsd: campaignAiBudgetUsd
    enableEntraAuth: enableEntraAuth
    entraClientId: entraClientId
    cpu: appCpu
    memory: appMemory
    maxReplicas: appMaxReplicas
  }
}

output AZURE_LOCATION string = location
output AZURE_RESOURCE_GROUP string = rg.name
output AZURE_CONTAINER_REGISTRY_NAME string = registry.outputs.name
output AZURE_CONTAINER_REGISTRY_ENDPOINT string = registry.outputs.loginServer
output SERVICE_WEB_NAME string = app.outputs.name
output SERVICE_WEB_URI string = app.outputs.uri
output COSMOS_ENDPOINT string = data.outputs.cosmosEndpoint
output BLOB_ACCOUNT_URL string = data.outputs.blobAccountUrl
output AZURE_OPENAI_ENDPOINT string = ai.outputs.openAiEndpoint
output AI_ENDPOINT string = ai.outputs.aiEndpoint
output APP_IDENTITY_CLIENT_ID string = identity.outputs.clientId
output APPLICATIONINSIGHTS_NAME string = monitoring.outputs.appInsightsName
