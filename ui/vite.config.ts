import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// `npm run dev` serves the UI on 5173 and proxies the API to the uvicorn app,
// so the browser sees one origin and the app's fetch paths stay relative.
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      "/api": {
        target: process.env.FICTIVE_API ?? "http://127.0.0.1:8000",
        changeOrigin: true,
      },
    },
  },
});
