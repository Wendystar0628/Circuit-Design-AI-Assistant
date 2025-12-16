# Context Compress Dialog
"""
上下文压缩预览对话框

职责：
- 显示压缩预览信息，让用户确认或调整压缩参数
- 展示当前上下文状态和压缩后预估
- 提供摘要预览和消息分类预览

使用示例：
    from presentation.dialogs.context_compress_dialog import ContextCompressDialog
    
    dialog = ContextCompressDialog(parent)
    if dialog.exec() == QDialog.DialogCode.Accepted:
        # 执行压缩
        pass
"""

from typing import Any, Dict, List, Optional

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QDialog,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QFrame,
    QPushButton,
    QSpinBox,
    QTextEdit,
    QGroupBox,
    QProgressBar,
    QCheckBox,
    QScrollArea,
    QWidget,
    QSizePolicy,
)

# ============================================================
# 样式常量
# ============================================================

PRIMARY_COLOR = "#4a9eff"
SUCCESS_COLOR = "#4caf50"
WARNING_COLOR = "#ff9800"
BORDER_COLOR = "#e0e0e0"
BACKGROUND_COLOR = "#f5f5f5"


# ============================================================
# ContextCompressDialog 类
# ============================================================

class ContextCompressDialog(QDialog):
    """
    上下文压缩预览对话框
    
    显示压缩预览信息，让用户确认或调整压缩参数。
    """
    
    # 信号定义
    preview_requested = pyqtSignal()           # 请求生成摘要预览
    compress_confirmed = pyqtSignal(dict)      # 确认压缩 (options)
    
    def __init__(self, parent: Optional[QWidget] = None):
        """初始化对话框"""
        super().__init__(parent)
        
        # 内部状态
        self._current_stats: Dict[str, Any] = {}
        self._preview_summary: str = ""
        self._message_categories: Dict[str, List] = {}
        
        # UI 组件引用
        self._message_count_label: Optional[QLabel] = None
        self._token_usage_label: Optional[QLabel] = None
        self._usage_progress: Optional[QProgressBar] = None
        self._keep_count_spin: Optional[QSpinBox] = None
        self._estimated_summary_label: Optional[QLabel] = None
        self._estimated_usage_label: Optional[QLabel] = None
        self._summary_preview: Optional[QTextEdit] = None
        self._preview_button: Optional[QPushButton] = None
        self._confirm_button: Optional[QPushButton] = None
        
        # 延迟获取的服务
        self._i18n = None
        self._context_manager = None
        
        # 初始化 UI
        self._setup_ui()
    
    @property
    def i18n(self):
        """延迟获取国际化管理器"""
        if self._i18n is None:
            try:
                from shared.service_locator import ServiceLocator
                from shared.service_names import SVC_I18N_MANAGER
                self._i18n = ServiceLocator.get_optional(SVC_I18N_MANAGER)
            except Exception:
                pass
        return self._i18n
    
    @property
    def context_manager(self):
        """延迟获取上下文管理器"""
        if self._context_manager is None:
            try:
                from shared.service_locator import ServiceLocator
                from shared.service_names import SVC_CONTEXT_MANAGER
                self._context_manager = ServiceLocator.get_optional(SVC_CONTEXT_MANAGER)
            except Exception:
                pass
        return self._context_manager
    
    def _get_text(self, key: str, default: str = "") -> str:
        """获取国际化文本"""
        if self.i18n:
            return self.i18n.get_text(key, default)
        return default


    def _setup_ui(self) -> None:
        """设置 UI 布局"""
        self.setWindowTitle(
            self._get_text("dialog.compress.title", "压缩上下文")
        )
        self.setMinimumSize(500, 600)
        self.setModal(True)
        
        main_layout = QVBoxLayout(self)
        main_layout.setSpacing(16)
        
        # 1. 当前状态区
        current_group = self._create_current_status_group()
        main_layout.addWidget(current_group)
        
        # 2. 压缩预估区
        estimate_group = self._create_estimate_group()
        main_layout.addWidget(estimate_group)
        
        # 3. 摘要预览区
        preview_group = self._create_preview_group()
        main_layout.addWidget(preview_group, 1)
        
        # 4. 消息分类预览（可折叠）
        category_group = self._create_category_group()
        main_layout.addWidget(category_group)
        
        # 5. 操作按钮
        buttons_layout = self._create_buttons()
        main_layout.addLayout(buttons_layout)
    
    def _create_current_status_group(self) -> QGroupBox:
        """创建当前状态区"""
        group = QGroupBox(
            self._get_text("dialog.compress.current_status", "当前状态")
        )
        layout = QVBoxLayout(group)
        
        # 消息数量
        msg_row = QHBoxLayout()
        msg_row.addWidget(QLabel(
            self._get_text("dialog.compress.message_count", "消息数量：")
        ))
        self._message_count_label = QLabel("0 条")
        self._message_count_label.setStyleSheet("font-weight: bold;")
        msg_row.addWidget(self._message_count_label)
        msg_row.addStretch()
        layout.addLayout(msg_row)
        
        # Token 占用
        token_row = QHBoxLayout()
        token_row.addWidget(QLabel(
            self._get_text("dialog.compress.token_usage", "Token 占用：")
        ))
        self._token_usage_label = QLabel("0 / 0 (0%)")
        self._token_usage_label.setStyleSheet("font-weight: bold;")
        token_row.addWidget(self._token_usage_label)
        token_row.addStretch()
        layout.addLayout(token_row)
        
        # 进度条
        self._usage_progress = QProgressBar()
        self._usage_progress.setFixedHeight(8)
        self._usage_progress.setTextVisible(False)
        self._usage_progress.setRange(0, 100)
        self._usage_progress.setStyleSheet("""
            QProgressBar {
                background-color: #e0e0e0;
                border-radius: 4px;
            }
            QProgressBar::chunk {
                background-color: #4caf50;
                border-radius: 4px;
            }
        """)
        layout.addWidget(self._usage_progress)
        
        return group
    
    def _create_estimate_group(self) -> QGroupBox:
        """创建压缩预估区"""
        group = QGroupBox(
            self._get_text("dialog.compress.estimate", "压缩预估")
        )
        layout = QVBoxLayout(group)
        
        # 保留消息数
        keep_row = QHBoxLayout()
        keep_row.addWidget(QLabel(
            self._get_text("dialog.compress.keep_count", "保留最近消息数：")
        ))
        self._keep_count_spin = QSpinBox()
        self._keep_count_spin.setRange(2, 20)
        self._keep_count_spin.setValue(5)
        self._keep_count_spin.valueChanged.connect(self._on_keep_count_changed)
        keep_row.addWidget(self._keep_count_spin)
        keep_row.addStretch()
        layout.addLayout(keep_row)
        
        # 预计生成摘要
        summary_row = QHBoxLayout()
        summary_row.addWidget(QLabel(
            self._get_text("dialog.compress.estimated_summary", "预计生成摘要：")
        ))
        self._estimated_summary_label = QLabel("约 2,000 tokens")
        summary_row.addWidget(self._estimated_summary_label)
        summary_row.addStretch()
        layout.addLayout(summary_row)
        
        # 压缩后占用
        after_row = QHBoxLayout()
        after_row.addWidget(QLabel(
            self._get_text("dialog.compress.estimated_after", "压缩后占用：")
        ))
        self._estimated_usage_label = QLabel("约 12,000 tokens (12%)")
        self._estimated_usage_label.setStyleSheet(f"color: {SUCCESS_COLOR}; font-weight: bold;")
        after_row.addWidget(self._estimated_usage_label)
        after_row.addStretch()
        layout.addLayout(after_row)
        
        return group
    
    def _create_preview_group(self) -> QGroupBox:
        """创建摘要预览区"""
        group = QGroupBox(
            self._get_text("dialog.compress.preview", "摘要预览")
        )
        layout = QVBoxLayout(group)
        
        # 预览文本框
        self._summary_preview = QTextEdit()
        self._summary_preview.setReadOnly(True)
        self._summary_preview.setPlaceholderText(
            self._get_text(
                "dialog.compress.preview_hint",
                "点击「预览摘要」按钮生成摘要预览..."
            )
        )
        self._summary_preview.setStyleSheet(f"""
            QTextEdit {{
                background-color: {BACKGROUND_COLOR};
                border: 1px solid {BORDER_COLOR};
                border-radius: 4px;
                padding: 8px;
            }}
        """)
        layout.addWidget(self._summary_preview)
        
        # 预览按钮
        self._preview_button = QPushButton(
            self._get_text("dialog.compress.btn_preview", "预览摘要")
        )
        self._preview_button.setStyleSheet(f"""
            QPushButton {{
                background-color: {BACKGROUND_COLOR};
                border: 1px solid {BORDER_COLOR};
                border-radius: 4px;
                padding: 8px 16px;
            }}
            QPushButton:hover {{
                background-color: #e8e8e8;
            }}
        """)
        self._preview_button.clicked.connect(self._on_preview_clicked)
        layout.addWidget(self._preview_button)
        
        return group


    def _create_category_group(self) -> QGroupBox:
        """创建消息分类预览区（可折叠）"""
        group = QGroupBox(
            self._get_text("dialog.compress.categories", "消息分类预览")
        )
        group.setCheckable(True)
        group.setChecked(False)
        
        layout = QVBoxLayout(group)
        
        # 滚动区域
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setMaximumHeight(150)
        scroll.setStyleSheet("""
            QScrollArea {
                border: none;
            }
        """)
        
        content = QWidget()
        content_layout = QVBoxLayout(content)
        content_layout.setSpacing(8)
        
        # 必保留消息
        keep_label = QLabel(
            self._get_text("dialog.compress.must_keep", "必保留消息（系统消息、工具调用）：")
        )
        keep_label.setStyleSheet("font-weight: bold; color: #4caf50;")
        content_layout.addWidget(keep_label)
        
        self._keep_messages_label = QLabel("0 条")
        content_layout.addWidget(self._keep_messages_label)
        
        # 将被压缩的消息
        compress_label = QLabel(
            self._get_text("dialog.compress.will_compress", "将被压缩的消息：")
        )
        compress_label.setStyleSheet("font-weight: bold; color: #ff9800;")
        content_layout.addWidget(compress_label)
        
        self._compress_messages_label = QLabel("0 条")
        content_layout.addWidget(self._compress_messages_label)
        
        content_layout.addStretch()
        scroll.setWidget(content)
        layout.addWidget(scroll)
        
        return group
    
    def _create_buttons(self) -> QHBoxLayout:
        """创建操作按钮"""
        layout = QHBoxLayout()
        layout.addStretch()
        
        # 取消按钮
        cancel_btn = QPushButton(self._get_text("btn.cancel", "取消"))
        cancel_btn.setStyleSheet("""
            QPushButton {
                background-color: #f5f5f5;
                border: 1px solid #e0e0e0;
                border-radius: 4px;
                padding: 8px 24px;
            }
            QPushButton:hover {
                background-color: #e8e8e8;
            }
        """)
        cancel_btn.clicked.connect(self.reject)
        layout.addWidget(cancel_btn)
        
        # 确认压缩按钮
        self._confirm_button = QPushButton(
            self._get_text("dialog.compress.btn_confirm", "确认压缩")
        )
        self._confirm_button.setStyleSheet(f"""
            QPushButton {{
                background-color: {PRIMARY_COLOR};
                color: white;
                border: none;
                border-radius: 4px;
                padding: 8px 24px;
                font-weight: bold;
            }}
            QPushButton:hover {{
                background-color: #3d8be8;
            }}
        """)
        self._confirm_button.clicked.connect(self._on_confirm_clicked)
        layout.addWidget(self._confirm_button)
        
        return layout
    
    # ============================================================
    # 公共方法
    # ============================================================
    
    def load_preview(self, state: Optional[Dict[str, Any]] = None) -> None:
        """
        加载压缩预览信息
        
        Args:
            state: 可选的状态字典，若不提供则从 ContextManager 获取
        """
        if self.context_manager is None:
            return
        
        try:
            # 获取当前统计信息
            stats = self.context_manager.get_stats()
            self._current_stats = stats
            
            # 更新当前状态显示
            message_count = stats.get("message_count", 0)
            used_tokens = stats.get("used_tokens", 0)
            total_tokens = stats.get("total_tokens", 100000)
            ratio = stats.get("usage_ratio", 0)
            
            self._message_count_label.setText(f"{message_count} 条")
            self._token_usage_label.setText(
                f"{used_tokens:,} / {total_tokens:,} ({int(ratio * 100)}%)"
            )
            self._usage_progress.setValue(int(ratio * 100))
            
            # 更新进度条颜色
            if ratio >= 0.85:
                color = "#f44336"
            elif ratio >= 0.70:
                color = "#ff9800"
            else:
                color = "#4caf50"
            
            self._usage_progress.setStyleSheet(f"""
                QProgressBar {{
                    background-color: #e0e0e0;
                    border-radius: 4px;
                }}
                QProgressBar::chunk {{
                    background-color: {color};
                    border-radius: 4px;
                }}
            """)
            
            # 获取消息分类
            categories = self.context_manager.classify_messages()
            self._message_categories = categories
            
            keep_count = len(categories.get("must_keep", []))
            compress_count = len(categories.get("can_compress", []))
            
            self._keep_messages_label.setText(f"{keep_count} 条")
            self._compress_messages_label.setText(f"{compress_count} 条")
            
            # 更新预估
            self._update_estimate()
            
        except Exception as e:
            if hasattr(self, '_logger') and self._logger:
                self._logger.error(f"加载压缩预览失败: {e}")
    
    def _update_estimate(self) -> None:
        """更新压缩预估"""
        keep_recent = self._keep_count_spin.value() if self._keep_count_spin else 5
        
        # 简单估算
        estimated_summary_tokens = 2000
        keep_messages_tokens = keep_recent * 500  # 假设每条消息平均 500 tokens
        
        total_tokens = self._current_stats.get("total_tokens", 100000)
        estimated_after = estimated_summary_tokens + keep_messages_tokens
        estimated_ratio = estimated_after / total_tokens if total_tokens > 0 else 0
        
        self._estimated_summary_label.setText(f"约 {estimated_summary_tokens:,} tokens")
        self._estimated_usage_label.setText(
            f"约 {estimated_after:,} tokens ({int(estimated_ratio * 100)}%)"
        )


    def generate_summary_preview(self) -> None:
        """调用 LLM 生成摘要预览"""
        if self.context_manager is None:
            return
        
        try:
            self._preview_button.setEnabled(False)
            self._preview_button.setText(
                self._get_text("dialog.compress.generating", "生成中...")
            )
            
            # 调用 ContextManager 生成预览
            preview = self.context_manager.generate_compress_preview(
                keep_recent=self._keep_count_spin.value()
            )
            
            self._preview_summary = preview.get("summary", "")
            self._summary_preview.setPlainText(self._preview_summary)
            
            # 更新预估
            if "estimated_tokens" in preview:
                self._estimated_summary_label.setText(
                    f"约 {preview['estimated_tokens']:,} tokens"
                )
            
        except Exception as e:
            self._summary_preview.setPlainText(f"生成预览失败: {e}")
        finally:
            self._preview_button.setEnabled(True)
            self._preview_button.setText(
                self._get_text("dialog.compress.btn_preview", "预览摘要")
            )
    
    def execute_compress(self) -> bool:
        """
        执行压缩操作
        
        Returns:
            bool: 是否成功
        """
        if self.context_manager is None:
            return False
        
        try:
            options = {
                "keep_recent": self._keep_count_spin.value(),
                "summary": self._preview_summary,
            }
            
            result = self.context_manager.compress(options)
            return result.get("success", False)
            
        except Exception as e:
            if hasattr(self, '_logger') and self._logger:
                self._logger.error(f"执行压缩失败: {e}")
            return False
    
    # ============================================================
    # 事件处理
    # ============================================================
    
    def _on_keep_count_changed(self, value: int) -> None:
        """保留数量变化时更新预估"""
        self._update_estimate()
    
    def _on_preview_clicked(self) -> None:
        """预览按钮点击"""
        self.preview_requested.emit()
        self.generate_summary_preview()
    
    def _on_confirm_clicked(self) -> None:
        """确认压缩按钮点击"""
        options = {
            "keep_recent": self._keep_count_spin.value(),
            "summary": self._preview_summary,
        }
        
        self.compress_confirmed.emit(options)
        
        # 执行压缩
        if self.execute_compress():
            self.accept()
    
    # ============================================================
    # 国际化
    # ============================================================
    
    def retranslate_ui(self) -> None:
        """刷新 UI 文本"""
        self.setWindowTitle(
            self._get_text("dialog.compress.title", "压缩上下文")
        )
        
        if self._preview_button:
            self._preview_button.setText(
                self._get_text("dialog.compress.btn_preview", "预览摘要")
            )
        
        if self._confirm_button:
            self._confirm_button.setText(
                self._get_text("dialog.compress.btn_confirm", "确认压缩")
            )


# ============================================================
# 模块导出
# ============================================================

__all__ = [
    "ContextCompressDialog",
]

