# Conversation - Message Formatting Helpers
"""
对话格式化辅助 - 提供消息格式化、渲染辅助函数

职责：
- 格式化消息用于 UI 显示
- 格式化消息用于导出
- 渲染操作摘要卡片
- 格式化深度思考内容

注意：消息的增删改查由 ContextManager 统一管理，本模块仅提供格式化功能。

使用示例：
    from domain.llm.conversation import format_message_for_display
    
    html = format_message_for_display(message)
"""

import html
import re
from datetime import datetime
from typing import Any, Dict, List, Optional, Union

from langchain_core.messages import BaseMessage

from domain.llm.message_helpers import (
    ROLE_USER,
    ROLE_ASSISTANT,
    ROLE_SYSTEM,
    get_role,
    get_reasoning_content,
    get_operations,
    get_attachments,
    get_timestamp,
    is_partial_response,
    is_ai_message,
)



# ============================================================
# 消息显示格式化
# ============================================================

def format_message_for_display(message: BaseMessage) -> str:
    """
    格式化消息用于 UI 显示
    
    Args:
        message: LangChain 消息对象
        
    Returns:
        HTML 格式的消息内容
    """
    parts = []
    
    # 获取内容
    content = message.content if isinstance(message.content, str) else ""
    
    # 格式化主内容
    content_html = _format_content_html(content)
    parts.append(content_html)
    
    # 助手消息：添加思考内容（如果有）
    reasoning = get_reasoning_content(message)
    if is_ai_message(message) and reasoning:
        reasoning_html = format_reasoning_content(reasoning)
        parts.insert(0, reasoning_html)  # 思考内容放在前面
    
    # 助手消息：添加操作摘要（如果有）
    operations = get_operations(message)
    if is_ai_message(message) and operations:
        operations_html = render_operations_summary(operations)
        parts.append(operations_html)
    
    # 添加附件（如果有）
    attachments = get_attachments(message)
    if attachments:
        attachments_html = _format_attachments_html(attachments)
        parts.append(attachments_html)
    
    return "\n".join(parts)


def _format_content_html(content: str) -> str:
    """
    格式化文本内容为 HTML
    
    支持：
    - 代码块高亮
    - 行内代码
    - 链接
    - 换行
    """
    # 转义 HTML 特殊字符
    content = html.escape(content)
    
    # 处理代码块 ```...```
    content = re.sub(
        r'```(\w*)\n(.*?)```',
        lambda m: _format_code_block(m.group(2), m.group(1)),
        content,
        flags=re.DOTALL
    )
    
    # 处理行内代码 `...`
    content = re.sub(
        r'`([^`]+)`',
        r'<code class="inline-code">\1</code>',
        content
    )
    
    # 处理换行
    content = content.replace('\n', '<br>')
    
    return f'<div class="message-content">{content}</div>'


def _format_code_block(code: str, language: str = "") -> str:
    """格式化代码块"""
    lang_class = f' class="language-{language}"' if language else ''
    return f'<pre><code{lang_class}>{code}</code></pre>'


def _format_attachments_html(attachments: List[Dict[str, Any]]) -> str:
    """格式化附件列表"""
    items = []
    for att in attachments:
        att_type = att.get("type", "file")
        att_path = att.get("path", "")
        att_name = att.get("name", "未知文件")
        if att_type == "image":
            items.append(f'<div class="attachment-image"><img src="{att_path}" alt="{att_name}"></div>')
        else:
            items.append(f'<div class="attachment-file">📎 {att_name}</div>')
    
    return f'<div class="attachments">{"".join(items)}</div>'



# ============================================================
# 深度思考内容处理
# ============================================================

def format_reasoning_content(reasoning: str) -> str:
    """
    格式化深度思考内容用于折叠展示
    
    Args:
        reasoning: 思考内容文本
        
    Returns:
        可折叠的 HTML 结构
    """
    if not reasoning:
        return ""
    
    # 转义 HTML
    reasoning_escaped = html.escape(reasoning)
    
    # 处理换行
    reasoning_escaped = reasoning_escaped.replace('\n', '<br>')
    
    return f'''
<details class="reasoning-container" open>
    <summary class="reasoning-header">
        <span class="reasoning-icon">💭</span>
        <span class="reasoning-title">思考过程</span>
    </summary>
    <div class="reasoning-content">
        {reasoning_escaped}
    </div>
</details>
<style>
.reasoning-container {{
    background-color: #f5f5f5;
    border-radius: 8px;
    padding: 12px;
    margin-bottom: 12px;
    font-size: 0.9em;
}}
.reasoning-header {{
    cursor: pointer;
    font-weight: 500;
    color: #666;
}}
.reasoning-icon {{
    margin-right: 6px;
}}
.reasoning-content {{
    margin-top: 8px;
    padding-top: 8px;
    border-top: 1px solid #e0e0e0;
    color: #555;
    line-height: 1.6;
}}
</style>
'''


def split_content_and_reasoning(response: Dict[str, Any]) -> tuple:
    """
    分离最终回答与思考过程
    
    Args:
        response: LLM 响应字典
        
    Returns:
        (content, reasoning_content) 元组
    """
    content = response.get("content", "")
    reasoning_content = response.get("reasoning_content", "")
    
    return content, reasoning_content


# ============================================================
# 操作摘要渲染
# ============================================================

