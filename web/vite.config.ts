/// <reference types="vitest/config" />
import { defineConfig, type Plugin } from "vite";

// Where the app lives (dashboard/, served by the api Lambda at /app/). Every "Check my
// eligibility" and "See the engine" link in index.html is written as %APP_URL%.
// Override at build time when the landing is hosted on a different origin than the app:
//   VITE_APP_URL=https://<api-host>/app/ npm run build
const APP_URL = process.env.VITE_APP_URL ?? "/app/";

function appUrl(): Plugin {
  return {
    name: "clickpar-app-url",
    transformIndexHtml: (html) => html.replaceAll("%APP_URL%", APP_URL),
  };
}

export default defineConfig({
  base: "/",
  plugins: [appUrl()],
  build: {
    outDir: "dist",
    emptyOutDir: true,
    // three.js is split into its own lazy chunk (the globe), so the first load stays small
    chunkSizeWarningLimit: 700,
  },
  test: {
    environment: "node",
    include: ["src/**/*.test.ts"],
  },
});
