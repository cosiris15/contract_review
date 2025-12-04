import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'
import path from 'path'
import AutoImport from 'unplugin-auto-import/vite'
import Components from 'unplugin-vue-components/vite'
import { ElementPlusResolver } from 'unplugin-vue-components/resolvers'

export default defineConfig({
  plugins: [
    vue(),
    AutoImport({
      resolvers: [ElementPlusResolver()],
    }),
    Components({
      resolvers: [ElementPlusResolver()],
    }),
  ],
  resolve: {
    alias: {
      '@': path.resolve(__dirname, 'src')
    }
  },
  server: {
    port: 3000,
    proxy: {
      '/api': {
        target: 'http://localhost:8000',
        changeOrigin: true
      }
    }
  },
  build: {
    outDir: 'dist',
    assetsDir: 'assets',
    rollupOptions: {
      output: {
        manualChunks(id) {
          // Clerk 单独打包
          if (id.includes('@clerk')) {
            return 'clerk'
          }
          // Element Plus 和 Vue 放在一起避免循环依赖
          if (id.includes('element-plus') || id.includes('@vue') || id.includes('vue')) {
            return 'ui-vendor'
          }
          // 其他 node_modules
          if (id.includes('node_modules')) {
            return 'vendor'
          }
        }
      }
    }
  }
})
