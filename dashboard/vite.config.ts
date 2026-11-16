import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

// 开发端口与后端代理：后端默认监听 9800（见 backend/config），/api 与 /v1 都转发过去
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    open: false,
    proxy: {
      // 用 127.0.0.1 显式走 IPv4：后端只监听 IPv4，
      // 用 localhost 时 Node 会先试 ::1（IPv6）→ ECONNREFUSED / AggregateError
      '/api': { target: 'http://127.0.0.1:9800', changeOrigin: true },
      '/v1': { target: 'http://127.0.0.1:9800', changeOrigin: true },
    },
  },
});
