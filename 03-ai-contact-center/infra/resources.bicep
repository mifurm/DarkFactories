// Resource-group scope: everything keyless (managed identity + RBAC only).
targetScope = 'resourceGroup'

param location string
@description('Governance + common tags (SecurityControl, SecurityExemption, project, concept, owner, environment) applied to EVERY taggable resource.')
param commonTags object
param environmentName string
param principalId string = ''
param apiAppExists string = 'false'
param dailyAiBudgetUsd string = '5'
param enableEntraAuth bool = false
param entraClientId string = ''
@secure()
param entraClientSecret string = ''
param deployRealtimeFallback bool = true

var token = toLower(uniqueString(subscription().id, resourceGroup().id, environmentName))
// Every taggable resource below uses `tags: tags` (== commonTags).
var tags = commonTags
var lawName = 'law-cc-${token}'
var appiName = 'appi-cc-${token}'
var miName = 'id-cc-${token}'
var acrName = 'acrcc${token}'
var cosmosName = 'cosmos-cc-${token}'
var storageName = 'stcc${token}'
var aiName = 'ais-cc-${token}'
var envName = 'cae-cc-${token}'
var appName = 'ca-concierge-${token}'
var placeholderImage = 'mcr.microsoft.com/azuredocs/containerapps-helloworld:latest'
var dbName = 'concierge'

// ---- built-in role definition ids ----
var roles = {
  acrPull: '7f951dda-4ed3-4680-a7ca-43fe172d538d'
  acrPush: '8311e382-0749-4cb8-b61a-304f252e45ec'
  blobContributor: 'ba92f5b4-2d11-453d-a403-e96b0029c9fe'
  openAiUser: '5e0bd9bd-7b93-4f28-af87-19fc36ad61bd'
  cogUser: 'a97b65f3-24c7-4388-baec-2e87135dc908'
  speechUser: 'f2dc8367-1007-4938-bd23-fe263f013447'
  metricsPublisher: '3913510d-42f4-4e42-8a64-420c390055eb'
}

// Keep in sync with app/src/concierge/core/collections.py (a unit test enforces this).
var cosmosContainers = [
  'conversations'
  'audit'
  'access_audit'
  'approvals'
  'idempotency'
  'payments'
  'bo_customers'
  'bo_orders'
  'bo_shipments'
  'bo_appointments'
  'bo_returns'
  'bo_refunds'
  'bo_credits'
  'bo_tickets'
  'bo_warranty'
  'kb_docs'
  'kb_chunks'
  'kb_versions'
  'history'
  'wfm_history'
  'voc'
  'qa_reviews'
  'eval_runs'
  'agent_configs'
  'rollouts'
  'campaigns'
  'callbacks'
  'contact_prefs'
  'usage_daily'
  'seed_meta'
  'embeddings_cache'
  'settings'
  'telephony_calls'
  'metrics_samples'
]

var baseModels = [
  { name: 'gpt-5.4-mini', model: 'gpt-5.4-mini', version: '2026-03-17', capacity: 400 }
  { name: 'gpt-5.4', model: 'gpt-5.4', version: '2026-03-05', capacity: 30 }
  { name: 'gpt-5.4-nano', model: 'gpt-5.4-nano', version: '2026-03-17', capacity: 100 }
  { name: 'gpt-realtime-2.1-mini', model: 'gpt-realtime-2.1-mini', version: '2026-07-07', capacity: 10 }
  { name: 'text-embedding-3-small', model: 'text-embedding-3-small', version: '1', capacity: 50 }
  { name: 'gpt-4o-mini-transcribe', model: 'gpt-4o-mini-transcribe', version: '2025-12-15', capacity: 50 }
]
var fallbackModels = deployRealtimeFallback ? [
  { name: 'gpt-realtime-mini', model: 'gpt-realtime-mini', version: '2025-12-15', capacity: 10 }
] : []
var modelDeployments = concat(baseModels, fallbackModels)

// ---------------- monitoring ----------------
resource law 'Microsoft.OperationalInsights/workspaces@2023-09-01' = {
  name: lawName
  location: location
  tags: tags
  properties: {
    sku: { name: 'PerGB2018' }
    retentionInDays: 30
    workspaceCapping: { dailyQuotaGb: 1 }
  }
}

