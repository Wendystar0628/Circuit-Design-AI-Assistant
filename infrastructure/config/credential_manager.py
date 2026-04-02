# Credential Manager - Sensitive Information Management
"""
凭证管理器 - 敏感信息专用管理

职责：
- 专门负责敏感凭证（API Key 等）的明文存储和读取
- 按厂商隔离存储，避免切换厂商时丢失配置
- 与普通配置分离，便于安全审计

初始化顺序：Phase 1.0，在 ConfigManager 之前初始化

存储结构（~/.circuit_design_ai/credentials.json）：
{
    "llm": {
        "zhipu": {"api_key": "plaintext_value", "updated_at": "..."},
        "deepseek": {"api_key": "plaintext_value", "updated_at": "..."}
    },
    "search": {
        "google": {"api_key": "plaintext_value", "cx": "...", "updated_at": "..."},
        "bing": {"api_key": "plaintext_value", "updated_at": "..."}
    }
}
"""

import json
import os
import stat
from datetime import datetime
from typing import Any, Dict, List, Optional
from threading import RLock

from .settings import (
    GLOBAL_CONFIG_DIR,
    CREDENTIALS_FILE,
    CREDENTIAL_TYPE_LLM,
    CREDENTIAL_TYPE_SEARCH,
)


class CredentialManager:
    """
    凭证管理器
    
    负责敏感凭证的明文存储、读取和管理。
    每个厂商的凭证独立存储，切换厂商时不会丢失已保存的凭证。
    """
    
    def __init__(self):
        """
        初始化凭证管理器
        
        注意：遵循延迟获取原则，不在 __init__ 中获取 ServiceLocator 服务
        """
        self._credentials: Dict[str, Dict[str, Dict[str, Any]]] = {}
        self._credentials_file = GLOBAL_CONFIG_DIR / CREDENTIALS_FILE
        self._lock = RLock()
        self._loaded = False
    
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
                    self._credentials = {
                        CREDENTIAL_TYPE_LLM: dict(self._credentials.get(CREDENTIAL_TYPE_LLM, {})),
                        CREDENTIAL_TYPE_SEARCH: dict(self._credentials.get(CREDENTIAL_TYPE_SEARCH, {})),
                    }
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
        获取指定厂商的凭证
        
        Args:
            provider_type: 厂商类型（llm/search）
            provider_id: 厂商标识（zhipu/deepseek/google/bing 等）
            
        Returns:
            凭证字典，不存在则返回 None
        """
        with self._lock:
            type_credentials = self._credentials.get(provider_type, {})
            provider_credentials = type_credentials.get(provider_id)
            
            if not provider_credentials:
                return None
            
            result = provider_credentials.copy()
            api_key = result.get("api_key", "")
            if isinstance(api_key, str):
                result["api_key"] = api_key.strip()
            
            return result
    
    def set_credential(
        self, 
        provider_type: str, 
        provider_id: str, 
        credential_data: Dict[str, Any]
    ) -> bool:
        """
        存储厂商凭证（明文）
        
        Args:
            provider_type: 厂商类型（llm/search）
            provider_id: 厂商标识
            credential_data: 凭证数据
            
        Returns:
            bool: 保存是否成功
        """
        with self._lock:
            # 确保类型存在
            if provider_type not in self._credentials:
                self._credentials[provider_type] = {}
            
            # 准备存储数据
            store_data = credential_data.copy()
            
            # 规范化 api_key
            api_key = store_data.get("api_key", "")
            if isinstance(api_key, str):
                store_data["api_key"] = api_key.strip()
            
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
    
    def validate_credential(
        self, 
        provider_type: str, 
        provider_id: str
    ) -> tuple[bool, str]:
        """
        校验凭证格式
        
        Args:
            provider_type: 厂商类型
            provider_id: 厂商标识
            
        Returns:
            (是否有效, 错误信息)
        """
        credential = self.get_credential(provider_type, provider_id)
        
        if not credential:
            return False, "凭证不存在"
        
        api_key = credential.get("api_key", "")
        if not api_key:
            return False, "API Key 为空"
        
        # 基本格式校验
        if len(api_key) < 10:
            return False, "API Key 长度过短"
        
        # 特定厂商的额外校验
        if provider_type == CREDENTIAL_TYPE_SEARCH and provider_id == "google":
            cx = credential.get("cx", "")
            if not cx:
                return False, "Google 搜索引擎 ID (cx) 为空"
        
        return True, ""

    
    # ============================================================
    # 便捷方法（LLM 凭证）
    # ============================================================
    
    def get_llm_api_key(self, provider_id: str) -> str:
        """
        获取 LLM 厂商的 API Key
        
        Args:
            provider_id: 厂商标识（zhipu/deepseek/qwen/openai/anthropic）
            
        Returns:
            API Key 明文，不存在则返回空字符串
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
            凭证字典（包含 api_key，Google 还包含 cx），不存在则返回 None
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
