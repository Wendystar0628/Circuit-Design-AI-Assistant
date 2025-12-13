# Presentation Layer
"""
表示层 - UI面板、对话框、用户交互

包含：
- main_window.py: 主窗口
- panels/: UI面板（文件浏览器、代码编辑器、对话面板、仿真结果）
- dialogs/: 对话框（API配置、关于、设置等）
- widgets/: 自定义控件
"""

from presentation.main_window import MainWindow

__all__ = [
    "MainWindow",
]
