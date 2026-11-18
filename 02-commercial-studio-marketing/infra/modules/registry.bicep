param location string
param commonTags object
param token string
param appPrincipalId string

@description('More principals allowed to pull images (the GPU motion worker identity).')
param extraPullPrincipalIds array = []

@description('Standard (100 GiB) is needed for the GPU worker image (~7 GiB of layers per version); Basic is capped at 10 GiB.')
@allowed(['Basic', 'Standard', 'Premium'])
param sku string = 'Standard'

var acrPullRole = '7f951dda-4ed3-4680-a7ca-43fe172d538d'

resource acr 'Microsoft.ContainerRegistry/registries@2023-07-01' = {
  name: 'acrstudio${token}'
  location: location
  tags: commonTags
  sku: { name: sku }
  properties: {
    adminUserEnabled: false
    publicNetworkAccess: 'Enabled'
  }
}

resource pull 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(acr.id, appPrincipalId, acrPullRole)
  scope: acr
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', acrPullRole)
    principalId: appPrincipalId
    principalType: 'ServicePrincipal'
  }
}

resource extraPull 'Microsoft.Authorization/roleAssignments@2022-04-01' = [
  for principalId in extraPullPrincipalIds: {
    name: guid(acr.id, principalId, acrPullRole)
    scope: acr
    properties: {
      roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', acrPullRole)
      principalId: principalId
      principalType: 'ServicePrincipal'
    }
  }
]

output name string = acr.name
output loginServer string = acr.properties.loginServer
