# Credential Manager - Sensitive Information Management
"""
凭证管理器 - 敏感信息专用管理

职责：
- 专门负责敏感凭证（API Key 等）的加密存储和读取
- 按厂商隔离存储，避免切换厂商时丢失配置
- 与普通配置分离，便于安全审计

初始化顺序：Phase 1.0，在 ConfigManager 之前初始化

存储结构（~/.circuit_design_ai/credentials.json）：
{
    "llm": {
        "zhipu": {"api_key": "encrypted_value", "updated_at": "..."},
        "deepseek": {"api_key": "encrypted_value", "updated_at": "..."}
    },
    "search": {
        "google": {"api_key": "encrypted_value", "cx": "...", "updated_at": "..."},
        "bing": {"api_key": "encrypted_value", "updated_at": "..."}
    }
}
"""

import json
import base64
import hashlib
import uuid
import os
import stat
from pathlib import Path
from datetime import datetime
from typing import Any, Dict, List, Optional
from threading import Lock

from .settings import (
    GLOBAL_CONFIG_DIR,
    CREDENTIALS_FILE,
    CREDENTIAL_TYPE_LLM,
    CREDENTIAL_TYPE_SEARCH,
    ENCRYPTION_SALT,
)


class CredentialManager:
    """
    凭证管理器
    
    专门负责敏感凭证的加密存储、读取和管理。
    每个厂商的凭证独立存储，切换厂商时不会丢失已保存的凭证。
    """
    
    def __init__(self):
        """
        初始化凭证管理器
        
        注意：遵循延迟获取原则，不在 __init__ 中获取 ServiceLocator 服务
        """
        self._credentials: Dict[str, Dict[str, Dict[str, Any]]] = {}
        self._credentials_file = GLOBAL_CONFIG_DIR / CREDENTIALS_FILE
        self._lock = Lock()
        self._loaded = False
        self._encryption_key: Optional[bytes] = None
    
    # ============================================================
    # 核心功能
    # ============================================================
    
    def load_credentials(self) -> bool:
        """
        加载凭证文件
        
        Returns:
            bool: 加载是否成功
        """
        with self._lock:
            try:
                # 确保配置目录存在
                GLOBAL_CONFIG_DIR.mkdir(parents=True, exist_ok=True)
                
                if self._credentials_file.exists():
                    with open(self._credentials_file, "r", encoding="utf-8") as f:
                        self._credentials = json.load(f)
                else:
                    # 凭证文件不存在，初始化空结构
                    self._credentials = {
                        CREDENTIAL_TYPE_LLM: {},
                        CREDENTIAL_TYPE_SEARCH: {},
                    }
                    self._save_credentials_internal()
                
                self._loaded = True
                self._log_info("凭证加载成功")
                return True
                
            except json.JSONDecodeError as e:
                self._log_error(f"凭证文件 JSON 解析失败: {e}")
                self._credentials = {
                    CREDENTIAL_TYPE_LLM: {},
                    CREDENTIAL_TYPE_SEARCH: {},
                }
                self._loaded = True
                return False
                
            except Exception as e:
                self._log_error(f"凭证加载失败: {e}")
                self._credentials = {
                    CREDENTIAL_TYPE_LLM: {},
                    CREDENTIAL_TYPE_SEARCH: {},
                }
                self._loaded = True
                return False
    
    def _save_credentials_internal(self) -> bool:
        """内部保存方法（不加锁）"""
        try:
            GLOBAL_CONFIG_DIR.mkdir(parents=True, exist_ok=True)
            
            with open(self._credentials_file, "w", encoding="utf-8") as f:
                json.dump(self._credentials, f, indent=2, ensure_ascii=False)
            
            # 设置文件权限为仅当前用户可读写（Unix 系统）
            self._set_file_permissions()
            
            self._log_info("凭证保存成功")
            return True
            
        except Exception as e:
            self._log_error(f"凭证保存失败: {e}")
            return False
    
    def _set_file_permissions(self) -> None:
        """设置凭证文件权限为仅当前用户可读写"""
        try:
            if os.name != "nt":  # Unix 系统
                os.chmod(self._credentials_file, stat.S_IRUSR | stat.S_IWUSR)
        except Exception:
            pass  # 权限设置失败不影响功能

    
    # ============================================================
    # 凭证读写接口
    # ============================================================
    
    def get_credential(
        self, 
        provider_type: str, 
        provider_id: str
    ) -> Optional[Dict[str, Any]]:
        """
        获取指定厂商的解密凭证
        
        Args:
            provider_type: 厂商类型（llm/search）
            provider_id: 厂商标识（zhipu/deepseek/google/bing 等）
            
        Returns:
            解密后的凭证字典，不存在则返回 None
        """
        with self._lock:
            type_credentials = self._credentials.get(provider_type, {})
            provider_credentials = type_credentials.get(provider_id)
            
            if not provider_credentials:
                return None
            
            # 解密 api_key 字段
            result = provider_credentials.copy()
            encrypted_key = result.get("api_key", "")
            if encrypted_key:
                result["api_key"] = self._decrypt(encrypted_key)
            
            return result
    
    def set_credential(
        self, 
        provider_type: str, 
        provider_id: str, 
        credential_data: Dict[str, Any]
    ) -> bool:
        """
        加密存储厂商凭证
        
        Args:
            provider_type: 厂商类型（llm/search）
            provider_id: 厂商标识
            credential_data: 凭证数据（api_key 会被加密，其他字段明文存储）
            
        Returns:
            bool: 保存是否成功
        """
        with self._lock:
            # 确保类型存在
            if provider_type not in self._credentials:
                self._credentials[provider_type] = {}
            
            # 准备存储数据
            store_data = credential_data.copy()
            
            # 加密 api_key 字段
            api_key = store_data.get("api_key", "")
            if api_key:
                store_data["api_key"] = self._encrypt(api_key)
            else:
                store_data["api_key"] = ""
            
            # 添加更新时间
            store_data["updated_at"] = datetime.now().isoformat()
            
            # 存储
            self._credentials[provider_type][provider_id] = store_data
            
            # 保存到文件
            success = self._save_credentials_internal()
            
            if success:
                self._log_info(f"凭证已保存: {provider_type}/{provider_id}")
            
            return success
    
    def delete_credential(self, provider_type: str, provider_id: str) -> bool:
        """
        删除指定厂商凭证
        
        Args:
            provider_type: 厂商类型
            provider_id: 厂商标识
            
        Returns:
            bool: 删除是否成功
        """
        with self._lock:
            type_credentials = self._credentials.get(provider_type, {})
            
            if provider_id in type_credentials:
                del type_credentials[provider_id]
                success = self._save_credentials_internal()
                if success:
                    self._log_info(f"凭证已删除: {provider_type}/{provider_id}")
                return success
            
            return True  # 不存在也算成功
    
    def has_credential(self, provider_type: str, provider_id: str) -> bool:
        """
        检查凭证是否存在
        
        Args:
            provider_type: 厂商类型
            provider_id: 厂商标识
            
        Returns:
            bool: 凭证是否存在且 api_key 非空
        """
        with self._lock:
            type_credentials = self._credentials.get(provider_type, {})
            provider_credentials = type_credentials.get(provider_id, {})
            return bool(provider_credentials.get("api_key"))
    
    def list_providers(self, provider_type: str) -> List[str]:
        """
        列出已配置凭证的厂商
        
        Args:
            provider_type: 厂商类型
            
        Returns:
            已配置凭证的厂商标识列表
        """
        with self._lock:
            type_credentials = self._credentials.get(provider_type, {})
            # 只返回有 api_key 的厂商
            return [
                pid for pid, cred in type_credentials.items()
                if cred.get("api_key")
            ]

    
    # ============================================================
    # 便捷方法（LLM 凭证）
    # ============================================================
    
    def get_llm_api_key(self, provider_id: str) -> str:
        """
        获取 LLM 厂商的 API Key
        
        Args:
            provider_id: 厂商标识（zhipu/deepseek/qwen/openai/anthropic）
            
        Returns:
            解密后的 API Key，不存在则返回空字符串
        """
        credential = self.get_credential(CREDENTIAL_TYPE_LLM, provider_id)
        return credential.get("api_key", "") if credential else ""
    
    def set_llm_api_key(self, provider_id: str, api_key: str) -> bool:
        """
        设置 LLM 厂商的 API Key
        
        Args:
            provider_id: 厂商标识
            api_key: API Key 明文
            
        Returns:
            bool: 保存是否成功
        """
        return self.set_credential(CREDENTIAL_TYPE_LLM, provider_id, {"api_key": api_key})
    
    # ============================================================
    # 便捷方法（搜索凭证）
    # ============================================================
    
    def get_search_credential(self, provider_id: str) -> Optional[Dict[str, Any]]:
        """
        获取搜索厂商的凭证
        
        Args:
            provider_id: 厂商标识（google/bing）
            
        Returns:
            解密后的凭证字典（包含 api_key，Google 还包含 cx）
        """
        return self.get_credential(CREDENTIAL_TYPE_SEARCH, provider_id)
    
    def set_search_credential(
        self, 
        provider_id: str, 
        api_key: str, 
        cx: Optional[str] = None
    ) -> bool:
        """
        设置搜索厂商的凭证
        
        Args:
            provider_id: 厂商标识
            api_key: API Key 明文
            cx: Google 搜索引擎 ID（仅 Google 需要）
            
        Returns:
            bool: 保存是否成功
        """
        credential_data = {"api_key": api_key}
        if cx is not None:
            credential_data["cx"] = cx
        return self.set_credential(CREDENTIAL_TYPE_SEARCH, provider_id, credential_data)
    
    # ============================================================
    # 加密/解密
    # ============================================================
    
    def _get_encryption_key(self) -> bytes:
        """
        获取加密密钥（派生自机器标识）
        
        Returns:
            32 字节的密钥
        """
        if self._encryption_key is not None:
            return self._encryption_key
        
        # 获取机器标识
        machine_id = self._get_machine_id()
        
        # 使用 PBKDF2 派生密钥
        self._encryption_key = hashlib.pbkdf2_hmac(
            "sha256",
            machine_id.encode(),
            ENCRYPTION_SALT,
            100000,
            dklen=32
        )
        return self._encryption_key
    
    def _get_machine_id(self) -> str:
        """
        获取机器唯一标识
        
        Returns:
            机器标识字符串
        """
        try:
            # 尝试获取 MAC 地址 + 用户名作为机器标识
            mac = uuid.getnode()
            username = os.getenv("USERNAME") or os.getenv("USER") or "default"
            return f"circuit_ai_cred_{mac}_{username}"
        except Exception:
            # 回退到固定标识
            return "circuit_ai_credential_default_key"
    
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
            
            key = base64.urlsafe_b64encode(self._get_encryption_key())
            fernet = Fernet(key)
            
            encrypted = fernet.encrypt(plaintext.encode())
            return base64.urlsafe_b64encode(encrypted).decode()
            
        except ImportError:
            self._log_warning("cryptography 未安装，凭证将使用不安全的编码存储")
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
            
            key = base64.urlsafe_b64encode(self._get_encryption_key())
            fernet = Fernet(key)
            
            encrypted = base64.urlsafe_b64decode(ciphertext.encode())
            decrypted = fernet.decrypt(encrypted)
            return decrypted.decode()
            
        except ImportError:
            try:
                return base64.b64decode(ciphertext.encode()).decode()
            except Exception:
                return ""
                
        except Exception:
            try:
                return base64.b64decode(ciphertext.encode()).decode()
            except Exception:
                return ""

    
    # ============================================================
    # 日志辅助方法
    # ============================================================
    
    def _log_info(self, message: str) -> None:
        """记录信息日志"""
        try:
            from infrastructure.utils.logger import get_logger
            get_logger("credential_manager").info(message)
        except Exception:
            print(f"[INFO] CredentialManager: {message}")
    
    def _log_warning(self, message: str) -> None:
        """记录警告日志"""
        try:
            from infrastructure.utils.logger import get_logger
            get_logger("credential_manager").warning(message)
        except Exception:
            print(f"[WARNING] CredentialManager: {message}")
    
    def _log_error(self, message: str) -> None:
        """记录错误日志"""
        try:
            from infrastructure.utils.logger import get_logger
            get_logger("credential_manager").error(message)
        except Exception:
            print(f"[ERROR] CredentialManager: {message}")


# ============================================================
# 模块导出
# ============================================================

__all__ = [
    "CredentialManager",
]
