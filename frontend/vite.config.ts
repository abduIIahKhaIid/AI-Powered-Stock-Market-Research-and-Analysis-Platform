import tailwindcss from "@tailwindcss/vite";
import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

// In Docker the API is reachable as http://api:8000; locally it runs on localhost:8000.
const apiTarget = process.env.VITE_API_PROXY_TARGET ?? "http://localhost:8000";
// Docker Desktop on Windows does not pass file-change events into bind mounts, so in Docker the
// dev server polls for changes (VITE_USE_POLLING=true); otherwise it would keep serving old code.
const usePolling = process.env.VITE_USE_POLLING === "true";
// Hostnames the dev server answers besides localhost (Vite blocks others against DNS
// rebinding). Cloudflare Quick Tunnel URLs are allowed so the app can be shared for a while;
// add more, comma-separated, in VITE_ALLOWED_HOSTS (a leading dot allows all subdomains).
const allowedHosts = [
  ".trycloudflare.com",
  ...(process.env.VITE_ALLOWED_HOSTS ?? "")
    .split(",")
    .map((host) => host.trim())
    .filter(Boolean),
];

export default defineConfig({
  plugins: [react(), tailwindcss()],
  build: {
    rolldownOptions: {
      output: {
        // React and the UI kit change rarely: keep them in their own cacheable chunk.
        codeSplitting: {
          groups: [
            {
              name: "vendor",
              test: /node_modules[\\/](react|react-dom|scheduler|radix-ui|@radix-ui|@floating-ui|lucide-react|tailwind-merge|clsx)[\\/]/,
            },
          ],
        },
      },
    },
  },
  server: {
    host: true,
    port: 5173,
    allowedHosts,
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
