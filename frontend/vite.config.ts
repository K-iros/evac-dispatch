import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react(), tailwindcss()],
  // maplibre-gl 依赖 Web Worker，rolldown-vite 预构建不产出 worker 资源
  // 会导致 maplibre-gl-worker.mjs 404、地图无法初始化，故排除预构建
  optimizeDeps: {
    exclude: ['maplibre-gl'],
  },
  server: {
    port: 5200,
    strictPort: true,
    proxy: {
      // 后端 FastAPI 开发服务
      '/api': {
        target: 'http://localhost:8000',
        changeOrigin: true,
      },
    },
  },
})
