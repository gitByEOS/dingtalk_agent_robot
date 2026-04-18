#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
交互日志系统 - 记录用户与 Agent 的对话

目录结构:
    logs/
    └── {user_id}/              # 每个用户一个文件夹
        ├── 2024-01-01.log      # 每天一个日志文件
        ├── 2024-01-02.log
        └── summary.json        # 用户汇总信息
"""

import json
from datetime import datetime
from pathlib import Path
from typing import Optional, Dict, Any


class InteractionLogger:
    """交互日志记录器"""

    def __init__(self, logs_dir: str = "./logs"):
        self.logs_dir = Path(logs_dir)
        self.logs_dir.mkdir(parents=True, exist_ok=True)

    def _get_user_dir(self, user_id: str) -> Path:
        """获取用户日志目录"""
        safe_id = self._sanitize_id(user_id)
        user_dir = self.logs_dir / safe_id
        user_dir.mkdir(parents=True, exist_ok=True)
        return user_dir

    def _sanitize_id(self, id_str: str) -> str:
        """清理 ID 字符串，只保留安全字符"""
        if not id_str:
            return "unknown"
        safe = "".join(c if c.isalnum() or c in "_-" else "_" for c in id_str)
        return safe[:64] if len(safe) > 64 else safe

    def _get_today_log_file(self, user_id: str) -> Path:
        """获取今天的日志文件路径"""
        user_dir = self._get_user_dir(user_id)
        today = datetime.now().strftime("%Y-%m-%d")
        return user_dir / f"{today}.log"

    def log_interaction(
        self,
        user_id: str,
        user_name: str,
        msg_id: str,
        chat_id: str,
        is_group: bool,
        is_mentioned: bool,
        user_input: str,
        agent_reply: str,
        duration_ms: Optional[int] = None,
        extra: Optional[Dict[str, Any]] = None
    ) -> str:
        """记录一次交互"""
        record = {
            "timestamp": datetime.now().isoformat(),
            "msg_id": msg_id,
            "chat_id": chat_id,
            "is_group": is_group,
            "is_mentioned": is_mentioned,
            "user_input": user_input,
            "agent_reply": agent_reply,
            "duration_ms": duration_ms
        }

        if extra:
            record["extra"] = extra

        log_file = self._get_today_log_file(user_id)
        with open(log_file, "a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")

        self._update_summary(user_id, user_name, is_group)
        return str(log_file)

    def _update_summary(self, user_id: str, user_name: str, is_group: bool):
        """更新用户汇总信息"""
        user_dir = self._get_user_dir(user_id)
        summary_file = user_dir / "summary.json"

        summary = {}
        if summary_file.exists():
            try:
                with open(summary_file, "r", encoding="utf-8") as f:
                    summary = json.load(f)
            except (json.JSONDecodeError, FileNotFoundError):
                summary = {}

        today = datetime.now().strftime("%Y-%m-%d")
        summary.setdefault("user_id", user_id)
        summary.setdefault("user_name", user_name)
        summary.setdefault("first_interaction", datetime.now().isoformat())
        summary["last_interaction"] = datetime.now().isoformat()
        summary.setdefault("total_interactions", 0)
        summary["total_interactions"] += 1

        summary.setdefault("daily_stats", {})
        summary["daily_stats"].setdefault(today, 0)
        summary["daily_stats"][today] += 1

        if is_group:
            summary.setdefault("group_interactions", 0)
            summary["group_interactions"] += 1
        else:
            summary.setdefault("private_interactions", 0)
            summary["private_interactions"] += 1

        with open(summary_file, "w", encoding="utf-8") as f:
            json.dump(summary, f, ensure_ascii=False, indent=2)


_logger: Optional[InteractionLogger] = None


def get_logger(logs_dir: str = "./logs") -> InteractionLogger:
    """获取全局日志实例"""
    global _logger
    if _logger is None:
        _logger = InteractionLogger(logs_dir)
    return _logger


def log_interaction(
    user_id: str,
    user_name: str,
    msg_id: str,
    chat_id: str,
    is_group: bool,
    is_mentioned: bool,
    user_input: str,
    agent_reply: str,
    duration_ms: Optional[int] = None
) -> str:
    """便捷日志函数"""
    return get_logger().log_interaction(
        user_id, user_name, msg_id, chat_id,
        is_group, is_mentioned, user_input, agent_reply, duration_ms
    )


def dump_conversations(logs_dir: str):
    """打印目录下所有对话日志"""
    logs_path = Path(logs_dir)
    if not logs_path.exists():
        print(f"目录不存在: {logs_dir}")
        return

    log_files = sorted(logs_path.rglob("*.log"))
    if not log_files:
        print(f"无日志文件: {logs_dir}")
        return

    for log_file in log_files:
        user_id = log_file.parent.name
        date = log_file.stem
        print(f"\n=== {user_id} / {date} ===")

        with open(log_file, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    record = json.loads(line)
                    ts = record.get("timestamp", "")
                    time_str = ts.split(".")[0] if ts else ""
                    print(f"\n[{time_str}]")
                    print(f"用户: {record.get('user_input', '')}")
                    print(f"回复: {record.get('agent_reply', '')}")
                except json.JSONDecodeError:
                    continue


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="交互日志工具")
    parser.add_argument("--dump", metavar="DIR", help="打印目录下所有对话日志")
    args = parser.parse_args()

    if args.dump:
        dump_conversations(args.dump)