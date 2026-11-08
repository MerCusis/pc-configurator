import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

// В разработке запросы /api уходят в nginx из docker compose.
// Браузер видит один origin, поэтому CORS не нужен.
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    strictPort: true,
    proxy: {
      '/api': { target: 'http://127.0.0.1:8080', changeOrigin: true },
    },
  },
});
