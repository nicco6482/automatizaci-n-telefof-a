import { resolve } from "node:path";
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// En desarrollo (`npm run dev`) el panel llama a la API en :8000. En producción la sirve la propia API.
// Rutas relativas (base "./") para que el anuncio funcione también como página estática.
export default defineConfig({
  base: "./",
  plugins: [react()],
  server: { port: 5173, proxy: { "/api": "http://localhost:8000" } },
  build: { rollupOptions: { input: { main: resolve(__dirname, "index.html"), anuncio: resolve(__dirname, "anuncio.html") } } },
});
