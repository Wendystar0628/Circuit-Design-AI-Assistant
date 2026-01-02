# File Browser Panel - File Tree Display
"""
文件浏览器面板 - 显示工作文件夹的文件树

职责：
- 显示工作文件夹的文件树结构
- 响应文件选择事件
- 支持文件过滤和右键菜单

位置：左栏（10%宽度）

设计原则：
- 延迟获取 ServiceLocator 中的服务
- 实现 retranslate_ui() 方法支持语言切换
- 订阅项目打开/关闭事件响应项目切换
"""

import os
import subprocess
import platform
from pathlib import Path
from typing import Optional, Dict, Any

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QTreeView,
    QLabel, QPushButton, QMenu, QApplication,
    QHeaderView, QStyle,
    QStyledItemDelegate, QStyleOptionViewItem
)
from PyQt6.QtCore import (
    Qt, pyqtSignal, QDir, QModelIndex, QSize,
    QSortFilterProxyModel
)
from PyQt6.QtGui import QIcon, QPainter, QColor, QAction, QFileSystemModel


# ============================================================
# 文件过滤常量
# ============================================================

# 允许显示的文件扩展名
ALLOWED_EXTENSIONS = {
    '.cir', '.sp', '.spice',  # SPICE 文件
    '.json',                   # JSON 文件
    '.png', '.jpg', '.jpeg',   # 图片文件
    '.txt',                    # 文本文件
    '.md', '.markdown',        # Markdown 文件
    '.docx',                   # Word 文档
    '.pdf',                    # PDF 文档
    '.py',                     # Python 文件
}

# 隐藏的目录名
HIDDEN_DIRECTORIES = {'.circuit_ai', '__pycache__', '.git', '.vscode'}


# ============================================================
# 文件过滤代理模型
# ============================================================

class FileFilterProxyModel(QSortFilterProxyModel):
    """
    文件过滤代理模型
    
    过滤规则：
    - 隐藏 .circuit_ai/ 等系统目录
    - 只显示允许的文件扩展名
    - 文件夹始终显示（如果包含允许的文件）
    """
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setRecursiveFilteringEnabled(True)
    
    def filterAcceptsRow(self, source_row: int, source_parent: QModelIndex) -> bool:
        """判断是否接受该行"""
        model = self.sourceModel()
        if not model:
            return False
        
        index = model.index(source_row, 0, source_parent)
        if not index.isValid():
            return False
        
        file_path = model.filePath(index)
        file_name = os.path.basename(file_path)
        
        # 隐藏以 . 开头的文件/目录（除了允许的扩展名）
        if file_name.startswith('.') and file_name not in {'.cir', '.sp', '.spice'}:
            # 检查是否是隐藏目录
            if file_name in HIDDEN_DIRECTORIES:
                return False
            # 检查是否是隐藏文件但有允许的扩展名
            ext = os.path.splitext(file_name)[1].lower()
            if ext not in ALLOWED_EXTENSIONS:
                return False
        
        # 如果是目录
        if model.isDir(index):
            # 隐藏特定目录
            if file_name in HIDDEN_DIRECTORIES:
                return False
            # 目录始终显示（递归过滤会处理空目录）
            return True
        
        # 如果是文件，检查扩展名
        ext = os.path.splitext(file_name)[1].lower()
        return ext in ALLOWED_EXTENSIONS


# ============================================================
# 文件浏览器面板
# ============================================================

