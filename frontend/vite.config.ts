import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react()],
  server: {
    proxy: {
      // 后端地址可用 NOVELCOMIC_API 覆盖（并行验证实例连独立后端时用）；SSE 长连接可正常透传
      '/api': process.env.NOVELCOMIC_API || 'http://127.0.0.1:8765',
    },
  },
})
