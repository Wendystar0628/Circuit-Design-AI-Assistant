from infrastructure.utils.markdown_renderer import render_markdown


def test_pipe_table_renders_without_blank_line_before_table_block():
    html = render_markdown(
        "适用于状态-动作空间较小的离散环境：\n"
        "| 方法 | 更新方式 | On/Off-policy | 特点 |\n"
        "|------|---------|---------------|------|\n"
        "| 动态规划 (DP) | 基于完整环境模型迭代 | - | 策略迭代/价值迭代 |"
    )

    assert "<table>" in html
    assert "<th>方法</th>" in html
    assert "<td>动态规划 (DP)</td>" in html


def test_pipe_table_preserves_inline_math_tokens_for_katex_rendering():
    html = render_markdown(
        "Intro\n"
        "| A | B |\n"
        "|---|---|\n"
        "| x | $y$ |"
    )

    assert "<table>" in html
    assert "$y$" in html
