import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import path from "node:path";

// DR-UI-01: Vite is the build tool. The SPA targets `dist/` and is served
// by any static host; in dev it talks to the Validance REST API specified
// by `VITE_VALIDANCE_BASE_URL` (defaults to http://localhost:8001).
export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: {
      "@": path.resolve(__dirname, "src"),
    },
  },
  server: {
    port: 5173,
    strictPort: false,
  },
});
