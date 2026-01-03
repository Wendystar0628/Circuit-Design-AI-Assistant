# Design Goals Collector - Collect Current Design Goals
"""
设计目标收集器 - 收集当前设计目标

职责：
- 从 design_goals_path 指向的 JSON 文件加载设计目标
- 格式化为 Prompt 友好的文本
- 计算目标达成进度（如有仿真结果）

数据来源：
- 设计目标：从 design_goals_path 指向的 JSON 文件加载
- 默认路径：.circuit_ai/design_goals.json

实现协议：ContextSource
优先级：ContextPriority.MEDIUM（20）
被调用方：implicit_context_aggregator.py
"""

import json
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from domain.llm.context_retrieval.context_source_protocol import (
    CollectionContext,
    ContextPriority,
    ContextResult,
    ContextSource,
)


class DesignGoalsCollector:
    """
    设计目标收集器
    
    实现 ContextSource 协议，收集当前设计目标。
    """

    def __init__(self):
        self._logger = None
        self._async_file_ops = None

    # ============================================================
    # 服务获取
    # ============================================================

    @property
    def logger(self):
        """延迟获取日志器"""
        if self._logger is None:
            try:
                from infrastructure.utils.logger import get_logger
                self._logger = get_logger("design_goals_collector")
            except Exception:
                pass
        return self._logger

    @property
    def async_file_ops(self):
        """延迟获取异步文件操作服务"""
        if self._async_file_ops is None:
            try:
                from shared.service_locator import ServiceLocator
                from shared.service_names import SVC_ASYNC_FILE_OPS
                self._async_file_ops = ServiceLocator.get_optional(SVC_ASYNC_FILE_OPS)
            except Exception:
                pass
        return self._async_file_ops

    # ============================================================
    # ContextSource 协议实现
    # ============================================================

    async def collect_async(self, context: CollectionContext) -> ContextResult:
        """
        异步收集设计目标
        
        Args:
            context: 收集上下文
            
        Returns:
            ContextResult: 收集结果
        """
        source_name = self.get_source_name()
        
        # 获取设计目标文件路径
        goals_path = context.design_goals_path or ".circuit_ai/design_goals.json"
        file_path = Path(context.project_path) / goals_path
        
        # 检查文件是否存在
        if not file_path.exists():
            if self.logger:
                self.logger.debug(f"Design goals file not found: {file_path}")
            return ContextResult.empty(source_name)
        
        try:
            # 异步加载设计目标
            goals_data = await self._load_goals_async(file_path)
            
            if not goals_data:
                return ContextResult.empty(source_name)
            
            # 格式化内容
            formatted_content = self._format_goals_for_prompt(
                goals_data, context.last_metrics
            )
            
            # 估算 Token 数
            token_count = self._estimate_tokens(formatted_content)
            
            # 提取元数据
            metadata = {
                "file_path": str(file_path),
                "goal_count": len(goals_data.get("goals", [])),
                "has_metrics": bool(context.last_metrics),
            }
            
            return ContextResult(
                content=formatted_content,
                token_count=token_count,
                source_name=source_name,
                priority=self.get_priority(),
                metadata=metadata,
            )
            
        except Exception as e:
            if self.logger:
                self.logger.error(f"Failed to collect design goals: {e}")
            return ContextResult.empty(source_name)

    def get_priority(self) -> ContextPriority:
        """获取优先级"""
        return ContextPriority.MEDIUM

    def get_source_name(self) -> str:
        """获取源名称"""
        return "design_goals"

    # ============================================================
    # 内部方法
    # ============================================================

    async def _load_goals_async(self, file_path: Path) -> Dict[str, Any]:
        """
        异步加载设计目标
        
        Args:
            file_path: 文件路径
            
        Returns:
            Dict: 设计目标数据
        """
        import asyncio
        
        try:
            if self.async_file_ops:
                content = await self.async_file_ops.read_file_async(str(file_path))
            else:
                content = await asyncio.to_thread(
                    lambda: file_path.read_text(encoding="utf-8")
                )
            
            return json.loads(content)
            
        except json.JSONDecodeError as e:
            if self.logger:
                self.logger.warning(f"Invalid JSON in design goals: {e}")
            return {}
        except Exception as e:
            if self.logger:
                self.logger.error(f"Failed to load design goals: {e}")
            return {}

    def _format_goals_for_prompt(
        self,
        goals_data: Dict[str, Any],
        current_metrics: Dict[str, Any],
    ) -> str:
        """
        格式化设计目标为 Prompt 友好的文本
        
        Args:
            goals_data: 设计目标数据
            current_metrics: 当前仿真指标
            
        Returns:
            str: 格式化的文本
        """
        lines = ["=== Design Goals ==="]
        
        # 提取项目描述
        description = goals_data.get("description")
        if description:
            lines.append(f"Project: {description}")
            lines.append("")
        
        # 提取目标列表
        goals = goals_data.get("goals", [])
        
        if not goals:
            # 尝试从顶层提取（兼容旧格式）
            goals = self._extract_goals_from_flat(goals_data)
        
        if not goals:
            lines.append("No design goals defined.")
            return "\n".join(lines)
        
        lines.append("Target Specifications:")
        
        # 计算目标达成进度
        progress_info = self._calculate_goal_progress(goals, current_metrics)
        
        for goal in goals:
            goal_line = self._format_single_goal(goal, progress_info)
            lines.append(goal_line)
        
        # 添加进度摘要
        if progress_info["total"] > 0:
            lines.append("")
            achieved = progress_info["achieved"]
            total = progress_info["total"]
            percentage = (achieved / total) * 100
            lines.append(f"Progress: {achieved}/{total} goals achieved ({percentage:.0f}%)")
            
            # 列出未达成的目标
            if progress_info["unmet"]:
                lines.append("")
                lines.append("Unmet goals (need attention):")
                for unmet in progress_info["unmet"][:5]:
                    lines.append(f"  - {unmet}")
        
        return "\n".join(lines)

    def _format_single_goal(
        self,
        goal: Dict[str, Any],
        progress_info: Dict[str, Any],
    ) -> str:
        """格式化单个目标"""
        name = goal.get("name", goal.get("metric", "unknown"))
        target = goal.get("target", goal.get("value", "N/A"))
        tolerance = goal.get("tolerance", "")
        priority = goal.get("priority", "normal")
        
        # 构建目标行
        parts = [f"  - {name}: {target}"]
        
        if tolerance:
            parts.append(f"(±{tolerance})")
        
        # 添加优先级标记
        if priority == "high" or priority == "critical":
            parts.append("[HIGH]")
        
        # 添加达成状态
        status = progress_info.get("status", {}).get(name)
        if status == "achieved":
            parts.append("✓")
        elif status == "unmet":
            current = progress_info.get("current", {}).get(name)
            if current:
                parts.append(f"(current: {current})")
        
        return " ".join(parts)

    def _extract_goals_from_flat(
        self, goals_data: Dict[str, Any]
    ) -> List[Dict[str, Any]]:
        """
        从扁平结构提取目标（兼容旧格式）
        
        Args:
            goals_data: 设计目标数据
            
        Returns:
            List: 目标列表
        """
        goals = []
        
        # 常见的目标字段名
        goal_fields = [
            "gain", "bandwidth", "phase_margin", "gain_margin",
            "input_impedance", "output_impedance", "slew_rate",
            "cmrr", "psrr", "noise", "thd", "power",
        ]
        
        for field in goal_fields:
            if field in goals_data:
                value = goals_data[field]
                if isinstance(value, dict):
                    goals.append({
                        "name": field,
                        "target": value.get("target", value.get("value")),
                        "tolerance": value.get("tolerance"),
                        "priority": value.get("priority", "normal"),
                    })
                else:
                    goals.append({
                        "name": field,
                        "target": value,
                    })
        
        return goals

    def _calculate_goal_progress(
        self,
        goals: List[Dict[str, Any]],
        current_metrics: Dict[str, Any],
    ) -> Dict[str, Any]:
        """
        计算目标达成进度
        
        Args:
            goals: 目标列表
            current_metrics: 当前仿真指标
            
        Returns:
            Dict: 进度信息
        """
        progress = {
            "total": len(goals),
            "achieved": 0,
            "unmet": [],
            "status": {},
            "current": {},
        }
        
        if not current_metrics:
            return progress
        
        for goal in goals:
            name = goal.get("name", goal.get("metric", ""))
            target = goal.get("target", goal.get("value"))
            tolerance = goal.get("tolerance")
            
            # 查找当前值
            current = current_metrics.get(name)
            if current is None:
                # 尝试模糊匹配
                for key in current_metrics:
                    if name.lower() in key.lower():
                        current = current_metrics[key]
                        break
            
            if current is not None:
                progress["current"][name] = current
                
                # 检查是否达成
                is_achieved = self._check_goal_achieved(target, current, tolerance)
                
                if is_achieved:
                    progress["achieved"] += 1
                    progress["status"][name] = "achieved"
                else:
                    progress["unmet"].append(name)
                    progress["status"][name] = "unmet"
        
        return progress

    def _check_goal_achieved(
        self,
        target: Any,
        current: Any,
        tolerance: Optional[str],
    ) -> bool:
        """
        检查目标是否达成
        
        Args:
            target: 目标值
            current: 当前值
            tolerance: 容差
            
        Returns:
            bool: 是否达成
        """
        try:
            # 解析目标值
            target_num = self._parse_numeric_value(target)
            current_num = self._parse_numeric_value(current)
            
            if target_num is None or current_num is None:
                return False
            
            # 解析容差
            if tolerance:
                tol_num = self._parse_tolerance(tolerance, target_num)
            else:
                # 默认 10% 容差
                tol_num = abs(target_num) * 0.1
            
            # 检查是否在容差范围内
            return abs(current_num - target_num) <= tol_num
            
        except Exception:
            return False

    def _parse_numeric_value(self, value: Any) -> Optional[float]:
        """解析数值"""
        if isinstance(value, (int, float)):
            return float(value)
        
        if isinstance(value, str):
            # 移除单位
            import re
            match = re.match(r"([+-]?\d*\.?\d+)", value.replace(",", ""))
            if match:
                return float(match.group(1))
        
        if isinstance(value, dict):
            return self._parse_numeric_value(value.get("value"))
        
        return None

    def _parse_tolerance(self, tolerance: str, target: float) -> float:
        """解析容差"""
        tolerance = str(tolerance).strip()
        
        # 百分比容差
        if "%" in tolerance:
            import re
            match = re.search(r"(\d+\.?\d*)", tolerance)
            if match:
                percent = float(match.group(1))
                return abs(target) * percent / 100
        
        # 绝对容差
        return self._parse_numeric_value(tolerance) or abs(target) * 0.1

    def _estimate_tokens(self, text: str) -> int:
        """估算 Token 数"""
        if not text:
            return 0
        
        try:
            from domain.llm.token_counter import count_tokens
            return count_tokens(text)
        except ImportError:
            return len(text) // 4


# ============================================================
# 模块导出
# ============================================================

__all__ = [
    "DesignGoalsCollector",
]
