param location string
param tags object
param token string
param identityId string
param identityClientId string
param identityPrincipalId string
param logAnalyticsName string
param appInsightsName string
param appInsightsConnectionString string
param cosmosEndpoint string
param cosmosDatabase string
param storageAccountUrl string
param openAiEndpoint string
param chatDeployment string
param reasoningDeployment string
param webImageName string
param dailyAiBudgetUsd string
param enableEntraAuth bool = false
param entraClientId string = ''
@secure()
param entraClientSecret string = ''
param resourceGroupName string
param subscriptionId string

var acrPull = '7f951dda-4ed3-4680-a7ca-43fe172d538d'
var monitoringMetricsPublisher = '3913510d-42f4-4e42-8a64-420c390055eb'
var reader = 'acdd72a7-3385-48ef-bd42-f606fba81ae7'
var placeholderImage = 'mcr.microsoft.com/k8se/quickstart:latest'
var image = empty(webImageName) ? placeholderImage : webImageName

resource logs 'Microsoft.OperationalInsights/workspaces@2023-09-01' existing = { name: logAnalyticsName }
resource appi 'Microsoft.Insights/components@2020-02-02' existing = { name: appInsightsName }

resource acr 'Microsoft.ContainerRegistry/registries@2023-07-01' = {
  name: 'acrns${token}'
  location: location
  tags: tags
  sku: { name: 'Basic' }
  properties: { adminUserEnabled: false, publicNetworkAccess: 'Enabled' }
}

resource acrPullRole 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  scope: acr
  name: guid(acr.id, identityPrincipalId, acrPull)
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', acrPull)
    principalId: identityPrincipalId
    principalType: 'ServicePrincipal'
  }
}

resource metricsRole 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  scope: appi
  name: guid(appi.id, identityPrincipalId, monitoringMetricsPublisher)
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', monitoringMetricsPublisher)
    principalId: identityPrincipalId
    principalType: 'ServicePrincipal'
  }
}

// Reader on the resource group lets the Deployment page list the live resource inventory.
resource readerRole 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(resourceGroup().id, identityPrincipalId, reader)
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', reader)
    principalId: identityPrincipalId
    principalType: 'ServicePrincipal'
  }
}

resource env 'Microsoft.App/managedEnvironments@2024-03-01' = {
  name: 'cae-nightshift-${token}'
  location: location
  tags: tags
  properties: {
    appLogsConfiguration: {
      destination: 'log-analytics'
      logAnalyticsConfiguration: {
        customerId: logs.properties.customerId
        sharedKey: logs.listKeys().primarySharedKey
      }
    }
  }
}

resource web 'Microsoft.App/containerApps@2024-03-01' = {
  name: 'ca-nightshift'
  location: location
  tags: union(tags, { 'azd-service-name': 'web' })
  identity: { type: 'UserAssigned', userAssignedIdentities: { '${identityId}': {} } }
  dependsOn: [acrPullRole]
  properties: {
    managedEnvironmentId: env.id
    configuration: {
      activeRevisionsMode: 'Single'
      ingress: { external: true, targetPort: 8000, transport: 'auto', allowInsecure: false }
      registries: [{ server: acr.properties.loginServer, identity: identityId }]
      secrets: enableEntraAuth ? [{ name: 'entra-client-secret', value: entraClientSecret }] : []
    }
    template: {
      containers: [
        {
          name: 'web'
          image: image
          resources: { cpu: json('0.5'), memory: '1Gi' } // measured: ~30 mCores / 280 MB with all three plants live; A/B replays burst higher
          env: [
            { name: 'NIGHTSHIFT_MODE', value: 'azure' }
            { name: 'AZURE_CLIENT_ID', value: identityClientId }
            { name: 'AZURE_REGION', value: location }
            { name: 'AZURE_SUBSCRIPTION_ID', value: subscriptionId }
            { name: 'AZURE_RESOURCE_GROUP', value: resourceGroupName }
            { name: 'COSMOS_ENDPOINT', value: cosmosEndpoint }
            { name: 'COSMOS_DATABASE', value: cosmosDatabase }
            { name: 'STORAGE_ACCOUNT_URL', value: storageAccountUrl }
            { name: 'AZURE_OPENAI_ENDPOINT', value: openAiEndpoint }
            { name: 'AZURE_OPENAI_CHAT_DEPLOYMENT', value: chatDeployment }
            { name: 'AZURE_OPENAI_REASONING_DEPLOYMENT', value: reasoningDeployment }
            { name: 'APPLICATIONINSIGHTS_CONNECTION_STRING', value: appInsightsConnectionString }
            { name: 'AI_DAILY_BUDGET_USD', value: dailyAiBudgetUsd }
            { name: 'PORT', value: '8000' }
          ]
          probes: [
            { type: 'Liveness', httpGet: { path: '/healthz', port: 8000 }, initialDelaySeconds: 10, periodSeconds: 20, timeoutSeconds: 5, failureThreshold: 5 }
            { type: 'Readiness', httpGet: { path: '/healthz', port: 8000 }, initialDelaySeconds: 5, periodSeconds: 10, timeoutSeconds: 5, failureThreshold: 6 }
            { type: 'Startup', httpGet: { path: '/healthz', port: 8000 }, initialDelaySeconds: 3, periodSeconds: 5, timeoutSeconds: 3, failureThreshold: 30 }
          ]
        }
      ]
      // One replica: the live plant simulation is in-process state (scale out by partitioning plants; see ARCHITECTURE.md).
      scale: { minReplicas: 1, maxReplicas: 1 }
    }
  }
}

resource auth 'Microsoft.App/containerApps/authConfigs@2024-03-01' = if (enableEntraAuth) {
  parent: web
  name: 'current'
  properties: {
    platform: { enabled: true }
    globalValidation: { unauthenticatedClientAction: 'RedirectToLoginPage', redirectToProvider: 'azureactivedirectory', excludedPaths: ['/healthz'] }
    identityProviders: {
      azureActiveDirectory: {
        enabled: true
        registration: {
          clientId: entraClientId
          clientSecretSettingName: 'entra-client-secret'
          openIdIssuer: '${environment().authentication.loginEndpoint}${tenant().tenantId}/v2.0'
        }
      }
    }
  }
}

output registryLoginServer string = acr.properties.loginServer
output registryName string = acr.name
output webUri string = 'https://${web.properties.configuration.ingress.fqdn}'
output webName string = web.name
