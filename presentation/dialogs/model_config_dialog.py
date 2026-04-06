# Model Configuration Dialog
"""
模型配置对话框

职责：
- 两级选择：先选择 LLM 厂商，再选择具体模型
- 厂商专属联网搜索（选择模型后才显示）
- 通用联网搜索配置（Google/Bing）
- 未实现的厂商显示占位提示

国际化支持：
- 实现 retranslate_ui() 方法
- 订阅 EVENT_LANGUAGE_CHANGED 事件
"""

import os
import tempfile
from typing import Optional, Dict, Any, List

from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QFormLayout,
    QLabel, QLineEdit, QComboBox, QCheckBox, QSpinBox,
    QPushButton, QGroupBox, QMessageBox, QWidget, QTabWidget
)
from PyQt6.QtCore import Qt

from infrastructure.config.settings import (
    CONFIG_EMBEDDING_PROVIDER,
    CONFIG_EMBEDDING_MODEL,
    CONFIG_EMBEDDING_BASE_URL,
    CONFIG_EMBEDDING_TIMEOUT,
    CONFIG_EMBEDDING_BATCH_SIZE,
    WEB_SEARCH_GOOGLE,
    WEB_SEARCH_BING,
    CONFIG_LLM_PROVIDER,
    CONFIG_LLM_MODEL,
    CONFIG_LLM_BASE_URL,
    CONFIG_LLM_TIMEOUT,
    CONFIG_LLM_STREAMING,
    CONFIG_ENABLE_THINKING,
    CONFIG_THINKING_TIMEOUT,
    CONFIG_ENABLE_PROVIDER_WEB_SEARCH,
    CONFIG_ENABLE_GENERAL_WEB_SEARCH,
    CONFIG_GENERAL_WEB_SEARCH_PROVIDER,
    DEFAULT_TIMEOUT,
    DEFAULT_EMBEDDING_TIMEOUT,
    DEFAULT_EMBEDDING_BATCH_SIZE,
    DEFAULT_THINKING_TIMEOUT,
)


# ============================================================
# 模型配置对话框
# ============================================================

