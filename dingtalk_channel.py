#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
DingTalk Channel - 钉钉机器人适配器

核心功能：
1. 通过 dingtalk-stream SDK 连接钉钉 Stream
2. 消息接收和解析（text, richText, picture, file, audio, video）
3. Markdown 格式化（表格转换、消息分块）
4. 媒体文件下载和附件处理
5. 引用消息上下文提取
6. 表情回复（👀 表示正在处理）
7. Webhook 缓存用于回复消息

参考: dingtalk-js/src/DingtalkAdapter.ts
"""

import re
import os
import time
import base64
import asyncio
import tempfile
import uuid
import logging
import threading
import requests
from typing import Optional, Dict, List, Any, Callable
from dataclasses import dataclass, field
from concurrent.futures import ThreadPoolExecutor

from dingtalk_utils import send_emotion, send_markdown, send_text_message
import dingtalk_stream
from dingtalk_stream import (
    DingTalkStreamClient,
    Credential,
    ChatbotHandler,
    ChatbotMessage,
    AckMessage,
    CallbackMessage,
)

# 常量
DOWNLOAD_API = "https://api.dingtalk.com/v1.0/robot/messageFiles/download"

# 消息类型处理器
MSGTYPE_HANDLERS = {
    'picture': lambda c: ('(image)', [c.get('downloadCode')], 'image', None),
    'file': lambda c: (f"(file: {c.get('fileName') or 'file'})", [c.get('downloadCode')], 'file', c.get('fileName')),
    'audio': lambda c: (c.get('recognition') or '(audio)', [c.get('downloadCode')], 'audio', None),
    'video': lambda c: ('(video)', [c.get('downloadCode')], 'video', None),
}


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
    """消息信封"""
    channel_name: str = ""
    sender_id: str = ""
    sender_name: str = "Unknown"
    chat_id: str = ""
    conversation_id: str = ""
    session_webhook: str = ""
    text: str = ""
    is_group: bool = False
    is_mentioned: bool = False
    is_reply_to_bot: bool = False
    referenced_text: Optional[str] = None
    message_id: Optional[str] = None
    attachments: List[Attachment] = field(default_factory=list)


# --- 媒体下载 ---


def download_media(download_code: str, robot_code: str, access_token: str) -> Optional[MediaFile]:
    """下载钉钉媒体文件"""
    if not download_code or not robot_code or not access_token:
        return None

    try:
        resp = requests.post(
            DOWNLOAD_API,
            headers={
                "x-acs-dingtalk-access-token": access_token,
                "Content-Type": "application/json"
            },
            json={"downloadCode": download_code, "robotCode": robot_code},
            timeout=30
        )
        if resp.status_code != 200:
            return None

        payload = resp.json()
        download_url = payload.get("downloadUrl") or payload.get("data", {}).get("downloadUrl")
        if not download_url:
            return None

        file_resp = requests.get(download_url, timeout=60)
        if file_resp.status_code != 200:
            return None

        return MediaFile(data=file_resp.content, mime_type=file_resp.headers.get("Content-Type", "application/octet-stream"))
    except Exception:
        return None


# --- DingtalkChannel ---


class DingtalkChannel:
    """钉钉机器人适配器"""

    def __init__(self, client_id: str, client_secret: str,
                 message_handler: Optional[Callable[[Envelope], None]] = None,
                 logger: Optional[logging.Logger] = None):
        if not client_id or not client_secret:
            raise ValueError("需要提供 client_id 和 client_secret")

        self.client_id = client_id
        self.client_secret = client_secret
        self.message_handler = message_handler
        self.logger = logger or logging.getLogger('dingtalk_channel')

        # 停止信号
        self._stop_event = threading.Event()

        # Stream 客户端
        self.credential = Credential(client_id, client_secret)
        self.client = DingTalkStreamClient(self.credential, self.logger)

        # Webhook 缓存
        self.webhooks: Dict[str, str] = {}
        self.worker_pool = ThreadPoolExecutor(max_workers=4, thread_name_prefix="dingtalk-worker")

        # 注册回调处理器
        self.handler = DingtalkCallbackHandler(self)
        self.client.register_callback_handler(dingtalk_stream.ChatbotMessage.TOPIC, self.handler)

    def connect(self):
        """连接钉钉 Stream"""
        self.logger.info("[DingTalk] Connecting...")
        self._stop_event.clear()

        # 在后台线程启动 SDK
        self._thread = threading.Thread(target=self.client.start_forever, daemon=True)
        self._thread.start()

        # 等待停止信号
        while not self._stop_event.wait(0.5):
            pass

        # 关闭 websocket 让 SDK 循环退出
        self._close_websocket()
        self._thread.join(timeout=3)
        self._cleanup()

    def disconnect(self):
        """触发停止"""
        self._stop_event.set()

    def _close_websocket(self):
        """关闭 websocket 连接"""
        ws = getattr(self.client, 'websocket', None)
        if not ws:
            return

        try:
            loop = asyncio.new_event_loop()
            loop.run_until_complete(ws.close())
            loop.close()
        except Exception:
            pass

    def _cleanup(self):
        """清理资源"""
        self.worker_pool.shutdown(wait=False)

    def get_access_token(self) -> Optional[str]:
        return self.client.get_access_token()

    def send_message(self, chat_id: str, text: str) -> bool:
        webhook = self.webhooks.get(chat_id)
        if not webhook and chat_id.startswith("https://"):
            webhook = chat_id
        if not webhook:
            self.logger.error(f"[DingTalk] No webhook for {chat_id}")
            return False
        return send_markdown(webhook, text)

    def reply(self, envelope: Envelope, text: str) -> bool:
        webhook = envelope.session_webhook or self.webhooks.get(envelope.conversation_id or envelope.chat_id)
        if not webhook:
            self.logger.error(f"[DingTalk] No webhook for envelope")
            return False
        return send_markdown(webhook, text)

    def attach_reaction(self, msg_id: Optional[str], conversation_id: str):
        token = self.get_access_token()
        if token and msg_id and conversation_id:
            send_emotion(token, self.client_id, msg_id, conversation_id, "reply")

    def recall_reaction(self, msg_id: Optional[str], conversation_id: str):
        token = self.get_access_token()
        if token and msg_id and conversation_id:
            send_emotion(token, self.client_id, msg_id, conversation_id, "recall")

    def _extract_content(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """从钉钉消息提取内容和媒体信息"""
        msgtype = data.get('msgtype', 'text')
        content = data.get('content', {})
        text_data = data.get('text', {})

        # 媒体类型：用处理器映射
        handler = MSGTYPE_HANDLERS.get(msgtype)
        if handler:
            text, codes, media_type, file_name = handler(content)
            return {'text': text, 'download_codes': codes, 'media_type': media_type, 'file_name': file_name}

        # richText：特殊处理
        if msgtype == 'richText':
            rich_text = content.get('richText', [])
            text_parts = []
            codes = []
            for part in rich_text:
                if part.get('type') == 'text' and part.get('text'):
                    text_parts.append(part['text'])
                elif part.get('type') == 'picture' and part.get('downloadCode'):
                    codes.append(part['downloadCode'])
            return {
                'text': ''.join(text_parts).strip() or ('(image)' if codes else ''),
                'download_codes': codes,
                'media_type': 'image' if codes else None,
                'file_name': None
            }

        # 默认文本
        return {'text': text_data.get('content', '').strip(), 'download_codes': [], 'media_type': None, 'file_name': None}

    def _extract_quoted_context(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """提取引用消息上下文"""
        chatbot_user_id = data.get('chatbotUserId')
        text_data = data.get('text', {})

        # 统一处理新旧格式
        replied = None
        if text_data.get('isReplyMsg') and text_data.get('repliedMsg'):
            replied = text_data['repliedMsg']
            text_content = self._summarize_replied_content(replied)
        elif data.get('quoteMessage'):
            replied = data['quoteMessage']
            text_content = replied.get('text', {}).get('content', '').strip()
        else:
            return {'referenced_text': None, 'is_reply_to_bot': False}

        sender_id = replied.get('senderId')
        return {
            'referenced_text': text_content,
            'is_reply_to_bot': bool(chatbot_user_id and sender_id == chatbot_user_id)
        }

    def _summarize_replied_content(self, replied: Dict[str, Any]) -> Optional[str]:
        """总结回复消息内容"""
        content = replied.get('content', {})

        # 直接文本
        if content.get('text'):
            return content['text'].strip()

        # RichText
        if content.get('richText'):
            parts = []
            for part in content['richText']:
                ptype = part.get('type', 'text')
                if ptype == 'text' and part.get('text'):
                    parts.append(part['text'])
                elif ptype == 'picture':
                    parts.append('[image]')
                elif ptype == 'at' and part.get('atName'):
                    parts.append(f"@{part['atName']}")
            return ''.join(parts).strip() if parts else None

        # 媒体类型
        msg_type = replied.get('msgType')
        media_map = {'picture': '[image]', 'audio': '[audio]', 'video': '[video]'}
        if msg_type in media_map:
            return media_map[msg_type]
        if msg_type == 'file':
            return f"[file: {content.get('fileName', 'file')}]"

        return None

    def _attach_media(self, envelope: Envelope, download_code: str, media_type: str, file_name: Optional[str] = None):
        """下载媒体并附加到 envelope"""
        token = self.get_access_token()
        if not token:
            return

        media = download_media(download_code, self.client_id, token)
        if not media:
            return

        if media_type == 'image':
            mime = media.mime_type if media.mime_type.startswith('image/') else 'image/jpeg'
            envelope.attachments.append(Attachment(
                type='image',
                data=base64.b64encode(media.data).decode('ascii'),
                mime_type=mime
            ))
        else:
            dir_path = os.path.join(tempfile.gettempdir(), 'channel-files', str(uuid.uuid4()))
            os.makedirs(dir_path, exist_ok=True)
            safe_name = file_name or f"dingtalk_{media_type}_{int(time.time())}"
            file_path = os.path.join(dir_path, safe_name)

            with open(file_path, 'wb') as f:
                f.write(media.data)

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
        """处理接收到的消息"""
        try:
            msg_id = incoming_message.message_id
            conversation_type = incoming_message.conversation_type
            session_webhook = incoming_message.session_webhook
            conversation_id = incoming_message.conversation_id

            if not session_webhook:
                self.logger.warning("[DingTalk] No sessionWebhook, skipping.")
                return

            if conversation_id:
                self.webhooks[conversation_id] = session_webhook

            is_group = conversation_type == '2'
            is_mentioned = bool(incoming_message.is_in_at_list)

            content = self._extract_content(incoming_message.to_dict())
            clean_text = content['text']

            if is_mentioned:
                clean_text = re.sub(r'@\S+', '', clean_text).strip()

            quoted = self._extract_quoted_context(incoming_message.to_dict())
            chat_id = conversation_id or session_webhook

            envelope = Envelope(
                channel_name='dingtalk',
                sender_id=incoming_message.sender_staff_id or incoming_message.sender_id or '',
                sender_name=incoming_message.sender_nick or 'Unknown',
                chat_id=chat_id,
                conversation_id=conversation_id or '',
                session_webhook=session_webhook or '',
                text=clean_text or content['text'],
                is_group=is_group,
                is_mentioned=is_mentioned,
                is_reply_to_bot=quoted['is_reply_to_bot'],
                referenced_text=quoted['referenced_text'],
                message_id=msg_id
            )

            if content['download_codes'] and content['media_type']:
                self._attach_media(envelope, content['download_codes'][0], content['media_type'], content['file_name'])

            if self.message_handler:
                self.message_handler(envelope)
            else:
                self.logger.info(f"[DingTalk] Received: {envelope.text[:50]}...")

        except Exception as e:
            self.logger.error(f"[DingTalk] Process error: {e}")


class DingtalkCallbackHandler(ChatbotHandler):
    """回调处理器"""

    def __init__(self, channel: DingtalkChannel):
        super().__init__()
        self.channel = channel

    def process(self, callback_message: CallbackMessage):
        try:
            incoming_message = ChatbotMessage.from_dict(callback_message.data)
            self.channel.worker_pool.submit(self.channel.process_message, incoming_message)
            return AckMessage.STATUS_OK, "ok"
        except Exception as e:
            self.logger.error(f"[DingtalkCallbackHandler] Error: {e}")
            return AckMessage.STATUS_NOT_IMPLEMENT, str(e)


# --- CLI ---


def main():
    import argparse
    parser = argparse.ArgumentParser(description="钉钉机器人消息发送工具")
    parser.add_argument("-w", "--webhook", required=True, help="Webhook URL")
    parser.add_argument("-m", "--message", required=True, help="消息内容")
    parser.add_argument("-t", "--title", help="标题")
    parser.add_argument("--type", choices=["markdown", "text"], default="markdown")

    args = parser.parse_args()

    if args.type == "markdown":
        success = send_markdown(args.webhook, args.message, args.title)
    else:
        success = send_text_message(args.webhook, args.message)

    print(f"发送{'成功' if success else '失败'}")


if __name__ == "__main__":
    main()