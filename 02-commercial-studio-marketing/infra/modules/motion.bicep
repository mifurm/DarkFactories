// GPU motion worker: runs the open image-to-video model (Wan 2.2 TI2V-5B, Apache-2.0) on a serverless A100 and consumes jobs
// from the Storage queue. No ingress, keyless (user-assigned identity), scale-to-zero via the KEDA azure-queue scaler.
// The environment has quota for ONE A100: keep maxReplicas = 1 and deploy new revisions while the queue is idle.
param location string
param commonTags object
param environmentId string
param identityId string
param identityClientId string
param acrLoginServer string

@description('Worker image. Empty = placeholder (the app then never scales above 0 because the queue is empty).')
param image string = ''
param motionAppExists bool = false

param blobAccountUrl string
param queueAccountUrl string
param storageAccountName string

param modelRepo string = 'Wan-AI/Wan2.2-TI2V-5B-Diffusers'
param modelRevision string = 'b8fff7315c768468a5333511427288870b2e9635'

@description('vCPU / memory allocated to the replica (billed per second with the GPU).')
param cpu string = '8'
param memory string = '64Gi'
param maxReplicas int = 1
@description('Seconds the replica stays up after the queue drains (cold start is ~4 min, so keep it warm between renders).')
param cooldownSeconds int = 420

var appName = 'ca-studio-motion'
var placeholderImage = 'mcr.microsoft.com/azuredocs/containerapps-helloworld:latest'

module existingImage 'app-image.bicep' = if (motionAppExists && empty(image)) {
  name: 'existing-motion-image'
  params: { name: appName }
}

var effectiveImage = !empty(image) ? image : (motionAppExists ? existingImage!.outputs.image : placeholderImage)

resource worker 'Microsoft.App/containerApps@2025-01-01' = {
  name: appName
  location: location
  tags: union(commonTags, { 'azd-service-name': 'motion' })
  identity: {
    type: 'UserAssigned'
    userAssignedIdentities: { '${identityId}': {} }
  }
  properties: {
    managedEnvironmentId: environmentId
    workloadProfileName: 'gpu-a100'
    configuration: {
      activeRevisionsMode: 'Single'
      registries: [
        { server: acrLoginServer, identity: identityId }
      ]
    }
    template: {
      terminationGracePeriodSeconds: 600
      containers: [
        {
          name: 'motion'
          image: effectiveImage
          resources: { cpu: json(cpu), memory: memory }
          env: [
            { name: 'MOTION_TRANSPORT', value: 'azure' }
            { name: 'MOTION_PIPELINE', value: 'wan' }
            { name: 'AZURE_CLIENT_ID', value: identityClientId }
            { name: 'MOTION_STORAGE_ACCOUNT_URL', value: blobAccountUrl }
            { name: 'MOTION_QUEUE_URL', value: queueAccountUrl }
            { name: 'MOTION_QUEUE_NAME', value: 'motion-jobs' }
            { name: 'MOTION_IN_CONTAINER', value: 'motion-in' }
            { name: 'MOTION_OUT_CONTAINER', value: 'motion-out' }
            { name: 'MOTION_MODELS_CONTAINER', value: 'motion-models' }
            { name: 'MOTION_MODEL_ID', value: 'wan2.2-ti2v-5b' }
            { name: 'MOTION_MODEL_REPO', value: modelRepo }
            { name: 'MOTION_MODEL_REVISION', value: modelRevision }
            { name: 'MOTION_MODEL_DIR', value: '/tmp/models' }
          ]
        }
      ]
      scale: {
        minReplicas: 0
        maxReplicas: maxReplicas
        cooldownPeriod: cooldownSeconds
        pollingInterval: 15
        rules: [
          {
            name: 'motion-queue'
            custom: {
              type: 'azure-queue'
              metadata: {
                queueName: 'motion-jobs'
                queueLength: '1'
                accountName: storageAccountName
                cloud: 'AzurePublicCloud'
              }
              identity: identityId
            }
          }
        ]
      }
    }
  }
}

output name string = worker.name
output image string = effectiveImage
