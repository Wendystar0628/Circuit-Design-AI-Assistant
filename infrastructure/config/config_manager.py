"""
配置统一访问管理器

职责：提供配置的统一访问接口，管理配置的读写、校验、变更通知和敏感信息加密

初始化顺序：Phase 1.1，依赖 Logger，注册到 ServiceLocator

使用方式：
    config_manager = ConfigManager()
    config_manager.load_config()
    
    # 读取配置
    timeout = config_manager.get("timeout", 60)
    
    # 写入配置（自动触发变更通知）
    config_manager.set("timeout", 120)
    
    # 获取解密后的 API 密钥
    api_key = config_manager.get_api_key("openai")
"""

import json
import base64
import hashlib
import uuid
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional
from threading import Lock

from .settings import (
    GLOBAL_CONFIG_DIR,
    GLOBAL_CONFIG_FILE,
    DEFAULT_CONFIG,
    ENCRYPTED_FIELDS,
    ENCRYPTION_SALT,
    CONFIG_API_KEY,
    CONFIG_WEB_SEARCH_API_KEY,
    CONFIG_TIMEOUT,
    CONFIG_STREAMING,
    CONFIG_LANGUAGE,
    SUPPORTED_LANGUAGES,
)


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
        self._fernet = None  # 加密器，延迟初始化
    
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
                    
                    # 合并默认配置（缺失字段使用默认值）
                    self._config = {**DEFAULT_CONFIG, **loaded_config}
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
            # 加密字段返回解密后的值
            if key in ENCRYPTED_FIELDS:
                encrypted_value = self._config.get(key, "")
                # 空值处理：空字符串直接返回默认值，不触发解密逻辑
                if not encrypted_value:
                    return default if default is not None else ""
                return self._decrypt(encrypted_value)
            
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
            
            # 加密字段处理：只有非空值才加密存储，空值直接存储空字符串
            if key in ENCRYPTED_FIELDS:
                if value:
                    self._config[key] = self._encrypt(value)
                else:
                    self._config[key] = ""
            else:
                self._config[key] = value
            
            if save:
                self._save_config_internal()
        
        # 触发变更通知（锁外执行，避免死锁）
        if old_value != value:
            self._notify_change(key, old_value, value)
    
    def get_all(self) -> Dict[str, Any]:
        """
        获取所有配置（敏感字段已解密）
        
        Returns:
            配置字典副本
        """
        with self._lock:
            result = self._config.copy()
            
            # 解密敏感字段（只有非空值才解密）
            for field in ENCRYPTED_FIELDS:
                encrypted_value = result.get(field, "")
                if encrypted_value:
                    result[field] = self._decrypt(encrypted_value)
                else:
                    result[field] = ""
            
            return result
    
    def get_all_keys(self) -> List[str]:
        """
        获取所有配置键列表
        
        Returns:
            键名列表
        """
        with self._lock:
            return list(self._config.keys())
    
    # ============================================================
    # API 密钥专用方法
    # ============================================================
    
    def get_api_key(self, provider: Optional[str] = None) -> str:
        """
        获取解密后的 API 密钥
        
        Args:
            provider: LLM 提供者（可选，用于未来多提供者支持）
            
        Returns:
            解密后的 API 密钥
        """
        return self.get(CONFIG_API_KEY, "")
    
    def set_api_key(self, key: str, provider: Optional[str] = None) -> None:
        """
        加密存储 API 密钥
        
        Args:
            key: API 密钥明文
            provider: LLM 提供者（可选）
        """
        self.set(CONFIG_API_KEY, key)
    
    def get_web_search_api_key(self) -> str:
        """获取解密后的搜索 API 密钥"""
        return self.get(CONFIG_WEB_SEARCH_API_KEY, "")
    
    def set_web_search_api_key(self, key: str) -> None:
        """加密存储搜索 API 密钥"""
        self.set(CONFIG_WEB_SEARCH_API_KEY, key)

    
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
            # 校验超时值
            timeout = self._config.get(CONFIG_TIMEOUT, 0)
            if not isinstance(timeout, (int, float)) or timeout <= 0:
                errors.append(f"超时值必须大于 0，当前值: {timeout}")
            
            # 校验流式输出开关
            streaming = self._config.get(CONFIG_STREAMING)
            if not isinstance(streaming, bool):
                errors.append(f"streaming 必须为布尔值，当前值: {streaming}")
            
            # 校验语言设置
            language = self._config.get(CONFIG_LANGUAGE, "")
            if language and language not in SUPPORTED_LANGUAGES:
                errors.append(f"不支持的语言: {language}，支持: {SUPPORTED_LANGUAGES}")
        
        return len(errors) == 0, errors
    
    def is_llm_configured(self) -> bool:
        """
        检查 LLM 是否已配置
        
        Returns:
            bool: API 密钥和提供者是否都已设置
        """
        with self._lock:
            provider = self._config.get("llm_provider", "")
            api_key = self._config.get(CONFIG_API_KEY, "")
            return bool(provider and api_key)
    
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
    # 加密/解密（使用简化的对称加密）
    # ============================================================
    
    def _get_encryption_key(self) -> bytes:
        """
        获取加密密钥（派生自机器标识）
        
        Returns:
            32 字节的密钥
        """
        # 获取机器标识
        machine_id = self._get_machine_id()
        
        # 使用 PBKDF2 派生密钥
        key = hashlib.pbkdf2_hmac(
            "sha256",
            machine_id.encode(),
            ENCRYPTION_SALT,
            100000,
            dklen=32
        )
        return key
    
    def _get_machine_id(self) -> str:
        """
        获取机器唯一标识
        
        Returns:
            机器标识字符串
        """
        try:
            # 尝试获取 MAC 地址作为机器标识
            mac = uuid.getnode()
            return f"circuit_ai_{mac}"
        except Exception:
            # 回退到固定标识（安全性降低，但保证可用）
            return "circuit_ai_default_key"
    
    def _encrypt(self, plaintext: str) -> str:
        """
        加密字符串
        
        Args:
            plaintext: 明文
            
        Returns:
            Base64 编码的密文
        """
        if not plaintext:
            return ""
        
        try:
            from cryptography.fernet import Fernet
            
            # 从派生密钥创建 Fernet 密钥
            key = base64.urlsafe_b64encode(self._get_encryption_key())
            fernet = Fernet(key)
            
            encrypted = fernet.encrypt(plaintext.encode())
            return base64.urlsafe_b64encode(encrypted).decode()
            
        except ImportError:
            # cryptography 未安装，使用简单的 Base64 编码（不安全，仅用于开发）
            self._log_warning("cryptography 未安装，API 密钥将使用不安全的编码存储")
            return base64.b64encode(plaintext.encode()).decode()
            
        except Exception as e:
            self._log_error(f"加密失败: {e}")
            return base64.b64encode(plaintext.encode()).decode()
    
    def _decrypt(self, ciphertext: str) -> str:
        """
        解密字符串
        
        Args:
            ciphertext: Base64 编码的密文
            
        Returns:
            明文，解密失败时返回空字符串
        """
        if not ciphertext:
            return ""
        
        try:
            from cryptography.fernet import Fernet
            
            # 从派生密钥创建 Fernet 密钥
            key = base64.urlsafe_b64encode(self._get_encryption_key())
            fernet = Fernet(key)
            
            encrypted = base64.urlsafe_b64decode(ciphertext.encode())
            decrypted = fernet.decrypt(encrypted)
            return decrypted.decode()
            
        except ImportError:
            # cryptography 未安装，尝试 Base64 解码
            try:
                return base64.b64decode(ciphertext.encode()).decode()
            except Exception:
                # 无法解码，可能是损坏的数据，返回空字符串
                return ""
                
        except Exception as e:
            # 解密失败，可能是旧格式或损坏的数据
            # 静默处理，不记录错误日志（避免用户困惑）
            # 返回空字符串，让用户重新输入
            try:
                return base64.b64decode(ciphertext.encode()).decode()
            except Exception:
                # 完全无法解密，返回空字符串
                # 用户需要重新输入 API Key
                return ""
    
    # ============================================================
    # 日志辅助方法（避免循环依赖）
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
