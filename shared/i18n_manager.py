# I18n Manager - Internationalization Management
"""
国际化管理器 - 统一管理多语言文本和语言切换

职责：
- 提供多语言文本获取接口
- 管理语言切换和 UI 刷新通知
- 与 ConfigManager 集成持久化语言设置

初始化顺序：
- Phase 1.3，依赖 ConfigManager（读取 language 配置）

设计原则：
- 延迟获取 ConfigManager 和 EventBus，避免初始化顺序问题
- 采用预制文本字典方案，无需外部翻译文件
- 语言切换通过 EventBus 通知所有 UI 组件

使用示例：
    from shared.i18n_manager import I18nManager
    
    i18n = I18nManager()
    
    # 获取文本
    title = i18n.get_text("app.title")
    
    # 切换语言
    i18n.set_language("zh_CN")
"""

from typing import Dict, List, Optional

from shared.event_types import EVENT_LANGUAGE_CHANGED


# ============================================================
# 支持的语言
# ============================================================

LANG_EN_US = "en_US"
LANG_ZH_CN = "zh_CN"

SUPPORTED_LANGUAGES = [LANG_EN_US, LANG_ZH_CN]

# 语言显示名称
LANGUAGE_NAMES = {
    LANG_EN_US: "English",
    LANG_ZH_CN: "简体中文",
}


# ============================================================
# 文本字典
# ============================================================

