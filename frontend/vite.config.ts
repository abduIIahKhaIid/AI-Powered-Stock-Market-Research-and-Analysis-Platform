import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// In Docker the API is reachable as http://api:8000; locally it runs on localhost:8000.
const apiTarget = process.env.VITE_API_PROXY_TARGET ?? "http://localhost:8000";
// Docker Desktop on Windows does not pass file-change events into bind mounts, so in Docker the
// dev server polls for changes (VITE_USE_POLLING=true); otherwise it would keep serving old code.
const usePolling = process.env.VITE_USE_POLLING === "true";

export default defineConfig({
  plugins: [react()],
  server: {
    host: true,
    port: 5173,
    watch: usePolling ? { usePolling: true, interval: 500 } : undefined,
    proxy: {
      "/api": {
        target: apiTarget,
        changeOrigin: true,
        rewrite: (path) => path.replace(/^\/api/, ""),
      },
    },
  },
});
