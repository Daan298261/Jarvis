import { defineConfig } from "vite"
import react from "@vitejs/plugin-react"
export default defineConfig({
  root: "mobile-orb", base: "./", plugins: [react()],
  build: { outDir: "../../android/app/src/main/assets/orb", emptyOutDir: true },
})
