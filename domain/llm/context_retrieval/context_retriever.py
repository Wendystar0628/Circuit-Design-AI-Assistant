# Context Retriever - Facade for Context Retrieval
"""
上下文检索门面类 - 协调各子模块，提供统一的上下文检索入口

职责：
- 作为门面类协调各子模块
- 提供统一的上下文检索入口
- 综合检索相关上下文

协调流程：
1. 调用 ImplicitContextCollector.collect() 收集隐式上下文
2. 调用 DiagnosticsCollector.collect() 收集诊断信息
3. 调用 KeywordExtractor.extract() 提取关键词
4. 并行执行多路检索
5. 调用 RetrievalMerger.merge() 融合结果并截断

阶段依赖说明：
- 向量检索功能依赖阶段四的 vector_store
- 阶段三实现时，向量检索路径返回空结果
- 仅启用隐式上下文收集、关键词匹配和依赖分析

被调用方：prompt_builder.py
"""

import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

from domain.llm.context_retrieval.implicit_context_collector import (
    ImplicitContextCollector, ImplicitContext
)
from domain.llm.context_retrieval.diagnostics_collector import (
    DiagnosticsCollector, Diagnostics
)


# ============================================================
# 常量定义
# ============================================================

SPICE_EXTENSIONS = {".cir", ".sp", ".spice", ".lib", ".inc"}
WATCHED_EXTENSIONS = {".cir", ".sp", ".spice", ".lib", ".inc", ".json", ".txt", ".md"}
IGNORED_DIRS = {".circuit_ai", "__pycache__", ".git", "node_modules"}

SPICE_METRICS = {
    "gain", "bandwidth", "phase", "margin", "impedance", "resistance",
    "capacitance", "inductance", "frequency", "voltage", "current",
    "power", "noise", "distortion", "slew", "offset", "cmrr", "psrr",
}

DEVICE_PATTERNS = [
    r'\b[RCLQMD]\d+\b',
    r'\bV[a-zA-Z_]\w*\b',
    r'\b[A-Z][a-zA-Z_]\w*\b',
]



@dataclass
class RetrievalResult:
    """检索结果"""
    path: str
    content: str
    relevance: float
    source: str  # "keyword" | "vector" | "dependency" | "implicit"
    token_count: int
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "path": self.path,
            "content": self.content,
            "relevance": self.relevance,
            "source": self.source,
            "token_count": self.token_count,
        }


@dataclass
class RetrievalContext:
    """完整的检索上下文"""
    implicit_context: Optional[ImplicitContext] = None
    diagnostics: Optional[Diagnostics] = None
    retrieval_results: List[RetrievalResult] = None
    
    def __post_init__(self):
        if self.retrieval_results is None:
            self.retrieval_results = []


