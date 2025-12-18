# API Configuration Dialog
"""
API配置对话框

职责：
- 管理智谱GLM配置，包括API密钥、模型选择、高级选项
- 当前版本仅支持智谱GLM，后续可扩展其他提供者

国际化支持：
- 实现 retranslate_ui() 方法
- 订阅 EVENT_LANGUAGE_CHANGED 事件
"""

from typing import Optional, Dict, Any, List

from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QFormLayout,
    QLabel, QLineEdit, QComboBox, QCheckBox, QSpinBox,
    QPushButton, QGroupBox, QMessageBox, QWidget
)
from PyQt6.QtCore import Qt


# ============================================================
# 智谱GLM配置数据
# ============================================================

from infrastructure.config.settings import DEFAULT_BASE_URL


def get_zhipu_models() -> List[str]:
    """从 ModelRegistry 获取智谱模型列表"""
    try:
        from shared.model_registry import ModelRegistry
        return ModelRegistry.list_model_names("zhipu")
    except Exception:
        return ["glm-4.6", "glm-4.6v", "glm-4.6v-flash"]

# 搜索供应商列表
# 智谱内置搜索：无需额外配置，使用 LLM 的 API Key
# Google：需要 API Key + 搜索引擎 ID（cx）
# Bing：需要 API Key
SEARCH_PROVIDERS: List[Dict[str, str]] = [
    {"id": "zhipu_web_search", "name": "智谱内置搜索"},
    {"id": "google", "name": "Google"},
    {"id": "bing", "name": "Bing"},
]




# ============================================================
# API配置对话框
# ============================================================

