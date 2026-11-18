// Reads the image currently deployed to the container app so re-provisioning never reverts it to the placeholder.
param exists bool
param name string

resource existingApp 'Microsoft.App/containerApps@2025-01-01' existing = if (exists) {
  name: name
}

output containers array = exists ? existingApp.properties.template.containers : []
