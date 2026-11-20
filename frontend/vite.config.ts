import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// Dev: the Flask API runs on :5000 (make dev-api) and Vite proxies /api to it.
// Production: Vercel serves dist/ and rewrites /api/* to the Python function.
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: { "/api": { target: process.env.GK_API ?? "http://127.0.0.1:5000", changeOrigin: false } },
  },
  build: {
    target: "es2021",
    sourcemap: false,
    cssCodeSplit: true,
    chunkSizeWarningLimit: 400,
    rollupOptions: {
      output: {
        manualChunks: {
          react: ["react", "react-dom", "react-router-dom"],
          query: ["@tanstack/react-query"],
        },
      },
    },
  },
  test: { environment: "jsdom", include: ["src/**/*.test.{ts,tsx}"] },
} as never);
