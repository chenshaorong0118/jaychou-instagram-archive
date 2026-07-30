import { defineConfig } from "vite";

export default defineConfig({
  root: "site",
  base: "/jaychou-instagram-archive/",
  publicDir: false,
  build: {
    outDir: "../dist",
    emptyOutDir: true,
    sourcemap: true,
  },
});
