import react from "@vitejs/plugin-react";
import { defineConfig, loadEnv } from "vite";

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), "");
  const apiBaseUrl = env.VITE_STORYFORGE_API_BASE_URL || "http://127.0.0.1:8000";

  return {
    plugins: [react()],
    server: {
      host: "127.0.0.1",
      port: 5173,
      proxy: {
        "/v1": apiBaseUrl,
        "/health": apiBaseUrl,
        "/outputs": apiBaseUrl
      }
    },
    preview: {
      host: "127.0.0.1",
      port: 4173
    }
  };
});
