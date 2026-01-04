# Prompt Variable Panel
"""
变量面板组件 - 横向流式布局显示模板变量

职责：
- 以横向按钮块形式显示当前模板的变量
- 支持点击插入变量到编辑器
- 自动换行，节省垂直空间

设计原则：
- 使用 FlowLayout 实现横向排列，超出宽度自动换行
- 变量显示为紧凑的按钮块，必需变量带星号标记
- 单击即可插入，无需额外的"插入"按钮
"""

from typing import List, Optional

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QPushButton, QSizePolicy, QLayout
)
from PyQt6.QtCore import Qt, pyqtSignal, QSize, QRect, QPoint


class FlowLayout(QLayout):
    """
    流式布局 - 横向排列，超出宽度自动换行
    
    参考 Qt 官方 FlowLayout 示例实现
    """
    
    def __init__(self, parent: Optional[QWidget] = None, margin: int = 0, spacing: int = 6):
        super().__init__(parent)
        self._items = []
        self._h_spacing = spacing
        self._v_spacing = spacing
        self.setContentsMargins(margin, margin, margin, margin)
    
    def addItem(self, item):
        self._items.append(item)
    
    def count(self):
        return len(self._items)
    
    def itemAt(self, index):
        if 0 <= index < len(self._items):
            return self._items[index]
        return None
    
    def takeAt(self, index):
        if 0 <= index < len(self._items):
            return self._items.pop(index)
        return None
    
    def expandingDirections(self):
        return Qt.Orientation(0)
    
    def hasHeightForWidth(self):
        return True
    
    def heightForWidth(self, width):
        return self._do_layout(QRect(0, 0, width, 0), test_only=True)
    
    def setGeometry(self, rect):
        super().setGeometry(rect)
        self._do_layout(rect, test_only=False)
    
    def sizeHint(self):
        return self.minimumSize()
    
    def minimumSize(self):
        size = QSize()
        for item in self._items:
            size = size.expandedTo(item.minimumSize())
        margins = self.contentsMargins()
        size += QSize(margins.left() + margins.right(), margins.top() + margins.bottom())
        return size
    
    def _do_layout(self, rect, test_only):
        margins = self.contentsMargins()
        effective_rect = rect.adjusted(margins.left(), margins.top(), -margins.right(), -margins.bottom())
        x = effective_rect.x()
        y = effective_rect.y()
        line_height = 0
        
        for item in self._items:
            widget = item.widget()
            if widget is None:
                continue
            
            space_x = self._h_spacing
            space_y = self._v_spacing
            
            next_x = x + item.sizeHint().width() + space_x
            if next_x - space_x > effective_rect.right() and line_height > 0:
                x = effective_rect.x()
                y = y + line_height + space_y
                next_x = x + item.sizeHint().width() + space_x
                line_height = 0
            
            if not test_only:
                item.setGeometry(QRect(QPoint(x, y), item.sizeHint()))
            
            x = next_x
            line_height = max(line_height, item.sizeHint().height())
        
        return y + line_height - rect.y() + margins.bottom()
    
    def clear(self):
        """清空所有项"""
        while self._items:
            item = self._items.pop()
            widget = item.widget()
            if widget:
                widget.deleteLater()