resource appi 'Microsoft.Insights/components@2020-02-02' = {
  name: appiName
  location: location
  kind: 'web'
  tags: tags
  properties: {
    Application_Type: 'web'
    WorkspaceResourceId: law.id
    IngestionMode: 'LogAnalytics'
    DisableLocalAuth: true // Entra-only ingestion: the connection string is an identifier, not a credential
  }
}

// ---------------- identity ----------------
resource mi 'Microsoft.ManagedIdentity/userAssignedIdentities@2023-01-31' = {
  name: miName
  location: location
  tags: tags
}

// ---------------- registry ----------------
resource acr 'Microsoft.ContainerRegistry/registries@2023-07-01' = {
  name: acrName
  location: location
  tags: tags
  sku: { name: 'Basic' }
  properties: {
    adminUserEnabled: false
  }
}

// ---------------- storage (Entra only) ----------------
resource storage 'Microsoft.Storage/storageAccounts@2023-05-01' = {
  name: storageName
  location: location
  tags: tags
  sku: { name: 'Standard_LRS' }
  kind: 'StorageV2'
  properties: {
    allowSharedKeyAccess: false
    allowBlobPublicAccess: false
    minimumTlsVersion: 'TLS1_2'
    supportsHttpsTrafficOnly: true
    defaultToOAuthAuthentication: true
    publicNetworkAccess: 'Enabled'
  }
}

resource blobSvc 'Microsoft.Storage/storageAccounts/blobServices@2023-05-01' = {
  parent: storage
  name: 'default'
}

resource blobContainers 'Microsoft.Storage/storageAccounts/blobServices/containers@2023-05-01' = [for c in ['recordings', 'kb-sources', 'exports']: {
  parent: blobSvc
  name: c
  properties: { publicAccess: 'None' }
}]

// ---------------- Cosmos DB (serverless, Entra RBAC only) ----------------
resource cosmos 'Microsoft.DocumentDB/databaseAccounts@2024-11-15' = {
  name: cosmosName
  location: location
  tags: tags
  kind: 'GlobalDocumentDB'
  properties: {
    databaseAccountOfferType: 'Standard'
    locations: [
      { locationName: location, failoverPriority: 0, isZoneRedundant: false }
    ]
    capabilities: [{ name: 'EnableServerless' }]
    consistencyPolicy: { defaultConsistencyLevel: 'Session' }
    disableLocalAuth: true
    publicNetworkAccess: 'Enabled'
    minimalTlsVersion: 'Tls12'
  }
}

resource cosmosDb 'Microsoft.DocumentDB/databaseAccounts/sqlDatabases@2024-11-15' = {
  parent: cosmos
  name: dbName
  properties: { resource: { id: dbName } }
}

@batchSize(1)
resource cosmosColl 'Microsoft.DocumentDB/databaseAccounts/sqlDatabases/containers@2024-11-15' = [for c in cosmosContainers: {
  parent: cosmosDb
  name: c
  properties: {
    resource: {
      id: c
      partitionKey: { paths: ['/pk'], kind: 'Hash', version: 2 }
      defaultTtl: -1 // items opt in to retention via their own ttl (data-retention policy)
    }
  }
}]

var cosmosDataContributor = '${cosmos.id}/sqlRoleDefinitions/00000000-0000-0000-0000-000000000002'

resource cosmosRoleMi 'Microsoft.DocumentDB/databaseAccounts/sqlRoleAssignments@2024-11-15' = {
  parent: cosmos
  name: guid(cosmos.id, mi.id, 'cosmos-data-contributor')
  properties: {
    roleDefinitionId: cosmosDataContributor
    principalId: mi.properties.principalId
    scope: cosmos.id
  }
}

resource cosmosRoleUser 'Microsoft.DocumentDB/databaseAccounts/sqlRoleAssignments@2024-11-15' = if (!empty(principalId)) {
  parent: cosmos
  name: guid(cosmos.id, principalId, 'cosmos-data-contributor')
  properties: {
    roleDefinitionId: cosmosDataContributor
    principalId: principalId
    scope: cosmos.id
  }
}

// ---------------- AI Services (Foundry) account + model deployments ----------------
resource ai 'Microsoft.CognitiveServices/accounts@2025-06-01' = {
  name: aiName
  location: location
  tags: tags
  kind: 'AIServices'
  sku: { name: 'S0' }
  identity: { type: 'SystemAssigned' }
  properties: {
    customSubDomainName: aiName
    publicNetworkAccess: 'Enabled'
    disableLocalAuth: true
    networkAcls: { defaultAction: 'Allow' }
  }
}

