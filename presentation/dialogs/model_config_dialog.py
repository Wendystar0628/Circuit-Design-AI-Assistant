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
    QPushButton, QGroupBox, QMessageBox, QWidget, QFrame
)
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QPixmap, QPainter, QColor

from infrastructure.config.settings import (
    PROVIDER_DEFAULTS,
    SUPPORTED_LLM_PROVIDERS,
    LLM_PROVIDER_ZHIPU,
    LLM_PROVIDER_DEEPSEEK,
    LLM_PROVIDER_QWEN,
    LLM_PROVIDER_OPENAI,
    LLM_PROVIDER_ANTHROPIC,
    WEB_SEARCH_GOOGLE,
    WEB_SEARCH_BING,
    SUPPORTED_GENERAL_WEB_SEARCH,
    CONFIG_LLM_PROVIDER,
    CONFIG_API_KEY,
    CONFIG_BASE_URL,
    CONFIG_MODEL,
    CONFIG_TIMEOUT,
    CONFIG_STREAMING,
    CONFIG_ENABLE_THINKING,
    CONFIG_THINKING_TIMEOUT,
    CONFIG_ENABLE_PROVIDER_WEB_SEARCH,
    CONFIG_ENABLE_GENERAL_WEB_SEARCH,
    CONFIG_GENERAL_WEB_SEARCH_PROVIDER,
    CONFIG_GENERAL_WEB_SEARCH_API_KEY,
    CONFIG_GOOGLE_SEARCH_CX,
    DEFAULT_BASE_URL,
    DEFAULT_MODEL,
    DEFAULT_TIMEOUT,
    DEFAULT_THINKING_TIMEOUT,
)


# ============================================================
# 厂商显示名称映射
# ============================================================

