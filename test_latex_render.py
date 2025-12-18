#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""测试 LaTeX 渲染"""

import sys
from pathlib import Path

# 添加项目路径
sys.path.insert(0, str(Path(__file__).parent))

def test_katex_resources():
    """测试 KaTeX 资源加载"""
    print("=" * 50)
    print("测试 1: KaTeX 资源加载")
    print("=" * 50)
    
    from infrastructure.utils.markdown_renderer import _get_katex_base_path, _load_katex_resources
    
    katex_path = _get_katex_base_path()
    print(f"KaTeX 路径: {katex_path}")
    
    if katex_path:
        print(f"katex.min.js 存在: {(katex_path / 'katex.min.js').exists()}")
        print(f"katex.min.css 存在: {(katex_path / 'katex.min.css').exists()}")
        print(f"auto-render.min.js 存在: {(katex_path / 'contrib' / 'auto-render.min.js').exists()}")
    
    css, js, auto_render = _load_katex_resources()
    print(f"\nCSS 长度: {len(css)}")
    print(f"JS 长度: {len(js)}")
    print(f"Auto-render JS 长度: {len(auto_render)}")
    
    return bool(css and js and auto_render)


def test_markdown_render():
    """测试 Markdown 渲染"""
    print("\n" + "=" * 50)
    print("测试 2: Markdown 渲染")
    print("=" * 50)
    
    from infrastructure.utils.markdown_renderer import render_markdown, get_full_html
    
    # 测试文本
    test_text = """# 测试标题

这是一个行内公式 $x^2 + y^2 = z^2$。

这是一个块级公式：

$$
f(x) = \\frac{1}{\\sqrt{2\\pi}} e^{-\\frac{x^2}{2}}
$$

普通文本继续。
"""
    
    print("原始文本:")
    print(test_text)
    print("\n渲染后的 HTML:")
    html = render_markdown(test_text)
    print(html)
    
    # 检查 LaTeX 是否被保留
    has_inline = '$' in html
    has_block = '$$' in html or 'katex-block' in html
    print(f"\n包含行内公式标记: {has_inline}")
    print(f"包含块级公式标记: {has_block}")
    
    return has_inline or has_block


def test_full_html():
    """测试完整 HTML 生成"""
    print("\n" + "=" * 50)
    print("测试 3: 完整 HTML 生成")
    print("=" * 50)
    
    from infrastructure.utils.markdown_renderer import get_full_html
    
    test_text = "公式 $E = mc^2$ 和 $$\\int_0^1 x^2 dx$$"
    
    full_html = get_full_html(test_text)
    
    print(f"HTML 长度: {len(full_html)}")
    print(f"包含 KaTeX CSS: {'katex' in full_html.lower()}")
    print(f"包含 renderMathInElement: {'renderMathInElement' in full_html}")
    
    # 保存到文件以便查看
    output_path = Path(__file__).parent / "test_output.html"
    output_path.write_text(full_html, encoding='utf-8')
    print(f"\n已保存到: {output_path}")
    
    return len(full_html) > 1000


def test_webengine():
    """测试 WebEngine 是否可用"""
    print("\n" + "=" * 50)
    print("测试 4: WebEngine 可用性")
    print("=" * 50)
    
    try:
        from PyQt6.QtWebEngineWidgets import QWebEngineView
        print("PyQt6.QtWebEngineWidgets 可用")
        return True
    except ImportError as e:
        print(f"PyQt6.QtWebEngineWidgets 不可用: {e}")
        return False


if __name__ == "__main__":
    results = []
    
    results.append(("KaTeX 资源加载", test_katex_resources()))
    results.append(("Markdown 渲染", test_markdown_render()))
    results.append(("完整 HTML 生成", test_full_html()))
    results.append(("WebEngine 可用性", test_webengine()))
    
    print("\n" + "=" * 50)
    print("测试结果汇总")
    print("=" * 50)
    for name, passed in results:
        status = "✓ 通过" if passed else "✗ 失败"
        print(f"{name}: {status}")
