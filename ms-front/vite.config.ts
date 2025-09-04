// vite.config.ts
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react-swc";
import path from "path";
import { componentTagger } from "lovable-tagger";

const LAN = "192.168.1.128"; // tu IP LAN

export default defineConfig(({ mode }) => ({
  server: {
    host: true,        // <-- escucha en todas (0.0.0.0)
    port: 8080,
    hmr: {
      host: LAN,       // cliente HMR apunta a tu IP
      protocol: "ws",
      port: 8080,
    },
    proxy: {
      "/api":    { target: `http://${LAN}:8000`, changeOrigin: true },
      "/health": { target: `http://${LAN}:8000`, changeOrigin: true },
      "/events": { target: `http://${LAN}:8000`, changeOrigin: true },
    },
  },
  plugins: [react(), mode === "development" && componentTagger()].filter(Boolean),
  resolve: { alias: { "@": path.resolve(__dirname, "./src") } },
}));
