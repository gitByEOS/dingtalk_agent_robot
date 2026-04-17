#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
启动器 - 运行钉钉 Stream 服务
"""

import os
import sys
import signal
import logging
import argparse
from dotenv import load_dotenv

# 在导入其他模块前，优先加载环境变量和配置日志
load_dotenv('.env.dingtalk')

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logging.getLogger('websockets').setLevel(logging.WARNING)
logging.getLogger('urllib3').setLevel(logging.WARNING)

logger = logging.getLogger('launch')

from dingtalk_service import DingTalkService

def main():
    parser = argparse.ArgumentParser(description="钉钉 Stream 服务")
    parser.add_argument("--client-id", default=os.environ.get("DINGTALK_CLIENT_ID"), help="钉钉 AppKey")
    parser.add_argument("--client-secret", default=os.environ.get("DINGTALK_CLIENT_SECRET"), help="钉钉 AppSecret")
    parser.add_argument("--agent", default="agent.py", help="Agent 脚本路径")

    args = parser.parse_args()

    if not args.client_id or not args.client_secret:
        print("错误: 需要提供 --client-id 和 --client-secret，或设置环境变量")
        sys.exit(1)

    logger.info(f"启动服务, Client ID: {args.client_id}")

    service = DingTalkService(
        client_id=args.client_id,
        client_secret=args.client_secret,
        agent_script=args.agent
    )

    # 信号处理 - 优雅退出
    def signal_handler(sig, frame):
        logger.info("[DingTalk] 收到中断信号，正在停止...")
        service.disconnect()
        sys.exit(0)

    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    # 运行服务
    service.connect()


if __name__ == "__main__":
    main()
