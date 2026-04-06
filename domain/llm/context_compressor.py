# Context Compressor - Context Compression Logic
"""
上下文压缩 - 上下文压缩逻辑

职责：
- 生成压缩预览
- 执行上下文压缩（含增强清理策略）
- 生成对话摘要

基础压缩策略：
1. 保留系统消息
2. 保留最近 N 条消息
3. 将旧消息压缩为摘要
4. 保留包含重要操作的消息

增强清理策略（解决无用信息占用 Token 问题）：
1. 深度思考内容清理：旧消息的 reasoning_content 截断或清空
2. 操作记录合并：去重并限制每条消息的操作数
3. 摘要替换：用新摘要替换旧摘要，避免累积
4. 消息内容截断：对旧消息的过长 content 进行智能截断

使用示例：
    from domain.llm.context_compressor import ContextCompressor
    compressor = ContextCompressor()
    preview = compressor.generate_compress_preview(state, keep_recent=5)
    result = await compressor.compress(state, llm_worker, keep_recent=5)
"""

from typing import Any, Dict, List, Tuple

from langchain_core.messages import BaseMessage

from domain.llm.message_helpers import (
    ROLE_SYSTEM,
    ROLE_USER,
    ROLE_ASSISTANT,
    is_system_message,
    is_ai_message,
    get_reasoning_content,
    get_operations,
    get_role,
)
from domain.llm.token_counter import count_tokens
from domain.llm.working_context_builder import (
    build_working_context_state,
    get_history_messages,
    get_working_context_messages,
    get_working_context_summary,
)


# ============================================================
# 常量
# ============================================================

# 默认保留的最近消息数（激进压缩策略）
DEFAULT_KEEP_RECENT = 3

# 摘要生成提示模板
SUMMARY_PROMPT_TEMPLATE = """请将以下对话历史压缩为极简摘要，仅保留核心信息：

{conversation}

要求：
1. 仅保留用户的核心设计目标（一句话）
2. 仅保留关键技术决策（列表形式，每项不超过 10 字）
3. 仅保留当前未解决的问题（如有）
4. 控制在 200 字以内，越短越好

摘要："""


# ============================================================
# 压缩预览
# ============================================================

class CompressPreview:
    """压缩预览信息"""
    
    def __init__(
        self,
        messages_to_summarize: List[BaseMessage],
        direct_messages_after_compress: List[BaseMessage],
        estimated_tokens_saved: int,
        summary_preview: str = "",
        compressed_message_count: int = 0,
    ):
        self.messages_to_summarize = messages_to_summarize
        self.direct_messages_after_compress = direct_messages_after_compress
        self.estimated_tokens_saved = estimated_tokens_saved
        self.summary_preview = summary_preview
        self.compressed_message_count = compressed_message_count
    
    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            "summarized_count": len(self.messages_to_summarize),
            "direct_count": len(self.direct_messages_after_compress),
            "estimated_tokens_saved": self.estimated_tokens_saved,
            "summary_preview": self.summary_preview,
            "compressed_message_count": self.compressed_message_count,
        }


# ============================================================
# 上下文压缩器
# ============================================================