class ApiConfigDialog(QDialog):
    """
    API配置对话框
    
    功能：
    - 智谱GLM API配置
    - API Key 和 Base URL 设置
    - 模型选择
    - 高级选项（流式输出、超时、深度思考、联网搜索）
    - 测试连接（阶段三实现）
    
    注意：语言切换功能已移至菜单栏"语言"菜单
    """

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        
        # 延迟获取的服务
        self._i18n_manager = None
        self._config_manager = None
        self._event_bus = None
        self._logger = None
        
        # UI 组件引用
        self._api_key_edit: Optional[QLineEdit] = None
        self._base_url_edit: Optional[QLineEdit] = None
        self._model_combo: Optional[QComboBox] = None
        self._streaming_check: Optional[QCheckBox] = None
        self._timeout_spin: Optional[QSpinBox] = None
        self._deep_think_check: Optional[QCheckBox] = None
        self._thinking_timeout_spin: Optional[QSpinBox] = None
        self._web_search_check: Optional[QCheckBox] = None
        self._search_provider_combo: Optional[QComboBox] = None
        self._search_api_key_edit: Optional[QLineEdit] = None
        self._search_api_key_label: Optional[QLabel] = None
        self._google_cx_edit: Optional[QLineEdit] = None
        self._google_cx_label: Optional[QLabel] = None
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
                self._logger = get_logger("api_config_dialog")
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
        self.setMinimumWidth(480)
        self.setModal(True)

    def _setup_ui(self):
        """设置 UI 布局"""
        main_layout = QVBoxLayout(self)
        main_layout.setSpacing(15)
        
        # LLM 配置组
        main_layout.addWidget(self._create_llm_group())
        
        # 高级选项组
        main_layout.addWidget(self._create_advanced_group())
        
        # 联网搜索组
        main_layout.addWidget(self._create_search_group())
        
        # 验证状态
        self._status_label = QLabel()
        self._status_label.setStyleSheet("color: #666;")
        main_layout.addWidget(self._status_label)
        
        # 按钮区域
        main_layout.addWidget(self._create_button_area())

    def _create_llm_group(self) -> QGroupBox:
        """创建 LLM 配置组"""
        group = QGroupBox()
        group.setProperty("group_type", "llm")
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
        self._base_url_edit.setText(DEFAULT_BASE_URL)
        
        base_url_label = QLabel()
        base_url_label.setProperty("label_type", "base_url")
        layout.addRow(base_url_label, self._base_url_edit)
        
        # 模型选择
        self._model_combo = QComboBox()
        for model in get_zhipu_models():
            self._model_combo.addItem(model)
        
        model_label = QLabel()
        model_label.setProperty("label_type", "model")
        layout.addRow(model_label, self._model_combo)
        
        return group

    def _create_advanced_group(self) -> QGroupBox:
        """创建高级选项组"""
        group = QGroupBox()
        group.setProperty("group_type", "advanced")
        layout = QFormLayout(group)
        
        # 流式输出
        self._streaming_check = QCheckBox()
        self._streaming_check.setChecked(True)
        
        streaming_label = QLabel()
        streaming_label.setProperty("label_type", "streaming")
        layout.addRow(streaming_label, self._streaming_check)
        
        # 超时设置
        self._timeout_spin = QSpinBox()
        self._timeout_spin.setRange(10, 300)
        self._timeout_spin.setValue(60)
        self._timeout_spin.setSuffix(" s")
        
        timeout_label = QLabel()
        timeout_label.setProperty("label_type", "timeout")
        layout.addRow(timeout_label, self._timeout_spin)
        
        # 深度思考
        self._deep_think_check = QCheckBox()
        self._deep_think_check.setChecked(True)  # 默认开启
        self._deep_think_check.stateChanged.connect(self._on_deep_think_changed)
        
        deep_think_label = QLabel()
        deep_think_label.setProperty("label_type", "deep_think")
        layout.addRow(deep_think_label, self._deep_think_check)
        
        # 深度思考超时（仅深度思考启用时显示）
        self._thinking_timeout_spin = QSpinBox()
        self._thinking_timeout_spin.setRange(60, 600)
        self._thinking_timeout_spin.setValue(300)
        self._thinking_timeout_spin.setSuffix(" s")
        
        thinking_timeout_label = QLabel()
        thinking_timeout_label.setProperty("label_type", "thinking_timeout")
        layout.addRow(thinking_timeout_label, self._thinking_timeout_spin)
        
        return group

    def _create_search_group(self) -> QGroupBox:
        """创建联网搜索组"""
        group = QGroupBox()
        group.setProperty("group_type", "search")
        layout = QFormLayout(group)
        
        # 联网搜索开关
        self._web_search_check = QCheckBox()
        self._web_search_check.stateChanged.connect(self._on_web_search_changed)
        
        search_label = QLabel()
        search_label.setProperty("label_type", "web_search")
        layout.addRow(search_label, self._web_search_check)
        
        # 搜索供应商
        self._search_provider_combo = QComboBox()
        for provider in SEARCH_PROVIDERS:
            self._search_provider_combo.addItem(provider["name"], provider["id"])
        self._search_provider_combo.setEnabled(False)
        self._search_provider_combo.currentIndexChanged.connect(self._on_search_provider_changed)
        
        provider_label = QLabel()
        provider_label.setProperty("label_type", "search_provider")
        layout.addRow(provider_label, self._search_provider_combo)
        
        # 搜索 API Key（智谱内置搜索时隐藏）
        self._search_api_key_edit = QLineEdit()
        self._search_api_key_edit.setEchoMode(QLineEdit.EchoMode.Password)
        self._search_api_key_edit.setEnabled(False)
        
        self._search_api_key_label = QLabel()
        self._search_api_key_label.setProperty("label_type", "search_api_key")
        layout.addRow(self._search_api_key_label, self._search_api_key_edit)
        
        # Google 搜索引擎 ID（仅选择 Google 时显示）
        self._google_cx_edit = QLineEdit()
        self._google_cx_edit.setEnabled(False)
        self._google_cx_edit.setPlaceholderText("Google Custom Search Engine ID")
        
        self._google_cx_label = QLabel()
        self._google_cx_label.setProperty("label_type", "google_cx")
        layout.addRow(self._google_cx_label, self._google_cx_edit)
        
        # 初始状态：隐藏 Google cx 输入框
        self._google_cx_label.setVisible(False)
        self._google_cx_edit.setVisible(False)
        
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
            return
        
        # API Key
        api_key = self.config_manager.get("api_key", "")
        self._api_key_edit.setText(api_key)
        
        # Base URL
        base_url = self.config_manager.get("base_url", DEFAULT_BASE_URL)
        self._base_url_edit.setText(base_url if base_url else DEFAULT_BASE_URL)
        
        # 模型
        model = self.config_manager.get("model", "GLM-4.6")
        index = self._model_combo.findText(model)
        if index >= 0:
            self._model_combo.setCurrentIndex(index)
        
        # 流式输出
        streaming = self.config_manager.get("streaming", True)
        self._streaming_check.setChecked(streaming)
        
        # 超时
        timeout = self.config_manager.get("timeout", 60)
        self._timeout_spin.setValue(timeout)
        
        # 深度思考
        deep_think = self.config_manager.get("enable_thinking", True)  # 默认开启
        self._deep_think_check.setChecked(deep_think)
        
        # 深度思考超时
        thinking_timeout = self.config_manager.get("thinking_timeout", 300)
        self._thinking_timeout_spin.setValue(thinking_timeout)
        self._thinking_timeout_spin.setEnabled(deep_think)
        
        # 联网搜索
        web_search = self.config_manager.get("enable_web_search", False)
        self._web_search_check.setChecked(web_search)
        
        # 搜索供应商（使用 id 匹配）
        search_provider = self.config_manager.get("web_search_provider", "zhipu_web_search")
        index = self._search_provider_combo.findData(search_provider)
        if index >= 0:
            self._search_provider_combo.setCurrentIndex(index)
        
        # 搜索 API Key
        search_api_key = self.config_manager.get("web_search_api_key", "")
        self._search_api_key_edit.setText(search_api_key)
        
        # Google 搜索引擎 ID
        google_cx = self.config_manager.get("google_search_cx", "")
        self._google_cx_edit.setText(google_cx)
        
        # 根据搜索供应商更新 UI 可见性
        self._on_search_provider_changed(self._search_provider_combo.currentIndex())
        
        # 更新验证状态
        self._update_validation_status("not_verified", "")

    def save_config(self) -> bool:
        """保存配置到文件"""
        if not self.config_manager:
            return False
        
        # 校验
        if not self._validate_config():
            return False
        
        # 保存配置
        self.config_manager.set("llm_provider", "智谱GLM")
        self.config_manager.set("api_key", self._api_key_edit.text())
        self.config_manager.set("base_url", self._base_url_edit.text())
        self.config_manager.set("model", self._model_combo.currentText())
        self.config_manager.set("streaming", self._streaming_check.isChecked())
        self.config_manager.set("timeout", self._timeout_spin.value())
        self.config_manager.set("enable_thinking", self._deep_think_check.isChecked())
        self.config_manager.set("thinking_timeout", self._thinking_timeout_spin.value())
        self.config_manager.set("enable_web_search", self._web_search_check.isChecked())
        self.config_manager.set("web_search_provider", self._search_provider_combo.currentData())
        self.config_manager.set("web_search_api_key", self._search_api_key_edit.text())
        self.config_manager.set("google_search_cx", self._google_cx_edit.text())
        
        if self.logger:
            self.logger.info("API configuration saved")
        
        return True

    def _validate_config(self) -> bool:
        """校验配置"""
        # API Key 可以为空（用户可以稍后配置）
        # 不再强制要求填写 API Key
        
        # 超时值必须 > 0
        if self._timeout_spin.value() <= 0:
            QMessageBox.warning(
                self,
                self._get_text("dialog.warning", "Warning"),
                self._get_text("dialog.api_config.error.invalid_timeout", "Timeout must be greater than 0")
            )
            self._timeout_spin.setFocus()
            return False
        
        return True


    # ============================================================
    # 事件处理
    # ============================================================

    def _on_deep_think_changed(self, state: int):
        """深度思考开关变化"""
        enabled = state == Qt.CheckState.Checked.value
        self._thinking_timeout_spin.setEnabled(enabled)

    def _on_web_search_changed(self, state: int):
        """联网搜索开关变化"""
        enabled = state == Qt.CheckState.Checked.value
        self._search_provider_combo.setEnabled(enabled)
        
        # 根据当前选择的供应商更新 UI
        if enabled:
            self._on_search_provider_changed(self._search_provider_combo.currentIndex())
        else:
            self._search_api_key_edit.setEnabled(False)
            self._google_cx_edit.setEnabled(False)
            self._google_cx_label.setVisible(False)
            self._google_cx_edit.setVisible(False)

    def _on_search_provider_changed(self, index: int):
        """搜索供应商变化"""
        provider_id = self._search_provider_combo.currentData()
        web_search_enabled = self._web_search_check.isChecked()
        
        if provider_id == "zhipu_web_search":
            # 智谱内置搜索：无需额外配置
            self._search_api_key_label.setVisible(False)
            self._search_api_key_edit.setVisible(False)
            self._search_api_key_edit.setEnabled(False)
            self._google_cx_label.setVisible(False)
            self._google_cx_edit.setVisible(False)
            self._google_cx_edit.setEnabled(False)
        elif provider_id == "google":
            # Google：需要 API Key + 搜索引擎 ID
            self._search_api_key_label.setVisible(True)
            self._search_api_key_edit.setVisible(True)
            self._search_api_key_edit.setEnabled(web_search_enabled)
            self._google_cx_label.setVisible(True)
            self._google_cx_edit.setVisible(True)
            self._google_cx_edit.setEnabled(web_search_enabled)
        elif provider_id == "bing":
            # Bing：仅需要 API Key
            self._search_api_key_label.setVisible(True)
            self._search_api_key_edit.setVisible(True)
            self._search_api_key_edit.setEnabled(web_search_enabled)
            self._google_cx_label.setVisible(False)
            self._google_cx_edit.setVisible(False)
            self._google_cx_edit.setEnabled(False)

    def _on_test_connection(self):
        """测试连接（阶段三实现）"""
        self._update_validation_status("testing", "")
        
        # TODO: 阶段三实现实际测试逻辑
        QMessageBox.information(
            self,
            self._get_text("dialog.api_config.test_connection", "Test Connection"),
            self._get_text(
                "dialog.api_config.test_not_implemented",
                "Connection test will be implemented in Phase 3"
            )
        )
        
        self._update_validation_status("not_verified", "")

    def _on_save(self):
        """保存按钮点击"""
        status = self._status_label.property("validation_status")
        if status != "verified":
            result = QMessageBox.question(
                self,
                self._get_text("dialog.confirm", "Confirm"),
                self._get_text(
                    "dialog.api_config.save_without_verify",
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
        """重置验证状态"""
        self._update_validation_status("not_verified", "")

    def _update_validation_status(self, status: str, message: str):
        """更新验证状态显示"""
        self._status_label.setProperty("validation_status", status)
        
        if status == "not_verified":
            self._status_label.setText(
                self._get_text("dialog.api_config.status.not_verified", "Not verified")
            )
            self._status_label.setStyleSheet("color: #666;")
        elif status == "testing":
            self._status_label.setText(
                self._get_text("dialog.api_config.status.testing", "Testing...")
            )
            self._status_label.setStyleSheet("color: #4a9eff;")
        elif status == "verified":
            self._status_label.setText(
                self._get_text("dialog.api_config.status.verified", "Connection successful")
            )
            self._status_label.setStyleSheet("color: #4caf50;")
        elif status == "failed":
            error_text = self._get_text("dialog.api_config.status.failed", "Connection failed")
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
            self._get_text("dialog.api_config.title", "API Configuration")
        )
        
        # 组标题
        for group in self.findChildren(QGroupBox):
            group_type = group.property("group_type")
            if group_type == "llm":
                group.setTitle(self._get_text("dialog.api_config.group.llm", "Zhipu GLM Configuration"))
            elif group_type == "advanced":
                group.setTitle(self._get_text("dialog.api_config.group.advanced", "Advanced Options"))
            elif group_type == "search":
                group.setTitle(self._get_text("dialog.api_config.group.search", "Web Search"))
        
        # 标签文本
        for label in self.findChildren(QLabel):
            label_type = label.property("label_type")
            if label_type == "api_key":
                label.setText(self._get_text("dialog.api_config.label.api_key", "API Key"))
            elif label_type == "base_url":
                label.setText(self._get_text("dialog.api_config.label.base_url", "Base URL"))
            elif label_type == "model":
                label.setText(self._get_text("dialog.api_config.label.model", "Model"))
            elif label_type == "streaming":
                label.setText(self._get_text("dialog.api_config.label.streaming", "Streaming Output"))
            elif label_type == "timeout":
                label.setText(self._get_text("dialog.api_config.label.timeout", "Timeout"))
            elif label_type == "deep_think":
                label.setText(self._get_text("dialog.api_config.label.deep_think", "Deep Thinking"))
            elif label_type == "thinking_timeout":
                label.setText(self._get_text("dialog.api_config.label.thinking_timeout", "Thinking Timeout"))
            elif label_type == "web_search":
                label.setText(self._get_text("dialog.api_config.label.web_search", "Enable Web Search"))
            elif label_type == "search_provider":
                label.setText(self._get_text("dialog.api_config.label.search_provider", "Search Provider"))
            elif label_type == "search_api_key":
                label.setText(self._get_text("dialog.api_config.label.search_api_key", "Search API Key"))
            elif label_type == "google_cx":
                label.setText(self._get_text("dialog.api_config.label.google_cx", "Search Engine ID (cx)"))
        
        # 按钮文本
        self._test_btn.setText(
            self._get_text("dialog.api_config.btn.test", "Test Connection")
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


# ============================================================
# 模块导出
# ============================================================

__all__ = [
    "ApiConfigDialog",
    "get_zhipu_models",
    "DEFAULT_BASE_URL",
]
