import { defineConfig } from 'vitest/config'
import react from '@vitejs/plugin-react'

// The browser talks only to this dev server, which forwards the backend's routes to FastAPI. Dev then runs on one
// origin, like the packaged app (where the backend serves the API and the SPA together), so no CORS and no second
// port to reach — WSL2's localhost relay has been seen forwarding 5173 but not 8000, which left every page empty.
const backend = process.env.VITE_BACKEND ?? 'http://127.0.0.1:8000'
// Keys starting with ^ are regexes. `(/|$)` lets /health and /voice-profile through as whole paths. /review and
// /drill need the slash: the SPA owns the bare paths, and only the backend uses /review/… and /drill/…; likewise
// /settings (the SPA page) and /settings/…, /app/… (the backend: YouTube cookies, update check).
const API = '^/(api|attempts|health|jobs|lessons|segments|sessions|voice-profile)(/|$)'
const API_SUBPATHS = '^/(review|drill|settings|app)/'

export default defineConfig({
  plugins: [react()],
  server: { port: 5173, strictPort: true, proxy: { [API]: backend, [API_SUBPATHS]: backend } },
  test: { environment: 'jsdom', globals: true, setupFiles: ['./src/test/setup.ts'] },
})
