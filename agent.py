#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""简单 Agent CLI - 只加载 .claude/rules 和 skills 作为系统提示词"""

import argparse
import os
import re
import subprocess
from pathlib import Path
from anthropic import Anthropic

# 默认配置
DEFAULT_API_KEY = "ollama"
DEFAULT_BASE_URL = "http://localhost:11434"
DEFAULT_MODEL = "MiniMax-M2.5"
DEFAULT_MAX_TOKENS = 4096

# 工作目录限制
ALLOWED_DIR = os.path.abspath(os.getcwd())

# Skill 脚本白名单路径（动态加载）
SKILL_SCRIPT_PATHS = []

# 危险命令黑名单
FORBIDDEN_CMDS = {
    'rm', 'mv', 'sudo', 'su', 'chmod', 'chown',
    'wget', 'curl', 'reboot', 'shutdown', 'halt',
    'mkfs', 'fdisk', 'mount', 'umount', 'dd',
    'kill', 'pkill', 'killall', 'ln'
}

def is_safe_command(command: str) -> tuple[bool, str]:
    """检查命令是否安全，限制危险操作和目录访问"""
    # 1. 检查是否试图目录穿越或使用家目录
    if '..' in command or '~' in command:
        return False, "禁止使用 '..' 或 '~' 进行路径穿越或越权访问"

    # 2. 阻止通过常见的环境变量绕过
    if re.search(r'\$[{]?(HOME|USER|PWD|OLDPWD|ROOT)\b', command, re.IGNORECASE):
        return False, "安全拦截: 禁止使用 $HOME 等环境变量绕过目录限制"

    # 3. 检查违禁词 (匹配独立的命令单词)
    for cmd in FORBIDDEN_CMDS:
        if re.search(rf'\b{cmd}\b', command):
            return False, f"安全拦截: 禁止使用危险命令 '{cmd}'"

    # 4. 检查绝对路径访问
    # 常见的系统级目录前缀，如果在命令中出现这些绝对路径，大概率是越权
    SYSTEM_DIRS = (
        '/etc', '/var', '/usr', '/bin', '/sbin', '/opt', '/root', '/tmp',
        '/Users', '/home', '/Library', '/System', '/private', '/Volumes',
        '/dev', '/proc', '/sys', '/boot', '/mnt', '/media', '/run'
    )

    # 查找所有可能以 / 开头的路径 (前置字符可能为空格、等号、引号、重定向等)
    paths = re.findall(r"(?:^|[\s:=<>|&\'\"])(/[\w/.-]+)", command)
    for p in paths:
        # 如果路径在白名单中，允许访问
        if any(p.startswith(script_path) for script_path in SKILL_SCRIPT_PATHS):
            continue
        # 如果路径不是以 ALLOWED_DIR 开头
        if not p.startswith(ALLOWED_DIR):
            # 进一步启发式判断：如果是常见系统路径或磁盘上真实存在的路径，则拦截
            # 这样可以避免误伤类似 awk '/pattern/' 这样的正则参数
            if p.startswith(SYSTEM_DIRS) or os.path.exists(p):
                return False, f"安全拦截: 禁止访问工作目录外的绝对路径 '{p}'"

    # 5. 阻止直接切换到根目录或非法的 cd 操作
    if re.search(r'\bcd\s+/', command):
        return False, "安全拦截: 禁止 cd 到绝对路径"

    return True, ""

# Bash 工具定义
BASH_TOOL = {
    "name": "bash",
    "description": "执行 bash 命令并返回结果",
    "input_schema": {
        "type": "object",
        "properties": {
            "command": {
                "type": "string",
                "description": "要执行的 bash 命令"
            }
        },
        "required": ["command"]
    }
}


def strip_yaml_frontmatter(content: str) -> str:
    """去除 YAML frontmatter"""
    pattern = r'^---\s*\n.*?\n---\s*\n+'
    return re.sub(pattern, '', content, flags=re.DOTALL).strip()


def load_rules(rules_dir: Path) -> list:
    """加载所有 .mdc 规则文件"""
    rules = []
    if not rules_dir.exists():
        return rules
    for f in sorted(rules_dir.glob("*.mdc")):
        if f.name.startswith('.'):
            continue
        content = f.read_text(encoding='utf-8')
        rules.append((f.stem, strip_yaml_frontmatter(content)))
    return rules


