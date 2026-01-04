#!/usr/bin/env python
"""
测试工具栏按钮的响应性
"""

import sys
from PyQt6.QtWidgets import QApplication, QMainWindow, QMessageBox
from presentation.toolbar_manager import ToolbarManager
from presentation.action_handlers import ActionHandlers

def test_toolbar_buttons():
    """测试工具栏按钮"""
    app = QApplication(sys.argv)
    
    # 创建主窗口
    main_window = QMainWindow()
    main_window.setWindowTitle("Toolbar Button Test")
    main_window.resize(800, 600)
    
    # 创建动作处理器
    action_handlers = ActionHandlers(main_window, {})
    callbacks = action_handlers.get_callbacks()
    
    # 创建工具栏管理器
    toolbar_manager = ToolbarManager(main_window)
    toolbar = toolbar_manager.setup_toolbar(callbacks)
    
    # 刷新文本
    toolbar_manager.retranslate_ui()
    
    # 检查仿真按钮
    run_auto = toolbar_manager.get_action("toolbar_run_auto")
    run_select = toolbar_manager.get_action("toolbar_run_select")
    stop = toolbar_manager.get_action("toolbar_stop")
    
    print("=" * 60)
    print("工具栏按钮测试")
    print("=" * 60)
    
    if run_auto:
        print(f"\n[▶ 自动运行] 按钮:")
        print(f"  - 已创建: ✓")
        print(f"  - 启用状态: {run_auto.isEnabled()}")
        print(f"  - 工具提示: {run_auto.toolTip()}")
        print(f"  - 已连接信号: {run_auto.receivers(run_auto.triggered) > 0}")
    
    if run_select:
        print(f"\n[📁 选择运行] 按钮:")
        print(f"  - 已创建: ✓")
        print(f"  - 启用状态: {run_select.isEnabled()}")
        print(f"  - 工具提示: {run_select.toolTip()}")
        print(f"  - 已连接信号: {run_select.receivers(run_select.triggered) > 0}")
    
    if stop:
        print(f"\n[停止] 按钮:")
        print(f"  - 已创建: ✓")
        print(f"  - 启用状态: {stop.isEnabled()}")
        print(f"  - 工具提示: {stop.toolTip()}")
        print(f"  - 已连接信号: {stop.receivers(stop.triggered) > 0}")
    
    print("\n" + "=" * 60)
    print("测试完成！")
    print("=" * 60)
    
    # 显示窗口
    main_window.show()
    
    # 提示用户测试
    QMessageBox.information(
        main_window,
        "测试说明",
        "请测试以下功能：\n\n"
        "1. 鼠标悬停在仿真按钮上，查看工具提示\n"
        "2. 点击仿真按钮，查看是否弹出对话框\n\n"
        "测试完成后关闭窗口。"
    )
    
    sys.exit(app.exec())

if __name__ == "__main__":
    test_toolbar_buttons()
