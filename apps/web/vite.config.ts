import path from "node:path"
import tailwindcss from "@tailwindcss/vite"
import react from "@vitejs/plugin-react"
import { defineConfig } from "vite"

// Dev: run `python -m deixis serve --dev` (port 8765); Vite proxies /api to it.
export default defineConfig({
  plugins: [react(), tailwindcss()],
  resolve: { alias: { "@": path.resolve(import.meta.dirname, "./src") } },
  server: { host: "127.0.0.1", port: 5178, strictPort: true, proxy: { "/api": { target: "http://127.0.0.1:8765", changeOrigin: false } } },
})
