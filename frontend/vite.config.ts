import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

// In production the bundle is served by the FastAPI app from /app
// (see backend/api/main.py), so asset URLs must be prefixed with /app/.
// The dev server keeps serving from the site root (/).
export default defineConfig(({ command }) => ({
  base: command === 'build' ? '/app/' : '/',
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      '/api': {
        target: 'http://localhost:8000',
        changeOrigin: true,
      },
    },
  },
}));
