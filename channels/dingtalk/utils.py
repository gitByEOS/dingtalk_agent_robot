#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
DingTalk API 工具函数

钉钉特有的 API 调用：
- send_emotion: 发送表情回复
- send_markdown: 发送 Markdown 消息
- send_text_message: 发送纯文本消息
"""

import json
import requests
from typing import Optional

from core.markdown import normalize_markdown, extract_title

# 表情 API 常量
EMOTION_API = "https://api.dingtalk.com/v1.0/robot/emotion"
ACK_REACTION_NAME = "get✓"
ACK_EMOTION_ID = "2659900"
ACK_EMOTION_BG_ID = "im_bg_2"


def send_emotion(
    access_token: str,
    robot_code: str,
    msg_id: str,
    conversation_id: str,
    action: str = "reply"
) -> bool:
    """发送表情回复"""
    if not access_token or not robot_code or not msg_id or not conversation_id:
        return False

    try:
        resp = requests.post(
            f"{EMOTION_API}/{action}",
            headers={
                "x-acs-dingtalk-access-token": access_token,
                "Content-Type": "application/json"
            },
            json={
                "robotCode": robot_code,
                "openMsgId": msg_id,
                "openConversationId": conversation_id,
                "emotionType": 2,
                "emotionName": ACK_REACTION_NAME,
                "textEmotion": {
                    "emotionId": ACK_EMOTION_ID,
                    "emotionName": ACK_REACTION_NAME,
                    "text": ACK_REACTION_NAME,
                    "backgroundId": ACK_EMOTION_BG_ID
                }
            },
            timeout=10
        )
        return resp.status_code == 200
    except Exception as e:
        print(f"[DingTalk] 表情API异常: {e}")
        return False


def send_markdown(webhook: str, text: str, title: Optional[str] = None) -> bool:
    """通过 Webhook 发送 Markdown 消息"""
    chunks = normalize_markdown(text)
    msg_title = title or extract_title(text)

    for i, chunk in enumerate(chunks):
        body = {
            "msgtype": "markdown",
            "markdown": {
                "title": f"{msg_title} (cont.)" if len(chunks) > 1 and i > 0 else msg_title,
                "text": chunk
            }
        }

        try:
            resp = requests.post(
                webhook,
                headers={"Content-Type": "application/json"},
                data=json.dumps(body),
                timeout=10
            )
            if resp.status_code != 200:
                print(f"[DingTalk] 发送失败: HTTP {resp.status_code} {resp.text}")
                return False
        except Exception as e:
            print(f"[DingTalk] 发送异常: {e}")
            return False

    return True


def send_text_message(webhook: str, text: str) -> bool:
    """通过 Webhook 发送纯文本消息"""
    body = {
        "msgtype": "text",
        "text": {"content": text}
    }

    try:
        resp = requests.post(
            webhook,
            headers={"Content-Type": "application/json"},
            data=json.dumps(body),
            timeout=10
        )
        return resp.status_code == 200
    except Exception as e:
        print(f"[DingTalk] 发送异常: {e}")
        return False