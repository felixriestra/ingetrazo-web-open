import {defineConfig} from "vite";

export default defineConfig({
  build: {
    // Three.js changes far less often than the application. Keeping it in a
    // stable chunk lets browsers reuse the rendering runtime across ordinary
    // viewer releases instead of downloading the entire client again.
    rollupOptions: {
      output: {
        manualChunks(id) {
          if (id.includes("/node_modules/three/")) return "three";
          return undefined;
        },
      },
    },
    // Three plus GLTFLoader is intentionally one cached runtime chunk. Its
    // gzip payload is ~155 KiB; the default warning is based on uncompressed
    // source size and is not representative of network transfer here.
    chunkSizeWarningLimit: 650,
  },
});