// Parallel deployments on one account fail with RequestConflict -> strictly sequential.
@batchSize(1)
resource aiDeployments 'Microsoft.CognitiveServices/accounts/deployments@2025-06-01' = [for d in modelDeployments: {
  parent: ai
  name: d.name
  tags: tags
  sku: { name: 'GlobalStandard', capacity: d.capacity }
  properties: {
    model: { format: 'OpenAI', name: d.model, version: d.version }
    versionUpgradeOption: 'NoAutoUpgrade'
  }
}]

// ---------------- role assignments ----------------
resource miAcrPull 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  scope: acr
  name: guid(acr.id, mi.id, roles.acrPull)
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', roles.acrPull)
    principalId: mi.properties.principalId
    principalType: 'ServicePrincipal'
  }
}

resource miBlob 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  scope: storage
  name: guid(storage.id, mi.id, roles.blobContributor)
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', roles.blobContributor)
    principalId: mi.properties.principalId
    principalType: 'ServicePrincipal'
  }
}

resource miOpenAi 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  scope: ai
  name: guid(ai.id, mi.id, roles.openAiUser)
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', roles.openAiUser)
    principalId: mi.properties.principalId
    principalType: 'ServicePrincipal'
  }
}

resource miCog 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  scope: ai
  name: guid(ai.id, mi.id, roles.cogUser)
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', roles.cogUser)
    principalId: mi.properties.principalId
    principalType: 'ServicePrincipal'
  }
}

resource miSpeech 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  scope: ai
  name: guid(ai.id, mi.id, roles.speechUser)
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', roles.speechUser)
    principalId: mi.properties.principalId
    principalType: 'ServicePrincipal'
  }
}

resource miMetrics 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  scope: appi
  name: guid(appi.id, mi.id, roles.metricsPublisher)
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', roles.metricsPublisher)
    principalId: mi.properties.principalId
    principalType: 'ServicePrincipal'
  }
}

resource userBlob 'Microsoft.Authorization/roleAssignments@2022-04-01' = if (!empty(principalId)) {
  scope: storage
  name: guid(storage.id, principalId, roles.blobContributor)
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', roles.blobContributor)
    principalId: principalId
    principalType: 'User'
  }
}

resource userOpenAi 'Microsoft.Authorization/roleAssignments@2022-04-01' = if (!empty(principalId)) {
  scope: ai
  name: guid(ai.id, principalId, roles.openAiUser)
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', roles.openAiUser)
    principalId: principalId
    principalType: 'User'
  }
}

resource userCog 'Microsoft.Authorization/roleAssignments@2022-04-01' = if (!empty(principalId)) {
  scope: ai
  name: guid(ai.id, principalId, roles.cogUser)
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', roles.cogUser)
    principalId: principalId
    principalType: 'User'
  }
}

resource userAcrPush 'Microsoft.Authorization/roleAssignments@2022-04-01' = if (!empty(principalId)) {
  scope: acr
  name: guid(acr.id, principalId, roles.acrPush)
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', roles.acrPush)
    principalId: principalId
    principalType: 'User'
  }
}

// ---------------- Container Apps ----------------
resource cae 'Microsoft.App/managedEnvironments@2025-01-01' = {
  name: envName
  location: location
  tags: tags
  properties: {
    appLogsConfiguration: { destination: 'azure-monitor' }
    zoneRedundant: false
    workloadProfiles: [
      { name: 'Consumption', workloadProfileType: 'Consumption' }
    ]
  }
}

resource caeDiag 'Microsoft.Insights/diagnosticSettings@2021-05-01-preview' = {
  name: 'to-log-analytics'
  scope: cae
  properties: {
    workspaceId: law.id
    logs: [
      { category: 'ContainerAppConsoleLogs', enabled: true }
      { category: 'ContainerAppSystemLogs', enabled: true }
    ]
  }
}

module fetchImage 'modules/fetch-container-image.bicep' = {
  name: 'fetch-container-image'
  params: {
    exists: apiAppExists == 'true'
    name: appName
  }
}

var image = (apiAppExists == 'true' && !empty(fetchImage.outputs.containers)) ? fetchImage.outputs.containers[0].image : placeholderImage
var aoaiEndpoint = 'https://${ai.name}.openai.azure.com'

