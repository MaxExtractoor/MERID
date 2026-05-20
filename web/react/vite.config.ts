import { defineConfig, loadEnv } from 'vite'
import react from '@vitejs/plugin-react'
import path from 'path'

export default defineConfig(({ mode }) => {
  const rootDir = path.resolve(__dirname, '../..')
  const env = loadEnv(mode, rootDir, '')
  const backendHost = env.MERID_BACKEND_HOST || '127.0.0.1'
  const backendPort = env.MERID_BACKEND_PORT || '8011'
  const backendHttp = `http://${backendHost}:${backendPort}`
  const backendWs = `ws://${backendHost}:${backendPort}`

  return {
    plugins: [react()],
    build: {
      target: 'esnext',
    },
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
        '/api': {
          target: backendHttp,
          changeOrigin: true,
          secure: false,
          ws: true,
        },
        '/ws': {
          target: backendWs,
          ws: true,
          changeOrigin: true,
        },
      },
    },
  }
})
