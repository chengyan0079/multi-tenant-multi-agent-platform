import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

// 开发端口；如需对接后端可在此配置 proxy
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    open: false,
    // 对接本地后端：/api/v1/*（含 /api/v1/agents、/api/v1/config）与部分 /v1/* 路由
    proxy: {
      '/api': { target: 'http://localhost:8000', changeOrigin: true },
      '/v1': { target: 'http://localhost:8000', changeOrigin: true },
    },
  },
});
