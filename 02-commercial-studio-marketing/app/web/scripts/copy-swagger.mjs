import { cpSync, mkdirSync, existsSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

// Serve Swagger UI from the same origin (no CDN fetches): copy the three files /docs needs into public/swagger.
const root = join(dirname(fileURLToPath(import.meta.url)), "..");
const src = join(root, "node_modules", "swagger-ui-dist");
const dst = join(root, "public", "swagger");
if (existsSync(src)) {
  mkdirSync(dst, { recursive: true });
  for (const f of ["swagger-ui-bundle.js", "swagger-ui.css", "favicon-32x32.png"]) cpSync(join(src, f), join(dst, f));
}
