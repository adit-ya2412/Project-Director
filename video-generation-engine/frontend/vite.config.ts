import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import path from 'node:path'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: {
      '@': path.resolve(__dirname, './src'),
    },
  },
  server: {
    port: 5173,
    proxy: {
      // Dev-only convenience: lets the app use relative `/api/v1/...` paths
      // (same as production, where FastAPI serves the built static files
      // and the API from the same origin) while Vite's dev server still
      // runs standalone. Backend CORS is already configured too, so this
      // is a nicety, not a requirement.
      '/api': {
        target: 'http://127.0.0.1:8000',
        changeOrigin: true,
      },
    },
  },
})
