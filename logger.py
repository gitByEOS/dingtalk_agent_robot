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

日志格式 (每条记录):
    {
        "timestamp": "2024-01-01T12:00:00",
        "msg_id": "xxx",
        "chat_id": "xxx",
        "is_group": false,
        "is_mentioned": true,
        "user_input": "用户消息内容",
        "agent_reply": "Agent回复内容",
        "duration_ms": 1234
    }
"""

import os
import json
import time
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
        # 清理 user_id 中的特殊字符
        safe_id = self._sanitize_id(user_id)
        user_dir = self.logs_dir / safe_id
        user_dir.mkdir(parents=True, exist_ok=True)
        return user_dir

    def _sanitize_id(self, id_str: str) -> str:
        """清理 ID 字符串，只保留安全字符"""
        if not id_str:
            return "unknown"
        # 只保留字母、数字、下划线、横线
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
        """
        记录一次交互

        Args:
            user_id: 用户 ID
            user_name: 用户昵称
            msg_id: 消息 ID
            chat_id: 会话 ID
            is_group: 是否群聊
            is_mentioned: 是否被 @
            user_input: 用户输入内容
            agent_reply: Agent 回复内容
            duration_ms: 处理耗时（毫秒）
            extra: 额外信息

        Returns:
            日志文件路径
        """
        # 构建日志记录
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

        # 写入日志文件
        log_file = self._get_today_log_file(user_id)
        with open(log_file, "a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")

        # 更新汇总信息
        self._update_summary(user_id, user_name, is_group)

        return str(log_file)

    def _update_summary(self, user_id: str, user_name: str, is_group: bool):
        """更新用户汇总信息"""
        user_dir = self._get_user_dir(user_id)
        summary_file = user_dir / "summary.json"

        # 读取现有汇总
        summary = {}
        if summary_file.exists():
            try:
                with open(summary_file, "r", encoding="utf-8") as f:
                    summary = json.load(f)
            except json.JSONDecodeError as e:
                print(f"汇总解析失败: {e}")
                summary = {}
            except FileNotFoundError:
                summary = {}

        # 更新汇总
        today = datetime.now().strftime("%Y-%m-%d")
        summary.setdefault("user_id", user_id)
        summary.setdefault("user_name", user_name)
        summary.setdefault("first_interaction", datetime.now().isoformat())
        summary["last_interaction"] = datetime.now().isoformat()
        summary.setdefault("total_interactions", 0)
        summary["total_interactions"] += 1

        # 按日期统计
        summary.setdefault("daily_stats", {})
        summary["daily_stats"].setdefault(today, 0)
        summary["daily_stats"][today] += 1

        # 按会话类型统计
        if is_group:
            summary.setdefault("group_interactions", 0)
            summary["group_interactions"] += 1
        else:
            summary.setdefault("private_interactions", 0)
            summary["private_interactions"] += 1

        # 写入汇总
        with open(summary_file, "w", encoding="utf-8") as f:
            json.dump(summary, f, ensure_ascii=False, indent=2)

# 全局实例（方便直接使用）
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