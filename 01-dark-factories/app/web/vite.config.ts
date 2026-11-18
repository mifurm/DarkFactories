import tailwindcss from '@tailwindcss/vite'
import react from '@vitejs/plugin-react'
import { defineConfig } from 'vitest/config'

const API = process.env.NIGHTSHIFT_API ?? 'http://127.0.0.1:8101'

export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    port: 5101,
    strictPort: true,
    proxy: {
      '/api': { target: API, changeOrigin: false },
      '/healthz': API,
      '/readyz': API,
      '/docs': API,
      '/openapi.json': API,
    },
  },
  build: { outDir: 'dist', sourcemap: false, chunkSizeWarningLimit: 1500 },
  test: { environment: 'jsdom', globals: true, setupFiles: ['./src/test-setup.ts'] },
})
