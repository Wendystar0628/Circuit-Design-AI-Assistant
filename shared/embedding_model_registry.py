# Embedding Model Registry
"""
嵌入模型注册表

职责：
- 作为嵌入模型配置的单一信息源（Single Source of Truth）
- 管理嵌入模型和厂商的注册、查询
- 与 LLM 的 ModelRegistry 分离管理

初始化顺序：Phase 1.5，与 ModelRegistry 同时初始化

使用示例：
    from shared.embedding_model_registry import EmbeddingModelRegistry
    
    # 获取当前嵌入模型配置
    config = EmbeddingModelRegistry.get_current_model()
    
    # 查询模型列表
    models = EmbeddingModelRegistry.list_models("local")
"""

import logging
from typing import Dict, List, Optional

from shared.model_types import EmbeddingModelConfig, EmbeddingProviderConfig


# ============================================================
# 内置嵌入模型配置
# ============================================================

# 本地嵌入模型
LOCAL_EMBEDDING_MODELS = [
    EmbeddingModelConfig(
        id="local:gte-modernbert-base",
        provider="local",
        name="gte-modernbert-base",
        display_name="GTE ModernBERT Base",
        dimensions=768,
        max_tokens=8192,
        is_local=True,
        description="英文嵌入模型，基于 ModernBERT 架构，支持 8192 长上下文",
    ),
    EmbeddingModelConfig(
        id="local:bge-small-en-v1.5",
        provider="local",
        name="bge-small-en-v1.5",
        display_name="BGE Small EN v1.5",
        dimensions=384,
        max_tokens=512,
        is_local=True,
        description="轻量级英文嵌入模型，适合资源受限环境",
    ),
]

# 智谱嵌入模型
ZHIPU_EMBEDDING_MODELS = [
    EmbeddingModelConfig(
        id="zhipu:embedding-3",
        provider="zhipu",
        name="embedding-3",
        display_name="Embedding-3",
        dimensions=2048,
        max_tokens=8192,
        is_local=False,
        description="智谱最新嵌入模型，2048 维向量",
    ),
    EmbeddingModelConfig(
        id="zhipu:embedding-2",
        provider="zhipu",
        name="embedding-2",
        display_name="Embedding-2",
        dimensions=1024,
        max_tokens=512,
        is_local=False,
        description="智谱旧版嵌入模型，1024 维向量",
    ),
]

# 厂商配置
LOCAL_EMBEDDING_PROVIDER = EmbeddingProviderConfig(
    id="local",
    display_name="本地模型",
    base_url="",
    default_model="gte-modernbert-base",
    requires_api_key=False,
    is_local=True,
    implemented=True,
)

ZHIPU_EMBEDDING_PROVIDER = EmbeddingProviderConfig(
    id="zhipu",
    display_name="智谱 AI",
    base_url="https://open.bigmodel.cn/api/paas/v4/embeddings",
    default_model="embedding-3",
    requires_api_key=True,
    is_local=False,
    implemented=True,
)

OPENAI_EMBEDDING_PROVIDER = EmbeddingProviderConfig(
    id="openai",
    display_name="OpenAI",
    base_url="https://api.openai.com/v1/embeddings",
    default_model="text-embedding-3-small",
    requires_api_key=True,
    is_local=False,
    implemented=False,  # 占位，未实现
)


# ============================================================
# 嵌入模型注册表
# ============================================================

