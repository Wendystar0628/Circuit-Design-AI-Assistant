# Markdown Renderer with LaTeX Support
"""
Markdown 渲染器（含 LaTeX 支持）

职责：
- 将 Markdown 文本转换为 HTML
- 支持 LaTeX 数学公式渲染（通过 KaTeX）
- 提供代码块语法高亮
- 生成完整的 HTML 页面模板

使用示例：
    from infrastructure.utils.markdown_renderer import MarkdownRenderer
    
    renderer = MarkdownRenderer()
    html = renderer.render_markdown("# Hello $x^2$")
    full_html = renderer.get_full_html_template(html)
"""

import os
import re
import base64
from pathlib import Path
from typing import Optional, Tuple

try:
    import markdown
    from markdown.extensions import fenced_code, tables, nl2br
    MARKDOWN_AVAILABLE = True
except ImportError:
    MARKDOWN_AVAILABLE = False


# ============================================================
# 常量定义
# ============================================================

# KaTeX CDN URLs (fallback if local files not available)
KATEX_CSS_CDN = "https://cdn.jsdelivr.net/npm/katex@0.16.9/dist/katex.min.css"
KATEX_JS_CDN = "https://cdn.jsdelivr.net/npm/katex@0.16.9/dist/katex.min.js"
KATEX_AUTO_RENDER_CDN = "https://cdn.jsdelivr.net/npm/katex@0.16.9/dist/contrib/auto-render.min.js"

# 缓存内联资源
_KATEX_INLINE_CACHE: Optional[Tuple[str, str, str]] = None  # (css, js, auto_render_js)


def _get_katex_base_path() -> Optional[Path]:
    """
    获取 KaTeX 资源文件的本地路径
    
    Returns:
        KaTeX 目录的 Path 对象，如果不存在则返回 None
    """
    # 从当前文件位置推算 resources/katex 路径
    current_file = Path(__file__).resolve()
    project_root = current_file.parent.parent.parent  # circuit_design_ai/
    katex_path = project_root / "resources" / "katex"
    
    if katex_path.exists() and (katex_path / "katex.min.js").exists():
        return katex_path
    return None


def _inline_fonts_in_css(css_content: str, fonts_dir: Path) -> str:
    """
    将 CSS 中的字体引用替换为 base64 内联数据
    
    Args:
        css_content: CSS 文件内容
        fonts_dir: 字体文件目录
        
    Returns:
        处理后的 CSS 内容
    """
    def replace_font_url(match):
        url = match.group(1)
        # 提取文件名
        font_file = url.split('/')[-1].split('?')[0].split('#')[0]
        font_path = fonts_dir / font_file
        
        if font_path.exists():
            try:
                font_data = font_path.read_bytes()
                font_base64 = base64.b64encode(font_data).decode('ascii')
                
                # 根据文件扩展名确定 MIME 类型
                if font_file.endswith('.woff2'):
                    mime = 'font/woff2'
                elif font_file.endswith('.woff'):
                    mime = 'font/woff'
                elif font_file.endswith('.ttf'):
                    mime = 'font/ttf'
                else:
                    mime = 'application/octet-stream'
                
                return f'url(data:{mime};base64,{font_base64})'
            except Exception:
                pass
        
        return match.group(0)  # 保持原样
    
    # 匹配 url(fonts/...) 或 url("fonts/...") 或 url('fonts/...')
    pattern = r'url\(["\']?(fonts/[^"\')\s]+)["\']?\)'
    return re.sub(pattern, replace_font_url, css_content)


