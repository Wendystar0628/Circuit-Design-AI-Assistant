# File Search Service - Unified File Search Entry
"""
文件搜索服务门面类

职责：
- 提供统一的实时文件搜索入口（不依赖向量索引）
- 支持按文件名、内容、符号搜索
- 维护文件名索引缓存，支持增量更新

初始化顺序：
- Phase 3 延迟初始化，依赖 FileManager、Logger
- 注册到 ServiceLocator

使用示例：
    from shared.service_locator import ServiceLocator
    from shared.service_names import SVC_FILE_SEARCH_SERVICE
    
    search_service = ServiceLocator.get(SVC_FILE_SEARCH_SERVICE)
    
    # 按文件名搜索
    results = search_service.search_by_name("opamp", fuzzy=True)
    
    # 按内容搜索
    results = search_service.search_by_content("SUBCKT", file_types=[".cir"])
    
    # 主搜索入口
    results = search_service.search_files("opamp", options)
"""

import fnmatch
import re
import threading
import time
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Set, Union

from infrastructure.file_intelligence.models.search_result import (
    SearchMatch,
    SearchOptions,
    SearchResult,
    SearchType,
)


# ============================================================
# 文件名索引缓存
# ============================================================

class FileNameIndex:
    """
    文件名索引缓存
    
    在项目打开时构建，支持增量更新。
    用于加速文件名搜索。
    """
    
    def __init__(self):
        # 文件路径集合：{relative_path: absolute_path}
        self._files: Dict[str, str] = {}
        # 文件名到路径的映射：{file_name: [relative_paths]}
        self._name_index: Dict[str, List[str]] = {}
        # 索引构建时间
        self._build_time: float = 0.0
        # 线程锁
        self._lock = threading.Lock()
        # 是否已构建
        self._built = False
    
    def build(
        self,
        work_dir: Path,
        exclude_patterns: List[str] = None
    ) -> int:
        """
        构建文件名索引
        
        Args:
            work_dir: 工作目录
            exclude_patterns: 排除的路径模式
            
        Returns:
            int: 索引的文件数量
        """
        if exclude_patterns is None:
            exclude_patterns = ["__pycache__", ".git", ".circuit_ai/temp"]
        
        with self._lock:
            self._files.clear()
            self._name_index.clear()
            
            start_time = time.time()
            
            for path in work_dir.rglob("*"):
                if not path.is_file():
                    continue
                
                # 检查是否应该排除
                relative = str(path.relative_to(work_dir))
                if self._should_exclude(relative, exclude_patterns):
                    continue
                
                # 添加到索引
                self._add_file(relative, str(path))
            
            self._build_time = time.time() - start_time
            self._built = True
            
            return len(self._files)
    
    def _should_exclude(self, path: str, patterns: List[str]) -> bool:
        """检查路径是否应该排除"""
        for pattern in patterns:
            if pattern in path:
                return True
        return False
    
    def _add_file(self, relative_path: str, absolute_path: str) -> None:
        """添加文件到索引"""
        self._files[relative_path] = absolute_path
        
        file_name = Path(relative_path).name.lower()
        if file_name not in self._name_index:
            self._name_index[file_name] = []
        self._name_index[file_name].append(relative_path)
    
    def add_file(self, relative_path: str, absolute_path: str) -> None:
        """增量添加文件"""
        with self._lock:
            self._add_file(relative_path, absolute_path)
    
    def remove_file(self, relative_path: str) -> None:
        """增量删除文件"""
        with self._lock:
            if relative_path in self._files:
                del self._files[relative_path]
                
                file_name = Path(relative_path).name.lower()
                if file_name in self._name_index:
                    try:
                        self._name_index[file_name].remove(relative_path)
                        if not self._name_index[file_name]:
                            del self._name_index[file_name]
                    except ValueError:
                        pass
    
    def update_file(self, relative_path: str, absolute_path: str) -> None:
        """更新文件（先删后加）"""
        self.remove_file(relative_path)
        self.add_file(relative_path, absolute_path)
    
    def search_by_name(
        self,
        query: str,
        fuzzy: bool = False,
        fuzzy_threshold: float = 0.6,
        max_results: int = 50
    ) -> List[tuple]:
        """
        按文件名搜索
        
        Args:
            query: 搜索查询
            fuzzy: 是否模糊匹配
            fuzzy_threshold: 模糊匹配阈值
            max_results: 最大结果数
            
        Returns:
            List[tuple]: [(relative_path, absolute_path, score), ...]
        """
        with self._lock:
            results = []
            query_lower = query.lower()
            
            for relative_path, absolute_path in self._files.items():
                file_name = Path(relative_path).name.lower()
                
                if fuzzy:
                    # 模糊匹配
                    score = SequenceMatcher(None, query_lower, file_name).ratio()
                    if score >= fuzzy_threshold:
                        results.append((relative_path, absolute_path, score))
                else:
                    # 精确匹配（包含查询字符串）
                    if query_lower in file_name:
                        # 计算匹配分数：完全匹配 > 前缀匹配 > 包含匹配
                        if file_name == query_lower:
                            score = 1.0
                        elif file_name.startswith(query_lower):
                            score = 0.9
                        else:
                            score = 0.7
                        results.append((relative_path, absolute_path, score))
            
            # 按分数排序
            results.sort(key=lambda x: x[2], reverse=True)
            
            return results[:max_results]
    
    def get_all_files(self) -> Dict[str, str]:
        """获取所有文件"""
        with self._lock:
            return self._files.copy()
    
    @property
    def file_count(self) -> int:
        """获取文件数量"""
        with self._lock:
            return len(self._files)
    
    @property
    def is_built(self) -> bool:
        """是否已构建索引"""
        return self._built
    
    @property
    def build_time_ms(self) -> float:
        """索引构建时间（毫秒）"""
        return self._build_time * 1000