class EmbeddingModelRegistry:
    """
    嵌入模型注册表（全局单例）
    
    管理所有已注册的嵌入模型和厂商配置，提供统一的查询接口。
    """
    
    # 类级别存储（单例模式）
    _models: Dict[str, EmbeddingModelConfig] = {}
    _providers: Dict[str, EmbeddingProviderConfig] = {}
    _initialized: bool = False
    _logger: Optional[logging.Logger] = None
    
    # ============================================================
    # 初始化
    # ============================================================
    
    @classmethod
    def initialize(cls) -> None:
        """
        初始化嵌入模型注册表
        
        加载所有内置嵌入模型配置。应在应用启动时调用一次。
        """
        if cls._initialized:
            return
        
        cls._logger = logging.getLogger(__name__)
        
        # 注册内置厂商
        cls.register_provider(LOCAL_EMBEDDING_PROVIDER)
        cls.register_provider(ZHIPU_EMBEDDING_PROVIDER)
        cls.register_provider(OPENAI_EMBEDDING_PROVIDER)
        
        # 注册内置模型
        for model in LOCAL_EMBEDDING_MODELS:
            cls.register_model(model)
        
        for model in ZHIPU_EMBEDDING_MODELS:
            cls.register_model(model)
        
        cls._initialized = True
        cls._logger.info(
            f"EmbeddingModelRegistry initialized: {len(cls._providers)} providers, "
            f"{len(cls._models)} models"
        )
    
    # ============================================================
    # 厂商管理
    # ============================================================
    
    @classmethod
    def register_provider(cls, provider: EmbeddingProviderConfig) -> None:
        """
        注册嵌入模型厂商配置
        
        Args:
            provider: 厂商配置
        """
        cls._providers[provider.id] = provider
        if cls._logger:
            cls._logger.debug(f"Registered embedding provider: {provider.id}")
    
    @classmethod
    def get_provider(cls, provider_id: str) -> Optional[EmbeddingProviderConfig]:
        """
        获取厂商配置
        
        Args:
            provider_id: 厂商 ID
            
        Returns:
            厂商配置，不存在则返回 None
        """
        return cls._providers.get(provider_id)
    
    @classmethod
    def list_providers(cls) -> List[EmbeddingProviderConfig]:
        """
        获取所有已注册的厂商
        
        Returns:
            厂商配置列表
        """
        return list(cls._providers.values())
    
    @classmethod
    def list_implemented_providers(cls) -> List[EmbeddingProviderConfig]:
        """
        获取所有已实现的厂商
        
        Returns:
            已实现的厂商配置列表
        """
        return [p for p in cls._providers.values() if p.implemented]
    
    # ============================================================
    # 模型管理
    # ============================================================
    
    @classmethod
    def register_model(cls, model: EmbeddingModelConfig) -> None:
        """
        注册嵌入模型配置
        
        Args:
            model: 模型配置
        """
        cls._models[model.id] = model
        if cls._logger:
            cls._logger.debug(f"Registered embedding model: {model.id}")
    
    @classmethod
    def get_model(cls, model_id: str) -> Optional[EmbeddingModelConfig]:
        """
        获取嵌入模型配置
        
        Args:
            model_id: 模型 ID（格式: "provider:model_name"）
            
        Returns:
            模型配置，不存在则返回 None
        """
        return cls._models.get(model_id)
    
    @classmethod
    def get_model_by_name(
        cls, provider_id: str, model_name: str
    ) -> Optional[EmbeddingModelConfig]:
        """
        通过厂商 ID 和模型名称获取模型配置
        
        Args:
            provider_id: 厂商 ID
            model_name: 模型名称
            
        Returns:
            模型配置，不存在则返回 None
        """
        model_id = f"{provider_id}:{model_name}"
        return cls.get_model(model_id)
    
    @classmethod
    def list_models(cls, provider_id: Optional[str] = None) -> List[EmbeddingModelConfig]:
        """
        获取模型列表
        
        Args:
            provider_id: 厂商 ID（可选，不指定则返回所有模型）
            
        Returns:
            模型配置列表
        """
        if provider_id:
            return [m for m in cls._models.values() if m.provider == provider_id]
        return list(cls._models.values())
    
    @classmethod
    def list_model_names(cls, provider_id: str) -> List[str]:
        """
        获取指定厂商的模型名称列表
        
        Args:
            provider_id: 厂商 ID
            
        Returns:
            模型名称列表
        """
        return [m.name for m in cls._models.values() if m.provider == provider_id]
    
    # ============================================================
    # 当前模型查询
    # ============================================================
    
    @classmethod
    def get_current_model(cls) -> Optional[EmbeddingModelConfig]:
        """
        获取当前配置的嵌入模型
        
        从 ConfigManager 读取当前配置的嵌入模型厂商和模型名称，
        返回对应的模型配置。
        
        Returns:
            当前嵌入模型配置，未配置则返回默认本地模型
        """
        try:
            from shared.service_locator import ServiceLocator
            from shared.service_names import SVC_CONFIG_MANAGER
            
            config_manager = ServiceLocator.get_optional(SVC_CONFIG_MANAGER)
            if not config_manager:
                # ConfigManager 未初始化，返回默认本地模型
                return cls.get_model("local:gte-modernbert-base")
            
            provider_id = config_manager.get("embedding_provider", "local")
            model_name = config_manager.get("embedding_model", "")
            
            # 如果未指定模型名称，使用厂商默认模型
            if not model_name:
                provider = cls.get_provider(provider_id)
                if provider:
                    model_name = provider.default_model
            
            if model_name:
                model = cls.get_model_by_name(provider_id, model_name)
                if model:
                    return model
            
            # 回退到默认本地模型
            return cls.get_model("local:gte-modernbert-base")
            
        except Exception:
            # 出错时返回默认本地模型
            return cls.get_model("local:gte-modernbert-base")
    
    # ============================================================
    # 工具方法
    # ============================================================
    
    @classmethod
    def clear(cls) -> None:
        """
        清空所有注册（仅用于测试）
        """
        cls._models.clear()
        cls._providers.clear()
        cls._initialized = False


# ============================================================
# 模块导出
# ============================================================

__all__ = [
    "EmbeddingModelRegistry",
    "LOCAL_EMBEDDING_MODELS",
    "ZHIPU_EMBEDDING_MODELS",
    "LOCAL_EMBEDDING_PROVIDER",
    "ZHIPU_EMBEDDING_PROVIDER",
    "OPENAI_EMBEDDING_PROVIDER",
]
