# Prompt Builder - Dynamic Prompt Construction Facade
"""
提示词构建器 - 门面类，协调各子模块构建上下文和任务模板

职责：
- 作为统一入口协调各子模块
- 按优先级组装上下文信息（不含身份提示词）
- 管理构建流程

⚠️ 职责变更：
- PromptBuilder 不再负责系统角色定义（身份提示词）
- 身份提示词的注入已迁移到 SystemPromptInjector
- 本类仅负责任务模板和上下文格式化

使用示例：
    from domain.llm.prompt_building import PromptBuilder
    
    builder = PromptBuilder()
    result = builder.build_context(
        context={"circuit_type": "amplifier"},
        user_message="Design a 20dB amplifier",
        project_path="/path/to/project"
    )
"""

import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from domain.llm.token_counter import count_tokens
from domain.llm.prompt_building.token_budget_allocator import (
    TokenBudgetAllocator,
    TokenBudget,
)
from domain.llm.prompt_building.context_formatter import ContextFormatter
from domain.llm.prompt_building.file_content_processor import FileContentProcessor


# ============================================================
# 数据类定义
# ============================================================

@dataclass
class PromptSection:
    """Prompt 组成部分"""
    name: str
    content: str
    token_count: int
    priority: int  # 优先级，数字越小优先级越高


@dataclass
class BuildResult:
    """构建结果"""
    prompt: str
    sections: List[PromptSection] = field(default_factory=list)
    total_tokens: int = 0
    budget: Optional[TokenBudget] = None
    truncated_sections: List[str] = field(default_factory=list)


# ============================================================
# PromptBuilder 类
# ============================================================

