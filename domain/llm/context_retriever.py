# Context Retriever - Intelligent Context Retrieval
"""
智能上下文检索器 - 根据用户消息自动检索工作区中相关的代码文件

职责：
- 从用户消息中提取关键词
- 多路检索相关代码（关键词匹配、向量语义、依赖分析）
- 融合排序并控制 Token 预算

阶段依赖说明：
- 向量检索功能依赖阶段四的 vector_store
- 阶段三实现时，向量检索路径返回空结果
- 仅启用关键词匹配和依赖分析
- 阶段四完成后，通过配置开关启用完整的混合检索能力

使用示例：
    from domain.llm.context_retriever import ContextRetriever
    
    retriever = ContextRetriever()
    results = retriever.retrieve(
        message="Help me design an inverting amplifier",
        project_path="/path/to/project",
        token_budget=2000
    )
"""

import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Set



# ============================================================
# 常量定义
# ============================================================

# SPICE 文件扩展名
SPICE_EXTENSIONS = {".cir", ".sp", ".spice", ".lib", ".inc"}

# 关注的文件扩展名
WATCHED_EXTENSIONS = {".cir", ".sp", ".spice", ".lib", ".inc", ".json", ".txt", ".md"}

# 忽略的目录
IGNORED_DIRS = {".circuit_ai", "__pycache__", ".git", "node_modules"}

# SPICE 指标词表
SPICE_METRICS = {
    "gain", "bandwidth", "phase", "margin", "impedance", "resistance",
    "capacitance", "inductance", "frequency", "voltage", "current",
    "power", "noise", "distortion", "slew", "offset", "cmrr", "psrr",
    "settling", "overshoot", "undershoot", "rise", "fall", "delay",
    "stability", "oscillation", "feedback", "loop", "pole", "zero",
}

# 器件名正则模式
DEVICE_PATTERNS = [
    r'\b[RCLQMD]\d+\b',           # R1, C2, L3, Q4, M5, D6
    r'\bV[a-zA-Z_]\w*\b',         # Vcc, Vdd, Vin
    r'\b[A-Z][a-zA-Z_]\w*\b',     # 大写开头的标识符
]

# 文件名正则模式
FILE_PATTERN = r'\b\w+\.(cir|sp|spice|lib|inc)\b'

# 子电路名正则模式
SUBCKT_PATTERN = r'\.subckt\s+(\w+)'


# ============================================================
# 数据结构
# ============================================================

@dataclass
class RetrievalResult:
    """检索结果"""
    path: str              # 文件相对路径
    content: str           # 文件内容或片段
    relevance: float       # 相关度评分（0-1）
    source: str            # 来源："keyword" | "vector" | "dependency" | "bm25"
    token_count: int       # 估算 token 数
    
    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            "path": self.path,
            "content": self.content,
            "relevance": self.relevance,
            "source": self.source,
            "token_count": self.token_count,
        }



# ============================================================
# 上下文检索器
# ============================================================

