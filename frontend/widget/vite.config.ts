/** Separate build for the embeddable widget: an ES-module `widget.js` (the tiny loader) that
 * code-splits the React panel into its own chunk, loaded on first open ([IMP-FE-7]). Run with
 * `npm run build:widget` → emits to `frontend/dist-widget/`. React is bundled (not externalized)
 * so the artifact is self-contained for any tenant page. */

import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

const here = dirname(fileURLToPath(import.meta.url));

export default defineConfig({
  plugins: [react()],
  build: {
    outDir: "dist-widget",
    emptyOutDir: true,
    target: "es2020",
    lib: {
      entry: resolve(here, "loader.ts"),
      formats: ["es"],
      fileName: () => "widget.js",
    },
    rollupOptions: {
      output: { chunkFileNames: "widget-[name]-[hash].js" },
    },
  },
});
