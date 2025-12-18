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
- 使用 SVG 图标（无 emoji）
"""

import os
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


# ============================================================
# SVG 图标加载（优先从本地文件加载）
# ============================================================

def _get_icons_dir() -> str:
    """获取图标目录路径"""
    current_file = os.path.abspath(__file__)
    conversation_dir = os.path.dirname(current_file)
    panels_dir = os.path.dirname(conversation_dir)
    presentation_dir = os.path.dirname(panels_dir)
    project_root = os.path.dirname(presentation_dir)
    return os.path.join(project_root, "resources", "icons")

def _load_svg_icon(relative_path: str, fallback: str) -> str:
    """
    从本地文件加载 SVG 图标
    
    Args:
        relative_path: 相对于 icons 目录的路径，如 "panel/robot.svg"
        fallback: 如果文件不存在时使用的内联 SVG
        
    Returns:
        SVG 字符串内容
    """
    try:
        icons_dir = _get_icons_dir()
        icon_path = os.path.join(icons_dir, relative_path)
        if os.path.exists(icon_path):
            with open(icon_path, "r", encoding="utf-8") as f:
                return f.read().strip()
    except Exception:
        pass
    return fallback

# 内联 SVG 后备定义（仅在本地文件不存在时使用）
_FALLBACK_ROBOT = '''<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="#4a9eff" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="3" y="8" width="18" height="12" rx="2"/><circle cx="9" cy="14" r="2"/><circle cx="15" cy="14" r="2"/><path d="M12 2v4"/><path d="M8 8V6a4 4 0 0 1 8 0v2"/></svg>'''
_FALLBACK_THINKING = '''<svg xmlns="http://www.w3.org/2000/svg" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="#666" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/><circle cx="9" cy="10" r="1" fill="#666"/><circle cx="12" cy="10" r="1" fill="#666"/><circle cx="15" cy="10" r="1" fill="#666"/></svg>'''
_FALLBACK_CLIPBOARD = '''<svg xmlns="http://www.w3.org/2000/svg" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="#4a9eff" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M16 4h2a2 2 0 0 1 2 2v14a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2V6a2 2 0 0 1 2-2h2"/><rect x="8" y="2" width="8" height="4" rx="1" ry="1"/><path d="M9 12h6"/><path d="M9 16h6"/></svg>'''
_FALLBACK_GLOBE = '''<svg xmlns="http://www.w3.org/2000/svg" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="#4a9eff" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"/><line x1="2" y1="12" x2="22" y2="12"/><path d="M12 2a15.3 15.3 0 0 1 4 10 15.3 15.3 0 0 1-4 10 15.3 15.3 0 0 1-4-10 15.3 15.3 0 0 1 4-10z"/></svg>'''
_FALLBACK_SUCCESS = '''<svg xmlns="http://www.w3.org/2000/svg" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="#4caf50" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M22 11.08V12a10 10 0 1 1-5.93-9.14"/><polyline points="22 4 12 14.01 9 11.01"/></svg>'''
_FALLBACK_PROGRESS = '''<svg xmlns="http://www.w3.org/2000/svg" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="#ff9800" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"/><polyline points="12 6 12 12 16 14"/></svg>'''
_FALLBACK_ERROR = '''<svg xmlns="http://www.w3.org/2000/svg" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="#f44336" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"/><line x1="15" y1="9" x2="9" y2="15"/><line x1="9" y1="9" x2="15" y2="15"/></svg>'''
_FALLBACK_IMAGE = '''<svg xmlns="http://www.w3.org/2000/svg" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="#666" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="3" y="3" width="18" height="18" rx="2" ry="2"/><circle cx="8.5" cy="8.5" r="1.5"/><polyline points="21 15 16 10 5 21"/></svg>'''
_FALLBACK_FILE = '''<svg xmlns="http://www.w3.org/2000/svg" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="#666" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14 2 14 8 20 8"/></svg>'''

# 从本地文件加载图标（带后备）
SVG_ROBOT = _load_svg_icon("panel/robot.svg", _FALLBACK_ROBOT)
SVG_THINKING = _load_svg_icon("panel/thinking.svg", _FALLBACK_THINKING)
SVG_CLIPBOARD = _load_svg_icon("panel/clipboard.svg", _FALLBACK_CLIPBOARD)
SVG_SEARCH = _load_svg_icon("panel/globe.svg", _FALLBACK_GLOBE)
SVG_SUCCESS = _load_svg_icon("status/success.svg", _FALLBACK_SUCCESS)
SVG_LOADING = _load_svg_icon("status/progress.svg", _FALLBACK_PROGRESS)
SVG_ERROR = _load_svg_icon("status/error.svg", _FALLBACK_ERROR)
SVG_IMAGE = _load_svg_icon("panel/image.svg", _FALLBACK_IMAGE)
SVG_FILE = _load_svg_icon("file/file.svg", _FALLBACK_FILE)


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
        self._stream_reasoning = ""  # 流式思考内容
        self._messages = []
        self._page_loaded = False
        self._pending_messages = []
        self._is_rendering = False
        self._stream_timer = QTimer(self)
        self._stream_timer.setInterval(50)
        self._stream_timer.timeout.connect(self._flush_stream)
        self._pending_update = False
        self._pending_reasoning_update = False  # 思考内容更新标志
        self._setup_ui()
    
    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        
        if WEBENGINE_AVAILABLE:
            self._web_view = QWebEngineView()
            self._web_view.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
            settings = self._web_view.settings()
            settings.setAttribute(QWebEngineSettings.WebAttribute.JavascriptEnabled, True)
            self._setup_web_channel()
            self._web_view.page().acceptNavigationRequest = self._handle_navigation
            self._web_view.loadFinished.connect(self._on_page_loaded)
            self._load_initial_page()
            layout.addWidget(self._web_view)
        else:
            label = QLabel("请安装 PyQt6-WebEngine")
            label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            layout.addWidget(label)
    
    def _setup_web_channel(self):
        if not WEBENGINE_AVAILABLE or not self._web_view:
            return
        try:
            self._web_channel = QWebChannel()
            self._web_channel.registerObject("pyBridge", self)
            self._web_view.page().setWebChannel(self._web_channel)
        except Exception:
            pass
    
    def _handle_navigation(self, url, nav_type, is_main_frame):
        url_str = url.toString()
        if url_str.startswith(('about:', 'data:')):
            return True
        if url_str.startswith('file://'):
            self.file_clicked.emit(url_str[7:])
            return False
        if url_str.startswith(('http://', 'https://')):
            self.link_clicked.emit(url_str)
            return False
        return True
    
    @pyqtSlot(str)
    def handleFileClick(self, path: str):
        self.file_clicked.emit(path)
    
    @pyqtSlot(str)
    def handleLinkClick(self, url: str):
        self.link_clicked.emit(url)
    
    def _on_page_loaded(self, ok):
        self._page_loaded = ok
        if ok and self._pending_messages and not self._is_rendering:
            self._do_render(self._pending_messages)
            self._pending_messages = []
    
    def _load_initial_page(self):
        self._web_view.setHtml(self._build_html(""))

    def _build_html(self, content: str) -> str:
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

.row { display: flex; gap: 8px; align-items: flex-start; }
.row.user { flex-direction: row-reverse; }
.avatar { width: 32px; height: 32px; border-radius: 50%; display: flex; 
          align-items: center; justify-content: center; background: #e8f5e9; flex-shrink: 0; }
.avatar svg { width: 20px; height: 20px; }
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
.think-toggle { cursor: pointer; color: #666; font-size: 12px; display: flex; align-items: center; gap: 4px; user-select: none; }
.think-toggle svg { vertical-align: middle; }
.think-toggle .arrow { transition: transform 0.2s; display: inline-block; }
.think-toggle.expanded .arrow { transform: rotate(90deg); }
.think-content { display: none; margin-top: 8px; max-height: 300px; overflow-y: auto; }
.think-content.show { display: block; }
.think-status { color: #999; font-size: 11px; margin-left: 4px; }
.think-status.thinking::after { content: "..."; animation: dots 1.5s infinite; }
.think-status.searching::after { content: "..."; animation: dots 1.5s infinite; }
.think-status.done { color: #4caf50; }
@keyframes dots { 0%,20% { content: "."; } 40% { content: ".."; } 60%,100% { content: "..."; } }
.search-card { background: #e8f4fd; border-left: 3px solid #4a9eff; border-radius: 4px; padding: 8px 12px; margin-bottom: 8px; }
.search-toggle { cursor: pointer; color: #4a9eff; font-size: 12px; display: flex; align-items: center; gap: 4px; user-select: none; }
.search-toggle svg { vertical-align: middle; }
.search-toggle .arrow { transition: transform 0.2s; display: inline-block; }
.search-toggle.expanded .arrow { transform: rotate(90deg); }
.search-content { display: none; margin-top: 8px; max-height: 200px; overflow-y: auto; }
.search-content.show { display: block; }
.search-item { padding: 4px 0; border-bottom: 1px solid #e0e0e0; font-size: 12px; }
.search-item:last-child { border-bottom: none; }
.search-item-title { color: #333; font-weight: 500; }
.search-item-url { color: #4a9eff; font-size: 11px; word-break: break-all; }
.search-item-snippet { color: #666; font-size: 11px; margin-top: 2px; }
.search-status { color: #999; font-size: 11px; margin-left: 4px; }
.sources-card { margin-top: 16px; padding-top: 12px; border-top: 1px solid #e0e0e0; }
.sources-title { color: #666; font-size: 12px; margin-bottom: 8px; display: flex; align-items: center; gap: 4px; }
.sources-list { display: flex; flex-wrap: wrap; gap: 6px; }
.source-item { display: inline-flex; align-items: center; gap: 4px; background: #f5f5f5; border-radius: 4px; padding: 4px 8px; font-size: 12px; color: #4a9eff; text-decoration: none; transition: background 0.2s; }
.source-item:hover { background: #e8f4fd; }
.source-num { color: #999; font-size: 11px; }
.source-domain { max-width: 120px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.ops-card { background: #f0f7ff; border-left: 3px solid #4a9eff; border-radius: 4px; padding: 8px 12px; margin-top: 8px; }
.ops-title { color: #4a9eff; font-size: 12px; font-weight: bold; margin-bottom: 4px; display: flex; align-items: center; gap: 4px; }
.ops-item { display: flex; align-items: center; gap: 6px; padding: 2px 0; font-size: 12px; color: #555; }
.ops-icon { width: 16px; display: flex; align-items: center; justify-content: center; }
.ops-more { color: #999; font-size: 11px; margin-top: 4px; }
.file-link { color: #4a9eff; cursor: pointer; text-decoration: underline; }
.file-link:hover { color: #2979ff; }
.attachments { display: flex; flex-wrap: wrap; gap: 8px; margin-top: 8px; }
.att-item { display: flex; align-items: center; gap: 4px; background: #fff; border: 1px solid #e0e0e0; 
            border-radius: 4px; padding: 4px 8px; font-size: 12px; cursor: pointer; }
.att-item:hover { background: #f5f5f5; }
.att-icon { display: flex; align-items: center; }
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
var _autoScroll = true;
var _scrollThreshold = 100;
window.addEventListener('scroll', function() {
    var atBottom = (window.innerHeight + window.scrollY) >= (document.body.scrollHeight - _scrollThreshold);
    _autoScroll = atBottom;
});
function scrollBottom() { if(_autoScroll) window.scrollTo(0, document.body.scrollHeight); }
function forceScrollBottom() { window.scrollTo(0, document.body.scrollHeight); _autoScroll = true; }
function addMsg(html) { document.getElementById('msgs').insertAdjacentHTML('beforeend', html); renderMath(); forceScrollBottom(); }
function updateStream(html) { 
    var s = document.querySelector('.msg.streaming .stream-content'); 
    if(s) { s.innerHTML = html; renderMath(); scrollBottom(); } 
}
function updateStreamReasoning(html) {
    var s = document.querySelector('.msg.streaming .think-content');
    if(s) { s.innerHTML = html; scrollBottom(); }
}
function finishThinking() {
    var status = document.querySelector('.msg.streaming .think-status');
    if(status) { 
        status.classList.remove('thinking');
        status.classList.add('done');
        status.textContent = '思考完成';
    }
}
function startSearching() {
    var search = document.querySelector('.msg.streaming .search-card');
    if(search) {
        search.style.display = 'block';
        var status = search.querySelector('.search-status');
        if(status) {
            status.classList.add('searching');
            status.textContent = '搜索中';
        }
    }
    // 搜索时隐藏思考区域
    var think = document.querySelector('.msg.streaming .think');
    if(think) { think.style.display = 'none'; }
}
function finishSearching(resultCount) {
    var search = document.querySelector('.msg.streaming .search-card');
    if(search) {
        var status = search.querySelector('.search-status');
        if(status) {
            status.classList.remove('searching');
            status.textContent = '已搜索 ' + resultCount + ' 条结果';
        }
    }
    // 搜索完成后显示思考区域
    var think = document.querySelector('.msg.streaming .think');
    if(think) { think.style.display = 'block'; }
}
function updateSearchResults(html) {
    var content = document.querySelector('.msg.streaming .search-content');
    if(content) { content.innerHTML = html; }
}
function toggleSearch(id) {
    var c = document.getElementById('search-'+id);
    var t = c ? c.previousElementSibling : null;
    if(c) {
        c.classList.toggle('show');
        if(t && t.classList.contains('search-toggle')) t.classList.toggle('expanded');
    }
}
function finishStream() { 
    var s = document.querySelector('.msg.streaming'); 
    if(s) { 
        s.classList.remove('streaming'); 
        var think = s.querySelector('.think');
        if(think) { 
            var content = think.querySelector('.think-content');
            if(content) content.classList.remove('show');
            var toggle = think.querySelector('.think-toggle');
            if(toggle) toggle.classList.remove('expanded');
            var status = think.querySelector('.think-status');
            if(status) {
                status.classList.remove('thinking');
                status.classList.add('done');
                status.textContent = '思考完成';
            }
        }
    } 
}
function clearMsgs() { document.getElementById('msgs').innerHTML = ''; _autoScroll = true; }
function toggleThink(id) { 
    var c = document.getElementById('think-'+id); 
    var t = c ? c.previousElementSibling : null;
    if(c) { 
        c.classList.toggle('show'); 
        if(t && t.classList.contains('think-toggle')) t.classList.toggle('expanded');
    } 
}
function onFileClick(path) { window.location.href = 'file://' + path; }
'''

    def render_messages(self, messages: List[Any]) -> None:
        self._messages = messages
        if not self._web_view:
            return
        if not self._page_loaded:
            self._pending_messages = messages
            return
        self._do_render(messages)
    
    def _do_render(self, messages: List[Any]):
        if not self._web_view or self._is_rendering:
            return
        self._is_rendering = True
        parts = [self._msg_to_html(m) for m in messages]
        content = '\n'.join(parts)
        escaped_content = self._esc(content)
        self._run_js(f"document.getElementById('msgs').innerHTML = `{escaped_content}`; renderMath();")
        self._is_rendering = False
    
    def _msg_to_html(self, msg) -> str:
        role = getattr(msg, 'role', 'assistant')
        content = getattr(msg, 'content', '') or ''
        reasoning = getattr(msg, 'reasoning_html', '') or ''
        msg_id = getattr(msg, 'id', 'x')
        operations = getattr(msg, 'operations', []) or []
        attachments = getattr(msg, 'attachments', []) or []
        web_search_results = getattr(msg, 'web_search_results', []) or []
        
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
<div class="think-toggle" onclick="toggleThink('{msg_id}')">{SVG_THINKING} 思考过程 ▶</div>
<div class="think-content" id="think-{msg_id}">{reasoning}</div></div>'''
            ops_html = self._render_operations_html(operations) if operations else ''
            sources_html = self._render_sources_html(web_search_results) if web_search_results else ''
            return f'<div class="row"><div class="avatar">{SVG_ROBOT}</div><div class="msg assistant">{think}{content_html}{sources_html}{ops_html}</div></div>'

    def _render_operations_html(self, operations: List[str]) -> str:
        if not operations:
            return ""
        
        max_display = 5
        items = []
        for op in operations[:max_display]:
            if "进行中" in op or "running" in op.lower():
                icon = SVG_LOADING
            elif "失败" in op or "error" in op.lower():
                icon = SVG_ERROR
            else:
                icon = SVG_SUCCESS
            
            op_html = self._linkify_file_paths(op)
            items.append(f'<div class="ops-item"><span class="ops-icon">{icon}</span><span>{op_html}</span></div>')
        
        more = ""
        if len(operations) > max_display:
            more = f'<div class="ops-more">... 还有 {len(operations) - max_display} 条操作</div>'
        
        return f'''<div class="ops-card">
<div class="ops-title">{SVG_CLIPBOARD} 操作记录</div>
{''.join(items)}
{more}
</div>'''
    
    def _render_attachments_html(self, attachments: List[Dict[str, Any]]) -> str:
        if not attachments:
            return ""
        
        items = []
        for att in attachments[:3]:
            att_type = att.get("type", "file")
            name = att.get("name", "未知文件")
            path = att.get("path", "")
            
            icon = SVG_IMAGE if att_type == "image" else SVG_FILE
            display_name = name[:12] + "..." if len(name) > 15 else name
            
            onclick = f'onclick="onFileClick(\'{self._esc_attr(path)}\')"' if path else ''
            items.append(f'<div class="att-item" {onclick}><span class="att-icon">{icon}</span><span class="att-name">{display_name}</span></div>')
        
        more = ""
        if len(attachments) > 3:
            more = f'<span class="att-more">+{len(attachments) - 3}</span>'
        
        return f'<div class="attachments">{"".join(items)}{more}</div>'
    
    def _render_sources_html(self, results: List[Dict[str, Any]]) -> str:
        """
        渲染搜索来源链接（类似 Google AI Studio 风格）
        
        Args:
            results: 搜索结果列表，每项包含 title, url, snippet
            
        Returns:
            HTML 字符串
        """
        if not results:
            return ""
        
        import html
        from urllib.parse import urlparse
        
        items = []
        for i, result in enumerate(results, 1):
            url = result.get("url", "")
            title = result.get("title", "")
            
            # 提取域名
            try:
                domain = urlparse(url).netloc
                if domain.startswith("www."):
                    domain = domain[4:]
            except:
                domain = url[:30] if url else "unknown"
            
            # 转义 HTML
            safe_url = html.escape(url)
            safe_domain = html.escape(domain)
            safe_title = html.escape(title) if title else safe_domain
            
            items.append(
                f'<a class="source-item" href="{safe_url}" target="_blank" title="{safe_title}">'
                f'<span class="source-num">{i}.</span>'
                f'<span class="source-domain">{safe_domain}</span>'
                f'</a>'
            )
        
        return f'''<div class="sources-card">
<div class="sources-title">{SVG_SEARCH} Sources</div>
<div class="sources-list">{"".join(items)}</div>
</div>'''
    
    def _linkify_file_paths(self, text: str) -> str:
        import re
        import html
        patterns = [
            (r'`([^`]+\.(py|cir|json|txt|md|spice))`', r'<a class="file-link" href="file://\1">`\1`</a>'),
            (r'"([^"]+\.(py|cir|json|txt|md|spice))"', r'<a class="file-link" href="file://\1">"\1"</a>'),
        ]
        result = html.escape(text)
        for pattern, replacement in patterns:
            result = re.sub(pattern, replacement, result, flags=re.IGNORECASE)
        return result
    
    def _md_to_html(self, text: str) -> str:
        if not text:
            return ""
        try:
            from infrastructure.utils.markdown_renderer import render_markdown
            return render_markdown(text)
        except:
            import html
            return html.escape(text).replace('\n', '<br>')

    # 流式输出
    def start_streaming(self, with_search: bool = False):
        """
        开始流式输出
        
        创建一个包含搜索区域、思考区域和内容区域的流式消息气泡。
        
        Args:
            with_search: 是否显示搜索区域
        """
        if not self._web_view:
            return
        self._is_streaming = True
        self._stream_content = ""
        self._stream_reasoning = ""
        
        # 搜索区域（默认隐藏，启用搜索时显示）
        search_html = f'''<div class="search-card" style="display: {'block' if with_search else 'none'};">
<div class="search-toggle" onclick="toggleSearch('stream')">{SVG_SEARCH} 联网搜索<span class="arrow">▶</span><span class="search-status {'searching' if with_search else ''}">{'搜索中' if with_search else ''}</span></div>
<div class="search-content" id="search-stream"></div>
</div>'''
        
        # 思考区域（启用搜索时初始隐藏，等搜索完成后显示）
        think_display = 'none' if with_search else 'block'
        
        # 创建包含搜索区域和思考区域的流式消息结构
        html = f'''<div class="row"><div class="avatar">{SVG_ROBOT}</div><div class="msg assistant streaming">
{search_html}
<div class="think" style="display: {think_display};">
<div class="think-toggle expanded" onclick="toggleThink('stream')">{SVG_THINKING} 思考过程<span class="arrow">▶</span><span class="think-status thinking">思考中</span></div>
<div class="think-content show" id="think-stream"></div>
</div>
<div class="stream-content"></div>
</div></div>'''
        self._run_js(f"addMsg(`{self._esc(html)}`)")
        self._stream_timer.start()
    
    def append_streaming_chunk(self, chunk: str, chunk_type: str = "content"):
        """
        追加流式输出块
        
        Args:
            chunk: 文本内容
            chunk_type: 内容类型 ("reasoning" | "content")
        """
        if chunk_type == "reasoning":
            self._stream_reasoning += chunk
            self._pending_reasoning_update = True
        else:
            self._stream_content += chunk
            self._pending_update = True
    
    def _flush_stream(self):
        """刷新流式输出缓冲区"""
        # 更新思考内容（使用 Markdown 渲染）
        if self._pending_reasoning_update:
            self._pending_reasoning_update = False
            reasoning_html = self._md_to_html(self._stream_reasoning)
            self._run_js(f"updateStreamReasoning(`{self._esc(reasoning_html)}`)")
        
        # 更新主内容
        if self._pending_update:
            self._pending_update = False
            html = self._md_to_html(self._stream_content)
            self._run_js(f"updateStream(`{self._esc(html)}`)")
    
    def finish_thinking(self):
        """
        完成思考阶段
        
        更新思考状态显示为"思考完成"，但不折叠思考区域。
        """
        self._run_js("finishThinking()")
    
    def start_searching(self):
        """
        开始搜索阶段
        
        显示搜索区域并更新状态为"搜索中"。
        """
        self._run_js("startSearching()")
    
    def finish_searching(self, result_count: int = 0):
        """
        完成搜索阶段
        
        更新搜索状态显示搜索结果数量。
        
        Args:
            result_count: 搜索结果数量
        """
        self._run_js(f"finishSearching({result_count})")
    
    def update_search_results(self, results: List[Dict[str, Any]]):
        """
        更新搜索结果显示
        
        Args:
            results: 搜索结果列表，每项包含 title, snippet, url
        """
        if not results:
            return
        
        items_html = []
        for r in results:
            title = r.get("title", "")
            snippet = r.get("snippet", "")
            url = r.get("url", "")
            items_html.append(f'''<div class="search-item">
<div class="search-item-title">{self._esc_html(title)}</div>
<div class="search-item-url"><a href="{url}" target="_blank">{url}</a></div>
<div class="search-item-snippet">{self._esc_html(snippet[:150])}</div>
</div>''')
        
        html = "".join(items_html)
        self._run_js(f"updateSearchResults(`{self._esc(html)}`)")
    
    def _esc_html(self, text: str) -> str:
        """转义 HTML 特殊字符"""
        import html
        return html.escape(text) if text else ""
    
    def finish_streaming(self):
        """
        完成流式输出
        
        停止定时器，最终更新内容，并折叠思考区域。
        """
        self._stream_timer.stop()
        self._is_streaming = False
        
        # 最终更新内容
        html = self._md_to_html(self._stream_content)
        self._run_js(f"updateStream(`{self._esc(html)}`)")
        
        # 如果有思考内容，最终更新（使用 Markdown 渲染）
        if self._stream_reasoning:
            reasoning_html = self._md_to_html(self._stream_reasoning)
            self._run_js(f"updateStreamReasoning(`{self._esc(reasoning_html)}`)")
        
        # 调用 finishStream 折叠思考区域
        self._run_js("finishStream()")
        
        self._stream_content = ""
        self._stream_reasoning = ""
    
    def update_streaming(self, content: str, reasoning: str = ""):
        """
        更新流式内容（兼容旧接口）
        
        Args:
            content: 主内容
            reasoning: 思考内容
        """
        self._stream_content = content
        self._stream_reasoning = reasoning
        self._pending_update = True
        if reasoning:
            self._pending_reasoning_update = True
    
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
