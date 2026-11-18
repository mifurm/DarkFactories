param location string
param commonTags object
param token string
param appPrincipalId string
param userPrincipalId string

var openAiUserRole = '5e0bd9bd-7b93-4f28-af87-19fc36ad61bd'
var cogServicesUserRole = 'a97b65f3-24c7-4388-baec-2e87135dc908'

// Role -> deployment. Capacities are deliberately modest ("K TPM" / units) to leave quota for others.
// tts-hd (Standard) and gpt-image-1.5 are the verified-available speech / image models in swedencentral.
var modelDeployments = [
  { role: 'chat', name: 'gpt-5.4-mini', model: 'gpt-5.4-mini', version: '2026-03-17', sku: 'GlobalStandard', capacity: 100 }
  { role: 'reasoning', name: 'gpt-5.4', model: 'gpt-5.4', version: '2026-03-05', sku: 'GlobalStandard', capacity: 50 }
  { role: 'embed', name: 'text-embedding-3-small', model: 'text-embedding-3-small', version: '1', sku: 'GlobalStandard', capacity: 50 }
  { role: 'tts', name: 'tts-hd', model: 'tts-hd', version: '001', sku: 'Standard', capacity: 2 }
  { role: 'image', name: 'gpt-image-1.5', model: 'gpt-image-1.5', version: '2025-12-16', sku: 'GlobalStandard', capacity: 3 }
  { role: 'image_draft', name: 'gpt-image-1-mini', model: 'gpt-image-1-mini', version: '2025-10-06', sku: 'GlobalStandard', capacity: 3 }
]

resource ai 'Microsoft.CognitiveServices/accounts@2024-10-01' = {
  name: 'ais-studio-${token}'
  location: location
  tags: commonTags
  kind: 'AIServices'
  sku: { name: 'S0' }
  identity: { type: 'SystemAssigned' }
  properties: {
    customSubDomainName: 'ais-studio-${token}'
    publicNetworkAccess: 'Enabled'
    disableLocalAuth: true
  }
}

// Deployments must be created sequentially on one account (parallel creation => RequestConflict).
@batchSize(1)
resource deployments 'Microsoft.CognitiveServices/accounts/deployments@2024-10-01' = [
  for d in modelDeployments: {
    parent: ai
    name: d.name
    sku: { name: d.sku, capacity: d.capacity }
    properties: {
      model: { format: 'OpenAI', name: d.model, version: d.version }
    }
  }
]

resource appOpenAi 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(ai.id, appPrincipalId, openAiUserRole)
  scope: ai
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', openAiUserRole)
    principalId: appPrincipalId
    principalType: 'ServicePrincipal'
  }
}

resource appCogUser 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(ai.id, appPrincipalId, cogServicesUserRole)
  scope: ai
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', cogServicesUserRole)
    principalId: appPrincipalId
    principalType: 'ServicePrincipal'
  }
}

resource userOpenAi 'Microsoft.Authorization/roleAssignments@2022-04-01' = if (!empty(userPrincipalId)) {
  name: guid(ai.id, userPrincipalId, openAiUserRole)
  scope: ai
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', openAiUserRole)
    principalId: userPrincipalId
    principalType: 'User'
  }
}

resource userCogUser 'Microsoft.Authorization/roleAssignments@2022-04-01' = if (!empty(userPrincipalId)) {
  name: guid(ai.id, userPrincipalId, cogServicesUserRole)
  scope: ai
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', cogServicesUserRole)
    principalId: userPrincipalId
    principalType: 'User'
  }
}

output openAiEndpoint string = 'https://${ai.properties.customSubDomainName}.openai.azure.com/'
output aiEndpoint string = 'https://${ai.properties.customSubDomainName}.cognitiveservices.azure.com/'
output deployments array = [for d in modelDeployments: { role: d.role, name: d.name }]
