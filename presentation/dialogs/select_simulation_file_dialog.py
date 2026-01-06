# Select Simulation File Dialog
"""
选择仿真文件对话框

职责：
- 让用户从工作路径中选择要运行仿真的文件
- 支持文件类型过滤
- 支持文件预览
- 支持多主电路降级模式

触发方式：
- 点击工具栏「选择运行」按钮
- 自动检测到多个主电路时自动弹出

被调用方：
- main_window.py（工具栏按钮）
- simulation_service.py（多主电路降级）
"""

from pathlib import Path
from typing import Any, Dict, List, Optional

from PyQt6.QtWidgets import (
    QDialog,
    QVBoxLayout,
    QHBoxLayout,
    QListWidget,
    QListWidgetItem,
    QTextEdit,
    QPushButton,
    QLabel,
    QGroupBox,
    QComboBox,
    QCheckBox,
    QWidget,
    QSplitter,
    QFrame,
)
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QIcon


class SelectSimulationFileDialog(QDialog):
    """
    选择仿真文件对话框
    
    功能：
    - 显示可仿真文件列表
    - 文件类型过滤
    - 文件预览
    - 多主电路降级模式
    """

    # 默认支持的文件扩展名
    DEFAULT_EXTENSIONS = [".cir", ".sp", ".spice", ".net", ".ckt", ".py"]

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        
        self._i18n_manager = None
        self._event_bus = None
        self._logger = None
        
        self._project_root: Optional[str] = None
        self._files: List[Dict[str, Any]] = []
        self._candidates: Optional[List[str]] = None
        self._selected_file: Optional[str] = None
        self._is_degraded_mode: bool = False
        
        self._file_list: Optional[QListWidget] = None
        self._preview_text: Optional[QTextEdit] = None
        self._filter_combo: Optional[QComboBox] = None
        self._remember_checkbox: Optional[QCheckBox] = None
        self._hint_label: Optional[QLabel] = None
        self._run_btn: Optional[QPushButton] = None
        self._cancel_btn: Optional[QPushButton] = None
        
        self._setup_dialog()
        self._setup_ui()
        self.retranslate_ui()
        self._subscribe_events()

    @property
    def i18n_manager(self):
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
        if self._logger is None:
            try:
                from infrastructure.utils.logger import get_logger
                self._logger = get_logger("select_simulation_file_dialog")
            except Exception:
                pass
        return self._logger

    def _get_text(self, key: str, default: Optional[str] = None) -> str:
        if self.i18n_manager:
            return self.i18n_manager.get_text(key, default)
        return default if default else key

    def _setup_dialog(self):
        self.setWindowFlags(
            self.windowFlags() & ~Qt.WindowType.WindowContextHelpButtonHint
        )
        self.setMinimumSize(700, 500)
        self.resize(800, 550)
        self.setModal(True)

    def _setup_ui(self):
        main_layout = QVBoxLayout(self)
        main_layout.setSpacing(10)
        
        # 提示文本
        self._hint_label = QLabel()
        self._hint_label.setWordWrap(True)
        self._hint_label.setStyleSheet("color: #666; padding: 4px;")
        main_layout.addWidget(self._hint_label)
        
        # 过滤器
        filter_layout = QHBoxLayout()
        filter_label = QLabel()
        filter_label.setProperty("label_type", "filter")
        filter_layout.addWidget(filter_label)
        
        self._filter_combo = QComboBox()
        self._filter_combo.setMinimumWidth(150)
        self._filter_combo.currentIndexChanged.connect(self._on_filter_changed)
        filter_layout.addWidget(self._filter_combo)
        filter_layout.addStretch()
        main_layout.addLayout(filter_layout)
        
        # 主分割器
        splitter = QSplitter(Qt.Orientation.Horizontal)
        
        # 文件列表
        list_group = QGroupBox()
        list_group.setProperty("group_type", "file_list")
        list_layout = QVBoxLayout(list_group)
        
        self._file_list = QListWidget()
        self._file_list.setAlternatingRowColors(True)
        self._file_list.currentItemChanged.connect(self._on_file_selected)
        self._file_list.itemDoubleClicked.connect(self._on_file_double_clicked)
        list_layout.addWidget(self._file_list)
        
        splitter.addWidget(list_group)
        
        # 预览区
        preview_group = QGroupBox()
        preview_group.setProperty("group_type", "preview")
        preview_layout = QVBoxLayout(preview_group)
        
        self._preview_text = QTextEdit()
        self._preview_text.setReadOnly(True)
        self._preview_text.setStyleSheet("""
            QTextEdit {
                background-color: #fafafa;
                border: 1px solid #e0e0e0;
                border-radius: 4px;
                padding: 8px;
                font-family: "JetBrains Mono", "Cascadia Code", "Consolas", monospace;
                font-size: 12px;
            }
        """)
        preview_layout.addWidget(self._preview_text)
        
        splitter.addWidget(preview_group)
        splitter.setSizes([350, 450])
        
        main_layout.addWidget(splitter, 1)
        
        # 记住选择
        self._remember_checkbox = QCheckBox()
        main_layout.addWidget(self._remember_checkbox)
        
        # 按钮区
        main_layout.addWidget(self._create_button_area())

    def _create_button_area(self) -> QWidget:
        widget = QWidget()
        layout = QHBoxLayout(widget)
        layout.setContentsMargins(0, 10, 0, 0)
        
        layout.addStretch()
        
        self._cancel_btn = QPushButton()
        self._cancel_btn.clicked.connect(self.reject)
        layout.addWidget(self._cancel_btn)
        
        self._run_btn = QPushButton()
        self._run_btn.setEnabled(False)
        self._run_btn.setStyleSheet("""
            QPushButton {
                background-color: #4a9eff;
                color: white;
                border: none;
                border-radius: 4px;
                padding: 8px 20px;
            }
            QPushButton:hover { background-color: #3a8eef; }
            QPushButton:disabled { background-color: #cccccc; }
        """)
        self._run_btn.clicked.connect(self._on_run_clicked)
        layout.addWidget(self._run_btn)
        
        return widget

    def load_simulatable_files(self, project_root: str) -> None:
        """扫描并加载所有可仿真文件"""
        self._project_root = project_root
        self._is_degraded_mode = False
        self._candidates = None
        self._files.clear()
        
        extensions = self._get_supported_extensions()
        root_path = Path(project_root)
        
        for ext in extensions:
            for file_path in root_path.rglob(f"*{ext}"):
                if file_path.is_file() and not self._is_hidden(file_path):
                    rel_path = file_path.relative_to(root_path)
                    self._files.append({
                        "path": str(file_path),
                        "relative_path": str(rel_path),
                        "name": file_path.name,
                        "extension": ext,
                        "executor_type": self._get_executor_type(ext),
                        "is_recommended": False,
                        "reason": "",
                    })
        
        self._files.sort(key=lambda f: f["relative_path"])
        self._populate_filter_combo()
        self._populate_file_list()
        self._update_hint_text()

    def set_candidates(self, file_list: List[str]) -> None:
        """设置候选文件列表（多主电路降级模式）"""
        self._is_degraded_mode = True
        self._candidates = file_list
        self._files.clear()
        
        for i, file_path in enumerate(file_list):
            path = Path(file_path)
            ext = path.suffix.lower()
            
            self._files.append({
                "path": file_path,
                "relative_path": path.name,
                "name": path.name,
                "extension": ext,
                "executor_type": self._get_executor_type(ext),
                "is_recommended": i == 0,
                "reason": self._get_text("simulation.candidate.reason", "包含仿真控制语句"),
            })
        
        self._populate_filter_combo()
        self._populate_file_list()
        self._update_hint_text()

    def get_selected_file(self) -> Optional[str]:
        """获取用户选中的文件路径"""
        return self._selected_file

    def should_remember_selection(self) -> bool:
        """是否记住选择"""
        return self._remember_checkbox.isChecked() if self._remember_checkbox else False

    def _get_supported_extensions(self) -> List[str]:
        """获取支持的文件扩展名"""
        try:
            from domain.simulation.executor.executor_registry import executor_registry
            return executor_registry.get_all_supported_extensions()
        except Exception:
            return self.DEFAULT_EXTENSIONS

    def _get_executor_type(self, extension: str) -> str:
        """根据扩展名获取执行器类型"""
        if extension == ".py":
            return "Python"
        return "SPICE"

    def _is_hidden(self, path: Path) -> bool:
        """检查路径是否为隐藏文件/目录"""
        for part in path.parts:
            if part.startswith("."):
                return True
        return False

    def _populate_filter_combo(self):
        self._filter_combo.clear()
        self._filter_combo.addItem(self._get_text("simulation.filter.all", "全部"), "all")
        self._filter_combo.addItem(self._get_text("simulation.filter.spice", "SPICE 文件"), "spice")
        self._filter_combo.addItem(self._get_text("simulation.filter.python", "Python 脚本"), "python")

    def _populate_file_list(self, filter_type: str = "all"):
        self._file_list.clear()
        
        for file_info in self._files:
            if filter_type == "spice" and file_info["executor_type"] != "SPICE":
                continue
            if filter_type == "python" and file_info["executor_type"] != "Python":
                continue
            
            item = QListWidgetItem()
            item.setData(Qt.ItemDataRole.UserRole, file_info["path"])
            
            display_text = f"{file_info['name']}"
            if file_info["relative_path"] != file_info["name"]:
                display_text += f"\n  📁 {file_info['relative_path']}"
            display_text += f"\n  [{file_info['executor_type']}]"
            
            if file_info["is_recommended"]:
                display_text = f"⭐ {display_text}"
            
            item.setText(display_text)
            self._file_list.addItem(item)

    def _update_hint_text(self):
        if self._is_degraded_mode:
            self._hint_label.setText(self._get_text(
                "simulation.hint.degraded",
                "检测到多个可能的主电路文件，请选择一个进行仿真"
            ))
        else:
            self._hint_label.setText(self._get_text(
                "simulation.hint.normal",
                "请选择要运行仿真的文件"
            ))

    def _on_filter_changed(self, index: int):
        filter_type = self._filter_combo.itemData(index)
        self._populate_file_list(filter_type)

    def _on_file_selected(self, current: QListWidgetItem, previous: QListWidgetItem):
        if current is None:
            self._preview_text.clear()
            self._run_btn.setEnabled(False)
            self._selected_file = None
            return
        
        file_path = current.data(Qt.ItemDataRole.UserRole)
        self._selected_file = file_path
        self._run_btn.setEnabled(True)
        self._load_preview(file_path)

    def _on_file_double_clicked(self, item: QListWidgetItem):
        self._on_run_clicked()

    def _load_preview(self, file_path: str):
        try:
            with open(file_path, "r", encoding="utf-8", errors="replace") as f:
                lines = f.readlines()[:30]
            
            preview = "".join(lines)
            if len(lines) == 30:
                preview += "\n... (更多内容省略)"
            
            self._preview_text.setPlainText(preview)
        except Exception as e:
            self._preview_text.setPlainText(f"无法预览文件: {e}")

    def _on_run_clicked(self):
        if self._selected_file:
            self.accept()

    def retranslate_ui(self):
        self.setWindowTitle(self._get_text("dialog.select_simulation.title", "选择仿真文件"))
        
        for group in self.findChildren(QGroupBox):
            group_type = group.property("group_type")
            if group_type == "file_list":
                group.setTitle(self._get_text("dialog.select_simulation.files", "可仿真文件"))
            elif group_type == "preview":
                group.setTitle(self._get_text("dialog.select_simulation.preview", "文件预览"))
        
        for label in self.findChildren(QLabel):
            if label.property("label_type") == "filter":
                label.setText(self._get_text("simulation.filter.label", "文件类型:"))
        
        if self._remember_checkbox:
            self._remember_checkbox.setText(self._get_text(
                "simulation.remember_selection",
                "记住此项目的选择"
            ))
        
        if self._run_btn:
            self._run_btn.setText(self._get_text("btn.run", "运行"))
        if self._cancel_btn:
            self._cancel_btn.setText(self._get_text("btn.cancel", "取消"))
        
        self._update_hint_text()
        self._populate_filter_combo()

    def _subscribe_events(self):
        if self.event_bus:
            from shared.event_types import EVENT_LANGUAGE_CHANGED
            self.event_bus.subscribe(EVENT_LANGUAGE_CHANGED, self._on_language_changed)

    def _on_language_changed(self, event_data: Dict[str, Any]):
        self.retranslate_ui()


__all__ = ["SelectSimulationFileDialog"]
