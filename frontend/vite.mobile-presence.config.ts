import { defineConfig } from "vite"
import react from "@vitejs/plugin-react"
import { cpSync } from "node:fs"

export default defineConfig({
  base: "./",
  plugins: [react(), { name: "bundle-original-humanoid", closeBundle() {
    cpSync("public/presence/jarvis-original", "../android/app/build/generated/mobile-presence/presence/presence/jarvis-original", { recursive: true })
  } }],
  publicDir: false,
  build: {
    outDir: "../android/app/build/generated/mobile-presence/presence",
    emptyOutDir: true,
    rollupOptions: { input: "mobile-presence.html" },
  },
})
