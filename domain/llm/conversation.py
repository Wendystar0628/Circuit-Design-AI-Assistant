# Conversation - Message Formatting Helpers
"""
对话格式化辅助 - 提供消息格式化、渲染辅助函数

职责：
- 格式化消息用于 UI 显示
- 格式化消息用于导出（markdown/json/text）
- 渲染操作摘要卡片
- 渲染联网搜索结果卡片
- 格式化深度思考内容用于折叠展示
- 格式化部分响应中断标记

注意：
- 消息的增删改查由 SessionStateManager 统一管理，本模块仅提供格式化功能
- 所有样式通过 CSS 类名定义，不使用内联样式（样式在 main.qss 中统一管理）

使用示例：
    from domain.llm.conversation import format_message_for_display
    
    html = format_message_for_display(message)
"""

import html
import re
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

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
    get_stop_reason,
    is_ai_message,
    get_web_search_results,
)
from domain.llm.message_types import Attachment

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
    
    # 助手消息：添加思考内容（如果有）
    if is_ai_message(message):
        reasoning = get_reasoning_content(message)
        if reasoning:
            reasoning_html = format_reasoning_content(reasoning)
            parts.append(reasoning_html)
    
    # 格式化主内容
    content_html = _format_content_html(content)
    parts.append(content_html)
    
    # 助手消息：添加部分响应标记（如果有）
    if is_ai_message(message) and is_partial_response(message):
        stop_reason = get_stop_reason(message)
        partial_html = format_partial_indicator(stop_reason)
        parts.append(partial_html)
    
    # 助手消息：添加联网搜索结果（如果有）
    if is_ai_message(message):
        web_results = get_web_search_results(message)
        if web_results:
            web_html = render_web_search_results(web_results)
            parts.append(web_html)
    
    # 助手消息：添加操作摘要（如果有）
    if is_ai_message(message):
        operations = get_operations(message)
        if operations:
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
    - 换行
    """
    if not content:
        return '<div class="message-content"></div>'
    
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
    lang_display = language.upper() if language else "CODE"
    lang_class = f' class="language-{language}"' if language else ''
    
    return f'''<div class="code-block">
<div class="code-block-header">{lang_display}</div>
<code{lang_class}>{code}</code>
</div>'''


def _format_attachments_html(attachments: List[Attachment]) -> str:
    """格式化附件列表"""
    items = []
    for att in attachments:
        att_type = att.type
        att_path = att.path
        att_name = html.escape(att.name or "未知文件")
        
        if att_type == "image":
            items.append(
                f'<div class="attachment-image">'
                f'<img src="{html.escape(att_path)}" alt="{att_name}">'
                f'</div>'
            )
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
        可折叠的 HTML 结构（使用 CSS 类名，不内联样式）
    """
    if not reasoning:
        return ""
    
    # 转义 HTML
    reasoning_escaped = html.escape(reasoning)
    
    # 处理换行
    reasoning_escaped = reasoning_escaped.replace('\n', '<br>')
    
    return f'''<details class="reasoning-container" open>
    <summary class="reasoning-header">
        <span class="reasoning-icon">💭</span>
        <span class="reasoning-title">思考过程</span>
    </summary>
    <div class="reasoning-content">
        {reasoning_escaped}
    </div>
</details>'''


def split_content_and_reasoning(response: Dict[str, Any]) -> Tuple[str, str]:
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


def format_partial_indicator(stop_reason: str = "") -> str:
    """
    格式化部分响应中断标记
    
    Args:
        stop_reason: 停止原因
        
    Returns:
        HTML 格式的中断标记
    """
    reason_text = {
        "user_requested": "用户中断",
        "timeout": "超时中断",
        "error": "错误中断",
        "session_switch": "会话切换",
        "app_shutdown": "应用关闭",
    }.get(stop_reason, "已中断")
    
    return f'''<div class="partial-indicator">
    <span class="partial-icon">⚠️</span>
    <span>{reason_text}</span>
</div>'''


# ============================================================
# 操作摘要渲染
# ============================================================

