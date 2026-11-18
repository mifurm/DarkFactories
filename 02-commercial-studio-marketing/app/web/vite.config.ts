import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";

// Dev: Vite on 5102 proxies the API (8102) so the browser only ever talks to one origin (no CORS).
export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    port: 5102,
    strictPort: true,
    proxy: {
      "/api": { target: "http://127.0.0.1:8102", changeOrigin: false },
      "/healthz": "http://127.0.0.1:8102",
      "/readyz": "http://127.0.0.1:8102",
      "/docs": "http://127.0.0.1:8102",
      "/openapi.json": "http://127.0.0.1:8102",
    },
  },
  build: { outDir: "dist", sourcemap: false, chunkSizeWarningLimit: 1200 },
});
