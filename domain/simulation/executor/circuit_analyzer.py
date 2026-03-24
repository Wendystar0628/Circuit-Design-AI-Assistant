# Circuit Analyzer - Circuit File Structure Analyzer
"""
电路文件分析器

职责：
- 分析工作区中的电路文件结构
- 识别主电路文件
- 提取文件引用关系
- 构建依赖关系图
- 扫描项目目录中的可仿真文件

设计原则：
- 复用现有的 IncludeParser 进行语句解析
- 使用被引用分析法识别主电路
- 提供清晰的文件类型判断规则
- 返回结构化的分析结果
- 支持从 ExecutorRegistry 动态获取扩展名

使用示例：
    analyzer = CircuitAnalyzer()
    
    # 扫描项目中的所有电路文件
    circuit_files = analyzer.scan_circuit_files(project_path)
    
    # 构建依赖关系图
    dep_graph = analyzer.build_dependency_graph(project_path)
    
"""

import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Set, TYPE_CHECKING

from domain.dependency.scanner.include_parser import IncludeParser, ParsedInclude

if TYPE_CHECKING:
    from domain.simulation.executor.executor_registry import ExecutorRegistry


# ============================================================
# 数据结构定义
# ============================================================

# ============================================================
# 日志记录器
# ============================================================

_logger = logging.getLogger(__name__)


# ============================================================
# 数据结构定义
# ============================================================

@dataclass
class CircuitFileInfo:
    """电路文件信息"""
    path: str  # 相对于项目根目录的路径
    abs_path: Path  # 绝对路径
    file_type: str  # 文件类型：main/subcircuit/parameter/library/unknown
    size_bytes: int  # 文件大小
    modified_time: float  # 最后修改时间（时间戳）
    has_simulation_commands: bool  # 是否包含仿真控制语句
    has_subcircuit_defs: bool  # 是否包含子电路定义
    has_only_params: bool  # 是否仅包含参数定义
    referenced_by: List[str] = field(default_factory=list)  # 被哪些文件引用
    references: List[ParsedInclude] = field(default_factory=list)  # 引用了哪些文件


# ============================================================
# CircuitAnalyzer - 电路文件分析器
# ============================================================

