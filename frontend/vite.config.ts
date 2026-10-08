import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  build: { outDir: "../src/rebound/static", emptyOutDir: true },
  server: {
    host: "127.0.0.1",
    port: 5173,
    strictPort: true,
    proxy: {
      "/docs": {
        target: "http://127.0.0.1:8787",
        changeOrigin: true,
      },
      "/openapi.json": {
        target: "http://127.0.0.1:8787",
        changeOrigin: true,
      },
      "/api": {
        target: "http://127.0.0.1:8787",
        changeOrigin: true,
        configure(proxy) {
          // Only the explicitly bound local development UI may write through
          // this proxy. Production keeps its strict same-origin boundary.
          proxy.on("proxyReq", (proxyReq, incoming) => {
            if (
              ["http://127.0.0.1:5173", "http://localhost:5173"].includes(
                incoming.headers.origin ?? "",
              )
            ) {
              proxyReq.setHeader("Origin", "http://127.0.0.1:8787");
            }
          });
        },
      },
    },
  },
});
