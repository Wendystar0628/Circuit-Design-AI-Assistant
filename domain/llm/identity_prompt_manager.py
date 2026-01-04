# Identity Prompt Manager
"""
自由工作模式身份提示词管理器

职责：
- 管理自由工作模式的身份提示词加载、保存和重置
- 身份提示词作为高层级固定系统提示，类似 Cursor Rules

设计原则：
- 与 PromptTemplateManager 职责分离，专注身份提示词管理
- 支持用户自定义覆盖内置默认
- 原子写入策略确保数据安全
"""

import json
import logging
import os
import tempfile
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Optional

from PyQt6.QtCore import QObject, pyqtSignal


@dataclass
class IdentityPrompt:
    """身份提示词数据类"""
    name: str
    description: str
    content: str
    is_custom: bool
    created_at: datetime
    updated_at: datetime
    source: str  # "builtin" or "custom"
    
    @classmethod
    def from_dict(cls, data: dict, source: str = "builtin") -> "IdentityPrompt":
        """从字典创建实例"""
        identity = data.get("identity", {})
        metadata = identity.get("metadata", {})
        
        created_at = metadata.get("created_at", "")
        updated_at = metadata.get("updated_at", "")
        
        try:
            created_dt = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
        except (ValueError, AttributeError):
            created_dt = datetime.now()
        
        try:
            updated_dt = datetime.fromisoformat(updated_at.replace("Z", "+00:00"))
        except (ValueError, AttributeError):
            updated_dt = datetime.now()
        
        return cls(
            name=identity.get("name", "身份提示词"),
            description=identity.get("description", ""),
            content=identity.get("content", ""),
            is_custom=metadata.get("is_custom", False),
            created_at=created_dt,
            updated_at=updated_dt,
            source=source,
        )
    
    def to_dict(self) -> dict:
        """转换为字典"""
        return {
            "version": "1.0.0",
            "identity": {
                "name": self.name,
                "description": self.description,
                "content": self.content,
                "metadata": {
                    "created_at": self.created_at.isoformat(),
                    "updated_at": self.updated_at.isoformat(),
                    "is_custom": self.is_custom,
                }
            }
        }


