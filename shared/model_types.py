"""Embedding model data contracts.

Chat-provider and chat-model metadata live in the immutable provider catalog.
This module intentionally contains only the still-active embedding contracts.
"""

from dataclasses import dataclass

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


__all__ = [
    "EmbeddingModelConfig",
    "EmbeddingProviderConfig",
]
