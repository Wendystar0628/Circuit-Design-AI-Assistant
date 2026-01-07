# FFTResultTab - FFT Spectrum Analysis Result Tab
"""
FFT 频谱分析结果标签页

职责：
- 展示 FFT 频谱分析结果
- 显示频谱图和谐波分析
- 显示失真指标（THD、SFDR、SNDR、ENOB）

设计原则：
- 使用 QWidget 作为基类
- 订阅 EVENT_FFT_COMPLETE 事件自动更新
- 支持国际化

被调用方：
- simulation_tab.py
"""

import logging
from typing import Any, Dict, List, Optional

import numpy as np
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QSplitter,
    QFrame,
    QLabel,
    QPushButton,
    QComboBox,
    QSizePolicy,
    QGroupBox,
)

from resources.theme import (
    COLOR_BG_PRIMARY,
    COLOR_BG_SECONDARY,
    COLOR_BG_TERTIARY,
    COLOR_TEXT_PRIMARY,
    COLOR_TEXT_SECONDARY,
    COLOR_ACCENT,
    COLOR_ACCENT_LIGHT,
    COLOR_BORDER,
    COLOR_SUCCESS,
    COLOR_ERROR,
    COLOR_WARNING,
    FONT_SIZE_NORMAL,
    FONT_SIZE_SMALL,
    FONT_SIZE_TITLE,
    FONT_SIZE_LARGE_TITLE,
    SPACING_SMALL,
    SPACING_NORMAL,
    SPACING_LARGE,
    BORDER_RADIUS_NORMAL,
)


# ============================================================
# 子组件
# ============================================================

class SignalSelectorBar(QFrame):
    """
    信号和窗函数选择器栏
    """
    
    signal_changed = pyqtSignal(str)
    window_changed = pyqtSignal(str)
    
    def __init__(self, parent=None):
        super().__init__(parent)
        
        self.setObjectName("signalSelectorBar")
        self.setFixedHeight(48)
        
        self._setup_ui()
        self._apply_style()
    
    def _setup_ui(self):
        """初始化 UI"""
        layout = QHBoxLayout(self)
        layout.setContentsMargins(SPACING_NORMAL, SPACING_SMALL, SPACING_NORMAL, SPACING_SMALL)
        layout.setSpacing(SPACING_NORMAL)
        
        # 信号选择
        signal_label = QLabel(self._get_text("fft.signal", "信号:"))
        signal_label.setObjectName("selectorLabel")
        layout.addWidget(signal_label)
        
        self._signal_combo = QComboBox()
        self._signal_combo.setObjectName("signalCombo")
        self._signal_combo.setMinimumWidth(150)
        self._signal_combo.currentTextChanged.connect(self._on_signal_changed)
        layout.addWidget(self._signal_combo)
        
        layout.addSpacing(SPACING_LARGE)
        
        # 窗函数选择
        window_label = QLabel(self._get_text("fft.window", "窗函数:"))
        window_label.setObjectName("selectorLabel")
        layout.addWidget(window_label)
        
        self._window_combo = QComboBox()
        self._window_combo.setObjectName("windowCombo")
        self._window_combo.addItems([
            "Hanning",
            "Hamming",
            "Blackman",
            "Rectangular",
            "Kaiser",
        ])
        self._window_combo.currentTextChanged.connect(self._on_window_changed)
        layout.addWidget(self._window_combo)
        
        layout.addStretch(1)
    
    def _apply_style(self):
        """应用样式"""
        self.setStyleSheet(f"""
            #signalSelectorBar {{
                background-color: {COLOR_BG_SECONDARY};
                border-bottom: 1px solid {COLOR_BORDER};
            }}
            
            #selectorLabel {{
                color: {COLOR_TEXT_SECONDARY};
                font-size: {FONT_SIZE_NORMAL}px;
            }}
            
            QComboBox {{
                background-color: {COLOR_BG_PRIMARY};
                border: 1px solid {COLOR_BORDER};
                border-radius: {BORDER_RADIUS_NORMAL}px;
                padding: 4px 8px;
                font-size: {FONT_SIZE_NORMAL}px;
            }}
        """)
    
    def set_signals(self, signals: List[str]):
        """设置信号列表"""
        self._signal_combo.blockSignals(True)
        self._signal_combo.clear()
        self._signal_combo.addItems(signals)
        self._signal_combo.blockSignals(False)
    
    def _on_signal_changed(self, signal: str):
        """处理信号变更"""
        if signal:
            self.signal_changed.emit(signal)
    
    def _on_window_changed(self, window: str):
        """处理窗函数变更"""
        if window:
            self.window_changed.emit(window)
    
    def _get_text(self, key: str, default: str) -> str:
        """获取国际化文本"""
        try:
            from shared.i18n_manager import I18nManager
            i18n = I18nManager()
            return i18n.get_text(key, default)
        except ImportError:
            return default
    
    def retranslate_ui(self):
        """重新翻译 UI 文本"""
        pass