def _load_katex_resources() -> Tuple[str, str, str]:
    """
    加载 KaTeX 资源文件内容（内联方式）
    
    Returns:
        (css_content, js_content, auto_render_js_content)
    """
    global _KATEX_INLINE_CACHE
    
    if _KATEX_INLINE_CACHE is not None:
        return _KATEX_INLINE_CACHE
    
    katex_path = _get_katex_base_path()
    if katex_path is None:
        return ("", "", "")
    
    try:
        # 读取 CSS 并处理字体路径
        css_path = katex_path / "katex.min.css"
        css_content = css_path.read_text(encoding='utf-8')
        
        # 将字体文件转换为 base64 内联（避免 file:// 协议问题）
        css_content = _inline_fonts_in_css(css_content, katex_path / "fonts")
        
        # 读取 JS
        js_path = katex_path / "katex.min.js"
        js_content = js_path.read_text(encoding='utf-8')
        
        # 读取 auto-render
        auto_render_path = katex_path / "contrib" / "auto-render.min.js"
        auto_render_content = auto_render_path.read_text(encoding='utf-8')
        
        _KATEX_INLINE_CACHE = (css_content, js_content, auto_render_content)
        return _KATEX_INLINE_CACHE
        
    except Exception as e:
        print(f"[MarkdownRenderer] Failed to load KaTeX resources: {e}")
        return ("", "", "")


# ============================================================
# MarkdownRenderer 类
# ============================================================

