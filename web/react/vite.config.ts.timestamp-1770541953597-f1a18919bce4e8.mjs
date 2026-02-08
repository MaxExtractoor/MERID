// vite.config.ts
import { defineConfig } from "file:///C:/Dev/MERID/web/react/node_modules/vite/dist/node/index.js";
import react from "file:///C:/Dev/MERID/web/react/node_modules/@vitejs/plugin-react/dist/index.mjs";
import path from "path";
var __vite_injected_original_dirname = "C:\\Dev\\MERID\\web\\react";
var vite_config_default = defineConfig({
  plugins: [react()],
  resolve: {
    alias: {
      "@": path.resolve(__vite_injected_original_dirname, "./src")
    }
  },
  server: {
    port: 5173,
    strictPort: true,
    // Fail if port is already in use instead of incrementing
    host: true,
    proxy: {
      "/api/v1/consensus/ws": {
        target: "ws://127.0.0.1:8011",
        ws: true,
        changeOrigin: true
      },
      "/api": {
        target: "http://127.0.0.1:8011",
        changeOrigin: true,
        secure: false,
        ws: true
      },
      "/ws": {
        target: "ws://127.0.0.1:8011",
        ws: true,
        changeOrigin: true
      }
    }
  }
});
export {
  vite_config_default as default
};
//# sourceMappingURL=data:application/json;base64,ewogICJ2ZXJzaW9uIjogMywKICAic291cmNlcyI6IFsidml0ZS5jb25maWcudHMiXSwKICAic291cmNlc0NvbnRlbnQiOiBbImNvbnN0IF9fdml0ZV9pbmplY3RlZF9vcmlnaW5hbF9kaXJuYW1lID0gXCJDOlxcXFxEZXZcXFxcTUVSSURcXFxcd2ViXFxcXHJlYWN0XCI7Y29uc3QgX192aXRlX2luamVjdGVkX29yaWdpbmFsX2ZpbGVuYW1lID0gXCJDOlxcXFxEZXZcXFxcTUVSSURcXFxcd2ViXFxcXHJlYWN0XFxcXHZpdGUuY29uZmlnLnRzXCI7Y29uc3QgX192aXRlX2luamVjdGVkX29yaWdpbmFsX2ltcG9ydF9tZXRhX3VybCA9IFwiZmlsZTovLy9DOi9EZXYvTUVSSUQvd2ViL3JlYWN0L3ZpdGUuY29uZmlnLnRzXCI7aW1wb3J0IHsgZGVmaW5lQ29uZmlnIH0gZnJvbSAndml0ZSdcclxuaW1wb3J0IHJlYWN0IGZyb20gJ0B2aXRlanMvcGx1Z2luLXJlYWN0J1xyXG5pbXBvcnQgcGF0aCBmcm9tICdwYXRoJ1xyXG5cclxuZXhwb3J0IGRlZmF1bHQgZGVmaW5lQ29uZmlnKHtcclxuICBwbHVnaW5zOiBbcmVhY3QoKV0sXHJcbiAgcmVzb2x2ZToge1xyXG4gICAgYWxpYXM6IHtcclxuICAgICAgJ0AnOiBwYXRoLnJlc29sdmUoX19kaXJuYW1lLCAnLi9zcmMnKSxcclxuICAgIH0sXHJcbiAgfSxcclxuICBzZXJ2ZXI6IHtcclxuICAgIHBvcnQ6IDUxNzMsXHJcbiAgICBzdHJpY3RQb3J0OiB0cnVlLCAgLy8gRmFpbCBpZiBwb3J0IGlzIGFscmVhZHkgaW4gdXNlIGluc3RlYWQgb2YgaW5jcmVtZW50aW5nXHJcbiAgICBob3N0OiB0cnVlLFxyXG4gICAgcHJveHk6IHtcclxuICAgICAgJy9hcGkvdjEvY29uc2Vuc3VzL3dzJzoge1xyXG4gICAgICAgIHRhcmdldDogJ3dzOi8vMTI3LjAuMC4xOjgwMTEnLFxyXG4gICAgICAgIHdzOiB0cnVlLFxyXG4gICAgICAgIGNoYW5nZU9yaWdpbjogdHJ1ZSxcclxuICAgICAgfSxcclxuICAgICAgJy9hcGknOiB7XHJcbiAgICAgICAgdGFyZ2V0OiAnaHR0cDovLzEyNy4wLjAuMTo4MDExJyxcclxuICAgICAgICBjaGFuZ2VPcmlnaW46IHRydWUsXHJcbiAgICAgICAgc2VjdXJlOiBmYWxzZSxcclxuICAgICAgICB3czogdHJ1ZSxcclxuICAgICAgfSxcclxuICAgICAgJy93cyc6IHtcclxuICAgICAgICB0YXJnZXQ6ICd3czovLzEyNy4wLjAuMTo4MDExJyxcclxuICAgICAgICB3czogdHJ1ZSxcclxuICAgICAgICBjaGFuZ2VPcmlnaW46IHRydWUsXHJcbiAgICAgIH0sXHJcbiAgICB9LFxyXG4gIH0sXHJcbn0pXHJcbiJdLAogICJtYXBwaW5ncyI6ICI7QUFBOFAsU0FBUyxvQkFBb0I7QUFDM1IsT0FBTyxXQUFXO0FBQ2xCLE9BQU8sVUFBVTtBQUZqQixJQUFNLG1DQUFtQztBQUl6QyxJQUFPLHNCQUFRLGFBQWE7QUFBQSxFQUMxQixTQUFTLENBQUMsTUFBTSxDQUFDO0FBQUEsRUFDakIsU0FBUztBQUFBLElBQ1AsT0FBTztBQUFBLE1BQ0wsS0FBSyxLQUFLLFFBQVEsa0NBQVcsT0FBTztBQUFBLElBQ3RDO0FBQUEsRUFDRjtBQUFBLEVBQ0EsUUFBUTtBQUFBLElBQ04sTUFBTTtBQUFBLElBQ04sWUFBWTtBQUFBO0FBQUEsSUFDWixNQUFNO0FBQUEsSUFDTixPQUFPO0FBQUEsTUFDTCx3QkFBd0I7QUFBQSxRQUN0QixRQUFRO0FBQUEsUUFDUixJQUFJO0FBQUEsUUFDSixjQUFjO0FBQUEsTUFDaEI7QUFBQSxNQUNBLFFBQVE7QUFBQSxRQUNOLFFBQVE7QUFBQSxRQUNSLGNBQWM7QUFBQSxRQUNkLFFBQVE7QUFBQSxRQUNSLElBQUk7QUFBQSxNQUNOO0FBQUEsTUFDQSxPQUFPO0FBQUEsUUFDTCxRQUFRO0FBQUEsUUFDUixJQUFJO0FBQUEsUUFDSixjQUFjO0FBQUEsTUFDaEI7QUFBQSxJQUNGO0FBQUEsRUFDRjtBQUNGLENBQUM7IiwKICAibmFtZXMiOiBbXQp9Cg==
