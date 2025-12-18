# Model Configurations
"""
模型配置模块

职责：
- 集中定义所有厂商和模型的配置
- 提供统一的配置导入入口

使用示例：
    from infrastructure.llm_adapters.model_configs import (
        ZHIPU_PROVIDER,
        ZHIPU_MODELS,
    )
"""

from infrastructure.llm_adapters.model_configs.zhipu_models import (
    ZHIPU_PROVIDER,
    ZHIPU_MODELS,
)

__all__ = [
    # 智谱
    "ZHIPU_PROVIDER",
    "ZHIPU_MODELS",
]
