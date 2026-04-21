import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      "/chat": {
        target: "http://localhost:8080",
        configure: (proxy) => {
          proxy.on("proxyReq", (_proxyReq, req) => {
            req.setTimeout(0);
          });
          proxy.on("proxyRes", (proxyRes) => {
            if (proxyRes.headers["content-type"]?.includes("text/event-stream")) {
              proxyRes.headers["x-accel-buffering"] = "no";
              proxyRes.headers["cache-control"] = "no-cache";
            }
          });
        },
      },
      "/health": "http://localhost:8080",
    },
  },
});
