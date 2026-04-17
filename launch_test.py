#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
DingTalk Channel 测试程序
"""

import os
import sys
import logging
from dotenv import load_dotenv

# 加载环境变量
load_dotenv('.env.dingtalk')

from dingtalk_channel import DingtalkChannel, Envelope

# 配置日志 - INFO 级别
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger('dingtalk_test')

# 设置 websockets 日志级别为 WARNING，减少调试输出
logging.getLogger('websockets.client').setLevel(logging.WARNING)
logging.getLogger('websockets').setLevel(logging.WARNING)
logging.getLogger('urllib3.connectionpool').setLevel(logging.WARNING)
logging.getLogger('asyncio').setLevel(logging.WARNING)


def message_handler(envelope: Envelope):
    """处理消息"""
    logger.info(f"收到消息:")
    logger.info(f"  发送者: {envelope.sender_name} ({envelope.sender_id})")
    logger.info(f"  会话: {envelope.chat_id}")
    logger.info(f"  内容: {envelope.text}")
    logger.info(f"  群聊: {envelope.is_group}")
    logger.info(f"  @我: {envelope.is_mentioned}")

    # 如果被 @ 或者私聊，回复消息
    if envelope.is_mentioned or not envelope.is_group:
        reply = f"你好 {envelope.sender_name}！\n\n收到你的消息：\n```\n{envelope.text}\n```\n\n这是一个自动回复测试。"
        logger.info(f"准备回复: {reply[:50]}...")

        # 发送回复
        success = channel.send_message(envelope.chat_id, reply)
        logger.info(f"发送结果: {'成功' if success else '失败'}")
    else:
        logger.info("群聊消息未被 @，不回复")


# 获取凭证
client_id = os.environ.get("DINGTALK_CLIENT_ID")
client_secret = os.environ.get("DINGTALK_CLIENT_SECRET")

if not client_id or not client_secret:
    logger.error("缺少 DINGTALK_CLIENT_ID 或 DINGTALK_CLIENT_SECRET")
    sys.exit(1)

logger.info(f"Client ID: {client_id}")

# 创建 channel
try:
    channel = DingtalkChannel(
        client_id=client_id,
        client_secret=client_secret,
        message_handler=message_handler,
        logger=logger
    )
    logger.info("DingtalkChannel 创建成功")
except Exception as e:
    logger.error(f"创建 DingtalkChannel 失败: {e}")
    sys.exit(1)

# 启动连接
logger.info("启动钉钉机器人...")
channel.connect()
logger.info("服务已停止")