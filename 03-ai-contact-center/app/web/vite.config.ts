import { defineConfig } from 'vitest/config'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'

const api = process.env.CONCIERGE_API_URL ?? 'http://127.0.0.1:8103'

export default defineConfig({
  plugins: [react(), tailwindcss()],
  // `npm test`: dictionary lint, plural / format / sorting rules (pure TypeScript, no browser needed)
  test: { include: ['src/**/*.test.ts'], environment: 'node' },
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