class CircuitAnalyzer:
    """
    电路文件分析器
    
    分析工作区中的电路文件结构，识别主电路文件，提取文件引用关系
    """
    
    # 支持的电路文件扩展名（默认值，可通过 executor_registry 动态获取）
    CIRCUIT_EXTENSIONS = {".cir", ".sp", ".spice", ".net", ".ckt"}
    
    # 仿真控制语句模式
    SIMULATION_COMMANDS = {
        ".ac", ".dc", ".tran", ".noise", ".op", ".tf", ".disto", ".pz", ".sens"
    }
    
    # 子电路定义模式
    SUBCKT_START_PATTERN = re.compile(r'^\s*\.subckt\s+', re.IGNORECASE)
    SUBCKT_END_PATTERN = re.compile(r'^\s*\.ends\s*', re.IGNORECASE)
    
    # 参数定义模式
    PARAM_PATTERN = re.compile(r'^\s*\.param\s+', re.IGNORECASE)
    
    # 模型定义模式
    MODEL_PATTERN = re.compile(r'^\s*\.model\s+', re.IGNORECASE)
    
    def __init__(self, executor_registry: Optional["ExecutorRegistry"] = None):
        """
        初始化电路分析器
        
        Args:
            executor_registry: 执行器注册表（可选），用于动态获取支持的扩展名
        """
        self.parser = IncludeParser()
        self._executor_registry = executor_registry
        self._logger = _logger
    
    # ============================================================
    # 扩展名管理
    # ============================================================
    
    def get_supported_extensions(self) -> List[str]:
        """
        获取支持的文件扩展名
        
        如果设置了 executor_registry，从注册表动态获取；
        否则使用默认的 CIRCUIT_EXTENSIONS。
        
        Returns:
            List[str]: 支持的文件扩展名列表
        """
        if self._executor_registry is not None:
            extensions = self._executor_registry.get_all_supported_extensions()
            if extensions:
                return extensions
        
        return list(self.CIRCUIT_EXTENSIONS)
    
    def set_executor_registry(self, registry: "ExecutorRegistry") -> None:
        """
        设置执行器注册表
        
        Args:
            registry: 执行器注册表实例
        """
        self._executor_registry = registry
    
    # ============================================================
    # 公开接口
    # ============================================================
    
    def scan_circuit_files(self, project_path: str) -> List[CircuitFileInfo]:
        """
        扫描项目中所有 SPICE 文件
        
        Args:
            project_path: 项目根目录路径
            
        Returns:
            List[CircuitFileInfo]: 电路文件信息列表
        """
        project_root = Path(project_path).resolve()
        circuit_files = []
        
        # 获取支持的扩展名
        extensions = self.get_supported_extensions()
        
        # 递归扫描所有电路文件
        for ext in extensions:
            for file_path in project_root.rglob(f"*{ext}"):
                # 跳过隐藏目录和备份文件
                if self._should_skip_file(file_path):
                    continue
                
                # 提取文件信息
                file_info = self._analyze_file(file_path, project_root)
                if file_info:
                    circuit_files.append(file_info)
        
        return circuit_files
    
    def parse_includes(self, file_path: str) -> List[ParsedInclude]:
        """
        解析文件中的 .include 和 .lib 语句
        
        Args:
            file_path: 文件路径
            
        Returns:
            List[ParsedInclude]: 解析出的引用列表
        """
        # 使用 IncludeParser 解析
        includes = self.parser.parse_file(file_path)
        
        # 解析路径并检查文件是否存在
        file_path_obj = Path(file_path)
        base_dir = file_path_obj.parent
        project_root = self._find_project_root(file_path_obj)
        
        for include in includes:
            include.resolve_path(base_dir, project_root)
        
        return includes
    
    def build_dependency_graph(self, project_path: str) -> Dict[str, List[str]]:
        """
        构建文件依赖关系图
        
        Args:
            project_path: 项目根目录路径
            
        Returns:
            Dict[str, List[str]]: 依赖关系图，键为文件路径，值为该文件引用的文件列表
        """
        project_root = Path(project_path).resolve()
        dep_graph = {}
        
        # 扫描所有电路文件
        circuit_files = self.scan_circuit_files(project_path)
        
        # 构建依赖关系
        for file_info in circuit_files:
            # 解析引用
            includes = self.parse_includes(str(file_info.abs_path))
            
            # 提取存在的引用文件路径
            referenced_files = [
                inc.resolved_path
                for inc in includes
                if inc.exists and inc.resolved_path
            ]
            
            dep_graph[file_info.path] = referenced_files
        
        return dep_graph
    
    def get_circuit_type(self, file_path: str) -> str:
        """
        判断文件类型
        
        Args:
            file_path: 文件路径
            
        Returns:
            str: 文件类型（main/subcircuit/parameter/library/unknown）
        """
        file_path_obj = Path(file_path)
        if not file_path_obj.exists():
            return "unknown"
        
        project_root = self._find_project_root(file_path_obj)
        file_info = self._analyze_file(file_path_obj, project_root)
        
        if not file_info:
            return "unknown"
        
        return file_info.file_type
    
    # ============================================================
    # 内部辅助方法
    # ============================================================
    
    def _should_skip_file(self, file_path: Path) -> bool:
        """
        判断是否应该跳过文件
        
        Args:
            file_path: 文件路径
            
        Returns:
            bool: 是否跳过
        """
        # 跳过隐藏目录
        for part in file_path.parts:
            if part.startswith('.'):
                return True
        
        # 跳过备份文件
        if file_path.name.endswith(('.bak', '.backup', '~')):
            return True
        
        return False
    
    def _find_project_root(self, file_path: Path) -> Path:
        """
        查找项目根目录
        
        Args:
            file_path: 文件路径
            
        Returns:
            Path: 项目根目录
        """
        # 向上查找包含 .circuit_ai 目录的父目录
        current = file_path.parent if file_path.is_file() else file_path
        
        while current != current.parent:
            if (current / ".circuit_ai").exists():
                return current
            current = current.parent
        
        # 未找到，返回文件所在目录
        return file_path.parent if file_path.is_file() else file_path
    
    def _analyze_file(self, file_path: Path, project_root: Path) -> Optional[CircuitFileInfo]:
        """
        分析单个文件
        
        Args:
            file_path: 文件路径
            project_root: 项目根目录
            
        Returns:
            Optional[CircuitFileInfo]: 文件信息，解析失败返回 None
        """
        try:
            # 读取文件内容
            content = file_path.read_text(encoding='utf-8', errors='ignore')
            lines = content.splitlines()
            
            # 分析文件特征
            has_simulation_commands = self._has_simulation_commands(lines)
            has_subcircuit_defs = self._has_subcircuit_defs(lines)
            has_only_params = self._has_only_params(lines)
            
            # 解析引用
            includes = self.parser.parse_content(content)
            for include in includes:
                include.resolve_path(file_path.parent, project_root)
            
            # 判断文件类型
            file_type = self._determine_file_type(
                has_simulation_commands,
                has_subcircuit_defs,
                has_only_params,
                len(includes)
            )
            
            # 计算相对路径
            try:
                rel_path = str(file_path.relative_to(project_root))
            except ValueError:
                rel_path = str(file_path)
            
            return CircuitFileInfo(
                path=rel_path,
                abs_path=file_path,
                file_type=file_type,
                size_bytes=file_path.stat().st_size,
                modified_time=file_path.stat().st_mtime,
                has_simulation_commands=has_simulation_commands,
                has_subcircuit_defs=has_subcircuit_defs,
                has_only_params=has_only_params,
                references=includes,
            )
            
        except Exception:
            return None
    
    def _has_simulation_commands(self, lines: List[str]) -> bool:
        """
        检查是否包含仿真控制语句
        
        Args:
            lines: 文件行列表
            
        Returns:
            bool: 是否包含仿真控制语句
        """
        for line in lines:
            stripped = line.strip().lower()
            if stripped.startswith('*') or stripped.startswith(';'):
                continue
            
            for cmd in self.SIMULATION_COMMANDS:
                if stripped.startswith(cmd):
                    return True
        
        return False
    
    def _has_subcircuit_defs(self, lines: List[str]) -> bool:
        """
        检查是否包含子电路定义
        
        Args:
            lines: 文件行列表
            
        Returns:
            bool: 是否包含子电路定义
        """
        for line in lines:
            if self.SUBCKT_START_PATTERN.match(line):
                return True
        
        return False
    
    def _has_only_params(self, lines: List[str]) -> bool:
        """
        检查是否仅包含参数定义
        
        Args:
            lines: 文件行列表
            
        Returns:
            bool: 是否仅包含参数定义
        """
        has_params = False
        has_other = False
        
        for line in lines:
            stripped = line.strip()
            if not stripped or stripped.startswith('*') or stripped.startswith(';'):
                continue
            
            if self.PARAM_PATTERN.match(line):
                has_params = True
            elif stripped.startswith('.'):
                # 其他 SPICE 指令
                has_other = True
        
        return has_params and not has_other
    
    def _determine_file_type(
        self,
        has_simulation_commands: bool,
        has_subcircuit_defs: bool,
        has_only_params: bool,
        num_includes: int
    ) -> str:
        """
        判断文件类型
        
        Args:
            has_simulation_commands: 是否包含仿真控制语句
            has_subcircuit_defs: 是否包含子电路定义
            has_only_params: 是否仅包含参数定义
            num_includes: 引用文件数量
            
        Returns:
            str: 文件类型
        """
        if has_only_params:
            return "parameter"
        
        if has_subcircuit_defs and not has_simulation_commands:
            return "subcircuit"
        
        if has_simulation_commands:
            return "main"
        
        if has_subcircuit_defs:
            return "library"
        
        return "unknown"
    
# ============================================================
# 模块导出
# ============================================================

__all__ = [
    "CircuitAnalyzer",
    "CircuitFileInfo",
]
