import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// EPIPE / ECONNRESET hit the proxy whenever uvicorn --reload bounces the
// backend mid-WS-frame. The frontend reconnects on its own; just don't spam
// stderr. Anything else still surfaces.
const RELOAD_NOISE = new Set(["EPIPE", "ECONNRESET", "ECONNREFUSED"]);

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      "/api": {
        target: "http://localhost:8000",
        configure: (proxy) => {
          proxy.on("error", (err) => {
            const code = (err as NodeJS.ErrnoException).code;
            if (!code || !RELOAD_NOISE.has(code)) console.error("[api proxy]", err);
          });
        },
      },
      "/ws": {
        target: "ws://localhost:8000",
        ws: true,
        configure: (proxy) => {
          proxy.on("error", (err) => {
            const code = (err as NodeJS.ErrnoException).code;
            if (!code || !RELOAD_NOISE.has(code)) console.error("[ws proxy]", err);
          });
        },
      },
    },
  },
  build: {
    outDir: "dist",
    emptyOutDir: true,
  },
});
