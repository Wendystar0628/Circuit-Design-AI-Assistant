# About Dialog
"""
关于对话框

职责：
- 显示软件版本、许可证信息、第三方组件声明

触发方式：
- 帮助菜单 → 关于

国际化支持：
- 实现 retranslate_ui() 方法
- 订阅 EVENT_LANGUAGE_CHANGED 事件
"""

from typing import Optional, Dict, Any

from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout,
    QLabel, QPushButton, QWidget, QScrollArea, QFrame
)
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QFont


# ============================================================
# 版本信息
# ============================================================

APP_VERSION = "0.1.0"
APP_COPYRIGHT = "Copyright 2024-2025"


# ============================================================
# 第三方许可证声明
# ============================================================

THIRD_PARTY_LICENSES = """
This software uses the following third-party components:

ngspice - Open Source SPICE Simulator
License: BSD-3-Clause
https://ngspice.sourceforge.io/

PyQt6 - Python bindings for Qt
License: GPL v3 / Commercial
https://www.riverbankcomputing.com/software/pyqt/

LangGraph - Framework for building stateful AI agents
License: MIT
https://github.com/langchain-ai/langgraph

Zhipu AI GLM - Large Language Model API
https://open.bigmodel.cn/

Additional Python packages are used under their respective licenses.
See requirements.txt for the complete list.
"""


# ============================================================
# 关于对话框
# ============================================================

