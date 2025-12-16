# Keyword Retriever
"""
精确匹配检索器 - 基于关键词在工作区文件中执行精确匹配检索

职责：
- 基于关键词在工作区文件中执行精确匹配检索
- 遍历项目目录下所有 SPICE 相关文件
- 计算匹配相关度

检索策略：
- 遍历项目目录下所有 SPICE 相关文件
- 对每个文件执行大小写不敏感的关键词匹配
- 计算匹配度：relevance = min(match_count / total_keywords, 1.0)
- 返回匹配度大于 0 的文件及其内容

文件过滤规则：
- 关注的扩展名：.cir、.sp、.spice、.lib、.inc、.json、.txt、.md
- 忽略的目录：.circuit_ai、__pycache__、.git、node_modules

被调用方：context_retriever.py
"""

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Set


# ============================================================
# 常量定义
# ============================================================

# 关注的文件扩展名
WATCHED_EXTENSIONS = {
    ".cir", ".sp", ".spice", ".lib", ".inc",
    ".json", ".txt", ".md",
}

# 忽略的目录
IGNORED_DIRS = {
    ".circuit_ai", "__pycache__", ".git", "node_modules",
    ".venv", "venv", ".idea", ".vscode",
}

# 大文件阈值（1MB）
MAX_FILE_SIZE = 1024 * 1024

# 大文件最大读取行数
MAX_LINES_FOR_LARGE_FILE = 500



@dataclass
class KeywordMatch:
    """关键词匹配结果"""
    path: str
    content: str
    relevance: float
    source: str = "keyword"
    token_count: int = 0
    matched_keywords: Set[str] = None
    
    def __post_init__(self):
        if self.matched_keywords is None:
            self.matched_keywords = set()
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "path": self.path,
            "content": self.content,
            "relevance": self.relevance,
            "source": self.source,
            "token_count": self.token_count,
        }


class KeywordRetriever:
    """
    精确匹配检索器
    
    基于关键词在工作区文件中执行精确匹配检索。
    """

    def __init__(self):
        self._logger = None

    @property
    def logger(self):
        if self._logger is None:
            try:
                from infrastructure.utils.logger import get_logger
                self._logger = get_logger("keyword_retriever")
            except Exception:
                pass
        return self._logger

    # ============================================================
    # 主入口
    # ============================================================

    def retrieve(
        self,
        keywords: Set[str],
        project_path: str,
    ) -> List[KeywordMatch]:
        """
        执行关键词检索
        
        Args:
            keywords: 关键词集合
            project_path: 项目路径
            
        Returns:
            List[KeywordMatch]: 匹配结果列表
        """
        if not keywords:
            return []
        
        results = []
        project_dir = Path(project_path)
        
        if not project_dir.exists():
            if self.logger:
                self.logger.warning(f"Project path not found: {project_path}")
            return results
        
        # 遍历项目文件
        for file_path in self.iter_project_files(project_dir):
            match = self.search_in_file(file_path, keywords, project_dir)
            if match and match.relevance > 0:
                results.append(match)
        
        # 按相关度排序
        results.sort(key=lambda x: x.relevance, reverse=True)
        
        if self.logger:
            self.logger.debug(
                f"Found {len(results)} files matching {len(keywords)} keywords"
            )
        
        return results


    # ============================================================
    # 文件搜索
    # ============================================================

    def search_in_file(
        self,
        file_path: Path,
        keywords: Set[str],
        project_dir: Path,
    ) -> Optional[KeywordMatch]:
        """
        在单个文件中搜索关键词
        
        Args:
            file_path: 文件路径
            keywords: 关键词集合
            project_dir: 项目目录（用于计算相对路径）
            
        Returns:
            KeywordMatch: 匹配结果，或 None
        """
        try:
            # 检查文件大小
            file_size = file_path.stat().st_size
            
            if file_size > MAX_FILE_SIZE:
                # 大文件只读取前 N 行
                content = self._read_large_file(file_path)
            else:
                content = file_path.read_text(encoding="utf-8", errors="ignore")
            
            if not content:
                return None
            
            # 执行关键词匹配
            matched_keywords = set()
            content_lower = content.lower()
            
            for kw in keywords:
                if kw.lower() in content_lower:
                    matched_keywords.add(kw)
            
            if not matched_keywords:
                return None
            
            # 计算相关度
            relevance = self.calculate_relevance(
                len(matched_keywords), len(keywords)
            )
            
            # 计算相对路径
            try:
                rel_path = str(file_path.relative_to(project_dir))
            except ValueError:
                rel_path = str(file_path)
            
            return KeywordMatch(
                path=rel_path,
                content=content,
                relevance=relevance,
                source="keyword",
                token_count=self._estimate_tokens(content),
                matched_keywords=matched_keywords,
            )
            
        except Exception as e:
            if self.logger:
                self.logger.debug(f"Error searching in {file_path}: {e}")
            return None

    def _read_large_file(self, file_path: Path) -> str:
        """
        读取大文件（仅前 N 行）
        
        Args:
            file_path: 文件路径
            
        Returns:
            str: 文件内容（截断）
        """
        lines = []
        try:
            with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
                for i, line in enumerate(f):
                    if i >= MAX_LINES_FOR_LARGE_FILE:
                        lines.append(f"\n... [truncated after {MAX_LINES_FOR_LARGE_FILE} lines]")
                        break
                    lines.append(line)
        except Exception:
            pass
        return "".join(lines)

    # ============================================================
    # 相关度计算
    # ============================================================

    def calculate_relevance(
        self,
        match_count: int,
        total_keywords: int,
    ) -> float:
        """
        计算匹配相关度
        
        公式：relevance = min(match_count / total_keywords, 1.0)
        
        Args:
            match_count: 匹配的关键词数量
            total_keywords: 总关键词数量
            
        Returns:
            float: 相关度（0-1）
        """
        if total_keywords == 0:
            return 0.0
        return min(match_count / total_keywords, 1.0)


    # ============================================================
    # 文件遍历
    # ============================================================

    def iter_project_files(self, project_dir: Path):
        """
        遍历项目文件（过滤忽略目录）
        
        使用生成器遍历文件，避免一次性加载所有文件。
        
        Args:
            project_dir: 项目目录
            
        Yields:
            Path: 文件路径
        """
        for root, dirs, files in os.walk(project_dir):
            # 过滤忽略的目录（原地修改 dirs 列表）
            dirs[:] = [d for d in dirs if d not in IGNORED_DIRS]
            
            for file in files:
                file_path = Path(root) / file
                
                # 检查扩展名
                if file_path.suffix.lower() in WATCHED_EXTENSIONS:
                    yield file_path

    # ============================================================
    # 辅助方法
    # ============================================================

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

    def get_file_extensions(self) -> Set[str]:
        """获取关注的文件扩展名"""
        return WATCHED_EXTENSIONS.copy()

    def get_ignored_dirs(self) -> Set[str]:
        """获取忽略的目录"""
        return IGNORED_DIRS.copy()


__all__ = [
    "KeywordRetriever",
    "KeywordMatch",
    "WATCHED_EXTENSIONS",
    "IGNORED_DIRS",
    "MAX_FILE_SIZE",
]