PROVIDER_DISPLAY_NAMES: Dict[str, str] = {
    LLM_PROVIDER_ZHIPU: "智谱 AI (Zhipu)",
    LLM_PROVIDER_DEEPSEEK: "DeepSeek",
    LLM_PROVIDER_QWEN: "通义千问 (Qwen)",
    LLM_PROVIDER_OPENAI: "OpenAI",
    LLM_PROVIDER_ANTHROPIC: "Anthropic Claude",
}


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
        
        # 厂商专属功能组件
        self._provider_features_group: Optional[QGroupBox] = None
        self._deep_think_check: Optional[QCheckBox] = None
        self._thinking_timeout_spin: Optional[QSpinBox] = None
        self._provider_web_search_check: Optional[QCheckBox] = None
        self._not_implemented_label: Optional[QLabel] = None
        
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
    
    def _setup_custom_styles(self):
        """设置自定义样式：复选框打钩、下拉框箭头"""
        # 创建临时目录存放图标
        self._temp_dir = tempfile.mkdtemp(prefix="circuit_ai_icons_")
        
        # 创建打钩图标 (checkmark.svg) - 白色打钩在蓝色背景上
        checkmark_svg = '''<svg xmlns="http://www.w3.org/2000/svg" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="#ffffff" stroke-width="3" stroke-linecap="round" stroke-linejoin="round"><polyline points="20 6 9 17 4 12"></polyline></svg>'''
        checkmark_path = os.path.join(self._temp_dir, "checkmark.svg")
        with open(checkmark_path, "w", encoding="utf-8") as f:
            f.write(checkmark_svg)
        
        # 创建下拉箭头图标 (dropdown.svg)
        dropdown_svg = '''<svg xmlns="http://www.w3.org/2000/svg" width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="#666" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="6 9 12 15 18 9"></polyline></svg>'''
        dropdown_path = os.path.join(self._temp_dir, "dropdown.svg")
        with open(dropdown_path, "w", encoding="utf-8") as f:
            f.write(dropdown_svg)
        
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
        
        # 1. 厂商和模型选择组
        main_layout.addWidget(self._create_provider_model_group())
        
        # 2. API 配置组
        main_layout.addWidget(self._create_api_config_group())
        
        # 3. 厂商专属功能组（选择模型后显示）
        self._provider_features_group = self._create_provider_features_group()
        main_layout.addWidget(self._provider_features_group)
        
        # 4. 通用联网搜索组
        self._general_search_group = self._create_general_search_group()
        main_layout.addWidget(self._general_search_group)
        
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
        for provider_id in SUPPORTED_LLM_PROVIDERS:
            display_name = PROVIDER_DISPLAY_NAMES.get(provider_id, provider_id)
            defaults = PROVIDER_DEFAULTS.get(provider_id, {})
            # 未实现的厂商添加标记
            if not defaults.get("implemented", False):
                display_name += " (Coming Soon)"
            self._provider_combo.addItem(display_name, provider_id)
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
        self._base_url_edit.setPlaceholderText(DEFAULT_BASE_URL)
        
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


    def _create_provider_features_group(self) -> QGroupBox:
        """创建厂商专属功能组"""
        group = QGroupBox()
        group.setProperty("group_type", "provider_features")
        layout = QVBoxLayout(group)
        
        # 未实现提示标签
        self._not_implemented_label = QLabel()
        self._not_implemented_label.setStyleSheet(
            "color: #ff9800; padding: 10px; background-color: #fff3e0; "
            "border-radius: 4px;"
        )
        self._not_implemented_label.setWordWrap(True)
        self._not_implemented_label.setVisible(False)
        layout.addWidget(self._not_implemented_label)
        
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
            return
        
        # 厂商
        provider = self.config_manager.get(CONFIG_LLM_PROVIDER, LLM_PROVIDER_ZHIPU)
        if not provider:
            provider = LLM_PROVIDER_ZHIPU
        index = self._provider_combo.findData(provider)
        if index >= 0:
            self._provider_combo.setCurrentIndex(index)
        else:
            self._provider_combo.setCurrentIndex(0)
        
        # 触发厂商变更以更新模型列表
        self._on_provider_changed(self._provider_combo.currentIndex())
        
        # 模型
        model = self.config_manager.get(CONFIG_MODEL, DEFAULT_MODEL)
        index = self._model_combo.findText(model, Qt.MatchFlag.MatchFixedString)
        if index >= 0:
            self._model_combo.setCurrentIndex(index)
        
        # API Key（从 CredentialManager 获取当前厂商的凭证）
        api_key = ""
        if self.credential_manager and provider:
            api_key = self.credential_manager.get_llm_api_key(provider)
        self._api_key_edit.setText(api_key)
        
        # Base URL
        base_url = self.config_manager.get(CONFIG_BASE_URL, "")
        self._base_url_edit.setText(base_url)
        
        # 流式输出
        streaming = self.config_manager.get(CONFIG_STREAMING, True)
        self._streaming_check.setChecked(streaming)
        
        # 超时
        timeout = self.config_manager.get(CONFIG_TIMEOUT, DEFAULT_TIMEOUT)
        self._timeout_spin.setValue(timeout)
        
        # 深度思考
        deep_think = self.config_manager.get(CONFIG_ENABLE_THINKING, True)
        self._deep_think_check.setChecked(deep_think)
        
        # 深度思考超时
        thinking_timeout = self.config_manager.get(CONFIG_THINKING_TIMEOUT, DEFAULT_THINKING_TIMEOUT)
        self._thinking_timeout_spin.setValue(thinking_timeout)
        self._thinking_timeout_spin.setEnabled(deep_think)
        
        # 通用搜索供应商
        search_provider = self.config_manager.get(CONFIG_GENERAL_WEB_SEARCH_PROVIDER, WEB_SEARCH_GOOGLE)
        index = self._general_search_provider_combo.findData(search_provider)
        if index >= 0:
            self._general_search_provider_combo.setCurrentIndex(index)
        
        # 通用搜索凭证（从 CredentialManager 获取）
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
        search_provider_id = self._general_search_provider_combo.currentData()
        
        # 保存 LLM 凭证到 CredentialManager
        if self.credential_manager:
            api_key = self._api_key_edit.text()
            if api_key:
                self.credential_manager.set_llm_api_key(provider_id, api_key)
            
            # 保存搜索凭证
            search_api_key = self._general_search_api_key_edit.text()
            if search_api_key:
                google_cx = self._google_cx_edit.text() if search_provider_id == WEB_SEARCH_GOOGLE else None
                self.credential_manager.set_search_credential(search_provider_id, search_api_key, google_cx)
        
        # 保存非敏感配置到 ConfigManager
        self.config_manager.set(CONFIG_LLM_PROVIDER, provider_id)
        self.config_manager.set(CONFIG_BASE_URL, self._base_url_edit.text())
        self.config_manager.set(CONFIG_MODEL, self._model_combo.currentText())
        self.config_manager.set(CONFIG_STREAMING, self._streaming_check.isChecked())
        self.config_manager.set(CONFIG_TIMEOUT, self._timeout_spin.value())
        self.config_manager.set(CONFIG_ENABLE_THINKING, self._deep_think_check.isChecked())
        self.config_manager.set(CONFIG_THINKING_TIMEOUT, self._thinking_timeout_spin.value())
        self.config_manager.set(CONFIG_ENABLE_PROVIDER_WEB_SEARCH, self._provider_web_search_check.isChecked())
        self.config_manager.set(CONFIG_ENABLE_GENERAL_WEB_SEARCH, self._general_search_check.isChecked())
        self.config_manager.set(CONFIG_GENERAL_WEB_SEARCH_PROVIDER, search_provider_id)
        
        if self.logger:
            self.logger.info(f"Model configuration saved: provider={provider_id}, model={self._model_combo.currentText()}")
        
        # 重新初始化 LLM 客户端
        self._reinit_llm_client(provider_id)
        
        return True

    def _validate_config(self) -> bool:
        """校验配置"""
        # 超时值必须 > 0
        if self._timeout_spin.value() <= 0:
            QMessageBox.warning(
                self,
                self._get_text("dialog.warning", "Warning"),
                self._get_text("dialog.model_config.error.invalid_timeout", "Timeout must be greater than 0")
            )
            self._timeout_spin.setFocus()
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

    def _reinit_llm_client(self, provider_id: str) -> None:
        """
        重新初始化 LLM 客户端
        
        在配置保存后调用，根据新配置创建 LLM 客户端并注册到 ServiceLocator。
        """
        try:
            from shared.service_locator import ServiceLocator
            from shared.service_names import SVC_LLM_CLIENT
            from infrastructure.config.settings import LLM_PROVIDER_ZHIPU
            
            # 获取凭证
            if not self.credential_manager:
                return
            
            credential = self.credential_manager.get_credential("llm", provider_id)
            if not credential or not credential.get("api_key"):
                if self.logger:
                    self.logger.warning(f"无法重新初始化 LLM 客户端：{provider_id} 的 API Key 未配置")
                return
            
            api_key = credential.get("api_key")
            base_url = self._base_url_edit.text().strip()
            model = self._model_combo.currentText()
            timeout = self._timeout_spin.value()
            
            # 根据厂商创建客户端
            if provider_id == LLM_PROVIDER_ZHIPU:
                from infrastructure.llm_adapters.zhipu import ZhipuClient
                
                client = ZhipuClient(
                    api_key=api_key,
                    base_url=base_url if base_url else None,
                    model=model if model else None,
                    timeout=timeout,
                )
                ServiceLocator.register(SVC_LLM_CLIENT, client)
                
                if self.logger:
                    self.logger.info(f"LLM 客户端已重新初始化：{provider_id}, model={model}")
            else:
                if self.logger:
                    self.logger.warning(f"LLM 客户端重新初始化跳过：厂商 {provider_id} 暂未实现")
                    
        except Exception as e:
            if self.logger:
                self.logger.error(f"重新初始化 LLM 客户端失败: {e}")

    # ============================================================
    # 事件处理
    # ============================================================

    def _on_provider_changed(self, index: int):
        """厂商选择变更"""
        provider_id = self._provider_combo.currentData()
        defaults = PROVIDER_DEFAULTS.get(provider_id, {})
        
        # 更新模型列表
        self._model_combo.clear()
        models = defaults.get("models", [])
        for model in models:
            self._model_combo.addItem(model)
        
        # 设置默认模型
        default_model = defaults.get("default_model", "")
        if default_model:
            index = self._model_combo.findText(default_model, Qt.MatchFlag.MatchFixedString)
            if index >= 0:
                self._model_combo.setCurrentIndex(index)
        
        # 更新 Base URL 占位符
        base_url = defaults.get("base_url", "")
        self._base_url_edit.setPlaceholderText(base_url)
        if not self._base_url_edit.text():
            self._base_url_edit.setText(base_url)
        
        # 从 CredentialManager 加载该厂商的已保存凭证
        if self.credential_manager and provider_id:
            saved_api_key = self.credential_manager.get_llm_api_key(provider_id)
            self._api_key_edit.setText(saved_api_key)
        else:
            self._api_key_edit.setText("")
        
        # 检查是否已实现
        implemented = defaults.get("implemented", False)
        supports_thinking = defaults.get("supports_thinking", False)
        supports_web_search = defaults.get("supports_web_search", False)
        
        # 更新厂商专属功能组
        self._update_provider_features(implemented, supports_thinking, supports_web_search)
        
        # 重置验证状态
        self._reset_validation_status()

    def _update_provider_features(self, implemented: bool, supports_thinking: bool, supports_web_search: bool):
        """更新厂商专属功能组的显示状态"""
        if not implemented:
            # 未实现：显示提示，禁用功能
            self._not_implemented_label.setVisible(True)
            self._not_implemented_label.setText(
                self._get_text(
                    "dialog.model_config.not_implemented",
                    "This provider is not yet implemented. Configuration will be saved but the provider cannot be used until implemented."
                )
            )
            self._deep_think_check.setEnabled(False)
            self._thinking_timeout_spin.setEnabled(False)
            self._provider_web_search_check.setEnabled(False)
            self._provider_web_search_check.setChecked(False)
            self._api_key_edit.setEnabled(True)  # 仍允许输入 API Key
        else:
            # 已实现：隐藏提示，根据支持情况启用功能
            self._not_implemented_label.setVisible(False)
            self._deep_think_check.setEnabled(supports_thinking)
            self._thinking_timeout_spin.setEnabled(
                supports_thinking and self._deep_think_check.isChecked()
            )
            self._api_key_edit.setEnabled(True)
            
            # 如果不支持深度思考，取消勾选
            if not supports_thinking:
                self._deep_think_check.setChecked(False)
            
            # 更新厂商专属搜索可用状态（考虑互斥逻辑）
            self._update_provider_search_availability()
            
            # 如果不支持厂商联网搜索，取消勾选
            if not supports_web_search:
                self._provider_web_search_check.setChecked(False)

    def _on_deep_think_changed(self, state: int):
        """深度思考开关变化"""
        enabled = state == Qt.CheckState.Checked.value
        provider_id = self._provider_combo.currentData()
        defaults = PROVIDER_DEFAULTS.get(provider_id, {})
        supports_thinking = defaults.get("supports_thinking", False)
        
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
        defaults = PROVIDER_DEFAULTS.get(provider_id, {})
        implemented = defaults.get("implemented", False)
        supports_web_search = defaults.get("supports_web_search", False)
        
        # 只有厂商已实现且支持联网搜索，且通用搜索未启用时才可用
        general_search_enabled = self._general_search_check.isChecked()
        can_enable = implemented and supports_web_search and not general_search_enabled
        
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
        defaults = PROVIDER_DEFAULTS.get(provider_id, {})
        
        if not defaults.get("implemented", False):
            QMessageBox.information(
                self,
                self._get_text("dialog.model_config.test_connection", "Test Connection"),
                self._get_text(
                    "dialog.model_config.provider_not_implemented",
                    "This provider is not yet implemented. Cannot test connection."
                )
            )
            return
        
        # 获取当前配置
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
            base_url = self._base_url_edit.text().strip()
            model = self._model_combo.currentText()
            
            # 根据厂商选择测试方法
            if provider_id == LLM_PROVIDER_ZHIPU:
                success, message = self._test_zhipu_connection(api_key, base_url, model)
            else:
                # 其他厂商暂未实现
                success = False
                message = self._get_text(
                    "dialog.model_config.provider_not_implemented",
                    "This provider is not yet implemented."
                )
            
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

    def _test_zhipu_connection(
        self, api_key: str, base_url: str, model: str
    ) -> tuple:
        """
        测试智谱 AI 连接
        
        Returns:
            (success: bool, message: str)
        """
        import httpx
        
        # 使用默认 base_url 如果未提供
        actual_base_url = base_url if base_url else "https://open.bigmodel.cn/api/paas/v4"
        url = f"{actual_base_url}/chat/completions"
        
        # 构建请求
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
        }
        
        request_body = {
            "model": model,
            "messages": [{"role": "user", "content": "Hi"}],
            "stream": False,
        }
        
        if self.logger:
            self.logger.info(f"Testing connection to: {url}")
            self.logger.info(f"Model: {model}")
            self.logger.debug(f"Request body: {request_body}")
        
        try:
            # 直接使用 httpx 发送请求，获取原始响应
            with httpx.Client(timeout=15.0) as client:
                response = client.post(url, json=request_body, headers=headers)
                
                status_code = response.status_code
                response_text = response.text
                
                if self.logger:
                    self.logger.info(f"Response status: {status_code}")
                    self.logger.debug(f"Response body: {response_text[:500]}")
                
                # 检查状态码
                if status_code == 200:
                    try:
                        data = response.json()
                        if "choices" in data and len(data["choices"]) > 0:
                            return True, ""
                        else:
                            return False, f"Unexpected response format: {response_text[:200]}"
                    except Exception as parse_err:
                        return False, f"Failed to parse response: {parse_err}"
                else:
                    # 返回详细的错误信息
                    return False, f"HTTP {status_code}: {response_text[:300]}"
                    
        except httpx.TimeoutException as e:
            if self.logger:
                self.logger.error(f"Timeout: {e}")
            return False, self._get_text(
                "dialog.model_config.error.timeout",
                "Request timed out, server may be slow"
            )
        except httpx.ConnectError as e:
            if self.logger:
                self.logger.error(f"Connect error: {e}")
            return False, self._get_text(
                "dialog.model_config.error.network",
                f"Connection failed: {e}"
            )
        except Exception as e:
            if self.logger:
                self.logger.error(f"Unexpected error: {type(e).__name__}: {e}")
            return False, f"{type(e).__name__}: {e}"

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
        
        # 组标题
        for group in self.findChildren(QGroupBox):
            group_type = group.property("group_type")
            if group_type == "provider_model":
                group.setTitle(self._get_text("dialog.model_config.group.provider_model", "Provider & Model"))
            elif group_type == "api_config":
                group.setTitle(self._get_text("dialog.model_config.group.api_config", "API Configuration"))
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
        
        # 更新未实现提示文本
        if self._not_implemented_label.isVisible():
            self._not_implemented_label.setText(
                self._get_text(
                    "dialog.model_config.not_implemented",
                    "This provider is not yet implemented. Configuration will be saved but the provider cannot be used until implemented."
                )
            )
        
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
        """对话框关闭时清理临时文件"""
        self._cleanup_temp_files()
        super().closeEvent(event)
    
    def _cleanup_temp_files(self):
        """清理临时图标文件"""
        if hasattr(self, "_temp_dir") and self._temp_dir and os.path.exists(self._temp_dir):
            try:
                import shutil
                shutil.rmtree(self._temp_dir, ignore_errors=True)
            except Exception:
                pass


# ============================================================
# 模块导出
# ============================================================

__all__ = [
    "ModelConfigDialog",
    "PROVIDER_DISPLAY_NAMES",
]
