# External Resolver
"""
外部源解析器

职责：
- 查询外部源（商城、公开库）是否有可用的模型
- 所有下载操作必须经过用户确认
- 支持离线模式（仅查询缓存）
"""

from typing import Optional

from domain.dependency.models.dependency_item import DependencyItem
from domain.dependency.models.resolution_result import (
    ResolutionResult,
    ResolutionSource,
)
from domain.dependency.resolver.resolution_strategy import ResolutionStrategy


class ExternalResolver(ResolutionStrategy):
    """
    外部源解析器
    
    查询外部源（商城、公开库）是否有可用的模型
    所有下载操作必须经过用户确认
    """
    
    def __init__(self):
        """初始化外部解析器"""
        # 延迟获取的服务
        self._model_downloader = None
        self._is_online = True
    
    @property
    def model_downloader(self):
        """延迟获取模型下载器（阶段十实现）"""
        if self._model_downloader is None:
            try:
                from shared.service_locator import ServiceLocator
                from shared.service_names import SVC_MODEL_DOWNLOADER
                self._model_downloader = ServiceLocator.get_optional(SVC_MODEL_DOWNLOADER)
            except Exception:
                pass
        return self._model_downloader
    
    def get_name(self) -> str:
        return "external_resolver"
    
    def can_resolve(self, dependency: DependencyItem) -> bool:
        """
        判断是否能够解析
        
        外部解析器仅处理 .lib 和 .model 类型的依赖
        """
        # 仅处理库文件和模型文件
        raw_path = dependency.raw_path.lower()
        return raw_path.endswith('.lib') or raw_path.endswith('.mod')
    
    def resolve(self, dependency: DependencyItem, project_root: str) -> ResolutionResult:
        """
        尝试从外部源解析依赖
        
        注意：此方法仅检查可用性，不执行实际下载
        下载操作需要用户在依赖健康面板中确认后执行
        """
        # 离线模式
        if not self._is_online:
            return ResolutionResult.create_failure(
                dependency_id=dependency.id,
                source=ResolutionSource.MARKETPLACE,
                error_message="离线模式，无法查询外部源",
            )
        
        # 检查模型下载器是否可用
        if self.model_downloader is None:
            return ResolutionResult.create_failure(
                dependency_id=dependency.id,
                source=ResolutionSource.MARKETPLACE,
                error_message="模型下载服务不可用（阶段十实现）",
            )
        
        # TODO: 阶段十实现 - 调用 model_downloader.check_model_availability()
        # 查询商城是否有该模型，返回可用性信息
        # 若可用，返回 requires_confirmation=True 的成功结果
        # 用户确认后，由依赖健康面板调用 model_downloader.execute_download()
        
        return ResolutionResult.create_failure(
            dependency_id=dependency.id,
            source=ResolutionSource.MARKETPLACE,
            error_message="外部源查询功能将在阶段十实现",
        )
    
    def set_online_mode(self, is_online: bool) -> None:
        """设置在线/离线模式"""
        self._is_online = is_online
    
    @property
    def requires_confirmation(self) -> bool:
        """外部源下载必须经过用户确认"""
        return True
    
    @property
    def requires_network(self) -> bool:
        return True


__all__ = ["ExternalResolver"]
