import { defineConfig } from 'vitest/config'
import vue from '@vitejs/plugin-vue'
import { fileURLToPath } from 'url'

export default defineConfig({
  plugins: [vue()],
  test: {
    environment: 'jsdom',
    globals: true,
    include: ['frontend/tests/**/*.{test,spec}.ts'],
    reporters: ['verbose', ['html', { outputFile: 'tests/reports/vitest/index.html' }]],
  },
  resolve: {
    alias: {
      '@': fileURLToPath(new URL('./frontend/src', import.meta.url)),
    },
  },
})
