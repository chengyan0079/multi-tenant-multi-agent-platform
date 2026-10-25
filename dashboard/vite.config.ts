import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

// 开发端口与后端代理：后端默认监听 9800（见 backend/config），/api 与 /v1 都转发过去
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    open: false,
    proxy: {
      '/api': { target: 'http://localhost:9800', changeOrigin: true },
      '/v1': { target: 'http://localhost:9800', changeOrigin: true },
    },
  },
});
