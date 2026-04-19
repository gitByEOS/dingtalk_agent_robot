/**
 * 主应用逻辑 - 文件夹拖拽/选择、用户列表、日志浏览、搜索过滤
 */
import { openLogFolder, parseLogFiles } from "./filePicker";
import type { LogDirectory, LogRecord, UserSummary } from "./types";
import "./style.css";

// ---- 状态 ----
let logDir: LogDirectory | null = null;
let currentUser: UserSummary | null = null;
let currentRecords: LogRecord[] = [];
let availableDates: string[] = [];
let searchQuery = "";

// ---- 初始化 ----
export function initApp(): void {
  showFolderPicker();
  bindSearch();
}

// ---- 文件夹选择（拖拽 + 按钮）----
function showFolderPicker(): void {
  const app = document.getElementById("app")!;
  app.innerHTML = `
    <header>
      <h1>日志查看器</h1>
    </header>
    <main class="container center-content">
      <div class="folder-picker">
        <div id="drop-zone" class="drop-zone">
          <svg xmlns="http://www.w3.org/2000/svg" width="48" height="48" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round">
            <path d="M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 3h9a2 2 0 0 1 2 2z"/>
            <line x1="12" y1="11" x2="12" y2="17"/>
            <line x1="9" y1="14" x2="15" y2="14"/>
          </svg>
          <p class="drop-hint">拖拽日志文件夹到这里</p>
          <button id="open-folder-btn" class="secondary-btn">或点击选择</button>
        </div>
      </div>
    </main>
  `;

  // 整个页面作为拖拽区域
  app.classList.add("drop-zone-full");

  app.addEventListener("dragover", (e) => {
    e.preventDefault();
    app.classList.add("dragover");
  });
  app.addEventListener("dragleave", (e) => {
    // 只有离开整个 app 才移除样式
    if (e.target === app) app.classList.remove("dragover");
  });

  app.addEventListener("drop", async (e) => {
    e.preventDefault();
    app.classList.remove("dragover");
    app.classList.remove("drop-zone-full");

    const items = Array.from(e.dataTransfer?.items || []);
    const files: File[] = [];

    for (const item of items) {
      if (item.kind === "file") {
        const entry = item.webkitGetAsEntry?.();
        if (entry) {
          await collectFiles(entry, files);
        } else {
          const file = item.getAsFile();
          if (file) files.push(file);
        }
      }
    }

    if (files.length === 0) return;

    try {
      logDir = await parseLogFiles(files);
      if (logDir.users.length === 0) {
        alert("未找到日志文件");
        return;
      }
      showMainView();
    } catch (err) {
      console.error((err as Error).message);
    }
  });

  document.getElementById("open-folder-btn")!.addEventListener("click", async () => {
    try {
      logDir = await openLogFolder();
      if (logDir.users.length === 0) {
        alert("未找到日志文件");
        return;
      }
      showMainView();
    } catch (e) {
      console.error((e as Error).message);
    }
  });
}

// 递归收集目录下的所有文件
async function collectFiles(entry: FileSystemEntry, files: File[]): Promise<void> {
  if (entry.isFile) {
    const file = await new Promise<File>((resolve) => (entry as FileSystemFileEntry).file(resolve));
    // 给 file 加上 webkitRelativePath（拖拽时缺失）
    Object.defineProperty(file, "webkitRelativePath", { value: entry.fullPath.slice(1) });
    files.push(file);
  } else if (entry.isDirectory) {
    const reader = (entry as FileSystemDirectoryEntry).createReader();
    const entries = await new Promise<FileSystemEntry[]>((resolve) => reader.readEntries(resolve));
    for (const e of entries) {
      await collectFiles(e, files);
    }
  }
}

// ---- 主视图 ----
function showMainView(): void {
  const app = document.getElementById("app")!;
  app.innerHTML = `
    <header>
      <h1>日志查看器</h1>
      <div class="search-bar">
        <input type="text" id="search-input" placeholder="搜索用户输入或回复..." />
      </div>
      <button id="reopen-folder-btn" class="secondary-btn">重新选择</button>
    </header>
    <main class="container">
      <aside class="sidebar">
        <h2>用户列表</h2>
        <ul id="user-list"></ul>
      </aside>
      <section class="content">
        <div id="date-filter"></div>
        <div id="log-container"></div>
      </section>
    </main>
  `;

  document.getElementById("reopen-folder-btn")!.addEventListener("click", () => {
    logDir = null;
    currentUser = null;
    showFolderPicker();
  });

  renderUserList();
}

