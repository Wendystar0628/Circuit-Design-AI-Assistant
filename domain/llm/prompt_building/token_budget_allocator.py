# Token Budget Allocator - Token Budget Management
"""
Token 预算分配器 - 计算和管理各部分的 Token 预算

职责：
- 计算模型可用的输入预算
- 按比例分配给各部分
- 动态重新分配未使用的预算

使用示例：
    from domain.llm.prompt_building.token_budget_allocator import TokenBudgetAllocator
    
    allocator = TokenBudgetAllocator()
    budget = allocator.allocate(model="glm-4.7")
"""

import logging
from dataclasses import dataclass
from typing import Dict, Optional

from domain.llm.token_counter import (
    get_model_context_limit,
    get_model_output_limit,
)


# ============================================================
# 常量定义
# ============================================================

# Token 预算分配比例（可配置）
DEFAULT_BUDGET_RATIOS: Dict[str, float] = {
    "system_prompt": 0.05,       # 系统提示词：5%
    "diagnostics": 0.10,         # 诊断信息：10%
    "implicit_context": 0.15,    # 隐式上下文：15%
    "dependencies": 0.10,        # 依赖文件：10%
    "summary": 0.05,             # 结构化摘要：5%
    "rag_results": 0.15,         # RAG 检索结果：15%
    "conversation": 0.20,        # 对话历史：20%
    "user_files": 0.10,          # 用户手动选择：10%
    "web_search": 0.10,          # 联网搜索：10%
}


# ============================================================
# 数据类定义
# ============================================================

@dataclass
class TokenBudget:
    """Token 预算分配"""
    total: int = 0
    system_prompt: int = 0
    diagnostics: int = 0
    implicit_context: int = 0
    dependencies: int = 0
    summary: int = 0
    rag_results: int = 0
    conversation: int = 0
    user_files: int = 0
    web_search: int = 0
    
    def remaining(self) -> int:
        """计算剩余预算"""
        used = (
            self.system_prompt + self.diagnostics + self.implicit_context +
            self.dependencies + self.summary + self.rag_results +
            self.conversation + self.user_files + self.web_search
        )
        return max(0, self.total - used)
    
    def to_dict(self) -> Dict[str, int]:
        """转换为字典"""
        return {
            "total": self.total,
            "system_prompt": self.system_prompt,
            "diagnostics": self.diagnostics,
            "implicit_context": self.implicit_context,
            "dependencies": self.dependencies,
            "summary": self.summary,
            "rag_results": self.rag_results,
            "conversation": self.conversation,
            "user_files": self.user_files,
            "web_search": self.web_search,
        }


# ============================================================
# TokenBudgetAllocator 类
# ============================================================

class TokenBudgetAllocator:
    """
    Token 预算分配器
    
    职责：
    - 计算模型可用的输入预算
    - 按比例分配给各部分
    - 动态重新分配未使用的预算
    """
    
    def __init__(
        self,
        budget_ratios: Optional[Dict[str, float]] = None,
        model: str = "default"
    ):
        """
        初始化分配器
        
        Args:
            budget_ratios: 自定义预算分配比例
            model: 默认模型名称
        """
        self._logger = logging.getLogger(__name__)
        self._budget_ratios = budget_ratios or DEFAULT_BUDGET_RATIOS.copy()
        self._model = model
    
    def allocate(self, model: Optional[str] = None) -> TokenBudget:
        """
        计算各部分的 Token 预算
        
        Args:
            model: 模型名称，默认使用构造时指定的模型
            
        Returns:
            TokenBudget 对象
        """
        model = model or self._model
        
        # 获取模型限制
        context_limit = get_model_context_limit(model)
        output_limit = get_model_output_limit(model)
        
        # 可用输入预算 = 上下文限制 - 输出预留
        total_budget = context_limit - output_limit
        
        # 按比例分配
        budget = TokenBudget(total=total_budget)
        budget.system_prompt = int(total_budget * self._budget_ratios.get("system_prompt", 0.05))
        budget.diagnostics = int(total_budget * self._budget_ratios.get("diagnostics", 0.10))
        budget.implicit_context = int(total_budget * self._budget_ratios.get("implicit_context", 0.15))
        budget.dependencies = int(total_budget * self._budget_ratios.get("dependencies", 0.10))
        budget.summary = int(total_budget * self._budget_ratios.get("summary", 0.05))
        budget.rag_results = int(total_budget * self._budget_ratios.get("rag_results", 0.15))
        budget.conversation = int(total_budget * self._budget_ratios.get("conversation", 0.20))
        budget.user_files = int(total_budget * self._budget_ratios.get("user_files", 0.10))
        budget.web_search = int(total_budget * self._budget_ratios.get("web_search", 0.10))
        
        self._logger.debug(f"Token budget allocated: total={total_budget}, model={model}")
        return budget
    
    def reallocate_unused(
        self,
        budget: TokenBudget,
        used: Dict[str, int]
    ) -> TokenBudget:
        """
        重新分配未使用的预算
        
        未使用的预算优先分配给对话历史
        
        Args:
            budget: 原始预算
            used: 各部分实际使用的 tokens
            
        Returns:
            调整后的预算
        """
        # 计算未使用的预算
        unused = 0
        for key in ["rag_results", "web_search", "user_files"]:
            allocated = getattr(budget, key, 0)
            actual = used.get(key, 0)
            if actual < allocated:
                unused += allocated - actual
        
        # 将未使用的预算分配给对话历史
        if unused > 0:
            budget.conversation += unused
            self._logger.debug(f"Reallocated {unused} tokens to conversation")
        
        return budget
    
    def get_budget_ratios(self) -> Dict[str, float]:
        """获取当前预算比例配置"""
        return self._budget_ratios.copy()
    
    def set_budget_ratios(self, ratios: Dict[str, float]) -> None:
        """
        设置自定义预算比例
        
        Args:
            ratios: 预算比例字典
        """
        self._budget_ratios.update(ratios)
        self._logger.info(f"Budget ratios updated: {ratios}")


# ============================================================
# 模块导出
# ============================================================

__all__ = [
    "TokenBudgetAllocator",
    "TokenBudget",
    "DEFAULT_BUDGET_RATIOS",
]
