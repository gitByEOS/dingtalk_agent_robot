/**
 * 文件夹选择器 - 用户选择 logs 目录，浏览器直接解析
 *
 * 使用 <input type="file" webkitdirectory> 让用户选择本地文件夹，
 * 通过 FileReader API 读取 .log（JSON Lines）和 summary.json。
 * 纯浏览器方案，零后端依赖。
 */
import type { LogDirectory, UserSummary, LogRecord } from "./types";

/**
 * 打开文件夹选择器，返回解析后的日志数据
 */
export function openLogFolder(): Promise<LogDirectory> {
  return new Promise((resolve, reject) => {
    const input = document.createElement("input");
    input.type = "file";
    (input as HTMLInputElement & { webkitdirectory: boolean }).webkitdirectory = true;

    input.addEventListener("change", async () => {
      const files = Array.from(input.files || []);
      if (files.length === 0) {
        reject(new Error("未选择任何文件"));
        return;
      }
      const dir = await parseLogFiles(files);
      resolve(dir);
    });

    input.click();
  });
}

/**
 * 遍历 FileList，按 user_id 分组并解析日志文件
 */
export async function parseLogFiles(files: File[]): Promise<LogDirectory> {
  const userMap = new Map<string, { files: File[]; summary?: Record<string, unknown> }>();

  // 按路径分组：user_id/2024-01-01.log → user_id
  // 如果选择的是 logs/ 根目录，路径为 logs/user_id/file.log，需要跳过第一层
  for (const file of files) {
    const parts = file.webkitRelativePath.split("/");
    const offset = parts[0] === "logs" ? 1 : 0;
    if (parts.length < offset + 2) continue;

    const userId = parts[offset];
    if (!userMap.has(userId)) {
      userMap.set(userId, { files: [] });
    }

    const entry = userMap.get(userId)!;
    if (parts[offset + 1] === "summary.json") {
      entry.summary = await readJsonFile(file);
    } else if (parts[offset + 1].endsWith(".log")) {
      entry.files.push(file);
    }
  }

  // 构建用户列表
  const users: UserSummary[] = [];
  const logsByUser = new Map<string, Map<string, LogRecord[]>>();

  for (const [userId, entry] of userMap) {
    const s = entry.summary || {};
    const user: UserSummary = {
      id: userId,
      name: (s.user_name as string) || userId,
      total: (s.total_interactions as number) || entry.files.length,
      lastInteraction: (s.last_interaction as string) || "",
      groupInteractions: (s.group_interactions as number) || 0,
      privateInteractions: (s.private_interactions as number) || 0,
    };
    users.push(user);

    // 解析日志文件
    const datesMap = new Map<string, LogRecord[]>();
    for (const file of entry.files) {
      const date = file.name.replace(".log", "");
      const records = await readJsonLinesFile(file);
      datesMap.set(date, records);
    }
    logsByUser.set(userId, datesMap);
  }

  users.sort((a, b) => b.lastInteraction.localeCompare(a.lastInteraction));
  return { users, logsByUser };
}

/**
 * 读取单个 JSON 文件
 */
function readJsonFile(file: File): Promise<Record<string, unknown>> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => {
      try {
        resolve(JSON.parse(reader.result as string));
      } catch {
        resolve({});
      }
    };
    reader.onerror = () => reject(new Error(`读取文件失败: ${file.name}`));
    reader.readAsText(file);
  });
}

/**
 * 读取 JSON Lines 文件，返回记录数组
 */
function readJsonLinesFile(file: File): Promise<LogRecord[]> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => {
      const lines = (reader.result as string).split("\n").filter((line) => line.trim());
      const records = lines
        .map((line) => {
          try {
            return JSON.parse(line) as LogRecord;
          } catch {
            return null;
          }
        })
        .filter(Boolean) as LogRecord[];
      resolve(records);
    };
    reader.onerror = () => reject(new Error(`读取日志文件失败: ${file.name}`));
    reader.readAsText(file);
  });
}