class FileBrowserPanel(QWidget):
    """
    文件浏览器面板
    
    显示工作文件夹的文件树，响应文件选择事件。
    
    信号：
    - file_selected(str): 文件被选中时发出，携带文件路径
    """
    
    # 文件选中信号
    file_selected = pyqtSignal(str)
    
    def __init__(self, parent=None):
        super().__init__(parent)
        
        # 延迟获取的服务
        self._i18n_manager = None
        self._event_bus = None
        self._logger = None
        
        # 当前根路径
        self._root_path: Optional[str] = None
        
        # UI 组件
        self._title_label: Optional[QLabel] = None
        self._refresh_btn: Optional[QPushButton] = None
        self._collapse_btn: Optional[QPushButton] = None
        self._tree_view: Optional[QTreeView] = None
        self._file_model: Optional[QFileSystemModel] = None
        self._proxy_model: Optional[FileFilterProxyModel] = None
        
        # 右键菜单
        self._context_menu: Optional[QMenu] = None
        self._file_menu_actions: Dict[str, QAction] = {}
        self._folder_menu_actions: Dict[str, QAction] = {}
        
        # 初始化 UI
        self._setup_ui()
        self._setup_style()
        self._setup_context_menu()
        
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

    @property
    def logger(self):
        """延迟获取 Logger"""
        if self._logger is None:
            try:
                from infrastructure.utils.logger import get_logger
                self._logger = get_logger("file_browser_panel")
            except Exception:
                pass
        return self._logger

    def _get_text(self, key: str, default: Optional[str] = None) -> str:
        """获取国际化文本"""
        if self.i18n_manager:
            return self.i18n_manager.get_text(key, default)
        return default if default else key


    # ============================================================
    # UI 初始化
    # ============================================================

    def _setup_ui(self):
        """设置 UI 布局"""
        # 主布局
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        
        # 标题栏
        header = self._create_header()
        layout.addWidget(header)
        
        # 文件树
        self._setup_tree_view()
        layout.addWidget(self._tree_view)

    def _create_header(self) -> QWidget:
        """创建标题栏"""
        header = QWidget()
        header.setFixedHeight(28)
        header.setObjectName("file_browser_header")
        
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(8, 0, 4, 0)
        header_layout.setSpacing(4)
        
        # 标题标签
        self._title_label = QLabel()
        self._title_label.setObjectName("file_browser_title")
        header_layout.addWidget(self._title_label)
        
        header_layout.addStretch()
        
        # 折叠全部按钮
        self._collapse_btn = QPushButton()
        self._collapse_btn.setObjectName("file_browser_btn")
        self._collapse_btn.setFixedSize(20, 20)
        self._collapse_btn.setToolTip("Collapse All")
        self._collapse_btn.clicked.connect(self._on_collapse_all)
        header_layout.addWidget(self._collapse_btn)
        
        # 刷新按钮
        self._refresh_btn = QPushButton()
        self._refresh_btn.setObjectName("file_browser_btn")
        self._refresh_btn.setFixedSize(20, 20)
        self._refresh_btn.setToolTip("Refresh")
        self._refresh_btn.clicked.connect(self.refresh)
        header_layout.addWidget(self._refresh_btn)
        
        return header

    def _setup_tree_view(self):
        """设置文件树视图"""
        # 创建文件系统模型
        self._file_model = QFileSystemModel()
        self._file_model.setReadOnly(True)
        
        # 创建过滤代理模型
        self._proxy_model = FileFilterProxyModel(self)
        self._proxy_model.setSourceModel(self._file_model)
        
        # 创建树视图
        self._tree_view = QTreeView()
        self._tree_view.setObjectName("file_browser_tree")
        self._tree_view.setModel(self._proxy_model)
        
        # 隐藏除名称外的所有列
        self._tree_view.setHeaderHidden(True)
        for i in range(1, 4):  # 隐藏 Size, Type, Date Modified 列
            self._tree_view.hideColumn(i)
        
        # 设置交互行为
        self._tree_view.setAnimated(True)
        self._tree_view.setIndentation(16)
        self._tree_view.setExpandsOnDoubleClick(True)
        self._tree_view.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        
        # 连接信号
        self._tree_view.clicked.connect(self._on_item_clicked)
        self._tree_view.doubleClicked.connect(self._on_item_double_clicked)
        self._tree_view.customContextMenuRequested.connect(self._on_context_menu)


    def _setup_style(self):
        """设置样式"""
        self.setStyleSheet("""
            /* 面板背景 */
            FileBrowserPanel {
                background-color: #f8f9fa;
            }
            
            /* 标题栏 */
            #file_browser_header {
                background-color: #f8f9fa;
                border-bottom: 1px solid #e0e0e0;
            }
            
            /* 标题文本 */
            #file_browser_title {
                color: #666666;
                font-size: 11px;
                font-weight: bold;
                text-transform: uppercase;
            }
            
            /* 标题栏按钮 */
            #file_browser_btn {
                background: transparent;
                border: none;
                border-radius: 3px;
                color: #666666;
            }
            #file_browser_btn:hover {
                background-color: #e0e0e0;
            }
            
            /* 文件树 */
            #file_browser_tree {
                background-color: #f8f9fa;
                border: none;
                font-family: "JetBrains Mono", "Cascadia Code", "SF Mono", "Consolas", monospace;
                font-size: 13px;
            }
            
            /* 树项目 */
            #file_browser_tree::item {
                height: 24px;
                padding-left: 4px;
            }
            
            /* 选中项 */
            #file_browser_tree::item:selected {
                background-color: #e3f2fd;
                color: #333333;
            }
            
            /* 悬停项 */
            #file_browser_tree::item:hover:!selected {
                background-color: #f0f7ff;
            }
            
            /* 分支线 */
            #file_browser_tree::branch:has-children:!has-siblings:closed,
            #file_browser_tree::branch:closed:has-children:has-siblings {
                border-image: none;
            }
            
            #file_browser_tree::branch:open:has-children:!has-siblings,
            #file_browser_tree::branch:open:has-children:has-siblings {
                border-image: none;
            }
        """)

    def _setup_context_menu(self):
        """设置右键菜单"""
        self._context_menu = QMenu(self)
        
        # 文件菜单项
        self._file_menu_actions["open"] = QAction(self)
        self._file_menu_actions["open"].triggered.connect(self._on_open_in_editor)
        
        self._file_menu_actions["show_in_system"] = QAction(self)
        self._file_menu_actions["show_in_system"].triggered.connect(self._on_show_in_system)
        
        self._file_menu_actions["copy_path"] = QAction(self)
        self._file_menu_actions["copy_path"].triggered.connect(self._on_copy_path)
        
        self._file_menu_actions["delete"] = QAction(self)
        self._file_menu_actions["delete"].triggered.connect(self._on_delete)
        
        # 文件夹菜单项
        self._folder_menu_actions["new_file"] = QAction(self)
        self._folder_menu_actions["new_file"].triggered.connect(self._on_new_file)
        
        self._folder_menu_actions["new_folder"] = QAction(self)
        self._folder_menu_actions["new_folder"].triggered.connect(self._on_new_folder)
        
        self._folder_menu_actions["refresh"] = QAction(self)
        self._folder_menu_actions["refresh"].triggered.connect(self.refresh)
        
        self._folder_menu_actions["show_in_system"] = QAction(self)
        self._folder_menu_actions["show_in_system"].triggered.connect(self._on_show_in_system)


    # ============================================================
    # 核心功能
    # ============================================================

    def set_root_path(self, folder_path: str):
        """
        设置根目录
        
        Args:
            folder_path: 工作文件夹路径
        """
        if not folder_path or not os.path.isdir(folder_path):
            if self.logger:
                self.logger.warning(f"Invalid folder path: {folder_path}")
            return
        
        self._root_path = folder_path
        
        # 设置文件模型根路径
        root_index = self._file_model.setRootPath(folder_path)
        
        # 设置代理模型的根索引
        proxy_root = self._proxy_model.mapFromSource(root_index)
        self._tree_view.setRootIndex(proxy_root)
        
        # 更新标题
        folder_name = os.path.basename(folder_path)
        self._title_label.setText(folder_name.upper())
        
        if self.logger:
            self.logger.info(f"File browser root set to: {folder_path}")

    def refresh(self):
        """刷新文件树"""
        if self._root_path and os.path.isdir(self._root_path):
            # 重新设置根路径以刷新
            self.set_root_path(self._root_path)
            if self.logger:
                self.logger.debug("File browser refreshed")

    def get_selected_file(self) -> Optional[str]:
        """
        获取当前选中文件
        
        Returns:
            str: 选中的文件路径，未选中返回 None
        """
        indexes = self._tree_view.selectedIndexes()
        if not indexes:
            return None
        
        # 获取源模型索引
        proxy_index = indexes[0]
        source_index = self._proxy_model.mapToSource(proxy_index)
        
        if source_index.isValid():
            file_path = self._file_model.filePath(source_index)
            # 只返回文件，不返回目录
            if os.path.isfile(file_path):
                return file_path
        
        return None

    def clear(self):
        """清空文件树显示"""
        self._root_path = None
        # 设置一个无效的根路径来清空显示
        self._file_model.setRootPath("")
        self._tree_view.setRootIndex(QModelIndex())
        self._title_label.setText(self._get_text("panel.file_browser", "EXPLORER"))
        
        if self.logger:
            self.logger.debug("File browser cleared")


    # ============================================================
    # 事件处理
    # ============================================================

    def _on_item_clicked(self, proxy_index: QModelIndex):
        """单击项目"""
        source_index = self._proxy_model.mapToSource(proxy_index)
        if not source_index.isValid():
            return
        
        file_path = self._file_model.filePath(source_index)
        
        # 如果是文件，发出选中信号
        if os.path.isfile(file_path):
            self.file_selected.emit(file_path)
            if self.logger:
                self.logger.debug(f"File selected: {file_path}")

    def _on_item_double_clicked(self, proxy_index: QModelIndex):
        """双击项目"""
        source_index = self._proxy_model.mapToSource(proxy_index)
        if not source_index.isValid():
            return
        
        file_path = self._file_model.filePath(source_index)
        
        # 如果是目录，展开/折叠由 QTreeView 自动处理
        # 如果是文件，发出选中信号
        if os.path.isfile(file_path):
            self.file_selected.emit(file_path)

    def _on_collapse_all(self):
        """折叠全部"""
        self._tree_view.collapseAll()

    def _on_context_menu(self, position):
        """显示右键菜单"""
        proxy_index = self._tree_view.indexAt(position)
        if not proxy_index.isValid():
            return
        
        source_index = self._proxy_model.mapToSource(proxy_index)
        if not source_index.isValid():
            return
        
        file_path = self._file_model.filePath(source_index)
        is_dir = os.path.isdir(file_path)
        
        # 清空菜单
        self._context_menu.clear()
        
        if is_dir:
            # 文件夹菜单
            self._context_menu.addAction(self._folder_menu_actions["new_file"])
            self._context_menu.addAction(self._folder_menu_actions["new_folder"])
            self._context_menu.addSeparator()
            self._context_menu.addAction(self._folder_menu_actions["refresh"])
            self._context_menu.addSeparator()
            self._context_menu.addAction(self._folder_menu_actions["show_in_system"])
        else:
            # 文件菜单
            self._context_menu.addAction(self._file_menu_actions["open"])
            self._context_menu.addSeparator()
            self._context_menu.addAction(self._file_menu_actions["show_in_system"])
            self._context_menu.addAction(self._file_menu_actions["copy_path"])
            self._context_menu.addSeparator()
            self._context_menu.addAction(self._file_menu_actions["delete"])
        
        # 显示菜单
        self._context_menu.exec(self._tree_view.viewport().mapToGlobal(position))

    def _on_open_in_editor(self):
        """在编辑器中打开"""
        file_path = self.get_selected_file()
        if file_path:
            self.file_selected.emit(file_path)

    def _on_show_in_system(self):
        """在系统中显示"""
        indexes = self._tree_view.selectedIndexes()
        if not indexes:
            return
        
        source_index = self._proxy_model.mapToSource(indexes[0])
        if not source_index.isValid():
            return
        
        file_path = self._file_model.filePath(source_index)
        
        try:
            system = platform.system()
            if system == "Windows":
                # Windows: 使用 explorer 并选中文件
                subprocess.run(["explorer", "/select,", file_path])
            elif system == "Darwin":
                # macOS: 使用 open -R 显示并选中
                subprocess.run(["open", "-R", file_path])
            else:
                # Linux: 使用 xdg-open 打开所在目录
                folder = os.path.dirname(file_path) if os.path.isfile(file_path) else file_path
                subprocess.run(["xdg-open", folder])
        except Exception as e:
            if self.logger:
                self.logger.error(f"Failed to show in system: {e}")

    def _on_copy_path(self):
        """复制路径"""
        file_path = self.get_selected_file()
        if file_path:
            clipboard = QApplication.clipboard()
            clipboard.setText(file_path)
            if self.logger:
                self.logger.debug(f"Path copied: {file_path}")

    def _on_delete(self):
        """删除文件（暂不实现，需要确认对话框）"""
        # TODO: 实现删除功能，需要确认对话框
        pass

    def _on_new_file(self):
        """新建文件（暂不实现）"""
        # TODO: 实现新建文件功能
        pass

    def _on_new_folder(self):
        """新建文件夹（暂不实现）"""
        # TODO: 实现新建文件夹功能
        pass


    # ============================================================
    # 国际化支持
    # ============================================================

    def retranslate_ui(self):
        """刷新所有 UI 文本（语言切换时调用）"""
        # 标题
        if self._root_path:
            folder_name = os.path.basename(self._root_path)
            self._title_label.setText(folder_name.upper())
        else:
            self._title_label.setText(self._get_text("panel.file_browser", "EXPLORER"))
        
        # 按钮提示
        self._refresh_btn.setToolTip(self._get_text("file_browser.refresh", "Refresh"))
        self._collapse_btn.setToolTip(self._get_text("file_browser.collapse_all", "Collapse All"))
        
        # 文件菜单项
        self._file_menu_actions["open"].setText(
            self._get_text("file_browser.open_in_editor", "Open in Editor")
        )
        self._file_menu_actions["show_in_system"].setText(
            self._get_text("file_browser.show_in_system", "Show in System")
        )
        self._file_menu_actions["copy_path"].setText(
            self._get_text("file_browser.copy_path", "Copy Path")
        )
        self._file_menu_actions["delete"].setText(
            self._get_text("file_browser.delete", "Delete")
        )
        
        # 文件夹菜单项
        self._folder_menu_actions["new_file"].setText(
            self._get_text("file_browser.new_file", "New File")
        )
        self._folder_menu_actions["new_folder"].setText(
            self._get_text("file_browser.new_folder", "New Folder")
        )
        self._folder_menu_actions["refresh"].setText(
            self._get_text("file_browser.refresh", "Refresh")
        )
        self._folder_menu_actions["show_in_system"].setText(
            self._get_text("file_browser.show_in_system", "Show in System")
        )

    # ============================================================
    # 事件订阅
    # ============================================================

    def _subscribe_events(self):
        """订阅事件"""
        if self.event_bus:
            from shared.event_types import (
                EVENT_LANGUAGE_CHANGED,
                EVENT_STATE_PROJECT_OPENED,
                EVENT_STATE_PROJECT_CLOSED
            )
            
            self.event_bus.subscribe(EVENT_LANGUAGE_CHANGED, self._on_language_changed)
            self.event_bus.subscribe(EVENT_STATE_PROJECT_OPENED, self._on_project_opened)
            self.event_bus.subscribe(EVENT_STATE_PROJECT_CLOSED, self._on_project_closed)

    def _on_language_changed(self, event_data: Dict[str, Any]):
        """语言变更事件处理"""
        self.retranslate_ui()
        if self.logger:
            new_lang = event_data.get("new_language", "unknown")
            self.logger.debug(f"File browser language changed to: {new_lang}")

    def _on_project_opened(self, event_data: Dict[str, Any]):
        """项目打开事件处理"""
        # 业务数据在 event_data["data"] 中
        data = event_data.get("data", {})
        project_path = data.get("path") if isinstance(data, dict) else None
        if project_path:
            self.set_root_path(project_path)
            if self.logger:
                self.logger.info(f"File browser switched to project: {project_path}")

    def _on_project_closed(self, event_data: Dict[str, Any]):
        """项目关闭事件处理"""
        self.clear()
        if self.logger:
            self.logger.info("File browser cleared due to project close")


# ============================================================
# 模块导出
# ============================================================

__all__ = [
    "FileBrowserPanel",
    "FileFilterProxyModel",
    "ALLOWED_EXTENSIONS",
    "HIDDEN_DIRECTORIES",
]
