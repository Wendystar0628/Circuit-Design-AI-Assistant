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

依赖服务：AsyncFileOps
被调用方：context_retriever.py
"""

import asyncio
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple


# ============================================================
# 常量定义
# ============================================================

MAX_DEPTH = 5

INCLUDE_PATTERN = re.compile(r'\.include\s+["\']?([^"\'\s]+)["\']?', re.IGNORECASE)
LIB_PATTERN = re.compile(r'\.lib\s+["\']?([^"\'\s]+)["\']?(?:\s+(\w+))?', re.IGNORECASE)
MODEL_PATTERN = re.compile(r'\.model\s+(\w+)\s+(\w+)', re.IGNORECASE)
SUBCKT_START_PATTERN = re.compile(r'\.subckt\s+(\w+)', re.IGNORECASE)
SUBCKT_END_PATTERN = re.compile(r'\.ends', re.IGNORECASE)

SPICE_EXTENSIONS = {".cir", ".sp", ".spice", ".lib", ".inc", ".mod", ".sub"}


# ============================================================
# 数据类定义
# ============================================================

@dataclass
class DependencyNode:
    """依赖节点"""
    path: str
    depth: int
    dependencies: List[str] = field(default_factory=list)
    content: Optional[str] = None
    subcircuits: List[str] = field(default_factory=list)
    mtime: float = 0.0


@dataclass
class DependencyGraph:
    """依赖图"""
    root: str
    nodes: Dict[str, DependencyNode] = field(default_factory=dict)
    order: List[str] = field(default_factory=list)
    build_time: float = 0.0


# ============================================================
# 主类
# ============================================================

class DependencyAnalyzer:
    """
    电路依赖图分析器
    
    构建电路文件之间的依赖关系图，实现多文件感知的上下文构建。
    所有涉及文件 I/O 的方法均为 async def，通过 AsyncFileOps 执行。
    """

    _cache: Dict[str, DependencyGraph] = {}

    def __init__(self):
        self._event_bus = None
        self._async_file_ops = None
        self._logger = None
        self._subscribed = False

    # ============================================================
    # 服务获取（延迟加载）
    # ============================================================

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
    def async_file_ops(self):
        if self._async_file_ops is None:
            try:
                from shared.service_locator import ServiceLocator
                from shared.service_names import SVC_ASYNC_FILE_OPS
                self._async_file_ops = ServiceLocator.get_optional(SVC_ASYNC_FILE_OPS)
            except Exception:
                pass
            if self._async_file_ops is None:
                try:
                    from infrastructure.persistence.async_file_ops import AsyncFileOps
                    self._async_file_ops = AsyncFileOps()
                except Exception:
                    pass
        return self._async_file_ops

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
        if self._subscribed or self.event_bus is None:
            return
        try:
            from shared.event_types import EVENT_FILE_CHANGED
            self.event_bus.subscribe(EVENT_FILE_CHANGED, self._on_file_changed)
            self._subscribed = True
        except Exception:
            pass

    def _on_file_changed(self, event_data: Dict[str, Any]):
        # 事件数据在 "data" 字段中
        data = event_data.get("data", event_data)
        path = data.get("path", "")
        if path:
            self.invalidate_cache(path)

    # ============================================================
    # 异步主入口
    # ============================================================

    async def build_dependency_graph_async(
        self,
        main_file: str,
        project_path: Optional[str] = None,
    ) -> DependencyGraph:
        """异步构建依赖图"""
        self._subscribe_events()
        
        main_path = Path(main_file)
        if not main_path.exists():
            return DependencyGraph(root=main_file)
        
        cached = self._cache.get(main_file)
        if cached and await self._is_cache_valid_async(cached):
            return cached
        
        import time
        graph = DependencyGraph(root=main_file, build_time=time.time())
        visited: Set[str] = set()
        
        await self._build_recursive_async(main_path, graph, visited, depth=0)
        graph.order = self._topological_sort(graph)
        self._cache[main_file] = graph
        
        if self.logger:
            self.logger.debug(f"Built dependency graph for {main_file}: {len(graph.nodes)} nodes")
        
        return graph

    async def _is_cache_valid_async(self, graph: DependencyGraph) -> bool:
        for path, node in graph.nodes.items():
            try:
                file_path = Path(path)
                if not file_path.exists():
                    return False
                if file_path.stat().st_mtime > node.mtime:
                    return False
            except Exception:
                return False
        return True

    async def _build_recursive_async(
        self,
        file_path: Path,
        graph: DependencyGraph,
        visited: Set[str],
        depth: int,
    ):
        path_str = str(file_path.resolve())
        
        if path_str in visited:
            if self.logger:
                self.logger.warning(f"Circular dependency detected: {path_str}")
            return
        
        if depth > MAX_DEPTH:
            if self.logger:
                self.logger.debug(f"Max depth reached for: {path_str}")
            return
        
        visited.add(path_str)
        
        try:
            mtime = file_path.stat().st_mtime
        except Exception:
            mtime = 0.0
        
        node = DependencyNode(path=path_str, depth=depth, mtime=mtime)
        
        try:
            if self.async_file_ops:
                content = await self.async_file_ops.read_file_async(str(file_path))
            else:
                content = await asyncio.to_thread(
                    file_path.read_text, encoding="utf-8", errors="ignore"
                )
            
            node.content = content
            node.subcircuits = self._extract_subcircuits(content)
            node.dependencies = self._parse_dependencies(content, file_path.parent)
            
            for dep in node.dependencies:
                dep_path = Path(dep)
                if dep_path.exists():
                    await self._build_recursive_async(dep_path, graph, visited, depth + 1)
                    
        except Exception as e:
            if self.logger:
                self.logger.debug(f"Error parsing {path_str}: {e}")
        
        graph.nodes[path_str] = node

    # ============================================================
    # 依赖解析
    # ============================================================

    def _parse_dependencies(self, content: str, base_dir: Path) -> List[str]:
        dependencies = []
        
        for match in INCLUDE_PATTERN.finditer(content):
            dep_path = self._resolve_path(match.group(1), base_dir)
            if dep_path:
                dependencies.append(dep_path)
        
        for match in LIB_PATTERN.finditer(content):
            dep_path = self._resolve_path(match.group(1), base_dir)
            if dep_path:
                dependencies.append(dep_path)
        
        return dependencies

    def _resolve_path(self, path_str: str, base_dir: Path) -> Optional[str]:
        candidates = [
            base_dir / path_str,
            Path(path_str),
            base_dir / "subcircuits" / path_str,
            base_dir / "parameters" / path_str,
        ]
        for candidate in candidates:
            if candidate.exists():
                return str(candidate.resolve())
        return None

    def _extract_subcircuits(self, content: str) -> List[str]:
        return SUBCKT_START_PATTERN.findall(content)

    def _topological_sort(self, graph: DependencyGraph) -> List[str]:
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
        
        visit(graph.root)
        return order

    # ============================================================
    # 依赖获取（从缓存读取）
    # ============================================================

    def get_all_dependencies(self, main_file: str) -> List[str]:
        """获取所有依赖文件（需先调用 build_dependency_graph_async）"""
        graph = self._cache.get(main_file)
        if not graph:
            return []
        return [p for p in graph.order if p != main_file]

    def get_dependency_order(self, main_file: str) -> List[str]:
        """获取拓扑排序后的依赖顺序（从缓存读取）"""
        graph = self._cache.get(main_file)
        return graph.order if graph else []


    # ============================================================
    # 异步获取依赖内容
    # ============================================================

    async def get_dependency_content_async(
        self,
        main_file: str,
        project_path: Optional[str] = None,
        max_depth: int = 3,
    ) -> List[Dict[str, Any]]:
        """
        异步按深度获取依赖文件内容
        
        上下文注入优先级：
        - 直接依赖（深度 1）：完整内容注入
        - 间接依赖（深度 2-3）：仅注入 .subckt 定义部分
        - 深层依赖（深度 4+）：仅记录文件名，不注入内容
        """
        graph = await self.build_dependency_graph_async(main_file, project_path)
        
        results: List[Dict[str, Any]] = []
        project_dir = Path(project_path) if project_path else Path(main_file).parent
        
        for path, node in graph.nodes.items():
            if path == main_file:
                continue
            
            try:
                rel_path = str(Path(path).relative_to(project_dir))
            except ValueError:
                rel_path = path
            
            if node.depth <= 1:
                results.append({
                    "path": rel_path,
                    "content": node.content or "",
                    "depth": node.depth,
                    "subcircuits": node.subcircuits,
                    "mtime": node.mtime,
                })
            elif node.depth <= max_depth:
                subckt_content = self._extract_subckt_definitions(node.content or "")
                results.append({
                    "path": rel_path,
                    "content": subckt_content,
                    "depth": node.depth,
                    "subcircuits": node.subcircuits,
                    "mtime": node.mtime,
                })
            else:
                results.append({
                    "path": rel_path,
                    "content": f"* File: {rel_path}\n* Subcircuits: {', '.join(node.subcircuits)}",
                    "depth": node.depth,
                    "subcircuits": node.subcircuits,
                    "mtime": node.mtime,
                })
        
        results.sort(key=lambda x: x.get("mtime", 0), reverse=True)
        return results

    def _extract_subckt_definitions(self, content: str) -> str:
        lines = content.split('\n')
        result_lines = []
        in_subckt = False
        
        for line in lines:
            stripped = line.strip().lower()
            if SUBCKT_START_PATTERN.match(stripped):
                in_subckt = True
            if in_subckt:
                result_lines.append(line)
            if SUBCKT_END_PATTERN.match(stripped):
                in_subckt = False
                result_lines.append('')
        
        return '\n'.join(result_lines)

    # ============================================================
    # 关联文件获取
    # ============================================================

    async def get_associated_files_async(
        self,
        circuit_file: str,
        project_path: str,
    ) -> Dict[str, Optional[Tuple[str, float]]]:
        """
        异步获取关联文件
        
        文件名关联规则：
        - xxx.cir 自动关联 xxx_sim.json（仿真结果）
        - xxx.cir 自动关联 xxx_goals.json（设计目标）
        """
        circuit_path = Path(circuit_file)
        project_dir = Path(project_path)
        base_name = circuit_path.stem
        
        associated: Dict[str, Optional[Tuple[str, float]]] = {
            "simulation_result": None,
            "design_goals": None,
        }
        
        sim_patterns = [
            project_dir / "simulation_results" / f"{base_name}_sim.json",
            project_dir / "simulation_results" / f"{base_name}.json",
            project_dir / ".circuit_ai" / "sim_results" / f"{base_name}_sim.json",
            project_dir / ".circuit_ai" / "sim_results" / f"{base_name}.json",
        ]
        for sim_path in sim_patterns:
            if sim_path.exists():
                associated["simulation_result"] = (str(sim_path), sim_path.stat().st_mtime)
                break
        
        goals_patterns = [
            project_dir / ".circuit_ai" / f"{base_name}_goals.json",
            project_dir / ".circuit_ai" / "design_goals.json",
        ]
        for goals_path in goals_patterns:
            if goals_path.exists():
                associated["design_goals"] = (str(goals_path), goals_path.stat().st_mtime)
                break
        
        return associated

    # ============================================================
    # 缓存管理
    # ============================================================

    def invalidate_cache(self, file_path: str):
        resolved_path = str(Path(file_path).resolve()) if Path(file_path).exists() else file_path
        
        if resolved_path in self._cache:
            del self._cache[resolved_path]
        
        to_remove = [
            main_file for main_file, graph in self._cache.items()
            if resolved_path in graph.nodes
        ]
        for main_file in to_remove:
            del self._cache[main_file]
        
        if self.logger and to_remove:
            self.logger.debug(f"Invalidated {len(to_remove) + 1} cache entries for {file_path}")

    def clear_cache(self):
        self._cache.clear()


__all__ = [
    "DependencyAnalyzer",
    "DependencyGraph",
    "DependencyNode",
    "MAX_DEPTH",
    "SPICE_EXTENSIONS",
]
