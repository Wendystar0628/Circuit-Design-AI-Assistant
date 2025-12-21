# Dependency Scanner
"""
依赖扫描器

职责：
- 扫描项目中所有电路文件
- 解析 .include 和 .lib 引用
- 检查引用文件是否存在
- 生成依赖健康报告
"""

import hashlib
import time
from pathlib import Path
from typing import List, Optional, Set

from domain.dependency.models.dependency_item import (
    DependencyItem,
    DependencyStatus,
    DependencyType,
)
from domain.dependency.models.health_report import HealthReport
from domain.dependency.scanner.include_parser import IncludeParser
from domain.dependency.scanner.scan_config import ScanConfig


class DependencyScanner:
    """
    依赖扫描器
    
    扫描项目电路文件，检查依赖完整性
    """
    
    def __init__(self, config: Optional[ScanConfig] = None):
        """
        初始化扫描器
        
        Args:
            config: 扫描配置，若为 None 则使用默认配置
        """
        self.config = config or ScanConfig()
        self.parser = IncludeParser()
        self._visited_files: Set[str] = set()
        self._current_depth: int = 0
    
    def scan(self, project_path: str) -> HealthReport:
        """
        扫描项目依赖
        
        Args:
            project_path: 项目根目录路径
            
        Returns:
            HealthReport: 依赖健康报告
        """
        start_time = time.time()
        self._visited_files.clear()
        self._current_depth = 0
        
        project_root = Path(project_path).resolve()
        report = HealthReport(project_path=str(project_root))
        
        # 收集所有电路文件
        circuit_files = self._collect_circuit_files(project_root)
        report.scanned_files = len(circuit_files)
        
        # 扫描每个文件
        for file_path in circuit_files:
            dependencies = self._scan_file(file_path, project_root)
            report.dependencies.extend(dependencies)
        
        # 计算扫描耗时
        report.scan_duration_ms = (time.time() - start_time) * 1000
        
        return report
    
    def _collect_circuit_files(self, project_root: Path) -> List[Path]:
        """收集项目中所有电路文件"""
        circuit_files = []
        # 缓存已检测的虚拟环境目录，避免重复检测
        venv_dirs: Set[Path] = set()
        
        for item in project_root.rglob("*"):
            # 跳过黑名单目录
            if any(part in self.config.blacklist_dirs for part in item.parts):
                continue
            
            # 跳过虚拟环境目录（通过特征文件检测）
            skip = False
            for parent in item.parents:
                if parent in venv_dirs:
                    skip = True
                    break
                if parent not in venv_dirs and self.config.is_venv_directory(parent):
                    venv_dirs.add(parent)
                    skip = True
                    break
            if skip:
                continue
            
            # 检查是否为电路文件
            if item.is_file() and self.config.is_circuit_file(item.name):
                # 检查文件大小
                try:
                    if item.stat().st_size <= self.config.max_file_size_bytes:
                        circuit_files.append(item)
                except OSError:
                    pass
        
        return circuit_files
    
    def _scan_file(
        self,
        file_path: Path,
        project_root: Path,
    ) -> List[DependencyItem]:
        """扫描单个文件的依赖"""
        dependencies = []
        
        # 防止重复扫描
        file_key = str(file_path.resolve())
        if file_key in self._visited_files:
            return dependencies
        self._visited_files.add(file_key)
        
        # 解析引用语句
        includes = self.parser.parse_file(str(file_path))
        
        for include in includes:
            # 生成唯一 ID
            dep_id = self._generate_dep_id(file_path, include.line_number, include.raw_path)
            
            # 确定依赖类型
            dep_type = (
                DependencyType.INCLUDE
                if include.statement_type == "include"
                else DependencyType.LIB
            )
            
            # 解析引用路径
            resolved_path = self._resolve_path(
                include.raw_path,
                file_path,
                project_root,
            )
            
            # 检查文件是否存在
            if resolved_path and Path(resolved_path).exists():
                status = DependencyStatus.RESOLVED
            else:
                status = DependencyStatus.MISSING
            
            # 创建依赖项
            dep = DependencyItem(
                id=dep_id,
                dep_type=dep_type,
                raw_path=include.raw_path,
                source_file=str(file_path.relative_to(project_root)),
                source_line=include.line_number,
                status=status,
                resolved_path=resolved_path if status == DependencyStatus.RESOLVED else None,
            )
            
            dependencies.append(dep)
            
            # 递归扫描嵌套引用
            if (
                self.config.parse_nested_includes
                and status == DependencyStatus.RESOLVED
                and self._current_depth < self.config.max_recursion_depth
            ):
                self._current_depth += 1
                nested_deps = self._scan_file(Path(resolved_path), project_root)
                dependencies.extend(nested_deps)
                self._current_depth -= 1
        
        return dependencies
    
    def _resolve_path(
        self,
        raw_path: str,
        source_file: Path,
        project_root: Path,
    ) -> Optional[str]:
        """
        解析引用路径
        
        尝试多种路径解析策略：
        1. 相对于源文件目录
        2. 相对于项目根目录
        3. 绝对路径
        """
        # 清理路径
        clean_path = raw_path.strip().strip('"').strip("'")
        
        # 策略1：相对于源文件目录
        relative_to_source = source_file.parent / clean_path
        if relative_to_source.exists():
            return str(relative_to_source.resolve())
        
        # 策略2：相对于项目根目录
        relative_to_root = project_root / clean_path
        if relative_to_root.exists():
            return str(relative_to_root.resolve())
        
        # 策略3：绝对路径
        absolute_path = Path(clean_path)
        if absolute_path.is_absolute() and absolute_path.exists():
            return str(absolute_path.resolve())
        
        # 策略4：在常见子目录中搜索
        common_dirs = ["subcircuits", "models", "lib", "libraries", "parameters"]
        filename = Path(clean_path).name
        for subdir in common_dirs:
            search_path = project_root / subdir / filename
            if search_path.exists():
                return str(search_path.resolve())
        
        return None
    
    def _generate_dep_id(
        self,
        source_file: Path,
        line_number: int,
        raw_path: str,
    ) -> str:
        """生成依赖项唯一 ID"""
        content = f"{source_file}:{line_number}:{raw_path}"
        return hashlib.md5(content.encode()).hexdigest()[:12]


__all__ = ["DependencyScanner"]
