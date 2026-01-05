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
    
    # 检测主电路文件
    result = analyzer.detect_main_circuit(project_path)
    if result["main_circuit"]:
        print(f"主电路: {result['main_circuit']}")
        print(f"置信度: {result['confidence']}")
    
    # 扫描可仿真文件（使用 ExecutorRegistry 的扩展名）
    scan_result = analyzer.scan_simulatable_files(project_path)
    print(f"发现 {len(scan_result.files)} 个可仿真文件")
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
class ScanResult:
    """
    文件扫描结果
    
    Attributes:
        files: 发现的可仿真文件列表（相对路径）
        main_circuit_candidates: 主电路候选列表（相对路径）
        dependency_graph: 文件依赖关系图
    """
    files: List[Path] = field(default_factory=list)
    """发现的可仿真文件列表"""
    
    main_circuit_candidates: List[Path] = field(default_factory=list)
    """主电路候选列表（可能为 0、1 或多个）"""
    
    dependency_graph: Dict[str, List[str]] = field(default_factory=dict)
    """文件依赖关系图"""
    
    def has_single_main_circuit(self) -> bool:
        """是否只有一个主电路候选"""
        return len(self.main_circuit_candidates) == 1
    
    def has_multiple_candidates(self) -> bool:
        """是否有多个主电路候选"""
        return len(self.main_circuit_candidates) > 1
    
    def has_no_candidates(self) -> bool:
        """是否没有主电路候选"""
        return len(self.main_circuit_candidates) == 0


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


@dataclass
class MainCircuitDetectionResult:
    """主电路检测结果"""
    main_circuit: Optional[str]  # 主电路路径（相对路径），未检测到则为 None
    confidence: float  # 置信度（0-1）
    candidates: List[Dict[str, any]]  # 其他候选主电路列表
    subcircuits: List[str]  # 子电路文件列表
    parameters: List[str]  # 参数文件列表
    dependency_graph: Dict[str, List[str]]  # 依赖关系图


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
    
    def scan_simulatable_files(self, project_path: str) -> ScanResult:
        """
        扫描项目目录中的可仿真文件
        
        返回扫描结果，包含文件列表、主电路候选和依赖关系图。
        
        Args:
            project_path: 项目根目录路径
            
        Returns:
            ScanResult: 扫描结果数据结构
        """
        project_root = Path(project_path).resolve()
        
        # 扫描所有电路文件
        circuit_files = self.scan_circuit_files(project_path)
        
        if not circuit_files:
            return ScanResult()
        
        # 构建依赖关系图
        dep_graph = self.build_dependency_graph(project_path)
        
        # 检测主电路
        detection_result = self.detect_main_circuit(project_path)
        
        # 构建文件路径列表
        files = [Path(f.path) for f in circuit_files]
        
        # 构建主电路候选列表
        candidates = []
        if detection_result.main_circuit:
            candidates.append(Path(detection_result.main_circuit))
        for candidate in detection_result.candidates:
            candidates.append(Path(candidate["path"]))
        
        return ScanResult(
            files=files,
            main_circuit_candidates=candidates,
            dependency_graph=dep_graph,
        )
    
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
    
    def detect_main_circuit(self, project_path: str) -> MainCircuitDetectionResult:
        """
        自动检测主电路文件
        
        使用被引用分析法：
        1. 扫描所有电路文件
        2. 构建引用关系图
        3. 计算每个文件的被引用次数
        4. 被引用次数为 0 且包含仿真控制语句的文件为主电路候选
        5. 按优先级规则排序候选文件
        
        Args:
            project_path: 项目根目录路径
            
        Returns:
            MainCircuitDetectionResult: 检测结果
        """
        project_root = Path(project_path).resolve()
        
        # 扫描所有电路文件
        circuit_files = self.scan_circuit_files(project_path)
        
        if not circuit_files:
            return MainCircuitDetectionResult(
                main_circuit=None,
                confidence=0.0,
                candidates=[],
                subcircuits=[],
                parameters=[],
                dependency_graph={},
            )
        
        # 构建依赖关系图
        dep_graph = self.build_dependency_graph(project_path)
        
        # 计算被引用次数
        referenced_count = {}
        for file_path in dep_graph:
            referenced_count[file_path] = 0
        
        for file_path, refs in dep_graph.items():
            for ref in refs:
                if ref in referenced_count:
                    referenced_count[ref] += 1
        
        # 找出主电路候选（被引用次数为 0 且包含仿真控制语句）
        candidates = []
        subcircuits = []
        parameters = []
        
        for file_info in circuit_files:
            ref_count = referenced_count.get(file_info.path, 0)
            
            # 分类文件
            if file_info.has_only_params:
                parameters.append(file_info.path)
            elif file_info.has_subcircuit_defs and not file_info.has_simulation_commands:
                subcircuits.append(file_info.path)
            elif ref_count == 0 and file_info.has_simulation_commands:
                # 主电路候选
                priority = self._calculate_priority(file_info, project_root)
                candidates.append({
                    "path": file_info.path,
                    "priority": priority,
                    "size": file_info.size_bytes,
                    "modified_time": file_info.modified_time,
                })
        
        # 按优先级排序候选文件
        candidates.sort(key=lambda x: x["priority"], reverse=True)
        
        # 确定主电路和置信度
        if not candidates:
            main_circuit = None
            confidence = 0.0
        elif len(candidates) == 1:
            main_circuit = candidates[0]["path"]
            confidence = 1.0
        else:
            # 多个候选，选择优先级最高的
            main_circuit = candidates[0]["path"]
            # 置信度基于优先级差距
            top_priority = candidates[0]["priority"]
            second_priority = candidates[1]["priority"] if len(candidates) > 1 else 0
            confidence = min(1.0, top_priority / (second_priority + 1))
        
        return MainCircuitDetectionResult(
            main_circuit=main_circuit,
            confidence=confidence,
            candidates=candidates[1:] if len(candidates) > 1 else [],
            subcircuits=subcircuits,
            parameters=parameters,
            dependency_graph=dep_graph,
        )
    
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
    
    def _calculate_priority(self, file_info: CircuitFileInfo, project_root: Path) -> float:
        """
        计算主电路候选的优先级
        
        优先级规则：
        1. 名为 main.cir 的文件优先级最高（+100）
        2. 包含仿真控制语句（+50）
        3. 文件大小较大（+0-20，按比例）
        4. 最近修改时间较新（+0-10，按比例）
        
        Args:
            file_info: 文件信息
            project_root: 项目根目录
            
        Returns:
            float: 优先级分数
        """
        priority = 0.0
        
        # 文件名优先级
        if file_info.abs_path.name.lower() == "main.cir":
            priority += 100.0
        
        # 仿真控制语句
        if file_info.has_simulation_commands:
            priority += 50.0
        
        # 文件大小（归一化到 0-20）
        # 假设 10KB 以上的文件为大文件
        size_score = min(20.0, (file_info.size_bytes / 10240) * 20)
        priority += size_score
        
        # 修改时间（归一化到 0-10）
        # 最近 7 天内修改的文件优先级更高
        import time
        current_time = time.time()
        age_days = (current_time - file_info.modified_time) / 86400
        if age_days < 7:
            time_score = 10.0 * (1 - age_days / 7)
            priority += time_score
        
        return priority


# ============================================================
# 模块导出
# ============================================================

__all__ = [
    "CircuitAnalyzer",
    "CircuitFileInfo",
    "MainCircuitDetectionResult",
    "ScanResult",
]