def render_operations_summary(operations: List[str]) -> str:
    """
    渲染操作摘要卡片
    
    Args:
        operations: 操作摘要列表
        
    Returns:
        HTML 格式的操作摘要卡片
    """
    if not operations:
        return ""
    
    items_html = "\n".join(
        f'<li class="operation-item">{html.escape(op)}</li>'
        for op in operations
    )
    
    return f'''
<div class="operations-card">
    <div class="operations-header">
        <span class="operations-icon">⚡</span>
        <span class="operations-title">执行的操作</span>
    </div>
    <ul class="operations-list">
        {items_html}
    </ul>
</div>
<style>
.operations-card {{
    background-color: #e3f2fd;
    border-radius: 8px;
    padding: 12px;
    margin-top: 12px;
}}
.operations-header {{
    font-weight: 500;
    color: #1976d2;
    margin-bottom: 8px;
}}
.operations-icon {{
    margin-right: 6px;
}}
.operations-list {{
    margin: 0;
    padding-left: 20px;
    color: #333;
}}
.operation-item {{
    margin: 4px 0;
}}
</style>
'''



# ============================================================
# 消息导出格式化
# ============================================================

def format_messages_for_export(
    messages: List[BaseMessage],
    format: str = "markdown"
) -> str:
    """
    格式化消息用于导出
    
    Args:
        messages: LangChain 消息列表
        format: 导出格式 ("markdown" | "json" | "text")
        
    Returns:
        格式化后的字符串
    """
    if format == "markdown":
        return _format_messages_markdown(messages)
    elif format == "json":
        return _format_messages_json(messages)
    else:
        return _format_messages_text(messages)


def _format_messages_markdown(messages: List[BaseMessage]) -> str:
    """导出为 Markdown 格式"""
    lines = ["# 对话记录\n"]
    
    for msg in messages:
        role = get_role(msg)
        timestamp = get_timestamp(msg)
        reasoning = get_reasoning_content(msg)
        operations = get_operations(msg)
        content = msg.content if isinstance(msg.content, str) else ""
        
        # 角色标题
        role_name = {
            ROLE_USER: "👤 用户",
            ROLE_ASSISTANT: "🤖 助手",
            ROLE_SYSTEM: "⚙️ 系统",
        }.get(role, role)
        
        lines.append(f"## {role_name}")
        lines.append(f"*{timestamp}*\n")
        
        # 思考内容
        if reasoning:
            lines.append("<details>")
            lines.append("<summary>💭 思考过程</summary>\n")
            lines.append(reasoning)
            lines.append("</details>\n")
        
        # 主内容
        lines.append(content)
        
        # 操作摘要
        if operations:
            lines.append("\n**执行的操作：**")
            for op in operations:
                lines.append(f"- {op}")
        
        lines.append("\n---\n")
    
    return "\n".join(lines)


def _format_messages_json(messages: List[BaseMessage]) -> str:
    """导出为 JSON 格式"""
    import json
    from domain.llm.message_helpers import messages_to_dicts
    return json.dumps(
        messages_to_dicts(messages),
        ensure_ascii=False,
        indent=2
    )


def _format_messages_text(messages: List[BaseMessage]) -> str:
    """导出为纯文本格式"""
    lines = []
    
    for msg in messages:
        role = get_role(msg)
        timestamp = get_timestamp(msg)
        reasoning = get_reasoning_content(msg)
        operations = get_operations(msg)
        content = msg.content if isinstance(msg.content, str) else ""
        
        role_name = {
            ROLE_USER: "用户",
            ROLE_ASSISTANT: "助手",
            ROLE_SYSTEM: "系统",
        }.get(role, role)
        
        lines.append(f"[{role_name}] ({timestamp})")
        
        if reasoning:
            lines.append(f"[思考] {reasoning}")
        
        lines.append(content)
        
        if operations:
            lines.append("[操作] " + ", ".join(operations))
        
        lines.append("")
    
    return "\n".join(lines)


# ============================================================
# 流式内容处理
# ============================================================

class StreamingContentBuffer:
    """
    流式内容缓冲区
    
    用于累积流式响应中的思考内容和回答内容。
    """
    
    def __init__(self):
        self.reasoning_buffer = ""
        self.content_buffer = ""
        self.is_reasoning_phase = True
    
    def append_reasoning(self, text: str) -> None:
        """追加思考内容"""
        self.reasoning_buffer += text
    
    def append_content(self, text: str) -> None:
        """追加回答内容"""
        if self.is_reasoning_phase:
            self.is_reasoning_phase = False
        self.content_buffer += text
    
    def get_reasoning(self) -> str:
        """获取累积的思考内容"""
        return self.reasoning_buffer
    
    def get_content(self) -> str:
        """获取累积的回答内容"""
        return self.content_buffer
    
    def clear(self) -> None:
        """清空缓冲区"""
        self.reasoning_buffer = ""
        self.content_buffer = ""
        self.is_reasoning_phase = True


# ============================================================
# 模块导出
# ============================================================

__all__ = [
    # 消息显示
    "format_message_for_display",
    # 深度思考
    "format_reasoning_content",
    "split_content_and_reasoning",
    # 操作摘要
    "render_operations_summary",
    # 导出
    "format_messages_for_export",
    # 流式处理
    "StreamingContentBuffer",
]
