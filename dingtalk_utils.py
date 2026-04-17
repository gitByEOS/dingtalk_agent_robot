#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
DingTalk 工具函数

包含：
- send_emotion: 发送表情回复
- send_markdown: 发送 Markdown 消息
- send_text_message: 发送纯文本消息
- normalize_dingtalk_markdown: 完整 Markdown 格式化流程
- split_chunks: 消息分块
- convert_tables: 表格转换
- extract_title: 提取标题
"""

import json
import re
import requests
import unicodedata
from typing import Optional, List

# 表情 API 常量
EMOTION_API = "https://api.dingtalk.com/v1.0/robot/emotion"
ACK_REACTION_NAME = "get✓" #👀
ACK_EMOTION_ID = "2659900"
ACK_EMOTION_BG_ID = "im_bg_2"

# 消息限制
CHUNK_LIMIT = 3800


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


def is_table_separator(line: str) -> bool:
    """判断是否是表格分隔行"""
    trimmed = line.strip()
    if not trimmed or '-' not in trimmed:
        return False
    cells = trimmed.lstrip('|').rstrip('|').split('|')
    cells = [c.strip() for c in cells]
    return len(cells) > 0 and all(re.match(r'^:?-{3,}:?$', c) for c in cells)


def is_table_row(line: str) -> bool:
    """判断是否是表格行"""
    trimmed = line.strip()
    return '|' in trimmed and not trimmed.startswith('```')


def parse_table_row(line: str) -> list:
    """解析表格行"""
    return [c.strip() for c in line.strip().lstrip('|').rstrip('|').split('|')]


def get_display_width(text: str) -> int:
    """计算字符串显示宽度，兼容中文对齐"""
    width = 0
    for char in text:
        width += 2 if unicodedata.east_asian_width(char) in ('W', 'F') else 1
    return width


def pad_table_cell(text: str, target_width: int) -> str:
    """按显示宽度补齐表格单元格"""
    padding = max(target_width - get_display_width(text), 0)
    return text + (' ' * padding)


def build_table_line(cells: list, widths: list) -> str:
    """构造单行对齐后的表格文本"""
    normalized_cells = cells + [''] * (len(widths) - len(cells))
    padded_cells = [
        pad_table_cell(cell, width)
        for cell, width in zip(normalized_cells, widths)
    ]
    return f"| {' | '.join(padded_cells)} |"


def render_table(lines: list) -> str:
    """渲染表格为钉钉可稳定显示的代码块表格"""
    rows = [
        parse_table_row(line)
        for line in lines
        if parse_table_row(line) and not is_table_separator(line)
    ]
    if not rows:
        return ''

    column_count = max(len(row) for row in rows)
    normalized_rows = [
        row + [''] * (column_count - len(row))
        for row in rows
    ]
    column_widths = [
        max(get_display_width(row[col]) for row in normalized_rows)
        for col in range(column_count)
    ]

    rendered_lines = [build_table_line(normalized_rows[0], column_widths)]
    separator = "|-" + "-|-".join('-' * width for width in column_widths) + "-|"
    rendered_lines.append(separator)
    rendered_lines.extend(
        build_table_line(row, column_widths)
        for row in normalized_rows[1:]
    )

    return "```text\n" + "\n".join(rendered_lines) + "\n```"


def convert_tables(text: str) -> str:
    """将 Markdown 表格转换为钉钉支持的格式"""
    lines = text.split('\n')
    output = []
    i = 0
    in_code = False

    while i < len(lines):
        line = lines[i] or ''
        if line.strip().startswith('```'):
            in_code = not in_code
            output.append(line)
            i += 1
            continue

        if not in_code and i + 1 < len(lines) and is_table_row(line) and is_table_separator(lines[i + 1] or ''):
            table_lines = [line]
            i += 2
            while i < len(lines) and is_table_row(lines[i] or ''):
                table_lines.append(lines[i] or '')
                i += 1
            output.append(render_table(table_lines))
            continue

        output.append(line)
        i += 1

    return '\n'.join(output)


def split_chunks(text: str) -> list:
    """将长消息分块，处理代码块闭合"""
    if not text or len(text) <= CHUNK_LIMIT:
        return [text]

    chunks = []
    buf = ''
    lines = text.split('\n')
    in_code = False

    for line in lines:
        fence_count = len(re.findall(r'```', line))

        if len(buf) + len(line) + 1 > CHUNK_LIMIT and buf:
            if in_code:
                buf += '\n```'
            chunks.append(buf)
            buf = '```\n' if in_code else ''

        buf += ('\n' if buf else '') + line

        if fence_count % 2 == 1:
            in_code = not in_code

    if buf:
        chunks.append(buf)

    return chunks


def extract_title(text: str) -> str:
    """从 Markdown 提取短标题"""
    first_line = text.split('\n')[0] or ''
    cleaned = re.sub(r'^(?:[#*\s\->]+|\d+\.\s+)', '', first_line)[:20]
    return cleaned or 'Reply'


def is_markdown_block_line(line: str) -> bool:
    """判断是否是 Markdown 块级语法行"""
    stripped = line.strip()
    if not stripped:
        return False
    return bool(re.match(r'^(#{1,6}\s+|[-*+]\s+|\d+\.\s+|>\s*|```)', stripped))


def normalize_line_breaks(text: str) -> str:
    """补齐钉钉 Markdown 的显式换行"""
    lines = text.split('\n')
    output = []
    in_code = False

    for index, line in enumerate(lines):
        stripped = line.strip()
        if stripped.startswith('```'):
            in_code = not in_code
            output.append(line)
            continue

        if in_code or not stripped:
            output.append(line)
            continue

        next_line = lines[index + 1] if index + 1 < len(lines) else ''
        next_stripped = next_line.strip()
        should_keep_break = (
            next_stripped
            and not is_markdown_block_line(line)
            and not is_markdown_block_line(next_line)
        )
        output.append(f"{line}  " if should_keep_break else line)

    return '\n'.join(output)


def normalize_dingtalk_markdown(text: str) -> list:
    """完整 Markdown 格式化流程"""
    converted = convert_tables(text)
    normalized = normalize_line_breaks(converted)
    return split_chunks(normalized)


def send_markdown(webhook: str, text: str, title: Optional[str] = None) -> bool:
    """通过 Webhook 发送 Markdown 消息"""
    chunks = normalize_dingtalk_markdown(text)
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