class DistortionMetricsCard(QFrame):
    """
    失真指标卡片
    
    显示 THD、SFDR、SNDR、ENOB
    """
    
    def __init__(self, parent=None):
        super().__init__(parent)
        
        self.setObjectName("distortionMetricsCard")
        
        self._setup_ui()
        self._apply_style()
    
    def _setup_ui(self):
        """初始化 UI"""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(SPACING_NORMAL, SPACING_NORMAL, SPACING_NORMAL, SPACING_NORMAL)
        layout.setSpacing(SPACING_NORMAL)
        
        # 标题
        title = QLabel(self._get_text("fft.distortion_metrics", "失真指标"))
        title.setObjectName("cardTitle")
        layout.addWidget(title)
        self._title = title
        
        # 指标网格
        metrics_frame = QFrame()
        metrics_layout = QHBoxLayout(metrics_frame)
        metrics_layout.setContentsMargins(0, 0, 0, 0)
        metrics_layout.setSpacing(SPACING_NORMAL)
        
        # THD
        self._thd_card = self._create_metric_card("THD", "—", "dB")
        metrics_layout.addWidget(self._thd_card)
        
        # SFDR
        self._sfdr_card = self._create_metric_card("SFDR", "—", "dB")
        metrics_layout.addWidget(self._sfdr_card)
        
        # SNDR
        self._sndr_card = self._create_metric_card("SNDR", "—", "dB")
        metrics_layout.addWidget(self._sndr_card)
        
        # ENOB
        self._enob_card = self._create_metric_card("ENOB", "—", "bits")
        metrics_layout.addWidget(self._enob_card)
        
        layout.addWidget(metrics_frame)
    
    def _create_metric_card(self, name: str, value: str, unit: str) -> QFrame:
        """创建单个指标卡片"""
        card = QFrame()
        card.setObjectName("metricCard")
        card.setStyleSheet(f"""
            #metricCard {{
                background-color: {COLOR_BG_SECONDARY};
                border-radius: {BORDER_RADIUS_NORMAL}px;
                padding: 8px;
            }}
        """)
        
        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(SPACING_SMALL, SPACING_SMALL, SPACING_SMALL, SPACING_SMALL)
        card_layout.setSpacing(4)
        card_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        
        # 名称
        name_label = QLabel(name)
        name_label.setStyleSheet(f"color: {COLOR_TEXT_SECONDARY}; font-size: {FONT_SIZE_SMALL}px;")
        name_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        card_layout.addWidget(name_label)
        
        # 值
        value_label = QLabel(value)
        value_label.setObjectName(f"{name.lower()}_value")
        value_label.setStyleSheet(f"color: {COLOR_TEXT_PRIMARY}; font-size: {FONT_SIZE_TITLE}px; font-weight: bold;")
        value_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        card_layout.addWidget(value_label)
        
        # 单位
        unit_label = QLabel(unit)
        unit_label.setStyleSheet(f"color: {COLOR_TEXT_SECONDARY}; font-size: {FONT_SIZE_SMALL}px;")
        unit_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        card_layout.addWidget(unit_label)
        
        card.value_label = value_label
        
        return card
    
    def _apply_style(self):
        """应用样式"""
        self.setStyleSheet(f"""
            #distortionMetricsCard {{
                background-color: {COLOR_BG_PRIMARY};
                border: 1px solid {COLOR_BORDER};
                border-radius: {BORDER_RADIUS_NORMAL}px;
            }}
            
            #cardTitle {{
                color: {COLOR_TEXT_PRIMARY};
                font-size: {FONT_SIZE_NORMAL}px;
                font-weight: bold;
            }}
        """)
    
    def set_metrics(self, thd: float, sfdr: float, sndr: float, enob: float):
        """设置指标值"""
        self._thd_card.value_label.setText(f"{thd:.2f}")
        self._sfdr_card.value_label.setText(f"{sfdr:.2f}")
        self._sndr_card.value_label.setText(f"{sndr:.2f}")
        self._enob_card.value_label.setText(f"{enob:.2f}")
    
    def clear(self):
        """清空显示"""
        self._thd_card.value_label.setText("—")
        self._sfdr_card.value_label.setText("—")
        self._sndr_card.value_label.setText("—")
        self._enob_card.value_label.setText("—")
    
    def _get_text(self, key: str, default: str) -> str:
        """获取国际化文本"""
        try:
            from shared.i18n_manager import I18nManager
            i18n = I18nManager()
            return i18n.get_text(key, default)
        except ImportError:
            return default
    
    def retranslate_ui(self):
        """重新翻译 UI 文本"""
        self._title.setText(self._get_text("fft.distortion_metrics", "失真指标"))


