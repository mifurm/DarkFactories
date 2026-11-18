param location string
param tags object
param token string

resource mi 'Microsoft.ManagedIdentity/userAssignedIdentities@2023-01-31' = {
  name: 'id-nightshift-${token}'
  location: location
  tags: tags
}

output id string = mi.id
output clientId string = mi.properties.clientId
output principalId string = mi.properties.principalId
