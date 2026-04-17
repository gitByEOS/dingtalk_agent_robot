#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
DingTalk Channel - 钉钉机器人适配器

核心功能：
1. 通过 dingtalk-stream SDK 连接钉钉 Stream
2. 消息接收和解析（text, richText, picture, file, audio, video）
3. 消息去重（防止重试导致重复处理）
4. Markdown 格式化（表格转换、消息分块）
5. 媒体文件下载和附件处理
6. 引用消息上下文提取
7. 表情回复（👀 表示正在处理）
8. Webhook 缓存用于回复消息

参考: dingtalk-js/src/DingtalkAdapter.ts
"""

import json
import re
import os
import time
import tempfile
import uuid
import hashlib
import logging
import asyncio
import requests
from typing import Optional, Dict, List, Any, Callable
from dataclasses import dataclass, field
from concurrent.futures import ThreadPoolExecutor

from dingtalk_utils import send_emotion, send_markdown, send_text_message, normalize_dingtalk_markdown
import dingtalk_stream
import websockets
from dingtalk_stream import (
    DingTalkStreamClient,
    Credential,
    ChatbotHandler,
    ChatbotMessage,
    AckMessage,
    CallbackMessage,
)

# 常量
CHUNK_LIMIT = 3800  # 钉钉消息最大长度
DEDUP_TTL_MS = 5 * 60 * 1000  # 去重 TTL 5分钟
DOWNLOAD_API = "https://api.dingtalk.com/v1.0/robot/messageFiles/download"
EMOTION_API = "https://api.dingtalk.com/v1.0/robot/emotion"
ACK_REACTION_NAME = "get✓" #👀
ACK_EMOTION_ID = "2659900"
ACK_EMOTION_BG_ID = "im_bg_1"


# --- 数据结构 ---


@dataclass
class MediaFile:
    """媒体文件"""
    data: bytes
    mime_type: str


@dataclass
class Attachment:
    """消息附件"""
    type: str  # 'image', 'file', 'audio', 'video'
    data: Optional[str] = None  # base64 (for image)
    file_path: Optional[str] = None  # 文件路径 (for file/audio/video)
    mime_type: Optional[str] = None
    file_name: Optional[str] = None


@dataclass
class Envelope:
    """
    消息信封 - 包含完整的消息上下文信息
    类似 dingtalk-js 的 Envelope 结构
    """
    channel_name: str = ""
    sender_id: str = ""
    sender_name: str = "Unknown"
    chat_id: str = ""  # conversationId 或 sessionWebhook
    text: str = ""
    is_group: bool = False
    is_mentioned: bool = False
    is_reply_to_bot: bool = False
    referenced_text: Optional[str] = None  # 引用消息内容
    message_id: Optional[str] = None
    attachments: List[Attachment] = field(default_factory=list)


# --- 媒体下载 ---


def download_media(download_code: str, robot_code: str, access_token: str) -> Optional[MediaFile]:
    """
    下载钉钉媒体文件（两步流程）

    Args:
        download_code: 消息中的下载码
        robot_code: 机器人的 clientId (AppKey)
        access_token: 钉钉 Access Token

    Returns:
        MediaFile 或 None
    """
    if not download_code or not robot_code or not access_token:
        return None

    try:
        # Step 1: 获取下载 URL
        api_resp = requests.post(
            DOWNLOAD_API,
            headers={
                "x-acs-dingtalk-access-token": access_token,
                "Content-Type": "application/json"
            },
            json={"downloadCode": download_code, "robotCode": robot_code},
            timeout=30
        )

        if api_resp.status_code != 200:
            print(f"获取下载URL失败: HTTP {api_resp.status_code}")
            return None

        payload = api_resp.json()
        download_url = payload.get("downloadUrl") or payload.get("data", {}).get("downloadUrl")

        if not download_url:
            print("响应中无 downloadUrl")
            return None

        # Step 2: 下载文件
        file_resp = requests.get(download_url, timeout=60)
        if file_resp.status_code != 200:
            print(f"下载文件失败: HTTP {file_resp.status_code}")
            return None

        mime_type = file_resp.headers.get("Content-Type", "application/octet-stream")
        return MediaFile(data=file_resp.content, mime_type=mime_type)

    except Exception as e:
        print(f"下载媒体异常: {e}")
        return None


# --- DingtalkChannel 类 ---


class DingtalkChannel:
    """
    钉钉机器人适配器 - 完整实现

    功能：
    1. 通过 dingtalk-stream SDK 连接钉钉 Stream
    2. 消息接收和解析
    3. 消息去重
    4. Webhook 缓存用于回复
    5. 媒体下载和附件处理
    6. 引用消息上下文提取
    7. 表情回复
    """

    def __init__(self, client_id: str, client_secret: str,
                 message_handler: Optional[Callable[[Envelope], None]] = None,
                 logger: Optional[logging.Logger] = None):
        """
        初始化 DingtalkChannel

        Args:
            client_id: 钉钉机器人 AppKey
            client_secret: 钉钉机器人 AppSecret
            message_handler: 消息处理回调函数，接收 Envelope
            logger: 日志记录器
        """
        if not client_id or not client_secret:
            raise ValueError("需要提供 client_id 和 client_secret")

        self.client_id = client_id
        self.client_secret = client_secret
        self.message_handler = message_handler
        self.logger = logger or logging.getLogger('dingtalk_channel')

        # Stream 客户端
        self.credential = Credential(client_id, client_secret)
        self.client = DingTalkStreamClient(self.credential, self.logger)

        # 消息去重
        self.seen_messages: Dict[str, int] = {}

        # Webhook 缓存: conversationId → sessionWebhook
        self.webhooks: Dict[str, str] = {}

        # 反应上下文: messageId → conversationId
        self.reaction_context: Dict[str, str] = {}

        # 正在处理的消息
        self.processing_messages: Dict[str, bool] = {}

        # 注册回调处理器
        self.handler = DingtalkCallbackHandler(self)
        self.client.register_callback_handler(
            dingtalk_stream.ChatbotMessage.TOPIC,
            self.handler
        )

    def connect(self):
        """连接钉钉 Stream"""
        self.logger.info("[DingTalk] Connecting via stream...")
        self.client.start_forever()

    def disconnect(self):
        """断开连接"""
        # dingtalk_stream SDK 的 stop 方法
        pass

    def get_access_token(self) -> Optional[str]:
        """获取钉钉 Access Token"""
        return self.client.get_access_token()

    def send_message(self, chat_id: str, text: str) -> bool:
        """
        发送消息到指定会话

        Args:
            chat_id: conversationId
            text: Markdown 文本

        Returns:
            是否发送成功
        """
        webhook = self.webhooks.get(chat_id)
        if not webhook:
            self.logger.error(f"[DingTalk] No webhook for chat_id {chat_id}, cannot send.")
            return False

        return send_markdown(webhook, text)

    def _attach_reaction(self, msg_id: str, conversation_id: str):
        """添加表情反应"""
        token = self.get_access_token()
        if token:
            send_emotion(token, self.client_id, msg_id, conversation_id, "reply")

    def _recall_reaction(self, msg_id: str, conversation_id: str):
        """移除表情反应"""
        token = self.get_access_token()
        if token:
            send_emotion(token, self.client_id, msg_id, conversation_id, "recall")

    def _on_prompt_start(self, msg_id: str):
        """开始处理消息时调用"""
        conv_id = self.reaction_context.get(msg_id)
        if conv_id:
            self._attach_reaction(msg_id, conv_id)

    def _on_prompt_end(self, msg_id: str):
        """处理完成时调用"""
        conv_id = self.reaction_context.get(msg_id)
        if conv_id:
            self._recall_reaction(msg_id, conv_id)
            self.reaction_context.pop(msg_id, None)

    def _dedup_check(self, msg_id: str) -> bool:
        """
        消息去重检查

        Returns:
            True 表示消息已处理过（跳过），False 表示新消息
        """
        now = int(time.time() * 1000)
        if msg_id in self.seen_messages:
            return True
        self.seen_messages[msg_id] = now
        return False

    def _cleanup_dedup(self):
        """清理过期的去重记录"""
        now = int(time.time() * 1000)
        expired = [k for k, v in self.seen_messages.items() if now - v > DEDUP_TTL_MS]
        for k in expired:
            self.seen_messages.pop(k)

    def _extract_content(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """
        从钉钉消息提取内容和媒体信息

        Returns:
            {
                'text': str,
                'download_codes': List[str],
                'media_type': Optional[str],
                'file_name': Optional[str]
            }
        """
        msgtype = data.get('msgtype', 'text')
        content = data.get('content', {})
        text_data = data.get('text', {})

        result = {
            'text': '',
            'download_codes': [],
            'media_type': None,
            'file_name': None
        }

        if msgtype == 'richText':
            rich_text = content.get('richText', [])
            text_parts = []
            codes = []
            for part in rich_text:
                part_type = part.get('type', 'text')
                if part_type == 'text' and part.get('text'):
                    text_parts.append(part['text'])
                elif part_type == 'picture' and part.get('downloadCode'):
                    codes.append(part['downloadCode'])

            result['text'] = ''.join(text_parts).strip() or ('(image)' if codes else '')
            result['download_codes'] = codes
            result['media_type'] = 'image' if codes else None

        elif msgtype == 'picture':
            code = content.get('downloadCode')
            result['text'] = '(image)'
            result['download_codes'] = [code] if code else []
            result['media_type'] = 'image'

        elif msgtype == 'file':
            code = content.get('downloadCode')
            file_name = content.get('fileName')
            result['text'] = f"(file: {file_name or 'file'})"
            result['download_codes'] = [code] if code else []
            result['media_type'] = 'file'
            result['file_name'] = file_name

        elif msgtype == 'audio':
            code = content.get('downloadCode')
            recognition = content.get('recognition')
            result['text'] = recognition or '(audio)'
            result['download_codes'] = [code] if code else []
            result['media_type'] = 'audio'

        elif msgtype == 'video':
            code = content.get('downloadCode')
            result['text'] = '(video)'
            result['download_codes'] = [code] if code else []
            result['media_type'] = 'video'

        else:
            # 默认文本消息
            result['text'] = text_data.get('content', '').strip()

        return result

    def _extract_quoted_context(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """
        提取引用消息上下文

        Returns:
            {
                'referenced_text': Optional[str],
                'is_reply_to_bot': bool
            }
        """
        chatbot_user_id = data.get('chatbotUserId')
        result = {'referenced_text': None, 'is_reply_to_bot': False}

        # 新格式: text.repliedMsg
        text_data = data.get('text', {})
        if text_data.get('isReplyMsg') and text_data.get('repliedMsg'):
            replied = text_data['repliedMsg']
            sender_id = replied.get('senderId')
            result['is_reply_to_bot'] = bool(chatbot_user_id and sender_id == chatbot_user_id)
            result['referenced_text'] = self._summarize_replied_content(replied)

        # 旧格式: quoteMessage
        elif data.get('quoteMessage'):
            quote = data['quoteMessage']
            sender_id = quote.get('senderId')
            result['is_reply_to_bot'] = bool(chatbot_user_id and sender_id == chatbot_user_id)
            result['referenced_text'] = quote.get('text', {}).get('content', '').strip()

        return result

    def _summarize_replied_content(self, replied: Dict[str, Any]) -> Optional[str]:
        """总结回复消息内容"""
        msg_type = replied.get('msgType')
        content = replied.get('content', {})

        # 直接文本
        if content.get('text'):
            return content['text'].strip()

        # RichText
        if content.get('richText'):
            parts = []
            for part in content['richText']:
                part_type = part.get('type', 'text')
                if part_type == 'text' and part.get('text'):
                    parts.append(part['text'])
                elif part_type == 'picture':
                    parts.append('[image]')
                elif part_type == 'at' and part.get('atName'):
                    parts.append(f"@{part['atName']}")
            return ''.join(parts).strip() if parts else None

        # 媒体类型
        if msg_type == 'picture':
            return '[image]'
        elif msg_type == 'file':
            return f"[file: {content.get('fileName', 'file')}]"
        elif msg_type == 'audio':
            return '[audio]'
        elif msg_type == 'video':
            return '[video]'

        return None

    def _attach_media(self, envelope: Envelope, download_code: str,
                      media_type: str, file_name: Optional[str] = None):
        """下载媒体文件并附加到 envelope"""
        token = self.get_access_token()
        if not token:
            self.logger.error("[DingTalk] Cannot download media: missing token")
            return

        media = download_media(download_code, self.client_id, token)
        if not media:
            return

        if media_type == 'image':
            mime = media.mime_type if media.mime_type.startswith('image/') else 'image/jpeg'
            envelope.attachments.append(Attachment(
                type='image',
                data=media.data.decode('base64'),  # 需要转 base64
                mime_type=mime
            ))
        else:
            # 保存非图片文件到临时目录
            dir_path = os.path.join(tempfile.gettempdir(), 'channel-files', str(uuid.uuid4()))
            os.makedirs(dir_path, exist_ok=True)
            safe_name = file_name or f"dingtalk_{media_type}_{int(time.time())}"
            file_path = os.path.join(dir_path, safe_name)

            with open(file_path, 'wb') as f:
                f.write(media.data)

            # 清理占位符文本
            placeholder_texts = ['(audio)', '(video)', f"(file: {file_name or 'file'})"]
            if envelope.text in placeholder_texts:
                envelope.text = ''

            envelope.attachments.append(Attachment(
                type=media_type,
                file_path=file_path,
                mime_type=media.mime_type,
                file_name=safe_name
            ))

    def process_message(self, incoming_message: ChatbotMessage):
        """
        处理接收到的消息

        Args:
            incoming_message: dingtalk_stream 的 ChatbotMessage
        """
        try:
            msg_id = incoming_message.message_id

            # 去重检查
            if msg_id and self._dedup_check(msg_id):
                return

            conversation_type = incoming_message.conversation_type
            session_webhook = incoming_message.session_webhook
            conversation_id = incoming_message.conversation_id

            if not session_webhook:
                self.logger.warning("[DingTalk] No sessionWebhook in message, skipping.")
                return

            # 缓存 webhook
            if conversation_id:
                self.webhooks[conversation_id] = session_webhook

            is_group = conversation_type == '2'
            is_mentioned = bool(incoming_message.is_in_at_list)

            # 提取内容
            content = self._extract_content(incoming_message.to_dict())
            clean_text = content['text']

            # 移除 @机器人
            if is_mentioned:
                clean_text = re.sub(r'@\S+', '', clean_text).strip()

            # 提取引用上下文
            quoted = self._extract_quoted_context(incoming_message.to_dict())

            chat_id = conversation_id or session_webhook

            envelope = Envelope(
                channel_name='dingtalk',
                sender_id=incoming_message.sender_staff_id or incoming_message.sender_id or '',
                sender_name=incoming_message.sender_nick or 'Unknown',
                chat_id=chat_id,
                text=clean_text or content['text'],
                is_group=is_group,
                is_mentioned=is_mentioned,
                is_reply_to_bot=quoted['is_reply_to_bot'],
                referenced_text=quoted['referenced_text'],
                message_id=msg_id
            )

            # 存储反应上下文
            if msg_id and conversation_id:
                self.reaction_context[msg_id] = conversation_id

            # 下载媒体
            if content['download_codes'] and content['media_type']:
                code = content['download_codes'][0]
                self._attach_media(envelope, code, content['media_type'], content['file_name'])

            # 添加表情反应
            self._on_prompt_start(msg_id)

            # 调用消息处理器
            if self.message_handler:
                try:
                    self.message_handler(envelope)
                except Exception as e:
                    self.logger.error(f"[DingTalk] Error in message handler: {e}")
                    self.send_message(chat_id, "Sorry, something went wrong processing your message.")
            else:
                self.logger.info(f"[DingTalk] Received message: {envelope.text[:50]}...")

            # 移除表情反应
            self._on_prompt_end(msg_id)

        except Exception as e:
            self.logger.error(f"[DingTalk] Failed to process message: {e}")


class DingtalkCallbackHandler(ChatbotHandler):
    """
    自定义回调处理器 - 将消息转发给 DingtalkChannel
    """

    def __init__(self, channel: DingtalkChannel):
        super().__init__()
        self.channel = channel

    def process(self, callback_message: CallbackMessage):
        """处理回调消息"""
        try:
            incoming_message = ChatbotMessage.from_dict(callback_message.data)
            self.channel.process_message(incoming_message)
            return AckMessage.STATUS_OK, "ok"
        except Exception as e:
            self.logger.error(f"[DingtalkCallbackHandler] Error: {e}")
            return AckMessage.STATUS_NOT_IMPLEMENT, str(e)


# --- CLI 入口 ---


def main():
    import argparse

    parser = argparse.ArgumentParser(description="钉钉机器人消息发送工具")
    parser.add_argument("-w", "--webhook", required=True, help="钉钉机器人 Webhook URL")
    parser.add_argument("-m", "--message", required=True, help="消息内容")
    parser.add_argument("-t", "--title", help="消息标题")
    parser.add_argument("--type", choices=["markdown", "text"], default="markdown", help="消息类型")

    args = parser.parse_args()

    if args.type == "markdown":
        success = send_markdown(args.webhook, args.message, args.title)
    else:
        success = send_text_message(args.webhook, args.message)

    print(f"发送{'成功' if success else '失败'}")


if __name__ == "__main__":
    main()