def render_operations_summary(operations: List[str]) -> str:
    """
    渲染操作摘要卡片
    
    Args:
        operations: 操作摘要列表
        
    Returns:
        HTML 格式的操作摘要卡片（使用 CSS 类名，不内联样式）
    """
    if not operations:
        return ""
    
    items_html = "\n".join(
        f'<li class="operation-item">{html.escape(op)}</li>'
        for op in operations
    )
    
    return f'''<div class="operations-card">
    <div class="operations-header">
        <span class="operations-icon">⚡</span>
        <span class="operations-title">执行的操作</span>
    </div>
    <ul class="operations-list">
        {items_html}
    </ul>
</div>'''


# ============================================================
# 联网搜索结果渲染
# ============================================================

def render_web_search_results(results: List[Dict[str, Any]]) -> str:
    """
    渲染联网搜索结果卡片
    
    Args:
        results: 搜索结果列表，每项包含 title, url, snippet
        
    Returns:
        HTML 格式的搜索结果卡片（使用 CSS 类名，不内联样式）
    """
    if not results:
        return ""
    
    items_html = []
    for result in results[:5]:  # 最多显示 5 条
        title = html.escape(result.get("title", "无标题"))
        url = html.escape(result.get("url", ""))
        snippet = html.escape(result.get("snippet", ""))
        
        items_html.append(f'''<li class="web-search-item">
    <a href="{url}" class="web-search-item-title" target="_blank">{title}</a>
    <div class="web-search-item-snippet">{snippet}</div>
    <div class="web-search-item-url">{url}</div>
</li>''')
    
    return f'''<div class="web-search-card">
    <div class="web-search-header">
        <span class="web-search-icon">🔍</span>
        <span class="web-search-title">联网搜索结果</span>
    </div>
    <ul class="web-search-list">
        {"".join(items_html)}
    </ul>
</div>'''



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
    lines.append(f"导出时间：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
    lines.append("---\n")
    
    for msg in messages:
        role = get_role(msg)
        timestamp = get_timestamp(msg)
        reasoning = get_reasoning_content(msg)
        operations = get_operations(msg)
        is_partial = is_partial_response(msg)
        content = msg.content if isinstance(msg.content, str) else ""
        
        # 角色标题
        role_name = {
            ROLE_USER: "👤 用户",
            ROLE_ASSISTANT: "🤖 助手",
            ROLE_SYSTEM: "⚙️ 系统",
        }.get(role, role)
        
        lines.append(f"## {role_name}")
        if timestamp:
            lines.append(f"*{_format_timestamp(timestamp)}*\n")
        
        # 思考内容
        if reasoning:
            lines.append("<details>")
            lines.append("<summary>💭 思考过程</summary>\n")
            lines.append(reasoning)
            lines.append("\n</details>\n")
        
        # 主内容
        lines.append(content)
        
        # 部分响应标记
        if is_partial:
            stop_reason = get_stop_reason(msg)
            lines.append(f"\n*[已中断: {stop_reason}]*")
        
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
    
    export_data = {
        "export_time": datetime.now().isoformat(),
        "message_count": len(messages),
        "messages": messages_to_dicts(messages),
    }
    
    return json.dumps(export_data, ensure_ascii=False, indent=2)


def _format_messages_text(messages: List[BaseMessage]) -> str:
    """导出为纯文本格式"""
    lines = []
    lines.append("=" * 50)
    lines.append("Conversation History")
    lines.append(f"Export time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    lines.append("=" * 50)
    lines.append("")
    
    for msg in messages:
        role = get_role(msg)
        timestamp = get_timestamp(msg)
        reasoning = get_reasoning_content(msg)
        operations = get_operations(msg)
        is_partial = is_partial_response(msg)
        content = msg.content if isinstance(msg.content, str) else ""
        
        role_name = {
            ROLE_USER: "用户",
            ROLE_ASSISTANT: "助手",
            ROLE_SYSTEM: "系统",
        }.get(role, role)
        
        time_str = _format_timestamp(timestamp) if timestamp else ""
        lines.append(f"[{role_name}] {time_str}")
        lines.append("-" * 30)
        
        if reasoning:
            lines.append("[思考过程]")
            lines.append(reasoning)
            lines.append("")
        
        lines.append(content)
        
        if is_partial:
            stop_reason = get_stop_reason(msg)
            lines.append(f"[已中断: {stop_reason}]")
        
        if operations:
            lines.append("[执行的操作]")
            for op in operations:
                lines.append(f"  - {op}")
        
        lines.append("")
        lines.append("")
    
    return "\n".join(lines)


def _format_timestamp(timestamp: str) -> str:
    """格式化 ISO 时间戳为可读格式"""
    if not timestamp:
        return ""
    try:
        dt = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
        return dt.strftime("%Y-%m-%d %H:%M:%S")
    except (ValueError, AttributeError):
        return timestamp



# ============================================================
# 流式内容处理
# ============================================================

class StreamingContentBuffer:
    """
    流式内容缓冲区
    
    用于累积流式响应中的思考内容和回答内容。
    
    使用示例：
        buffer = StreamingContentBuffer()
        
        # 流式接收思考内容
        buffer.append_reasoning("首先分析...")
        buffer.append_reasoning("然后考虑...")
        
        # 流式接收回答内容（自动标记思考阶段结束）
        buffer.append_content("根据分析，")
        buffer.append_content("建议使用...")
        
        # 获取累积内容
        reasoning = buffer.get_reasoning()
        content = buffer.get_content()
    """
    
    def __init__(self):
        self._reasoning_buffer: str = ""
        self._content_buffer: str = ""
        self._is_reasoning_phase: bool = True
    
    @property
    def reasoning_buffer(self) -> str:
        """获取思考内容缓冲区"""
        return self._reasoning_buffer
    
    @property
    def content_buffer(self) -> str:
        """获取回答内容缓冲区"""
        return self._content_buffer
    
    @property
    def is_reasoning_phase(self) -> bool:
        """是否在思考阶段"""
        return self._is_reasoning_phase
    
    def append_reasoning(self, text: str) -> None:
        """
        追加思考内容
        
        Args:
            text: 思考内容增量
        """
        if text:
            self._reasoning_buffer += text
    
    def append_content(self, text: str) -> None:
        """
        追加回答内容
        
        首次调用时自动标记思考阶段结束。
        
        Args:
            text: 回答内容增量
        """
        if text:
            if self._is_reasoning_phase:
                self._is_reasoning_phase = False
            self._content_buffer += text
    
    def get_reasoning(self) -> str:
        """获取累积的思考内容"""
        return self._reasoning_buffer
    
    def get_content(self) -> str:
        """获取累积的回答内容"""
        return self._content_buffer
    
    def get_formatted_reasoning(self) -> str:
        """
        获取格式化的思考内容 HTML
        
        Returns:
            格式化的 HTML，如果无思考内容则返回空字符串
        """
        if not self._reasoning_buffer:
            return ""
        return format_reasoning_content(self._reasoning_buffer)
    
    def get_formatted_content(self) -> str:
        """
        获取格式化的回答内容 HTML
        
        Returns:
            格式化的 HTML
        """
        return _format_content_html(self._content_buffer)
    
    def has_content(self) -> bool:
        """是否有任何内容（思考或回答）"""
        return bool(self._reasoning_buffer or self._content_buffer)
    
    def clear(self) -> None:
        """清空缓冲区"""
        self._reasoning_buffer = ""
        self._content_buffer = ""
        self._is_reasoning_phase = True


# ============================================================
# 模块导出
# ============================================================

__all__ = [
    # 消息显示
    "format_message_for_display",
    # 深度思考
    "format_reasoning_content",
    "split_content_and_reasoning",
    # 部分响应
    "format_partial_indicator",
    # 操作摘要
    "render_operations_summary",
    # 联网搜索
    "render_web_search_results",
    # 导出
    "format_messages_for_export",
    # 流式处理
    "StreamingContentBuffer",
]