class IdentityPromptManager(QObject):
    """
    身份提示词管理器
    
    Signals:
        prompt_loaded: 提示词加载完成
        prompt_saved: 提示词保存完成
        prompt_reset: 提示词重置完成
    """
    
    prompt_loaded = pyqtSignal()
    prompt_saved = pyqtSignal(bool, str)  # success, message
    prompt_reset = pyqtSignal()
    
    # 内置默认提示词路径
    BUILTIN_PATH = "resources/prompts/identity_prompt.json"
    
    # 用户自定义提示词相对路径
    CUSTOM_RELATIVE_PATH = "prompts/custom/identity_prompt.json"
    
    # 硬编码最小提示词（回退保护）
    FALLBACK_CONTENT = (
        "You are an expert analog circuit design assistant. "
        "Help users design, analyze, and optimize circuits using SPICE simulation."
    )
    
    def __init__(self, parent: Optional[QObject] = None):
        super().__init__(parent)
        self._logger = logging.getLogger(__name__)
        
        # 当前加载的身份提示词
        self._current_prompt: Optional[IdentityPrompt] = None
        
        # 内置默认提示词（缓存）
        self._builtin_prompt: Optional[IdentityPrompt] = None
        
        # 用户配置目录
        self._user_config_dir: Optional[Path] = None
    
    def initialize(self, user_config_dir: Optional[str] = None) -> bool:
        """
        初始化管理器
        
        Args:
            user_config_dir: 用户配置目录，默认为 ~/.circuit_design_ai
            
        Returns:
            是否初始化成功
        """
        try:
            # 设置用户配置目录
            if user_config_dir:
                self._user_config_dir = Path(user_config_dir)
            else:
                self._user_config_dir = Path.home() / ".circuit_design_ai"
            
            # 加载提示词
            self.load()
            return True
        except Exception as e:
            self._logger.error(f"初始化身份提示词管理器失败: {e}")
            return False
    
    def load(self) -> None:
        """加载身份提示词（优先用户自定义，回退内置默认）"""
        # 1. 尝试加载用户自定义
        custom_prompt = self._load_custom_prompt()
        if custom_prompt:
            self._current_prompt = custom_prompt
            self._logger.info("已加载用户自定义身份提示词")
            self.prompt_loaded.emit()
            return
        
        # 2. 尝试加载内置默认
        builtin_prompt = self._load_builtin_prompt()
        if builtin_prompt:
            self._current_prompt = builtin_prompt
            self._builtin_prompt = builtin_prompt
            self._logger.info("已加载内置默认身份提示词")
            self.prompt_loaded.emit()
            return
        
        # 3. 使用硬编码回退
        self._current_prompt = IdentityPrompt(
            name="身份提示词",
            description="回退默认",
            content=self.FALLBACK_CONTENT,
            is_custom=False,
            created_at=datetime.now(),
            updated_at=datetime.now(),
            source="fallback",
        )
        self._logger.warning("使用硬编码回退身份提示词")
        self.prompt_loaded.emit()
    
    def _load_custom_prompt(self) -> Optional[IdentityPrompt]:
        """加载用户自定义提示词"""
        if not self._user_config_dir:
            return None
        
        custom_path = self._user_config_dir / self.CUSTOM_RELATIVE_PATH
        if not custom_path.exists():
            return None
        
        try:
            with open(custom_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            prompt = IdentityPrompt.from_dict(data, source="custom")
            prompt.is_custom = True
            return prompt
        except Exception as e:
            self._logger.warning(f"加载用户自定义提示词失败: {e}")
            return None
    
    def _load_builtin_prompt(self) -> Optional[IdentityPrompt]:
        """加载内置默认提示词"""
        # 尝试从资源目录加载
        try:
            # 获取模块所在目录
            module_dir = Path(__file__).parent.parent.parent
            builtin_path = module_dir / self.BUILTIN_PATH
            
            if not builtin_path.exists():
                self._logger.warning(f"内置提示词文件不存在: {builtin_path}")
                return None
            
            with open(builtin_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            return IdentityPrompt.from_dict(data, source="builtin")
        except Exception as e:
            self._logger.warning(f"加载内置提示词失败: {e}")
            return None
    
    def get_identity_prompt(self) -> str:
        """获取当前身份提示词内容"""
        if self._current_prompt:
            return self._current_prompt.content
        return self.FALLBACK_CONTENT
    
    def get_identity_prompt_full(self) -> Optional[IdentityPrompt]:
        """获取完整身份提示词对象"""
        return self._current_prompt
    
    def save_custom(self, content: str) -> bool:
        """
        保存用户自定义身份提示词
        
        Args:
            content: 提示词内容
            
        Returns:
            是否保存成功
        """
        if not self._user_config_dir:
            self.prompt_saved.emit(False, "用户配置目录未设置")
            return False
        
        try:
            # 确保目录存在
            custom_path = self._user_config_dir / self.CUSTOM_RELATIVE_PATH
            custom_path.parent.mkdir(parents=True, exist_ok=True)
            
            # 创建新的提示词对象
            now = datetime.now()
            new_prompt = IdentityPrompt(
                name="自由工作模式身份提示词",
                description="用户自定义身份提示词",
                content=content,
                is_custom=True,
                created_at=self._current_prompt.created_at if self._current_prompt else now,
                updated_at=now,
                source="custom",
            )
            
            # 原子写入：先写临时文件，再重命名
            temp_fd, temp_path = tempfile.mkstemp(
                suffix=".json",
                dir=str(custom_path.parent)
            )
            try:
                with os.fdopen(temp_fd, "w", encoding="utf-8") as f:
                    json.dump(new_prompt.to_dict(), f, ensure_ascii=False, indent=2)
                
                # 重命名（原子操作）
                os.replace(temp_path, str(custom_path))
            except Exception:
                # 清理临时文件
                if os.path.exists(temp_path):
                    os.unlink(temp_path)
                raise
            
            # 更新当前提示词
            self._current_prompt = new_prompt
            
            self._logger.info("身份提示词已保存")
            self.prompt_saved.emit(True, "保存成功")
            return True
            
        except Exception as e:
            self._logger.error(f"保存身份提示词失败: {e}")
            self.prompt_saved.emit(False, str(e))
            return False
    
    def reset_to_default(self) -> bool:
        """
        重置为内置默认
        
        Returns:
            是否重置成功
        """
        try:
            # 删除用户自定义文件
            if self._user_config_dir:
                custom_path = self._user_config_dir / self.CUSTOM_RELATIVE_PATH
                if custom_path.exists():
                    custom_path.unlink()
                    self._logger.info(f"已删除用户自定义文件: {custom_path}")
            
            # 重新加载（将加载内置默认）
            self.load()
            
            self.prompt_reset.emit()
            return True
            
        except Exception as e:
            self._logger.error(f"重置身份提示词失败: {e}")
            return False
    
    def is_custom(self) -> bool:
        """检查当前是否为用户自定义"""
        if self._current_prompt:
            return self._current_prompt.is_custom
        return False
    
    def get_default_content(self) -> str:
        """获取内置默认内容"""
        if self._builtin_prompt:
            return self._builtin_prompt.content
        
        # 尝试加载
        builtin = self._load_builtin_prompt()
        if builtin:
            self._builtin_prompt = builtin
            return builtin.content
        
        return self.FALLBACK_CONTENT
    
    def get_source(self) -> str:
        """获取当前提示词来源"""
        if self._current_prompt:
            return self._current_prompt.source
        return "fallback"


__all__ = [
    "IdentityPromptManager",
    "IdentityPrompt",
]