class ContextCompressor:
    """
    上下文压缩器
    
    负责压缩对话历史，生成摘要。
    直接操作 LangChain 消息类型。
    """
    
    def __init__(self):
        """初始化压缩器"""
        self._logger = None
    
    @property
    def logger(self):
        """延迟获取日志器"""
        if self._logger is None:
            try:
                from infrastructure.utils.logger import get_logger
                self._logger = get_logger("context_compressor")
            except Exception:
                pass
        return self._logger
    
    def generate_compress_preview(
        self,
        state: Dict[str, Any],
        keep_recent: int = DEFAULT_KEEP_RECENT,
        model: str = "default"
    ) -> CompressPreview:
        """
        生成压缩预览
        
        Args:
            state: 当前状态
            keep_recent: 保留的最近消息数
            model: 模型名称（用于 token 计算）
            
        Returns:
            CompressPreview: 压缩预览信息
        """
        direct_messages, messages_to_summarize = self._select_messages_for_summary(
            state,
            keep_recent,
        )

        tokens_saved = sum(
            count_tokens(msg.content if isinstance(msg.content, str) else "", model)
            + count_tokens(get_reasoning_content(msg) or "", model)
            for msg in messages_to_summarize
        )

        summary_preview = self._build_preview_summary(state, messages_to_summarize)

        return CompressPreview(
            messages_to_summarize=messages_to_summarize,
            direct_messages_after_compress=direct_messages,
            estimated_tokens_saved=tokens_saved,
            summary_preview=summary_preview,
            compressed_message_count=len(messages_to_summarize),
        )
    
    async def compress(
        self,
        state: Dict[str, Any],
        llm_worker: Any,
        keep_recent: int = DEFAULT_KEEP_RECENT,
        context_limit: int = 128000,
        model: str = "default"
    ) -> Dict[str, Any]:
        """
        执行压缩操作（含自适应压缩策略）
        
        Args:
            state: 当前状态
            llm_worker: LLM Worker 实例
            keep_recent: 保留的最近消息数
            context_limit: 上下文窗口大小（tokens）
            model: 模型名称（用于 token 计算）
            
        Returns:
            压缩结果
        """
        try:
            from infrastructure.config.settings import (
                COMPRESS_ADAPTIVE_ENABLED,
                COMPRESS_TARGET_RATIO,
                COMPRESS_MAX_ATTEMPTS,
            )
        except ImportError:
            COMPRESS_ADAPTIVE_ENABLED = True
            COMPRESS_TARGET_RATIO = 0.20
            COMPRESS_MAX_ATTEMPTS = 3

        preview = self.generate_compress_preview(state, keep_recent=keep_recent, model=model)

        if not preview.messages_to_summarize:
            if self.logger:
                self.logger.info("消息数量不足，无需压缩")
            return {
                "status": "skipped",
                "state": state,
                "error": "No compressible history",
            }
        
        try:
            safe_context_limit = max(1, context_limit)

            attempt_keep_recent = max(1, keep_recent)
            new_state = await self._do_compress(
                state,
                llm_worker,
                attempt_keep_recent,
                model,
            )
            final_ratio = 0.0

            if COMPRESS_ADAPTIVE_ENABLED:
                attempt = 1

                while attempt < COMPRESS_MAX_ATTEMPTS:
                    current_tokens = self._calculate_state_tokens(new_state, model)
                    current_ratio = current_tokens / safe_context_limit

                    if self.logger:
                        self.logger.info(
                            f"压缩尝试 {attempt}: {current_tokens} tokens "
                            f"({current_ratio:.1%}), 目标 {COMPRESS_TARGET_RATIO:.0%}"
                        )

                    if current_ratio <= COMPRESS_TARGET_RATIO:
                        break

                    next_keep_recent = max(1, attempt_keep_recent - 1)
                    if next_keep_recent == attempt_keep_recent:
                        break

                    attempt_keep_recent = next_keep_recent
                    new_state = await self._do_compress(
                        state,
                        llm_worker,
                        attempt_keep_recent,
                        model,
                    )
                    attempt += 1

                final_tokens = self._calculate_state_tokens(new_state, model)
                final_ratio = final_tokens / safe_context_limit

                if final_ratio > COMPRESS_TARGET_RATIO:
                    if self.logger:
                        self.logger.warning(
                            f"压缩后仍超过目标: {final_ratio:.1%} > {COMPRESS_TARGET_RATIO:.0%}"
                        )
            else:
                final_tokens = self._calculate_state_tokens(new_state, model)
                final_ratio = final_tokens / safe_context_limit
            
            return {
                "status": "completed",
                "state": new_state,
                "final_ratio": final_ratio,
                "target_ratio": COMPRESS_TARGET_RATIO,
                "missed_target": final_ratio > COMPRESS_TARGET_RATIO,
            }
            
        except Exception as e:
            if self.logger:
                self.logger.error(f"压缩失败: {e}")

            return {
                "status": "failed",
                "state": state,
                "error": str(e),
            }
    
    async def _do_compress(
        self,
        state: Dict[str, Any],
        llm_worker: Any,
        keep_recent: int,
        model: str
    ) -> Dict[str, Any]:
        """执行单次压缩"""
        direct_messages, messages_to_summarize = self._select_messages_for_summary(
            state,
            keep_recent,
        )

        if not messages_to_summarize:
            return state

        summary = await self._generate_summary(messages_to_summarize, llm_worker)

        new_state = build_working_context_state(
            state,
            summary=self._replace_summary(summary),
            compressed_count=len(messages_to_summarize),
            keep_recent=keep_recent,
        )

        if self.logger:
            self.logger.info(
                f"压缩完成: 摘要覆盖 {len(messages_to_summarize)} 条历史消息, "
                f"直接保留 {len(direct_messages)} 条工作上下文消息"
            )

        return new_state
    
    def _calculate_state_tokens(
        self,
        state: Dict[str, Any],
        model: str
    ) -> int:
        """计算状态的总 token 数"""
        messages = get_working_context_messages(state)
        total = 0

        for msg in messages:
            content = msg.content if isinstance(msg.content, str) else ""
            total += count_tokens(content, model)
            reasoning = get_reasoning_content(msg)
            if reasoning:
                total += count_tokens(reasoning, model)

        return total
    
    def _get_messages(self, state: Dict[str, Any]) -> List[BaseMessage]:
        """获取消息列表"""
        return get_history_messages(state)

    def _select_messages_for_summary(
        self,
        state: Dict[str, Any],
        keep_recent: int,
    ) -> Tuple[List[BaseMessage], List[BaseMessage]]:
        messages = self._get_messages(state)
        system_messages = [msg for msg in messages if is_system_message(msg)]
        non_system_messages = [msg for msg in messages if not is_system_message(msg)]

        if len(non_system_messages) <= keep_recent:
            return list(system_messages) + list(non_system_messages), []

        messages_to_summarize = list(non_system_messages[:-keep_recent])
        direct_messages = list(system_messages) + list(non_system_messages[-keep_recent:])
        return direct_messages, messages_to_summarize

    def _build_preview_summary(
        self,
        state: Dict[str, Any],
        messages_to_summarize: List[BaseMessage],
    ) -> str:
        if not messages_to_summarize:
            return get_working_context_summary(state)

        preview_summary = self._generate_simple_summary(messages_to_summarize)
        return self._replace_summary(preview_summary)
    
    async def _generate_summary(
        self,
        messages: List[BaseMessage],
        llm_worker: Any
    ) -> str:
        """
        生成摘要
        
        Args:
            messages: 要压缩的消息
            llm_worker: LLM Worker 实例
            
        Returns:
            摘要文本
        """
        # 构建对话文本
        conversation_text = self._format_messages_for_summary(messages)
        
        # 构建提示
        prompt = SUMMARY_PROMPT_TEMPLATE.format(conversation=conversation_text)
        
        try:
            # 调用 LLM 生成摘要
            response = await llm_worker.generate(
                prompt=prompt,
                max_tokens=1000,
                temperature=0.3,
            )
            
            return response.get("content", "")
            
        except Exception as e:
            if self.logger:
                self.logger.warning(f"LLM 摘要生成失败，使用简单摘要: {e}")
            
            # 回退到简单摘要
            return self._generate_simple_summary(messages)
    
    def _format_messages_for_summary(self, messages: List[BaseMessage]) -> str:
        """格式化消息用于摘要生成"""
        lines = []
        
        for msg in messages:
            role = get_role(msg)
            role_name = {
                ROLE_USER: "用户",
                ROLE_ASSISTANT: "助手",
                ROLE_SYSTEM: "系统",
            }.get(role, role)
            
            # 截断过长的内容
            content = msg.content if isinstance(msg.content, str) else ""
            if len(content) > 500:
                content = content[:500] + "..."
            
            lines.append(f"[{role_name}]: {content}")
            
            # 添加操作摘要
            operations = get_operations(msg)
            if operations:
                ops = ", ".join(operations[:3])
                if len(operations) > 3:
                    ops += f" 等 {len(operations)} 项操作"
                lines.append(f"  → 执行操作: {ops}")
        
        return "\n\n".join(lines)
    
    def _generate_simple_summary(self, messages: List[BaseMessage]) -> str:
        """生成简单摘要（不调用 LLM）"""
        if not messages:
            return ""
        
        from domain.llm.message_helpers import is_human_message
        
        lines = [f"Conversation summary ({len(messages)} messages):"]
        
        # 提取用户问题
        user_msgs = [m for m in messages if is_human_message(m)]
        if user_msgs:
            content = user_msgs[0].content if isinstance(user_msgs[0].content, str) else ""
            first_question = content[:100]
            lines.append(f"- 初始问题: {first_question}...")
        
        # 提取执行的操作
        all_operations = []
        for msg in messages:
            if is_ai_message(msg):
                all_operations.extend(get_operations(msg))
        
        if all_operations:
            ops_summary = ", ".join(all_operations[:5])
            if len(all_operations) > 5:
                ops_summary += f" 等 {len(all_operations)} 项"
            lines.append(f"- 执行操作: {ops_summary}")
        
        return "\n".join(lines)
    
    def _replace_summary(
        self,
        new_summary: str
    ) -> str:
        """
        摘要替换策略
        
        策略：
        - 直接使用新摘要
        
        Args:
            new_summary: 新摘要
            
        Returns:
            最终摘要
        """
        try:
            from infrastructure.config.settings import SUMMARY_MAX_LENGTH
        except ImportError:
            SUMMARY_MAX_LENGTH = 2000

        result = new_summary

        # 限制长度
        if len(result) > SUMMARY_MAX_LENGTH:
            result = result[:SUMMARY_MAX_LENGTH] + "\n[...摘要已截断...]"
        
        return result


# ============================================================
# 模块导出
# ============================================================

__all__ = [
    # 类
    "ContextCompressor",
    "CompressPreview",
    # 常量
    "DEFAULT_KEEP_RECENT",
    "SUMMARY_PROMPT_TEMPLATE",
]
