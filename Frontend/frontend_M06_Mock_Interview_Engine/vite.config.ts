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
/** M11, the voice engine (PORTS.txt 8111): the panel's voices, faces and
 *  hearing. Core's voice client asks for /v1/voice/... on this origin, and
 *  "/v1" alone sent it to M06, which has no such route: standalone, every
 *  line fell back to the browser's voice without a word (2026-10-28). */
const VOICE_TARGET = process.env.VITE_VOICE_BASE ?? "http://127.0.0.1:8111";

export default defineConfig({
  plugins: [react(), tailwindcss()],
  optimizeDeps: {
    // @ai/core ships TypeScript source rather than a build, so Vite must
    // transform it instead of pre-bundling it as an opaque dependency.
    exclude: ["@ai/core"],
    // The panel's 3D heads (Core's TalkingHead) load this renderer, which
    // imports jszip — CommonJS, so it works only pre-bundled. With @ai/core
    // excluded nothing tells Vite the renderer is used: it was served raw,
    // the import failed and every head fell back to its photograph (M20 found
    // it live, 2026-10-28; the platform shell finds it at run time instead).
    include: ["@myned-ai/gsplat-flame-avatar-renderer"],
  },
  server: {
    port: 5206,
    proxy: {
      // The live stream goes through here too; http-proxy streams, so the
      // interviewer's tokens are not buffered on the way.
      // First: the first key that matches wins, and "/v1" would take it.
      "/v1/voice": { target: VOICE_TARGET, changeOrigin: true },
      "/v1": { target: API_TARGET, changeOrigin: true },
      "/health": { target: API_TARGET, changeOrigin: true },
      "/status": { target: API_TARGET, changeOrigin: true },
    },
  },
  preview: { port: 5206 },
});
