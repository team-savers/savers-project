import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import { VitePWA } from 'vite-plugin-pwa'
import { execSync } from 'node:child_process'

// Build stamp injected as a `define` global so it is inlined at build time.
// Used as a tiny on-screen marker (demo/ops only) to verify which build is
// currently live on a device. This is NOT a secret — it is a UTC build
// timestamp plus the short git sha, intended to be human-visible. Keeping it
// in `define` means it is statically replaced and costs nothing at runtime.
const buildStamp = (() => {
  const now = new Date().toISOString().replace(/\.\d+Z$/, 'Z')
  let sha = 'dev'
  try {
    sha = execSync('git rev-parse --short HEAD').toString().trim()
  } catch {
    sha = 'nogit'
  }
  return `${now}-${sha}`
})()

// Port 3000 is fixed: Kakao Maps JS SDK allows http://localhost:3000 only.
// strictPort prevents Vite from silently falling back to 3001+ (which would
// break Kakao Maps rendering in dev) when 3000 is busy.
export default defineConfig({
  define: {
    __BUILD_STAMP__: JSON.stringify(buildStamp),
  },
  plugins: [
    react(),
    VitePWA({
      strategies: 'injectManifest',
      srcDir: 'src',
      filename: 'sw.ts',
      injectRegister: 'auto',
      registerType: 'autoUpdate',
      devOptions: {
        enabled: true,
        type: 'module',
      },
      manifest: {
        name: '세이버스',
        short_name: '세이버스',
        start_url: '/',
        display: 'standalone',
        background_color: '#ffffff',
        theme_color: '#ffffff',
        icons: [
          {
            src: '/favicon.svg',
            sizes: 'any',
            type: 'image/svg+xml',
          },
        ],
      },
    }),
  ],
  server: {
    port: 3000,
    strictPort: true,
  },
})
