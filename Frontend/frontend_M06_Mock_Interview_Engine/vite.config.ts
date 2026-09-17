import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";

/**
 * M06 — Mock Interview Engine, on its reserved port 5206 (PORTS.txt).
 *
 * This repo holds one module, so this is the app. Platform_Shell mounts the
 * same `src/routes.tsx` — the components are identical either way, so what
 * you fix here is what students get.
 */
const API_TARGET = process.env.VITE_API_BASE ?? "http://127.0.0.1:8106";

export default defineConfig({
  plugins: [react(), tailwindcss()],
  optimizeDeps: {
    // @ai/core ships TypeScript source rather than a build, so Vite must
    // transform it instead of pre-bundling it as an opaque dependency.
    exclude: ["@ai/core"],
  },
  server: {
    port: 5206,
    proxy: {
      // The live stream goes through here too; http-proxy streams, so the
      // interviewer's tokens are not buffered on the way.
      "/v1": { target: API_TARGET, changeOrigin: true },
      "/health": { target: API_TARGET, changeOrigin: true },
      "/status": { target: API_TARGET, changeOrigin: true },
    },
  },
  preview: { port: 5206 },
});