class FFTSpectrumChart(QFrame):
    """
    FFT 频谱图组件
    """
    
    def __init__(self, parent=None):
        super().__init__(parent)
        
        self.setObjectName("fftSpectrumChart")
        
        self._plot_widget = None
        
        self._setup_ui()
        self._apply_style()
    
    def _setup_ui(self):
        """初始化 UI"""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        
        try:
            import pyqtgraph as pg
            
            pg.setConfigOptions(antialias=True, background='w', foreground='k')
            
            self._plot_widget = pg.PlotWidget()
            self._plot_widget.setObjectName("fftPlot")
            self._plot_widget.showGrid(x=True, y=True, alpha=0.3)
            self._plot_widget.setLabel('bottom', self._get_text("fft.frequency", "频率"), units='Hz')
            self._plot_widget.setLabel('left', self._get_text("fft.magnitude", "幅度"), units='dB')
            self._plot_widget.setLogMode(x=True, y=False)
            
            layout.addWidget(self._plot_widget)
            
        except ImportError:
            placeholder = QLabel(self._get_text(
                "fft.pyqtgraph_missing",
                "频谱图需要 pyqtgraph 库"
            ))
            placeholder.setAlignment(Qt.AlignmentFlag.AlignCenter)
            placeholder.setStyleSheet(f"color: {COLOR_TEXT_SECONDARY};")
            layout.addWidget(placeholder)
    
    def _apply_style(self):
        """应用样式"""
        self.setStyleSheet(f"""
            #fftSpectrumChart {{
                background-color: {COLOR_BG_PRIMARY};
                border: 1px solid {COLOR_BORDER};
                border-radius: {BORDER_RADIUS_NORMAL}px;
            }}
        """)
    
    def update_spectrum(self, frequencies: List[float], magnitudes_db: List[float]):
        """更新频谱图"""
        if self._plot_widget is None or not frequencies:
            return
        
        try:
            import pyqtgraph as pg
            
            self._plot_widget.clear()
            
            # 过滤掉零频率（对数坐标不支持）
            valid_indices = [i for i, f in enumerate(frequencies) if f > 0]
            freq_valid = [frequencies[i] for i in valid_indices]
            mag_valid = [magnitudes_db[i] for i in valid_indices]
            
            # 绘制频谱
            pen = pg.mkPen(color=COLOR_ACCENT, width=1)
            self._plot_widget.plot(freq_valid, mag_valid, pen=pen)
            
            self._plot_widget.autoRange()
            
        except Exception as e:
            logging.getLogger(__name__).warning(f"更新频谱图失败: {e}")
    
    def highlight_harmonics(self, harmonic_freqs: List[float], harmonic_mags: List[float]):
        """高亮谐波分量"""
        if self._plot_widget is None:
            return
        
        try:
            import pyqtgraph as pg
            
            # 添加谐波标记
            scatter = pg.ScatterPlotItem(
                harmonic_freqs, harmonic_mags,
                symbol='o',
                size=10,
                brush=pg.mkBrush(COLOR_ERROR),
                pen=pg.mkPen('w', width=1)
            )
            self._plot_widget.addItem(scatter)
            
        except Exception as e:
            logging.getLogger(__name__).warning(f"高亮谐波失败: {e}")
    
    def clear(self):
        """清空图表"""
        if self._plot_widget:
            self._plot_widget.clear()
    
    def _get_text(self, key: str, default: str) -> str:
        """获取国际化文本"""
        try:
            from shared.i18n_manager import I18nManager
            i18n = I18nManager()
            return i18n.get_text(key, default)
        except ImportError:
            return default
    
    def retranslate_ui(self):
        """重新翻译 UI 文本"""
        if self._plot_widget:
            self._plot_widget.setLabel('bottom', self._get_text("fft.frequency", "频率"), units='Hz')
            self._plot_widget.setLabel('left', self._get_text("fft.magnitude", "幅度"), units='dB')


