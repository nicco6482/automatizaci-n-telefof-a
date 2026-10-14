import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// En desarrollo (`npm run dev`) el panel llama a la API en :8000. En producción la sirve la propia API.
export default defineConfig({
  plugins: [react()],
  server: { port: 5173, proxy: { "/api": "http://localhost:8000" } },
});
