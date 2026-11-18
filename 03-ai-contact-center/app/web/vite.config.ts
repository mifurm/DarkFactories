import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'

const api = 'http://127.0.0.1:8103'

export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    host: '127.0.0.1',
    port: 5103,
    proxy: {
      '/api': { target: api, changeOrigin: false },
      '/ws': { target: api.replace('http', 'ws'), ws: true, changeOrigin: false },
      '/healthz': api,
      '/readyz': api,
      '/docs': api,
      '/openapi.json': api,
    },
  },
  build: { outDir: 'dist', sourcemap: false, chunkSizeWarningLimit: 900 },
})
