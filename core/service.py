#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
服务编排层

职责：
1. 消息去重
2. 会话隔离
3. 调用 Agent
4. 记录交互日志
5. 协调 Channel 完成回复和表情
"""

import os
import subprocess
import time
import logging
import threading
from typing import Dict

from channels.dingtalk.channel import DingtalkChannel, Envelope
from core.logger import log_interaction

logger = logging.getLogger(__name__)
DEDUP_TTL_MS = 5 * 60 * 1000


class Service:
    """服务编排层"""

    def __init__(self, client_id: str, client_secret: str, agent_script: str = "agent.py"):
        self.agent_script = agent_script
        self.seen_messages: Dict[str, int] = {}
        self.session_locks: Dict[str, threading.Lock] = {}
        self.state_lock = threading.Lock()
        self.channel = DingtalkChannel(
            client_id=client_id,
            client_secret=client_secret,
            message_handler=self.handle_envelope,
            logger=logger,
        )

    def call_agent(self, message: str) -> str:
        """调用 Agent 处理消息"""
        try:
            result = subprocess.run(
                ["python3", self.agent_script, "-i", message],
                capture_output=True,
                text=True,
                timeout=120,
                cwd=os.getcwd()
            )
            if result.returncode == 0:
                return result.stdout.strip()
            else:
                logger.error(f"[Agent] 执行失败: {result.stderr}")
                return f"处理失败: {result.stderr}"

        except subprocess.TimeoutExpired:
            return "处理超时，请稍后重试"
        except Exception as e:
            return f"处理异常: {e}"

    def _cleanup_dedup_locked(self, now_ms: int):
        """清理过期去重记录"""
        expired_ids = [
            msg_id
            for msg_id, seen_at in self.seen_messages.items()
            if now_ms - seen_at > DEDUP_TTL_MS
        ]
        for msg_id in expired_ids:
            self.seen_messages.pop(msg_id, None)

    def _is_duplicate(self, msg_id: str) -> bool:
        """检查消息是否重复"""
        now_ms = int(time.time() * 1000)
        with self.state_lock:
            self._cleanup_dedup_locked(now_ms)
            if msg_id in self.seen_messages:
                return True
            self.seen_messages[msg_id] = now_ms
            return False

    def _get_session_key(self, envelope: Envelope) -> str:
        """获取会话隔离键"""
        return envelope.chat_id or envelope.sender_id or "default"

    def _get_session_lock(self, session_key: str) -> threading.Lock:
        """按会话获取串行锁"""
        with self.state_lock:
            lock = self.session_locks.get(session_key)
            if lock is None:
                lock = threading.Lock()
                self.session_locks[session_key] = lock
            return lock

    def handle_envelope(self, envelope: Envelope):
        """处理标准消息信封"""
        if envelope.message_id and self._is_duplicate(envelope.message_id):
            logger.info(f"重复消息 {envelope.message_id}, 跳过")
            return

        session_key = self._get_session_key(envelope)
        session_lock = self._get_session_lock(session_key)
        with session_lock:
            self._process_envelope(envelope)

    def _process_envelope(self, envelope: Envelope):
        """在会话锁内处理消息"""
        logger.info(f"收到消息: {envelope.sender_name} -> {envelope.text[:50]}...")

        start_time = time.time()
        reply = ""
        if envelope.conversation_id:
            self.channel.attach_reaction(envelope.message_id, envelope.conversation_id)

        try:
            reply = self.call_agent(envelope.text)
        except Exception as e:
            logger.error(f"调用 Agent 异常: {e}")
            reply = f"处理异常: {e}"
        finally:
            if envelope.conversation_id:
                self.channel.recall_reaction(envelope.message_id, envelope.conversation_id)

        duration_ms = int((time.time() - start_time) * 1000)

        log_interaction(
            user_id=envelope.sender_id or "unknown",
            user_name=envelope.sender_name,
            msg_id=envelope.message_id or "",
            chat_id=envelope.chat_id,
            is_group=envelope.is_group,
            is_mentioned=envelope.is_mentioned,
            user_input=envelope.text,
            agent_reply=reply,
            duration_ms=duration_ms,
        )

        if self.channel.reply(envelope, reply):
            logger.info(f"已回复: {reply[:50]}...")
        else:
            logger.warning("回复失败，未找到可用 webhook")

    def connect(self):
        """连接 Channel"""
        logger.info("服务启动，连接 Channel...")
        self.channel.connect()

    def disconnect(self):
        """断开 Channel"""
        self.channel.disconnect()