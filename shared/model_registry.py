# Model Registry
"""
模型注册表

职责：
- 作为模型目录与能力元数据的单一信息源（Single Source of Truth）
- 管理模型和厂商的注册、查询

设计原则：
- 全局单例模式
- 延迟初始化，避免循环依赖

使用示例：
    from shared.model_registry import ModelRegistry
    
    # 获取模型配置
    config = ModelRegistry.get_model("zhipu:glm-5")
    
    # 查询模型能力
    if config.supports_thinking:
        # 启用深度思考
        pass
"""

import logging
from typing import Dict, List, Optional

from shared.model_types import ModelConfig, ProviderConfig


# ============================================================
# 模型注册表
# ============================================================

class ModelRegistry:
    """
    模型注册表（全局单例）
    
    管理所有已注册的模型和厂商配置，提供统一的查询接口。
    """
    
    # 类级别存储（单例模式）
    _models: Dict[str, ModelConfig] = {}
    _providers: Dict[str, ProviderConfig] = {}
    _initialized: bool = False
    _logger: Optional[logging.Logger] = None
    
    # ============================================================
    # 初始化
    # ============================================================
    
    @classmethod
    def initialize(cls) -> None:
        """
        初始化模型注册表
        
        加载所有内置模型配置。应在应用启动时调用一次。
        """
        if cls._initialized:
            return
        
        cls._logger = logging.getLogger(__name__)
        
        # 注册内置模型（延迟导入避免循环依赖）
        cls._register_builtin_models()
        
        cls._initialized = True
        cls._logger.info(
            f"ModelRegistry initialized: {len(cls._providers)} providers, "
            f"{len(cls._models)} models"
        )
    
    @classmethod
    def _register_builtin_models(cls) -> None:
        """注册内置模型配置"""
        # 延迟导入，避免循环依赖
        try:
            from infrastructure.llm_adapters.model_configs import (
                ZHIPU_PROVIDER,
                ZHIPU_MODELS,
                DEEPSEEK_PROVIDER,
                DEEPSEEK_MODELS,
                QWEN_PROVIDER,
                QWEN_MODELS,
            )
            
            # 注册智谱厂商
            cls.register_provider(ZHIPU_PROVIDER)
            cls.register_provider(DEEPSEEK_PROVIDER)
            cls.register_provider(QWEN_PROVIDER)
            
            # 注册智谱模型
            for model in ZHIPU_MODELS:
                cls.register_model(model)
            for model in DEEPSEEK_MODELS:
                cls.register_model(model)
            for model in QWEN_MODELS:
                cls.register_model(model)
                
        except ImportError as e:
            if cls._logger:
                cls._logger.warning(f"Failed to load builtin models: {e}")
    
    # ============================================================
    # 厂商管理
    # ============================================================
    
    @classmethod
    def register_provider(cls, provider: ProviderConfig) -> None:
        """
        注册厂商配置
        
        Args:
            provider: 厂商配置
        """
        cls._providers[provider.id] = provider
        if cls._logger:
            cls._logger.debug(f"Registered provider: {provider.id}")
    
    @classmethod
    def get_provider(cls, provider_id: str) -> Optional[ProviderConfig]:
        """
        获取厂商配置
        
        Args:
            provider_id: 厂商 ID
            
        Returns:
            厂商配置，不存在则返回 None
        """
        return cls._providers.get(provider_id)
    
    @classmethod
    def list_providers(cls) -> List[ProviderConfig]:
        """
        获取所有已注册的厂商
        
        Returns:
            厂商配置列表
        """
        return list(cls._providers.values())
    
    @classmethod
    def list_implemented_providers(cls) -> List[ProviderConfig]:
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
    def register_model(cls, model: ModelConfig) -> None:
        """
        注册模型配置
        
        Args:
            model: 模型配置
        """
        cls._models[model.id] = model
        if cls._logger:
            cls._logger.debug(f"Registered model: {model.id}")
    
    @classmethod
    def get_model(cls, model_id: str) -> Optional[ModelConfig]:
        """
        获取模型配置
        
        Args:
            model_id: 模型 ID（格式: "provider:model_name"）
            
        Returns:
            模型配置，不存在则返回 None
        """
        return cls._models.get(model_id)
    
    @classmethod
    def get_model_by_name(cls, provider_id: str, model_name: str) -> Optional[ModelConfig]:
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
    def list_models(cls, provider_id: Optional[str] = None) -> List[ModelConfig]:
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
    # 视觉模型处理
    # ============================================================
    
    @classmethod
    def get_vision_fallback(cls, model_id: str) -> Optional[str]:
        """
        获取模型的视觉回退模型 ID
        
        当消息包含图片但当前模型不支持视觉时，
        应切换到此模型。
        
        Args:
            model_id: 当前模型 ID
            
        Returns:
            视觉回退模型 ID，不需要回退则返回 None
        """
        model = cls.get_model(model_id)
        if not model:
            return None
        
        # 如果已经是视觉模型，无需回退
        if model.is_vision_model or model.supports_vision:
            return None
        
        return model.vision_fallback
    
    @classmethod
    def resolve_model_for_content(
        cls,
        model_id: str,
        has_images: bool
    ) -> str:
        """
        根据内容类型解析实际使用的模型
        
        如果消息包含图片且当前模型不支持视觉，
        自动切换到视觉回退模型。
        
        Args:
            model_id: 请求的模型 ID
            has_images: 消息是否包含图片
            
        Returns:
            实际使用的模型 ID
        """
        if not has_images:
            return model_id
        
        fallback = cls.get_vision_fallback(model_id)
        if fallback:
            if cls._logger:
                cls._logger.info(
                    f"Auto-switching to vision model: {model_id} -> {fallback}"
                )
            return fallback
        
        return model_id
    
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

__all__ = ["ModelRegistry"]
