import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import path from 'path'

export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: {
      '@': path.resolve(__dirname, './src'),
    },
  },
  server: {
    port: 5173,
    strictPort: true,  // Fail if port is already in use instead of incrementing
    host: true,
    proxy: {
      '/api/v1/consensus/ws': {
        target: 'ws://127.0.0.1:8011',
        ws: true,
        changeOrigin: true,
      },
      '/api': {
        target: 'http://127.0.0.1:8011',
        changeOrigin: true,
        secure: false,
        ws: true,
      },
      '/ws': {
        target: 'ws://127.0.0.1:8011',
        ws: true,
        changeOrigin: true,
      },
    },
  },
})
