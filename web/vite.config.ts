import react from '@vitejs/plugin-react-swc'
import { defineConfig } from 'vite'
import { viteStaticCopy } from 'vite-plugin-static-copy'

// https://vite.dev/config/
export default defineConfig({
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