TEXTS: Dict[str, Dict[str, str]] = {
    LANG_EN_US: {
        # 应用标题
        "app.title": "Circuit AI Design Assistant",
        "app.version": "Version",
        
        # 菜单 - 文件
        "menu.file": "File",
        "menu.file.open": "Open Workspace",
        "menu.file.close": "Close Workspace",
        "menu.file.save": "Save",
        "menu.file.save_all": "Save All",
        "menu.file.exit": "Exit",
        
        # 菜单 - 编辑
        "menu.edit": "Edit",
        "menu.edit.undo": "Undo",
        "menu.edit.redo": "Redo",
        "menu.edit.cut": "Cut",
        "menu.edit.copy": "Copy",
        "menu.edit.paste": "Paste",
        
        # 菜单 - 视图
        "menu.view": "View",
        "menu.view.file_browser": "File Browser",
        "menu.view.code_editor": "Code Editor",
        "menu.view.chat_panel": "Chat Panel",
        "menu.view.simulation": "Simulation Results",
        
        # 菜单 - 仿真
        "menu.simulation": "Simulation",
        "menu.simulation.run": "Run Simulation",
        "menu.simulation.stop": "Stop Simulation",
        
        # 菜单 - 知识库
        "menu.knowledge": "Knowledge Base",
        "menu.knowledge.import": "Import Documents",
        "menu.knowledge.rebuild": "Rebuild Index",
        
        # 菜单 - 工具
        "menu.tools": "Tools",
        "menu.tools.api_config": "API Configuration",
        "menu.tools.compress_context": "Compress Context",
        
        # 菜单 - 设置
        "menu.settings": "Settings",
        "menu.settings.api_config": "API Configuration",
        "menu.settings.language": "Language",
        "menu.settings.preferences": "Preferences",
        
        # 菜单 - 帮助
        "menu.help": "Help",
        "menu.help.about": "About",
        "menu.help.documentation": "Documentation",
        
        # 按钮
        "btn.save": "Save",
        "btn.cancel": "Cancel",
        "btn.ok": "OK",
        "btn.apply": "Apply",
        "btn.send": "Send",
        "btn.stop": "Stop",
        "btn.continue": "Continue",
        "btn.retry": "Retry",
        "btn.close": "Close",
        "btn.browse": "Browse",
        "btn.confirm": "Confirm",
        
        # 状态栏
        "status.ready": "Ready",
        "status.loading": "Loading...",
        "status.saving": "Saving...",
        "status.running": "Running...",
        "status.idle": "Idle",
        "status.error": "Error",
        "status.connected": "Connected",
        "status.disconnected": "Disconnected",
        "status.open_workspace": "Please open a workspace folder",
        
        # 面板标题
        "panel.file_browser": "File Browser",
        "panel.code_editor": "Code Editor",
        "panel.chat": "AI Assistant",
        "panel.simulation": "Simulation Results",
        "panel.iteration_history": "Iteration History",
        
        # 对话框
        "dialog.open_workspace.title": "Open Workspace",
        "dialog.api_config.title": "API Configuration",
        "dialog.about.title": "About",
        "dialog.confirm.title": "Confirm",
        "dialog.error.title": "Error",
        "dialog.warning.title": "Warning",
        "dialog.info.title": "Information",
        
        # 错误消息
        "error.file_not_found": "File not found",
        "error.permission_denied": "Permission denied",
        "error.network_error": "Network error",
        "error.api_error": "API error",
        "error.simulation_failed": "Simulation failed",
        "error.unknown": "An unknown error occurred",
        
        # 提示消息
        "hint.drag_file": "Drag and drop files here",
        "hint.enter_message": "Enter your message...",
        "hint.select_file": "Select a file to view",
        
        # 工作流
        "workflow.iteration": "Iteration",
        "workflow.waiting_confirmation": "Waiting for confirmation",
        "workflow.auto_continue": "Auto continue",
        "workflow.stopped": "Stopped",
        "workflow.completed": "Completed",
    },

    LANG_ZH_CN: {
        # 应用标题
        "app.title": "电路AI设计助理",
        "app.version": "版本",
        
        # 菜单 - 文件
        "menu.file": "文件",
        "menu.file.open": "打开工作文件夹",
        "menu.file.close": "关闭工作文件夹",
        "menu.file.save": "保存",
        "menu.file.save_all": "全部保存",
        "menu.file.exit": "退出",
        
        # 菜单 - 编辑
        "menu.edit": "编辑",
        "menu.edit.undo": "撤销",
        "menu.edit.redo": "重做",
        "menu.edit.cut": "剪切",
        "menu.edit.copy": "复制",
        "menu.edit.paste": "粘贴",
        
        # 菜单 - 视图
        "menu.view": "视图",
        "menu.view.file_browser": "文件浏览器",
        "menu.view.code_editor": "代码编辑器",
        "menu.view.chat_panel": "对话面板",
        "menu.view.simulation": "仿真结果",
        
        # 菜单 - 仿真
        "menu.simulation": "仿真",
        "menu.simulation.run": "运行仿真",
        "menu.simulation.stop": "停止仿真",
        
        # 菜单 - 知识库
        "menu.knowledge": "知识库",
        "menu.knowledge.import": "导入文档",
        "menu.knowledge.rebuild": "重建索引",
        
        # 菜单 - 工具
        "menu.tools": "工具",
        "menu.tools.api_config": "API 配置",
        "menu.tools.compress_context": "压缩上下文",
        
        # 菜单 - 设置
        "menu.settings": "设置",
        "menu.settings.api_config": "API 配置",
        "menu.settings.language": "语言",
        "menu.settings.preferences": "偏好设置",
        
        # 菜单 - 帮助
        "menu.help": "帮助",
        "menu.help.about": "关于",
        "menu.help.documentation": "文档",
        
        # 按钮
        "btn.save": "保存",
        "btn.cancel": "取消",
        "btn.ok": "确定",
        "btn.apply": "应用",
        "btn.send": "发送",
        "btn.stop": "停止",
        "btn.continue": "继续",
        "btn.retry": "重试",
        "btn.close": "关闭",
        "btn.browse": "浏览",
        "btn.confirm": "确认",
        
        # 状态栏
        "status.ready": "就绪",
        "status.loading": "加载中...",
        "status.saving": "保存中...",
        "status.running": "运行中...",
        "status.idle": "空闲",
        "status.error": "错误",
        "status.connected": "已连接",
        "status.disconnected": "已断开",
        "status.open_workspace": "请先打开工作文件夹",
        
        # 面板标题
        "panel.file_browser": "文件浏览器",
        "panel.code_editor": "代码编辑器",
        "panel.chat": "AI 助手",
        "panel.simulation": "仿真结果",
        "panel.iteration_history": "迭代历史",
        
        # 对话框
        "dialog.open_workspace.title": "打开工作文件夹",
        "dialog.api_config.title": "API 配置",
        "dialog.about.title": "关于",
        "dialog.confirm.title": "确认",
        "dialog.error.title": "错误",
        "dialog.warning.title": "警告",
        "dialog.info.title": "提示",
        
        # 错误消息
        "error.file_not_found": "文件未找到",
        "error.permission_denied": "权限被拒绝",
        "error.network_error": "网络错误",
        "error.api_error": "API 错误",
        "error.simulation_failed": "仿真失败",
        "error.unknown": "发生未知错误",
        
        # 提示消息
        "hint.drag_file": "拖放文件到此处",
        "hint.enter_message": "输入您的消息...",
        "hint.select_file": "选择文件以查看",
        
        # 工作流
        "workflow.iteration": "迭代",
        "workflow.waiting_confirmation": "等待确认",
        "workflow.auto_continue": "自动继续",
        "workflow.stopped": "已停止",
        "workflow.completed": "已完成",
    },
}


# ============================================================
# 国际化管理器
# ============================================================