resource app 'Microsoft.App/containerApps@2025-01-01' = {
  name: appName
  location: location
  tags: union(tags, { 'azd-service-name': 'api' })
  identity: {
    type: 'UserAssigned'
    userAssignedIdentities: { '${mi.id}': {} }
  }
  properties: {
    managedEnvironmentId: cae.id
    workloadProfileName: 'Consumption'
    configuration: {
      activeRevisionsMode: 'Single'
      ingress: {
        external: true
        targetPort: 8000
        transport: 'auto'
        allowInsecure: false
        stickySessions: { affinity: 'sticky' }
      }
      registries: [
        { server: acr.properties.loginServer, identity: mi.id }
      ]
      secrets: enableEntraAuth ? [
        { name: 'entra-client-secret', value: entraClientSecret }
      ] : []
    }
    template: {
      containers: [
        {
          name: 'api'
          image: image
          resources: { cpu: json('1.0'), memory: '2Gi' }
          env: [
            { name: 'AZURE_CLIENT_ID', value: mi.properties.clientId }
            { name: 'CONCIERGE_MODE', value: 'azure' }
            { name: 'COSMOS_ENDPOINT', value: cosmos.properties.documentEndpoint }
            { name: 'COSMOS_DATABASE', value: dbName }
            { name: 'STORAGE_ACCOUNT_URL', value: storage.properties.primaryEndpoints.blob }
            { name: 'AZURE_OPENAI_ENDPOINT', value: aoaiEndpoint }
            { name: 'AI_SERVICES_ENDPOINT', value: 'https://${ai.name}.cognitiveservices.azure.com' }
            { name: 'AOAI_DEPLOYMENT_CHAT', value: 'gpt-5.4-mini' }
            { name: 'AOAI_DEPLOYMENT_REASONING', value: 'gpt-5.4' }
            { name: 'AOAI_DEPLOYMENT_NANO', value: 'gpt-5.4-nano' }
            { name: 'AOAI_DEPLOYMENT_REALTIME', value: 'gpt-realtime-2.1-mini' }
            { name: 'AOAI_DEPLOYMENT_REALTIME_FALLBACK', value: deployRealtimeFallback ? 'gpt-realtime-mini' : '' }
            { name: 'AOAI_DEPLOYMENT_EMBED', value: 'text-embedding-3-small' }
            { name: 'AOAI_DEPLOYMENT_TRANSCRIBE', value: 'gpt-4o-mini-transcribe' }
            { name: 'APPLICATIONINSIGHTS_CONNECTION_STRING', value: appi.properties.ConnectionString }
            { name: 'AI_DAILY_BUDGET_USD', value: dailyAiBudgetUsd }
            { name: 'AZURE_RESOURCE_GROUP', value: resourceGroup().name }
            { name: 'AZURE_LOCATION', value: location }
            { name: 'ACR_NAME', value: acr.name }
            { name: 'ENABLE_ENTRA_AUTH', value: string(enableEntraAuth) }
          ]
          probes: [
            { type: 'Startup', httpGet: { path: '/healthz', port: 8000 }, initialDelaySeconds: 3, periodSeconds: 3, failureThreshold: 40 }
            { type: 'Liveness', httpGet: { path: '/healthz', port: 8000 }, periodSeconds: 20, failureThreshold: 3 }
            { type: 'Readiness', httpGet: { path: '/healthz', port: 8000 }, periodSeconds: 10, failureThreshold: 3 }
          ]
        }
      ]
      scale: {
        minReplicas: 1
        // Live conversation fan-out (WebSocket bus) is in-process; scale-out path = Web PubSub / Service Bus (see ARCHITECTURE.md).
        maxReplicas: 1
      }
    }
  }
  dependsOn: [
    miAcrPull
    miOpenAi
    cosmosRoleMi
    aiDeployments
  ]
}

resource appAuth 'Microsoft.App/containerApps/authConfigs@2025-01-01' = if (enableEntraAuth) {
  parent: app
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

output acrLoginServer string = acr.properties.loginServer
output acrName string = acr.name
output appName string = app.name
output appUrl string = 'https://${app.properties.configuration.ingress.fqdn}'
output cosmosEndpoint string = cosmos.properties.documentEndpoint
output openAiEndpoint string = aoaiEndpoint
output aiName string = ai.name
