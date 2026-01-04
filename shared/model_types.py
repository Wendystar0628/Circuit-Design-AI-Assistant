# Model Types
"""
模型相关类型定义

职责：
- 定义 LLM 模型配置数据结构
- 定义 LLM 厂商配置数据结构
- 定义嵌入模型配置数据结构
- 定义本地模型信息数据结构
- 提供类型安全的模型信息访问

设计原则：
- 纯数据类定义，不依赖其他业务模块
- 所有模型属性集中定义，作为单一信息源
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, List, Optional


@dataclass
class ModelConfig:
    """
    模型完整配置（单一信息源）
    
    所有模型相关的配置都应该在这里定义，
    避免在多个文件中重复定义模型属性。
    """
    
    # ============================================================
    # 基础信息
    # ============================================================
    
    id: str                           # 模型唯一标识，格式: "provider:model_name"
    provider: str                     # 厂商 ID（如 "zhipu", "deepseek"）
    name: str                         # 模型名称（如 "glm-4.7"）
    display_name: str                 # 显示名称（如 "GLM-4.7"）
    
    # ============================================================
    # 能力标志
    # ============================================================
    
    supports_vision: bool = False     # 是否支持图像输入
    supports_tools: bool = False      # 是否支持工具调用
    supports_thinking: bool = False   # 是否支持深度思考
    supports_web_search: bool = False # 是否支持厂商专属联网搜索
    supports_streaming: bool = True   # 是否支持流式输出
    
    # ============================================================
    # 上下文和 Token 限制
    # ============================================================
    
    context_limit: int = 128000       # 上下文限制（tokens）
    max_tokens_default: int = 4096    # 普通模式默认 max_tokens
    max_tokens_thinking: int = 4096   # 深度思考模式 max_tokens
    
    # ============================================================
    # 深度思考配置
    # ============================================================
    
    thinking_temperature: float = 1.0       # 深度思考模式固定 temperature
    thinking_timeout: int = 300             # 深度思考模式超时秒数
    
    # ============================================================
    # 普通模式配置
    # ============================================================
    
    default_temperature: float = 0.7        # 普通模式默认 temperature
    default_timeout: int = 60               # 普通模式超时秒数
    
    # ============================================================
    # 特殊行为
    # ============================================================
    
    # 当消息包含图片时，自动切换到的视觉模型 ID
    # 例如 "glm-4.7" 设置为 "zhipu:glm-4.6v"
    vision_fallback: Optional[str] = None
    
    # 是否为视觉模型（用于判断是否需要特殊处理）
    is_vision_model: bool = False
    
    # ============================================================
    # 元数据
    # ============================================================
    
    description: str = ""             # 模型描述
    deprecated: bool = False          # 是否已弃用
    
    def __post_init__(self):
        """初始化后处理"""
        # 自动生成 ID（如果未提供）
        if not self.id:
            self.id = f"{self.provider}:{self.name}"


@dataclass
class ProviderConfig:
    """
    厂商配置
    
    定义 LLM 厂商的基础信息和默认配置。
    """
    
    id: str                           # 厂商唯一标识（如 "zhipu"）
    name: str                         # 厂商名称（如 "智谱 AI"）
    display_name: str                 # 显示名称（如 "智谱 AI (Zhipu)"）
    
    # API 配置
    base_url: str                     # API 端点
    auth_header: str = "Authorization"  # 认证头名称
    auth_prefix: str = "Bearer"       # 认证前缀
    
    # 默认模型
    default_model: str = ""           # 默认模型名称
    
    # 厂商级别能力（所有模型共享）
    supports_web_search: bool = False # 是否支持厂商专属联网搜索
    
    # 实现状态
    implemented: bool = False         # 是否已实现
    
    # 元数据
    description: str = ""             # 厂商描述
    website: str = ""                 # 官网链接
    docs_url: str = ""                # 文档链接


# ============================================================
# 本地模型信息
# ============================================================

@dataclass
class LocalModelInfo:
    """
    本地模型信息数据类
    
    用于存储从 Ollama 服务获取的本地模型信息。
    """
    
    name: str                         # 模型名称（如 "qwen2.5:7b"）
    size: int = 0                     # 模型文件大小（字节）
    parameter_size: str = ""          # 参数量估算（如 "7B"）
    modified_at: Optional[datetime] = None  # 最后修改时间
    digest: str = ""                  # 模型摘要/哈希
    
    @property
    def size_gb(self) -> float:
        """获取模型大小（GB）"""
        return self.size / (1024 ** 3) if self.size > 0 else 0.0
    
    @property
    def display_size(self) -> str:
        """获取显示用的大小字符串"""
        if self.size <= 0:
            return "Unknown"
        gb = self.size_gb
        if gb >= 1:
            return f"{gb:.1f} GB"
        mb = self.size / (1024 ** 2)
        return f"{mb:.0f} MB"


# ============================================================
# 嵌入模型配置
# ============================================================

@dataclass
class EmbeddingModelConfig:
    """
    嵌入模型配置数据类
    
    定义嵌入模型的完整配置信息。
    """
    
    id: str                           # 模型唯一标识（格式: "provider:model_name"）
    provider: str                     # 厂商标识（如 "local", "zhipu"）
    name: str                         # 模型名称（如 "gte-modernbert-base"）
    display_name: str                 # 显示名称（如 "GTE ModernBERT Base"）
    
    # 模型参数
    dimensions: int = 768             # 输出向量维度
    max_tokens: int = 8192            # 单次请求最大 token 数
    
    # 模型属性
    is_local: bool = False            # 是否为本地模型
    
    # 元数据
    description: str = ""             # 模型描述
    
    def __post_init__(self):
        """初始化后处理"""
        if not self.id:
            self.id = f"{self.provider}:{self.name}"


@dataclass
class EmbeddingProviderConfig:
    """
    嵌入模型厂商配置数据类
    
    定义嵌入模型厂商的基础信息。
    """
    
    id: str                           # 厂商唯一标识（如 "local", "zhipu"）
    display_name: str                 # 显示名称（如 "本地模型"）
    
    # API 配置
    base_url: str = ""                # API 端点
    
    # 默认模型
    default_model: str = ""           # 默认模型名称
    
    # 厂商属性
    requires_api_key: bool = False    # 是否需要 API Key
    is_local: bool = False            # 是否为本地厂商
    implemented: bool = False         # 是否已实现


# ============================================================
# 模块导出
# ============================================================

__all__ = [
    "ModelConfig",
    "ProviderConfig",
    "LocalModelInfo",
    "EmbeddingModelConfig",
    "EmbeddingProviderConfig",
]
