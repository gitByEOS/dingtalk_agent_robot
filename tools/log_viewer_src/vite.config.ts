/**
 * Vite+ 日志查看器配置
 *
 * vp 链路:
 *   vp dev          - 启动开发服务器
 *   vp check        - 格式化 + lint + 类型检查 (vp check --fix 自动修复)
 *   vp build        - 生产构建，产出 dist/（纯静态文件，无需后端）
 *   vp preview      - 预览生产构建
 *
 * 构建产出:
 *   dist/index.html         - 开发服务器用（分离 CSS/JS）
 *   dist/log-viewer.html    - 单文件应用，双击即可打开
 */
import { defineConfig } from "vite-plus";
import { readdirSync, readFileSync, writeFileSync, existsSync } from "node:fs";
import { resolve, dirname } from "node:path";
import { fileURLToPath } from "node:url";

const __dirname = dirname(fileURLToPath(import.meta.url));

export default defineConfig({
  fmt: {},
  lint: { options: { typeAware: true, typeCheck: true } },
  server: {
    port: 5174,
  },
  plugins: [
    {
      name: "single-file",
      // 构建完成后从磁盘读取产物，内联为单文件应用
      closeBundle() {
        const outDir = resolve(__dirname, "dist");
        const assetsDir = resolve(outDir, "assets");

        // 收集所有 CSS 和 JS 文件名
        const cssFiles = existsSync(assetsDir)
          ? readdirSync(assetsDir).filter((f) => f.endsWith(".css"))
          : [];
        const jsFiles = existsSync(assetsDir)
          ? readdirSync(assetsDir).filter((f) => f.endsWith(".js"))
          : [];

        // 找 HTML 文件
        let htmlFile = "";
        for (const f of readdirSync(outDir)) {
          if (f.endsWith(".html")) {
            htmlFile = f;
            break;
          }
        }
        if (!htmlFile) return;

        let html = readFileSync(resolve(outDir, htmlFile), "utf-8");

        // 内联 CSS（路径为 /assets/filename.css）
        for (const f of cssFiles) {
          const css = readFileSync(resolve(assetsDir, f), "utf-8");
          html = html.replace(
            new RegExp(
              `<link[^>]*href="/assets/${f.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")}"[^>]*/?>`,
            ),
            `<style>${css}</style>`,
          );
        }

        // 内联 JS（路径为 /assets/filename.js），保留 type="module" 确保 DOM 就绪后执行
        for (const f of jsFiles) {
          const js = readFileSync(resolve(assetsDir, f), "utf-8");
          html = html.replace(
            new RegExp(
              `<script[^>]*type="module"[^>]*src="/assets/${f.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")}"[^>]*></script>`,
            ),
            `<script type="module">${js}</script>`,
          );
        }

        writeFileSync(resolve(outDir, "log-viewer.html"), html);
      },
    },
  ],
});
