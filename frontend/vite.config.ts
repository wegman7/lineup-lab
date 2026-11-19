import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

// In dev, the API runs on :8000 (uvicorn); in production both are one origin (one container).
export default defineConfig({
  plugins: [react()],
  server: {
    proxy: {
      '/chat': 'http://localhost:8000',
      '/api': 'http://localhost:8000',
    },
  },
})
