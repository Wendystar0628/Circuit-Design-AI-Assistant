# Web-based Message View Component
"""
基于 WebEngine 的消息显示组件

使用单个 QWebEngineView 渲染所有消息，支持 Markdown 和 LaTeX。

功能特性：
- Markdown 渲染（标题、列表、代码块、表格等）
- LaTeX 公式渲染（行内 $...$ 和块级 $$...$$）
- 深度思考内容折叠
- 操作摘要卡片（显示 AI 执行的操作）
- 附件预览（图片、文件）
- 文件路径点击处理
- 流式输出支持
"""

from typing import Any, Dict, List, Optional
from PyQt6.QtCore import Qt, pyqtSignal, pyqtSlot, QTimer, QUrl

try:
    from PyQt6.QtWebEngineWidgets import QWebEngineView
    from PyQt6.QtWebEngineCore import QWebEngineSettings
    from PyQt6.QtWebChannel import QWebChannel
    WEBENGINE_AVAILABLE = True
except ImportError:
    WEBENGINE_AVAILABLE = False

from PyQt6.QtWidgets import QWidget, QVBoxLayout, QSizePolicy, QLabel


class WebMessageView(QWidget):
    """
    基于 WebEngine 的消息显示组件
    
    整合了原 MessageBubble 的所有功能：
    - 消息渲染（用户/助手/系统）
    - 深度思考折叠
    - 操作摘要卡片
    - 附件预览
    - 文件/链接点击处理
    """
    
    # 信号定义
    link_clicked = pyqtSignal(str)      # 链接点击 (url)
    file_clicked = pyqtSignal(str)      # 文件点击 (file_path)
    
    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self._web_view = None
        self._web_channel = None
        self._is_streaming = False
        self._stream_content = ""
        self._messages = []
        self._page_loaded = False
        self._pending_messages = []  # 等待页面加载完成后渲染的消息
        self._is_rendering = False   # 防止重复渲染
        self._stream_timer = QTimer(self)
        self._stream_timer.setInterval(50)
        self._stream_timer.timeout.connect(self._flush_stream)
        self._pending_update = False
        self._setup_ui()
    
    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        
        if WEBENGINE_AVAILABLE:
            self._web_view = QWebEngineView()
            self._web_view.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
            settings = self._web_view.settings()
            settings.setAttribute(QWebEngineSettings.WebAttribute.JavascriptEnabled, True)
            # 设置 WebChannel 用于 JS 与 Python 通信
            self._setup_web_channel()
            # 拦截导航请求处理文件/链接点击
            self._web_view.page().acceptNavigationRequest = self._handle_navigation
            self._web_view.loadFinished.connect(self._on_page_loaded)
            self._load_initial_page()
            layout.addWidget(self._web_view)
        else:
            label = QLabel("请安装 PyQt6-WebEngine")
            label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            layout.addWidget(label)
    
    def _setup_web_channel(self):
        """设置 WebChannel 用于 JS 调用 Python"""
        if not WEBENGINE_AVAILABLE or not self._web_view:
            return
        try:
            self._web_channel = QWebChannel()
            self._web_channel.registerObject("pyBridge", self)
            self._web_view.page().setWebChannel(self._web_channel)
        except Exception:
            pass  # WebChannel 可选，失败不影响基本功能
    
    def _handle_navigation(self, url, nav_type, is_main_frame):
        """处理导航请求，拦截文件和外部链接"""
        url_str = url.toString()
        # 允许 about:blank 和 data: URL
        if url_str.startswith(('about:', 'data:')):
            return True
        # 处理文件链接
        if url_str.startswith('file://'):
            file_path = url_str[7:]
            self.file_clicked.emit(file_path)
            return False
        # 处理外部链接
        if url_str.startswith(('http://', 'https://')):
            self.link_clicked.emit(url_str)
            return False
        return True
    
    @pyqtSlot(str)
    def handleFileClick(self, path: str):
        """处理 JS 调用的文件点击"""
        self.file_clicked.emit(path)
    
    @pyqtSlot(str)
    def handleLinkClick(self, url: str):
        """处理 JS 调用的链接点击"""
        self.link_clicked.emit(url)
    
    def _on_page_loaded(self, ok):
        self._page_loaded = ok
        # 只在有待渲染消息且不在渲染中时才渲染
        if ok and self._pending_messages and not self._is_rendering:
            self._do_render(self._pending_messages)
            self._pending_messages = []
    
    def _load_initial_page(self):
        html = self._build_html("")
        self._web_view.setHtml(html)

    def _build_html(self, content: str) -> str:
        """构建完整 HTML 页面"""
        css, js, auto_js = self._load_katex()
        return f'''<!DOCTYPE html>
<html><head><meta charset="UTF-8">
<style>{css}</style>
<style>{self._get_styles()}</style>
</head><body>
<div id="msgs">{content}</div>
<script>{js}</script>
<script>{auto_js}</script>
<script>{self._get_scripts()}</script>
</body></html>'''
    
    def _load_katex(self):
        try:
            from infrastructure.utils.markdown_renderer import _load_katex_resources
            return _load_katex_resources()
        except:
            return ("", "", "")

    def _get_styles(self) -> str:
        return '''
* { margin: 0; padding: 0; box-sizing: border-box; }
body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Arial, sans-serif;
       font-size: 14px; line-height: 1.6; color: #333; background: #fff; padding: 12px; }
#msgs { display: flex; flex-direction: column; gap: 12px; }
.msg { max-width: 85%; padding: 12px 16px; border-radius: 12px; word-wrap: break-word; }
.msg.user { align-self: flex-end; background: #e3f2fd; }
.msg.assistant { align-self: flex-start; background: #f8f9fa; }
.msg.system { align-self: center; background: transparent; color: #6c757d; font-size: 12px; }
.msg.streaming::after { content: "▌"; color: #4a9eff; animation: blink 1s infinite; }
@keyframes blink { 0%,50% { opacity: 1; } 51%,100% { opacity: 0; } }
.row { display: flex; gap: 8px; align-items: flex-start; }
.row.user { flex-direction: row-reverse; }
.avatar { width: 32px; height: 32px; border-radius: 50%; display: flex; 
          align-items: center; justify-content: center; font-size: 18px; background: #e8f5e9; flex-shrink: 0; }
h1,h2,h3 { margin: 16px 0 8px; font-weight: 600; }
h1 { font-size: 1.5em; } h2 { font-size: 1.3em; } h3 { font-size: 1.1em; }
p { margin-bottom: 8px; }
ul,ol { margin-left: 20px; margin-bottom: 8px; }
pre { background: #f5f5f5; border-radius: 6px; padding: 12px; overflow-x: auto; margin: 8px 0; }
code { font-family: "SF Mono", Monaco, Consolas, monospace; font-size: 13px; }
:not(pre)>code { background: #e8e8e8; padding: 2px 6px; border-radius: 4px; }
table { border-collapse: collapse; width: 100%; margin: 8px 0; }
th,td { border: 1px solid #e0e0e0; padding: 8px 12px; text-align: left; }
th { background: #f5f5f5; font-weight: 600; }
a { color: #4a9eff; text-decoration: none; }
a:hover { text-decoration: underline; }
.katex-block,.katex-display { text-align: center; margin: 12px 0; overflow-x: auto; }
.katex { font-size: 1.1em; }
.think { background: #f5f5f5; border-radius: 8px; padding: 8px 12px; margin-bottom: 8px; font-size: 13px; color: #555; }
.think-toggle { cursor: pointer; color: #666; font-size: 12px; }
.think-content { display: none; margin-top: 8px; }
.think-content.show { display: block; }
/* 操作摘要卡片样式 */
.ops-card { background: #f0f7ff; border-left: 3px solid #4a9eff; border-radius: 4px; padding: 8px 12px; margin-top: 8px; }
.ops-title { color: #4a9eff; font-size: 12px; font-weight: bold; margin-bottom: 4px; }
.ops-item { display: flex; align-items: center; gap: 6px; padding: 2px 0; font-size: 12px; color: #555; }
.ops-icon { width: 16px; text-align: center; }
.ops-more { color: #999; font-size: 11px; margin-top: 4px; }
.file-link { color: #4a9eff; cursor: pointer; text-decoration: underline; }
.file-link:hover { color: #2979ff; }
/* 附件预览样式 */
.attachments { display: flex; flex-wrap: wrap; gap: 8px; margin-top: 8px; }
.att-item { display: flex; align-items: center; gap: 4px; background: #fff; border: 1px solid #e0e0e0; 
            border-radius: 4px; padding: 4px 8px; font-size: 12px; cursor: pointer; }
.att-item:hover { background: #f5f5f5; }
.att-icon { font-size: 14px; }
.att-name { color: #333; max-width: 100px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.att-more { background: #e0e0e0; border-radius: 4px; padding: 4px 8px; font-size: 12px; color: #666; }
'''

    def _get_scripts(self) -> str:
        return '''
function renderMath() {
    if (typeof renderMathInElement !== 'undefined') {
        renderMathInElement(document.body, {
            delimiters: [{left: "$$", right: "$$", display: true}, {left: "$", right: "$", display: false}],
            throwOnError: false
        });
    }
}
function scrollBottom() { window.scrollTo(0, document.body.scrollHeight); }
function addMsg(html) { document.getElementById('msgs').insertAdjacentHTML('beforeend', html); renderMath(); scrollBottom(); }
function updateStream(html) { var s = document.querySelector('.msg.streaming'); if(s) { s.innerHTML = html; renderMath(); scrollBottom(); } }
function finishStream() { var s = document.querySelector('.msg.streaming'); if(s) s.classList.remove('streaming'); }
function clearMsgs() { document.getElementById('msgs').innerHTML = ''; }
function toggleThink(id) { var c = document.getElementById('think-'+id); if(c) c.classList.toggle('show'); }
function onFileClick(path) { window.location.href = 'file://' + path; }
'''

    def render_messages(self, messages: List[Any]) -> None:
        """渲染消息列表"""
        self._messages = messages
        
        if not self._web_view:
            return
        
        # 如果页面还没加载完成，保存待渲染消息
        if not self._page_loaded:
            self._pending_messages = messages
            return
        
        # 使用 JavaScript 增量更新，避免重新加载页面
        self._do_render(messages)
    
    def _do_render(self, messages: List[Any]):
        """实际执行渲染（通过 JS 更新 DOM，不重新加载页面）"""
        if not self._web_view or self._is_rendering:
            return
        
        self._is_rendering = True
        parts = [self._msg_to_html(m) for m in messages]
        content = '\n'.join(parts)
        # 使用 JS 更新内容，而不是 setHtml 重新加载整个页面
        escaped_content = self._esc(content)
        self._run_js(f"document.getElementById('msgs').innerHTML = `{escaped_content}`; renderMath();")
        self._is_rendering = False
    
    def _msg_to_html(self, msg) -> str:
        """将消息转换为 HTML"""
        role = getattr(msg, 'role', 'assistant')
        content = getattr(msg, 'content', '') or ''
        reasoning = getattr(msg, 'reasoning_html', '') or ''
        msg_id = getattr(msg, 'id', 'x')
        operations = getattr(msg, 'operations', []) or []
        attachments = getattr(msg, 'attachments', []) or []
        
        content_html = self._md_to_html(content)
        
        if role == 'user':
            att_html = self._render_attachments_html(attachments) if attachments else ''
            return f'<div class="row user"><div class="msg user">{content_html}{att_html}</div></div>'
        elif role == 'system':
            return f'<div class="row"><div class="msg system">{content_html}</div></div>'
        else:
            think = ""
            if reasoning:
                think = f'''<div class="think">
<div class="think-toggle" onclick="toggleThink('{msg_id}')">💭 思考过程 ▶</div>
<div class="think-content" id="think-{msg_id}">{reasoning}</div></div>'''
            ops_html = self._render_operations_html(operations) if operations else ''
            return f'<div class="row"><div class="avatar">🤖</div><div class="msg assistant">{think}{content_html}{ops_html}</div></div>'

    def _render_operations_html(self, operations: List[str]) -> str:
        """渲染操作摘要卡片 HTML"""
        if not operations:
            return ""
        
        max_display = 5
        items = []
        for op in operations[:max_display]:
            icon = "✅"
            if "进行中" in op or "running" in op.lower():
                icon = "⏳"
            elif "失败" in op or "error" in op.lower():
                icon = "❌"
            
            # 检查是否包含文件路径，添加点击链接
            op_html = self._linkify_file_paths(op)
            items.append(f'<div class="ops-item"><span class="ops-icon">{icon}</span><span>{op_html}</span></div>')
        
        more = ""
        if len(operations) > max_display:
            more = f'<div class="ops-more">... 还有 {len(operations) - max_display} 条操作</div>'
        
        return f'''<div class="ops-card">
<div class="ops-title">📋 操作记录</div>
{''.join(items)}
{more}
</div>'''
    
    def _render_attachments_html(self, attachments: List[Dict[str, Any]]) -> str:
        """渲染附件预览 HTML"""
        if not attachments:
            return ""
        
        items = []
        for att in attachments[:3]:
            att_type = att.get("type", "file")
            name = att.get("name", "未知文件")
            path = att.get("path", "")
            
            icon = "🖼️" if att_type == "image" else "📄"
            display_name = name[:12] + "..." if len(name) > 15 else name
            
            onclick = f'onclick="onFileClick(\'{self._esc_attr(path)}\')"' if path else ''
            items.append(f'<div class="att-item" {onclick}><span class="att-icon">{icon}</span><span class="att-name">{display_name}</span></div>')
        
        more = ""
        if len(attachments) > 3:
            more = f'<span class="att-more">+{len(attachments) - 3}</span>'
        
        return f'<div class="attachments">{"".join(items)}{more}</div>'
    
    def _linkify_file_paths(self, text: str) -> str:
        """将文本中的文件路径转换为可点击链接"""
        import re
        import html
        
        # 匹配文件路径模式
        patterns = [
            (r'`([^`]+\.(py|cir|json|txt|md|spice))`', r'<a class="file-link" href="file://\1">`\1`</a>'),
            (r'"([^"]+\.(py|cir|json|txt|md|spice))"', r'<a class="file-link" href="file://\1">"\1"</a>'),
        ]
        
        result = html.escape(text)
        for pattern, replacement in patterns:
            result = re.sub(pattern, replacement, result, flags=re.IGNORECASE)
        
        return result
    
    def _md_to_html(self, text: str) -> str:
        """Markdown 转 HTML"""
        if not text:
            return ""
        try:
            from infrastructure.utils.markdown_renderer import render_markdown
            return render_markdown(text)
        except:
            import html
            return html.escape(text).replace('\n', '<br>')
    
    # 流式输出
    def start_streaming(self):
        if not self._web_view:
            return
        self._is_streaming = True
        self._stream_content = ""
        html = '<div class="row"><div class="avatar">🤖</div><div class="msg assistant streaming"></div></div>'
        self._run_js(f"addMsg(`{self._esc(html)}`)")
        self._stream_timer.start()
    
    def append_streaming_chunk(self, chunk: str, chunk_type: str = "content"):
        if chunk_type == "content":
            self._stream_content += chunk
        self._pending_update = True
    
    def _flush_stream(self):
        if not self._pending_update:
            return
        self._pending_update = False
        html = self._md_to_html(self._stream_content)
        self._run_js(f"updateStream(`{self._esc(html)}`)")
    
    def finish_streaming(self):
        self._stream_timer.stop()
        self._is_streaming = False
        html = self._md_to_html(self._stream_content)
        self._run_js(f"updateStream(`{self._esc(html)}`)")
        self._run_js("finishStream()")
        self._stream_content = ""
    
    def update_streaming(self, content: str, reasoning: str = ""):
        self._stream_content = content
        self._pending_update = True
    
    def is_streaming(self) -> bool:
        return self._is_streaming
    
    def clear_messages(self):
        self._messages = []
        self._run_js("clearMsgs()")
    
    def scroll_to_bottom(self):
        self._run_js("scrollBottom()")
    
    def _run_js(self, code: str):
        if self._web_view:
            self._web_view.page().runJavaScript(code)
    
    def _esc(self, text: str) -> str:
        """转义 JavaScript 模板字符串中的特殊字符"""
        return text.replace('\\', '\\\\').replace('`', '\\`').replace('$', '\\$').replace('\r', '').replace('\n', '\\n')
    
    def _esc_attr(self, text: str) -> str:
        """转义 HTML 属性中的特殊字符"""
        return text.replace("'", "\\'").replace('"', '\\"').replace('\\', '\\\\')
    
    def cleanup(self):
        self._stream_timer.stop()


__all__ = ["WebMessageView", "WEBENGINE_AVAILABLE"]
