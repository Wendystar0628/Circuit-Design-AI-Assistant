# Simulation Context Collector - Collect Simulation Results and Errors
"""
仿真上下文收集器 - 收集仿真结果和仿真错误信息

职责：
- 从 sim_result_path 指向的 JSON 文件加载仿真结果
- 格式化仿真指标摘要
- 格式化仿真错误信息
- 标注数据新鲜度

数据来源（遵循 GraphState 的 Reference-Based 原则）：
- 仿真结果：从 sim_result_path 指向的 JSON 文件加载
- 仿真错误：从 error_context 字符串读取（轻量摘要）
- 仿真时间戳：从仿真结果文件的 timestamp 字段读取

实现协议：ContextSource
优先级：ContextPriority.HIGH（10）
被调用方：implicit_context_aggregator.py
"""

import json
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from domain.llm.context_retrieval.context_source_protocol import (
    CollectionContext,
    ContextPriority,
    ContextResult,
    ContextSource,
)


# ============================================================
# 常量定义
# ============================================================

# 关键仿真指标（按重要性排序）
KEY_METRICS = [
    "gain", "bandwidth", "phase_margin", "gain_margin",
    "input_impedance", "output_impedance", "slew_rate",
    "cmrr", "psrr", "noise", "thd", "power_consumption",
]