class MarkdownRenderer:
    """
    Markdown 渲染器
    
    支持 Markdown 转 HTML，包含 LaTeX 公式渲染。
    """
    
    def __init__(self, use_local_katex: bool = True):
        """
        初始化渲染器
        
        Args:
            use_local_katex: 是否使用本地 KaTeX 文件
        """
        self._use_local_katex = use_local_katex
        self._katex_base_path = _get_katex_base_path() if use_local_katex else None
        self._md = None
        
        if MARKDOWN_AVAILABLE:
            self._md = markdown.Markdown(
                extensions=[
                    'fenced_code',
                    'tables',
                    'nl2br',
                ],
                output_format='html5'
            )
    
    def render_markdown(self, text: str) -> str:
        """
        将 Markdown 转换为 HTML
        
        Args:
            text: Markdown 文本
            
        Returns:
            HTML 字符串
        """
        if not text:
            return ""
        
        # 保护 LaTeX 公式不被 Markdown 解析器处理
        text, latex_blocks = self._protect_latex(text)
        
        # Markdown 转 HTML
        if self._md:
            self._md.reset()
            html = self._md.convert(text)
        else:
            # 简单回退：基本转义和换行
            html = self._simple_markdown(text)
        
        # 恢复 LaTeX 公式
        html = self._restore_latex(html, latex_blocks)
        
        return html
    
    def _protect_latex(self, text: str) -> tuple:
        """
        保护 LaTeX 公式，避免被 Markdown 解析器破坏
        
        Args:
            text: 原始文本
            
        Returns:
            (处理后的文本, LaTeX 块列表)
        """
        latex_blocks = []
        
        # 保护块级公式 $$...$$
        def replace_block(match):
            idx = len(latex_blocks)
            latex_blocks.append(('block', match.group(1)))
            return f'LATEX_BLOCK_{idx}_PLACEHOLDER'
        
        # 匹配 $$...$$ (块级公式)
        block_pattern = r'\$\$(.+?)\$\$'
        text = re.sub(block_pattern, replace_block, text, flags=re.DOTALL)
        
        # 保护行内公式 $...$（但不匹配 $$）
        def replace_inline(match):
            idx = len(latex_blocks)
            latex_blocks.append(('inline', match.group(1)))
            return f'LATEX_INLINE_{idx}_PLACEHOLDER'
        
        # 匹配 $...$ (行内公式，排除 $$)
        inline_pattern = r'(?<!\$)\$(?!\$)(.+?)(?<!\$)\$(?!\$)'
        text = re.sub(inline_pattern, replace_inline, text)
        
        return text, latex_blocks
    
    def _restore_latex(self, html: str, latex_blocks: list) -> str:
        """
        恢复 LaTeX 公式
        
        Args:
            html: HTML 文本
            latex_blocks: LaTeX 块列表
            
        Returns:
            恢复后的 HTML
        """
        for idx, (block_type, content) in enumerate(latex_blocks):
            if block_type == 'block':
                placeholder = f'LATEX_BLOCK_{idx}_PLACEHOLDER'
                # 块级公式使用 div 包裹，保留 $$ 分隔符
                replacement = f'<div class="katex-block">$${content}$$</div>'
            else:
                placeholder = f'LATEX_INLINE_{idx}_PLACEHOLDER'
                # 行内公式直接使用 $...$ 分隔符
                replacement = f'${content}$'
            
            html = html.replace(placeholder, replacement)
        
        return html
    
    def _simple_markdown(self, text: str) -> str:
        """简单的 Markdown 转换（回退方案）"""
        # 转义 HTML
        html = text.replace("&", "&amp;")
        html = html.replace("<", "&lt;")
        html = html.replace(">", "&gt;")
        
        # 换行
        html = html.replace("\n", "<br>")
        
        # 粗体
        html = re.sub(r'\*\*(.+?)\*\*', r'<strong>\1</strong>', html)
        
        # 斜体
        html = re.sub(r'\*(.+?)\*', r'<em>\1</em>', html)
        
        # 行内代码
        html = re.sub(r'`(.+?)`', r'<code>\1</code>', html)
        
        return html
    
    def render_code_block(self, code: str, language: str = "") -> str:
        """
        渲染代码块
        
        Args:
            code: 代码内容
            language: 语言类型
            
        Returns:
            HTML 字符串
        """
        # 转义 HTML
        escaped = code.replace("&", "&amp;")
        escaped = escaped.replace("<", "&lt;")
        escaped = escaped.replace(">", "&gt;")
        
        lang_class = f' class="language-{language}"' if language else ''
        return f'<pre><code{lang_class}>{escaped}</code></pre>'
    
    def get_full_html_template(self, content_html: str, title: str = "") -> str:
        """
        生成包含 KaTeX 的完整 HTML 页面（使用内联资源）
        
        Args:
            content_html: 内容 HTML
            title: 页面标题
            
        Returns:
            完整的 HTML 页面
        """
        katex_resources = self._get_inline_katex_resources()
        
        html_template = '''<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{title}</title>
    <style>
{katex_css}
    </style>
    <style>
{stylesheet}
    </style>
</head>
<body>
    <div id="content">
{content}
    </div>
    <script>
{katex_js}
    </script>
    <script>
{auto_render_js}
    </script>
    <script>
        document.addEventListener("DOMContentLoaded", function() {{
            if (typeof renderMathInElement !== 'undefined') {{
                renderMathInElement(document.body, {{
                    delimiters: [
                        {{left: "$$", right: "$$", display: true}},
                        {{left: "$", right: "$", display: false}}
                    ],
                    throwOnError: false
                }});
            }}
        }});
    </script>
</body>
</html>'''
        
        return html_template.format(
            title=title,
            katex_css=katex_resources[0],
            stylesheet=self.get_stylesheet(),
            content=content_html,
            katex_js=katex_resources[1],
            auto_render_js=katex_resources[2]
        )
    
    def _get_inline_katex_resources(self) -> Tuple[str, str, str]:
        """获取内联的 KaTeX 资源"""
        if self._use_local_katex:
            resources = _load_katex_resources()
            if resources[0]:  # 如果成功加载
                return resources
        
        # 回退到 CDN（返回空字符串，使用外部链接）
        return ("", "", "")
    
    def get_full_html_template_cdn(self, content_html: str, title: str = "") -> str:
        """
        生成包含 KaTeX 的完整 HTML 页面（使用 CDN）
        
        Args:
            content_html: 内容 HTML
            title: 页面标题
            
        Returns:
            完整的 HTML 页面
        """
        html_template = '''<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{title}</title>
    <link rel="stylesheet" href="{katex_css_cdn}">
    <style>
{stylesheet}
    </style>
</head>
<body>
    <div id="content">
{content}
    </div>
    <script src="{katex_js_cdn}"></script>
    <script src="{auto_render_cdn}"></script>
    <script>
        document.addEventListener("DOMContentLoaded", function() {{
            if (typeof renderMathInElement !== 'undefined') {{
                renderMathInElement(document.body, {{
                    delimiters: [
                        {{left: "$$", right: "$$", display: true}},
                        {{left: "$", right: "$", display: false}}
                    ],
                    throwOnError: false
                }});
            }}
        }});
    </script>
</body>
</html>'''
        
        return html_template.format(
            title=title,
            katex_css_cdn=KATEX_CSS_CDN,
            stylesheet=self.get_stylesheet(),
            content=content_html,
            katex_js_cdn=KATEX_JS_CDN,
            auto_render_cdn=KATEX_AUTO_RENDER_CDN
        )

    def get_stylesheet(self) -> str:
        """获取渲染样式表"""
        return '''
        * {
            margin: 0;
            padding: 0;
            box-sizing: border-box;
        }
        
        body {
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif;
            font-size: 14px;
            line-height: 1.6;
            color: #333333;
            background-color: transparent;
            padding: 0;
        }
        
        #content {
            padding: 0;
        }
        
        /* 标题 */
        h1, h2, h3, h4, h5, h6 {
            margin-top: 16px;
            margin-bottom: 8px;
            font-weight: 600;
            line-height: 1.25;
        }
        
        h1 { font-size: 1.5em; }
        h2 { font-size: 1.3em; }
        h3 { font-size: 1.1em; }
        
        /* 段落 */
        p {
            margin-bottom: 8px;
        }
        
        /* 列表 */
        ul, ol {
            margin-left: 20px;
            margin-bottom: 8px;
        }
        
        li {
            margin-bottom: 4px;
        }
        
        /* 代码块 */
        pre {
            background-color: #f5f5f5;
            border-radius: 6px;
            padding: 12px;
            overflow-x: auto;
            margin-bottom: 12px;
        }
        
        code {
            font-family: "SF Mono", Monaco, "Cascadia Code", "Roboto Mono", Consolas, monospace;
            font-size: 13px;
        }
        
        /* 行内代码 */
        :not(pre) > code {
            background-color: #f0f0f0;
            padding: 2px 6px;
            border-radius: 4px;
        }
        
        /* 表格 */
        table {
            border-collapse: collapse;
            width: 100%;
            margin-bottom: 12px;
        }
        
        th, td {
            border: 1px solid #e0e0e0;
            padding: 8px 12px;
            text-align: left;
        }
        
        th {
            background-color: #f5f5f5;
            font-weight: 600;
        }
        
        /* 链接 */
        a {
            color: #4a9eff;
            text-decoration: none;
        }
        
        a:hover {
            text-decoration: underline;
        }
        
        /* LaTeX 块级公式 */
        .katex-block {
            text-align: center;
            margin: 12px 0;
            overflow-x: auto;
        }
        
        /* KaTeX 样式调整 */
        .katex {
            font-size: 1.1em;
        }
        
        .katex-display {
            margin: 12px 0;
            overflow-x: auto;
            overflow-y: hidden;
        }
        '''


# ============================================================
# 便捷函数
# ============================================================

_default_renderer: Optional[MarkdownRenderer] = None

def get_renderer() -> MarkdownRenderer:
    """获取默认渲染器实例"""
    global _default_renderer
    if _default_renderer is None:
        _default_renderer = MarkdownRenderer()
    return _default_renderer

def render_markdown(text: str) -> str:
    """便捷函数：渲染 Markdown"""
    return get_renderer().render_markdown(text)

def get_full_html(content: str, title: str = "") -> str:
    """便捷函数：生成完整 HTML 页面"""
    html = get_renderer().render_markdown(content)
    return get_renderer().get_full_html_template(html, title)


# ============================================================
# 模块导出
# ============================================================

__all__ = [
    "MarkdownRenderer",
    "render_markdown",
    "get_full_html",
    "get_renderer",
]