class HarmonicBarChart(QFrame):
    """
    谐波分量柱状图
    """
    
    def __init__(self, parent=None):
        super().__init__(parent)
        
        self.setObjectName("harmonicBarChart")
        
        self._plot_widget = None
        
        self._setup_ui()
        self._apply_style()
    
    def _setup_ui(self):
        """初始化 UI"""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        
        try:
            import pyqtgraph as pg
            
            pg.setConfigOptions(antialias=True, background='w', foreground='k')
            
            self._plot_widget = pg.PlotWidget()
            self._plot_widget.setObjectName("harmonicPlot")
            self._plot_widget.showGrid(x=False, y=True, alpha=0.3)
            self._plot_widget.setLabel('bottom', self._get_text("fft.harmonic", "谐波次数"))
            self._plot_widget.setLabel('left', self._get_text("fft.magnitude", "幅度"), units='dB')
            
            layout.addWidget(self._plot_widget)
            
        except ImportError:
            placeholder = QLabel(self._get_text(
                "fft.pyqtgraph_missing",
                "谐波图需要 pyqtgraph 库"
            ))
            placeholder.setAlignment(Qt.AlignmentFlag.AlignCenter)
            placeholder.setStyleSheet(f"color: {COLOR_TEXT_SECONDARY};")
            layout.addWidget(placeholder)
    
    def _apply_style(self):
        """应用样式"""
        self.setStyleSheet(f"""
            #harmonicBarChart {{
                background-color: {COLOR_BG_PRIMARY};
                border: 1px solid {COLOR_BORDER};
                border-radius: {BORDER_RADIUS_NORMAL}px;
            }}
        """)
    
    def update_harmonics(self, harmonic_orders: List[int], magnitudes_db: List[float]):
        """更新谐波柱状图"""
        if self._plot_widget is None or not harmonic_orders:
            return
        
        try:
            import pyqtgraph as pg
            
            self._plot_widget.clear()
            
            # 颜色：基波蓝色，谐波橙色
            colors = [COLOR_ACCENT if i == 0 else '#FF9800' for i in range(len(harmonic_orders))]
            
            # 绘制柱状图
            for i, (order, mag) in enumerate(zip(harmonic_orders, magnitudes_db)):
                bar = pg.BarGraphItem(
                    x=[order], height=[mag], width=0.6,
                    brush=pg.mkBrush(colors[i]),
                    pen=pg.mkPen(colors[i], width=1)
                )
                self._plot_widget.addItem(bar)
            
            # 设置 X 轴刻度
            x_axis = self._plot_widget.getAxis('bottom')
            ticks = [(i, f"H{i}" if i > 0 else "基波") for i in harmonic_orders]
            x_axis.setTicks([ticks])
            
            self._plot_widget.autoRange()
            
        except Exception as e:
            logging.getLogger(__name__).warning(f"更新谐波图失败: {e}")
    
    def clear(self):
        """清空图表"""
        if self._plot_widget:
            self._plot_widget.clear()
    
    def _get_text(self, key: str, default: str) -> str:
        """获取国际化文本"""
        try:
            from shared.i18n_manager import I18nManager
            i18n = I18nManager()
            return i18n.get_text(key, default)
        except ImportError:
            return default
    
    def retranslate_ui(self):
        """重新翻译 UI 文本"""
        if self._plot_widget:
            self._plot_widget.setLabel('bottom', self._get_text("fft.harmonic", "谐波次数"))
            self._plot_widget.setLabel('left', self._get_text("fft.magnitude", "幅度"), units='dB')



# ============================================================
# FFTResultTab - 主组件
# ============================================================