class AboutDialog(QDialog):
    """
    关于对话框
    
    显示内容：
    - 软件名称
    - 版本号
    - 版权声明
    - 第三方许可证声明
    """

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        
        # 延迟获取的服务
        self._i18n_manager = None
        self._event_bus = None
        
        # UI 组件引用
        self._title_label: Optional[QLabel] = None
        self._version_label: Optional[QLabel] = None
        self._copyright_label: Optional[QLabel] = None
        self._desc_label: Optional[QLabel] = None
        self._license_label: Optional[QLabel] = None
        self._license_text: Optional[QLabel] = None
        self._close_btn: Optional[QPushButton] = None
        
        # 初始化 UI
        self._setup_dialog()
        self._setup_ui()
        
        # 应用国际化文本
        self.retranslate_ui()
        
        # 订阅事件
        self._subscribe_events()


    # ============================================================
    # 延迟获取服务
    # ============================================================

    @property
    def i18n_manager(self):
        """延迟获取 I18nManager"""
        if self._i18n_manager is None:
            try:
                from shared.service_locator import ServiceLocator
                from shared.service_names import SVC_I18N_MANAGER
                self._i18n_manager = ServiceLocator.get_optional(SVC_I18N_MANAGER)
            except Exception:
                pass
        return self._i18n_manager

    @property
    def event_bus(self):
        """延迟获取 EventBus"""
        if self._event_bus is None:
            try:
                from shared.service_locator import ServiceLocator
                from shared.service_names import SVC_EVENT_BUS
                self._event_bus = ServiceLocator.get_optional(SVC_EVENT_BUS)
            except Exception:
                pass
        return self._event_bus

    def _get_text(self, key: str, default: Optional[str] = None) -> str:
        """获取国际化文本"""
        if self.i18n_manager:
            return self.i18n_manager.get_text(key, default)
        return default if default else key


    # ============================================================
    # UI 初始化
    # ============================================================

    def _setup_dialog(self):
        """设置对话框基本属性"""
        self.setWindowFlags(
            self.windowFlags() & ~Qt.WindowType.WindowContextHelpButtonHint
        )
        self.setFixedSize(450, 420)
        self.setModal(True)

    def _setup_ui(self):
        """设置 UI 布局"""
        main_layout = QVBoxLayout(self)
        main_layout.setSpacing(15)
        main_layout.setContentsMargins(30, 30, 30, 20)
        
        # 标题区域
        main_layout.addWidget(self._create_header())
        
        # 分隔线
        line = QFrame()
        line.setFrameShape(QFrame.Shape.HLine)
        line.setStyleSheet("background-color: #e0e0e0;")
        main_layout.addWidget(line)
        
        # 许可证区域
        main_layout.addWidget(self._create_license_area(), 1)
        
        # 关闭按钮
        main_layout.addWidget(self._create_button_area())

    def _create_header(self) -> QWidget:
        """创建标题区域"""
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setSpacing(8)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        
        # 软件名称
        self._title_label = QLabel()
        title_font = QFont()
        title_font.setPointSize(18)
        title_font.setBold(True)
        self._title_label.setFont(title_font)
        self._title_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._title_label.setStyleSheet("color: #333;")
        layout.addWidget(self._title_label)
        
        # 版本号
        self._version_label = QLabel()
        self._version_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._version_label.setStyleSheet("color: #666; font-size: 13px;")
        layout.addWidget(self._version_label)
        
        # 描述
        self._desc_label = QLabel()
        self._desc_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._desc_label.setStyleSheet("color: #666; font-size: 12px;")
        self._desc_label.setWordWrap(True)
        layout.addWidget(self._desc_label)
        
        # 版权声明
        self._copyright_label = QLabel()
        self._copyright_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._copyright_label.setStyleSheet("color: #888; font-size: 11px;")
        layout.addWidget(self._copyright_label)
        
        return widget


    def _create_license_area(self) -> QWidget:
        """创建许可证区域"""
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setSpacing(8)
        layout.setContentsMargins(0, 0, 0, 0)
        
        # 许可证标题
        self._license_label = QLabel()
        self._license_label.setStyleSheet("color: #333; font-weight: bold;")
        layout.addWidget(self._license_label)
        
        # 许可证内容（滚动区域）
        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_area.setStyleSheet(
            "QScrollArea { border: 1px solid #e0e0e0; border-radius: 4px; }"
        )
        
        self._license_text = QLabel(THIRD_PARTY_LICENSES)
        self._license_text.setWordWrap(True)
        self._license_text.setAlignment(Qt.AlignmentFlag.AlignTop)
        self._license_text.setStyleSheet(
            "color: #555; font-size: 11px; padding: 10px; background-color: #f8f9fa;"
        )
        self._license_text.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
        )
        
        scroll_area.setWidget(self._license_text)
        layout.addWidget(scroll_area)
        
        return widget

    def _create_button_area(self) -> QWidget:
        """创建按钮区域"""
        widget = QWidget()
        layout = QHBoxLayout(widget)
        layout.setContentsMargins(0, 10, 0, 0)
        
        layout.addStretch()
        
        # 关闭按钮
        self._close_btn = QPushButton()
        self._close_btn.setMinimumWidth(100)
        self._close_btn.setStyleSheet(
            "QPushButton { background-color: #4a9eff; color: white; "
            "border: none; border-radius: 4px; padding: 8px 20px; }"
            "QPushButton:hover { background-color: #3d8ce6; }"
        )
        self._close_btn.clicked.connect(self.accept)
        layout.addWidget(self._close_btn)
        
        layout.addStretch()
        
        return widget


    # ============================================================
    # 国际化支持
    # ============================================================

    def retranslate_ui(self):
        """刷新所有 UI 文本"""
        # 对话框标题
        self.setWindowTitle(self._get_text("dialog.about.title", "About"))
        
        # 软件名称
        self._title_label.setText(
            self._get_text("app.title", "Circuit AI Design Assistant")
        )
        
        # 版本号
        self._version_label.setText(
            f"{self._get_text('app.version', 'Version')}: {APP_VERSION}"
        )
        
        # 描述
        self._desc_label.setText(
            self._get_text(
                "app.description",
                "An AI-powered circuit design assistant using Zhipu GLM"
            )
        )
        
        # 版权声明
        self._copyright_label.setText(APP_COPYRIGHT)
        
        # 许可证标题
        self._license_label.setText(
            self._get_text("dialog.about.licenses", "Third-Party Licenses")
        )
        
        # 关闭按钮
        self._close_btn.setText(self._get_text("btn.close", "Close"))

    def _subscribe_events(self):
        """订阅事件"""
        if self.event_bus:
            from shared.event_types import EVENT_LANGUAGE_CHANGED
            self.event_bus.subscribe(EVENT_LANGUAGE_CHANGED, self._on_language_changed)

    def _on_language_changed(self, event_data: Dict[str, Any]):
        """语言变更事件处理"""
        self.retranslate_ui()


# ============================================================
# 模块导出
# ============================================================

__all__ = [
    "AboutDialog",
    "APP_VERSION",
]