class PromptBuilder:
    """
    提示词构建器 - 门面类
    
    职责：
    - 作为统一入口协调各子模块
    - 按优先级组装上下文信息（不含身份提示词）
    
    ⚠️ 注意：身份提示词由 SystemPromptInjector 负责注入
    
    组装顺序（按优先级从高到低）：
    1. 诊断信息
    2. 隐式上下文
    3. 依赖文件上下文
    4. 结构化对话摘要
    5. 联网搜索结果
    6. RAG 检索上下文
    7. 近期对话历史
    8. 用户手动选择的文件
    9. 任务特定模板（可选）
    10. 用户消息
    """
    
    def __init__(
        self,
        budget_ratios: Optional[Dict[str, float]] = None,
        model: str = "default"
    ):
        """
        初始化构建器
        
        Args:
            budget_ratios: 自定义预算分配比例
            model: 模型名称
        """
        self._logger = logging.getLogger(__name__)
        self._model = model
        
        # 子模块
        self._budget_allocator = TokenBudgetAllocator(budget_ratios, model)
        self._formatter = ContextFormatter()
        self._file_processor = FileContentProcessor()
        
        # 延迟获取的服务
        self._prompt_template_manager = None
        self._context_retriever = None
        self._context_manager = None
    
    # ============================================================
    # 服务获取（延迟初始化）
    # ============================================================
    
    def _get_prompt_template_manager(self):
        """延迟获取 PromptTemplateManager"""
        if self._prompt_template_manager is None:
            try:
                from shared.service_locator import ServiceLocator
                from shared.service_names import SVC_PROMPT_TEMPLATE_MANAGER
                self._prompt_template_manager = ServiceLocator.get(SVC_PROMPT_TEMPLATE_MANAGER)
            except Exception as e:
                self._logger.warning(f"Failed to get PromptTemplateManager: {e}")
                from domain.llm.prompt_template_manager import PromptTemplateManager
                self._prompt_template_manager = PromptTemplateManager()
        return self._prompt_template_manager
    
    def _get_context_retriever(self):
        """延迟获取 ContextRetriever"""
        if self._context_retriever is None:
            try:
                from domain.llm.context_retrieval import ContextRetriever
                self._context_retriever = ContextRetriever()
            except Exception as e:
                self._logger.warning(f"Failed to get ContextRetriever: {e}")
        return self._context_retriever
    
    def _get_context_manager(self):
        """延迟获取 ContextManager"""
        if self._context_manager is None:
            try:
                from shared.service_locator import ServiceLocator
                from shared.service_names import SVC_CONTEXT_MANAGER
                self._context_manager = ServiceLocator.get(SVC_CONTEXT_MANAGER)
            except Exception as e:
                self._logger.debug(f"ContextManager not available: {e}")
        return self._context_manager
    
    # ============================================================
    # 主构建方法
    # ============================================================
    
    def build_context(
        self,
        context: Optional[Dict[str, Any]] = None,
        user_message: str = "",
        project_path: Optional[str] = None,
        include_retrieval: bool = True,
        model: Optional[str] = None
    ) -> BuildResult:
        """
        构建上下文信息（不含身份提示词）
        
        此方法供 SystemPromptInjector 调用，构建 Layer 2 上下文
        
        Args:
            context: 模板变量上下文
            user_message: 用户消息
            project_path: 项目路径
            include_retrieval: 是否包含自动检索的上下文
            model: 模型名称
            
        Returns:
            BuildResult 包含上下文内容和构建信息
        """
        context = context or {}
        model = model or self._model
        
        # 分配预算
        budget = self._budget_allocator.allocate(model)
        
        # 收集各部分
        sections: List[PromptSection] = []
        used_tokens: Dict[str, int] = {}
        truncated: List[str] = []
        
        # 按优先级收集各部分（不含身份提示词）
        self._collect_context_sections(
            sections, used_tokens, truncated,
            budget, context, user_message, project_path,
            include_retrieval
        )
        
        # 重新分配未使用的预算
        budget = self._budget_allocator.reallocate_unused(budget, used_tokens)
        
        # 按优先级排序并组装
        sections.sort(key=lambda s: s.priority)
        prompt_parts = [s.content for s in sections if s.content]
        final_prompt = "\n".join(prompt_parts)
        total_tokens = sum(s.token_count for s in sections)
        
        return BuildResult(
            prompt=final_prompt,
            sections=sections,
            total_tokens=total_tokens,
            budget=budget,
            truncated_sections=truncated
        )
    
    def build_task_template(
        self,
        template_name: str,
        context: Optional[Dict[str, Any]] = None
    ) -> Optional[str]:
        """
        构建任务模板部分
        
        Args:
            template_name: 模板名称常量
            context: 模板变量上下文
            
        Returns:
            任务模板内容，失败返回 None
        """
        manager = self._get_prompt_template_manager()
        if not manager:
            return None
        
        try:
            content = manager.get_template(template_name, variables=context or {})
            return content
        except Exception as e:
            self._logger.warning(f"Failed to get template {template_name}: {e}")
            return None
    
    def _collect_context_sections(
        self,
        sections: List[PromptSection],
        used_tokens: Dict[str, int],
        truncated: List[str],
        budget: TokenBudget,
        context: Dict[str, Any],
        user_message: str,
        project_path: Optional[str],
        include_retrieval: bool
    ) -> None:
        """收集所有上下文部分（不含身份提示词）"""
        
        # 1. 诊断信息（优先级 1）
        if include_retrieval and project_path:
            diag_section = self._build_diagnostics_section(project_path, budget.diagnostics)
            if diag_section:
                sections.append(diag_section)
                used_tokens["diagnostics"] = diag_section.token_count
        
        # 2. 隐式上下文（优先级 2）
        if include_retrieval and project_path:
            implicit_section = self._build_implicit_context_section(project_path, budget.implicit_context)
            if implicit_section:
                sections.append(implicit_section)
                used_tokens["implicit_context"] = implicit_section.token_count
        
        # 3. 依赖文件（优先级 3）
        if include_retrieval and project_path:
            dep_section = self._build_dependency_section(project_path, budget.dependencies)
            if dep_section:
                sections.append(dep_section)
                used_tokens["dependencies"] = dep_section.token_count
        
        # 4. 结构化摘要（优先级 4）
        summary_section = self._build_summary_section(budget.summary)
        if summary_section:
            sections.append(summary_section)
            used_tokens["summary"] = summary_section.token_count
        
        # 5. 联网搜索结果（优先级 5）
        web_results = context.get("web_search_results")
        if web_results:
            web_section = self._build_web_search_section(web_results, budget.web_search)
            if web_section:
                sections.append(web_section)
                used_tokens["web_search"] = web_section.token_count
        
        # 6. RAG 检索结果（优先级 6）
        if include_retrieval and project_path:
            rag_section = self._build_rag_section(user_message, project_path, budget.rag_results)
            if rag_section:
                sections.append(rag_section)
                used_tokens["rag_results"] = rag_section.token_count
        
        # 7. 对话历史（优先级 7）
        conv_section = self._build_conversation_section(budget.conversation)
        if conv_section:
            sections.append(conv_section)
            used_tokens["conversation"] = conv_section.token_count
        
        # 8. 用户手动选择的文件（优先级 8）
        user_files = context.get("user_files", [])
        if user_files:
            files_section = self._build_user_files_section(user_files, budget.user_files)
            if files_section:
                sections.append(files_section)
                used_tokens["user_files"] = files_section.token_count
        
        # 9. 用户消息（优先级 9）
        if user_message:
            user_section = PromptSection(
                name="user_message",
                content=f"\n## User Message\n{user_message}",
                token_count=count_tokens(user_message) + 10,
                priority=9
            )
            sections.append(user_section)
    
    # ============================================================
    # 各部分构建方法
    # ============================================================
    
    def _build_diagnostics_section(self, project_path: str, budget: int) -> Optional[PromptSection]:
        """
        构建诊断信息部分
        
        注意：诊断信息现在通过 ImplicitContextAggregator 收集，
        此方法作为备用方案，直接从 ContextRetriever 获取诊断结果。
        """
        try:
            import asyncio
            from domain.llm.context_retrieval import (
                DiagnosticsCollector,
                CollectionContext,
            )
            
            collector = DiagnosticsCollector()
            ctx = CollectionContext(project_path=project_path)
            
            # 运行异步收集
            try:
                loop = asyncio.get_running_loop()
                future = asyncio.run_coroutine_threadsafe(
                    collector.collect_async(ctx), loop
                )
                result = future.result(timeout=5)
            except RuntimeError:
                result = asyncio.run(collector.collect_async(ctx))
            
            if result.is_empty:
                return None
            
            content = result.content
            token_count = result.token_count
            
            if token_count > budget:
                content = self._file_processor.truncate_to_budget(content, budget)
                token_count = budget
                self._logger.warning("Diagnostics truncated due to budget")
            
            return PromptSection(
                name="diagnostics",
                content=content,
                token_count=token_count,
                priority=1
            )
        except Exception as e:
            self._logger.warning(f"Failed to build diagnostics section: {e}")
            return None
    
    def _build_implicit_context_section(self, project_path: str, budget: int) -> Optional[PromptSection]:
        """构建隐式上下文部分
        
        注意：隐式上下文现在通过 ImplicitContextAggregator.collect_async() 收集，
        并通过 ContextRetriever 统一管理。此方法保留用于向后兼容，
        但建议使用 ContextRetriever.retrieve_async() 获取完整上下文。
        """
        # 隐式上下文已通过 ContextRetriever 收集，此处返回 None
        # 避免重复收集
        return None
    
    def _build_dependency_section(self, project_path: str, budget: int) -> Optional[PromptSection]:
        """构建依赖文件部分
        
        注意：依赖文件现在通过 ContextRetriever 统一管理。
        此方法保留用于向后兼容。
        """
        # 依赖文件已通过 ContextRetriever 收集，此处返回 None
        # 避免重复收集
        return None
    
    def _build_summary_section(self, budget: int) -> Optional[PromptSection]:
        """构建结构化摘要部分"""
        context_manager = self._get_context_manager()
        if not context_manager:
            return None
        
        try:
            summary = context_manager.get_summary()
            if not summary:
                return None
            
            content = self._formatter.format_summary(summary)
            token_count = count_tokens(content)
            
            if token_count > budget:
                content = self._file_processor.truncate_to_budget(content, budget)
                token_count = budget
            
            return PromptSection(
                name="summary",
                content=content,
                token_count=token_count,
                priority=4
            )
        except Exception as e:
            self._logger.debug(f"No summary available: {e}")
            return None
    
    def _build_web_search_section(self, search_results: List[Dict[str, Any]], budget: int) -> Optional[PromptSection]:
        """构建联网搜索结果部分"""
        if not search_results:
            return None
        
        content = self._formatter.format_web_search(search_results)
        token_count = count_tokens(content)
        
        if token_count > budget:
            content = self._file_processor.truncate_to_budget(content, budget)
            token_count = budget
        
        return PromptSection(
            name="web_search",
            content=content,
            token_count=token_count,
            priority=5
        )
    
    def _build_rag_section(self, query: str, project_path: str, budget: int) -> Optional[PromptSection]:
        """构建 RAG 检索结果部分"""
        retriever = self._get_context_retriever()
        if not retriever:
            return None
        
        try:
            result = retriever.retrieve(
                message=query,
                project_path=project_path,
                token_budget=budget
            )
            
            if not result or not result.items:
                return None
            
            content = self._formatter.format_rag_results(result.items)
            token_count = count_tokens(content)
            
            if token_count > budget:
                content = self._file_processor.truncate_to_budget(content, budget)
                token_count = budget
            
            return PromptSection(
                name="rag_results",
                content=content,
                token_count=token_count,
                priority=6
            )
        except Exception as e:
            self._logger.warning(f"Failed to build RAG section: {e}")
            return None
    
    def _build_conversation_section(self, budget: int) -> Optional[PromptSection]:
        """构建对话历史部分"""
        context_manager = self._get_context_manager()
        if not context_manager:
            return None
        
        try:
            messages = context_manager.get_messages(max_tokens=budget)
            if not messages:
                return None
            
            content = self._formatter.format_conversation(messages)
            token_count = count_tokens(content)
            
            if token_count > budget:
                content = self._file_processor.truncate_to_budget(content, budget)
                token_count = budget
            
            return PromptSection(
                name="conversation",
                content=content,
                token_count=token_count,
                priority=7
            )
        except Exception as e:
            self._logger.debug(f"No conversation history: {e}")
            return None
    
    def _build_user_files_section(self, files: List[Dict[str, Any]], budget: int) -> Optional[PromptSection]:
        """构建用户手动选择的文件部分"""
        if not files:
            return None
        
        content = self._formatter.format_user_files(files, budget)
        token_count = count_tokens(content)
        
        return PromptSection(
            name="user_files",
            content=content,
            token_count=token_count,
            priority=8
        )
    
    # ============================================================
    # 便捷方法
    # ============================================================
    
    def allocate_token_budget(self, model: Optional[str] = None) -> TokenBudget:
        """计算各部分的 Token 预算（委托给 TokenBudgetAllocator）"""
        return self._budget_allocator.allocate(model)


# ============================================================
# 模块导出
# ============================================================

__all__ = [
    "PromptBuilder",
    "PromptSection",
    "BuildResult",
]
