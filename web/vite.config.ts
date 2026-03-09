import react from '@vitejs/plugin-react-swc'
import { defineConfig } from 'vite'
import { viteStaticCopy } from 'vite-plugin-static-copy'

// https://vite.dev/config/
export default defineConfig({
  resolve: {
    alias: {
      '@douyinfe/semi-ui/dist/css/semi.min.css': new URL('./node_modules/@douyinfe/semi-ui/dist/css/semi.min.css', import.meta.url).pathname
    }
  },
  plugins: [
    react(),
    viteStaticCopy({
      targets: [
        { src: 'node_modules/prismjs/components', dest: '.' }
      ],
      watch: { reloadPageOnChange: true }
    })
  ]
})