class I18nManager:
    """
    国际化管理器
    
    统一管理多语言文本和语言切换。
    
    设计原则：
    - 延迟获取 ConfigManager 和 EventBus
    - 语言切换通过 EventBus 通知 UI 组件
    - 文本键不存在时返回键名本身，便于调试
    """

    def __init__(self):
        # 当前语言
        self._current_language = LANG_EN_US
        
        # 延迟获取的服务
        self._config_manager = None
        self._event_bus = None
        self._logger = None
        
        # 尝试从配置加载语言设置
        self._load_language_from_config()

    # ============================================================
    # 延迟获取服务
    # ============================================================

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
                self._logger = get_logger("i18n_manager")
            except Exception:
                pass
        return self._logger

    # ============================================================
    # 配置加载
    # ============================================================

    def _load_language_from_config(self):
        """从配置加载语言设置"""
        if self.config_manager is None:
            return
        
        try:
            lang = self.config_manager.get("language")
            if lang and lang in SUPPORTED_LANGUAGES:
                self._current_language = lang
                if self.logger:
                    self.logger.info(f"Loaded language from config: {lang}")
        except Exception as e:
            if self.logger:
                self.logger.warning(f"Failed to load language from config: {e}")

    # ============================================================
    # 核心功能
    # ============================================================

    def get_text(self, key: str, default: Optional[str] = None) -> str:
        """
        根据键名获取当前语言的文本
        
        Args:
            key: 文本键（如 "app.title"、"btn.save"）
            default: 默认值（键不存在时返回）
            
        Returns:
            str: 对应语言的文本，键不存在时返回 default 或键名本身
        """
        texts = TEXTS.get(self._current_language, {})
        text = texts.get(key)
        
        if text is not None:
            return text
        
        # 回退到英文
        if self._current_language != LANG_EN_US:
            en_texts = TEXTS.get(LANG_EN_US, {})
            text = en_texts.get(key)
            if text is not None:
                return text
        
        # 返回默认值或键名
        if default is not None:
            return default
        
        # 返回键名便于调试
        if self.logger:
            self.logger.debug(f"Missing translation for key: {key}")
        return key

    def set_language(self, lang_code: str) -> bool:
        """
        切换语言
        
        切换后会：
        1. 更新当前语言
        2. 保存到配置文件
        3. 通过 EventBus 发布 EVENT_LANGUAGE_CHANGED 事件
        
        Args:
            lang_code: 语言代码（如 "en_US"、"zh_CN"）
            
        Returns:
            bool: 是否切换成功
        """
        if lang_code not in SUPPORTED_LANGUAGES:
            if self.logger:
                self.logger.warning(f"Unsupported language: {lang_code}")
            return False
        
        if lang_code == self._current_language:
            return True
        
        old_language = self._current_language
        self._current_language = lang_code
        
        if self.logger:
            self.logger.info(f"Language changed: {old_language} -> {lang_code}")
        
        # 保存到配置
        self._save_language_to_config(lang_code)
        
        # 发布语言变更事件
        self._publish_language_changed(old_language, lang_code)
        
        return True

    def _save_language_to_config(self, lang_code: str):
        """保存语言设置到配置"""
        if self.config_manager is None:
            return
        
        try:
            self.config_manager.set("language", lang_code)
        except Exception as e:
            if self.logger:
                self.logger.warning(f"Failed to save language to config: {e}")

    def _publish_language_changed(self, old_language: str, new_language: str):
        """发布语言变更事件"""
        if self.event_bus is None:
            return
        
        try:
            self.event_bus.publish(
                EVENT_LANGUAGE_CHANGED,
                {
                    "old_language": old_language,
                    "new_language": new_language,
                },
                source="i18n_manager"
            )
        except Exception as e:
            if self.logger:
                self.logger.warning(f"Failed to publish language changed event: {e}")


    def get_current_language(self) -> str:
        """
        获取当前语言代码
        
        Returns:
            str: 当前语言代码（如 "en_US"）
        """
        return self._current_language

    def get_available_languages(self) -> List[str]:
        """
        返回支持的语言列表
        
        Returns:
            list: 语言代码列表
        """
        return SUPPORTED_LANGUAGES.copy()

    def get_language_name(self, lang_code: str) -> str:
        """
        获取语言的显示名称
        
        Args:
            lang_code: 语言代码
            
        Returns:
            str: 语言显示名称（如 "English"、"简体中文"）
        """
        return LANGUAGE_NAMES.get(lang_code, lang_code)

    def get_all_language_names(self) -> Dict[str, str]:
        """
        获取所有语言的显示名称
        
        Returns:
            dict: {lang_code: display_name}
        """
        return LANGUAGE_NAMES.copy()

    # ============================================================
    # 便捷方法
    # ============================================================

    def t(self, key: str, default: Optional[str] = None) -> str:
        """
        get_text 的简写
        
        Args:
            key: 文本键
            default: 默认值
            
        Returns:
            str: 翻译后的文本
        """
        return self.get_text(key, default)

    def is_chinese(self) -> bool:
        """当前是否为中文"""
        return self._current_language == LANG_ZH_CN

    def is_english(self) -> bool:
        """当前是否为英文"""
        return self._current_language == LANG_EN_US


# ============================================================
# 模块导出
# ============================================================

__all__ = [
    "I18nManager",
    # 语言常量
    "LANG_EN_US",
    "LANG_ZH_CN",
    "SUPPORTED_LANGUAGES",
    "LANGUAGE_NAMES",
    # 文本字典
    "TEXTS",
]
