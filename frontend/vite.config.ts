import { fileURLToPath, URL } from 'node:url'
import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'
import { viteSingleFile } from 'vite-plugin-singlefile'

// В деве Vite-сервер проксирует /api и /media на Django (127.0.0.1:8000),
// чтобы фронт и бэкенд жили на одном origin и не воевали с CORS/куками.
export default defineConfig({
  // viteSingleFile инлайнит весь JS/CSS в один index.html — тогда при
  // открытии из Битрикс24 нет под-запросов к /assets (это ломало работу
  // через ngrok-free: он подсовывал HTML-заглушку вместо чанков → белый экран),
  // как и было у старого самодостаточного app.html.
  plugins: [vue(), viteSingleFile()],
  resolve: {
    alias: {
      '@': fileURLToPath(new URL('./src', import.meta.url)),
    },
  },
  server: {
    port: 5173,
    proxy: {
      '/api': { target: 'http://127.0.0.1:8000', changeOrigin: true },
      '/media': { target: 'http://127.0.0.1:8000', changeOrigin: true },
      '/external': { target: 'http://127.0.0.1:8000', changeOrigin: true },
    },
  },
  build: {
    // Собранная статика уедет в dist/, её отдаёт nginx в проде.
    outDir: 'dist',
    emptyOutDir: true,
  },
})
