param location string
param commonTags object
param token string
param appPrincipalId string
param userPrincipalId string

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

output cosmosEndpoint string = cosmos.properties.documentEndpoint
output cosmosDatabase string = db.name
output blobAccountUrl string = storage.properties.primaryEndpoints.blob
output blobContainer string = assetsContainer.name
