# Vite+ 日志查看器

纯浏览器端日志查看工具，双击 HTML 即可打开使用。

## 目标

用 Vite+（vite-plus）为 Python 项目的交互日志搭建一个 TypeScript Web 查看界面。

## 操作步骤

### 1. 安装 vp 工具链

```bash
curl -fsSL https://vite.plus | bash
```

### 2. 创建 Vite+ 项目

```bash
vp create vite log-viewer -- --template vanilla-ts
```

### vp 完整链路总结

| 命令              | 作用                       | 耗时   |
| ----------------- | -------------------------- | ------ |
| `vp install`      | 安装依赖                   | 2.5s   |
| `vp dev`          | 启动开发服务器（含中间件） | -      |
| `vp test run`     | 运行测试                   | 71ms   |
| `vp test watch`   | 监听模式                   | -      |
| `vp check`        | 格式化 + lint + 类型检查   | ~300ms |
| `vp check --fix`  | 自动修复格式问题           | -      |
| `vp build`        | 生产构建                   | 206ms  |
| `vp preview`      | 预览构建产物               | -      |
| `vp add <pkg>`    | 添加依赖                   | -      |
| `vp add -D <pkg>` | 添加开发依赖               | -      |

## 项目结构

```
src/
├── main.ts      # 入口
├── app.ts       # 文件选择、用户列表、日志渲染
├── filePicker.ts # webkitdirectory 读取本地文件
├── types.ts     # TypeScript 类型定义
└── style.css    # 样式
```

## 命令

```bash
vp dev      # 开发服务器
vp build    # 构建，产出 dist/log-viewer.html（单文件）
vp check    # 格式化 + lint + 类型检查
```

## 数据格式

日志目录结构：

```
logs/
├── user_id/
│   ├── 2024-01-01.log   # JSON Lines 格式
│   ├── 2024-01-02.log
│   └── summary.json     # 用户摘要
```

.log 文件格式（每行一个 JSON）：

```json
{ "timestamp": "...", "user_input": "...", "agent_reply": "...", "is_group": false }
```
