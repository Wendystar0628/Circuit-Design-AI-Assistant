# Web-based Message View Component
"""
基于 WebEngine 的消息显示组件

使用单个 QWebEngineView 渲染所有消息，支持 Markdown 和 LaTeX。
"""

from typing import Any, List, Optional
from PyQt6.QtCore import Qt, pyqtSignal, QTimer
from PyQt6.QtWidgets import QWidget, QVBoxLayout, QSizePolicy, QLabel

try:
    from PyQt6.QtWebEngineWidgets import QWebEngineView
    from PyQt6.QtWebEngineCore import QWebEngineSettings
    WEBENGINE_AVAILABLE = True
except ImportError:
    WEBENGINE_AVAILABLE = False


class WebMessageView(QWidget):
    """基于 WebEngine 的消息显示组件"""
    
    link_clicked = pyqtSignal(str)
    
    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self._web_view = None
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
            self._web_view.loadFinished.connect(self._on_page_loaded)
            self._load_initial_page()
            layout.addWidget(self._web_view)
        else:
            label = QLabel("请安装 PyQt6-WebEngine")
            label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            layout.addWidget(label)
    
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
        
        content_html = self._md_to_html(content)
        
        if role == 'user':
            return f'<div class="row user"><div class="msg user">{content_html}</div></div>'
        elif role == 'system':
            return f'<div class="row"><div class="msg system">{content_html}</div></div>'
        else:
            think = ""
            if reasoning:
                think = f'''<div class="think">
<div class="think-toggle" onclick="toggleThink('{msg_id}')">💭 思考过程 ▶</div>
<div class="think-content" id="think-{msg_id}">{reasoning}</div></div>'''
            return f'<div class="row"><div class="avatar">🤖</div><div class="msg assistant">{think}{content_html}</div></div>'
    
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
    
    def cleanup(self):
        self._stream_timer.stop()


__all__ = ["WebMessageView", "WEBENGINE_AVAILABLE"]