class ModelConfigDialog(QDialog):
    """
    模型配置对话框
    
    功能：
    - 两级选择：厂商 → 模型
    - 厂商专属功能（深度思考、联网搜索）
    - 通用联网搜索配置（Google/Bing）
    - 未实现厂商的占位提示
    """

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        
        # 延迟获取的服务
        self._i18n_manager = None
        self._config_manager = None
        self._credential_manager = None
        self._event_bus = None
        self._logger = None
        
        # UI 组件引用
        self._provider_combo: Optional[QComboBox] = None
        self._model_combo: Optional[QComboBox] = None
        self._api_key_edit: Optional[QLineEdit] = None
        self._base_url_edit: Optional[QLineEdit] = None
        self._streaming_check: Optional[QCheckBox] = None
        self._timeout_spin: Optional[QSpinBox] = None

        self._embedding_config_group: Optional[QGroupBox] = None
        self._embedding_provider_combo: Optional[QComboBox] = None
        self._embedding_model_combo: Optional[QComboBox] = None
        self._embedding_api_key_edit: Optional[QLineEdit] = None
        self._embedding_base_url_edit: Optional[QLineEdit] = None
        self._embedding_timeout_spin: Optional[QSpinBox] = None
        self._embedding_batch_size_spin: Optional[QSpinBox] = None
        self._tab_widget: Optional[QTabWidget] = None
        self._chat_tab: Optional[QWidget] = None
        self._embedding_tab: Optional[QWidget] = None
        
        # 厂商专属功能组件
        self._provider_features_group: Optional[QGroupBox] = None
        self._api_config_group: Optional[QGroupBox] = None
        self._deep_think_check: Optional[QCheckBox] = None
        self._thinking_timeout_spin: Optional[QSpinBox] = None
        self._provider_web_search_check: Optional[QCheckBox] = None
        
        # 通用联网搜索组件
        self._general_search_group: Optional[QGroupBox] = None
        self._general_search_check: Optional[QCheckBox] = None
        self._general_search_provider_combo: Optional[QComboBox] = None
        self._general_search_api_key_edit: Optional[QLineEdit] = None
        self._google_cx_edit: Optional[QLineEdit] = None
        self._google_cx_label: Optional[QLabel] = None
        
        # 按钮和状态
        self._test_btn: Optional[QPushButton] = None
        self._status_label: Optional[QLabel] = None
        self._save_btn: Optional[QPushButton] = None
        self._cancel_btn: Optional[QPushButton] = None
        
        # 初始化 UI
        self._setup_dialog()
        self._setup_ui()
        
        # 加载配置
        self.load_config()
        
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
    def config_manager(self):
        """延迟获取 ConfigManager"""
        if self._config_manager is None:
            try:
                from shared.service_locator import ServiceLocator
                from shared.service_names import SVC_CONFIG_MANAGER
                self._config_manager = ServiceLocator.get_optional(SVC_CONFIG_MANAGER)
            except Exception:
                pass
        return self._config_manager

    @property
    def credential_manager(self):
        """延迟获取 CredentialManager"""
        if self._credential_manager is None:
            try:
                from shared.service_locator import ServiceLocator
                from shared.service_names import SVC_CREDENTIAL_MANAGER
                self._credential_manager = ServiceLocator.get_optional(SVC_CREDENTIAL_MANAGER)
            except Exception:
                pass
        return self._credential_manager

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
                self._logger = get_logger("model_config_dialog")
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

    def _setup_dialog(self):
        """设置对话框基本属性"""
        self.setWindowFlags(
            self.windowFlags() & ~Qt.WindowType.WindowContextHelpButtonHint
        )
        self.setMinimumWidth(520)
        self.setModal(True)
        
        # 创建临时图标文件并设置样式
        self._setup_custom_styles()
    
    def _get_icon_paths(self) -> tuple:
        """
        获取 UI 图标路径
        
        优先使用本地 resources/icons/ui/ 目录下的图标，
        如果不存在则创建临时文件。
        
        Returns:
            (checkmark_path, dropdown_path)
        """
        # 尝试获取本地图标路径
        try:
            # 获取项目根目录
            current_file = os.path.abspath(__file__)
            dialogs_dir = os.path.dirname(current_file)
            presentation_dir = os.path.dirname(dialogs_dir)
            project_root = os.path.dirname(presentation_dir)
            
            icons_dir = os.path.join(project_root, "resources", "icons", "ui")
            checkmark_path = os.path.join(icons_dir, "checkmark.svg")
            dropdown_path = os.path.join(icons_dir, "dropdown.svg")
            
            # 检查本地图标是否存在
            if os.path.exists(checkmark_path) and os.path.exists(dropdown_path):
                self._temp_dir = None  # 不需要临时目录
                return checkmark_path, dropdown_path
        except Exception:
            pass
        
        # 本地图标不存在，创建临时文件
        self._temp_dir = tempfile.mkdtemp(prefix="circuit_ai_icons_")
        
        # 创建打钩图标 (checkmark.svg) - 白色打钩在蓝色背景上
        checkmark_svg = '''<svg xmlns="http://www.w3.org/2000/svg" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="#ffffff" stroke-width="3" stroke-linecap="round" stroke-linejoin="round"><polyline points="20 6 9 17 4 12"></polyline></svg>'''
        checkmark_path = os.path.join(self._temp_dir, "checkmark.svg")
        with open(checkmark_path, "w", encoding="utf-8") as f:
            f.write(checkmark_svg)
        
        # 创建下拉箭头图标 (dropdown.svg)
        dropdown_svg = '''<svg xmlns="http://www.w3.org/2000/svg" width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="#666666" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="6 9 12 15 18 9"></polyline></svg>'''
        dropdown_path = os.path.join(self._temp_dir, "dropdown.svg")
        with open(dropdown_path, "w", encoding="utf-8") as f:
            f.write(dropdown_svg)
        
        return checkmark_path, dropdown_path
    
    def _setup_custom_styles(self):
        """设置自定义样式：复选框打钩、下拉框箭头"""
        # 获取本地图标路径
        checkmark_path, dropdown_path = self._get_icon_paths()
        
        # 转换路径为 Qt 样式表格式（使用正斜杠）
        checkmark_url = checkmark_path.replace("\\", "/")
        dropdown_url = dropdown_path.replace("\\", "/")
        
        # 设置样式表
        self.setStyleSheet(f"""
            /* 复选框样式：使用打钩而非蓝色填充 */
            QCheckBox::indicator {{
                width: 18px;
                height: 18px;
                border: 2px solid #ccc;
                border-radius: 3px;
                background-color: #fff;
            }}
            QCheckBox::indicator:hover {{
                border-color: #4a9eff;
            }}
            QCheckBox::indicator:checked {{
                background-color: #4a9eff;
                border-color: #4a9eff;
                image: url({checkmark_url});
            }}
            QCheckBox::indicator:checked:hover {{
                background-color: #3d8ce6;
                border-color: #3d8ce6;
            }}
            QCheckBox::indicator:disabled {{
                border-color: #ddd;
                background-color: #f5f5f5;
            }}
            QCheckBox::indicator:checked:disabled {{
                background-color: #ccc;
                border-color: #ccc;
            }}
            
            /* 下拉框样式：添加下拉箭头指示 */
            QComboBox {{
                border: 1px solid #ccc;
                border-radius: 4px;
                padding: 6px 28px 6px 10px;
                background-color: #fff;
                min-height: 20px;
            }}
            QComboBox:hover {{
                border-color: #4a9eff;
            }}
            QComboBox:focus {{
                border-color: #4a9eff;
            }}
            QComboBox::drop-down {{
                subcontrol-origin: padding;
                subcontrol-position: center right;
                width: 24px;
                border: none;
                background: transparent;
            }}
            QComboBox::down-arrow {{
                image: url({dropdown_url});
                width: 12px;
                height: 12px;
            }}
            QComboBox:disabled {{
                background-color: #f5f5f5;
                color: #999;
            }}
            QComboBox QAbstractItemView {{
                border: 1px solid #ccc;
                background-color: #fff;
                selection-background-color: #e3f2fd;
                selection-color: #333;
                outline: none;
            }}
            QComboBox QAbstractItemView::item {{
                padding: 6px 10px;
                min-height: 24px;
            }}
            QComboBox QAbstractItemView::item:hover {{
                background-color: #f5f5f5;
            }}
            QComboBox QAbstractItemView::item:selected {{
                background-color: #e3f2fd;
            }}
        """)

    def _setup_ui(self):
        """设置 UI 布局"""
        main_layout = QVBoxLayout(self)
        main_layout.setSpacing(15)

        self._tab_widget = QTabWidget()
        main_layout.addWidget(self._tab_widget)

        self._chat_tab = QWidget()
        chat_layout = QVBoxLayout(self._chat_tab)
        chat_layout.setContentsMargins(0, 8, 0, 0)
        chat_layout.setSpacing(15)

        chat_layout.addWidget(self._create_provider_model_group())

        self._api_config_group = self._create_api_config_group()
        chat_layout.addWidget(self._api_config_group)

        self._provider_features_group = self._create_provider_features_group()
        chat_layout.addWidget(self._provider_features_group)

        self._general_search_group = self._create_general_search_group()
        chat_layout.addWidget(self._general_search_group)
        chat_layout.addStretch()

        self._embedding_tab = QWidget()
        embedding_layout = QVBoxLayout(self._embedding_tab)
        embedding_layout.setContentsMargins(0, 8, 0, 0)
        embedding_layout.setSpacing(15)

        self._embedding_config_group = self._create_embedding_config_group()
        embedding_layout.addWidget(self._embedding_config_group)
        embedding_layout.addStretch()

        self._tab_widget.addTab(self._chat_tab, "")
        self._tab_widget.addTab(self._embedding_tab, "")
        
        # 验证状态
        self._status_label = QLabel()
        self._status_label.setStyleSheet("color: #666;")
        main_layout.addWidget(self._status_label)
        
        # 按钮区域
        main_layout.addWidget(self._create_button_area())

    def _create_provider_model_group(self) -> QGroupBox:
        """创建厂商和模型选择组"""
        group = QGroupBox()
        group.setProperty("group_type", "provider_model")
        layout = QFormLayout(group)
        
        # 厂商选择
        self._provider_combo = QComboBox()
        self._populate_chat_providers()
        self._provider_combo.currentIndexChanged.connect(self._on_provider_changed)
        
        provider_label = QLabel()
        provider_label.setProperty("label_type", "provider")
        layout.addRow(provider_label, self._provider_combo)
        
        # 模型选择
        self._model_combo = QComboBox()
        
        model_label = QLabel()
        model_label.setProperty("label_type", "model")
        layout.addRow(model_label, self._model_combo)
        
        return group

    def _create_api_config_group(self) -> QGroupBox:
        """创建 API 配置组"""
        group = QGroupBox()
        group.setProperty("group_type", "api_config")
        layout = QFormLayout(group)
        
        # API Key
        self._api_key_edit = QLineEdit()
        self._api_key_edit.setEchoMode(QLineEdit.EchoMode.Password)
        self._api_key_edit.textChanged.connect(self._reset_validation_status)
        
        api_key_label = QLabel()
        api_key_label.setProperty("label_type", "api_key")
        layout.addRow(api_key_label, self._api_key_edit)
        
        # Base URL
        self._base_url_edit = QLineEdit()
        
        base_url_label = QLabel()
        base_url_label.setProperty("label_type", "base_url")
        layout.addRow(base_url_label, self._base_url_edit)
        
        # 流式输出
        self._streaming_check = QCheckBox()
        self._streaming_check.setChecked(True)
        
        streaming_label = QLabel()
        streaming_label.setProperty("label_type", "streaming")
        layout.addRow(streaming_label, self._streaming_check)
        
        # 超时设置
        self._timeout_spin = QSpinBox()
        self._timeout_spin.setRange(10, 300)
        self._timeout_spin.setValue(DEFAULT_TIMEOUT)
        self._timeout_spin.setSuffix(" s")
        
        timeout_label = QLabel()
        timeout_label.setProperty("label_type", "timeout")
        layout.addRow(timeout_label, self._timeout_spin)
        
        return group

    def _create_embedding_config_group(self) -> QGroupBox:
        """创建嵌入模型配置组"""
        group = QGroupBox()
        group.setProperty("group_type", "embedding_config")
        layout = QFormLayout(group)

        self._embedding_provider_combo = QComboBox()
        self._embedding_provider_combo.currentIndexChanged.connect(self._on_embedding_provider_changed)
        provider_label = QLabel()
        provider_label.setProperty("label_type", "embedding_provider")
        layout.addRow(provider_label, self._embedding_provider_combo)

        self._embedding_model_combo = QComboBox()
        model_label = QLabel()
        model_label.setProperty("label_type", "embedding_model")
        layout.addRow(model_label, self._embedding_model_combo)

        self._embedding_api_key_edit = QLineEdit()
        self._embedding_api_key_edit.setEchoMode(QLineEdit.EchoMode.Password)
        api_key_label = QLabel()
        api_key_label.setProperty("label_type", "embedding_api_key")
        layout.addRow(api_key_label, self._embedding_api_key_edit)

        self._embedding_base_url_edit = QLineEdit()
        base_url_label = QLabel()
        base_url_label.setProperty("label_type", "embedding_base_url")
        layout.addRow(base_url_label, self._embedding_base_url_edit)

        self._embedding_timeout_spin = QSpinBox()
        self._embedding_timeout_spin.setRange(5, 300)
        self._embedding_timeout_spin.setValue(DEFAULT_EMBEDDING_TIMEOUT)
        self._embedding_timeout_spin.setSuffix(" s")
        timeout_label = QLabel()
        timeout_label.setProperty("label_type", "embedding_timeout")
        layout.addRow(timeout_label, self._embedding_timeout_spin)

        self._embedding_batch_size_spin = QSpinBox()
        self._embedding_batch_size_spin.setRange(1, 256)
        self._embedding_batch_size_spin.setValue(DEFAULT_EMBEDDING_BATCH_SIZE)
        batch_size_label = QLabel()
        batch_size_label.setProperty("label_type", "embedding_batch_size")
        layout.addRow(batch_size_label, self._embedding_batch_size_spin)

        self._populate_embedding_providers(force_refresh=True)

        return group


    def _create_provider_features_group(self) -> QGroupBox:
        """创建厂商专属功能组"""
        group = QGroupBox()
        group.setProperty("group_type", "provider_features")
        layout = QVBoxLayout(group)
        
        # 功能表单
        form_layout = QFormLayout()
        
        # 深度思考
        self._deep_think_check = QCheckBox()
        self._deep_think_check.setChecked(True)
        self._deep_think_check.stateChanged.connect(self._on_deep_think_changed)
        
        deep_think_label = QLabel()
        deep_think_label.setProperty("label_type", "deep_think")
        form_layout.addRow(deep_think_label, self._deep_think_check)
        
        # 深度思考超时
        self._thinking_timeout_spin = QSpinBox()
        self._thinking_timeout_spin.setRange(60, 600)
        self._thinking_timeout_spin.setValue(DEFAULT_THINKING_TIMEOUT)
        self._thinking_timeout_spin.setSuffix(" s")
        
        thinking_timeout_label = QLabel()
        thinking_timeout_label.setProperty("label_type", "thinking_timeout")
        form_layout.addRow(thinking_timeout_label, self._thinking_timeout_spin)
        
        # 厂商专属联网搜索
        self._provider_web_search_check = QCheckBox()
        self._provider_web_search_check.stateChanged.connect(self._on_provider_web_search_changed)
        
        provider_search_label = QLabel()
        provider_search_label.setProperty("label_type", "provider_web_search")
        form_layout.addRow(provider_search_label, self._provider_web_search_check)
        
        layout.addLayout(form_layout)
        
        return group

    def _create_general_search_group(self) -> QGroupBox:
        """创建通用联网搜索组"""
        group = QGroupBox()
        group.setProperty("group_type", "general_search")
        layout = QFormLayout(group)
        
        # 启用通用联网搜索
        self._general_search_check = QCheckBox()
        self._general_search_check.stateChanged.connect(self._on_general_search_changed)
        
        search_label = QLabel()
        search_label.setProperty("label_type", "general_search")
        layout.addRow(search_label, self._general_search_check)
        
        # 搜索供应商选择
        self._general_search_provider_combo = QComboBox()
        self._general_search_provider_combo.addItem("Google", WEB_SEARCH_GOOGLE)
        self._general_search_provider_combo.addItem("Bing", WEB_SEARCH_BING)
        self._general_search_provider_combo.setEnabled(False)
        self._general_search_provider_combo.currentIndexChanged.connect(
            self._on_general_search_provider_changed
        )
        
        provider_label = QLabel()
        provider_label.setProperty("label_type", "general_search_provider")
        layout.addRow(provider_label, self._general_search_provider_combo)
        
        # 搜索 API Key
        self._general_search_api_key_edit = QLineEdit()
        self._general_search_api_key_edit.setEchoMode(QLineEdit.EchoMode.Password)
        self._general_search_api_key_edit.setEnabled(False)
        
        api_key_label = QLabel()
        api_key_label.setProperty("label_type", "general_search_api_key")
        layout.addRow(api_key_label, self._general_search_api_key_edit)
        
        # Google 搜索引擎 ID（仅 Google 时显示）
        self._google_cx_edit = QLineEdit()
        self._google_cx_edit.setEnabled(False)
        self._google_cx_edit.setPlaceholderText("Google Custom Search Engine ID")
        
        self._google_cx_label = QLabel()
        self._google_cx_label.setProperty("label_type", "google_cx")
        layout.addRow(self._google_cx_label, self._google_cx_edit)
        
        return group

    def _create_button_area(self) -> QWidget:
        """创建按钮区域"""
        widget = QWidget()
        layout = QHBoxLayout(widget)
        layout.setContentsMargins(0, 10, 0, 0)
        
        # 测试连接按钮
        self._test_btn = QPushButton()
        self._test_btn.clicked.connect(self._on_test_connection)
        layout.addWidget(self._test_btn)
        
        layout.addStretch()
        
        # 保存按钮
        self._save_btn = QPushButton()
        self._save_btn.setDefault(True)
        self._save_btn.setStyleSheet(
            "QPushButton { background-color: #4a9eff; color: white; "
            "border: none; border-radius: 4px; padding: 8px 20px; }"
            "QPushButton:hover { background-color: #3d8ce6; }"
        )
        self._save_btn.clicked.connect(self._on_save)
        layout.addWidget(self._save_btn)
        
        # 取消按钮
        self._cancel_btn = QPushButton()
        self._cancel_btn.clicked.connect(self.reject)
        layout.addWidget(self._cancel_btn)
        
        return widget


    # ============================================================
    # 配置加载与保存
    # ============================================================

    def load_config(self):
        """加载当前配置到界面"""
        if not self.config_manager:
            # 无配置管理器时使用默认值
            self._on_provider_changed(0)
            self._populate_embedding_providers(force_refresh=True)
            if self._embedding_provider_combo.count() > 0:
                self._embedding_provider_combo.setCurrentIndex(0)
                self._on_embedding_provider_changed(self._embedding_provider_combo.currentIndex())
            return
        
        # 厂商
        provider = self.config_manager.get(CONFIG_LLM_PROVIDER, "")
        index = self._provider_combo.findData(provider)
        if index >= 0:
            self._provider_combo.setCurrentIndex(index)
        elif self._provider_combo.count() > 0:
            self._provider_combo.setCurrentIndex(0)
        
        # 触发厂商变更以更新模型列表和配置区显示
        self._on_provider_changed(self._provider_combo.currentIndex())

        # 模型
        model = self.config_manager.get(CONFIG_LLM_MODEL, "")
        index = self._model_combo.findText(model, Qt.MatchFlag.MatchFixedString)
        if index >= 0:
            self._model_combo.setCurrentIndex(index)

        # API Key（从 CredentialManager 获取当前厂商的凭证）
        api_key = ""
        if self.credential_manager and provider:
            api_key = self.credential_manager.get_llm_api_key(provider)
        self._api_key_edit.setText(api_key)

        # Base URL
        base_url = self.config_manager.get(CONFIG_LLM_BASE_URL, "")
        self._base_url_edit.setText(base_url)

        # 流式输出
        streaming = self.config_manager.get(CONFIG_LLM_STREAMING, True)
        self._streaming_check.setChecked(streaming)

        # 超时
        timeout = self.config_manager.get(CONFIG_LLM_TIMEOUT, DEFAULT_TIMEOUT)
        self._timeout_spin.setValue(timeout)
        
        # 深度思考
        deep_think = self.config_manager.get(CONFIG_ENABLE_THINKING, True)
        self._deep_think_check.setChecked(deep_think)
        
        # 深度思考超时
        thinking_timeout = self.config_manager.get(CONFIG_THINKING_TIMEOUT, DEFAULT_THINKING_TIMEOUT)
        self._thinking_timeout_spin.setValue(thinking_timeout)
        self._thinking_timeout_spin.setEnabled(deep_think)

        self._populate_embedding_providers(force_refresh=True)
        embedding_provider = self.config_manager.get(CONFIG_EMBEDDING_PROVIDER, "")
        embedding_index = self._embedding_provider_combo.findData(embedding_provider)
        if embedding_index >= 0:
            self._embedding_provider_combo.setCurrentIndex(embedding_index)
        elif self._embedding_provider_combo.count() > 0:
            self._embedding_provider_combo.setCurrentIndex(0)
        self._on_embedding_provider_changed(self._embedding_provider_combo.currentIndex())

        embedding_model = self.config_manager.get(CONFIG_EMBEDDING_MODEL, "")
        if embedding_model:
            model_index = self._embedding_model_combo.findText(embedding_model, Qt.MatchFlag.MatchFixedString)
            if model_index >= 0:
                self._embedding_model_combo.setCurrentIndex(model_index)

        if self.credential_manager and embedding_provider:
            self._embedding_api_key_edit.setText(
                self.credential_manager.get_embedding_api_key(embedding_provider)
            )

        embedding_base_url = self.config_manager.get(CONFIG_EMBEDDING_BASE_URL, "")
        if embedding_base_url:
            self._embedding_base_url_edit.setText(embedding_base_url)

        embedding_timeout = self.config_manager.get(CONFIG_EMBEDDING_TIMEOUT, DEFAULT_EMBEDDING_TIMEOUT)
        self._embedding_timeout_spin.setValue(embedding_timeout)
        embedding_batch_size = self.config_manager.get(CONFIG_EMBEDDING_BATCH_SIZE, DEFAULT_EMBEDDING_BATCH_SIZE)
        self._embedding_batch_size_spin.setValue(embedding_batch_size)

        search_provider = self.config_manager.get(CONFIG_GENERAL_WEB_SEARCH_PROVIDER, WEB_SEARCH_GOOGLE)
        index = self._general_search_provider_combo.findData(search_provider)
        if index >= 0:
            self._general_search_provider_combo.setCurrentIndex(index)

        search_api_key = ""
        google_cx = ""
        if self.credential_manager:
            search_cred = self.credential_manager.get_search_credential(search_provider)
            if search_cred:
                search_api_key = search_cred.get("api_key", "")
                google_cx = search_cred.get("cx", "")
        self._general_search_api_key_edit.setText(search_api_key)
        self._google_cx_edit.setText(google_cx)
        
        # 联网搜索配置（互斥处理）
        # 先读取配置值
        provider_search = self.config_manager.get(CONFIG_ENABLE_PROVIDER_WEB_SEARCH, False)
        general_search = self.config_manager.get(CONFIG_ENABLE_GENERAL_WEB_SEARCH, False)
        
        # 互斥校验：如果两者都为 True，优先保留厂商专属搜索
        if provider_search and general_search:
            general_search = False
        
        # 先设置通用搜索（会触发互斥逻辑）
        self._general_search_check.setChecked(general_search)
        self._on_general_search_changed(
            Qt.CheckState.Checked.value if general_search else Qt.CheckState.Unchecked.value
        )
        
        # 再设置厂商专属搜索（会触发互斥逻辑）
        self._provider_web_search_check.setChecked(provider_search)
        if provider_search:
            self._on_provider_web_search_changed(Qt.CheckState.Checked.value)
        
        # 更新验证状态：检查是否之前已验证过
        self._check_and_update_verification_status(provider)

    def save_config(self) -> bool:
        """保存配置到文件"""
        if not self.config_manager:
            return False
        
        # 校验
        if not self._validate_config():
            return False
        
        # 获取当前选择的厂商
        provider_id = self._provider_combo.currentData()
        embedding_provider_id = self._embedding_provider_combo.currentData()
        search_provider_id = self._general_search_provider_combo.currentData()
        previous_provider_id = self.config_manager.get(CONFIG_LLM_PROVIDER, "")
        previous_model_name = self.config_manager.get(CONFIG_LLM_MODEL, "")
        previous_model_id = (
            f"{previous_provider_id}:{previous_model_name}"
            if previous_provider_id and previous_model_name else ""
        )
        
        # 保存厂商选择
        self.config_manager.set(CONFIG_LLM_PROVIDER, provider_id)

        # 云端模型配置
        # 保存 LLM 凭证到 CredentialManager
        if self.credential_manager:
            api_key = self._api_key_edit.text().strip()
            if api_key:
                self.credential_manager.set_llm_api_key(provider_id, api_key)
            else:
                self.credential_manager.delete_credential("llm", provider_id)

        self.config_manager.set(CONFIG_LLM_BASE_URL, self._base_url_edit.text())
        self.config_manager.set(CONFIG_LLM_MODEL, self._model_combo.currentText())
        self.config_manager.set(CONFIG_LLM_STREAMING, self._streaming_check.isChecked())
        self.config_manager.set(CONFIG_LLM_TIMEOUT, self._timeout_spin.value())

        self.config_manager.set(CONFIG_EMBEDDING_PROVIDER, embedding_provider_id)
        self.config_manager.set(CONFIG_EMBEDDING_MODEL, self._embedding_model_combo.currentText())
        self.config_manager.set(CONFIG_EMBEDDING_BASE_URL, self._embedding_base_url_edit.text().strip())
        self.config_manager.set(CONFIG_EMBEDDING_TIMEOUT, self._embedding_timeout_spin.value())
        self.config_manager.set(CONFIG_EMBEDDING_BATCH_SIZE, self._embedding_batch_size_spin.value())
        if self.credential_manager and embedding_provider_id:
            embedding_api_key = self._embedding_api_key_edit.text().strip()
            if embedding_api_key:
                self.credential_manager.set_embedding_api_key(embedding_provider_id, embedding_api_key)
            else:
                self.credential_manager.delete_credential("embedding", embedding_provider_id)
        
        # 保存其他配置
        self.config_manager.set(CONFIG_ENABLE_THINKING, self._deep_think_check.isChecked())
        self.config_manager.set(CONFIG_THINKING_TIMEOUT, self._thinking_timeout_spin.value())
        self.config_manager.set(CONFIG_ENABLE_PROVIDER_WEB_SEARCH, self._provider_web_search_check.isChecked())
        self.config_manager.set(CONFIG_ENABLE_GENERAL_WEB_SEARCH, self._general_search_check.isChecked())
        self.config_manager.set(CONFIG_GENERAL_WEB_SEARCH_PROVIDER, search_provider_id)

        if self.credential_manager:
            search_api_key = self._general_search_api_key_edit.text().strip()
            if search_api_key:
                google_cx = self._google_cx_edit.text().strip() if search_provider_id == WEB_SEARCH_GOOGLE else None
                self.credential_manager.set_search_credential(search_provider_id, search_api_key, google_cx)
            else:
                self.credential_manager.delete_credential("search", search_provider_id)
        
        if self.logger:
            self.logger.info(f"Model configuration saved: provider={provider_id}, model={self._model_combo.currentText()}")
        
        self._request_llm_runtime_refresh(
            provider_id=provider_id,
            old_model_id=previous_model_id,
        )
        
        return True

    def _validate_config(self) -> bool:
        """校验配置"""
        if self._timeout_spin.value() <= 0:
            QMessageBox.warning(
                self,
                self._get_text("dialog.warning", "Warning"),
                self._get_text("dialog.model_config.error.invalid_timeout", "Timeout must be greater than 0")
            )
            self._timeout_spin.setFocus()
            return False

        if self._embedding_timeout_spin.value() <= 0:
            QMessageBox.warning(
                self,
                self._get_text("dialog.warning", "Warning"),
                self._get_text("dialog.model_config.error.invalid_timeout", "Timeout must be greater than 0")
            )
            self._embedding_timeout_spin.setFocus()
            return False

        if self._embedding_batch_size_spin.value() <= 0:
            QMessageBox.warning(
                self,
                self._get_text("dialog.warning", "Warning"),
                self._get_text("dialog.model_config.error.invalid_batch_size", "Batch size must be greater than 0")
            )
            self._embedding_batch_size_spin.setFocus()
            return False
        
        # 联网搜索互斥校验（防御性检查，UI 已确保互斥）
        provider_search = self._provider_web_search_check.isChecked()
        general_search = self._general_search_check.isChecked()
        if provider_search and general_search:
            # 理论上不应该发生，但作为防御性检查
            QMessageBox.warning(
                self,
                self._get_text("dialog.warning", "Warning"),
                self._get_text(
                    "dialog.model_config.error.search_mutex",
                    "Provider web search and general web search cannot be enabled at the same time."
                )
            )
            return False
        
        return True

    def _request_llm_runtime_refresh(
        self,
        provider_id: str,
        old_model_id: str,
    ) -> None:
        """
        请求刷新 LLM 运行时
        
        在配置保存后调用，发布 EVENT_LLM_CONFIG_CHANGED，由应用层（bootstrap）
        订阅该事件并负责刷新运行时和统一广播模型变更。界面层不直接操作运行时。
        """
        try:
            model = self._model_combo.currentText()

            if self.event_bus:
                from shared.event_types import EVENT_LLM_CONFIG_CHANGED
                self.event_bus.publish(
                    EVENT_LLM_CONFIG_CHANGED,
                    data={
                        "provider": provider_id,
                        "model": model,
                        "old_model_id": old_model_id,
                        "source": "model_config_dialog",
                    }
                )
                    
        except Exception as e:
            if self.logger:
                self.logger.error(f"请求 LLM 运行时刷新失败: {e}")

    # ============================================================
    # 事件处理
    # ============================================================

    def _populate_chat_providers(self) -> None:
        if self._provider_combo is None:
            return

        self._provider_combo.blockSignals(True)
        self._provider_combo.clear()
        for provider in self._list_chat_providers():
            self._provider_combo.addItem(provider.display_name, provider.id)
        self._provider_combo.blockSignals(False)

    def _list_chat_providers(self):
        try:
            from shared.model_registry import ModelRegistry
            ModelRegistry.initialize()
            return ModelRegistry.list_implemented_providers()
        except Exception as e:
            if self.logger:
                self.logger.error(f"加载对话模型厂商失败: {e}")
            return []

    def _get_chat_provider(self, provider_id: str):
        if not provider_id:
            return None

        try:
            from shared.model_registry import ModelRegistry
            ModelRegistry.initialize()
            return ModelRegistry.get_provider(provider_id)
        except Exception as e:
            if self.logger:
                self.logger.error(f"读取对话模型厂商配置失败: {e}")
            return None

    def _on_provider_changed(self, index: int):
        """厂商选择变更"""
        provider_id = self._provider_combo.currentData()
        provider = self._get_chat_provider(provider_id)

        self._model_combo.clear()
        models = self._get_models_for_provider(provider_id)
        for model in models:
            self._model_combo.addItem(model)

        # 设置默认模型
        default_model = provider.default_model if provider else ""
        if default_model:
            idx = self._model_combo.findText(default_model, Qt.MatchFlag.MatchFixedString)
            if idx >= 0:
                self._model_combo.setCurrentIndex(idx)

        # 更新 Base URL 占位符
        base_url = provider.base_url if provider else ""
        self._base_url_edit.setPlaceholderText(base_url)
        self._base_url_edit.setText(base_url)

        # 从 CredentialManager 加载该厂商的已保存凭证
        if self.credential_manager and provider_id:
            saved_api_key = self.credential_manager.get_llm_api_key(provider_id)
            self._api_key_edit.setText(saved_api_key)
        else:
            self._api_key_edit.setText("")
        
        supports_thinking = self._provider_supports_thinking(provider_id)
        supports_web_search = provider.supports_web_search if provider else False
        
        self._update_provider_features(supports_thinking, supports_web_search)
        
        # 重置验证状态
        self._reset_validation_status()
    
    def _get_models_for_provider(self, provider_id: str) -> List[str]:
        """从 ModelRegistry 获取厂商的模型列表"""
        try:
            from shared.model_registry import ModelRegistry
            return ModelRegistry.list_model_names(provider_id)
        except Exception:
            return []
    
    def _provider_supports_thinking(self, provider_id: str) -> bool:
        """检查厂商是否有任何模型支持深度思考"""
        try:
            from shared.model_registry import ModelRegistry
            models = ModelRegistry.list_models(provider_id)
            return any(m.supports_thinking for m in models)
        except Exception:
            return False

    def _populate_embedding_providers(self, force_refresh: bool = False) -> None:
        if self._embedding_provider_combo is None:
            return

        if force_refresh:
            self._embedding_provider_combo.blockSignals(True)
            self._embedding_provider_combo.clear()
            self._embedding_provider_combo.blockSignals(False)
        elif self._embedding_provider_combo.count() > 0:
            return

        try:
            from shared.embedding_model_registry import EmbeddingModelRegistry
            EmbeddingModelRegistry.initialize()
            providers = EmbeddingModelRegistry.list_implemented_providers()
        except Exception as e:
            if self.logger:
                self.logger.error(f"加载嵌入模型厂商失败: {e}")
            return

        for provider in providers:
            self._embedding_provider_combo.addItem(provider.display_name, provider.id)

    def _get_embedding_provider(self, provider_id: str):
        if not provider_id:
            return None

        try:
            from shared.embedding_model_registry import EmbeddingModelRegistry
            EmbeddingModelRegistry.initialize()
            return EmbeddingModelRegistry.get_provider(provider_id)
        except Exception as e:
            if self.logger:
                self.logger.error(f"读取嵌入模型厂商配置失败: {e}")
            return None

    def _on_embedding_provider_changed(self, index: int):
        provider_id = self._embedding_provider_combo.currentData()
        if not provider_id:
            return

        self._embedding_model_combo.clear()
        provider = self._get_embedding_provider(provider_id)
        if provider is None:
            self._embedding_base_url_edit.clear()
            return

        try:
            from shared.embedding_model_registry import EmbeddingModelRegistry
            EmbeddingModelRegistry.initialize()
            model_names = EmbeddingModelRegistry.list_model_names(provider_id)
            for model_name in model_names:
                self._embedding_model_combo.addItem(model_name)
        except Exception as e:
            if self.logger:
                self.logger.error(f"加载嵌入模型列表失败: {e}")
            model_names = []

        default_model = provider.default_model
        if default_model:
            model_index = self._embedding_model_combo.findText(default_model, Qt.MatchFlag.MatchFixedString)
            if model_index >= 0:
                self._embedding_model_combo.setCurrentIndex(model_index)

        base_url = provider.base_url
        self._embedding_base_url_edit.setPlaceholderText(base_url)
        self._embedding_base_url_edit.setText(base_url)

        if self.credential_manager:
            self._embedding_api_key_edit.setText(
                self.credential_manager.get_embedding_api_key(provider_id)
            )

    def _update_provider_features(self, supports_thinking: bool, supports_web_search: bool):
        """更新厂商专属功能组的显示状态"""
        self._deep_think_check.setEnabled(supports_thinking)
        self._thinking_timeout_spin.setEnabled(
            supports_thinking and self._deep_think_check.isChecked()
        )
        self._api_key_edit.setEnabled(True)

        if not supports_thinking:
            self._deep_think_check.setChecked(False)

        if not supports_web_search:
            self._provider_web_search_check.setChecked(False)

        self._update_provider_search_availability()

    def _on_deep_think_changed(self, state: int):
        """深度思考开关变化"""
        enabled = state == Qt.CheckState.Checked.value
        provider_id = self._provider_combo.currentData()
        supports_thinking = self._provider_supports_thinking(provider_id)
        
        self._thinking_timeout_spin.setEnabled(enabled and supports_thinking)

    def _on_provider_web_search_changed(self, state: int):
        """厂商专属联网搜索开关变化"""
        enabled = state == Qt.CheckState.Checked.value
        
        # 互斥逻辑：启用厂商专属搜索时禁用通用搜索
        if enabled:
            self._general_search_check.setChecked(False)
            self._general_search_check.setEnabled(False)
            self._general_search_check.setToolTip(
                self._get_text(
                    "dialog.model_config.search_mutex_hint_provider",
                    "Disabled: Provider web search is enabled"
                )
            )
            # 禁用通用搜索的子控件
            self._general_search_provider_combo.setEnabled(False)
            self._general_search_api_key_edit.setEnabled(False)
            self._google_cx_edit.setEnabled(False)
        else:
            # 恢复通用搜索的可用状态
            self._general_search_check.setEnabled(True)
            self._general_search_check.setToolTip("")

    def _update_provider_search_availability(self):
        """更新厂商专属搜索的可用状态"""
        provider_id = self._provider_combo.currentData()
        provider = self._get_chat_provider(provider_id)
        supports_web_search = provider.supports_web_search if provider else False
        
        general_search_enabled = self._general_search_check.isChecked()
        can_enable = supports_web_search and not general_search_enabled
        
        self._provider_web_search_check.setEnabled(can_enable)
        
        if not can_enable:
            if general_search_enabled:
                self._provider_web_search_check.setToolTip(
                    self._get_text(
                        "dialog.model_config.search_mutex_hint",
                        "Disabled: General web search is enabled"
                    )
                )
            elif not supports_web_search:
                self._provider_web_search_check.setToolTip(
                    self._get_text(
                        "dialog.model_config.provider_no_web_search",
                        "This provider does not support built-in web search"
                    )
                )
            else:
                self._provider_web_search_check.setToolTip("")
        else:
            self._provider_web_search_check.setToolTip("")

    def _on_general_search_changed(self, state: int):
        """通用联网搜索开关变化"""
        enabled = state == Qt.CheckState.Checked.value
        self._general_search_provider_combo.setEnabled(enabled)
        self._general_search_api_key_edit.setEnabled(enabled)
        
        # 互斥逻辑：启用通用搜索时禁用厂商专属搜索
        if enabled:
            self._provider_web_search_check.setChecked(False)
            self._provider_web_search_check.setEnabled(False)
            self._provider_web_search_check.setToolTip(
                self._get_text(
                    "dialog.model_config.search_mutex_hint",
                    "Disabled: General web search is enabled"
                )
            )
        else:
            # 恢复厂商专属搜索的可用状态（如果厂商支持）
            self._update_provider_search_availability()
        
        # 根据当前选择的供应商更新 Google cx 可见性
        if enabled:
            self._on_general_search_provider_changed(
                self._general_search_provider_combo.currentIndex()
            )
        else:
            self._google_cx_edit.setEnabled(False)

    def _on_general_search_provider_changed(self, index: int):
        """通用搜索供应商变化"""
        provider_id = self._general_search_provider_combo.currentData()
        enabled = self._general_search_check.isChecked()
        
        if provider_id == WEB_SEARCH_GOOGLE:
            # Google：显示搜索引擎 ID
            self._google_cx_label.setVisible(True)
            self._google_cx_edit.setVisible(True)
            self._google_cx_edit.setEnabled(enabled)
        else:
            # Bing：隐藏搜索引擎 ID
            self._google_cx_label.setVisible(False)
            self._google_cx_edit.setVisible(False)
            self._google_cx_edit.setEnabled(False)

    def _on_test_connection(self):
        """测试连接"""
        provider_id = self._provider_combo.currentData()
        
        api_key = self._api_key_edit.text().strip()
        if not api_key:
            QMessageBox.warning(
                self,
                self._get_text("dialog.warning", "Warning"),
                self._get_text(
                    "dialog.model_config.error.no_api_key",
                    "Please enter an API Key first."
                )
            )
            return
        
        # 更新状态为测试中
        self._update_validation_status("testing", "")
        self._test_btn.setEnabled(False)
        
        # 使用 QTimer 延迟执行测试，避免阻塞 UI
        from PyQt6.QtCore import QTimer
        QTimer.singleShot(100, lambda: self._do_test_connection(provider_id, api_key))

    def _do_test_connection(self, provider_id: str, api_key: str):
        """执行实际的连接测试"""
        try:
            from infrastructure.llm_adapters import LLMClientFactory

            base_url = self._base_url_edit.text().strip()
            model = self._model_combo.currentText()
            timeout = self._timeout_spin.value()
            client = LLMClientFactory.create_client(
                provider_id=provider_id,
                api_key=api_key,
                base_url=base_url if base_url else None,
                model=model if model else None,
                timeout=timeout,
            )
            response = client.chat(
                messages=[{"role": "user", "content": "Hi"}],
                streaming=False,
                thinking=False,
            )
            success = bool(response.content or response.tool_calls is not None)
            message = ""
            
            # 更新状态
            if success:
                self._update_validation_status("verified", "")
                self._save_verification_timestamp(provider_id)
            else:
                self._update_validation_status("failed", message)
                
        except Exception as e:
            if self.logger:
                self.logger.error(f"Connection test failed: {e}")
            self._update_validation_status("failed", str(e))
        finally:
            self._test_btn.setEnabled(True)

    def _save_verification_timestamp(self, provider_id: str):
        """保存验证时间戳"""
        if self.config_manager:
            from datetime import datetime
            timestamp = datetime.now().isoformat()
            self.config_manager.set(f"llm_verified_at_{provider_id}", timestamp)

    def _load_verification_timestamp(self, provider_id: str) -> str:
        """加载验证时间戳"""
        if self.config_manager:
            return self.config_manager.get(f"llm_verified_at_{provider_id}", "")
        return ""

    def _on_save(self):
        """保存按钮点击"""
        status = self._status_label.property("validation_status")
        if status != "verified":
            result = QMessageBox.question(
                self,
                self._get_text("dialog.confirm", "Confirm"),
                self._get_text(
                    "dialog.model_config.save_without_verify",
                    "API Key has not been verified. Save anyway?"
                ),
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No
            )
            if result != QMessageBox.StandardButton.Yes:
                return
        
        if self.save_config():
            self.accept()

    def _reset_validation_status(self):
        """重置验证状态（厂商切换时调用）"""
        # 检查新厂商是否之前已验证过
        provider_id = self._provider_combo.currentData()
        self._check_and_update_verification_status(provider_id)
    
    def _check_and_update_verification_status(self, provider_id: str):
        """
        检查并更新验证状态
        
        如果该厂商之前已验证过且 API Key 未变更，显示"已验证"状态。
        """
        if not provider_id:
            self._update_validation_status("not_verified", "")
            return
        
        # 检查是否有验证时间戳
        verified_at = self._load_verification_timestamp(provider_id)
        if not verified_at:
            self._update_validation_status("not_verified", "")
            return
        
        # 检查当前 API Key 是否与已保存的一致
        current_api_key = self._api_key_edit.text().strip()
        saved_api_key = ""
        if self.credential_manager:
            saved_api_key = self.credential_manager.get_llm_api_key(provider_id)
        
        if current_api_key and current_api_key == saved_api_key:
            # API Key 未变更，显示已验证状态
            self._update_validation_status("verified", "")
        else:
            # API Key 已变更或为空，需要重新验证
            self._update_validation_status("not_verified", "")

    def _update_validation_status(self, status: str, message: str):
        """更新验证状态显示"""
        self._status_label.setProperty("validation_status", status)
        
        if status == "not_verified":
            self._status_label.setText(
                self._get_text("dialog.model_config.status.not_verified", "Not verified")
            )
            self._status_label.setStyleSheet("color: #666;")
        elif status == "testing":
            self._status_label.setText(
                self._get_text("dialog.model_config.status.testing", "Testing...")
            )
            self._status_label.setStyleSheet("color: #4a9eff;")
        elif status == "verified":
            self._status_label.setText(
                self._get_text("dialog.model_config.status.verified", "Connection successful")
            )
            self._status_label.setStyleSheet("color: #4caf50;")
        elif status == "failed":
            error_text = self._get_text("dialog.model_config.status.failed", "Connection failed")
            if message:
                error_text += f": {message}"
            self._status_label.setText(error_text)
            self._status_label.setStyleSheet("color: #f44336;")


    # ============================================================
    # 国际化支持
    # ============================================================

    def retranslate_ui(self):
        """刷新所有 UI 文本"""
        # 对话框标题
        self.setWindowTitle(
            self._get_text("dialog.model_config.title", "Model Configuration")
        )

        if self._tab_widget:
            self._tab_widget.setTabText(
                0,
                self._get_text("dialog.model_config.tab.chat", "对话模型配置")
            )
            self._tab_widget.setTabText(
                1,
                self._get_text("dialog.model_config.tab.embedding", "嵌入模型配置")
            )
        
        # 组标题
        for group in self.findChildren(QGroupBox):
            group_type = group.property("group_type")
            if group_type == "provider_model":
                group.setTitle(self._get_text("dialog.model_config.group.provider_model", "Provider & Model"))
            elif group_type == "api_config":
                group.setTitle(self._get_text("dialog.model_config.group.api_config", "API Configuration"))
            elif group_type == "embedding_config":
                group.setTitle(self._get_text("dialog.model_config.group.embedding_config", "Embedding Configuration"))
            elif group_type == "provider_features":
                group.setTitle(self._get_text("dialog.model_config.group.provider_features", "Provider Features"))
            elif group_type == "general_search":
                group.setTitle(self._get_text("dialog.model_config.group.general_search", "General Web Search"))
        
        # 标签文本
        for label in self.findChildren(QLabel):
            label_type = label.property("label_type")
            if label_type == "provider":
                label.setText(self._get_text("dialog.model_config.label.provider", "Provider"))
            elif label_type == "model":
                label.setText(self._get_text("dialog.model_config.label.model", "Model"))
            elif label_type == "api_key":
                label.setText(self._get_text("dialog.model_config.label.api_key", "API Key"))
            elif label_type == "base_url":
                label.setText(self._get_text("dialog.model_config.label.base_url", "Base URL"))
            elif label_type == "streaming":
                label.setText(self._get_text("dialog.model_config.label.streaming", "Streaming Output"))
            elif label_type == "timeout":
                label.setText(self._get_text("dialog.model_config.label.timeout", "Timeout"))
            elif label_type == "embedding_provider":
                label.setText(self._get_text("dialog.model_config.label.embedding_provider", "Embedding Provider"))
            elif label_type == "embedding_model":
                label.setText(self._get_text("dialog.model_config.label.embedding_model", "Embedding Model"))
            elif label_type == "embedding_api_key":
                label.setText(self._get_text("dialog.model_config.label.embedding_api_key", "Embedding API Key"))
            elif label_type == "embedding_base_url":
                label.setText(self._get_text("dialog.model_config.label.embedding_base_url", "Embedding Base URL"))
            elif label_type == "embedding_timeout":
                label.setText(self._get_text("dialog.model_config.label.embedding_timeout", "Embedding Timeout"))
            elif label_type == "embedding_batch_size":
                label.setText(self._get_text("dialog.model_config.label.embedding_batch_size", "Embedding Batch Size"))
            elif label_type == "deep_think":
                label.setText(self._get_text("dialog.model_config.label.deep_think", "Deep Thinking"))
            elif label_type == "thinking_timeout":
                label.setText(self._get_text("dialog.model_config.label.thinking_timeout", "Thinking Timeout"))
            elif label_type == "provider_web_search":
                label.setText(self._get_text("dialog.model_config.label.provider_web_search", "Provider Web Search"))
            elif label_type == "general_search":
                label.setText(self._get_text("dialog.model_config.label.general_search", "Enable Web Search"))
            elif label_type == "general_search_provider":
                label.setText(self._get_text("dialog.model_config.label.general_search_provider", "Search Provider"))
            elif label_type == "general_search_api_key":
                label.setText(self._get_text("dialog.model_config.label.general_search_api_key", "Search API Key"))
            elif label_type == "google_cx":
                label.setText(self._get_text("dialog.model_config.label.google_cx", "Search Engine ID (cx)"))
        
        # 按钮文本
        self._test_btn.setText(
            self._get_text("dialog.model_config.btn.test", "Test Connection")
        )
        self._save_btn.setText(self._get_text("btn.save", "Save"))
        self._cancel_btn.setText(self._get_text("btn.cancel", "Cancel"))
        
        # 更新验证状态文本
        status = self._status_label.property("validation_status")
        if status:
            self._update_validation_status(status, "")

    def _subscribe_events(self):
        """订阅事件"""
        if self.event_bus:
            from shared.event_types import EVENT_LANGUAGE_CHANGED
            self.event_bus.subscribe(EVENT_LANGUAGE_CHANGED, self._on_event_language_changed)

    def _on_event_language_changed(self, event_data: Dict[str, Any]):
        """语言变更事件处理"""
        self.retranslate_ui()
    
    def closeEvent(self, event):
        """Clean up temporary files when dialog closes"""
        self._cleanup_temp_files()
        super().closeEvent(event)
    
    def _cleanup_temp_files(self):
        """清理临时图标文件（仅在使用临时目录时）"""
        if hasattr(self, "_temp_dir") and self._temp_dir:
            if os.path.exists(self._temp_dir):
                try:
                    import shutil
                    shutil.rmtree(self._temp_dir, ignore_errors=True)
                except Exception:
                    pass
            self._temp_dir = None


# ============================================================
# 模块导出
# ============================================================

__all__ = [
    "ModelConfigDialog",
]
