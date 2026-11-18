param location string
param commonTags object
param token string
param identityId string
param identityClientId string
param logAnalyticsId string
param appInsightsConnectionString string
param acrName string
param acrLoginServer string
param cosmosEndpoint string
param cosmosDatabase string
param blobAccountUrl string
param blobContainer string
param openAiEndpoint string
param aiEndpoint string
param deployments array
param webAppExists bool
param appImage string
param dailyAiBudgetUsd string
param campaignAiBudgetUsd string
param enableEntraAuth bool
param entraClientId string
param cpu string
param memory string
param maxReplicas int

var appName = 'ca-studio-web'
var placeholderImage = 'mcr.microsoft.com/azuredocs/containerapps-helloworld:latest'

resource env 'Microsoft.App/managedEnvironments@2024-03-01' = {
  name: 'cae-studio-${take(token, 6)}'
  location: location
  tags: commonTags
  properties: {
    // Keyless log routing (diagnostic settings) instead of a Log Analytics shared key.
    appLogsConfiguration: { destination: 'azure-monitor' }
    workloadProfiles: [
      { name: 'Consumption', workloadProfileType: 'Consumption' }
    ]
  }
}

resource envDiag 'Microsoft.Insights/diagnosticSettings@2021-05-01-preview' = {
  name: 'to-log-analytics'
  scope: env
  properties: {
    workspaceId: logAnalyticsId
    logs: [
      { categoryGroup: 'allLogs', enabled: true }
    ]
  }
}

// azd pattern: keep the already deployed image when the app exists (idempotent re-provision).
module existingImage 'app-image.bicep' = if (webAppExists && empty(appImage)) {
  name: 'existing-image'
  params: { name: appName }
}

var effectiveImage = !empty(appImage) ? appImage : (webAppExists ? existingImage!.outputs.image : placeholderImage)
var isPlaceholder = effectiveImage == placeholderImage

var modelEnv = [for d in deployments: { name: 'MODEL_${toUpper(d.role)}', value: d.name }]

var baseEnv = [
  { name: 'SPOTLIGHT_MODE', value: 'azure' }
  { name: 'AZURE_CLIENT_ID', value: identityClientId }
  { name: 'AZURE_REGION', value: location }
  { name: 'COSMOS_ENDPOINT', value: cosmosEndpoint }
  { name: 'COSMOS_DATABASE', value: cosmosDatabase }
  { name: 'BLOB_ACCOUNT_URL', value: blobAccountUrl }
  { name: 'BLOB_CONTAINER', value: blobContainer }
  { name: 'AZURE_OPENAI_ENDPOINT', value: openAiEndpoint }
  { name: 'AI_ENDPOINT', value: aiEndpoint }
  { name: 'DAILY_AI_BUDGET_USD', value: dailyAiBudgetUsd }
  { name: 'CAMPAIGN_AI_BUDGET_USD', value: campaignAiBudgetUsd }
  { name: 'APPLICATIONINSIGHTS_CONNECTION_STRING', value: appInsightsConnectionString }
  { name: 'OTEL_SERVICE_NAME', value: 'spotlight-studio' }
  { name: 'PORT', value: '8000' }
]

var authEnv = enableEntraAuth ? [{ name: 'OVERRIDE_USE_MI_FIC_ASSERTION_CLIENTID', value: identityClientId }] : []

var probes = isPlaceholder ? [] : [
  { type: 'Startup', httpGet: { path: '/healthz', port: 8000 }, periodSeconds: 3, failureThreshold: 60 }
  { type: 'Liveness', httpGet: { path: '/healthz', port: 8000 }, periodSeconds: 20, failureThreshold: 3 }
  { type: 'Readiness', httpGet: { path: '/healthz', port: 8000 }, periodSeconds: 10, failureThreshold: 3 }
]

resource app 'Microsoft.App/containerApps@2024-03-01' = {
  name: appName
  location: location
  tags: union(commonTags, { 'azd-service-name': 'web' })
  identity: {
    type: 'UserAssigned'
    userAssignedIdentities: { '${identityId}': {} }
  }
  properties: {
    managedEnvironmentId: env.id
    workloadProfileName: 'Consumption'
    configuration: {
      activeRevisionsMode: 'Single'
      ingress: {
        external: true
        targetPort: 8000
        transport: 'auto'
        allowInsecure: false
      }
      registries: [
        { server: acrLoginServer, identity: identityId }
      ]
      secrets: enableEntraAuth ? [{ name: 'override-use-mi-fic-assertion-client-id', value: identityClientId }] : []
    }
    template: {
      containers: [
        {
          name: 'web'
          image: effectiveImage
          resources: { cpu: json(cpu), memory: memory }
          env: concat(baseEnv, modelEnv, authEnv)
          probes: probes
        }
      ]
      scale: {
        minReplicas: 1
        maxReplicas: maxReplicas
        rules: [
          { name: 'http', http: { metadata: { concurrentRequests: '40' } } }
        ]
      }
    }
  }
}

// Optional hardening (documented, not exercised by the demo deployment): Entra ID in front of the app.
resource auth 'Microsoft.App/containerApps/authConfigs@2024-03-01' = if (enableEntraAuth) {
  parent: app
  name: 'current'
  properties: {
    platform: { enabled: true }
    globalValidation: {
      unauthenticatedClientAction: 'RedirectToLoginPage'
      excludedPaths: ['/healthz']
    }
    identityProviders: {
      azureActiveDirectory: {
        enabled: true
        registration: {
          openIdIssuer: '${environment().authentication.loginEndpoint}${tenant().tenantId}/v2.0'
          clientId: entraClientId
          clientSecretSettingName: 'override-use-mi-fic-assertion-client-id'
        }
      }
    }
    login: { tokenStore: { enabled: false } }
  }
}

output name string = app.name
output uri string = 'https://${app.properties.configuration.ingress.fqdn}'
output acrName string = acrName
output image string = effectiveImage
output blobContainerName string = blobContainer
