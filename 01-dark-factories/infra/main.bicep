// SwarmAI Dark Factory ("Nightshift") — subscription-scope entry point.
// Creates the resource group WITH the mandatory governance tags, then every resource inside it.
targetScope = 'subscription'

@minLength(1)
@maxLength(32)
@description('azd environment name')
param environmentName string

@description('Azure region for every resource')
param location string = 'swedencentral'

param resourceGroupName string = 'rg-swarmai-darkfactory'

@description('Object id of the deploying user: receives data-plane roles so local runs can use real Azure. Empty = skip.')
param principalId string = ''

@allowed(['User', 'ServicePrincipal', 'Group'])
param principalType string = 'User'

@description('Container image for the web app. Empty = placeholder image (first provision); azd deploy then rolls out the real image.')
param webImageName string = ''

param chatModelName string = 'gpt-5.4-mini'
param chatModelVersion string = '2026-03-17'
param chatCapacity int = 100
param reasoningModelName string = 'gpt-5.4'
param reasoningModelVersion string = '2026-03-05'
param reasoningCapacity int = 50

@description('Daily Azure OpenAI spend cap (USD) enforced by the app; fails closed.')
param dailyAiBudgetUsd string = '5'

@description('Optional: put Container Apps built-in Entra authentication in front of the app (needs entraClientId + a secret).')
param enableEntraAuth bool = false
param entraClientId string = ''
@secure()
param entraClientSecret string = ''


// One tag set for the RG (at creation) AND every taggable resource: MCAPS governance honours SecurityControl=Ignore;
// SecurityExemption=StorageAccountKeyAccess is the sanctioned exemption value (this app is keyless and does not need it).
var commonTags = {
  SecurityControl: 'Ignore'
  SecurityExemption: 'StorageAccountKeyAccess'
  project: 'SwarmAI'
  concept: 'darkfactory'
  owner: 'michalfu'
  environment: 'demo'
}
var token = toLower(uniqueString(subscription().id, resourceGroupName))

resource rg 'Microsoft.Resources/resourceGroups@2024-03-01' = {
  name: resourceGroupName
  location: location
  // azd locates the environment's resource group through this extra tag
  tags: union(commonTags, { 'azd-env-name': environmentName })
}

module monitoring 'modules/monitoring.bicep' = {
  name: 'monitoring'
  scope: rg
  params: { location: location, tags: commonTags, token: token }
}

module identity 'modules/identity.bicep' = {
  name: 'identity'
  scope: rg
  params: { location: location, tags: commonTags, token: token }
}

module data 'modules/data.bicep' = {
  name: 'data'
  scope: rg
  params: {
    location: location
    tags: commonTags
    token: token
    appPrincipalId: identity.outputs.principalId
    userPrincipalId: principalId
    userPrincipalType: principalType
  }
}

module ai 'modules/ai.bicep' = {
  name: 'ai'
  scope: rg
  params: {
    location: location
    tags: commonTags
    token: token
    appPrincipalId: identity.outputs.principalId
    userPrincipalId: principalId
    userPrincipalType: principalType
    chatModelName: chatModelName
    chatModelVersion: chatModelVersion
    chatCapacity: chatCapacity
    reasoningModelName: reasoningModelName
    reasoningModelVersion: reasoningModelVersion
    reasoningCapacity: reasoningCapacity
  }
}

module app 'modules/app.bicep' = {
  name: 'app'
  scope: rg
  params: {
    location: location
    tags: commonTags
    token: token
    identityId: identity.outputs.id
    identityClientId: identity.outputs.clientId
    identityPrincipalId: identity.outputs.principalId
    logAnalyticsName: monitoring.outputs.logAnalyticsName
    appInsightsName: monitoring.outputs.appInsightsName
    appInsightsConnectionString: monitoring.outputs.appInsightsConnectionString
    cosmosEndpoint: data.outputs.cosmosEndpoint
    cosmosDatabase: data.outputs.cosmosDatabase
    storageAccountUrl: data.outputs.storageBlobEndpoint
    openAiEndpoint: ai.outputs.endpoint
    chatDeployment: ai.outputs.chatDeployment
    reasoningDeployment: ai.outputs.reasoningDeployment
    webImageName: webImageName
    dailyAiBudgetUsd: dailyAiBudgetUsd
    enableEntraAuth: enableEntraAuth
    entraClientId: entraClientId
    entraClientSecret: entraClientSecret
    resourceGroupName: resourceGroupName
    subscriptionId: subscription().subscriptionId
  }
}

output AZURE_LOCATION string = location
output AZURE_RESOURCE_GROUP string = rg.name
output AZURE_CONTAINER_REGISTRY_ENDPOINT string = app.outputs.registryLoginServer
output AZURE_CONTAINER_REGISTRY_NAME string = app.outputs.registryName
output WEB_URI string = app.outputs.webUri
output WEB_APP_NAME string = app.outputs.webName
output COSMOS_ENDPOINT string = data.outputs.cosmosEndpoint
output AZURE_OPENAI_ENDPOINT string = ai.outputs.endpoint
output APPINSIGHTS_NAME string = monitoring.outputs.appInsightsName