class FFTResultTab(QWidget):
    """
    FFT 频谱分析结果标签页
    
    展示 FFT 频谱分析结果，显示频谱图和谐波分析。
    
    Signals:
        export_requested: 请求导出数据
    """
    
    export_requested = pyqtSignal()
    
    def __init__(self, parent=None):
        super().__init__(parent)
        
        self._logger = logging.getLogger(__name__)
        
        # 数据
        self._fft_result: Optional[Any] = None
        self._current_signal: str = ""
        
        # EventBus 引用
        self._event_bus = None
        self._subscriptions: List[tuple] = []
        
        # 初始化 UI
        self._setup_ui()
        self._apply_style()
        self._connect_signals()
        
        # 订阅事件
        self._subscribe_events()
        
        # 初始化文本
        self.retranslate_ui()
    
    def _setup_ui(self):
        """初始化 UI 组件"""
        self.setSizePolicy(
            QSizePolicy.Policy.Expanding,
            QSizePolicy.Policy.Expanding
        )
        
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)
        
        # 顶部：信号选择器
        self._signal_selector = SignalSelectorBar()
        main_layout.addWidget(self._signal_selector)
        
        # 主内容区
        content_widget = QWidget()
        content_layout = QVBoxLayout(content_widget)
        content_layout.setContentsMargins(SPACING_NORMAL, SPACING_NORMAL, SPACING_NORMAL, SPACING_NORMAL)
        content_layout.setSpacing(SPACING_NORMAL)
        
        # 失真指标卡片
        self._metrics_card = DistortionMetricsCard()
        content_layout.addWidget(self._metrics_card)
        
        # 图表区（左右分栏）
        charts_splitter = QSplitter(Qt.Orientation.Horizontal)
        charts_splitter.setObjectName("chartsSplitter")
        charts_splitter.setHandleWidth(1)
        charts_splitter.setChildrenCollapsible(False)
        
        # 左侧：FFT 频谱图
        left_panel = QWidget()
        left_layout = QVBoxLayout(left_panel)
        left_layout.setContentsMargins(0, 0, SPACING_SMALL, 0)
        left_layout.setSpacing(SPACING_SMALL)
        
        spectrum_title = QLabel(self._get_text("fft.spectrum", "FFT 频谱"))
        spectrum_title.setStyleSheet(f"color: {COLOR_TEXT_PRIMARY}; font-size: {FONT_SIZE_NORMAL}px; font-weight: bold;")
        left_layout.addWidget(spectrum_title)
        self._spectrum_title = spectrum_title
        
        self._spectrum_chart = FFTSpectrumChart()
        left_layout.addWidget(self._spectrum_chart, 1)
        
        charts_splitter.addWidget(left_panel)
        
        # 右侧：谐波柱状图
        right_panel = QWidget()
        right_layout = QVBoxLayout(right_panel)
        right_layout.setContentsMargins(SPACING_SMALL, 0, 0, 0)
        right_layout.setSpacing(SPACING_SMALL)
        
        harmonic_title = QLabel(self._get_text("fft.harmonics", "谐波分量"))
        harmonic_title.setStyleSheet(f"color: {COLOR_TEXT_PRIMARY}; font-size: {FONT_SIZE_NORMAL}px; font-weight: bold;")
        right_layout.addWidget(harmonic_title)
        self._harmonic_title = harmonic_title
        
        self._harmonic_chart = HarmonicBarChart()
        right_layout.addWidget(self._harmonic_chart, 1)
        
        charts_splitter.addWidget(right_panel)
        
        # 设置初始比例（60:40）
        charts_splitter.setSizes([600, 400])
        
        content_layout.addWidget(charts_splitter, 1)
        
        main_layout.addWidget(content_widget, 1)
        
        # 底部：操作栏
        self._action_bar = QFrame()
        self._action_bar.setObjectName("actionBar")
        self._action_bar.setFixedHeight(48)
        action_layout = QHBoxLayout(self._action_bar)
        action_layout.setContentsMargins(SPACING_NORMAL, SPACING_SMALL, SPACING_NORMAL, SPACING_SMALL)
        
        # 基波频率显示
        self._fundamental_label = QLabel()
        self._fundamental_label.setObjectName("fundamentalLabel")
        action_layout.addWidget(self._fundamental_label)
        
        action_layout.addStretch(1)
        
        # 导出按钮
        self._export_btn = QPushButton()
        self._export_btn.setObjectName("exportBtn")
        self._export_btn.clicked.connect(self._on_export_clicked)
        action_layout.addWidget(self._export_btn)
        
        main_layout.addWidget(self._action_bar)
        
        # 空状态提示
        self._empty_widget = QFrame()
        self._empty_widget.setObjectName("emptyWidget")
        empty_layout = QVBoxLayout(self._empty_widget)
        empty_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        
        self._empty_label = QLabel()
        self._empty_label.setObjectName("emptyLabel")
        self._empty_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        empty_layout.addWidget(self._empty_label)
        
        main_layout.addWidget(self._empty_widget)
        
        # 初始显示空状态
        self._show_empty_state()
    
    def _apply_style(self):
        """应用样式"""
        self.setStyleSheet(f"""
            FFTResultTab {{
                background-color: {COLOR_BG_PRIMARY};
            }}
            
            #chartsSplitter {{
                background-color: {COLOR_BG_PRIMARY};
            }}
            
            #chartsSplitter::handle {{
                background-color: {COLOR_BORDER};
            }}
            
            #actionBar {{
                background-color: {COLOR_BG_SECONDARY};
                border-top: 1px solid {COLOR_BORDER};
            }}
            
            #fundamentalLabel {{
                color: {COLOR_TEXT_SECONDARY};
                font-size: {FONT_SIZE_SMALL}px;
            }}
            
            #exportBtn {{
                background-color: {COLOR_ACCENT};
                color: white;
                border: none;
                border-radius: {BORDER_RADIUS_NORMAL}px;
                padding: 8px 16px;
                font-size: {FONT_SIZE_NORMAL}px;
            }}
            
            #exportBtn:hover {{
                background-color: {COLOR_ACCENT};
                opacity: 0.9;
            }}
            
            #emptyWidget {{
                background-color: {COLOR_BG_PRIMARY};
            }}
            
            #emptyLabel {{
                color: {COLOR_TEXT_SECONDARY};
                font-size: {FONT_SIZE_NORMAL}px;
            }}
        """)
    
    def _connect_signals(self):
        """连接信号"""
        self._signal_selector.signal_changed.connect(self._on_signal_changed)
        self._signal_selector.window_changed.connect(self._on_window_changed)
    
    def _subscribe_events(self):
        """订阅事件"""
        event_bus = self._get_event_bus()
        if not event_bus:
            return
        
        from shared.event_types import EVENT_FFT_COMPLETE, EVENT_LANGUAGE_CHANGED
        
        subscriptions = [
            (EVENT_FFT_COMPLETE, self._on_fft_complete),
            (EVENT_LANGUAGE_CHANGED, self._on_language_changed),
        ]
        
        for event_type, handler in subscriptions:
            event_bus.subscribe(event_type, handler)
            self._subscriptions.append((event_type, handler))
    
    def _unsubscribe_events(self):
        """取消事件订阅"""
        event_bus = self._get_event_bus()
        if not event_bus:
            return
        
        for event_type, handler in self._subscriptions:
            try:
                event_bus.unsubscribe(event_type, handler)
            except Exception:
                pass
        
        self._subscriptions.clear()
    
    def _get_event_bus(self):
        """获取 EventBus"""
        if self._event_bus is None:
            try:
                from shared.service_locator import ServiceLocator
                from shared.service_names import SVC_EVENT_BUS
                self._event_bus = ServiceLocator.get_optional(SVC_EVENT_BUS)
            except Exception:
                pass
        return self._event_bus
    
    # ============================================================
    # 公开方法
    # ============================================================
    
    def update_results(self, fft_result: Any):
        """
        更新 FFT 分析结果显示
        
        Args:
            fft_result: FFT 分析结果对象
        """
        self._fft_result = fft_result
        
        if fft_result is None:
            self._show_empty_state()
            return
        
        self._show_content_state()
        
        # 提取信号列表
        signals = getattr(fft_result, 'signals', [])
        if not signals:
            # 尝试从其他属性获取
            signal_name = getattr(fft_result, 'signal_name', '')
            if signal_name:
                signals = [signal_name]
        
        self._signal_selector.set_signals(signals)
        
        # 更新失真指标
        thd = getattr(fft_result, 'thd_db', 0.0)
        sfdr = getattr(fft_result, 'sfdr_db', 0.0)
        sndr = getattr(fft_result, 'sndr_db', 0.0)
        enob = getattr(fft_result, 'enob', 0.0)
        
        self._metrics_card.set_metrics(thd, sfdr, sndr, enob)
        
        # 更新频谱图
        frequencies = getattr(fft_result, 'frequencies', [])
        magnitudes = getattr(fft_result, 'magnitudes_db', [])
        
        if frequencies and magnitudes:
            self._spectrum_chart.update_spectrum(frequencies, magnitudes)
        
        # 更新谐波柱状图
        harmonic_orders = getattr(fft_result, 'harmonic_orders', [])
        harmonic_mags = getattr(fft_result, 'harmonic_magnitudes_db', [])
        
        if not harmonic_orders:
            # 默认显示基波和前 5 次谐波
            harmonic_orders = list(range(6))
            harmonic_mags = [0.0] * 6
        
        self._harmonic_chart.update_harmonics(harmonic_orders, harmonic_mags)
        
        # 高亮谐波
        harmonic_freqs = getattr(fft_result, 'harmonic_frequencies', [])
        if harmonic_freqs and harmonic_mags:
            self._spectrum_chart.highlight_harmonics(harmonic_freqs, harmonic_mags)
        
        # 更新基波频率显示
        fundamental_freq = getattr(fft_result, 'fundamental_frequency', 0.0)
        if fundamental_freq > 0:
            self._fundamental_label.setText(
                f"{self._get_text('fft.fundamental', '基波频率')}: {fundamental_freq:.2f} Hz"
            )
        else:
            self._fundamental_label.clear()
    
    def _show_empty_state(self):
        """显示空状态"""
        self._signal_selector.hide()
        self._metrics_card.hide()
        self._spectrum_chart.hide()
        self._harmonic_chart.hide()
        self._spectrum_title.hide()
        self._harmonic_title.hide()
        self._action_bar.hide()
        
        self._empty_label.setText(self._get_text(
            "fft.no_results",
            "暂无 FFT 分析结果"
        ))
        self._empty_widget.show()
    
    def _show_content_state(self):
        """显示内容状态"""
        self._empty_widget.hide()
        
        self._signal_selector.show()
        self._metrics_card.show()
        self._spectrum_chart.show()
        self._harmonic_chart.show()
        self._spectrum_title.show()
        self._harmonic_title.show()
        self._action_bar.show()
    
    # ============================================================
    # 事件处理
    # ============================================================
    
    def _on_signal_changed(self, signal: str):
        """处理信号变更"""
        self._current_signal = signal
        # 重新加载该信号的 FFT 数据
        # 实际实现中需要调用服务重新计算
    
    def _on_window_changed(self, window: str):
        """处理窗函数变更"""
        # 重新计算 FFT
        # 实际实现中需要调用服务重新计算
        pass
    
    def _on_fft_complete(self, event_data: Dict[str, Any]):
        """处理 FFT 分析完成事件"""
        # 事件数据在 "data" 字段中
        data = event_data.get("data", event_data)
        result = data.get("result")
        if result:
            self.update_results(result)
    
    def _on_language_changed(self, event_data: Dict[str, Any]):
        """处理语言变更事件"""
        self.retranslate_ui()
    
    def _on_export_clicked(self):
        """处理导出按钮点击"""
        self.export_requested.emit()
    
    def _get_text(self, key: str, default: str) -> str:
        """获取国际化文本"""
        try:
            from shared.i18n_manager import I18nManager
            i18n = I18nManager()
            return i18n.get_text(key, default)
        except ImportError:
            return default
    
    def retranslate_ui(self):
        """重新翻译 UI 文本"""
        self._export_btn.setText(self._get_text("fft.export", "导出数据"))
        self._empty_label.setText(self._get_text("fft.no_results", "暂无 FFT 分析结果"))
        self._spectrum_title.setText(self._get_text("fft.spectrum", "FFT 频谱"))
        self._harmonic_title.setText(self._get_text("fft.harmonics", "谐波分量"))
        
        self._signal_selector.retranslate_ui()
        self._metrics_card.retranslate_ui()
        self._spectrum_chart.retranslate_ui()
        self._harmonic_chart.retranslate_ui()
    
    def closeEvent(self, event):
        """关闭事件"""
        self._unsubscribe_events()
        super().closeEvent(event)


# ============================================================
# 模块导出
# ============================================================

__all__ = [
    "FFTResultTab",
]