class SimulationContextCollector:
    """
    仿真上下文收集器
    
    实现 ContextSource 协议，收集仿真结果和错误信息。
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
                self._logger = get_logger("simulation_context_collector")
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
        异步收集仿真上下文
        
        Args:
            context: 收集上下文
            
        Returns:
            ContextResult: 收集结果
        """
        source_name = self.get_source_name()
        content_parts: List[str] = []
        metadata: Dict[str, Any] = {}
        
        # 收集仿真结果
        if context.sim_result_path:
            sim_content, sim_metadata = await self._load_simulation_result_async(
                context.project_path, context.sim_result_path
            )
            if sim_content:
                content_parts.append(sim_content)
                metadata.update(sim_metadata)
        
        # 收集仿真错误
        if context.error_context:
            error_content = self._format_error_context(context.error_context)
            if error_content:
                content_parts.append(error_content)
                metadata["has_error"] = True
        
        # 如果没有任何内容，返回空结果
        if not content_parts:
            return ContextResult.empty(source_name)
        
        # 组合内容
        full_content = "\n\n".join(content_parts)
        token_count = self._estimate_tokens(full_content)
        
        return ContextResult(
            content=full_content,
            token_count=token_count,
            source_name=source_name,
            priority=self.get_priority(),
            metadata=metadata,
        )

    def get_priority(self) -> ContextPriority:
        """获取优先级"""
        return ContextPriority.HIGH

    def get_source_name(self) -> str:
        """获取源名称"""
        return "simulation_context"

    # ============================================================
    # 内部方法
    # ============================================================

    async def _load_simulation_result_async(
        self,
        project_path: str,
        sim_result_path: str,
    ) -> tuple[str, Dict[str, Any]]:
        """
        异步加载仿真结果
        
        Args:
            project_path: 项目路径
            sim_result_path: 仿真结果文件相对路径
            
        Returns:
            tuple: (格式化内容, 元数据)
        """
        import asyncio
        
        file_path = Path(project_path) / sim_result_path
        
        if not file_path.exists():
            if self.logger:
                self.logger.debug(f"Simulation result file not found: {file_path}")
            return "", {}
        
        try:
            # 异步读取文件
            if self.async_file_ops:
                content = await self.async_file_ops.read_file_async(str(file_path))
            else:
                content = await asyncio.to_thread(
                    lambda: file_path.read_text(encoding="utf-8")
                )
            
            # 解析 JSON
            result_data = json.loads(content)
            
            # 格式化内容
            formatted = self._format_metrics_summary(result_data)
            
            # 提取元数据
            metadata = self._extract_result_metadata(result_data, file_path)
            
            return formatted, metadata
            
        except json.JSONDecodeError as e:
            if self.logger:
                self.logger.warning(f"Invalid JSON in simulation result: {e}")
            return "", {}
        except Exception as e:
            if self.logger:
                self.logger.error(f"Failed to load simulation result: {e}")
            return "", {}

    def _format_metrics_summary(self, result_data: Dict[str, Any]) -> str:
        """
        格式化仿真指标摘要
        
        Args:
            result_data: 仿真结果数据
            
        Returns:
            str: 格式化的摘要文本
        """
        lines = ["=== Simulation Results ==="]
        
        # 提取时间戳
        timestamp = result_data.get("timestamp")
        if timestamp:
            freshness = self._calculate_freshness(timestamp)
            lines.append(f"Data freshness: {freshness}")
        
        # 提取分析类型
        analysis_type = result_data.get("analysis_type", "unknown")
        lines.append(f"Analysis type: {analysis_type}")
        
        # 提取仿真配置
        config = result_data.get("config", {})
        if config:
            config_items = []
            if "frequency_range" in config:
                config_items.append(f"Freq: {config['frequency_range']}")
            if "temperature" in config:
                config_items.append(f"Temp: {config['temperature']}")
            if config_items:
                lines.append(f"Config: {', '.join(config_items)}")
        
        lines.append("")
        lines.append("Key Metrics:")
        
        # 提取指标
        metrics = result_data.get("metrics", {})
        if not metrics:
            # 尝试从顶层提取
            metrics = {k: v for k, v in result_data.items() 
                      if k in KEY_METRICS or k.endswith("_db") or k.endswith("_hz")}
        
        # 按重要性排序输出
        for key in KEY_METRICS:
            if key in metrics:
                value = metrics[key]
                formatted_value = self._format_metric_value(key, value)
                lines.append(f"  - {key}: {formatted_value}")
        
        # 输出其他指标
        other_metrics = {k: v for k, v in metrics.items() if k not in KEY_METRICS}
        for key, value in list(other_metrics.items())[:10]:
            formatted_value = self._format_metric_value(key, value)
            lines.append(f"  - {key}: {formatted_value}")
        
        # 提取状态
        status = result_data.get("status", "unknown")
        if status != "success":
            lines.append(f"\nStatus: {status}")
        
        return "\n".join(lines)

    def _format_metric_value(self, key: str, value: Any) -> str:
        """格式化指标值"""
        if isinstance(value, float):
            # 根据指标类型添加单位
            if "gain" in key.lower():
                return f"{value:.2f} dB"
            elif "bandwidth" in key.lower() or "frequency" in key.lower():
                if value >= 1e6:
                    return f"{value/1e6:.2f} MHz"
                elif value >= 1e3:
                    return f"{value/1e3:.2f} kHz"
                else:
                    return f"{value:.2f} Hz"
            elif "phase" in key.lower() or "margin" in key.lower():
                return f"{value:.1f}°"
            elif "impedance" in key.lower():
                if value >= 1e6:
                    return f"{value/1e6:.2f} MΩ"
                elif value >= 1e3:
                    return f"{value/1e3:.2f} kΩ"
                else:
                    return f"{value:.2f} Ω"
            else:
                return f"{value:.4g}"
        elif isinstance(value, dict):
            # 复合值（如带单位的值）
            if "value" in value and "unit" in value:
                return f"{value['value']} {value['unit']}"
            return str(value)
        else:
            return str(value)

    def _calculate_freshness(self, timestamp: str) -> str:
        """
        计算数据新鲜度
        
        Args:
            timestamp: ISO 格式时间戳
            
        Returns:
            str: 新鲜度描述
        """
        try:
            # 解析时间戳
            if "T" in timestamp:
                dt = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
            else:
                dt = datetime.strptime(timestamp, "%Y-%m-%d %H:%M:%S")
            
            # 计算时间差
            now = datetime.now()
            if dt.tzinfo:
                now = datetime.now(dt.tzinfo)
            
            delta = now - dt
            
            if delta.total_seconds() < 60:
                return "just now"
            elif delta.total_seconds() < 3600:
                minutes = int(delta.total_seconds() / 60)
                return f"{minutes} minute{'s' if minutes > 1 else ''} ago"
            elif delta.total_seconds() < 86400:
                hours = int(delta.total_seconds() / 3600)
                return f"{hours} hour{'s' if hours > 1 else ''} ago"
            else:
                days = int(delta.total_seconds() / 86400)
                return f"{days} day{'s' if days > 1 else ''} ago"
                
        except Exception:
            return "unknown"

    def _extract_result_metadata(
        self, result_data: Dict[str, Any], file_path: Path
    ) -> Dict[str, Any]:
        """提取仿真结果元数据"""
        return {
            "file_path": str(file_path),
            "timestamp": result_data.get("timestamp"),
            "analysis_type": result_data.get("analysis_type"),
            "status": result_data.get("status", "unknown"),
            "metric_count": len(result_data.get("metrics", {})),
        }

    def _format_error_context(self, error_context: str) -> str:
        """
        格式化错误上下文
        
        Args:
            error_context: 错误上下文字符串
            
        Returns:
            str: 格式化的错误信息
        """
        if not error_context:
            return ""
        
        lines = [
            "=== Simulation Error ===",
            "The last simulation encountered an error:",
            "",
            error_context,
            "",
            "Please address this error before proceeding.",
        ]
        
        return "\n".join(lines)

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
    "SimulationContextCollector",
    "KEY_METRICS",
]
