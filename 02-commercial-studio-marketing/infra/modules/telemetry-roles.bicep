param appInsightsName string
param appPrincipalId string
param userPrincipalId string

var metricsPublisherRole = '3913510d-42f4-4e42-8a64-420c390055eb'

resource appInsights 'Microsoft.Insights/components@2020-02-02' existing = {
  name: appInsightsName
}

resource appPublish 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(appInsights.id, appPrincipalId, metricsPublisherRole)
  scope: appInsights
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', metricsPublisherRole)
    principalId: appPrincipalId
    principalType: 'ServicePrincipal'
  }
}

resource userPublish 'Microsoft.Authorization/roleAssignments@2022-04-01' = if (!empty(userPrincipalId)) {
  name: guid(appInsights.id, userPrincipalId, metricsPublisherRole)
  scope: appInsights
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', metricsPublisherRole)
    principalId: userPrincipalId
    principalType: 'User'
  }
}
