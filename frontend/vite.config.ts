import { defineConfig } from 'vitest/config'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'
import { existsSync, readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { parseEnv } from 'node:util'

// Read only on the Vite server; never expose this file through import.meta.env.
const envPath = fileURLToPath(new URL('../.env', import.meta.url))
const fileEnv = existsSync(envPath) ? parseEnv(readFileSync(envPath, 'utf8')) : {}
const setting = (name: string, fallback: string) =>
  process.env[`CORNAGENT_${name}`] || fileEnv[`CORNAGENT_${name}`] || fallback
const port = (name: string, fallback: string) => {
  const value = Number(setting(name, fallback))
  if (!Number.isInteger(value) || value < 1 || value > 65535) throw new Error(`Invalid ${name}`)
  return value
}
const serverHost = setting('SERVER_HOST', '127.0.0.1')
const proxyHost = ['0.0.0.0', '::'].includes(serverHost) ? '127.0.0.1' : serverHost
const proxyTarget = `http://${proxyHost.includes(':') ? `[${proxyHost}]` : proxyHost}:${port('SERVER_PORT', '8000')}`
const frontendHost = setting('FRONTEND_HOST', '127.0.0.1')
const frontendPort = port('FRONTEND_PORT', '5173')

export default defineConfig({
  envDir: false,
  plugins: [react(), tailwindcss()],
  server: {
    host: frontendHost, port: frontendPort, strictPort: true,
    proxy: { '/api': { target: proxyTarget, changeOrigin: false } },
  },
  preview: { host: frontendHost, port: frontendPort, strictPort: true },
  build: { cssCodeSplit: false },
  test: {
    globals: true, maxWorkers: 3, testTimeout: 30000, hookTimeout: 30000,
    projects: [
      { extends: true, test: { name: 'unit', environment: 'node', include: ['src/**/*.unit.test.ts'], setupFiles: './tests/setup/unit-browser-state.ts' } },
      { extends: true, test: { name: 'component', environment: 'jsdom', include: ['src/**/*.component.test.tsx'], setupFiles: './tests/setup/dom.ts', css: true } },
    ],
  },
})
