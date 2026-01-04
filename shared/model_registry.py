# Model Registry
"""
模型注册表

职责：
- 作为所有模型配置的单一信息源（Single Source of Truth）
- 管理模型和厂商的注册、查询
- 管理当前选中的模型状态
- 发布模型切换事件

设计原则：
- 全局单例模式
- 延迟初始化，避免循环依赖
- 通过事件通知模型切换

使用示例：
    from shared.model_registry import ModelRegistry
    
    # 获取当前模型配置
    config = ModelRegistry.get_current_model()
    
    # 切换模型
    ModelRegistry.set_current_model("zhipu:glm-4.7")
    
    # 查询模型能力
    if config.supports_thinking:
        # 启用深度思考
        pass
"""

import logging
from typing import Dict, List, Optional, Callable

from shared.model_types import ModelConfig, ProviderConfig, LocalModelInfo


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
    _current_model_id: Optional[str] = None
    _initialized: bool = False
    _logger: Optional[logging.Logger] = None
    
    # 本地模型缓存
    _local_models: List[LocalModelInfo] = []
    _local_models_loaded: bool = False
    
    # 模型切换回调（用于不依赖 EventBus 的场景）
    _on_model_changed_callbacks: List[Callable[[str, Optional[str]], None]] = []
    
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
            )
            
            # 注册智谱厂商
            cls.register_provider(ZHIPU_PROVIDER)
            
            # 注册智谱模型
            for model in ZHIPU_MODELS:
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
    # 当前模型管理
    # ============================================================
    
    @classmethod
    def get_current_model(cls) -> Optional[ModelConfig]:
        """
        获取当前选中的模型配置
        
        Returns:
            当前模型配置，未设置则返回 None
        """
        if cls._current_model_id:
            return cls.get_model(cls._current_model_id)
        return None
    
    @classmethod
    def get_current_model_id(cls) -> Optional[str]:
        """
        获取当前选中的模型 ID
        
        Returns:
            当前模型 ID，未设置则返回 None
        """
        return cls._current_model_id
    
    @classmethod
    def set_current_model(cls, model_id: str, publish_event: bool = True) -> bool:
        """
        设置当前模型
        
        Args:
            model_id: 模型 ID（格式: "provider:model_name"）
            publish_event: 是否发布模型切换事件
            
        Returns:
            是否设置成功
        """
        # 验证模型存在
        model = cls.get_model(model_id)
        if not model:
            if cls._logger:
                cls._logger.warning(f"Model not found: {model_id}")
            return False
        
        old_model_id = cls._current_model_id
        cls._current_model_id = model_id
        
        if cls._logger:
            cls._logger.info(f"Current model changed: {old_model_id} -> {model_id}")
        
        # 触发回调
        for callback in cls._on_model_changed_callbacks:
            try:
                callback(model_id, old_model_id)
            except Exception as e:
                if cls._logger:
                    cls._logger.error(f"Model change callback error: {e}")
        
        # 发布事件
        if publish_event:
            cls._publish_model_changed_event(model_id, old_model_id)
        
        return True
    
    @classmethod
    def set_current_model_by_name(
        cls,
        provider_id: str,
        model_name: str,
        publish_event: bool = True
    ) -> bool:
        """
        通过厂商 ID 和模型名称设置当前模型
        
        Args:
            provider_id: 厂商 ID
            model_name: 模型名称
            publish_event: 是否发布模型切换事件
            
        Returns:
            是否设置成功
        """
        model_id = f"{provider_id}:{model_name}"
        return cls.set_current_model(model_id, publish_event)
    
    # ============================================================
    # 模型能力查询（便捷方法）
    # ============================================================
    
    @classmethod
    def current_supports_thinking(cls) -> bool:
        """当前模型是否支持深度思考"""
        model = cls.get_current_model()
        return model.supports_thinking if model else False
    
    @classmethod
    def current_supports_vision(cls) -> bool:
        """当前模型是否支持视觉"""
        model = cls.get_current_model()
        return model.supports_vision if model else False
    
    @classmethod
    def current_supports_tools(cls) -> bool:
        """当前模型是否支持工具调用"""
        model = cls.get_current_model()
        return model.supports_tools if model else False
    
    @classmethod
    def current_supports_web_search(cls) -> bool:
        """当前模型是否支持厂商专属联网搜索"""
        model = cls.get_current_model()
        return model.supports_web_search if model else False
    
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
    # 本地模型管理
    # ============================================================
    
    @classmethod
    def refresh_local_models(cls, host: str = "http://localhost:11434") -> List[LocalModelInfo]:
        """
        刷新本地模型列表（从 Ollama 服务获取）
        
        调用 Ollama API 获取已安装的模型列表，并缓存结果。
        
        Args:
            host: Ollama 服务地址
            
        Returns:
            本地模型信息列表
        """
        import httpx
        from datetime import datetime
        
        cls._local_models = []
        
        try:
            # 调用 Ollama API 获取模型列表
            response = httpx.get(
                f"{host}/api/tags",
                timeout=5.0
            )
            response.raise_for_status()
            
            data = response.json()
            models = data.get("models", [])
            
            for model_data in models:
                model_info = LocalModelInfo(
                    name=model_data.get("name", ""),
                    size=model_data.get("size", 0),
                    parameter_size=model_data.get("details", {}).get("parameter_size", ""),
                    digest=model_data.get("digest", ""),
                )
                
                # 解析修改时间
                modified_at_str = model_data.get("modified_at", "")
                if modified_at_str:
                    try:
                        # Ollama 返回 ISO 格式时间
                        model_info.modified_at = datetime.fromisoformat(
                            modified_at_str.replace("Z", "+00:00")
                        )
                    except Exception:
                        pass
                
                cls._local_models.append(model_info)
            
            cls._local_models_loaded = True
            
            if cls._logger:
                cls._logger.info(f"Loaded {len(cls._local_models)} local models from Ollama")
            
        except httpx.ConnectError:
            if cls._logger:
                cls._logger.warning(f"Cannot connect to Ollama at {host}")
        except httpx.TimeoutException:
            if cls._logger:
                cls._logger.warning(f"Timeout connecting to Ollama at {host}")
        except Exception as e:
            if cls._logger:
                cls._logger.error(f"Failed to refresh local models: {e}")
        
        return cls._local_models
    
    @classmethod
    def get_local_models(cls) -> List[LocalModelInfo]:
        """
        获取已缓存的本地模型列表
        
        如果尚未加载，返回空列表。
        调用 refresh_local_models() 来刷新列表。
        
        Returns:
            本地模型信息列表
        """
        return cls._local_models.copy()
    
    @classmethod
    def is_local_models_loaded(cls) -> bool:
        """检查本地模型列表是否已加载"""
        return cls._local_models_loaded
    
    @classmethod
    def get_local_model_names(cls) -> List[str]:
        """
        获取本地模型名称列表
        
        Returns:
            模型名称列表
        """
        return [m.name for m in cls._local_models]
    
    # ============================================================
    # 事件和回调
    # ============================================================
    
    @classmethod
    def on_model_changed(cls, callback: Callable[[str, Optional[str]], None]) -> None:
        """
        注册模型切换回调
        
        Args:
            callback: 回调函数，参数为 (new_model_id, old_model_id)
        """
        cls._on_model_changed_callbacks.append(callback)
    
    @classmethod
    def _publish_model_changed_event(
        cls,
        new_model_id: str,
        old_model_id: Optional[str]
    ) -> None:
        """发布模型切换事件"""
        try:
            from shared.service_locator import ServiceLocator
            from shared.service_names import SVC_EVENT_BUS
            from shared.event_types import EVENT_MODEL_CHANGED
            
            event_bus = ServiceLocator.get_optional(SVC_EVENT_BUS)
            if event_bus:
                new_model = cls.get_model(new_model_id)
                event_bus.publish(
                    EVENT_MODEL_CHANGED,
                    data={
                        "new_model_id": new_model_id,
                        "old_model_id": old_model_id,
                        "provider": new_model.provider if new_model else None,
                        "model_name": new_model.name if new_model else None,
                        "supports_thinking": new_model.supports_thinking if new_model else False,
                        "supports_vision": new_model.supports_vision if new_model else False,
                    },
                    source="model_registry"
                )
        except Exception as e:
            if cls._logger:
                cls._logger.debug(f"Failed to publish model changed event: {e}")
    
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
        cls._current_model_id = None
        cls._initialized = False
        cls._on_model_changed_callbacks.clear()
        cls._local_models.clear()
        cls._local_models_loaded = False


# ============================================================
# 模块导出
# ============================================================

__all__ = ["ModelRegistry"]
