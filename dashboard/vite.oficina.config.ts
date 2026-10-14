import { resolve } from "node:path";
import { defineConfig } from "vite";

// La oficina de muñecos como un único script para la demo web (demo_web/oficina.js → window.TelecoOficina).
export default defineConfig({
  build: {
    outDir: resolve(__dirname, "..", "demo_web"),
    emptyOutDir: false,
    copyPublicDir: false,
    lib: { entry: resolve(__dirname, "src/office/demo.ts"), name: "TelecoOficina", formats: ["iife"], fileName: () => "oficina.js" },
  },
});
