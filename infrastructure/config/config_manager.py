"""
配置统一访问管理器

职责：提供非敏感配置的统一访问接口，管理配置的读写、校验和变更通知

初始化顺序：Phase 1.1，依赖 Logger，注册到 ServiceLocator

使用方式：
    config_manager = ConfigManager()
    config_manager.load_config()
    
    # 读取配置
    timeout = config_manager.get("llm_timeout", 60)
    
    # 写入配置（自动触发变更通知）
    config_manager.set("llm_timeout", 120)
"""

import json
from typing import Any, Callable, Dict, List, Optional
from threading import Lock

from .settings import (
    GLOBAL_CONFIG_DIR,
    GLOBAL_CONFIG_FILE,
    DEFAULT_CONFIG,
    CONFIG_LANGUAGE,
    CONFIG_LLM_PROVIDER,
    CONFIG_LLM_MODEL,
    CONFIG_LLM_TIMEOUT,
    CONFIG_LLM_STREAMING,
    CONFIG_EMBEDDING_PROVIDER,
    SUPPORTED_LANGUAGES,
    SUPPORTED_LLM_PROVIDERS,
    SUPPORTED_EMBEDDING_PROVIDERS,
)


_REMOVED_CONFIG_KEYS = {
    "general_web_search_provider",
}


