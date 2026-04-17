#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
DingTalk Stream 服务 - 接收消息并调用 agent.py 处理

使用 dingtalk_stream SDK 连接钉钉 Stream 服务。
"""

import os
import subprocess
import time
import logging
from typing import Optional

import dingtalk_stream
from dingtalk_stream import (
    DingTalkStreamClient,
    Credential,
    AsyncChatbotHandler,
    ChatbotMessage,
    AckMessage,
)


from logger import log_interaction
from dingtalk_utils import send_emotion, send_markdown

logger = logging.getLogger(__name__)


class DingTalkService:
    """钉钉 Stream 服务"""

    def __init__(self, client_id: str, client_secret: str, agent_script: str = "agent.py"):
        self.client_id = client_id
        self.client_secret = client_secret
        self.agent_script = agent_script
        self.seen_messages: dict = {}  # msgId -> timestamp
        self.webhooks: dict = {}  # conversationId -> sessionWebhook
        self.dedup_ttl_ms = 5 * 60 * 1000  # 5 分钟

        # 创建 Stream 客户端
        self.credential = Credential(client_id, client_secret)
        self.client = DingTalkStreamClient(self.credential, logger)

        # 注册回调处理器
        self.handler = ServiceChatbotHandler(self)
        self.client.register_callback_handler(
            dingtalk_stream.ChatbotMessage.TOPIC,
            self.handler
        )

    def call_agent(self, message: str) -> str:
        """调用 agent.py 处理消息"""
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

    def dedup_check(self, msg_id: str) -> bool:
        """消息去重检查，返回 True 表示已处理过"""
        if msg_id in self.seen_messages:
            return True
        self.seen_messages[msg_id] = time.time() * 1000
        return False

    def get_access_token(self) -> Optional[str]:
        """获取钉钉 Access Token"""
        return self.client.get_access_token()

    def process_message(self, incoming_message: ChatbotMessage):
        """处理接收到的消息"""
        import re

        msg_id = incoming_message.message_id
        conversation_id = incoming_message.conversation_id
        session_webhook = incoming_message.session_webhook
        sender_nick = incoming_message.sender_nick or "Unknown"
        is_group = incoming_message.conversation_type == '2'
        is_mentioned = bool(incoming_message.is_in_at_list)

        # 去重检查
        if msg_id and self.dedup_check(msg_id):
            logger.info(f"[DingTalk] 重复消息 {msg_id}, 跳过")
            return

        # 缓存 webhook
        if conversation_id and session_webhook:
            self.webhooks[conversation_id] = session_webhook

        # 提取消息内容
        text = ""
        msg_type = incoming_message.message_type

        if msg_type == 'text' and incoming_message.text:
            text = incoming_message.text.content or ""
        elif msg_type == 'richText' and incoming_message.rich_text_content:
            for part in incoming_message.rich_text_content.rich_text_list:
                if 'text' in part:
                    text += part.get("text", "")
        else:
            text = f"[{msg_type}]"

        # 去除 @机器人
        if is_mentioned:
            text = re.sub(r'@\S+', '', text).strip()

        logger.info(f"[DingTalk] 收到消息: {sender_nick} -> {text[:50]}...")

        # 添加表情表示正在处理
        token = self.get_access_token()
        if token and msg_id and conversation_id:
            send_emotion(token, self.client_id, msg_id, conversation_id, "reply")

        # 调用 agent
        start_time = time.time()
        reply = self.call_agent(text)
        duration_ms = int((time.time() - start_time) * 1000)

        # 移除表情
        if token and msg_id and conversation_id:
            send_emotion(token, self.client_id, msg_id, conversation_id, "recall")

        # 记录交互日志
        log_interaction(
            user_id=incoming_message.sender_staff_id or incoming_message.sender_id or "unknown",
            user_name=sender_nick,
            msg_id=msg_id or "",
            chat_id=conversation_id or session_webhook or "",
            is_group=is_group,
            is_mentioned=is_mentioned,
            user_input=text,
            agent_reply=reply,
            duration_ms=duration_ms
        )

        # 发送回复
        if session_webhook:
            send_markdown(session_webhook, reply)
            logger.info(f"[DingTalk] 已回复: {reply[:50]}...")
        else:
            logger.warning(f"[DingTalk] 无 sessionWebhook, 无法回复")

    def connect(self):
        """连接钉钉 Stream"""
        logger.info("[DingTalk] 服务启动，连接 Stream...")
        self.client.start_forever()


class ServiceChatbotHandler(AsyncChatbotHandler):
    """自定义回调处理器 - 使用线程池处理阻塞操作"""

    def __init__(self, service: DingTalkService):
        super().__init__(max_workers=4)
        self.service = service

    def process(self, callback_message):
        """处理回调消息（非 async，在线程池中执行）"""
        try:
            incoming_message = ChatbotMessage.from_dict(callback_message.data)
            self.service.process_message(incoming_message)
            return AckMessage.STATUS_OK, "ok"
        except Exception as e:
            self.logger.error(f"[Handler] 处理异常: {e}")
            return AckMessage.STATUS_NOT_IMPLEMENT, str(e)


