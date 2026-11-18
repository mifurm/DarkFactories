param location string
param commonTags object

resource identity 'Microsoft.ManagedIdentity/userAssignedIdentities@2023-01-31' = {
  name: 'id-studio-app'
  location: location
  tags: commonTags
}

// GPU motion worker: its own identity, so it can reach only the motion queue/blobs and pull its image (no Cosmos, no Azure OpenAI).
resource motionIdentity 'Microsoft.ManagedIdentity/userAssignedIdentities@2023-01-31' = {
  name: 'id-studio-motion'
  location: location
  tags: commonTags
}

output id string = identity.id
output principalId string = identity.properties.principalId
output clientId string = identity.properties.clientId
output motionId string = motionIdentity.id
output motionPrincipalId string = motionIdentity.properties.principalId
output motionClientId string = motionIdentity.properties.clientId
