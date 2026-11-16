import { defineConfig } from 'vitest/config'
import { loadEnv } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, '.', '')
  const proxyTarget = env.VITE_API_PROXY_TARGET
  return {
    plugins: [react()],
    server: {
      host: '127.0.0.1',
      port: 4173,
      proxy: proxyTarget ? { '/api': { target: proxyTarget, changeOrigin: true } } : undefined,
    },
    test: {
      environment: 'jsdom',
      setupFiles: './src/test/setup.ts',
      css: true,
    },
  }
})
