param name string

resource existingApp 'Microsoft.App/containerApps@2024-03-01' existing = {
  name: name
}

output image string = existingApp.properties.template.containers[0].image
