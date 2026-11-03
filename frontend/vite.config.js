import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'

// Сборка в frontend/dist; раздаётся FastAPI на / и /assets.
export default defineConfig({
  plugins: [vue()],
})
