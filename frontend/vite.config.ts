import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'

// https://vite.dev/config/
export default defineConfig({
  // Served same-origin under /demo/ by the FastAPI engine's StaticFiles
  // mount (src/main.py) -- /agent already claims "/" for the chat page.
  // vite dev (local, unaffected) still serves from / on its own port.
  base: process.env.NODE_ENV === 'production' ? '/demo/' : '/',
  plugins: [
    react(),
    tailwindcss(),
  ],
})