def load_skills(skills_dir: Path) -> list:
    """加载所有 SKILL.md 技能文件，并注入脚本路径"""
    global SKILL_SCRIPT_PATHS
    skills = []
    if not skills_dir.exists():
        return skills
    for d in sorted(skills_dir.iterdir()):
        if not d.is_dir() or d.name.startswith('.'):
            continue
        skill_file = d / "SKILL.md"
        if skill_file.exists():
            content = skill_file.read_text(encoding='utf-8')
            content = strip_yaml_frontmatter(content)

            # 检查 scripts 目录，注入脚本实际路径
            scripts_dir = d / "scripts"
            if scripts_dir.exists():
                scripts_info = []
                for script in scripts_dir.glob("*.py"):
                    script_path = str(script)
                    scripts_info.append(f"  - {script.name}: {script_path}")
                    # 添加到白名单
                    SKILL_SCRIPT_PATHS.append(script_path)
                if scripts_info:
                    content += f"\n\n## 脚本路径\n本技能的脚本位于:\n" + "\n".join(scripts_info)

            skills.append((d.name, content))
    return skills


def build_system_prompt(rules_dir: Path, skills_dir: Path) -> str:
    """组合系统提示词"""
    parts = []
    parts.append("你是一个Losta项目组的Agent，能帮你处理一些简单的任务。")

    rules = load_rules(rules_dir)
    skills = load_skills(skills_dir)

    if rules:
        parts.append("# Rules\n")
        for name, content in rules:
            parts.append(f"## {name}\n\n{content}\n")

    if skills:
        parts.append("# Skills\n")
        for name, content in skills:
            parts.append(f"## {name}\n\n{content}\n")

    return "\n".join(parts).strip()


def run_bash_command(command: str) -> str:
    """执行 bash 命令并返回结果"""
    safe, reason = is_safe_command(command)
    if not safe:
        return reason

    try:
        result = subprocess.run(
            command,
            shell=True,
            capture_output=True,
            text=True,
            timeout=60,
            cwd=ALLOWED_DIR,
            env=os.environ.copy()
        )
        if result.returncode != 0:
            return f"错误: {result.stderr}"
        return result.stdout.strip()
    except subprocess.TimeoutExpired:
        return "错误: 命令执行超时"
    except Exception as e:
        return f"错误: {str(e)}"


def extract_text_from_response(resp) -> str:
    """从响应中提取文本"""
    for block in resp.content:
        if hasattr(block, 'text'):
            return block.text
    return ""


def extract_tool_use(resp) -> dict | None:
    """从响应中提取 tool_use block"""
    for block in resp.content:
        if block.type == "tool_use":
            return {
                "id": block.id,
                "name": block.name,
                "input": block.input
            }
    return None


def chat_with_tools(client: Anthropic, model: str, system_prompt: str, message: str, max_tokens: int) -> str:
    """带工具调用能力的对话"""
    messages = [{"role": "user", "content": message}]

    while True:
        resp = client.messages.create(
            model=model,
            max_tokens=max_tokens,
            system=system_prompt,
            messages=messages,
            tools=[BASH_TOOL],
        )

        # 检查是否有 tool_use
        tool_use = extract_tool_use(resp)

        if tool_use and tool_use["name"] == "bash":
            # 执行命令
            command = tool_use["input"]["command"]
            result = run_bash_command(command)

            # 添加 assistant 响应和 tool_result
            messages.append({"role": "assistant", "content": resp.content})
            messages.append({
                "role": "user",
                "content": [{
                    "type": "tool_result",
                    "tool_use_id": tool_use["id"],
                    "content": result
                }]
            })
            # 继循环
            continue

        # 没有 tool_use，返回最终文本
        return extract_text_from_response(resp)


def main():
    parser = argparse.ArgumentParser(description="简单 Agent CLI")
    parser.add_argument("-i", "--input", required=True, help="输入消息")
    parser.add_argument("--model", default=DEFAULT_MODEL, help="模型名称")
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL, help="API 基础 URL")
    parser.add_argument("--max-tokens", type=int, default=DEFAULT_MAX_TOKENS, help="最大 token 数")
    args = parser.parse_args()

    system_prompt = build_system_prompt(
        Path(".claude/rules"),
        Path(".claude/skills")
    )

    client = Anthropic(api_key=DEFAULT_API_KEY, base_url=args.base_url)

    result = chat_with_tools(client, args.model, system_prompt, args.input, args.max_tokens)
    print(result)


if __name__ == "__main__":
    main()