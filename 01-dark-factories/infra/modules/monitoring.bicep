param location string
param tags object
param token string

resource logs 'Microsoft.OperationalInsights/workspaces@2023-09-01' = {
  name: 'log-nightshift-${token}'
  location: location
  tags: tags
  properties: {
    sku: { name: 'PerGB2018' }
    retentionInDays: 30
    workspaceCapping: { dailyQuotaGb: 1 }
  }
}

// Workspace-based; local (key) ingestion disabled -> the app authenticates with its managed identity.
resource appi 'Microsoft.Insights/components@2020-02-02' = {
  name: 'appi-nightshift-${token}'
  location: location
  tags: tags
  kind: 'web'
  properties: {
    Application_Type: 'web'
    WorkspaceResourceId: logs.id
    IngestionMode: 'LogAnalytics'
    DisableLocalAuth: true
  }
}

output logAnalyticsName string = logs.name
output appInsightsName string = appi.name
output appInsightsConnectionString string = appi.properties.ConnectionString
