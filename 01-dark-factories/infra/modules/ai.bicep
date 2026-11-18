param location string
param tags object
param token string
param appPrincipalId string
param userPrincipalId string = ''
param userPrincipalType string = 'User'
param chatModelName string
param chatModelVersion string
param chatCapacity int
param reasoningModelName string
param reasoningModelVersion string
param reasoningCapacity int

var openAiUser = '5e0bd9bd-7b93-4f28-af87-19fc36ad61bd'
var cognitiveServicesUser = 'a97b65f3-24c7-4388-baec-2e87135dc908'
var accountName = 'ais-nightshift-${token}'

resource account 'Microsoft.CognitiveServices/accounts@2024-10-01' = {
  name: accountName
  location: location
  tags: tags
  kind: 'AIServices'
  sku: { name: 'S0' }
  properties: {
    customSubDomainName: accountName
    publicNetworkAccess: 'Enabled'
    disableLocalAuth: true
  }
}

// Deployments on one account must be created sequentially (parallel -> RequestConflict).
resource chat 'Microsoft.CognitiveServices/accounts/deployments@2024-10-01' = {
  parent: account
  name: 'chat'
  sku: { name: 'GlobalStandard', capacity: chatCapacity }
  properties: { model: { format: 'OpenAI', name: chatModelName, version: chatModelVersion } }
}

resource reasoning 'Microsoft.CognitiveServices/accounts/deployments@2024-10-01' = {
  parent: account
  name: 'reasoning'
  dependsOn: [chat]
  sku: { name: 'GlobalStandard', capacity: reasoningCapacity }
  properties: { model: { format: 'OpenAI', name: reasoningModelName, version: reasoningModelVersion } }
}

resource appOpenAi 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  scope: account
  name: guid(account.id, appPrincipalId, openAiUser)
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', openAiUser)
    principalId: appPrincipalId
    principalType: 'ServicePrincipal'
  }
}

resource appCogUser 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  scope: account
  name: guid(account.id, appPrincipalId, cognitiveServicesUser)
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', cognitiveServicesUser)
    principalId: appPrincipalId
    principalType: 'ServicePrincipal'
  }
}

resource userOpenAi 'Microsoft.Authorization/roleAssignments@2022-04-01' = if (!empty(userPrincipalId)) {
  scope: account
  name: guid(account.id, userPrincipalId, openAiUser)
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', openAiUser)
    principalId: userPrincipalId
    principalType: userPrincipalType
  }
}

output endpoint string = 'https://${accountName}.openai.azure.com/'
output accountName string = account.name
output chatDeployment string = chat.name
output reasoningDeployment string = reasoning.name
