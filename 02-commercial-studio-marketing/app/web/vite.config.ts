import { defineConfig } from "vitest/config";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";

// Dev: Vite on 5102 proxies the API (8102) so the browser only ever talks to one origin (no CORS).
// SPOTLIGHT_API / SPOTLIGHT_WEB_PORT let a second dev instance run next to it (e.g. SPOTLIGHT_API=http://127.0.0.1:8112 vite --port 5112).
const API = process.env.SPOTLIGHT_API ?? "http://127.0.0.1:8102";
const PORT = Number(process.env.SPOTLIGHT_WEB_PORT ?? 5102);
const proxy = {
  "/api": { target: API, changeOrigin: false },
  "/healthz": API,
  "/readyz": API,
  "/docs": API,
  "/openapi.json": API,
};

export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: { port: PORT, strictPort: true, proxy },
  preview: { proxy },
  build: { outDir: "dist", sourcemap: false, chunkSizeWarningLimit: 1200 },
  test: { include: ["src/**/*.test.ts"], environment: "node" },
});
