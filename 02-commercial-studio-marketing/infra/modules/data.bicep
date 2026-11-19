param location string
param commonTags object
param token string
param appPrincipalId string
param userPrincipalId string

@description('Principal of the GPU motion worker identity (queue consumer + blob read/write on the motion containers). Empty = no motion resources.')
param motionPrincipalId string = ''

// Logical collections used by the app (keep in sync with spotlight.core.repo.COLLECTIONS — unit-tested).
var collections = [
  'brands'
  'brand_chunks'
  'learnings'
  'claims'
  'rights'
  'campaigns'
  'briefs'
  'artifacts'
  'assets'
  'reports'
  'approvals'
  'audit'
  'provenance'
  'experiments'
  'performance'
  'usage'
  'jobs'
  'aicache'
  'webhooks'
  'settings'
  'collections'
  'plans'
]

var cosmosDataContributor = '00000000-0000-0000-0000-000000000002'
var blobDataContributor = 'ba92f5b4-2d11-453d-a403-e96b0029c9fe'
var queueDataContributor = '974c5e8b-45b9-4653-ba55-5f855dd0fb88'
var motionContainers = ['motion-in', 'motion-out', 'motion-models']
var enableMotion = !empty(motionPrincipalId)

resource cosmos 'Microsoft.DocumentDB/databaseAccounts@2024-11-15' = {
  name: 'cosmos-studio-${token}'
  location: location
  tags: commonTags
  kind: 'GlobalDocumentDB'
  properties: {
    databaseAccountOfferType: 'Standard'
    locations: [
      { locationName: location, failoverPriority: 0, isZoneRedundant: false }
    ]
    capabilities: [
      { name: 'EnableServerless' }
    ]
    consistencyPolicy: { defaultConsistencyLevel: 'Session' }
    disableLocalAuth: true
    publicNetworkAccess: 'Enabled'
    minimalTlsVersion: 'Tls12'
  }
}

resource db 'Microsoft.DocumentDB/databaseAccounts/sqlDatabases@2024-11-15' = {
  parent: cosmos
  name: 'studio'
  properties: { resource: { id: 'studio' } }
}

resource containers 'Microsoft.DocumentDB/databaseAccounts/sqlDatabases/containers@2024-11-15' = [
  for c in collections: {
    parent: db
    name: c
    properties: {
      resource: {
        id: c
        partitionKey: { paths: ['/pk'], kind: 'Hash', version: 2 }
        defaultTtl: c == 'aicache' ? 1209600 : -1
        indexingPolicy: {
          indexingMode: 'consistent'
          includedPaths: [{ path: '/*' }]
          excludedPaths: [{ path: '/embedding/?' }, { path: '/blob/?' }, { path: '/"_etag"/?' }]
        }
      }
    }
  }
]

resource appCosmosRole 'Microsoft.DocumentDB/databaseAccounts/sqlRoleAssignments@2024-11-15' = {
  parent: cosmos
  name: guid(cosmos.id, appPrincipalId, cosmosDataContributor)
  properties: {
    roleDefinitionId: '${cosmos.id}/sqlRoleDefinitions/${cosmosDataContributor}'
    principalId: appPrincipalId
    scope: cosmos.id
  }
}

resource userCosmosRole 'Microsoft.DocumentDB/databaseAccounts/sqlRoleAssignments@2024-11-15' = if (!empty(userPrincipalId)) {
  parent: cosmos
  name: guid(cosmos.id, userPrincipalId, cosmosDataContributor)
  properties: {
    roleDefinitionId: '${cosmos.id}/sqlRoleDefinitions/${cosmosDataContributor}'
    principalId: userPrincipalId
    scope: cosmos.id
  }
}

resource storage 'Microsoft.Storage/storageAccounts@2023-05-01' = {
  name: 'st${token}'
  location: location
  tags: commonTags
  sku: { name: 'Standard_LRS' }
  kind: 'StorageV2'
  properties: {
    accessTier: 'Hot'
    allowBlobPublicAccess: false
    allowSharedKeyAccess: false
    defaultToOAuthAuthentication: true
    minimumTlsVersion: 'TLS1_2'
    supportsHttpsTrafficOnly: true
    publicNetworkAccess: 'Enabled'
  }
}

resource blobService 'Microsoft.Storage/storageAccounts/blobServices@2023-05-01' = {
  parent: storage
  name: 'default'
}

