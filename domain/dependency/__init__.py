# Dependency Health Check Module
"""
依赖健康检查模块

职责：
- 扫描项目电路文件中的 .include 和 .lib 引用
- 检查引用文件是否存在于本地
- 生成依赖健康报告
- 提供依赖解析策略

模块结构：
- models/: 数据模型定义
- scanner/: 依赖扫描器
- resolver/: 依赖解析策略
- service/: 依赖健康服务
- events/: 依赖相关事件定义

设计原则：
- 早发现：项目打开时立即启动本地扫描
- 异步执行：扫描任务不阻塞主线程
- 保守策略：外部依赖下载必须用户确认
- 离线友好：本地扫描与外部查询分离
"""

from domain.dependency.models import (
    DependencyItem,
    DependencyStatus,
    DependencyType,
    HealthReport,
    ResolutionResult,
    ResolutionSource,
)

__all__ = [
    "DependencyItem",
    "DependencyStatus",
    "DependencyType",
    "HealthReport",
    "ResolutionResult",
    "ResolutionSource",
]
