import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'
import tailwindcss from '@tailwindcss/vite'
import { fileURLToPath, URL } from 'node:url'

// 构建产物直接落到后端的静态目录 ../web，Python 那边不用改任何配置
export default defineConfig({
  plugins: [vue(), tailwindcss()],
  // 把构建时间打进前端：界面上能一眼看出浏览器跑的是哪一版（排查缓存问题用）
  define: {
    __BUILD__: JSON.stringify(new Date().toLocaleString('zh-CN', { hour12: false })),
  },
  base: './',
  build: {
    outDir: '../web',
    emptyOutDir: true,
    chunkSizeWarningLimit: 2000,
  },
  server: {
    port: 5173,
    // 开发时把接口转发给本地 Python 服务（生产是同源，不需要）
    proxy: { '/api': 'http://127.0.0.1:8765' },
  },
  resolve: {
    alias: { '@': fileURLToPath(new URL('./src', import.meta.url)) },
  },
})
