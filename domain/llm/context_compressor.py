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
    new_state = await compressor.compress(state, llm_worker, keep_recent=5)
"""

import copy
from typing import Any, Dict, List, Optional, Tuple

from domain.llm.message_types import (
    Message,
    ROLE_SYSTEM,
    ROLE_USER,
    ROLE_ASSISTANT,
)
from domain.llm.message_adapter import MessageAdapter
from domain.llm.token_counter import count_tokens


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

# 结构化摘要生成提示模板
STRUCTURED_SUMMARY_PROMPT_TEMPLATE = """请分析以下电路设计对话历史，提取结构化信息：

{conversation}

请按以下 JSON 格式输出：
{{
  "design_goal": "用户的设计目标（一句话描述）",
  "attempted_solutions": [
    {{"solution": "方案描述", "status": "success/failed", "reason": "原因"}}
  ],
  "current_problem": "当前面临的问题（如无则为空）",
  "key_decisions": ["用户确认的关键设计决策"],
  "circuit_modifications": ["电路修改记录"],
  "performance_metrics": {{"指标名": "达成值"}}
}}

仅输出 JSON，不要其他内容："""


# ============================================================
# 压缩预览
# ============================================================

class StructuredSummary:
    """结构化摘要"""
    
    def __init__(
        self,
        design_goal: str = "",
        attempted_solutions: Optional[List[Dict[str, str]]] = None,
        current_problem: str = "",
        key_decisions: Optional[List[str]] = None,
        circuit_modifications: Optional[List[str]] = None,
        performance_metrics: Optional[Dict[str, str]] = None,
    ):
        self.design_goal = design_goal
        self.attempted_solutions = attempted_solutions or []
        self.current_problem = current_problem
        self.key_decisions = key_decisions or []
        self.circuit_modifications = circuit_modifications or []
        self.performance_metrics = performance_metrics or {}
    
    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            "design_goal": self.design_goal,
            "attempted_solutions": self.attempted_solutions,
            "current_problem": self.current_problem,
            "key_decisions": self.key_decisions,
            "circuit_modifications": self.circuit_modifications,
            "performance_metrics": self.performance_metrics,
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "StructuredSummary":
        """从字典创建"""
        return cls(
            design_goal=data.get("design_goal", ""),
            attempted_solutions=data.get("attempted_solutions", []),
            current_problem=data.get("current_problem", ""),
            key_decisions=data.get("key_decisions", []),
            circuit_modifications=data.get("circuit_modifications", []),
            performance_metrics=data.get("performance_metrics", {}),
        )
    
    def format_for_prompt(self) -> str:
        """格式化为 Prompt 注入格式"""
        lines = ["[对话历史摘要]"]
        
        if self.design_goal:
            lines.append(f"设计目标: {self.design_goal}")
        
        if self.attempted_solutions:
            lines.append("已尝试方案:")
            for sol in self.attempted_solutions:
                status = "✓" if sol.get("status") == "success" else "✗"
                lines.append(f"  {status} {sol.get('solution', '')}")
        
        if self.current_problem:
            lines.append(f"当前问题: {self.current_problem}")
        
        if self.key_decisions:
            lines.append(f"关键决策: {', '.join(self.key_decisions)}")
        
        if self.performance_metrics:
            metrics = [f"{k}={v}" for k, v in self.performance_metrics.items()]
            lines.append(f"已达成指标: {', '.join(metrics)}")
        
        return "\n".join(lines)


class CompressPreview:
    """压缩预览信息"""
    
    def __init__(
        self,
        messages_to_remove: List[Message],
        messages_to_keep: List[Message],
        estimated_tokens_saved: int,
        summary_preview: str = "",
    ):
        self.messages_to_remove = messages_to_remove
        self.messages_to_keep = messages_to_keep
        self.estimated_tokens_saved = estimated_tokens_saved
        self.summary_preview = summary_preview
    
    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            "remove_count": len(self.messages_to_remove),
            "keep_count": len(self.messages_to_keep),
            "estimated_tokens_saved": self.estimated_tokens_saved,
            "summary_preview": self.summary_preview,
        }


# ============================================================
# 上下文压缩器
# ============================================================

class ContextCompressor:
    """
    上下文压缩器
    
    负责压缩对话历史，生成摘要。
    通过 MessageAdapter 与 GraphState 交互，保持解耦。
    """
    
    def __init__(self):
        """初始化压缩器"""
        self._logger = None
        self._event_bus = None
        self._message_adapter = MessageAdapter()
    
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
        messages = self._get_messages(state)
        
        # 选择要保留和移除的消息
        to_keep, to_remove = self._select_messages_to_keep(
            messages, keep_recent
        )
        
        # 估算节省的 tokens
        tokens_saved = sum(
            count_tokens(msg.content, model) for msg in to_remove
        )
        
        # 生成摘要预览（简化版，不调用 LLM）
        summary_preview = self._generate_simple_summary(to_remove)
        
        return CompressPreview(
            messages_to_remove=to_remove,
            messages_to_keep=to_keep,
            estimated_tokens_saved=tokens_saved,
            summary_preview=summary_preview,
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
            更新后的状态副本
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
        
        messages = self._get_messages(state)
        
        if len(messages) <= keep_recent + 1:  # +1 for system message
            if self.logger:
                self.logger.info("消息数量不足，无需压缩")
            return state
        
        # 发布压缩开始事件
        self._publish_compress_event("started", {
            "message_count": len(messages),
            "keep_recent": keep_recent,
        })
        
        try:
            # 首次压缩
            new_state = await self._do_compress(
                state, llm_worker, keep_recent, model
            )
            
            # 自适应压缩：检查压缩后占比
            if COMPRESS_ADAPTIVE_ENABLED:
                target_tokens = int(context_limit * COMPRESS_TARGET_RATIO)
                attempt = 1
                
                while attempt < COMPRESS_MAX_ATTEMPTS:
                    current_tokens = self._calculate_state_tokens(new_state, model)
                    current_ratio = current_tokens / context_limit
                    
                    if self.logger:
                        self.logger.info(
                            f"压缩尝试 {attempt}: {current_tokens} tokens "
                            f"({current_ratio:.1%}), 目标 {COMPRESS_TARGET_RATIO:.0%}"
                        )
                    
                    if current_ratio <= COMPRESS_TARGET_RATIO:
                        # 达到目标，压缩成功
                        break
                    
                    # 未达标，执行更激进的压缩
                    new_state = await self._do_aggressive_compress(
                        new_state, llm_worker, attempt, model
                    )
                    attempt += 1
                
                # 最终检查
                final_tokens = self._calculate_state_tokens(new_state, model)
                final_ratio = final_tokens / context_limit
                
                if final_ratio > COMPRESS_TARGET_RATIO:
                    if self.logger:
                        self.logger.warning(
                            f"压缩后仍超过目标: {final_ratio:.1%} > {COMPRESS_TARGET_RATIO:.0%}"
                        )
                    # 发布建议开启新对话的事件
                    self._publish_compress_event("suggest_new_conversation", {
                        "current_ratio": final_ratio,
                        "target_ratio": COMPRESS_TARGET_RATIO,
                    })
            
            # 发布压缩完成事件
            self._publish_compress_event("completed", {
                "final_ratio": final_ratio if COMPRESS_ADAPTIVE_ENABLED else None,
            })
            
            return new_state
            
        except Exception as e:
            if self.logger:
                self.logger.error(f"压缩失败: {e}")
            
            self._publish_compress_event("failed", {"error": str(e)})
            return state
    
    async def _do_compress(
        self,
        state: Dict[str, Any],
        llm_worker: Any,
        keep_recent: int,
        model: str
    ) -> Dict[str, Any]:
        """执行单次压缩"""
        messages = self._get_messages(state)
        
        # 选择要保留和移除的消息
        to_keep, to_remove = self._select_messages_to_keep(
            messages, keep_recent
        )
        
        if not to_remove:
            return state
        
        # 增强清理策略
        to_keep = self._clean_reasoning_content(to_keep, keep_recent)
        to_keep = self._merge_operations(to_remove, to_keep)
        to_keep = self._truncate_old_messages(to_keep, keep_recent)
        
        # 生成摘要
        existing_summary = state.get("conversation_summary", "")
        summary = await self._generate_summary(to_remove, llm_worker)
        
        # 通过 MessageAdapter 更新状态
        new_state = self._message_adapter.update_state_messages(state, to_keep)
        
        # 更新摘要（使用替换策略）
        new_state["conversation_summary"] = self._replace_summary(
            existing_summary, summary
        )
        
        if self.logger:
            self.logger.info(f"压缩完成: 移除 {len(to_remove)} 条消息")
        
        return new_state
    
    async def _do_aggressive_compress(
        self,
        state: Dict[str, Any],
        llm_worker: Any,
        attempt: int,
        model: str
    ) -> Dict[str, Any]:
        """
        执行更激进的压缩（自适应策略）
        
        Args:
            state: 当前状态
            llm_worker: LLM Worker 实例
            attempt: 当前尝试次数（1=二次压缩，2=极端压缩）
            model: 模型名称
            
        Returns:
            更新后的状态
        """
        try:
            from infrastructure.config.settings import (
                COMPRESS_SECONDARY_KEEP_RECENT,
                COMPRESS_SECONDARY_TRUNCATE_LEN,
                COMPRESS_EXTREME_KEEP_RECENT,
                COMPRESS_EXTREME_SUMMARY_ONLY,
            )
        except ImportError:
            COMPRESS_SECONDARY_KEEP_RECENT = 2
            COMPRESS_SECONDARY_TRUNCATE_LEN = 200
            COMPRESS_EXTREME_KEEP_RECENT = 1
            COMPRESS_EXTREME_SUMMARY_ONLY = True
        
        messages = self._get_messages(state)
        
        if attempt == 1:
            # 二次压缩：减少保留消息数，更激进截断
            if self.logger:
                self.logger.info("执行二次压缩...")
            
            keep_recent = COMPRESS_SECONDARY_KEEP_RECENT
            truncate_len = COMPRESS_SECONDARY_TRUNCATE_LEN
            
            to_keep, to_remove = self._select_messages_to_keep(
                messages, keep_recent
            )
            
            # 更激进的截断
            for msg in to_keep:
                if not msg.is_system() and len(msg.content) > truncate_len:
                    msg.content = msg.content[:truncate_len] + "\n[...已截断...]"
                msg.reasoning_content = ""  # 清空所有 reasoning
            
            new_state = self._message_adapter.update_state_messages(state, to_keep)
            new_state["conversation_summary"] = state.get("conversation_summary", "")
            
        else:
            # 极端压缩：仅保留摘要和最近 1 条消息
            if self.logger:
                self.logger.info("执行极端压缩...")
            
            if COMPRESS_EXTREME_SUMMARY_ONLY:
                # 仅保留系统消息和摘要
                system_msgs = [m for m in messages if m.is_system()]
                non_system = [m for m in messages if not m.is_system()]
                
                # 保留最近 1 条
                to_keep = system_msgs + non_system[-COMPRESS_EXTREME_KEEP_RECENT:]
                
                # 清空所有内容，仅保留摘要
                for msg in to_keep:
                    if not msg.is_system():
                        msg.content = msg.content[:100] + "..." if len(msg.content) > 100 else msg.content
                    msg.reasoning_content = ""
                    msg.operations = []
                
                new_state = self._message_adapter.update_state_messages(state, to_keep)
                
                # 确保摘要存在
                summary = state.get("conversation_summary", "")
                if not summary:
                    summary = self._generate_simple_summary(non_system)
                new_state["conversation_summary"] = summary[:500]  # 限制摘要长度
            else:
                new_state = state
        
        return new_state
    
    def _calculate_state_tokens(
        self,
        state: Dict[str, Any],
        model: str
    ) -> int:
        """计算状态的总 token 数"""
        messages = self._get_messages(state)
        total = 0
        
        for msg in messages:
            total += count_tokens(msg.content, model)
            if msg.reasoning_content:
                total += count_tokens(msg.reasoning_content, model)
        
        # 加上摘要
        summary = state.get("conversation_summary", "")
        if summary:
            total += count_tokens(summary, model)
        
        return total
    
    def _get_messages(self, state: Dict[str, Any]) -> List[Message]:
        """获取消息列表（内部格式）"""
        return self._message_adapter.extract_messages_from_state(state)
    
    def _select_messages_to_keep(
        self,
        messages: List[Message],
        keep_recent: int
    ) -> Tuple[List[Message], List[Message]]:
        """
        选择保留的消息
        
        策略：
        1. 始终保留系统消息
        2. 保留最近 N 条消息
        3. 保留包含重要操作的消息
        
        Args:
            messages: 所有消息
            keep_recent: 保留的最近消息数
            
        Returns:
            (保留的消息, 移除的消息)
        """
        to_keep = []
        to_remove = []
        
        # 分离系统消息
        system_msgs = [m for m in messages if m.is_system()]
        non_system_msgs = [m for m in messages if not m.is_system()]
        
        # 系统消息始终保留
        to_keep.extend(system_msgs)
        
        if len(non_system_msgs) <= keep_recent:
            # 消息数量不足，全部保留
            to_keep.extend(non_system_msgs)
            return to_keep, to_remove
        
        # 分割：旧消息 vs 最近消息
        old_msgs = non_system_msgs[:-keep_recent]
        recent_msgs = non_system_msgs[-keep_recent:]
        
        # 最近消息保留
        to_keep.extend(recent_msgs)
        
        # 检查旧消息中是否有重要的
        for msg in old_msgs:
            if self._is_important_message(msg):
                to_keep.insert(len(system_msgs), msg)  # 插入到系统消息之后
            else:
                to_remove.append(msg)
        
        return to_keep, to_remove
    
    def _is_important_message(self, msg: Message) -> bool:
        """判断消息是否重要"""
        # 包含操作的助手消息
        if msg.is_assistant() and msg.operations:
            return True
        
        # 包含代码块的消息
        if "```" in msg.content:
            return True
        
        return False
    
    async def _generate_summary(
        self,
        messages: List[Message],
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
    
    def _format_messages_for_summary(self, messages: List[Message]) -> str:
        """格式化消息用于摘要生成"""
        lines = []
        
        for msg in messages:
            role_name = {
                ROLE_USER: "用户",
                ROLE_ASSISTANT: "助手",
                ROLE_SYSTEM: "系统",
            }.get(msg.role, msg.role)
            
            # 截断过长的内容
            content = msg.content
            if len(content) > 500:
                content = content[:500] + "..."
            
            lines.append(f"[{role_name}]: {content}")
            
            # 添加操作摘要
            if msg.operations:
                ops = ", ".join(msg.operations[:3])
                if len(msg.operations) > 3:
                    ops += f" 等 {len(msg.operations)} 项操作"
                lines.append(f"  → 执行操作: {ops}")
        
        return "\n\n".join(lines)
    
    def _generate_simple_summary(self, messages: List[Message]) -> str:
        """生成简单摘要（不调用 LLM）"""
        if not messages:
            return ""
        
        lines = [f"对话摘要（{len(messages)} 条消息）："]
        
        # 提取用户问题
        user_msgs = [m for m in messages if m.is_user()]
        if user_msgs:
            first_question = user_msgs[0].content[:100]
            lines.append(f"- 初始问题: {first_question}...")
        
        # 提取执行的操作
        all_operations = []
        for msg in messages:
            if msg.is_assistant() and msg.operations:
                all_operations.extend(msg.operations)
        
        if all_operations:
            ops_summary = ", ".join(all_operations[:5])
            if len(all_operations) > 5:
                ops_summary += f" 等 {len(all_operations)} 项"
            lines.append(f"- 执行操作: {ops_summary}")
        
        return "\n".join(lines)
    
    async def _generate_structured_summary(
        self,
        messages: List[Message],
        llm_worker: Any
    ) -> StructuredSummary:
        """
        生成结构化摘要
        
        Args:
            messages: 要压缩的消息
            llm_worker: LLM Worker 实例
            
        Returns:
            StructuredSummary: 结构化摘要对象
        """
        import json
        
        conversation_text = self._format_messages_for_summary(messages)
        prompt = STRUCTURED_SUMMARY_PROMPT_TEMPLATE.format(
            conversation=conversation_text
        )
        
        try:
            response = await llm_worker.generate(
                prompt=prompt,
                max_tokens=1500,
                temperature=0.2,
            )
            
            content = response.get("content", "")
            # 尝试解析 JSON
            data = json.loads(content)
            return StructuredSummary.from_dict(data)
            
        except json.JSONDecodeError as e:
            if self.logger:
                self.logger.warning(f"结构化摘要 JSON 解析失败: {e}")
            return self._extract_key_decisions(messages)
            
        except Exception as e:
            if self.logger:
                self.logger.warning(f"结构化摘要生成失败: {e}")
            return self._extract_key_decisions(messages)
    
    def _extract_key_decisions(
        self,
        messages: List[Message]
    ) -> StructuredSummary:
        """
        从消息中提取关键决策（不调用 LLM 的回退方案）
        
        Args:
            messages: 消息列表
            
        Returns:
            StructuredSummary: 基于规则提取的结构化摘要
        """
        summary = StructuredSummary()
        
        # 提取设计目标（第一条用户消息）
        user_msgs = [m for m in messages if m.is_user()]
        if user_msgs:
            summary.design_goal = user_msgs[0].content[:200]
        
        # 提取电路修改（从操作记录）
        for msg in messages:
            if msg.is_assistant() and msg.operations:
                for op in msg.operations:
                    if any(kw in op.lower() for kw in 
                           ["修改", "添加", "删除", "调整", "modify", "add", "remove"]):
                        summary.circuit_modifications.append(op)
        
        # 限制数量
        summary.circuit_modifications = summary.circuit_modifications[:10]
        
        return summary
    
    # ============================================================
    # 增强清理方法
    # ============================================================
    
    def _clean_reasoning_content(
        self,
        messages: List[Message],
        keep_recent: int
    ) -> List[Message]:
        """
        清理深度思考内容
        
        策略：
        - 最近 KEEP_REASONING_RECENT_COUNT 条消息保留完整 reasoning_content
        - 其余消息的 reasoning_content 截断或清空
        
        Args:
            messages: 消息列表
            keep_recent: 保留的最近消息数
            
        Returns:
            清理后的消息列表
        """
        try:
            from infrastructure.config.settings import (
                KEEP_REASONING_RECENT_COUNT,
                REASONING_TRUNCATE_LENGTH,
            )
        except ImportError:
            KEEP_REASONING_RECENT_COUNT = 2
            REASONING_TRUNCATE_LENGTH = 0
        
        if not messages:
            return messages
        
        # 分离系统消息和非系统消息
        system_msgs = [m for m in messages if m.is_system()]
        non_system_msgs = [m for m in messages if not m.is_system()]
        
        # 处理非系统消息
        total = len(non_system_msgs)
        for i, msg in enumerate(non_system_msgs):
            if not msg.is_assistant() or not msg.reasoning_content:
                continue
            
            # 最近 N 条保留完整
            if i >= total - KEEP_REASONING_RECENT_COUNT:
                continue
            
            # 其余消息清理 reasoning_content
            if REASONING_TRUNCATE_LENGTH == 0:
                msg.reasoning_content = ""
            elif len(msg.reasoning_content) > REASONING_TRUNCATE_LENGTH:
                msg.reasoning_content = (
                    msg.reasoning_content[:REASONING_TRUNCATE_LENGTH] + 
                    "\n[...思考内容已截断...]"
                )
        
        return system_msgs + non_system_msgs
    
    def _merge_operations(
        self,
        messages_to_remove: List[Message],
        messages_to_keep: List[Message]
    ) -> List[Message]:
        """
        合并操作记录
        
        策略：
        - 收集被移除消息的 operations
        - 去重并限制数量
        - 附加到保留消息的最后一条助手消息
        
        Args:
            messages_to_remove: 被移除的消息
            messages_to_keep: 保留的消息
            
        Returns:
            更新后的保留消息列表
        """
        try:
            from infrastructure.config.settings import (
                OPERATIONS_MERGE_ENABLED,
                OPERATIONS_MAX_PER_MESSAGE,
                OPERATIONS_DEDUP_ENABLED,
            )
        except ImportError:
            OPERATIONS_MERGE_ENABLED = True
            OPERATIONS_MAX_PER_MESSAGE = 5
            OPERATIONS_DEDUP_ENABLED = True
        
        if not OPERATIONS_MERGE_ENABLED:
            return messages_to_keep
        
        # 收集被移除消息的操作
        removed_operations = []
        for msg in messages_to_remove:
            if msg.is_assistant() and msg.operations:
                removed_operations.extend(msg.operations)
        
        if not removed_operations:
            return messages_to_keep
        
        # 去重（保留最后出现的）
        if OPERATIONS_DEDUP_ENABLED:
            seen = {}
            for op in removed_operations:
                seen[op] = op  # 后出现的覆盖先出现的
            removed_operations = list(seen.values())
        
        # 限制每条消息的操作数
        for msg in messages_to_keep:
            if msg.is_assistant() and msg.operations:
                if len(msg.operations) > OPERATIONS_MAX_PER_MESSAGE:
                    msg.operations = msg.operations[-OPERATIONS_MAX_PER_MESSAGE:]
        
        return messages_to_keep
    
    def _truncate_old_messages(
        self,
        messages: List[Message],
        keep_recent: int
    ) -> List[Message]:
        """
        截断旧消息内容（激进策略）
        
        策略（参考 Cursor/Windsurf）：
        - 对于非最近 N 条的消息，激进截断
        - 代码块截断到指定行数（不完整保留）
        - 代码应通过 RAG 检索获取，而非保留在上下文中
        
        Args:
            messages: 消息列表
            keep_recent: 保留的最近消息数
            
        Returns:
            截断后的消息列表
        """
        try:
            from infrastructure.config.settings import (
                OLD_MESSAGE_TRUNCATE_LENGTH,
                CODE_BLOCK_MAX_LINES,
            )
        except ImportError:
            OLD_MESSAGE_TRUNCATE_LENGTH = 500
            CODE_BLOCK_MAX_LINES = 20
        
        if OLD_MESSAGE_TRUNCATE_LENGTH == 0:
            return messages
        
        # 分离系统消息和非系统消息
        system_msgs = [m for m in messages if m.is_system()]
        non_system_msgs = [m for m in messages if not m.is_system()]
        
        total = len(non_system_msgs)
        for i, msg in enumerate(non_system_msgs):
            # 最近 N 条不截断
            if i >= total - keep_recent:
                continue
            
            # 系统消息不截断
            if msg.is_system():
                continue
            
            content = msg.content
            
            # 先处理代码块：截断到指定行数
            content = self._truncate_code_blocks(content, CODE_BLOCK_MAX_LINES)
            
            # 再处理整体长度
            if len(content) > OLD_MESSAGE_TRUNCATE_LENGTH:
                # 激进截断：只保留开头部分
                content = content[:OLD_MESSAGE_TRUNCATE_LENGTH] + "\n[...已截断...]"
            
            msg.content = content
        
        return system_msgs + non_system_msgs
    
    def _truncate_code_blocks(self, content: str, max_lines: int) -> str:
        """
        截断代码块到指定行数
        
        Args:
            content: 消息内容
            max_lines: 代码块最大行数
            
        Returns:
            处理后的内容
        """
        import re
        
        def truncate_block(match):
            block = match.group(0)
            lines = block.split('\n')
            if len(lines) <= max_lines + 2:  # +2 for ``` markers
                return block
            # 保留开头和结尾的 ```
            header = lines[0]  # ```language
            truncated = lines[1:max_lines+1]
            return f"{header}\n" + '\n'.join(truncated) + f"\n[...{len(lines)-max_lines-2} 行已省略...]\n```"
        
        # 匹配代码块
        pattern = r'```[\w]*\n[\s\S]*?```'
        return re.sub(pattern, truncate_block, content)
    
    def _replace_summary(
        self,
        old_summary: str,
        new_summary: str
    ) -> str:
        """
        摘要替换策略
        
        策略：
        - 当 SUMMARY_REPLACE_ON_COMPRESS = True 时，用新摘要替换旧摘要
        - 否则累积摘要
        - 限制摘要最大长度
        
        Args:
            old_summary: 旧摘要
            new_summary: 新摘要
            
        Returns:
            最终摘要
        """
        try:
            from infrastructure.config.settings import (
                SUMMARY_REPLACE_ON_COMPRESS,
                SUMMARY_MAX_LENGTH,
            )
        except ImportError:
            SUMMARY_REPLACE_ON_COMPRESS = True
            SUMMARY_MAX_LENGTH = 2000
        
        if SUMMARY_REPLACE_ON_COMPRESS:
            # 替换策略：直接使用新摘要
            result = new_summary
        else:
            # 累积策略
            if old_summary:
                result = f"{old_summary}\n\n---\n\n{new_summary}"
            else:
                result = new_summary
        
        # 限制长度
        if len(result) > SUMMARY_MAX_LENGTH:
            result = result[:SUMMARY_MAX_LENGTH] + "\n[...摘要已截断...]"
        
        return result
    
    def _publish_compress_event(
        self,
        status: str,
        data: Dict[str, Any]
    ) -> None:
        """发布压缩事件"""
        if self.event_bus is None:
            return
        
        try:
            from shared.event_types import (
                EVENT_CONTEXT_COMPRESS_REQUESTED,
                EVENT_CONTEXT_COMPRESS_PREVIEW_READY,
                EVENT_CONTEXT_COMPRESS_COMPLETE,
            )
            
            event_map = {
                "started": EVENT_CONTEXT_COMPRESS_REQUESTED,
                "preview": EVENT_CONTEXT_COMPRESS_PREVIEW_READY,
                "completed": EVENT_CONTEXT_COMPRESS_COMPLETE,
                "failed": EVENT_CONTEXT_COMPRESS_COMPLETE,
            }
            
            event_type = event_map.get(status)
            if event_type:
                self.event_bus.publish(event_type, {"status": status, **data})
                
        except Exception:
            pass


# ============================================================
# 模块导出
# ============================================================

__all__ = [
    # 类
    "ContextCompressor",
    "CompressPreview",
    "StructuredSummary",
    # 常量
    "DEFAULT_KEEP_RECENT",
    "SUMMARY_PROMPT_TEMPLATE",
    "STRUCTURED_SUMMARY_PROMPT_TEMPLATE",
]