class VariableButton(QPushButton):
    """
    变量按钮 - 紧凑的可点击变量标签
    """
    
    def __init__(self, var_name: str, is_required: bool = False, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self._var_name = var_name
        self._is_required = is_required
        self._setup_ui()
    
    def _setup_ui(self):
        # 显示文本：{变量名} 或 {变量名} *
        display_text = f"{{{self._var_name}}}"
        if self._is_required:
            display_text += " *"
        self.setText(display_text)
        
        # 样式
        base_style = """
            QPushButton {
                padding: 4px 8px;
                border: 1px solid #ccc;
                border-radius: 4px;
                background-color: #f5f5f5;
                font-family: Consolas, Monaco, monospace;
                font-size: 12px;
            }
            QPushButton:hover {
                background-color: #e3f2fd;
                border-color: #2196f3;
            }
            QPushButton:pressed {
                background-color: #bbdefb;
            }
        """
        
        if self._is_required:
            # 必需变量使用蓝色边框
            base_style = """
                QPushButton {
                    padding: 4px 8px;
                    border: 1px solid #1976d2;
                    border-radius: 4px;
                    background-color: #e3f2fd;
                    font-family: Consolas, Monaco, monospace;
                    font-size: 12px;
                    font-weight: bold;
                }
                QPushButton:hover {
                    background-color: #bbdefb;
                    border-color: #1565c0;
                }
                QPushButton:pressed {
                    background-color: #90caf9;
                }
            """
        
        self.setStyleSheet(base_style)
        
        # Tooltip
        tooltip = self._get_text(
            "dialog.prompt_editor.required_variable" if self._is_required else "dialog.prompt_editor.optional_variable",
            "Required variable, click to insert" if self._is_required else "Optional variable, click to insert"
        )
        self.setToolTip(tooltip)
        
        # 尺寸策略
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
    
    def _get_text(self, key: str, default: str) -> str:
        """获取国际化文本"""
        try:
            from shared.service_locator import ServiceLocator
            from shared.service_names import SVC_I18N_MANAGER
            i18n = ServiceLocator.get_optional(SVC_I18N_MANAGER)
            if i18n:
                return i18n.get_text(key, default)
        except Exception:
            pass
        return default
    
    @property
    def var_name(self) -> str:
        return self._var_name
    
    @property
    def is_required(self) -> bool:
        return self._is_required


class PromptVariablePanel(QWidget):
    """
    变量面板组件 - 横向流式布局
    
    Signals:
        variable_insert_requested(str): 请求插入变量（格式：{var_name}）
    """
    
    variable_insert_requested = pyqtSignal(str)
    
    def __init__(self, parent: Optional[QWidget] = None, show_label: bool = True):
        """
        初始化变量面板
        
        Args:
            parent: 父组件
            show_label: 是否显示"变量："标签（自由模式下可隐藏以节省空间）
        """
        super().__init__(parent)
        self._variables: List[str] = []
        self._required_variables: List[str] = []
        self._show_label = show_label
        self._buttons: List[VariableButton] = []
        self._setup_ui()
    
    def _setup_ui(self) -> None:
        """初始化 UI"""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)
        
        # 标签行（可选）
        if self._show_label:
            header_layout = QHBoxLayout()
            header_layout.setContentsMargins(0, 0, 0, 0)
            header_layout.setSpacing(8)
            
            label = QLabel(self._get_text("dialog.prompt_editor.variables", "Variables"))
            label.setStyleSheet("font-weight: bold; color: #555;")
            header_layout.addWidget(label)
            
            # 提示文本
            hint = QLabel(self._get_text(
                "dialog.prompt_editor.variable_hint_short",
                "点击插入"
            ))
            hint.setStyleSheet("color: #888; font-size: 11px;")
            header_layout.addWidget(hint)
            
            header_layout.addStretch()
            layout.addLayout(header_layout)
        
        # 流式布局容器
        self._flow_container = QWidget()
        self._flow_layout = FlowLayout(self._flow_container, margin=0, spacing=6)
        self._flow_container.setLayout(self._flow_layout)
        layout.addWidget(self._flow_container)
        
        # 空状态提示
        self._empty_label = QLabel(self._get_text(
            "dialog.prompt_editor.no_variables",
            "无可用变量"
        ))
        self._empty_label.setStyleSheet("color: #aaa; font-style: italic;")
        self._empty_label.setVisible(False)
        layout.addWidget(self._empty_label)
    
    def _get_text(self, key: str, default: str) -> str:
        """获取国际化文本"""
        try:
            from shared.service_locator import ServiceLocator
            from shared.service_names import SVC_I18N_MANAGER
            i18n = ServiceLocator.get_optional(SVC_I18N_MANAGER)
            if i18n:
                return i18n.get_text(key, default)
        except Exception:
            pass
        return default
    
    def set_variables(
        self,
        variables: List[str],
        required_variables: Optional[List[str]] = None
    ) -> None:
        """
        设置变量列表
        
        Args:
            variables: 所有变量列表
            required_variables: 必需变量列表
        """
        self._variables = variables or []
        self._required_variables = required_variables or []
        self._update_buttons()
    
    def _update_buttons(self) -> None:
        """更新按钮显示"""
        # 清空现有按钮
        self._flow_layout.clear()
        self._buttons.clear()
        
        if not self._variables:
            self._empty_label.setVisible(True)
            self._flow_container.setVisible(False)
            return
        
        self._empty_label.setVisible(False)
        self._flow_container.setVisible(True)
        
        # 创建变量按钮
        for var in self._variables:
            is_required = var in self._required_variables
            btn = VariableButton(var, is_required, self._flow_container)
            btn.clicked.connect(lambda checked, v=var: self._on_button_clicked(v))
            self._flow_layout.addWidget(btn)
            self._buttons.append(btn)
        
        # 强制更新布局
        self._flow_container.updateGeometry()
    
    def _on_button_clicked(self, var_name: str) -> None:
        """按钮点击处理"""
        self.variable_insert_requested.emit(f"{{{var_name}}}")
    
    def clear(self) -> None:
        """清空变量列表"""
        self._variables = []
        self._required_variables = []
        self._flow_layout.clear()
        self._buttons.clear()
        self._empty_label.setVisible(True)
        self._flow_container.setVisible(False)
    
    def get_selected_variable(self) -> Optional[str]:
        """获取当前选中的变量（兼容旧接口）"""
        # 流式布局没有选中概念，返回 None
        return None


__all__ = ["PromptVariablePanel", "FlowLayout", "VariableButton"]