class ContextRetriever:
    """
    智能上下文检索器
    
    根据用户消息自动检索工作区中相关的代码文件，
    为 LLM 提供智能上下文补充。
    
    检索策略（Hybrid RAG）：
    - 路径A - 精确匹配：在工作区文件中 grep 搜索提取的关键词
    - 路径B - 向量语义检索：使用语义查询在向量库中检索（阶段四启用）
    - 路径C - BM25 关键词检索：基于 TF-IDF 的稀疏检索（阶段四启用）
    - 路径D - 依赖分析：解析当前 SPICE 文件的 .include 语句
    """

    def __init__(self):
        # 延迟获取的服务
        self._vector_store = None
        self._session_state = None
        self._logger = None

    # ============================================================
    # 服务获取
    # ============================================================

    @property
    def vector_store(self):
        """延迟获取向量存储"""
        if self._vector_store is None:
            try:
                from shared.service_locator import ServiceLocator
                from shared.service_names import SVC_VECTOR_STORE
                self._vector_store = ServiceLocator.get_optional(SVC_VECTOR_STORE)
            except Exception:
                pass
        return self._vector_store

    @property
    def session_state(self):
        """延迟获取会话状态（只读）"""
        if self._session_state is None:
            try:
                from shared.service_locator import ServiceLocator
                from shared.service_names import SVC_SESSION_STATE
                self._session_state = ServiceLocator.get_optional(SVC_SESSION_STATE)
            except Exception:
                pass
        return self._session_state

    @property
    def logger(self):
        """延迟获取日志器"""
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
    ) -> List[RetrievalResult]:
        """
        综合检索相关代码
        
        Args:
            message: 用户消息
            project_path: 项目路径
            token_budget: Token 预算
            main_file: 当前主文件路径（用于依赖分析）
            
        Returns:
            检索结果列表
        """
        if self.logger:
            self.logger.debug(f"Retrieving context for: {message[:50]}...")
        
        # 提取关键词
        keywords = self.extract_keywords(message)
        
        if self.logger:
            self.logger.debug(f"Extracted keywords: {keywords}")
        
        # 多路检索
        all_results: List[RetrievalResult] = []
        
        # 路径A - 精确匹配
        keyword_results = self.retrieve_by_keywords(keywords, project_path)
        all_results.extend(keyword_results)
        
        # 路径B - 向量语义检索（阶段四启用）
        if self._is_vector_search_enabled():
            vector_results = self.retrieve_by_vector(message, top_k=10)
            all_results.extend(vector_results)
        
        # 路径D - 依赖分析
        if main_file:
            dependency_results = self.retrieve_by_dependency(main_file, project_path)
            all_results.extend(dependency_results)
        
        # 融合排序
        merged_results = self.merge_and_rank(all_results, token_budget)
        
        if self.logger:
            self.logger.info(
                f"Retrieved {len(merged_results)} results "
                f"(budget: {token_budget} tokens)"
            )
        
        return merged_results

    def _is_vector_search_enabled(self) -> bool:
        """检查向量检索是否启用"""
        # 检查向量存储是否可用
        if self.vector_store is None:
            return False
        
        # TODO: 检查 RAG 开关（从配置或 SessionState 获取）
        # 目前默认返回 False，待 RAG 功能完善后启用
        return False


    # ============================================================
    # 关键词提取
    # ============================================================

    def extract_keywords(self, message: str) -> Dict[str, Set[str]]:
        """
        从用户消息中提取关键词
        
        针对 SPICE 领域优化，提取：
        - 器件名（R1, C2, Q3 等）
        - 节点名（Vcc, Vdd, Vin 等）
        - 文件名（*.cir, *.sp 等）
        - 子电路名
        - 指标词（gain, bandwidth 等）
        
        Args:
            message: 用户消息
            
        Returns:
            分类的关键词字典
        """
        keywords = {
            "devices": set(),      # 器件名
            "nodes": set(),        # 节点名
            "files": set(),        # 文件名
            "subcircuits": set(),  # 子电路名
            "metrics": set(),      # 指标词
            "identifiers": set(),  # 其他标识符
        }
        
        # 提取器件名
        for pattern in DEVICE_PATTERNS:
            matches = re.findall(pattern, message, re.IGNORECASE)
            keywords["devices"].update(m.upper() for m in matches)
        
        # 提取文件名
        file_matches = re.findall(FILE_PATTERN, message, re.IGNORECASE)
        keywords["files"].update(file_matches)
        
        # 提取子电路名
        subckt_matches = re.findall(SUBCKT_PATTERN, message, re.IGNORECASE)
        keywords["subcircuits"].update(subckt_matches)
        
        # 提取指标词
        words = set(re.findall(r'\b\w+\b', message.lower()))
        keywords["metrics"] = words & SPICE_METRICS
        
        # 提取其他标识符（大写开头的词）
        identifiers = re.findall(r'\b[A-Z][a-zA-Z0-9_]+\b', message)
        keywords["identifiers"].update(identifiers)
        
        return keywords

    # ============================================================
    # 精确匹配检索
    # ============================================================

    def retrieve_by_keywords(
        self,
        keywords: Dict[str, Set[str]],
        project_path: str,
    ) -> List[RetrievalResult]:
        """
        精确匹配检索
        
        在工作区文件中搜索提取的关键词。
        
        Args:
            keywords: 分类的关键词字典
            project_path: 项目路径
            
        Returns:
            检索结果列表
        """
        results = []
        
        # 合并所有关键词
        all_keywords = set()
        for kw_set in keywords.values():
            all_keywords.update(kw_set)
        
        if not all_keywords:
            return results
        
        # 遍历项目文件
        project_dir = Path(project_path)
        if not project_dir.exists():
            return results
        
        for file_path in self._iter_project_files(project_dir):
            try:
                content = file_path.read_text(encoding="utf-8", errors="ignore")
                
                # 计算匹配度
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
            # 过滤忽略的目录
            dirs[:] = [d for d in dirs if d not in IGNORED_DIRS]
            
            for file in files:
                file_path = Path(root) / file
                if file_path.suffix.lower() in WATCHED_EXTENSIONS:
                    yield file_path


    # ============================================================
    # 向量语义检索（阶段四启用）
    # ============================================================

    def retrieve_by_vector(
        self,
        query: str,
        top_k: int = 10,
    ) -> List[RetrievalResult]:
        """
        向量语义检索
        
        使用语义查询在向量库中检索相关内容。
        阶段三返回空结果，阶段四启用后使用 vector_store。
        
        Args:
            query: 语义查询
            top_k: 返回数量
            
        Returns:
            检索结果列表
        """
        if self.vector_store is None:
            if self.logger:
                self.logger.debug("Vector store not available, skipping vector search")
            return []
        
        try:
            # 调用向量存储检索
            # 阶段四实现具体逻辑
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

    def retrieve_by_dependency(
        self,
        main_file: str,
        project_path: str,
    ) -> List[RetrievalResult]:
        """
        依赖分析检索
        
        解析当前 SPICE 文件的 .include 语句，找到引用的子电路。
        
        Args:
            main_file: 主文件路径
            project_path: 项目路径
            
        Returns:
            检索结果列表
        """
        results = []
        
        main_path = Path(main_file)
        if not main_path.exists():
            return results
        
        try:
            content = main_path.read_text(encoding="utf-8", errors="ignore")
            
            # 提取 .include 语句
            include_pattern = r'\.include\s+["\']?([^"\'\s]+)["\']?'
            includes = re.findall(include_pattern, content, re.IGNORECASE)
            
            # 提取 .lib 语句
            lib_pattern = r'\.lib\s+["\']?([^"\'\s]+)["\']?'
            libs = re.findall(lib_pattern, content, re.IGNORECASE)
            
            # 合并依赖文件
            dependencies = set(includes + libs)
            
            project_dir = Path(project_path)
            main_dir = main_path.parent
            
            for dep in dependencies:
                # 尝试相对于主文件目录解析
                dep_path = main_dir / dep
                if not dep_path.exists():
                    # 尝试相对于项目目录解析
                    dep_path = project_dir / dep
                
                if dep_path.exists():
                    try:
                        dep_content = dep_path.read_text(encoding="utf-8", errors="ignore")
                        rel_path = str(dep_path.relative_to(project_dir))
                        
                        results.append(RetrievalResult(
                            path=rel_path,
                            content=dep_content,
                            relevance=0.9,  # 依赖文件高相关度
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

    def merge_and_rank(
        self,
        results: List[RetrievalResult],
        token_budget: int,
    ) -> List[RetrievalResult]:
        """
        融合多路结果并排序
        
        使用 RRF（Reciprocal Rank Fusion）算法融合多路检索结果。
        
        Args:
            results: 所有检索结果
            token_budget: Token 预算
            
        Returns:
            融合排序后的结果列表
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
        k = 60  # RRF 常数
        rrf_scores: Dict[str, float] = {}
        path_to_result: Dict[str, RetrievalResult] = {}
        
        for source, source_results in by_source.items():
            for rank, result in enumerate(source_results, start=1):
                path = result.path
                
                # 累加 RRF 分数
                rrf_score = 1.0 / (k + rank)
                rrf_scores[path] = rrf_scores.get(path, 0) + rrf_score
                
                # 保留最高相关度的结果
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
                # 更新相关度为 RRF 分数（归一化）
                max_rrf = max(rrf_scores.values()) if rrf_scores else 1.0
                result.relevance = rrf_scores[path] / max_rrf
                
                final_results.append(result)
                total_tokens += result.token_count
            else:
                # 超出预算，停止添加
                break
        
        return final_results

    # ============================================================
    # 辅助方法
    # ============================================================

    def _estimate_tokens(self, text: str) -> int:
        """
        估算文本的 Token 数
        
        委托给 token_counter 模块，若不可用则回退到简单估算。
        遵循单一信息源原则，所有 Token 计算由 token_counter 模块负责。
        """
        if not text:
            return 0
        
        try:
            from domain.llm.token_counter import estimate_tokens
            return estimate_tokens(text)
        except ImportError:
            # 回退到简单估算（4 字符 ≈ 1 token）
            return len(text) // 4

    # ============================================================
    # 隐式上下文收集（3.2.3.1）
    # ============================================================

    def collect_implicit_context(
        self,
        project_path: str,
    ) -> Dict[str, Any]:
        """
        收集隐式上下文（自动触发）
        
        触发时机：用户发送消息时自动执行，无需用户手动 @引用
        
        收集内容：
        - 当前打开的电路文件内容
        - 最新仿真结果
        - 当前设计目标
        - 最近的仿真错误信息（如果存在）
        
        Args:
            project_path: 项目路径
            
        Returns:
            隐式上下文字典
        """
        context = {
            "current_circuit": None,
            "simulation_result": None,
            "design_goals": None,
            "simulation_error": None,
        }
        
        project_dir = Path(project_path)
        circuit_ai_dir = project_dir / ".circuit_ai"
        
        # 获取当前电路文件
        circuit_file = self._get_current_circuit_file(project_dir)
        if circuit_file:
            context["current_circuit"] = {
                "path": str(circuit_file.relative_to(project_dir)),
                "content": circuit_file.read_text(encoding="utf-8", errors="ignore"),
            }
        
        # 获取最新仿真结果
        sim_result = self._get_latest_simulation_result(project_dir)
        if sim_result:
            context["simulation_result"] = sim_result
        
        # 获取设计目标
        design_goals = self._get_design_goals(circuit_ai_dir)
        if design_goals:
            context["design_goals"] = design_goals
        
        # 获取仿真错误
        sim_error = self._get_simulation_error(circuit_ai_dir)
        if sim_error:
            context["simulation_error"] = sim_error
        
        return context
    
    def _get_current_circuit_file(self, project_dir: Path) -> Optional[Path]:
        """获取当前打开的电路文件"""
        # 尝试从 SessionState 获取当前打开的文件
        if self.session_state:
            current_file = self.session_state.active_circuit_file
            if current_file:
                return Path(current_file)
        
        # 回退：查找最近修改的 .cir 文件
        cir_files = list(project_dir.glob("*.cir"))
        if cir_files:
            return max(cir_files, key=lambda f: f.stat().st_mtime)
        
        return None
    
    def _get_latest_simulation_result(
        self,
        project_dir: Path
    ) -> Optional[Dict[str, Any]]:
        """获取最新仿真结果"""
        import json
        
        sim_dir = project_dir / "simulation_results"
        if not sim_dir.exists():
            return None
        
        json_files = list(sim_dir.glob("*.json"))
        if not json_files:
            return None
        
        # 获取最近修改的文件
        latest_file = max(json_files, key=lambda f: f.stat().st_mtime)
        
        try:
            data = json.loads(latest_file.read_text(encoding="utf-8"))
            return {
                "path": str(latest_file.relative_to(project_dir)),
                "data": data,
            }
        except Exception:
            return None
    
    def _get_design_goals(
        self,
        circuit_ai_dir: Path
    ) -> Optional[Dict[str, Any]]:
        """
        获取设计目标
        
        委托给 design_service 处理
        """
        try:
            from domain.services.design_service import load_design_goals
            # circuit_ai_dir 是 .circuit_ai 目录，需要获取其父目录作为 project_root
            project_root = circuit_ai_dir.parent
            goals = load_design_goals(str(project_root))
            return goals if goals else None
        except Exception:
            return None
    
    def _get_simulation_error(
        self,
        circuit_ai_dir: Path
    ) -> Optional[str]:
        """获取仿真错误信息（如有）"""
        # 尝试从 SessionState 获取
        if self.session_state:
            error = self.session_state.error_context
            if error:
                return error
        
        return None

    # ============================================================
    # 诊断信息收集（3.2.3.2）
    # ============================================================

    def collect_diagnostics(
        self,
        project_path: str,
        circuit_file: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        收集所有诊断信息
        
        设计理念：在用户发送消息前，自动收集并注入诊断信息，
        让 LLM 了解当前问题状态。
        
        Args:
            project_path: 项目路径
            circuit_file: 当前电路文件路径（可选）
            
        Returns:
            诊断信息字典
        """
        diagnostics = {
            "syntax_errors": [],
            "simulation_errors": [],
            "warnings": [],
            "error_history": [],
        }
        
        project_dir = Path(project_path)
        
        # 获取语法错误
        if circuit_file:
            syntax_errors = self._get_syntax_errors(circuit_file)
            diagnostics["syntax_errors"] = syntax_errors
        
        # 获取仿真错误
        sim_errors = self._get_simulation_errors(project_dir)
        diagnostics["simulation_errors"] = sim_errors
        
        # 获取警告信息
        warnings = self._get_warning_messages(project_dir)
        diagnostics["warnings"] = warnings
        
        # 获取历史错误关联
        if circuit_file:
            error_history = self._get_error_history(circuit_file)
            diagnostics["error_history"] = error_history
        
        return diagnostics
    
    def _get_syntax_errors(self, circuit_file: str) -> List[Dict[str, Any]]:
        """
        获取语法检查结果
        
        注意：完整的语法检查在阶段四实现，这里提供基础框架
        """
        errors = []
        
        try:
            file_path = Path(circuit_file)
            if not file_path.exists():
                return errors
            
            content = file_path.read_text(encoding="utf-8", errors="ignore")
            lines = content.split("\n")
            
            # 基础语法检查
            for i, line in enumerate(lines, 1):
                line_stripped = line.strip()
                
                # 跳过空行和注释
                if not line_stripped or line_stripped.startswith("*"):
                    continue
                
                # 检查未闭合的引号
                if line_stripped.count('"') % 2 != 0:
                    errors.append({
                        "line": i,
                        "message": "未闭合的引号",
                        "content": line_stripped[:50],
                    })
                
                # 检查 .subckt 和 .ends 配对（简化检查）
                # 完整检查在阶段四实现
                
        except Exception as e:
            if self.logger:
                self.logger.debug(f"Syntax check failed: {e}")
        
        return errors
    
    def _get_simulation_errors(self, project_dir: Path) -> List[Dict[str, Any]]:
        """获取仿真错误信息"""
        errors = []
        
        # 从 SessionState 获取最近的仿真错误
        if self.session_state:
            last_error = self.session_state.error_context
            if last_error:
                errors.append({
                    "type": "simulation",
                    "message": last_error,
                })
        
        return errors
    
    def _get_warning_messages(self, project_dir: Path) -> List[Dict[str, Any]]:
        """获取警告信息"""
        # TODO: 警告信息收集待实现
        # 目前返回空列表，待后续从 GraphState 或日志中收集
        return []
    
    def _get_error_history(self, circuit_file: str) -> List[Dict[str, Any]]:
        """
        获取历史错误关联
        
        维护 error_history 字典，记录最近 3 次仿真失败的错误类型和简要描述。
        当同一电路再次讨论时，注入历史错误摘要。
        """
        # TODO: 错误历史收集待实现
        # 目前返回空列表，待后续从 GraphState 或日志中收集
        return []


# ============================================================
# 模块导出
# ============================================================

__all__ = [
    "ContextRetriever",
    "RetrievalResult",
    "SPICE_EXTENSIONS",
    "SPICE_METRICS",
]
