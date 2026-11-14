import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  // Share the repo-root .env with the backend. Only VITE_* variables reach the browser.
  envDir: '..',
  // The registry and the heart model live in the repo-root assets/ folder, outside frontend/.
  server: { port: 5173, strictPort: true, fs: { allow: ['..'] } },
})
