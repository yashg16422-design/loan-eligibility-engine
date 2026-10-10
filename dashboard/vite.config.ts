import tailwindcss from "@tailwindcss/vite";
import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

// Served by the api Lambda under /app (same origin as the JSON API: no CORS).
// `npm run dev` proxies the API to the deployed stage so the UI runs against live data.
const API = process.env.API_TARGET ?? "https://t7lcgp5o0j.execute-api.ap-southeast-2.amazonaws.com";
const apiRoutes = ["/check", "/me", "/products", "/ops", "/uploads", "/analytics", "/account", "/auth"];

export default defineConfig({
  base: "/app/",
  plugins: [react(), tailwindcss()],
  build: {
    outDir: "../loan_engine/api/static",
    emptyOutDir: true,
    assetsInlineLimit: 0,
  },
  server: {
    proxy: Object.fromEntries(apiRoutes.map((r) => [r, { target: API, changeOrigin: true }])),
  },
});
