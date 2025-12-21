# Dependency Health Service
"""
依赖健康服务

职责：
- 作为依赖健康检查的统一入口
- 协调扫描器和解析器
- 管理健康报告的缓存和持久化
- 发布依赖相关事件
"""

from pathlib import Path
from typing import List, Optional

from domain.dependency.models.dependency_item import DependencyItem, DependencyStatus
from domain.dependency.models.health_report import HealthReport
from domain.dependency.models.resolution_result import ResolutionResult
from domain.dependency.scanner.dependency_scanner import DependencyScanner
from domain.dependency.scanner.scan_config import ScanConfig
from domain.dependency.resolver.local_resolver import LocalResolver
from domain.dependency.resolver.external_resolver import ExternalResolver
from domain.dependency.resolver.resolution_strategy import ResolutionStrategy


class DependencyHealthService:
    """
    依赖健康服务
    
    提供依赖健康检查的统一接口
    """
    
    # 健康报告缓存文件名
    REPORT_CACHE_FILE = "dependency_health.json"
    
    def __init__(self, config: Optional[ScanConfig] = None):
        """
        初始化服务
        
        Args:
            config: 扫描配置
        """
        self.config = config or ScanConfig()
        self.scanner = DependencyScanner(self.config)
        
        # 解析策略链（按优先级排序）
        self._resolvers: List[ResolutionStrategy] = [
            LocalResolver(),
            ExternalResolver(),
        ]
        
        # 缓存的健康报告
        self._cached_report: Optional[HealthReport] = None
        
        # 延迟获取的服务
        self._event_bus = None
        self._logger = None
        self._json_repo = None
    
    @property
    def event_bus(self):
        """延迟获取事件总线"""
        if self._event_bus is None:
            try:
                from shared.service_locator import ServiceLocator
                from shared.service_names import SVC_EVENT_BUS
                self._event_bus = ServiceLocator.get_optional(SVC_EVENT_BUS)
            except Exception:
                pass
        return self._event_bus
    
    @property
    def logger(self):
        """延迟获取日志器"""
        if self._logger is None:
            try:
                from infrastructure.utils.logger import get_logger
                self._logger = get_logger("dependency_health_service")
            except Exception:
                pass
        return self._logger
    
    @property
    def json_repo(self):
        """延迟获取 JSON 仓库"""
        if self._json_repo is None:
            try:
                from infrastructure.persistence.json_repository import JsonRepository
                self._json_repo = JsonRepository()
            except Exception:
                pass
        return self._json_repo
    
    def start_scan(self, project_path: str) -> None:
        """
        启动异步扫描
        
        扫描任务通过 AsyncTaskRegistry 提交到后台线程
        扫描完成后发布 EVENT_DEPENDENCY_SCAN_COMPLETE 事件
        
        Args:
            project_path: 项目根目录路径
        """
        # 发布扫描开始事件
        if self.event_bus:
            from shared.event_types import EVENT_DEPENDENCY_SCAN_STARTED
            self.event_bus.publish(EVENT_DEPENDENCY_SCAN_STARTED, {
                "project_path": project_path,
            })
        
        # TODO: 通过 AsyncTaskRegistry 提交异步任务
        # 目前同步执行，后续改为异步
        try:
            report = self.scan_sync(project_path)
            self._publish_scan_complete(report)
        except Exception as e:
            if self.logger:
                self.logger.error(f"依赖扫描失败: {e}")
    
    def scan_sync(self, project_path: str) -> HealthReport:
        """
        同步执行扫描
        
        Args:
            project_path: 项目根目录路径
            
        Returns:
            HealthReport: 健康报告
        """
        if self.logger:
            self.logger.info(f"开始扫描项目依赖: {project_path}")
        
        # 执行扫描
        report = self.scanner.scan(project_path)
        
        # 缓存报告
        self._cached_report = report
        
        # 持久化报告
        self._save_report(project_path, report)
        
        if self.logger:
            self.logger.info(
                f"依赖扫描完成: {report.total_count} 个依赖, "
                f"{report.missing_count} 个缺失"
            )
        
        return report
    
    def get_cached_report(self) -> Optional[HealthReport]:
        """获取缓存的健康报告"""
        return self._cached_report
    
    def load_cached_report(self, project_path: str) -> Optional[HealthReport]:
        """
        从文件加载缓存的健康报告
        
        Args:
            project_path: 项目根目录路径
            
        Returns:
            Optional[HealthReport]: 健康报告，若不存在则返回 None
        """
        cache_file = Path(project_path) / ".circuit_ai" / self.REPORT_CACHE_FILE
        
        if not cache_file.exists():
            return None
        
        try:
            if self.json_repo:
                data = self.json_repo.load_json(cache_file)
            else:
                import json
                data = json.loads(cache_file.read_text())
            
            report = HealthReport.from_dict(data)
            self._cached_report = report
            return report
            
        except Exception as e:
            if self.logger:
                self.logger.warning(f"加载依赖健康报告失败: {e}")
            return None
    
    def try_resolve(
        self,
        dependency: DependencyItem,
        project_path: str,
    ) -> ResolutionResult:
        """
        尝试解析单个依赖
        
        按策略链顺序尝试解析
        
        Args:
            dependency: 依赖项
            project_path: 项目根目录
            
        Returns:
            ResolutionResult: 解析结果
        """
        for resolver in self._resolvers:
            if resolver.can_resolve(dependency):
                result = resolver.resolve(dependency, project_path)
                if result.success:
                    return result
        
        # 所有策略都失败
        from domain.dependency.models.resolution_result import ResolutionSource
        return ResolutionResult.create_failure(
            dependency_id=dependency.id,
            source=ResolutionSource.PROJECT_LOCAL,
            error_message="所有解析策略均失败",
        )
    
    def apply_resolution(
        self,
        dependency_id: str,
        result: ResolutionResult,
    ) -> bool:
        """
        应用解析结果
        
        更新依赖项状态并刷新报告
        
        Args:
            dependency_id: 依赖项 ID
            result: 解析结果
            
        Returns:
            bool: 是否成功
        """
        if not self._cached_report:
            return False
        
        # 查找依赖项
        for dep in self._cached_report.dependencies:
            if dep.id == dependency_id:
                if result.success:
                    dep.status = DependencyStatus.RESOLVED
                    dep.resolved_path = result.resolved_path
                    dep.resolution_source = result.source.value
                else:
                    dep.status = DependencyStatus.ERROR
                    dep.error_message = result.error_message
                
                # 发布报告更新事件
                self._publish_report_updated()
                return True
        
        return False
    
    def _save_report(self, project_path: str, report: HealthReport) -> None:
        """保存健康报告到文件"""
        cache_dir = Path(project_path) / ".circuit_ai"
        cache_dir.mkdir(parents=True, exist_ok=True)
        cache_file = cache_dir / self.REPORT_CACHE_FILE
        
        try:
            if self.json_repo:
                self.json_repo.save_json(cache_file, report.to_dict())
            else:
                import json
                cache_file.write_text(json.dumps(report.to_dict(), indent=2))
        except Exception as e:
            if self.logger:
                self.logger.warning(f"保存依赖健康报告失败: {e}")
    
    def _publish_scan_complete(self, report: HealthReport) -> None:
        """发布扫描完成事件"""
        if self.event_bus:
            from shared.event_types import EVENT_DEPENDENCY_SCAN_COMPLETE
            self.event_bus.publish(EVENT_DEPENDENCY_SCAN_COMPLETE, {
                "project_path": report.project_path,
                "total_dependencies": report.total_count,
                "missing_count": report.missing_count,
                "resolved_count": report.resolved_count,
                "has_issues": report.has_issues,
            })
    
    def _publish_report_updated(self) -> None:
        """发布报告更新事件"""
        if self.event_bus and self._cached_report:
            from shared.event_types import EVENT_DEPENDENCY_REPORT_UPDATED
            self.event_bus.publish(EVENT_DEPENDENCY_REPORT_UPDATED, {
                "report_path": self._cached_report.project_path,
                "missing_dependencies": [
                    d.to_dict() for d in self._cached_report.get_missing_dependencies()
                ],
                "resolution_suggestions": [],
            })


__all__ = ["DependencyHealthService"]