resource assetsContainer 'Microsoft.Storage/storageAccounts/blobServices/containers@2023-05-01' = {
  parent: blobService
  name: 'assets'
  properties: { publicAccess: 'None' }
}

resource appBlobRole 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(storage.id, appPrincipalId, blobDataContributor)
  scope: storage
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', blobDataContributor)
    principalId: appPrincipalId
    principalType: 'ServicePrincipal'
  }
}

resource userBlobRole 'Microsoft.Authorization/roleAssignments@2022-04-01' = if (!empty(userPrincipalId)) {
  name: guid(storage.id, userPrincipalId, blobDataContributor)
  scope: storage
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', blobDataContributor)
    principalId: userPrincipalId
    principalType: 'User'
  }
}

// ---- Cinematic motion transport (queue + blobs). Keyless: Entra roles only; the GPU worker has no ingress. ----
resource queueService 'Microsoft.Storage/storageAccounts/queueServices@2023-05-01' = if (enableMotion) {
  parent: storage
  name: 'default'
}

resource motionQueue 'Microsoft.Storage/storageAccounts/queueServices/queues@2023-05-01' = if (enableMotion) {
  parent: queueService
  name: 'motion-jobs'
}

resource motionBlobContainers 'Microsoft.Storage/storageAccounts/blobServices/containers@2023-05-01' = [
  for c in motionContainers: if (enableMotion) {
    parent: blobService
    name: c
    properties: { publicAccess: 'None' }
  }
]

// Least privilege: the GPU worker gets roles on the three motion containers and on the one queue ONLY — never on the account, which also holds
// the `assets` container (campaign assets and the provenance signing key). Studio keeps its account-wide blob role (it owns `assets`) and gets the queue role on the queue.
resource appQueueRole 'Microsoft.Authorization/roleAssignments@2022-04-01' = if (enableMotion) {
  name: guid(motionQueue.id, appPrincipalId, queueDataContributor)
  scope: motionQueue
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', queueDataContributor)
    principalId: appPrincipalId
    principalType: 'ServicePrincipal'
  }
}

// The worker consumes jobs and KEDA reads the queue length with the worker identity (Get Queue Properties).
resource motionQueueRole 'Microsoft.Authorization/roleAssignments@2022-04-01' = if (enableMotion) {
  name: guid(motionQueue.id, motionPrincipalId, queueDataContributor)
  scope: motionQueue
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', queueDataContributor)
    principalId: motionPrincipalId
    principalType: 'ServicePrincipal'
  }
}

resource userQueueRole 'Microsoft.Authorization/roleAssignments@2022-04-01' = if (enableMotion && !empty(userPrincipalId)) {
  name: guid(motionQueue.id, userPrincipalId, queueDataContributor)
  scope: motionQueue
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', queueDataContributor)
    principalId: userPrincipalId
    principalType: 'User'
  }
}

resource motionBlobRoles 'Microsoft.Authorization/roleAssignments@2022-04-01' = [
  for (c, i) in motionContainers: if (enableMotion) {
    name: guid(motionBlobContainers[i].id, motionPrincipalId, blobDataContributor)
    scope: motionBlobContainers[i]
    properties: {
      roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', blobDataContributor)
      principalId: motionPrincipalId
      principalType: 'ServicePrincipal'
    }
  }
]

// Transport blobs are throw-away (Studio keeps every finished clip as a library asset): delete them after 3 days.
resource lifecycle 'Microsoft.Storage/storageAccounts/managementPolicies@2023-05-01' = if (enableMotion) {
  parent: storage
  name: 'default'
  properties: {
    policy: {
      rules: [
        {
          name: 'motion-transport-ttl'
          enabled: true
          type: 'Lifecycle'
          definition: {
            filters: { blobTypes: ['blockBlob'], prefixMatch: ['motion-in/', 'motion-out/'] }
            actions: { baseBlob: { delete: { daysAfterModificationGreaterThan: 3 } } }
          }
        }
      ]
    }
  }
}

output cosmosEndpoint string = cosmos.properties.documentEndpoint
output cosmosDatabase string = db.name
output blobAccountUrl string = storage.properties.primaryEndpoints.blob
output queueAccountUrl string = storage.properties.primaryEndpoints.queue
output storageAccountName string = storage.name
output blobContainer string = assetsContainer.name
