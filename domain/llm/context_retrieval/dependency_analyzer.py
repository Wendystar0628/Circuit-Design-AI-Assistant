# Dependency Analyzer
"""
电路依赖图分析器 - 构建电路文件之间的依赖关系图

职责：
- 构建电路文件之间的依赖关系图
- 实现多文件感知的上下文构建
- 解析 .include、.lib、.model 语句

依赖解析规则：
- .include "path/to/file.cir" - 直接包含子电路文件
- .lib "path/to/lib.lib" section - 库文件引用
- .model 语句中引用的外部模型文件
- 支持相对路径和绝对路径解析

递归解析策略：
- 最大递归深度：5 层（防止循环引用）
- 检测循环依赖并记录警告日志
- 缓存已解析的依赖关系

上下文注入优先级：
- 直接依赖（深度 1）：完整内容注入
- 间接依赖（深度 2-3）：仅注入 .subckt 定义部分
- 深层依赖（深度 4+）：仅记录文件名，不注入内容

被调用方：context_retriever.py
"""

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Set


# ============================================================
# 常量定义
# ============================================================

# 最大递归深度
MAX_DEPTH = 5

# 依赖语句正则模式
INCLUDE_PATTERN = r'\.include\s+["\']?([^"\'\s]+)["\']?'
LIB_PATTERN = r'\.lib\s+["\']?([^"\'\s]+)["\']?(?:\s+(\w+))?'
MODEL_PATTERN = r'\.model\s+(\w+)\s+(\w+)'

# SPICE 文件扩展名
SPICE_EXTENSIONS = {".cir", ".sp", ".spice", ".lib", ".inc", ".mod"}


@dataclass
class DependencyNode:
    """依赖节点"""
    path: str
    depth: int
    dependencies: List[str] = field(default_factory=list)
    content: Optional[str] = None
    subcircuits: List[str] = field(default_factory=list)



@dataclass
class DependencyGraph:
    """依赖图"""
    root: str
    nodes: Dict[str, DependencyNode] = field(default_factory=dict)
    order: List[str] = field(default_factory=list)  # 拓扑排序后的顺序


