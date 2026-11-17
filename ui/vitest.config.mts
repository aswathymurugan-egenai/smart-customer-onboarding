import { fileURLToPath } from "node:url";

import { defineConfig } from "vitest/config";

export default defineConfig({
  // Next.js needs `jsx: preserve` in tsconfig, so tests ask the transformer for the automatic runtime.
  oxc: { jsx: { runtime: "automatic" } },
  resolve: {
    alias: { "@": fileURLToPath(new URL("./", import.meta.url)) },
  },
  test: {
    environment: "jsdom",
    setupFiles: ["./vitest.setup.ts"],
    include: ["features/**/*.test.{ts,tsx}", "tests/unit/**/*.test.{ts,tsx}"],
    sequence: { shuffle: true },
    css: false,
    pool: "threads",
    testTimeout: 20000,
    hookTimeout: 30000,
  },
});
