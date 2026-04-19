/**
 * TypeScript 类型定义
 */

export interface UserSummary {
  id: string;
  name: string;
  total: number;
  lastInteraction: string;
  groupInteractions: number;
  privateInteractions: number;
}

export interface LogRecord {
  timestamp: string;
  msg_id: string;
  chat_id: string;
  is_group: boolean;
  is_mentioned: boolean;
  user_input: string;
  agent_reply: string;
  duration_ms: number | null;
  extra?: Record<string, unknown>;
}

/**
 * 解析后的日志目录数据
 * - users: 用户列表（从 summary.json 提取）
 * - logsByUser: 每个用户的日期 → 记录数组映射
 */
export interface LogDirectory {
  users: UserSummary[];
  logsByUser: Map<string, Map<string, LogRecord[]>>;
}