class DependencyAnalyzer:
    """
    电路依赖图分析器
    
    构建电路文件之间的依赖关系图，实现多文件感知的上下文构建。
    """

    # 依赖图缓存：{main_file: (mtime, DependencyGraph)}
    _cache: Dict[str, tuple] = {}

    def __init__(self):
        self._event_bus = None
        self._logger = None
        self._subscribed = False

    @property
    def event_bus(self):
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
        if self._logger is None:
            try:
                from infrastructure.utils.logger import get_logger
                self._logger = get_logger("dependency_analyzer")
            except Exception:
                pass
        return self._logger

    def _subscribe_events(self):
        """订阅文件变化事件"""
        if self._subscribed or self.event_bus is None:
            return
        try:
            from shared.event_types import EVENT_FILE_CHANGED
            self.event_bus.subscribe(EVENT_FILE_CHANGED, self._on_file_changed)
            self._subscribed = True
        except Exception:
            pass

    def _on_file_changed(self, event_data: Dict[str, Any]):
        """文件变化事件处理，失效相关缓存"""
        path = event_data.get("path", "")
        if path:
            self.invalidate_cache(path)


    # ============================================================
    # 主入口
    # ============================================================

    def build_dependency_graph(self, main_file: str) -> DependencyGraph:
        """
        构建依赖图
        
        Args:
            main_file: 主电路文件路径
            
        Returns:
            DependencyGraph: 依赖图
        """
        self._subscribe_events()
        
        main_path = Path(main_file)
        if not main_path.exists():
            return DependencyGraph(root=main_file)
        
        # 检查缓存
        mtime = main_path.stat().st_mtime
        cached = self._cache.get(main_file)
        if cached and cached[0] == mtime:
            return cached[1]
        
        # 构建新的依赖图
        graph = DependencyGraph(root=main_file)
        visited: Set[str] = set()
        
        self._build_recursive(main_path, graph, visited, depth=0)
        
        # 拓扑排序
        graph.order = self._topological_sort(graph)
        
        # 缓存结果
        self._cache[main_file] = (mtime, graph)
        
        if self.logger:
            self.logger.debug(
                f"Built dependency graph for {main_file}: "
                f"{len(graph.nodes)} nodes"
            )
        
        return graph

    def _build_recursive(
        self,
        file_path: Path,
        graph: DependencyGraph,
        visited: Set[str],
        depth: int,
    ):
        """递归构建依赖图"""
        path_str = str(file_path)
        
        # 检查循环依赖
        if path_str in visited:
            if self.logger:
                self.logger.warning(f"Circular dependency detected: {path_str}")
            return
        
        # 检查深度限制
        if depth > MAX_DEPTH:
            if self.logger:
                self.logger.debug(f"Max depth reached for: {path_str}")
            return
        
        visited.add(path_str)
        
        # 创建节点
        node = DependencyNode(path=path_str, depth=depth)
        
        try:
            content = file_path.read_text(encoding="utf-8", errors="ignore")
            node.content = content
            
            # 提取子电路定义
            node.subcircuits = self._extract_subcircuits(content)
            
            # 解析依赖
            dependencies = self._parse_dependencies(content, file_path.parent)
            node.dependencies = dependencies
            
            # 递归处理依赖
            for dep in dependencies:
                dep_path = Path(dep)
                if dep_path.exists():
                    self._build_recursive(dep_path, graph, visited, depth + 1)
                    
        except Exception as e:
            if self.logger:
                self.logger.debug(f"Error parsing {path_str}: {e}")
        
        graph.nodes[path_str] = node


    # ============================================================
    # 依赖解析
    # ============================================================

    def _parse_dependencies(
        self,
        content: str,
        base_dir: Path,
    ) -> List[str]:
        """
        解析文件中的依赖声明
        
        Args:
            content: 文件内容
            base_dir: 基准目录（用于解析相对路径）
            
        Returns:
            List[str]: 依赖文件路径列表
        """
        dependencies = []
        
        # 解析 .include 语句
        includes = re.findall(INCLUDE_PATTERN, content, re.IGNORECASE)
        for inc in includes:
            dep_path = self._resolve_path(inc, base_dir)
            if dep_path:
                dependencies.append(dep_path)
        
        # 解析 .lib 语句
        libs = re.findall(LIB_PATTERN, content, re.IGNORECASE)
        for lib_match in libs:
            lib_path = lib_match[0] if isinstance(lib_match, tuple) else lib_match
            dep_path = self._resolve_path(lib_path, base_dir)
            if dep_path:
                dependencies.append(dep_path)
        
        return dependencies

    def _resolve_path(self, path_str: str, base_dir: Path) -> Optional[str]:
        """
        解析路径（支持相对路径和绝对路径）
        
        Args:
            path_str: 路径字符串
            base_dir: 基准目录
            
        Returns:
            str: 解析后的绝对路径，或 None
        """
        # 尝试相对于基准目录
        rel_path = base_dir / path_str
        if rel_path.exists():
            return str(rel_path.resolve())
        
        # 尝试绝对路径
        abs_path = Path(path_str)
        if abs_path.exists():
            return str(abs_path.resolve())
        
        # 尝试在 subcircuits 目录查找
        subcircuits_path = base_dir / "subcircuits" / path_str
        if subcircuits_path.exists():
            return str(subcircuits_path.resolve())
        
        return None

    def _extract_subcircuits(self, content: str) -> List[str]:
        """提取子电路定义名称"""
        pattern = r'\.subckt\s+(\w+)'
        return re.findall(pattern, content, re.IGNORECASE)

    # ============================================================
    # 拓扑排序
    # ============================================================

    def _topological_sort(self, graph: DependencyGraph) -> List[str]:
        """
        拓扑排序依赖图
        
        返回从叶子节点到根节点的顺序（依赖优先）
        """
        visited: Set[str] = set()
        order: List[str] = []
        
        def visit(path: str):
            if path in visited:
                return
            visited.add(path)
            
            node = graph.nodes.get(path)
            if node:
                for dep in node.dependencies:
                    visit(dep)
            
            order.append(path)
        
        # 从根节点开始
        visit(graph.root)
        
        return order


    # ============================================================
    # 依赖获取
    # ============================================================

    def get_all_dependencies(self, main_file: str) -> List[str]:
        """
        获取所有依赖文件（递归）
        
        Args:
            main_file: 主电路文件路径
            
        Returns:
            List[str]: 所有依赖文件路径
        """
        graph = self.build_dependency_graph(main_file)
        # 排除主文件本身
        return [p for p in graph.order if p != main_file]

    def get_dependency_order(self, main_file: str) -> List[str]:
        """
        获取拓扑排序后的依赖顺序
        
        Args:
            main_file: 主电路文件路径
            
        Returns:
            List[str]: 拓扑排序后的文件路径列表
        """
        graph = self.build_dependency_graph(main_file)
        return graph.order

    def get_dependency_content(
        self,
        main_file: str,
        max_depth: int = 3,
        project_path: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """
        按深度获取依赖文件内容
        
        上下文注入优先级：
        - 直接依赖（深度 1）：完整内容注入
        - 间接依赖（深度 2-3）：仅注入 .subckt 定义部分
        - 深层依赖（深度 4+）：仅记录文件名，不注入内容
        
        Args:
            main_file: 主电路文件路径
            max_depth: 最大深度
            project_path: 项目路径（用于计算相对路径）
            
        Returns:
            List[Dict]: 依赖内容列表
        """
        graph = self.build_dependency_graph(main_file)
        results = []
        
        project_dir = Path(project_path) if project_path else Path(main_file).parent
        
        for path, node in graph.nodes.items():
            if path == main_file:
                continue  # 跳过主文件
            
            # 计算相对路径
            try:
                rel_path = str(Path(path).relative_to(project_dir))
            except ValueError:
                rel_path = path
            
            if node.depth <= 1:
                # 直接依赖：完整内容
                results.append({
                    "path": rel_path,
                    "content": node.content or "",
                    "depth": node.depth,
                    "subcircuits": node.subcircuits,
                })
            elif node.depth <= max_depth:
                # 间接依赖：仅 .subckt 定义
                subckt_content = self._extract_subckt_definitions(node.content or "")
                results.append({
                    "path": rel_path,
                    "content": subckt_content,
                    "depth": node.depth,
                    "subcircuits": node.subcircuits,
                })
            else:
                # 深层依赖：仅文件名
                results.append({
                    "path": rel_path,
                    "content": f"* File: {rel_path}\n* Subcircuits: {', '.join(node.subcircuits)}",
                    "depth": node.depth,
                    "subcircuits": node.subcircuits,
                })
        
        return results

    def _extract_subckt_definitions(self, content: str) -> str:
        """提取 .subckt 定义部分"""
        lines = content.split('\n')
        result_lines = []
        in_subckt = False
        
        for line in lines:
            line_lower = line.strip().lower()
            
            if line_lower.startswith('.subckt'):
                in_subckt = True
            
            if in_subckt:
                result_lines.append(line)
            
            if line_lower.startswith('.ends'):
                in_subckt = False
                result_lines.append('')  # 空行分隔
        
        return '\n'.join(result_lines)


    # ============================================================
    # 缓存管理
    # ============================================================

    def invalidate_cache(self, file_path: str):
        """
        文件变更时失效缓存
        
        Args:
            file_path: 变更的文件路径
        """
        # 直接失效该文件的缓存
        if file_path in self._cache:
            del self._cache[file_path]
        
        # 失效所有依赖该文件的缓存
        to_remove = []
        for main_file, (_, graph) in self._cache.items():
            if file_path in graph.nodes:
                to_remove.append(main_file)
        
        for main_file in to_remove:
            del self._cache[main_file]
        
        if self.logger and to_remove:
            self.logger.debug(
                f"Invalidated {len(to_remove) + 1} cache entries for {file_path}"
            )

    def clear_cache(self):
        """清除所有缓存"""
        self._cache.clear()

    # ============================================================
    # 文件名关联
    # ============================================================

    def get_associated_files(
        self,
        circuit_file: str,
        project_path: str,
    ) -> Dict[str, Optional[str]]:
        """
        获取关联文件
        
        文件名关联规则：
        - xxx.cir 自动关联 xxx_sim.json（仿真结果）
        - xxx.cir 自动关联 xxx_goals.json（设计目标）
        
        Args:
            circuit_file: 电路文件路径
            project_path: 项目路径
            
        Returns:
            Dict: 关联文件字典
        """
        circuit_path = Path(circuit_file)
        project_dir = Path(project_path)
        base_name = circuit_path.stem
        
        associated = {
            "simulation_result": None,
            "design_goals": None,
        }
        
        # 查找仿真结果
        sim_patterns = [
            project_dir / "simulation_results" / f"{base_name}_sim.json",
            project_dir / "simulation_results" / f"{base_name}.json",
        ]
        for sim_path in sim_patterns:
            if sim_path.exists():
                associated["simulation_result"] = str(sim_path)
                break
        
        # 查找设计目标
        goals_patterns = [
            project_dir / ".circuit_ai" / f"{base_name}_goals.json",
            project_dir / ".circuit_ai" / "design_goals.json",
        ]
        for goals_path in goals_patterns:
            if goals_path.exists():
                associated["design_goals"] = str(goals_path)
                break
        
        return associated


__all__ = [
    "DependencyAnalyzer",
    "DependencyGraph",
    "DependencyNode",
    "MAX_DEPTH",
]
