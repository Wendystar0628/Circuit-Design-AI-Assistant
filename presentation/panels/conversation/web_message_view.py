# Web-based Message View Component
"""
基于 WebEngine 的消息显示组件

使用单个 QWebEngineView 渲染所有消息，支持 Markdown 和 LaTeX。

功能特性：
- Markdown 渲染（标题、列表、代码块、表格等）
- LaTeX 公式渲染（行内 $...$ 和块级 $$...$$）
- Agent step 气泡渲染
- 深度思考内容折叠
- 附件预览（图片、文件）
- 文件路径点击处理
- 当前运行时步骤渲染
- 使用 SVG 图标（无 emoji）
"""

import os
from typing import Any, Dict, List, Optional
from PyQt6.QtCore import Qt, pyqtSignal, QUrl

from domain.llm.attachment_references import (
    INLINE_ATTACHMENT_PLACEMENT,
    normalize_attachments,
    replace_inline_attachment_markers,
)
from domain.llm.message_types import Attachment

try:
    from PyQt6.QtWebEngineWidgets import QWebEngineView
    from PyQt6.QtWebEngineCore import QWebEnginePage, QWebEngineSettings
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
_FALLBACK_THINKING = '''<svg xmlns="http://www.w3.org/2000/svg" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="#666" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/><circle cx="9" cy="10" r="1" fill="#666"/><circle cx="12" cy="10" r="1" fill="#666"/><circle cx="15" cy="10" r="1" fill="#666"/></svg>'''
_FALLBACK_GLOBE = '''<svg xmlns="http://www.w3.org/2000/svg" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="#4a9eff" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"/><line x1="2" y1="12" x2="22" y2="12"/><path d="M12 2a15.3 15.3 0 0 1 4 10 15.3 15.3 0 0 1-4 10 15.3 15.3 0 0 1-4-10 15.3 15.3 0 0 1 4-10z"/></svg>'''
_FALLBACK_ERROR = '''<svg xmlns="http://www.w3.org/2000/svg" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="#f44336" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"/><line x1="15" y1="9" x2="9" y2="15"/><line x1="9" y1="9" x2="15" y2="15"/></svg>'''
_FALLBACK_FILE = '''<svg xmlns="http://www.w3.org/2000/svg" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="#666" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14 2 14 8 20 8"/></svg>'''

# 从本地文件加载图标（带后备）
SVG_THINKING = _load_svg_icon("panel/thinking.svg", _FALLBACK_THINKING)
SVG_SEARCH = _load_svg_icon("panel/globe.svg", _FALLBACK_GLOBE)
SVG_ERROR = _load_svg_icon("status/error.svg", _FALLBACK_ERROR)
SVG_FILE = _load_svg_icon("file/file.svg", _FALLBACK_FILE)

_FALLBACK_TOOL = '''<svg xmlns="http://www.w3.org/2000/svg" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="#ff9800" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M14.7 6.3a1 1 0 0 0 0 1.4l1.6 1.6a1 1 0 0 0 1.4 0l3.77-3.77a6 6 0 0 1-7.94 7.94l-6.91 6.91a2.12 2.12 0 0 1-3-3l6.91-6.91a6 6 0 0 1 7.94-7.94l-3.76 3.76z"/></svg>'''
SVG_TOOL = _load_svg_icon("panel/tool.svg", _FALLBACK_TOOL)
_FALLBACK_ROLLBACK = '''<svg xmlns="http://www.w3.org/2000/svg" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="#2563eb" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M3 7v6h6"/><path d="M3 13a9 9 0 1 0 3-6.7L3 7"/></svg>'''
SVG_ROLLBACK = _load_svg_icon("panel/undo.svg", _FALLBACK_ROLLBACK)


if WEBENGINE_AVAILABLE:
    class _MessageWebPage(QWebEnginePage):
        def __init__(self, owner: "WebMessageView"):
            super().__init__(owner)
            self._owner = owner

        def acceptNavigationRequest(self, url, nav_type, is_main_frame):
            url_str = url.toString()
            if url_str.startswith(("about:", "data:")):
                return True
            if url_str.startswith("suggestion://"):
                self._owner.suggestion_clicked.emit(url_str[len("suggestion://"):])
                return False
            if url_str.startswith("rollback://"):
                self._owner.rollback_requested.emit(url_str[len("rollback://"):])
                return False
            if url_str.startswith("file://"):
                self._owner.file_clicked.emit(url.toLocalFile() or url_str[7:])
                return False
            if url_str.startswith(("http://", "https://")):
                self._owner.link_clicked.emit(url_str)
                return False
            return True