// ---- 用户列表 ----
function renderUserList(): void {
  if (!logDir) return;

  const list = document.getElementById("user-list")!;
  list.innerHTML = "";

  for (const user of logDir.users) {
    const li = document.createElement("li");
    li.className = "user-item";
    li.innerHTML = `
      <div class="user-name">${escapeHtml(user.name)}</div>
      <div class="user-meta">${user.total} 次交互</div>
    `;
    li.addEventListener("click", () => selectUser(user, li));
    list.appendChild(li);
  }
}

// ---- 选择用户 ----
function selectUser(user: UserSummary, li: HTMLLIElement): void {
  document.querySelectorAll(".user-item.active").forEach((el) => {
    el.classList.remove("active");
  });
  li.classList.add("active");

  currentUser = user;
  searchQuery = "";
  const searchInput = document.getElementById("search-input") as HTMLInputElement;
  if (searchInput) searchInput.value = "";

  // 从 logsByUser 获取日期列表
  const datesMap = logDir?.logsByUser.get(user.id);
  if (datesMap) {
    availableDates = Array.from(datesMap.keys()).sort().reverse();
  } else {
    availableDates = [];
  }
  renderDateFilter();

  if (availableDates.length > 0) {
    loadLogs(availableDates[0]);
  }
}

// ---- 日期筛选 ----
function renderDateFilter(): void {
  const container = document.getElementById("date-filter")!;
  if (availableDates.length === 0) {
    container.innerHTML = "";
    return;
  }

  container.innerHTML = `
    <div class="date-chips">
      ${availableDates.map((d) => `<button class="date-chip" data-date="${d}">${d}</button>`).join("")}
    </div>
  `;

  container.querySelectorAll(".date-chip").forEach((btn) => {
    btn.addEventListener("click", () => {
      container
        .querySelectorAll(".date-chip.active")
        .forEach((el) => el.classList.remove("active"));
      btn.classList.add("active");
      loadLogs(btn.getAttribute("data-date")!);
    });
  });

  const first = container.querySelector(".date-chip");
  if (first) first.classList.add("active");
}

// ---- 加载日志 ----
function loadLogs(date: string): void {
  if (!currentUser || !logDir) return;

  const datesMap = logDir.logsByUser.get(currentUser.id);
  currentRecords = datesMap?.get(date) || [];
  renderRecords();
}

// ---- 渲染记录 ----
function renderRecords(): void {
  const container = document.getElementById("log-container")!;
  const records = searchQuery
    ? currentRecords.filter(
        (r) =>
          r.user_input.toLowerCase().includes(searchQuery.toLowerCase()) ||
          r.agent_reply.toLowerCase().includes(searchQuery.toLowerCase()),
      )
    : currentRecords;

  if (records.length === 0) {
    container.innerHTML = `<div class="empty">${searchQuery ? "无匹配结果" : "暂无记录"}</div>`;
    return;
  }

  container.innerHTML = records.map(formatRecord).join("");
}

// ---- 格式化单条记录 ----
function formatRecord(record: LogRecord): string {
  const time = record.timestamp.split("T")[1]?.split(".")[0] || "";
  const duration = record.duration_ms ? `${record.duration_ms}ms` : "";

  return `
    <div class="log-card">
      <div class="log-header">
        <span class="log-time">${escapeHtml(time)}</span>
        <span class="log-meta">
          ${record.is_group ? "群聊" : "私聊"}
          ${duration ? ` · ${duration}` : ""}
        </span>
      </div>
      <div class="log-input">
        <div class="log-label">用户</div>
        <div class="log-text">${escapeHtml(record.user_input)}</div>
      </div>
      <div class="log-reply">
        <div class="log-label">Agent 🤖</div>
        <div class="log-text">${escapeHtml(record.agent_reply)}</div>
      </div>
    </div>
  `;
}

// ---- 搜索 ----
function bindSearch(): void {
  const app = document.getElementById("app");
  if (!app) return;

  app.addEventListener("input", (e) => {
    const target = e.target as HTMLInputElement;
    if (target.id === "search-input") {
      clearTimeout(
        (target as HTMLInputElement & { _timer?: ReturnType<typeof setTimeout> })._timer,
      );
      const timer = setTimeout(() => {
        searchQuery = target.value.trim();
        renderRecords();
      }, 200);
      (target as HTMLInputElement & { _timer?: ReturnType<typeof setTimeout> })._timer = timer;
    }
  });
}

// ---- 工具 ----
function escapeHtml(str: string): string {
  const div = document.createElement("div");
  div.textContent = str;
  return div.innerHTML;
}
