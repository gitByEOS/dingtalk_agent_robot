#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Markdown 格式化工具

可复用于其他 channel（飞书、企微等）
"""

import re
import unicodedata

CHUNK_LIMIT = 3800


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
    """渲染表格为代码块表格"""
    rows = [
        parse_table_row(line)
        for line in lines
        if parse_table_row(line) and not is_table_separator(line)
    ]
    if not rows:
        return ''

    column_count = max(len(row) for row in rows)
    normalized_rows = [row + [''] * (column_count - len(row)) for row in rows]
    column_widths = [
        max(get_display_width(row[col]) for row in normalized_rows)
        for col in range(column_count)
    ]

    rendered_lines = [build_table_line(normalized_rows[0], column_widths)]
    separator = "|-" + "-|-".join('-' * width for width in column_widths) + "-|"
    rendered_lines.append(separator)
    rendered_lines.extend(build_table_line(row, column_widths) for row in normalized_rows[1:])

    return "```text\n" + "\n".join(rendered_lines) + "\n```"


def convert_tables(text: str) -> str:
    """将 Markdown 表格转换为代码块表格"""
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
    """补齐 Markdown 显式换行"""
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


def normalize_markdown(text: str) -> list:
    """完整 Markdown 格式化流程"""
    converted = convert_tables(text)
    normalized = normalize_line_breaks(converted)
    return split_chunks(normalized)