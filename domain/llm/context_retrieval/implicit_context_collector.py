# Implicit Context Collector
"""
隐式上下文收集器 - 自动收集工作区中的隐式上下文信息

职责：
- 自动收集工作区中的隐式上下文信息，无需用户手动 @引用
- 获取当前打开的电路文件内容
- 获取最新仿真结果
- 获取设计目标
- 获取仿真错误信息

设计理念：
- 借鉴 Cursor 等 AI IDE 的上下文管理方案
- 自动收集隐式上下文，减少用户手动操作
- 与 FileWatcherWorker 集成，缓存最近修改的文件列表

触发时机：用户发送消息时自动执行
被调用方：context_retriever.py
"""

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Set


# SPICE 文件扩展名
SPICE_EXTENSIONS = {".cir", ".sp", ".spice"}


@dataclass
class ImplicitContext:
    """隐式上下文数据结构"""
    current_circuit: Optional[Dict[str, Any]] = None
    simulation_result: Optional[Dict[str, Any]] = None
    design_goals: Optional[Dict[str, Any]] = None
    simulation_error: Optional[str] = None
    
    @property
    def current_circuit_file(self) -> Optional[str]:
        """获取当前电路文件路径（兼容旧接口）"""
        if self.current_circuit:
            return self.current_circuit.get("path")
        return None
    
    @property
    def current_circuit_content(self) -> Optional[str]:
        """获取当前电路文件内容（兼容旧接口）"""
        if self.current_circuit:
            return self.current_circuit.get("content")
        return None


class ImplicitContextCollector:
    """
    隐式上下文收集器
    
    自动收集工作区中的隐式上下文信息，无需用户手动 @引用。
    """

    def __init__(self):
        self._session_state = None
        self._event_bus = None
        self._logger = None
        self._recent_files: List[str] = []
        self._subscribed = False


    # ============================================================
    # 服务获取
    # ============================================================

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

    @property
    def logger(self):
        """延迟获取日志器"""
        if self._logger is None:
            try:
                from infrastructure.utils.logger import get_logger
                self._logger = get_logger("implicit_context_collector")
            except Exception:
                pass
        return self._logger

    # ============================================================
    # 事件订阅
    # ============================================================

    def _subscribe_events(self):
        """订阅文件变化事件"""
        if self._subscribed or self.event_bus is None:
            return
        try:
            from shared.event_types import (
                EVENT_FILE_CHANGED, EVENT_FILE_CREATED, EVENT_FILE_DELETED
            )
            self.event_bus.subscribe(EVENT_FILE_CHANGED, self._on_file_changed)
            self.event_bus.subscribe(EVENT_FILE_CREATED, self._on_file_changed)
            self.event_bus.subscribe(EVENT_FILE_DELETED, self._on_file_deleted)
            self._subscribed = True
        except Exception as e:
            if self.logger:
                self.logger.debug(f"Failed to subscribe events: {e}")

    def _on_file_changed(self, event_data: Dict[str, Any]):
        """文件变化事件处理"""
        path = event_data.get("path", "")
        if path and path not in self._recent_files:
            self._recent_files.insert(0, path)
            self._recent_files = self._recent_files[:20]

    def _on_file_deleted(self, event_data: Dict[str, Any]):
        """文件删除事件处理"""
        path = event_data.get("path", "")
        if path in self._recent_files:
            self._recent_files.remove(path)


    # ============================================================
    # 主入口
    # ============================================================

    def collect(self, project_path: str) -> ImplicitContext:
        """
        收集所有隐式上下文
        
        Args:
            project_path: 项目路径
            
        Returns:
            ImplicitContext: 隐式上下文数据
        """
        self._subscribe_events()
        
        project_dir = Path(project_path)
        circuit_ai_dir = project_dir / ".circuit_ai"
        
        context = ImplicitContext()
        
        # 获取当前电路文件
        circuit_file = self.get_current_circuit_file(project_dir)
        if circuit_file:
            try:
                content = circuit_file.read_text(encoding="utf-8", errors="ignore")
                context.current_circuit = {
                    "path": str(circuit_file.relative_to(project_dir)),
                    "content": content,
                }
            except Exception as e:
                if self.logger:
                    self.logger.debug(f"Failed to read circuit file: {e}")
        
        # 获取最新仿真结果
        context.simulation_result = self.get_latest_simulation_result(project_dir)
        
        # 获取设计目标
        context.design_goals = self.get_design_goals(circuit_ai_dir)
        
        # 获取仿真错误
        context.simulation_error = self.get_simulation_error()
        
        return context

    # ============================================================
    # 收集方法
    # ============================================================

    def get_current_circuit_file(self, project_dir: Path) -> Optional[Path]:
        """
        获取当前打开的电路文件
        
        优先级：
        1. SessionState 中记录的当前文件
        2. 最近修改的文件列表中的电路文件
        3. 项目目录下最近修改的 .cir 文件
        """
        # 从 SessionState 获取
        if self.session_state:
            current_file = self.session_state.active_circuit_file
            if current_file:
                path = Path(current_file)
                if path.exists():
                    return path
        
        # 从最近文件列表获取
        for file_path in self._recent_files:
            path = Path(file_path)
            if path.exists() and path.suffix.lower() in SPICE_EXTENSIONS:
                return path
        
        # 回退：查找最近修改的 .cir 文件
        cir_files = []
        for ext in SPICE_EXTENSIONS:
            cir_files.extend(project_dir.glob(f"*{ext}"))
        
        if cir_files:
            return max(cir_files, key=lambda f: f.stat().st_mtime)
        
        return None

    def get_latest_simulation_result(
        self, project_dir: Path
    ) -> Optional[Dict[str, Any]]:
        """
        获取最新仿真结果
        
        从 simulation_results/ 目录下获取最近修改的 JSON 文件
        """
        sim_dir = project_dir / "simulation_results"
        if not sim_dir.exists():
            return None
        
        json_files = list(sim_dir.glob("*.json"))
        if not json_files:
            return None
        
        latest_file = max(json_files, key=lambda f: f.stat().st_mtime)
        
        try:
            data = json.loads(latest_file.read_text(encoding="utf-8"))
            return {
                "path": str(latest_file.relative_to(project_dir)),
                "data": data,
            }
        except Exception as e:
            if self.logger:
                self.logger.debug(f"Failed to read simulation result: {e}")
            return None

    def get_design_goals(
        self, circuit_ai_dir: Path
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
        except Exception as e:
            if self.logger:
                self.logger.debug(f"Failed to read design goals: {e}")
            return None

    def get_simulation_error(self) -> Optional[str]:
        """
        获取仿真错误信息（如有）
        
        从 SessionState.error_context 获取
        """
        if self.session_state:
            error = self.session_state.error_context
            if error:
                return str(error)
        return None

    def to_dict(self, context: ImplicitContext) -> Dict[str, Any]:
        """将 ImplicitContext 转换为字典"""
        return {
            "current_circuit": context.current_circuit,
            "simulation_result": context.simulation_result,
            "design_goals": context.design_goals,
            "simulation_error": context.simulation_error,
        }


__all__ = ["ImplicitContextCollector", "ImplicitContext", "SPICE_EXTENSIONS"]
