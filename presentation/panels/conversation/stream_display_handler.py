# Stream Display Handler
"""
流式显示处理器

职责：
- 专注于流式输出的显示逻辑
- 处理思考/回答阶段切换
- 实现节流聚合减少 UI 刷新频率
- 管理自动滚动行为

使用示例：
    from presentation.panels.conversation.stream_display_handler import (
        StreamDisplayHandler
    )
    
    handler = StreamDisplayHandler()
    handler.start_stream()
    handler.append_chunk(chunk, chunk_type)
    handler.finish_stream()
"""

from typing import Callable, Optional

from PyQt6.QtCore import QObject, QTimer, pyqtSignal

# ============================================================
# 常量定义
# ============================================================

# 节流间隔（毫秒）
DEFAULT_THROTTLE_MS = 50
MIN_THROTTLE_MS = 20
MAX_THROTTLE_MS = 200

# 阶段类型
PHASE_REASONING = "reasoning"
PHASE_CONTENT = "content"


# ============================================================
# StreamDisplayHandler 类
# ============================================================

class StreamDisplayHandler(QObject):
    """
    流式显示处理器
    
    专注于流式输出的显示逻辑，实现节流聚合。
    """
    
    # 信号定义
    content_updated = pyqtSignal(str, str)    # 内容更新 (content, reasoning)
    phase_switched = pyqtSignal(str)          # 阶段切换 (new_phase)
    stream_started = pyqtSignal()             # 流式开始
    stream_finished = pyqtSignal()            # 流式结束
    scroll_requested = pyqtSignal()           # 请求滚动到底部
    
    def __init__(self, parent: Optional[QObject] = None):
        """初始化流式显示处理器"""
        super().__init__(parent)
        
        # 内部状态
        self._is_streaming = False
        self._current_phase = PHASE_REASONING
        self._content_buffer = ""
        self._reasoning_buffer = ""
        self._pending_content = ""
        self._pending_reasoning = ""
        
        # 自动滚动状态
        self._auto_scroll_enabled = True
        
        # 节流定时器
        self._throttle_ms = DEFAULT_THROTTLE_MS
        self._throttle_timer: Optional[QTimer] = None
        self._setup_throttle_timer()
    
    def _setup_throttle_timer(self) -> None:
        """设置节流定时器"""
        self._throttle_timer = QTimer(self)
        self._throttle_timer.setInterval(self._throttle_ms)
        self._throttle_timer.timeout.connect(self._flush_buffer)
    
    # ============================================================
    # 公共方法
    # ============================================================
    
    def start_stream(self) -> None:
        """开始流式显示"""
        self._is_streaming = True
        self._current_phase = PHASE_REASONING
        self._content_buffer = ""
        self._reasoning_buffer = ""
        self._pending_content = ""
        self._pending_reasoning = ""
        
        # 启动节流定时器
        if self._throttle_timer:
            self._throttle_timer.start()
        
        self.stream_started.emit()
    
    def append_chunk(self, chunk: str, chunk_type: str = PHASE_CONTENT) -> None:
        """
        追加流式数据块
        
        Args:
            chunk: 数据块内容
            chunk_type: 块类型（reasoning/content）
        """
        if not self._is_streaming:
            return
        
        # 检测阶段切换
        if chunk_type != self._current_phase:
            self.handle_phase_switch(chunk_type)
        
        # 追加到待处理缓冲区
        if chunk_type == PHASE_REASONING:
            self._pending_reasoning += chunk
        else:
            self._pending_content += chunk
    
    def handle_phase_switch(self, new_phase: str) -> None:
        """
        处理思考/回答阶段切换
        
        Args:
            new_phase: 新阶段类型
        """
        # 先刷新当前缓冲区
        self._flush_buffer()
        
        self._current_phase = new_phase
        self.phase_switched.emit(new_phase)
    
    def finish_stream(self) -> None:
        """结束流式显示"""
        # 刷新剩余缓冲区
        self._flush_buffer()
        
        # 停止节流定时器
        if self._throttle_timer:
            self._throttle_timer.stop()
        
        self._is_streaming = False
        self.stream_finished.emit()
    
    def get_content(self) -> str:
        """获取当前内容"""
        return self._content_buffer + self._pending_content
    
    def get_reasoning(self) -> str:
        """获取当前思考内容"""
        return self._reasoning_buffer + self._pending_reasoning
    
    def is_streaming(self) -> bool:
        """检查是否正在流式输出"""
        return self._is_streaming
    
    def get_current_phase(self) -> str:
        """获取当前阶段"""
        return self._current_phase


    # ============================================================
    # 节流处理
    # ============================================================
    
    def set_throttle_interval(self, ms: int) -> None:
        """
        设置节流间隔
        
        Args:
            ms: 间隔毫秒数（20-200）
        """
        self._throttle_ms = max(MIN_THROTTLE_MS, min(MAX_THROTTLE_MS, ms))
        if self._throttle_timer:
            self._throttle_timer.setInterval(self._throttle_ms)
    
    def get_throttle_interval(self) -> int:
        """获取节流间隔"""
        return self._throttle_ms
    
    def _flush_buffer(self) -> None:
        """刷新缓冲区，更新显示"""
        if not self._pending_content and not self._pending_reasoning:
            return
        
        # 合并到主缓冲区
        if self._pending_reasoning:
            self._reasoning_buffer += self._pending_reasoning
            self._pending_reasoning = ""
        
        if self._pending_content:
            self._content_buffer += self._pending_content
            self._pending_content = ""
        
        # 发出更新信号
        self.content_updated.emit(self._content_buffer, self._reasoning_buffer)
        
        # 请求滚动
        if self._auto_scroll_enabled:
            self.scroll_requested.emit()
    
    # ============================================================
    # 自动滚动控制
    # ============================================================
    
    def set_auto_scroll(self, enabled: bool) -> None:
        """设置自动滚动"""
        self._auto_scroll_enabled = enabled
    
    def is_auto_scroll_enabled(self) -> bool:
        """检查自动滚动是否启用"""
        return self._auto_scroll_enabled
    
    def pause_auto_scroll(self) -> None:
        """暂停自动滚动（用户手动滚动时）"""
        self._auto_scroll_enabled = False
    
    def resume_auto_scroll(self) -> None:
        """恢复自动滚动"""
        self._auto_scroll_enabled = True
    
    # ============================================================
    # 清理
    # ============================================================
    
    def clear(self) -> None:
        """清空所有状态"""
        self._is_streaming = False
        self._current_phase = PHASE_REASONING
        self._content_buffer = ""
        self._reasoning_buffer = ""
        self._pending_content = ""
        self._pending_reasoning = ""
        
        if self._throttle_timer:
            self._throttle_timer.stop()
    
    def cleanup(self) -> None:
        """清理资源"""
        self.clear()
        if self._throttle_timer:
            self._throttle_timer.stop()
            self._throttle_timer.deleteLater()
            self._throttle_timer = None


# ============================================================
# 模块导出
# ============================================================

__all__ = [
    "StreamDisplayHandler",
    # 常量
    "PHASE_REASONING",
    "PHASE_CONTENT",
    "DEFAULT_THROTTLE_MS",
]

