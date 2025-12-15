# I18n Manager - Internationalization Management
"""
国际化管理器 - 统一管理多语言文本和语言切换

职责：
- 从外部 JSON 文件加载多语言文本
- 提供多语言文本获取接口
- 管理语言切换和 UI 刷新通知
- 与 ConfigManager 集成持久化语言设置

初始化顺序：
- Phase 1.3，依赖 ConfigManager（读取 language 配置）

设计原则：
- 延迟获取 ConfigManager 和 EventBus，避免初始化顺序问题
- 从 resources/i18n/ 目录加载 JSON 文件
- 语言切换通过 EventBus 通知所有 UI 组件

使用示例：
    from shared.i18n_manager import I18nManager
    
    i18n = I18nManager()
    
    # 获取文本
    title = i18n.get_text("app.title")
    
    # 带变量的文本
    error_msg = i18n.get_text("error.file_not_found", path="/some/path")
    
    # 切换语言
    i18n.set_language("zh_CN")
"""

import json
import os
from pathlib import Path
from typing import Any, Dict, List, Optional

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
# 国际化管理器
# ============================================================

class I18nManager:
    """
    国际化管理器
    
    统一管理多语言文本和语言切换，从外部 JSON 文件加载文本。
    
    设计原则：
    - 延迟获取 ConfigManager 和 EventBus
    - 语言切换通过 EventBus 通知 UI 组件
    - 文本键不存在时返回键名本身，便于调试
    - 支持变量占位符 {variable_name}
    """

    def __init__(self):
        # 当前语言
        self._current_language = LANG_EN_US
        
        # 文本缓存：{lang_code: {key: text}}
        self._texts: Dict[str, Dict[str, str]] = {}
        
        # i18n 目录路径
        self._i18n_dir: Optional[Path] = None
        
        # 延迟获取的服务
        self._config_manager = None
        self._event_bus = None
        self._logger = None
        
        # 初始化 i18n 目录路径
        self._init_i18n_dir()
        
        # 尝试从配置加载语言设置
        self._load_language_from_config()
        
        # 加载当前语言的文本
        self._load_language_file(self._current_language)

    # ============================================================
    # 初始化
    # ============================================================

    def _init_i18n_dir(self):
        """初始化 i18n 目录路径"""
        # 获取 resources/i18n 目录的绝对路径
        # 从当前文件位置向上找到 circuit_design_ai 目录
        current_file = Path(__file__).resolve()
        # shared/i18n_manager.py -> circuit_design_ai/shared/i18n_manager.py
        project_root = current_file.parent.parent
        self._i18n_dir = project_root / "resources" / "i18n"

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
    # 文件加载
    # ============================================================

    def _load_language_file(self, lang_code: str) -> bool:
        """
        从 JSON 文件加载指定语言的文本
        
        Args:
            lang_code: 语言代码（如 "en_US"、"zh_CN"）
            
        Returns:
            bool: 是否加载成功
        """
        if lang_code in self._texts:
            # 已加载，跳过
            return True
        
        if self._i18n_dir is None:
            if self.logger:
                self.logger.warning("i18n directory not initialized")
            return False
        
        file_path = self._i18n_dir / f"{lang_code}.json"
        
        if not file_path.exists():
            if self.logger:
                self.logger.warning(f"Language file not found: {file_path}")
            return False
        
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                texts = json.load(f)
            
            if not isinstance(texts, dict):
                if self.logger:
                    self.logger.error(f"Invalid language file format: {file_path}")
                return False
            
            self._texts[lang_code] = texts
            
            if self.logger:
                self.logger.info(f"Loaded language file: {file_path} ({len(texts)} keys)")
            
            return True
            
        except json.JSONDecodeError as e:
            if self.logger:
                self.logger.error(f"Failed to parse language file {file_path}: {e}")
            return False
        except Exception as e:
            if self.logger:
                self.logger.error(f"Failed to load language file {file_path}: {e}")
            return False

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

    def get_text(self, key: str, default: Optional[str] = None, **kwargs: Any) -> str:
        """
        根据键名获取当前语言的文本
        
        Args:
            key: 文本键（如 "app.title"、"btn.save"）
            default: 默认值（键不存在时返回）
            **kwargs: 变量占位符的值（如 path="/some/path"）
            
        Returns:
            str: 对应语言的文本，键不存在时返回 default 或键名本身
            
        示例：
            get_text("app.title")  # -> "Circuit AI Design Assistant"
            get_text("error.file_not_found", path="/test.txt")  # -> "File not found: /test.txt"
        """
        # 确保当前语言已加载
        if self._current_language not in self._texts:
            self._load_language_file(self._current_language)
        
        texts = self._texts.get(self._current_language, {})
        text = texts.get(key)
        
        if text is None:
            # 回退到英文
            if self._current_language != LANG_EN_US:
                if LANG_EN_US not in self._texts:
                    self._load_language_file(LANG_EN_US)
                en_texts = self._texts.get(LANG_EN_US, {})
                text = en_texts.get(key)
        
        if text is None:
            # 返回默认值或键名
            if default is not None:
                return default
            
            # 返回键名便于调试
            if self.logger:
                self.logger.debug(f"Missing translation for key: {key}")
            return key
        
        # 替换变量占位符
        if kwargs:
            try:
                text = text.format(**kwargs)
            except KeyError as e:
                if self.logger:
                    self.logger.warning(f"Missing variable in text '{key}': {e}")
        
        return text

    def set_language(self, lang_code: str) -> bool:
        """
        切换语言
        
        切换后会：
        1. 加载对应的 JSON 文件到内存
        2. 更新当前语言
        3. 保存到配置文件
        4. 通过 EventBus 发布 EVENT_LANGUAGE_CHANGED 事件
        
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
        
        # 加载新语言文件
        if not self._load_language_file(lang_code):
            if self.logger:
                self.logger.error(f"Failed to load language file for: {lang_code}")
            return False
        
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
        扫描 i18n 目录返回支持的语言列表
        
        Returns:
            list: 语言代码列表
        """
        if self._i18n_dir is None or not self._i18n_dir.exists():
            return SUPPORTED_LANGUAGES.copy()
        
        languages = []
        for file_path in self._i18n_dir.glob("*.json"):
            lang_code = file_path.stem
            if lang_code in SUPPORTED_LANGUAGES:
                languages.append(lang_code)
        
        # 确保至少返回默认语言
        if not languages:
            return SUPPORTED_LANGUAGES.copy()
        
        return languages

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

    def reload_texts(self) -> bool:
        """
        重新加载当前语言文件（支持热更新）
        
        Returns:
            bool: 是否重新加载成功
        """
        # 清除缓存
        if self._current_language in self._texts:
            del self._texts[self._current_language]
        
        # 重新加载
        success = self._load_language_file(self._current_language)
        
        if success and self.logger:
            self.logger.info(f"Reloaded language file: {self._current_language}")
        
        return success

    # ============================================================
    # 便捷方法
    # ============================================================

    def t(self, key: str, default: Optional[str] = None, **kwargs: Any) -> str:
        """
        get_text 的简写
        
        Args:
            key: 文本键
            default: 默认值
            **kwargs: 变量占位符的值
            
        Returns:
            str: 翻译后的文本
        """
        return self.get_text(key, default, **kwargs)

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
]