class ContextRetriever:
    """
    上下文检索门面类
    
    协调各子模块，提供统一的上下文检索入口。
    """

    def __init__(self):
        self._implicit_collector = ImplicitContextCollector()
        self._diagnostics_collector = DiagnosticsCollector()
        self._vector_store = None
        self._app_state = None
        self._logger = None

    # ============================================================
    # 服务获取
    # ============================================================

    @property
    def vector_store(self):
        if self._vector_store is None:
            try:
                from shared.service_locator import ServiceLocator
                from shared.service_names import SVC_VECTOR_STORE
                self._vector_store = ServiceLocator.get_optional(SVC_VECTOR_STORE)
            except Exception:
                pass
        return self._vector_store

    @property
    def app_state(self):
        if self._app_state is None:
            try:
                from shared.service_locator import ServiceLocator
                from shared.service_names import SVC_APP_STATE
                self._app_state = ServiceLocator.get_optional(SVC_APP_STATE)
            except Exception:
                pass
        return self._app_state

    @property
    def logger(self):
        if self._logger is None:
            try:
                from infrastructure.utils.logger import get_logger
                self._logger = get_logger("context_retriever")
            except Exception:
                pass
        return self._logger


    # ============================================================
    # 主入口
    # ============================================================

    def retrieve(
        self,
        message: str,
        project_path: str,
        token_budget: int = 2000,
        main_file: Optional[str] = None,
    ) -> RetrievalContext:
        """
        综合检索相关上下文
        
        Args:
            message: 用户消息
            project_path: 项目路径
            token_budget: Token 预算
            main_file: 当前主文件路径
            
        Returns:
            RetrievalContext: 完整的检索上下文
        """
        if self.logger:
            self.logger.debug(f"Retrieving context for: {message[:50]}...")
        
        context = RetrievalContext()
        
        # 1. 收集隐式上下文
        context.implicit_context = self._implicit_collector.collect(project_path)
        
        # 确定当前电路文件
        circuit_file = main_file
        if not circuit_file and context.implicit_context.current_circuit:
            circuit_file = str(
                Path(project_path) / context.implicit_context.current_circuit["path"]
            )
        
        # 2. 收集诊断信息
        context.diagnostics = self._diagnostics_collector.collect(
            project_path, circuit_file
        )
        
        # 3. 提取关键词
        keywords = self._extract_keywords(message)
        
        # 4. 多路检索
        all_results: List[RetrievalResult] = []
        
        # 关键词检索
        keyword_results = self._retrieve_by_keywords(keywords, project_path)
        all_results.extend(keyword_results)
        
        # 向量检索（阶段四启用）
        if self._is_vector_search_enabled():
            vector_results = self._retrieve_by_vector(message, top_k=10)
            all_results.extend(vector_results)
        
        # 依赖分析
        if circuit_file:
            dep_results = self._retrieve_by_dependency(circuit_file, project_path)
            all_results.extend(dep_results)
        
        # 5. 融合结果
        context.retrieval_results = self._merge_results(all_results, token_budget)
        
        if self.logger:
            self.logger.info(
                f"Retrieved {len(context.retrieval_results)} results "
                f"(budget: {token_budget} tokens)"
            )
        
        return context

    def _is_vector_search_enabled(self) -> bool:
        """检查向量检索是否启用"""
        if self.vector_store is None:
            return False
        if self.app_state:
            return getattr(self.app_state, "rag_enabled", False)
        return False


    # ============================================================
    # 关键词提取
    # ============================================================

    def _extract_keywords(self, message: str) -> Dict[str, Set[str]]:
        """从用户消息中提取关键词"""
        keywords = {
            "devices": set(),
            "nodes": set(),
            "files": set(),
            "subcircuits": set(),
            "metrics": set(),
            "identifiers": set(),
        }
        
        for pattern in DEVICE_PATTERNS:
            matches = re.findall(pattern, message, re.IGNORECASE)
            keywords["devices"].update(m.upper() for m in matches)
        
        file_matches = re.findall(r'\b\w+\.(cir|sp|spice|lib|inc)\b', message, re.IGNORECASE)
        keywords["files"].update(file_matches)
        
        subckt_matches = re.findall(r'\.subckt\s+(\w+)', message, re.IGNORECASE)
        keywords["subcircuits"].update(subckt_matches)
        
        words = set(re.findall(r'\b\w+\b', message.lower()))
        keywords["metrics"] = words & SPICE_METRICS
        
        identifiers = re.findall(r'\b[A-Z][a-zA-Z0-9_]+\b', message)
        keywords["identifiers"].update(identifiers)
        
        return keywords

    # ============================================================
    # 关键词检索
    # ============================================================

    def _retrieve_by_keywords(
        self,
        keywords: Dict[str, Set[str]],
        project_path: str,
    ) -> List[RetrievalResult]:
        """精确匹配检索"""
        results = []
        
        all_keywords = set()
        for kw_set in keywords.values():
            all_keywords.update(kw_set)
        
        if not all_keywords:
            return results
        
        project_dir = Path(project_path)
        if not project_dir.exists():
            return results
        
        for file_path in self._iter_project_files(project_dir):
            try:
                content = file_path.read_text(encoding="utf-8", errors="ignore")
                
                match_count = 0
                for kw in all_keywords:
                    if kw.lower() in content.lower():
                        match_count += 1
                
                if match_count > 0:
                    relevance = min(match_count / len(all_keywords), 1.0)
                    rel_path = str(file_path.relative_to(project_dir))
                    
                    results.append(RetrievalResult(
                        path=rel_path,
                        content=content,
                        relevance=relevance,
                        source="keyword",
                        token_count=self._estimate_tokens(content),
                    ))
            except Exception as e:
                if self.logger:
                    self.logger.debug(f"Error reading {file_path}: {e}")
        
        return results

    def _iter_project_files(self, project_dir: Path):
        """遍历项目文件"""
        for root, dirs, files in os.walk(project_dir):
            dirs[:] = [d for d in dirs if d not in IGNORED_DIRS]
            for file in files:
                file_path = Path(root) / file
                if file_path.suffix.lower() in WATCHED_EXTENSIONS:
                    yield file_path


    # ============================================================
    # 向量检索（阶段四启用）
    # ============================================================

    def _retrieve_by_vector(
        self,
        query: str,
        top_k: int = 10,
    ) -> List[RetrievalResult]:
        """向量语义检索（阶段四启用）"""
        if self.vector_store is None:
            return []
        
        try:
            results = self.vector_store.search(query, top_k=top_k)
            return [
                RetrievalResult(
                    path=r.get("path", ""),
                    content=r.get("content", ""),
                    relevance=r.get("score", 0.0),
                    source="vector",
                    token_count=self._estimate_tokens(r.get("content", "")),
                )
                for r in results
            ]
        except Exception as e:
            if self.logger:
                self.logger.warning(f"Vector search failed: {e}")
            return []

    # ============================================================
    # 依赖分析检索
    # ============================================================

    def _retrieve_by_dependency(
        self,
        main_file: str,
        project_path: str,
    ) -> List[RetrievalResult]:
        """依赖分析检索"""
        results = []
        main_path = Path(main_file)
        
        if not main_path.exists():
            return results
        
        try:
            content = main_path.read_text(encoding="utf-8", errors="ignore")
            
            include_pattern = r'\.include\s+["\']?([^"\'\s]+)["\']?'
            includes = re.findall(include_pattern, content, re.IGNORECASE)
            
            lib_pattern = r'\.lib\s+["\']?([^"\'\s]+)["\']?'
            libs = re.findall(lib_pattern, content, re.IGNORECASE)
            
            dependencies = set(includes + libs)
            project_dir = Path(project_path)
            main_dir = main_path.parent
            
            for dep in dependencies:
                dep_path = main_dir / dep
                if not dep_path.exists():
                    dep_path = project_dir / dep
                
                if dep_path.exists():
                    try:
                        dep_content = dep_path.read_text(encoding="utf-8", errors="ignore")
                        rel_path = str(dep_path.relative_to(project_dir))
                        
                        results.append(RetrievalResult(
                            path=rel_path,
                            content=dep_content,
                            relevance=0.9,
                            source="dependency",
                            token_count=self._estimate_tokens(dep_content),
                        ))
                    except Exception as e:
                        if self.logger:
                            self.logger.debug(f"Error reading dependency {dep_path}: {e}")
        except Exception as e:
            if self.logger:
                self.logger.warning(f"Dependency analysis failed: {e}")
        
        return results


    # ============================================================
    # 结果融合
    # ============================================================

    def _merge_results(
        self,
        results: List[RetrievalResult],
        token_budget: int,
    ) -> List[RetrievalResult]:
        """
        融合多路结果并排序
        
        使用 RRF（Reciprocal Rank Fusion）算法融合多路检索结果。
        """
        if not results:
            return []
        
        # 按来源分组
        by_source: Dict[str, List[RetrievalResult]] = {}
        for r in results:
            if r.source not in by_source:
                by_source[r.source] = []
            by_source[r.source].append(r)
        
        # 对每组按相关度排序
        for source in by_source:
            by_source[source].sort(key=lambda x: x.relevance, reverse=True)
        
        # 计算 RRF 分数
        k = 60
        rrf_scores: Dict[str, float] = {}
        path_to_result: Dict[str, RetrievalResult] = {}
        
        for source, source_results in by_source.items():
            for rank, result in enumerate(source_results, start=1):
                path = result.path
                rrf_score = 1.0 / (k + rank)
                rrf_scores[path] = rrf_scores.get(path, 0) + rrf_score
                
                if path not in path_to_result or result.relevance > path_to_result[path].relevance:
                    path_to_result[path] = result
        
        # 按 RRF 分数排序
        sorted_paths = sorted(rrf_scores.keys(), key=lambda p: rrf_scores[p], reverse=True)
        
        # 按 Token 预算截断
        final_results = []
        total_tokens = 0
        
        for path in sorted_paths:
            result = path_to_result[path]
            
            if total_tokens + result.token_count <= token_budget:
                max_rrf = max(rrf_scores.values()) if rrf_scores else 1.0
                result.relevance = rrf_scores[path] / max_rrf
                final_results.append(result)
                total_tokens += result.token_count
            else:
                break
        
        return final_results

    def _estimate_tokens(self, text: str) -> int:
        """
        估算文本的 Token 数
        
        优先使用 token_counter 模块的精确计算，
        若不可用则回退到简单估算。
        """
        if not text:
            return 0
        
        try:
            from domain.llm.token_counter import count_tokens
            return count_tokens(text)
        except ImportError:
            # 回退到简单估算
            return len(text) // 4

    # ============================================================
    # 便捷方法
    # ============================================================

    def collect_implicit_context(self, project_path: str) -> Dict[str, Any]:
        """收集隐式上下文（兼容旧接口）"""
        context = self._implicit_collector.collect(project_path)
        return self._implicit_collector.to_dict(context)

    def collect_diagnostics(
        self,
        project_path: str,
        circuit_file: Optional[str] = None,
    ) -> Dict[str, Any]:
        """收集诊断信息（兼容旧接口）"""
        diagnostics = self._diagnostics_collector.collect(project_path, circuit_file)
        return self._diagnostics_collector.to_dict(diagnostics)

    def record_error(self, circuit_file: str, error: str):
        """记录错误到历史"""
        self._diagnostics_collector.record_error(circuit_file, error)

    def clear_error_history(self, circuit_file: str):
        """清除错误历史"""
        self._diagnostics_collector.clear_error_history(circuit_file)


__all__ = [
    "ContextRetriever",
    "RetrievalResult",
    "RetrievalContext",
    "SPICE_EXTENSIONS",
    "SPICE_METRICS",
]
