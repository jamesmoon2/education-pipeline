import { defineConfig } from "vitest/config";
import react from "@vitejs/plugin-react";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";

function devProxy() {
  try {
    const workspace = process.env.EP_WORKSPACE ?? resolve(__dirname, "..");
    const file = resolve(workspace, ".education-pipeline/daemon.json");
    const record = JSON.parse(readFileSync(file, "utf-8")) as { port: number };
    return { "/v1": { target: `http://127.0.0.1:${record.port}` } };
  } catch {
    // No daemon running; dev server still starts, API calls will fail.
    return undefined;
  }
}

export default defineConfig({
  plugins: [react()],
  server: { proxy: devProxy() },
  test: {
    environment: "jsdom",
    globals: true,
    setupFiles: "./src/test/setup.ts",
    include: ["src/**/*.test.{ts,tsx}"],
  },
});
