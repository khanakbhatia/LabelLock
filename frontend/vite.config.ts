import { defineConfig } from 'vitest/config';
import react from '@vitejs/plugin-react';
import { resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
const frontendDir = fileURLToPath(new URL('.', import.meta.url));

export default defineConfig(({ mode }) => ({
  base: mode === 'panel' ? './' : '/',
  plugins: [react()],
  build: mode === 'panel' ? { outDir: resolve(frontendDir, '../extension/panel'), emptyOutDir: true, rollupOptions: { input: resolve(frontendDir, 'panel.html') } } : undefined,
  test: { environment: 'jsdom', setupFiles: ['./src/test/setup.ts'], css: true },
}));
