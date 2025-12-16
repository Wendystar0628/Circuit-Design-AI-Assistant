# Retrieval Merger
"""
检索结果融合器 - 融合多路检索结果，执行 RRF 算法和重排序

职责：
- 融合多路检索结果
- 执行 RRF（Reciprocal Rank Fusion）算法
- 管理 Token 预算
- 可选的重排序（Reranking）

多路检索策略（Hybrid RAG）：
- 路径A - 精确匹配：KeywordRetriever
- 路径B - 向量语义检索：VectorRetriever（阶段四启用）
- 路径C - 依赖分析：DependencyAnalyzer

结果融合算法（RRF）：
- 对每路检索结果按相关度排序
- 计算 RRF 分数：score = Σ 1/(k + rank_i)，其中 k=60
- 合并所有路径的 RRF 分数，统一排序
- 去重：同一文件只保留最高分

被调用方：context_retriever.py
"""

from dataclasses import dataclass
from typing import Any, Dict, List, Optional


@dataclass
class RetrievalItem:
    """检索结果项"""
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


class RetrievalMerger:
    """
    检索结果融合器
    
    融合多路检索结果，执行 RRF 算法和重排序。
    """

    # RRF 常数
    RRF_K = 60
    
    # 重排序配置
    RERANK_ENABLED = False  # 阶段四启用
    RERANK_MODEL = "mixedbread-ai/mxbai-rerank-base-v1"


    def __init__(self):
        self._reranker = None
        self._logger = None

    @property
    def logger(self):
        if self._logger is None:
            try:
                from infrastructure.utils.logger import get_logger
                self._logger = get_logger("retrieval_merger")
            except Exception:
                pass
        return self._logger

    # ============================================================
    # 主入口
    # ============================================================

    def merge(
        self,
        results_dict: Dict[str, List[RetrievalItem]],
        token_budget: int,
        query: Optional[str] = None,
    ) -> List[RetrievalItem]:
        """
        融合多路检索结果
        
        Args:
            results_dict: 多路检索结果，key 为来源名称
            token_budget: Token 预算
            query: 原始查询（用于重排序）
            
        Returns:
            List[RetrievalItem]: 融合后的结果列表
        """
        if not results_dict:
            return []
        
        # 1. 计算 RRF 分数
        rrf_scores, path_to_item = self.compute_rrf_scores(results_dict)
        
        if not rrf_scores:
            return []
        
        # 2. 去重
        deduplicated = self.deduplicate(rrf_scores, path_to_item)
        
        # 3. 重排序（可选，阶段四启用）
        if self.RERANK_ENABLED and query:
            deduplicated = self.rerank(deduplicated, query, top_k=20)
        
        # 4. 按预算截断
        final_results = self.truncate_by_budget(deduplicated, token_budget)
        
        if self.logger:
            self.logger.debug(
                f"Merged {sum(len(v) for v in results_dict.values())} items "
                f"into {len(final_results)} results"
            )
        
        return final_results

    # ============================================================
    # RRF 算法
    # ============================================================

    def compute_rrf_scores(
        self,
        results_dict: Dict[str, List[RetrievalItem]],
    ) -> tuple:
        """
        计算 RRF 分数
        
        RRF 公式：score = Σ 1/(k + rank_i)
        
        Args:
            results_dict: 多路检索结果
            
        Returns:
            tuple: (rrf_scores, path_to_item)
        """
        rrf_scores: Dict[str, float] = {}
        path_to_item: Dict[str, RetrievalItem] = {}
        
        for source, items in results_dict.items():
            # 按相关度排序
            sorted_items = sorted(items, key=lambda x: x.relevance, reverse=True)
            
            for rank, item in enumerate(sorted_items, start=1):
                path = item.path
                
                # 累加 RRF 分数
                rrf_score = 1.0 / (self.RRF_K + rank)
                rrf_scores[path] = rrf_scores.get(path, 0) + rrf_score
                
                # 保留最高相关度的结果
                if path not in path_to_item:
                    path_to_item[path] = item
                elif item.relevance > path_to_item[path].relevance:
                    path_to_item[path] = item
        
        return rrf_scores, path_to_item


    # ============================================================
    # 去重
    # ============================================================

    def deduplicate(
        self,
        rrf_scores: Dict[str, float],
        path_to_item: Dict[str, RetrievalItem],
    ) -> List[RetrievalItem]:
        """
        去重，同一文件只保留最高分
        
        Args:
            rrf_scores: RRF 分数字典
            path_to_item: 路径到结果项的映射
            
        Returns:
            List[RetrievalItem]: 去重后的结果列表
        """
        # 按 RRF 分数排序
        sorted_paths = sorted(
            rrf_scores.keys(),
            key=lambda p: rrf_scores[p],
            reverse=True
        )
        
        # 归一化相关度分数
        max_rrf = max(rrf_scores.values()) if rrf_scores else 1.0
        
        results = []
        for path in sorted_paths:
            item = path_to_item[path]
            # 更新相关度为归一化的 RRF 分数
            item.relevance = rrf_scores[path] / max_rrf
            results.append(item)
        
        return results

    # ============================================================
    # 重排序（阶段四启用）
    # ============================================================

    def rerank(
        self,
        candidates: List[RetrievalItem],
        query: str,
        top_k: int = 20,
    ) -> List[RetrievalItem]:
        """
        使用交叉编码器重排序
        
        默认模型：mixedbread-ai/mxbai-rerank-base-v1
        从 vendor/models/rerankers/ 加载
        
        Args:
            candidates: 候选结果列表
            query: 原始查询
            top_k: 返回数量
            
        Returns:
            List[RetrievalItem]: 重排序后的结果列表
        """
        if not self.RERANK_ENABLED:
            return candidates[:top_k * 2]
        
        # 阶段四实现：加载重排序模型
        if self._reranker is None:
            try:
                # TODO: 阶段四实现重排序模型加载
                # from vendor.models.rerankers import load_reranker
                # self._reranker = load_reranker(self.RERANK_MODEL)
                pass
            except Exception as e:
                if self.logger:
                    self.logger.warning(f"Failed to load reranker: {e}")
                return candidates[:top_k * 2]
        
        if self._reranker is None:
            return candidates[:top_k * 2]
        
        try:
            # 准备重排序输入
            pairs = [(query, item.content) for item in candidates[:top_k * 2]]
            
            # 执行重排序
            scores = self._reranker.compute_score(pairs)
            
            # 按分数排序
            scored_items = list(zip(candidates[:top_k * 2], scores))
            scored_items.sort(key=lambda x: x[1], reverse=True)
            
            # 更新相关度
            reranked = []
            for item, score in scored_items[:top_k]:
                item.relevance = score
                reranked.append(item)
            
            return reranked
            
        except Exception as e:
            if self.logger:
                self.logger.warning(f"Reranking failed: {e}")
            return candidates[:top_k]


    # ============================================================
    # Token 预算管理
    # ============================================================

    def truncate_by_budget(
        self,
        results: List[RetrievalItem],
        token_budget: int,
    ) -> List[RetrievalItem]:
        """
        按 Token 预算截断
        
        优先保留高 RRF 分数的结果。
        
        Args:
            results: 已排序的结果列表
            token_budget: Token 预算
            
        Returns:
            List[RetrievalItem]: 截断后的结果列表
        """
        if not results:
            return []
        
        final_results = []
        total_tokens = 0
        
        for item in results:
            if total_tokens + item.token_count <= token_budget:
                final_results.append(item)
                total_tokens += item.token_count
            else:
                # 尝试截断内容以适应预算
                remaining_budget = token_budget - total_tokens
                if remaining_budget > 100:  # 至少保留 100 tokens
                    truncated_item = self._truncate_item(item, remaining_budget)
                    if truncated_item:
                        final_results.append(truncated_item)
                break
        
        return final_results

    def _truncate_item(
        self,
        item: RetrievalItem,
        max_tokens: int,
    ) -> Optional[RetrievalItem]:
        """
        截断单个结果项的内容
        
        Args:
            item: 结果项
            max_tokens: 最大 token 数
            
        Returns:
            RetrievalItem: 截断后的结果项，或 None
        """
        # 估算每个 token 约 4 个字符
        max_chars = max_tokens * 4
        
        if len(item.content) <= max_chars:
            return item
        
        # 截断内容
        truncated_content = item.content[:max_chars]
        
        # 尝试在行边界截断
        last_newline = truncated_content.rfind('\n')
        if last_newline > max_chars // 2:
            truncated_content = truncated_content[:last_newline]
        
        truncated_content += "\n... [truncated]"
        
        return RetrievalItem(
            path=item.path,
            content=truncated_content,
            relevance=item.relevance,
            source=item.source,
            token_count=max_tokens,
        )

    # ============================================================
    # 辅助方法
    # ============================================================

    def estimate_tokens(self, text: str) -> int:
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

    def get_source_stats(
        self,
        results: List[RetrievalItem],
    ) -> Dict[str, int]:
        """获取各来源的结果数量统计"""
        stats: Dict[str, int] = {}
        for item in results:
            stats[item.source] = stats.get(item.source, 0) + 1
        return stats


__all__ = [
    "RetrievalMerger",
    "RetrievalItem",
]
