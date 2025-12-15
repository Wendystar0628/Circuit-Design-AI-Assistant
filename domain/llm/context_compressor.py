# Context Compressor - Context Compression Logic
"""
上下文压缩 - 上下文压缩逻辑

职责：
- 生成压缩预览
- 执行上下文压缩
- 生成对话摘要

压缩策略：
1. 保留系统消息
2. 保留最近 N 条消息
3. 将旧消息压缩为摘要
4. 保留包含重要操作的消息

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

# 默认保留的最近消息数
DEFAULT_KEEP_RECENT = 5

# 摘要生成提示模板
SUMMARY_PROMPT_TEMPLATE = """请将以下对话历史压缩为简洁的摘要，保留关键信息：

{conversation}

要求：
1. 保留用户的主要需求和目标
2. 保留助手执行的关键操作
3. 保留重要的技术决策和结论
4. 使用简洁的语言，控制在 500 字以内

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
        keep_recent: int = DEFAULT_KEEP_RECENT
    ) -> Dict[str, Any]:
        """
        执行压缩操作
        
        Args:
            state: 当前状态
            llm_worker: LLM Worker 实例
            keep_recent: 保留的最近消息数
            
        Returns:
            更新后的状态副本
        """
        messages = self._get_messages(state)
        
        if len(messages) <= keep_recent + 1:  # +1 for system message
            if self.logger:
                self.logger.info("消息数量不足，无需压缩")
            return state
        
        # 选择要保留和移除的消息
        to_keep, to_remove = self._select_messages_to_keep(
            messages, keep_recent
        )
        
        if not to_remove:
            return state
        
        # 发布压缩开始事件
        self._publish_compress_event("started", {
            "remove_count": len(to_remove),
            "keep_count": len(to_keep),
        })
        
        try:
            # 生成摘要
            summary = await self._generate_summary(to_remove, llm_worker)
            
            # 通过 MessageAdapter 更新状态
            new_state = self._message_adapter.update_state_messages(state, to_keep)
            
            # 更新摘要
            existing_summary = state.get("conversation_summary", "")
            if existing_summary:
                new_state["conversation_summary"] = (
                    f"{existing_summary}\n\n---\n\n{summary}"
                )
            else:
                new_state["conversation_summary"] = summary
            
            # 发布压缩完成事件
            self._publish_compress_event("completed", {
                "removed_count": len(to_remove),
                "summary_length": len(summary),
            })
            
            if self.logger:
                self.logger.info(
                    f"上下文压缩完成: 移除 {len(to_remove)} 条消息"
                )
            
            return new_state
            
        except Exception as e:
            if self.logger:
                self.logger.error(f"压缩失败: {e}")
            
            self._publish_compress_event("failed", {"error": str(e)})
            
            # 失败时返回原状态
            return state
    
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
    "ContextCompressor",
    "CompressPreview",
    "StructuredSummary",
    "DEFAULT_KEEP_RECENT",
    "SUMMARY_PROMPT_TEMPLATE",
    "STRUCTURED_SUMMARY_PROMPT_TEMPLATE",
]