class WebMessageView(QWidget):
    """
    基于 WebEngine 的消息显示组件
    
    负责对话消息与运行时 Agent steps 的统一渲染：
    - 消息渲染（用户/助手/系统）
    - 深度思考折叠
    - Agent step 工具与搜索卡片
    - 附件预览
    - 文件/链接点击处理
    """
    
    # 信号定义
    link_clicked = pyqtSignal(str)      # 链接点击 (url)
    file_clicked = pyqtSignal(str)      # 文件点击 (file_path)
    suggestion_clicked = pyqtSignal(str)  # 建议选项点击 (suggestion_id)
    rollback_requested = pyqtSignal(str)
    
    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self._web_view = None
        self._page_loaded = False
        self._pending_render_state: Optional[Dict[str, str]] = None
        self._setup_ui()
    
    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        
        if WEBENGINE_AVAILABLE:
            self._web_view = QWebEngineView()
            self._web_view.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
            self._web_view.setPage(_MessageWebPage(self))
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
        if not ok:
            return
        self._page_loaded = True
        if self._pending_render_state is not None:
            pending_render_state = dict(self._pending_render_state)
            self._pending_render_state = None
            self._apply_render_state(
                pending_render_state.get('messages', ''),
                pending_render_state.get('runtime', ''),
            )

    def _load_initial_page(self):
        self._web_view.setHtml(self._build_html(""))

    def _build_html(self, content: str) -> str:
        css, js, auto_js = self._load_katex()
        return f'''<!DOCTYPE html>
<html><head><meta charset="UTF-8">
<style>{css}</style>
<style>{self._get_styles()}</style>
</head><body>
<div id="conversation-root"><div id="message-list">{content}</div><div id="runtime-steps-root"></div></div>
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
body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Arial, "Microsoft YaHei UI", sans-serif;
       font-size: 14px; line-height: 1.6; color: #333; background: #fff; padding: 12px; }
#conversation-root { display: flex; flex-direction: column; gap: 12px; }
#message-list, #runtime-steps-root { display: contents; }
.msg { max-width: 85%; padding: 12px 16px; border-radius: 12px; word-wrap: break-word; }
.msg.user { margin-left: auto; background: #e3f2fd; }
.msg.assistant { margin-right: auto; background: #f8f9fa; }
.msg.system { align-self: center; background: transparent; color: #6c757d; font-size: 12px; }
.msg.suggestion { margin-right: auto; background: #f8fafc; border: 1px solid #dbe3f0; }
.msg.assistant.step { border: 1px solid #e2e8f0; box-shadow: 0 2px 8px rgba(15, 23, 42, 0.04); background: #fbfcfe; }
.partial-badge { display: inline-flex; align-items: center; gap: 4px; margin-top: 10px; padding: 4px 8px; border-radius: 999px; background: #fff7ed; color: #c2410c; font-size: 11px; border: 1px solid #fed7aa; }

.row { display: flex; width: 100%; }
.row.user { justify-content: flex-end; align-items: flex-end; gap: 8px; }
.row.system { justify-content: center; }
.message-actions { display: flex; align-items: center; }
.rollback-btn { width: 28px; height: 28px; border-radius: 999px; border: 1px solid #bfdbfe; background: #eff6ff; color: #2563eb; display: inline-flex; align-items: center; justify-content: center; cursor: pointer; transition: background 0.15s ease, border-color 0.15s ease, transform 0.15s ease; }
.rollback-btn:hover { background: #dbeafe; border-color: #93c5fd; transform: translateY(-1px); }
.rollback-btn svg { width: 14px; height: 14px; display: block; }
h1,h2,h3 { margin: 16px 0 8px; font-weight: 600; }
h1 { font-size: 1.5em; } h2 { font-size: 1.3em; } h3 { font-size: 1.1em; }
p { margin-bottom: 8px; }
ul,ol { margin-left: 20px; margin-bottom: 8px; }
pre { background: #f5f5f5; border-radius: 6px; padding: 12px; overflow-x: auto; margin: 8px 0; }
code { font-family: "JetBrains Mono", "Cascadia Code", "SF Mono", "Consolas", monospace; font-size: 13px; }
:not(pre)>code { background: #e8e8e8; padding: 2px 6px; border-radius: 4px; }
table { border-collapse: collapse; width: 100%; margin: 8px 0; }
th,td { border: 1px solid #e0e0e0; padding: 8px 12px; text-align: left; }
th { background: #f5f5f5; font-weight: 600; }
a { color: #4a9eff; text-decoration: none; }
a:hover { text-decoration: underline; }
.katex-block,.katex-display { text-align: center; margin: 12px 0; overflow-x: auto; }
.katex { font-size: 1.1em; }
@keyframes detail-spinner { from { transform: rotate(0deg); } to { transform: rotate(360deg); } }
@keyframes detail-dot-pulse { 0%, 80%, 100% { opacity: 0.28; transform: translateY(0); } 40% { opacity: 1; transform: translateY(-1px); } }
.search-item { padding: 4px 0; border-bottom: 1px solid #e0e0e0; font-size: 12px; }
.search-item:last-child { border-bottom: none; }
.search-item-title { color: #333; font-weight: 500; }
.search-item-url { color: #4a9eff; font-size: 11px; word-break: break-all; }
.search-item-snippet { color: #666; font-size: 11px; margin-top: 2px; }
.inline-file-ref { display: inline-flex; align-items: center; gap: 6px; padding: 2px 10px; border-radius: 999px; background: #dbeafe; border: 1px solid #bfdbfe; color: #1d4ed8; font-size: 12px; cursor: pointer; vertical-align: baseline; margin: 0 2px; }
.inline-file-ref:hover { background: #cfe3ff; text-decoration: none; }
.inline-file-ref .ref-icon { display: inline-flex; align-items: center; }
.inline-file-ref .ref-name { max-width: 180px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.attachment-gallery { display: flex; flex-wrap: wrap; gap: 10px; margin-top: 10px; }
.image-thumb { width: 168px; border-radius: 12px; overflow: hidden; border: 1px solid #dbe3f0; background: #ffffff; cursor: pointer; }
.image-thumb:hover { border-color: #93c5fd; box-shadow: 0 8px 18px rgba(30, 64, 175, 0.12); }
.image-thumb img { width: 100%; height: 112px; object-fit: cover; display: block; background: #f3f4f6; }
.image-caption { display: block; padding: 8px 10px; font-size: 12px; color: #374151; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.gallery-file-ref { display: inline-flex; align-items: center; gap: 6px; background: #ffffff; border: 1px solid #dbe3f0; border-radius: 10px; padding: 8px 10px; font-size: 12px; color: #1f2937; cursor: pointer; }
.gallery-file-ref:hover { background: #f8fbff; border-color: #93c5fd; }
.gallery-file-ref .ref-name { max-width: 180px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.suggestion-card { display: flex; flex-direction: column; gap: 10px; }
.suggestion-title { font-size: 13px; font-weight: 600; color: #334155; }
.suggestion-summary { font-size: 12px; color: #64748b; }
.suggestion-actions { display: flex; flex-wrap: wrap; gap: 8px; }
.suggestion-chip { display: inline-flex; align-items: center; gap: 6px; padding: 8px 12px; border-radius: 999px; border: 1px solid #cbd5e1; background: #ffffff; color: #0f172a; font-size: 12px; text-decoration: none; }
.suggestion-chip.active:hover { border-color: #60a5fa; background: #eff6ff; }
.suggestion-chip.selected { background: #2563eb; color: #ffffff; border-color: #2563eb; }
.suggestion-chip.expired { background: #f8fafc; color: #94a3b8; border-color: #e2e8f0; cursor: default; }
.suggestion-hint { font-size: 12px; color: #94a3b8; }
.tool-args { font-size: 11px; color: #666; margin-bottom: 8px; font-family: "JetBrains Mono","Cascadia Code","Consolas",monospace; line-height: 1.4; }
.tool-result-content { font-size: 11px; color: #555; background: #f5f5f5; border-radius: 4px; padding: 6px 8px;
    max-height: 120px; overflow-y: auto; white-space: pre-wrap; word-break: break-all;
    font-family: "JetBrains Mono","Cascadia Code","Consolas",monospace; }
.detail-card { border-radius: 10px; border: 1px solid #e5e7eb; overflow: hidden; margin-bottom: 8px; background: #ffffff; }
.detail-card.thinking { background: #f8fafc; border-color: #e2e8f0; }
.detail-card.search { background: #eff6ff; border-color: #bfdbfe; }
.detail-card.tool { background: #fff7ed; border-color: #fed7aa; }
.detail-toggle { cursor: pointer; display: flex; align-items: center; gap: 8px; padding: 10px 12px; color: #334155; font-size: 12px; user-select: none; }
.detail-toggle svg { flex-shrink: 0; }
.detail-toggle .arrow { transition: transform 0.2s; margin-left: auto; display: inline-block; }
.detail-toggle.expanded .arrow { transform: rotate(90deg); }
.detail-title { color: #0f172a; font-weight: 600; }
.detail-summary { color: #64748b; min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.detail-status { display: inline-flex; align-items: center; gap: 5px; font-size: 11px; padding: 1px 6px; border-radius: 999px; white-space: nowrap; }
.detail-status-indicator { display: inline-flex; align-items: center; gap: 4px; }
.detail-status-spinner { width: 9px; height: 9px; border-radius: 999px; border: 1.5px solid currentColor; border-right-color: transparent; animation: detail-spinner 0.8s linear infinite; box-sizing: border-box; }
.detail-status-dots { display: inline-flex; align-items: center; gap: 2px; }
.detail-status-dots span { width: 3px; height: 3px; border-radius: 999px; background: currentColor; opacity: 0.28; animation: detail-dot-pulse 1.2s ease-in-out infinite; }
.detail-status-dots span:nth-child(2) { animation-delay: 0.16s; }
.detail-status-dots span:nth-child(3) { animation-delay: 0.32s; }
.detail-status.running, .detail-status.thinking { color: #2563eb; background: #dbeafe; }
.detail-status.done { color: #166534; background: #dcfce7; }
.detail-status.error { color: #b91c1c; background: #fee2e2; }
.detail-content { display: none; padding: 0 12px 12px; max-height: 300px; overflow-y: auto; overscroll-behavior: contain; }
.detail-content.show { display: block; }
.detail-body-muted { font-size: 12px; color: #64748b; }
'''

    def _get_scripts(self) -> str:
        return '''
var _scrollThreshold = 64;
var _viewportState = { stickToBottom: true, suppressScrollTracking: false };
var _detailViewportStates = {};
function ensureDetailViewportState(key) {
    var normalizedKey = String(key || '');
    if (!normalizedKey) return null;
    if (!_detailViewportStates[normalizedKey]) {
        _detailViewportStates[normalizedKey] = {
            stickToBottom: true,
            suppressScrollTracking: false,
            scrollTop: 0,
            expanded: false
        };
    }
    return _detailViewportStates[normalizedKey];
}
function getScroller() {
    return document.scrollingElement || document.documentElement || document.body;
}
function isNearBottom() {
    var s = getScroller();
    return (s.scrollHeight - (s.scrollTop + s.clientHeight)) <= _scrollThreshold;
}
function isElementNearBottom(el) {
    if (!el) return true;
    return (el.scrollHeight - (el.scrollTop + el.clientHeight)) <= _scrollThreshold;
}
function syncViewportState() {
    if (_viewportState.suppressScrollTracking) return;
    _viewportState.stickToBottom = isNearBottom();
}
window.addEventListener('scroll', syncViewportState, { passive: true });
document.addEventListener('scroll', function(event) {
    var target = event.target;
    if (!target || !target.classList || !target.classList.contains('detail-content')) return;
    var state = ensureDetailViewportState(target.dataset.detailKey || '');
    if (!state || state.suppressScrollTracking) return;
    state.scrollTop = target.scrollTop;
    state.stickToBottom = isElementNearBottom(target);
    state.expanded = target.classList.contains('show');
}, { passive: true, capture: true });
function renderMath() {
    if (typeof renderMathInElement !== 'undefined') {
        renderMathInElement(document.body, {
            delimiters: [{left: "$$", right: "$$", display: true}, {left: "$", right: "$", display: false}],
            throwOnError: false
        });
    }
}
function captureDetailViewportStates() {
    document.querySelectorAll('.detail-content[data-detail-key]').forEach(function(el) {
        var state = ensureDetailViewportState(el.dataset.detailKey || '');
        if (!state) return;
        state.scrollTop = el.scrollTop;
        state.stickToBottom = isElementNearBottom(el);
        state.expanded = el.classList.contains('show');
    });
}
function restoreDetailViewportStates() {
    document.querySelectorAll('.detail-content[data-detail-key]').forEach(function(el) {
        var state = ensureDetailViewportState(el.dataset.detailKey || '');
        if (!state) return;
        var toggle = el.previousElementSibling;
        var isExpanded = state.expanded !== false;
        el.classList.toggle('show', isExpanded);
        if (toggle && toggle.classList.contains('detail-toggle')) {
            toggle.classList.toggle('expanded', isExpanded);
        }
        if (!isExpanded) return;
        state.suppressScrollTracking = true;
        if (state.stickToBottom) {
            el.scrollTop = el.scrollHeight;
        } else {
            var maxScrollTop = Math.max(0, el.scrollHeight - el.clientHeight);
            el.scrollTop = Math.min(state.scrollTop || 0, maxScrollTop);
        }
        state.suppressScrollTracking = false;
    });
}
function withViewportPreserved(mutator) {
    var s = getScroller();
    var preserveBottomStickiness = _viewportState.stickToBottom && isNearBottom();
    var previousScrollTop = s.scrollTop;
    captureDetailViewportStates();
    mutator();
    renderMath();
    requestAnimationFrame(function() {
        restoreDetailViewportStates();
        if (preserveBottomStickiness) {
            scrollBottom(true);
            return;
        }
        _viewportState.suppressScrollTracking = true;
        s.scrollTop = previousScrollTop;
        _viewportState.suppressScrollTracking = false;
    });
}
function scrollBottom(force) {
    if (!force && !_viewportState.stickToBottom) return;
    var s = getScroller();
    _viewportState.suppressScrollTracking = true;
    s.scrollTop = s.scrollHeight;
    _viewportState.suppressScrollTracking = false;
    _viewportState.stickToBottom = true;
}
function replaceConversation(messageHtml, runtimeHtml) {
    withViewportPreserved(function() {
        document.getElementById('message-list').innerHTML = messageHtml;
        document.getElementById('runtime-steps-root').innerHTML = runtimeHtml;
    });
}
function clearConversation() {
    _detailViewportStates = {};
    _viewportState.stickToBottom = true;
    replaceConversation('', '');
}
function toggleDetail(id) { 
    var c = document.getElementById('detail-'+id); 
    var t = c ? c.previousElementSibling : null;
    if(c) { 
        c.classList.toggle('show'); 
        if(t && t.classList.contains('detail-toggle')) t.classList.toggle('expanded');
        var state = ensureDetailViewportState(id);
        if (state) {
            state.expanded = c.classList.contains('show');
            if (state.expanded) {
                state.suppressScrollTracking = true;
                if (state.stickToBottom) {
                    c.scrollTop = c.scrollHeight;
                } else {
                    var maxScrollTop = Math.max(0, c.scrollHeight - c.clientHeight);
                    c.scrollTop = Math.min(state.scrollTop || 0, maxScrollTop);
                }
                state.suppressScrollTracking = false;
            }
        }
    } 
}
function onFileClick(path) {
    var normalized = String(path || '').split(String.fromCharCode(92)).join('/');
    window.location.href = 'file:///' + encodeURI(normalized);
}
function onRollbackClick(messageId) {
    window.location.href = 'rollback://' + encodeURIComponent(String(messageId || ''));
}
'''

    def render_messages(self, messages: List[Any]) -> None:
        if not self._web_view:
            return
        self.render_conversation(messages)

    def render_conversation(
        self,
        messages: List[Any],
        runtime_steps: Optional[List[Any]] = None,
    ) -> None:
        if not self._web_view:
            return
        message_html = self._build_messages_html(messages)
        runtime_html = ''.join(
            self._render_runtime_step(step) for step in (runtime_steps or [])
        )
        if not self._page_loaded:
            self._pending_render_state = {
                'messages': message_html,
                'runtime': runtime_html,
            }
            return
        self._apply_render_state(message_html, runtime_html)

    def _apply_render_state(self, message_html: str, runtime_html: str) -> None:
        escaped_message_html = self._esc(message_html)
        escaped_runtime_html = self._esc(runtime_html)
        self._run_js(
            "(function(){"
            f"var messageHtml = `{escaped_message_html}`;"
            f"var runtimeHtml = `{escaped_runtime_html}`;"
            "if (typeof replaceConversation === 'function') { replaceConversation(messageHtml, runtimeHtml); return; }"
            "var messageRoot = document.getElementById('message-list');"
            "var runtimeRoot = document.getElementById('runtime-steps-root');"
            "if (messageRoot) { messageRoot.innerHTML = messageHtml; }"
            "if (runtimeRoot) { runtimeRoot.innerHTML = runtimeHtml; }"
            "if (typeof renderMath === 'function') { renderMath(); }"
            "})();"
        )

    def _build_messages_html(self, messages: List[Any]) -> str:
        return '\n'.join(self._msg_to_html(message) for message in messages)

    def _msg_to_html(self, msg) -> str:
        role = getattr(msg, 'role', 'assistant')
        content = getattr(msg, 'content', '') or ''
        msg_id = getattr(msg, 'id', 'x')
        attachments = normalize_attachments(getattr(msg, 'attachments', []) or [])
        agent_steps = getattr(msg, 'agent_steps', []) or []

        if role == 'user':
            content_html = self._render_user_content_html(content, attachments)
            att_html = self._render_attachments_html(attachments) if attachments else ''
            rollback_html = ''
            if getattr(msg, 'can_rollback', False):
                rollback_html = (
                    f'<div class="message-actions">'
                    f'<button class="rollback-btn" type="button" onclick="onRollbackClick(\'{self._esc_attr(msg_id)}\')">{SVG_ROLLBACK}</button>'
                    f'</div>'
                )
            return f'<div class="row user"><div class="msg user">{content_html}{att_html}</div>{rollback_html}</div>'
        elif role == 'suggestion':
            return self._render_suggestion_message_html(msg)
        elif role == 'system':
            content_html = self._md_to_html(content)
            return f'<div class="row system"><div class="msg system">{content_html}</div></div>'
        else:
            return ''.join(self._render_persisted_agent_step(msg_id, step) for step in agent_steps)

    def _render_persisted_agent_step(self, message_id: str, step: Any) -> str:
        step_id = getattr(step, 'step_id', '') or f'{message_id}-step-{getattr(step, "step_index", 0)}'
        return self._render_agent_step_html(step, step_id)

    def _render_runtime_step(self, step: Any) -> str:
        step_id = getattr(step, 'step_id', '') or f'runtime-step-{getattr(step, "step_index", 0)}'
        return self._render_agent_step_html(step, step_id)

    def _render_agent_step_html(self, step: Any, step_dom_id: str) -> str:
        content_html = self._md_to_html(getattr(step, 'content', '') or '')
        reasoning_text = getattr(step, 'reasoning_content', '') or ''
        reasoning_html = self._md_to_html(reasoning_text) if reasoning_text else ''
        tool_calls = getattr(step, 'tool_calls', []) or []
        web_search_results = getattr(step, 'web_search_results', []) or []
        web_search_query = getattr(step, 'web_search_query', '') or ''
        web_search_message = getattr(step, 'web_search_message', '') or ''
        web_search_state = getattr(step, 'web_search_state', 'idle') or 'idle'
        is_complete = bool(getattr(step, 'is_complete', False))
        is_partial = bool(getattr(step, 'is_partial', False))
        stop_reason = getattr(step, 'stop_reason', '') or ''

        think_html = self._render_reasoning_block(step_dom_id, reasoning_html, is_complete) if reasoning_html else ''
        search_html = self._render_step_search_html(step_dom_id, web_search_query, web_search_results, web_search_message, web_search_state)
        tools_html = ''.join(self._render_tool_call_html(tool_call) for tool_call in tool_calls)
        partial_badge = ''
        if is_partial:
            partial_badge = (
                f'<div class="partial-badge">'
                f'{SVG_ERROR}<span>{self._esc_html(self._get_stop_reason_label(stop_reason))}</span>'
                f'</div>'
            )

        body_html = content_html or ''
        sections_html = f'{search_html}{think_html}{tools_html}{body_html}{partial_badge}'
        if not sections_html:
            return ''
        return (
            '<div class="row assistant">'
            '<div class="msg assistant step">'
            f'{sections_html}'
            '</div>'
            '</div>'
        )

    def _render_detail_card_html(
        self,
        detail_key: str,
        variant: str,
        icon_svg: str,
        title: str,
        body_html: str,
        summary: str = '',
        status_text: str = '',
        status_class: str = '',
    ) -> str:
        summary_html = f'<span class="detail-summary">{self._esc_html(summary)}</span>' if summary else ''
        status_indicator_html = ''
        if status_class in {'running', 'thinking'}:
            status_indicator_html = (
                '<span class="detail-status-indicator">'
                '<span class="detail-status-spinner"></span>'
                '<span class="detail-status-dots"><span></span><span></span><span></span></span>'
                '</span>'
            )
        status_html = (
            f'<span class="detail-status {status_class}">{status_indicator_html}<span class="detail-status-label">{self._esc_html(status_text)}</span></span>'
            if status_text else ''
        )
        detail_key_attr = self._esc_attr(detail_key)
        return (
            f'<div class="detail-card {variant}">'
            f'<div class="detail-toggle" onclick="toggleDetail(\'{detail_key_attr}\')">'
            f'{icon_svg}'
            f'<span class="detail-title">{self._esc_html(title)}</span>'
            f'{summary_html}'
            f'{status_html}'
            f'<span class="arrow">▶</span>'
            f'</div>'
            f'<div class="detail-content" id="detail-{detail_key_attr}" data-detail-key="{detail_key_attr}">{body_html}</div>'
            f'</div>'
        )

    def _build_tool_target_label(self, arguments: Dict[str, Any]) -> str:
        candidate_keys = (
            'path',
            'file_path',
            'target_file',
            'TargetFile',
            'SearchPath',
            'SearchDirectory',
        )
        for key in candidate_keys:
            value = arguments.get(key)
            if not value:
                continue
            normalized = str(value).strip().rstrip('\\/')
            if not normalized:
                continue
            normalized = normalized.replace('\\', '/')
            name = os.path.basename(normalized)
            return name or normalized
        return ''

    def _render_reasoning_block(self, block_id: str, reasoning_html: str, is_complete: bool) -> str:
        status_class = 'done' if is_complete else 'thinking'
        status_text = '已完成' if is_complete else '思考中'
        return self._render_detail_card_html(
            detail_key=f'{block_id}-thinking',
            variant='thinking',
            icon_svg=SVG_THINKING,
            title='思考过程',
            body_html=reasoning_html,
            status_text=status_text,
            status_class=status_class,
        )

    def _render_step_search_html(
        self,
        block_id: str,
        query: str,
        results: List[Dict[str, Any]],
        message: str,
        state: str,
    ) -> str:
        if not query and not results and not message and state == 'idle':
            return ''

        status_text = {
            'running': '搜索中',
            'complete': f'已搜索 {len(results)} 条结果',
            'error': '搜索失败',
        }.get(state, '')
        status_class = {
            'running': 'running',
            'complete': 'done',
            'error': 'error',
        }.get(state, '')

        content_items: List[str] = []
        display_results = results or []
        if state == 'error' and not display_results and message:
            display_results = [{
                'title': '搜索失败',
                'url': '',
                'snippet': message,
            }]

        for item in display_results:
            title_html = self._esc_html(item.get('title', '') or '')
            url = item.get('url', '') or ''
            snippet = self._esc_html((item.get('snippet', '') or '')[:180])
            url_html = f'<div class="search-item-url"><a href="{self._esc_attr(url)}" target="_blank">{self._esc_html(url)}</a></div>' if url else ''
            content_items.append(f'''<div class="search-item">
<div class="search-item-title">{title_html}</div>
{url_html}
<div class="search-item-snippet">{snippet}</div>
</div>''')

        if not content_items and message and state != 'error':
            content_items.append(f'<div class="search-item"><div class="search-item-snippet">{self._esc_html(message)}</div></div>')

        body_html = ''.join(content_items)
        if not body_html and message:
            body_html = f'<div class="detail-body-muted">{self._esc_html(message)}</div>'

        return self._render_detail_card_html(
            detail_key=f'{block_id}-search',
            variant='search',
            icon_svg=SVG_SEARCH,
            title='联网搜索',
            summary=query or '',
            body_html=body_html,
            status_text=status_text,
            status_class=status_class,
        )

    def _render_tool_call_html(self, tool_call: Any) -> str:
        tool_call_id = self._esc_attr(getattr(tool_call, 'tool_call_id', '') or '')
        tool_name = self._esc_html(getattr(tool_call, 'tool_name', '') or '')
        arguments = getattr(tool_call, 'arguments', {}) or {}
        result_content = getattr(tool_call, 'result_content', '') or ''
        is_error = bool(getattr(tool_call, 'is_error', False))
        target_label = self._build_tool_target_label(arguments)

        args_lines = []
        for key, value in arguments.items():
            value_str = str(value)
            if len(value_str) > 80:
                value_str = value_str[:77] + '...'
            args_lines.append(f'{self._esc_html(str(key))}: {self._esc_html(value_str)}')
        args_html = '<br>'.join(args_lines) if args_lines else ''

        status_class = 'error' if is_error else ('done' if result_content else 'running')
        status_text = '失败' if is_error else ('完成' if result_content else '执行中')
        detail_blocks: List[str] = []
        if args_html:
            detail_blocks.append(f'<div class="tool-args">{args_html}</div>')
        if result_content:
            display = result_content[:300] + ('...' if len(result_content) > 300 else '')
            detail_blocks.append(f'<div class="tool-result-content">{self._esc_html(display)}</div>')

        return self._render_detail_card_html(
            detail_key=f'{tool_call_id or tool_name}-tool',
            variant='tool',
            icon_svg=SVG_TOOL,
            title=tool_name or '工具调用',
            summary=target_label,
            body_html=''.join(detail_blocks),
            status_text=status_text,
            status_class=status_class,
        )

    def _render_suggestion_message_html(self, msg) -> str:
        title_html = '<div class="suggestion-title">下一步建议</div>'
        summary = self._esc_html(getattr(msg, 'status_summary', '') or '')
        summary_html = f'<div class="suggestion-summary">{summary}</div>' if summary else ''

        actions: List[str] = []
        suggestion_state = getattr(msg, 'suggestion_state', '') or 'active'
        selected_suggestion_id = getattr(msg, 'selected_suggestion_id', '') or ''
        for suggestion in getattr(msg, 'suggestions', []) or []:
            suggestion_id = self._esc_attr(getattr(suggestion, 'id', '') or '')
            label = self._esc_html(getattr(suggestion, 'label', '') or '')
            description = self._esc_html(getattr(suggestion, 'description', '') or '')
            is_selected = selected_suggestion_id and getattr(suggestion, 'id', '') == selected_suggestion_id
            if suggestion_state == 'active':
                href = f'href="suggestion://{suggestion_id}"'
                class_name = 'suggestion-chip active'
            elif is_selected:
                href = ''
                class_name = 'suggestion-chip selected'
                label = f'✓ {label}'
            else:
                href = ''
                class_name = 'suggestion-chip expired'
            title = f' title="{description}"' if description else ''
            actions.append(
                f'<a class="{class_name}" {href}{title}>{label}</a>'
            )

        hint_html = ''
        if suggestion_state == 'active':
            hint_html = '<div class="suggestion-hint">或者直接在输入框中继续输入你的想法</div>'

        return (
            '<div class="row suggestion">'
            '<div class="msg suggestion">'
            '<div class="suggestion-card">'
            f'{title_html}{summary_html}'
            f'<div class="suggestion-actions">{"".join(actions)}</div>'
            f'{hint_html}'
            '</div>'
            '</div>'
            '</div>'
        )

    def _render_user_content_html(self, content: str, attachments: List[Attachment]) -> str:
        replaced = replace_inline_attachment_markers(
            content,
            attachments,
            self._render_inline_attachment_html,
            lambda _reference_id, label: self._esc_html(label),
        )
        return self._md_to_html(replaced)

    def _render_inline_attachment_html(self, attachment: Attachment) -> str:
        display_name = self._truncate_attachment_name(attachment.name or "未知文件", 28)
        onclick = f'onclick="onFileClick(\'{self._esc_attr(attachment.path)}\')"' if attachment.path else ''
        return (
            f'<span class="inline-file-ref" {onclick}>'
            f'<span class="ref-icon">{SVG_FILE}</span>'
            f'<span class="ref-name">{self._esc_html(display_name)}</span>'
            f'</span>'
        )

    def _render_attachments_html(self, attachments: List[Attachment]) -> str:
        gallery_items: List[str] = []
        for attachment in attachments:
            if attachment.type == "image":
                if not attachment.path:
                    continue
                image_url = self._local_file_url(attachment.path)
                display_name = attachment.name or 'image'
                gallery_items.append(
                    f'<div class="image-thumb" onclick="onFileClick(\'{self._esc_attr(attachment.path)}\')">'
                    f'<img src="{self._esc_attr(image_url)}" alt="{self._esc_html(display_name)}">'
                    f'<span class="image-caption">{self._esc_html(self._truncate_attachment_name(display_name, 28))}</span>'
                    f'</div>'
                )
                continue
            if attachment.placement == INLINE_ATTACHMENT_PLACEMENT:
                continue
            display_name = attachment.name or '文件'
            gallery_items.append(
                f'<div class="gallery-file-ref" onclick="onFileClick(\'{self._esc_attr(attachment.path)}\')">'
                f'<span class="ref-icon">{SVG_FILE}</span>'
                f'<span class="ref-name">{self._esc_html(self._truncate_attachment_name(display_name, 28))}</span>'
                f'</div>'
            )
        if not gallery_items:
            return ""
        return f'<div class="attachment-gallery">{"".join(gallery_items)}</div>'

    def _local_file_url(self, path: str) -> str:
        return QUrl.fromLocalFile(path).toString()

    def _truncate_attachment_name(self, name: str, limit: int) -> str:
        if len(name) <= limit:
            return name
        base, ext = os.path.splitext(name)
        room = max(4, limit - len(ext) - 3)
        return f'{base[:room]}...{ext}'

    def _get_stop_reason_label(self, reason: str) -> str:
        return {
            'user_requested': '已由用户停止',
            'timeout': '响应超时，已中断',
            'error': '生成出现错误，内容为部分结果',
            'session_switch': '会话切换，中断了当前输出',
            'app_shutdown': '应用关闭，中断了当前输出',
        }.get(reason, '该回复未完整生成')
    
    def _md_to_html(self, text: str) -> str:
        if not text:
            return ""
        try:
            from infrastructure.utils.markdown_renderer import render_markdown
            return render_markdown(text)
        except:
            import html
            return html.escape(text).replace('\n', '<br>')

    def _esc_html(self, text: str) -> str:
        """转义 HTML 特殊字符"""
        import html
        return html.escape(text) if text else ""
    
    def clear_messages(self):
        self._pending_render_state = {
            'messages': '',
            'runtime': '',
        }
        if not self._page_loaded:
            return
        self._run_js(
            "(function(){"
            "if (typeof clearConversation === 'function') { clearConversation(); return; }"
            "var messageRoot = document.getElementById('message-list');"
            "var runtimeRoot = document.getElementById('runtime-steps-root');"
            "if (messageRoot) { messageRoot.innerHTML = ''; }"
            "if (runtimeRoot) { runtimeRoot.innerHTML = ''; }"
            "})();"
        )
    
    def _run_js(self, code: str):
        if not self._web_view:
            return
        if not self._page_loaded:
            return
        self._web_view.page().runJavaScript(code)

    def _esc(self, text: str) -> str:
        """转义 JavaScript 模板字符串中的特殊字符"""
        return text.replace('\\', '\\\\').replace('`', '\\`').replace('$', '\\$').replace('\r', '').replace('\n', '\\n')
    
    def _esc_attr(self, text: str) -> str:
        """转义 HTML 属性中的特殊字符"""
        return text.replace("'", "\\'").replace('"', '\\"').replace('\\', '\\\\')
    
    def cleanup(self):
        self._pending_render_state = None


__all__ = ["WebMessageView", "WEBENGINE_AVAILABLE"]
