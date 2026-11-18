// Copies the Swagger UI bundle next to the SPA so /docs works without any CDN.
import { cpSync, existsSync, mkdirSync } from 'node:fs'
import { resolve } from 'node:path'

const src = resolve('node_modules/swagger-ui-dist')
const dst = resolve('dist/swagger')
if (!existsSync(src)) {
  console.warn('swagger-ui-dist not installed; /docs will fall back to the default assets')
} else {
  mkdirSync(dst, { recursive: true })
  for (const f of ['swagger-ui-bundle.js', 'swagger-ui.css', 'favicon-32x32.png']) {
    cpSync(resolve(src, f), resolve(dst, f))
  }
}
