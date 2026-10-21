import { defineConfig } from 'vite';
import vue from '@vitejs/plugin-vue';

// 构建产物直接输出到 Flask 静态目录，manifest 供 Flask 模板引用哈希文件名。
export default defineConfig({
  plugins: [vue()],
  base: '/static/dist/',
  build: {
    outDir: '../app/static/dist',
    emptyOutDir: true,
    manifest: true,
    assetsDir: 'assets',
    // 首屏解析耗时优化：生产包不产出 sourcemap，
    // 目标语法对齐主流浏览器，减少运行时的语法降级开销
    sourcemap: false,
    target: 'es2019',
    reportCompressedSize: false,
    rollupOptions: {
      input: 'src/main.js'
    }
  },
  define: {
    __VUE_OPTIONS_API__: true,
    __VUE_PROD_DEVTOOLS__: false,
    __VUE_PROD_HYDRATION_MISMATCH_DETAILS__: false
  },
  server: {
    port: 5173,
    strictPort: true,
    cors: true
  }
});
