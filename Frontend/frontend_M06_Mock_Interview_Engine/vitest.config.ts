import { defineConfig } from "vitest/config";
import react from "@vitejs/plugin-react";

/**
 * The page tests (2026-10-24): `npm test`. A browser-shaped DOM (jsdom), and
 * no Tailwind — a test reads what the page says and which classes it chose,
 * not how they paint.
 */
export default defineConfig({
  plugins: [react()],
  test: {
    environment: "jsdom",
    include: ["src/**/*.test.{ts,tsx}"],
    // @ai/core ships TypeScript source, so it is transformed, not required.
    server: { deps: { inline: ["@ai/core"] } },
  },
});
