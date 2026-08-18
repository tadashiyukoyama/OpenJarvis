import path from 'path';
import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';
import tailwindcss from '@tailwindcss/vite';
import { VitePWA } from 'vite-plugin-pwa';

// VITE_SUPABASE_ANON_KEY is intentionally NOT required here: a missing key
// disables the savings leaderboard at runtime (see src/lib/supabase.ts) rather
// than failing the build, so the package/app stays publishable without it.
export default defineConfig({
  resolve: {
    alias: {
      '@': path.resolve(__dirname, './src'),
    },
  },
  plugins: [
    react(),
    tailwindcss(),
    VitePWA({
      // Never replace the active page while the user is typing or authenticating.
      // A new bundle becomes active on the next deliberate navigation/reload.
      registerType: 'prompt',
      useCredentials: true,
      manifest: {
        name: 'OpenJarvis',
        short_name: 'Jarvis',
        description: 'On-device AI assistant',
        theme_color: '#161618',
        background_color: '#161618',
        display: 'standalone',
        start_url: '/jarvis',
        scope: '/',
        icons: [
          { src: 'pwa-192x192.png', sizes: '192x192', type: 'image/png' },
          { src: 'pwa-512x512.png', sizes: '512x512', type: 'image/png' },
        ],
      },
      workbox: {
        // Keep a newly built worker waiting until the next deliberate reload.
        // This prevents a service-worker update from interrupting login or text input.
        skipWaiting: false,
        clientsClaim: false,
        globPatterns: ['**/*.{js,css,html,ico,png,svg}'],
        navigateFallbackDenylist: [/^\/v1\//, /^\/health/, /^\/dashboard/, /^\/api\//],
      },
    }),
  ],
  build: {
    outDir: '../src/openjarvis/server/static',
    emptyOutDir: true,
    minify: 'esbuild',
    rollupOptions: {
      output: {
        manualChunks: {
          react: ['react', 'react-dom'],
          markdown: ['react-markdown', 'rehype-highlight', 'remark-gfm'],
          charts: ['recharts'],
          router: ['react-router'],
        },
      },
    },
  },
  server: {
    port: 5173,
    proxy: {
      // The audited local launcher serves OpenJarvis on 8127. Keep a matching
      // fallback so `npm run dev` cannot silently proxy to an unrelated port
      // when VITE_API_URL is absent.
      '/v1': process.env.VITE_API_URL || 'http://127.0.0.1:8127',
      '/health': process.env.VITE_API_URL || 'http://127.0.0.1:8127',
      '/api': process.env.VITE_API_URL || 'http://127.0.0.1:8127',
    },
  },
});