# ============================================================
# 文件搜索服务
# ============================================================

class FileSearchService:
    """
    文件搜索服务门面类
    
    提供统一的实时文件搜索入口，支持：
    - 按文件名搜索（支持模糊匹配）
    - 按内容搜索
    - 按符号搜索（委托给 file_analyzer）
    
    性能优化：
    - 文件名索引缓存（项目打开时构建）
    - 增量更新索引（文件变更时）
    - 大文件跳过内容搜索（>1MB）
    """
    
    # 大文件阈值（字节）
    LARGE_FILE_THRESHOLD = 1024 * 1024  # 1MB
    
    # 默认排除模式
    DEFAULT_EXCLUDE_PATTERNS = [
        "__pycache__", ".git", ".circuit_ai/temp", "node_modules",
        ".pytest_cache", ".mypy_cache", "*.pyc", "*.pyo"
    ]
    
    def __init__(self):
        """初始化文件搜索服务"""
        # 文件名索引
        self._file_index = FileNameIndex()
        
        # 延迟获取的服务
        self._file_manager = None
        self._event_bus = None
        self._logger = None
        
        # 事件订阅状态
        self._subscribed = False
    
    # ============================================================
    # 延迟获取服务
    # ============================================================
    
    @property
    def file_manager(self):
        """延迟获取文件管理器"""
        if self._file_manager is None:
            try:
                from shared.service_locator import ServiceLocator
                from shared.service_names import SVC_FILE_MANAGER
                self._file_manager = ServiceLocator.get_optional(SVC_FILE_MANAGER)
            except Exception:
                pass
        return self._file_manager
    
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
                self._logger = get_logger("file_search_service")
            except Exception:
                pass
        return self._logger
    
    # ============================================================
    # 索引管理
    # ============================================================
    
    def build_index(self, work_dir: Union[str, Path] = None) -> int:
        """
        构建文件名索引
        
        Args:
            work_dir: 工作目录，默认从 FileManager 获取
            
        Returns:
            int: 索引的文件数量
        """
        if work_dir is None:
            if self.file_manager is not None:
                work_dir = self.file_manager.get_work_dir()
            if work_dir is None:
                if self.logger:
                    self.logger.warning("无法构建索引：工作目录未设置")
                return 0
        
        work_dir = Path(work_dir)
        
        if self.logger:
            self.logger.info(f"开始构建文件索引: {work_dir}")
        
        count = self._file_index.build(work_dir, self.DEFAULT_EXCLUDE_PATTERNS)
        
        if self.logger:
            self.logger.info(
                f"文件索引构建完成: {count} 个文件, "
                f"耗时 {self._file_index.build_time_ms:.0f}ms"
            )
        
        # 订阅文件变更事件
        self._subscribe_file_events()
        
        return count
    
    def _subscribe_file_events(self) -> None:
        """订阅文件变更事件，用于增量更新索引"""
        if self._subscribed or self.event_bus is None:
            return
        
        try:
            from shared.event_types import EVENT_FILE_CHANGED
            self.event_bus.subscribe(EVENT_FILE_CHANGED, self._on_file_changed)
            self._subscribed = True
            
            if self.logger:
                self.logger.debug("已订阅文件变更事件")
        except Exception as e:
            if self.logger:
                self.logger.warning(f"订阅文件变更事件失败: {e}")
    
    def _on_file_changed(self, event_data: Dict[str, Any]) -> None:
        """处理文件变更事件"""
        data = event_data.get("data", {})
        path = data.get("path", "")
        operation = data.get("operation", "")
        
        if not path:
            return
        
        # 获取相对路径
        if self.file_manager is not None:
            relative_path = self.file_manager.to_relative_path(path)
        else:
            relative_path = path
        
        # 更新索引
        if operation == "create":
            self._file_index.add_file(relative_path, path)
        elif operation == "delete":
            self._file_index.remove_file(relative_path)
        elif operation == "update":
            self._file_index.update_file(relative_path, path)
    
    # ============================================================
    # 主搜索入口
    # ============================================================
    
    def search_files(
        self,
        query: str,
        options: SearchOptions = None
    ) -> List[SearchResult]:
        """
        主搜索入口
        
        Args:
            query: 搜索查询
            options: 搜索选项
            
        Returns:
            List[SearchResult]: 搜索结果列表
        """
        if options is None:
            options = SearchOptions(query=query)
        else:
            options.query = query
        
        if options.search_type == SearchType.NAME:
            return self.search_by_name(
                query,
                fuzzy=options.fuzzy_threshold < 1.0,
                fuzzy_threshold=options.fuzzy_threshold,
                file_types=options.file_types,
                max_results=options.max_results,
            )
        elif options.search_type == SearchType.CONTENT:
            return self.search_by_content(
                query,
                file_types=options.file_types,
                case_sensitive=options.case_sensitive,
                max_results=options.max_results,
            )
        elif options.search_type == SearchType.SYMBOL:
            return self.search_symbols(
                query,
                file_types=options.file_types,
                max_results=options.max_results,
            )
        else:
            return []
    
    # ============================================================
    # 按文件名搜索
    # ============================================================
    
    def search_by_name(
        self,
        pattern: str,
        fuzzy: bool = False,
        fuzzy_threshold: float = 0.6,
        file_types: List[str] = None,
        max_results: int = 50
    ) -> List[SearchResult]:
        """
        按文件名搜索
        
        Args:
            pattern: 搜索模式
            fuzzy: 是否模糊匹配
            fuzzy_threshold: 模糊匹配阈值
            file_types: 限定文件类型
            max_results: 最大结果数
            
        Returns:
            List[SearchResult]: 搜索结果列表
        """
        # 确保索引已构建
        if not self._file_index.is_built:
            self.build_index()
        
        # 从索引搜索
        matches = self._file_index.search_by_name(
            pattern,
            fuzzy=fuzzy,
            fuzzy_threshold=fuzzy_threshold,
            max_results=max_results * 2  # 多取一些，后面过滤
        )
        
        results = []
        for relative_path, absolute_path, score in matches:
            # 过滤文件类型
            if file_types:
                ext = Path(relative_path).suffix.lower()
                if ext not in [t.lower() for t in file_types]:
                    continue
            
            result = SearchResult.from_path(
                Path(absolute_path),
                relative_path,
                score=score
            )
            results.append(result)
            
            if len(results) >= max_results:
                break
        
        return results

    
    # ============================================================
    # 按内容搜索
    # ============================================================
    
    def search_by_content(
        self,
        query: str,
        file_types: List[str] = None,
        case_sensitive: bool = False,
        max_results: int = 50,
        context_lines: int = 2
    ) -> List[SearchResult]:
        """
        按内容搜索
        
        Args:
            query: 搜索查询
            file_types: 限定文件类型
            case_sensitive: 是否区分大小写
            max_results: 最大结果数
            context_lines: 上下文行数
            
        Returns:
            List[SearchResult]: 搜索结果列表
        """
        # 确保索引已构建
        if not self._file_index.is_built:
            self.build_index()
        
        results = []
        files = self._file_index.get_all_files()
        
        # 编译正则表达式
        flags = 0 if case_sensitive else re.IGNORECASE
        try:
            pattern = re.compile(re.escape(query), flags)
        except re.error:
            if self.logger:
                self.logger.warning(f"无效的搜索模式: {query}")
            return []
        
        for relative_path, absolute_path in files.items():
            # 过滤文件类型
            if file_types:
                ext = Path(relative_path).suffix.lower()
                if ext not in [t.lower() for t in file_types]:
                    continue
            
            # 跳过大文件
            try:
                file_size = Path(absolute_path).stat().st_size
                if file_size > self.LARGE_FILE_THRESHOLD:
                    continue
            except Exception:
                continue
            
            # 搜索文件内容
            matches = self._search_file_content(
                absolute_path,
                pattern,
                context_lines
            )
            
            if matches:
                # 计算分数：匹配数量越多分数越高
                score = min(1.0, len(matches) / 10.0)
                
                result = SearchResult.from_path(
                    Path(absolute_path),
                    relative_path,
                    score=score,
                    matches=matches
                )
                results.append(result)
                
                if len(results) >= max_results:
                    break
        
        # 按匹配数量排序
        results.sort(key=lambda r: r.match_count, reverse=True)
        
        return results
    
    def _search_file_content(
        self,
        file_path: str,
        pattern: re.Pattern,
        context_lines: int = 2
    ) -> List[SearchMatch]:
        """
        搜索单个文件的内容
        
        Args:
            file_path: 文件路径
            pattern: 编译后的正则表达式
            context_lines: 上下文行数
            
        Returns:
            List[SearchMatch]: 匹配列表
        """
        matches = []
        
        try:
            # 读取文件
            if self.file_manager is not None:
                content = self.file_manager.read_file(file_path)
            else:
                content = Path(file_path).read_text(encoding='utf-8')
            
            lines = content.split('\n')
            
            for i, line in enumerate(lines):
                for match in pattern.finditer(line):
                    # 获取上下文
                    start_ctx = max(0, i - context_lines)
                    end_ctx = min(len(lines), i + context_lines + 1)
                    
                    search_match = SearchMatch(
                        line_number=i + 1,
                        line_content=line,
                        match_start=match.start(),
                        match_end=match.end(),
                        context_before=lines[start_ctx:i],
                        context_after=lines[i + 1:end_ctx],
                    )
                    matches.append(search_match)
                    
                    # 限制每个文件的匹配数量
                    if len(matches) >= 100:
                        return matches
                        
        except Exception as e:
            if self.logger:
                self.logger.debug(f"搜索文件内容失败: {file_path} - {e}")
        
        return matches
    
    # ============================================================
    # 按符号搜索
    # ============================================================
    
    def search_symbols(
        self,
        symbol_name: str,
        symbol_type: str = None,
        file_types: List[str] = None,
        max_results: int = 50
    ) -> List[SearchResult]:
        """
        按符号搜索
        
        委托给 file_analyzer 实现（后续阶段实现）
        
        Args:
            symbol_name: 符号名称
            symbol_type: 符号类型（function/class/variable 等）
            file_types: 限定文件类型
            max_results: 最大结果数
            
        Returns:
            List[SearchResult]: 搜索结果列表
        """
        # TODO: 委托给 file_analyzer 实现
        # 当前使用内容搜索作为降级方案
        if self.logger:
            self.logger.debug(f"符号搜索降级为内容搜索: {symbol_name}")
        
        return self.search_by_content(
            symbol_name,
            file_types=file_types,
            max_results=max_results
        )
    
    # ============================================================
    # 便捷方法
    # ============================================================
    
    def find_file(self, file_name: str) -> Optional[SearchResult]:
        """
        查找单个文件（精确匹配文件名）
        
        Args:
            file_name: 文件名
            
        Returns:
            SearchResult: 搜索结果，未找到返回 None
        """
        results = self.search_by_name(file_name, fuzzy=False, max_results=1)
        
        # 检查是否精确匹配
        for result in results:
            if result.file_name.lower() == file_name.lower():
                return result
        
        return None
    
    def find_files_by_extension(
        self,
        extension: str,
        max_results: int = 100
    ) -> List[SearchResult]:
        """
        按扩展名查找文件
        
        Args:
            extension: 文件扩展名（如 ".cir"）
            max_results: 最大结果数
            
        Returns:
            List[SearchResult]: 搜索结果列表
        """
        if not extension.startswith("."):
            extension = "." + extension
        
        return self.search_by_name("", file_types=[extension], max_results=max_results)
    
    def get_index_stats(self) -> Dict[str, Any]:
        """
        获取索引统计信息
        
        Returns:
            Dict: 统计信息
        """
        return {
            "file_count": self._file_index.file_count,
            "is_built": self._file_index.is_built,
            "build_time_ms": self._file_index.build_time_ms,
        }


# ============================================================
# 模块导出
# ============================================================

__all__ = [
    "FileSearchService",
    "FileNameIndex",
]