class ConfigManager:
    """
    配置统一访问管理器
    
    提供配置的统一读写接口，禁止其他模块直接解析 config.json
    """
    
    def __init__(self):
        """
        初始化配置管理器
        
        注意：遵循延迟获取原则，不在 __init__ 中获取 ServiceLocator 服务
        """
        self._config: Dict[str, Any] = {}
        self._config_file = GLOBAL_CONFIG_FILE
        self._lock = Lock()
        self._change_handlers: Dict[str, List[Callable]] = {}
        self._loaded = False
        
        # 延迟获取的服务引用
        self._event_bus = None

    # ============================================================
    # 延迟获取服务（遵循开发前必读原则）
    # ============================================================
    
    @property
    def event_bus(self):
        """延迟获取 EventBus 服务"""
        if self._event_bus is None:
            try:
                from shared.service_locator import ServiceLocator
                from shared.service_names import SVC_EVENT_BUS
                self._event_bus = ServiceLocator.get_optional(SVC_EVENT_BUS)
            except Exception:
                self._event_bus = None
        return self._event_bus

    # ============================================================
    # 核心功能
    # ============================================================
    
    def load_config(self) -> bool:
        """
        加载配置文件
        
        缺失字段使用 settings.py 默认值
        
        Returns:
            bool: 加载是否成功
        """
        with self._lock:
            try:
                # 确保配置目录存在
                GLOBAL_CONFIG_DIR.mkdir(parents=True, exist_ok=True)
                
                if self._config_file.exists():
                    with open(self._config_file, "r", encoding="utf-8") as f:
                        loaded_config = json.load(f)

                    removed_keys = [key for key in _REMOVED_CONFIG_KEYS if key in loaded_config]
                    for key in removed_keys:
                        loaded_config.pop(key, None)
                    
                    # 合并默认配置（缺失字段使用默认值）
                    self._config = {**DEFAULT_CONFIG, **loaded_config}
                    if removed_keys:
                        self._save_config_internal()
                else:
                    # 配置文件不存在，使用默认配置
                    self._config = DEFAULT_CONFIG.copy()
                    self._save_config_internal()
                
                self._loaded = True
                self._log_info("配置加载成功")
                return True
                
            except json.JSONDecodeError as e:
                self._log_error(f"配置文件 JSON 解析失败: {e}")
                self._config = DEFAULT_CONFIG.copy()
                self._loaded = True
                return False
                
            except Exception as e:
                self._log_error(f"配置加载失败: {e}")
                self._config = DEFAULT_CONFIG.copy()
                self._loaded = True
                return False
    
    def save_config(self) -> bool:
        """
        保存配置到文件
        
        Returns:
            bool: 保存是否成功
        """
        with self._lock:
            return self._save_config_internal()
    
    def _save_config_internal(self) -> bool:
        """内部保存方法（不加锁）"""
        try:
            GLOBAL_CONFIG_DIR.mkdir(parents=True, exist_ok=True)
            
            with open(self._config_file, "w", encoding="utf-8") as f:
                json.dump(self._config, f, indent=2, ensure_ascii=False)
            
            self._log_info("配置保存成功")
            return True
            
        except Exception as e:
            self._log_error(f"配置保存失败: {e}")
            return False
    
    def get(self, key: str, default: Any = None) -> Any:
        """
        统一配置读取接口
        
        Args:
            key: 配置键名
            default: 默认值（如果配置中没有该键）
            
        Returns:
            配置值
        """
        with self._lock:
            return self._config.get(key, default)
    
    def set(self, key: str, value: Any, save: bool = True) -> None:
        """
        统一配置写入接口
        
        自动触发变更通知
        
        Args:
            key: 配置键名
            value: 配置值
            save: 是否立即保存到文件
        """
        with self._lock:
            old_value = self._config.get(key)
            self._config[key] = value
            
            if save:
                self._save_config_internal()
        
        # 触发变更通知（锁外执行，避免死锁）
        if old_value != value:
            self._notify_change(key, old_value, value)
    
    def get_all(self) -> Dict[str, Any]:
        """
        获取所有配置
        
        Returns:
            配置字典副本
        """
        with self._lock:
            return self._config.copy()
    
    def get_all_keys(self) -> List[str]:
        """
        获取所有配置键列表
        
        Returns:
            键名列表
        """
        with self._lock:
            return list(self._config.keys())
    
    # ============================================================
    # 配置校验
    # ============================================================
    
    def validate_config(self) -> tuple[bool, List[str]]:
        """
        校验配置有效性
        
        Returns:
            (是否有效, 错误信息列表)
        """
        errors = []
        
        with self._lock:
            # 校验 LLM 超时值
            llm_timeout = self._config.get(CONFIG_LLM_TIMEOUT, 0)
            if llm_timeout and (not isinstance(llm_timeout, (int, float)) or llm_timeout <= 0):
                errors.append(f"LLM 超时值必须大于 0，当前值: {llm_timeout}")
            
            # 校验 LLM 流式输出开关
            llm_streaming = self._config.get(CONFIG_LLM_STREAMING)
            if llm_streaming is not None and not isinstance(llm_streaming, bool):
                errors.append(f"llm_streaming 必须为布尔值，当前值: {llm_streaming}")
            
            # 校验语言设置
            language = self._config.get(CONFIG_LANGUAGE, "")
            if language and language not in SUPPORTED_LANGUAGES:
                errors.append(f"不支持的语言: {language}，支持: {SUPPORTED_LANGUAGES}")
            
            # 校验 LLM 厂商标识
            llm_provider = self._config.get(CONFIG_LLM_PROVIDER, "")
            if llm_provider and llm_provider not in SUPPORTED_LLM_PROVIDERS:
                errors.append(f"不支持的 LLM 厂商: {llm_provider}，支持: {SUPPORTED_LLM_PROVIDERS}")
            
            # 校验嵌入模型厂商标识
            embedding_provider = self._config.get(CONFIG_EMBEDDING_PROVIDER, "")
            if embedding_provider and embedding_provider not in SUPPORTED_EMBEDDING_PROVIDERS:
                errors.append(f"不支持的嵌入模型厂商: {embedding_provider}，支持: {SUPPORTED_EMBEDDING_PROVIDERS}")
        
        return len(errors) == 0, errors
    
    # ============================================================
    # 变更通知机制
    # ============================================================
    
    def subscribe_change(self, key: str, handler: Callable[[str, Any, Any], None]) -> None:
        """
        订阅特定配置项变更
        
        Args:
            key: 配置键名
            handler: 回调函数，签名为 handler(key, old_value, new_value)
        """
        with self._lock:
            if key not in self._change_handlers:
                self._change_handlers[key] = []
            self._change_handlers[key].append(handler)
    
    def unsubscribe_change(self, key: str, handler: Callable) -> None:
        """
        取消订阅配置项变更
        
        Args:
            key: 配置键名
            handler: 要移除的回调函数
        """
        with self._lock:
            if key in self._change_handlers:
                try:
                    self._change_handlers[key].remove(handler)
                except ValueError:
                    pass
    
    def _notify_change(self, key: str, old_value: Any, new_value: Any) -> None:
        """
        通知配置变更
        
        Args:
            key: 变更的配置键
            old_value: 旧值
            new_value: 新值
        """
        # 调用特定键的订阅者
        handlers = self._change_handlers.get(key, [])
        for handler in handlers:
            try:
                handler(key, old_value, new_value)
            except Exception as e:
                self._log_error(f"配置变更回调执行失败: {e}")
        
        # 通过 EventBus 发布全局事件
        if self.event_bus:
            try:
                from shared.event_types import EVENT_STATE_CONFIG_CHANGED
                self.event_bus.publish(EVENT_STATE_CONFIG_CHANGED, {
                    "key": key,
                    "old_value": old_value,
                    "new_value": new_value,
                })
            except Exception as e:
                self._log_error(f"发布配置变更事件失败: {e}")
    
    # ============================================================
    # 日志辅助方法
    # ============================================================
    
    def _log_info(self, message: str) -> None:
        """记录信息日志"""
        try:
            from infrastructure.utils.logger import get_logger
            get_logger("config_manager").info(message)
        except Exception:
            print(f"[INFO] ConfigManager: {message}")
    
    def _log_warning(self, message: str) -> None:
        """记录警告日志"""
        try:
            from infrastructure.utils.logger import get_logger
            get_logger("config_manager").warning(message)
        except Exception:
            print(f"[WARNING] ConfigManager: {message}")
    
    def _log_error(self, message: str) -> None:
        """记录错误日志"""
        try:
            from infrastructure.utils.logger import get_logger
            get_logger("config_manager").error(message)
        except Exception:
            print(f"[ERROR] ConfigManager: {message}")
