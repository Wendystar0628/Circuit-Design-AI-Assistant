# Simulation Settings Dialog
"""
仿真设置对话框

职责：
- 提供仿真分析类型和图表显示类型的统一配置界面
- 两个标签页：分析类型选择、图表显示选择
- 与 AnalysisSelector 和 ChartSelector 领域服务集成

触发方式：
- 菜单栏「设置 → 仿真设置」
- 快捷键 Ctrl+Shift+S

国际化支持：
- 实现 retranslate_ui() 方法
- 所有文本支持中英文切换
"""

import logging
from typing import Dict, List, Optional

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QCheckBox,
    QDialog,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QTabWidget,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from domain.simulation.service.analysis_selector import (
    AnalysisSelector,
    AnalysisType,
    analysis_selector,
)
from domain.simulation.service.chart_selector import (
    ChartSelector,
    ChartType,
    chart_selector,
)


# ============================================================
# 图表类别显示名称
# ============================================================

CHART_CATEGORY_NAMES: Dict[str, str] = {
    "waveform": "波形图表",
    "bode": "Bode 图",
    "dc": "特性曲线",
    "spectrum": "频谱分析",
    "statistics": "统计图表",
    "sweep": "参数扫描",
    "sensitivity": "敏感度",
    "pvt": "PVT 图表",
    "noise": "噪声图表",
}

CHART_CATEGORY_NAMES_EN: Dict[str, str] = {
    "waveform": "Waveform",
    "bode": "Bode Plot",
    "dc": "DC Characteristics",
    "spectrum": "Spectrum Analysis",
    "statistics": "Statistics",
    "sweep": "Parameter Sweep",
    "sensitivity": "Sensitivity",
    "pvt": "PVT Analysis",
    "noise": "Noise Analysis",
}


# ============================================================
# SimulationSettingsDialog
# ============================================================

class SimulationSettingsDialog(QDialog):
    """
    仿真设置对话框
    
    功能：
    - 分析类型选择（基础分析 + 高级分析）
    - 图表显示选择（分类树形结构）
    - 快捷操作（全选、推荐图表等）
    - 配置持久化
    """
    
    # 信号定义
    settings_changed = pyqtSignal()
    settings_applied = pyqtSignal()
    
    def __init__(
        self,
        parent: Optional[QWidget] = None,
        analysis_selector_instance: Optional[AnalysisSelector] = None,
        chart_selector_instance: Optional[ChartSelector] = None,
    ):
        super().__init__(parent)
        
        self._logger = logging.getLogger(__name__)
        
        # 使用传入的实例或模块级单例
        self._analysis_selector = analysis_selector_instance or analysis_selector
        self._chart_selector = chart_selector_instance or chart_selector
        
        # 项目根目录（由调用方设置）
        self._project_root: Optional[str] = None
        
        # UI 组件引用
        self._tab_widget: Optional[QTabWidget] = None
        
        # 分析类型标签页组件
        self._basic_group: Optional[QGroupBox] = None
        self._advanced_group: Optional[QGroupBox] = None
        self._analysis_checkboxes: Dict[AnalysisType, QCheckBox] = {}
        self._execution_order_label: Optional[QLabel] = None
        
        # 图表标签页组件
        self._chart_tree: Optional[QTreeWidget] = None
        self._chart_items: Dict[ChartType, QTreeWidgetItem] = {}
        self._category_items: Dict[str, QTreeWidgetItem] = {}
        
        # 按钮
        self._ok_btn: Optional[QPushButton] = None
        self._apply_btn: Optional[QPushButton] = None
        self._cancel_btn: Optional[QPushButton] = None
        self._reset_btn: Optional[QPushButton] = None
        
        # 初始化 UI
        self._setup_dialog()
        self._setup_ui()
        
        # 加载当前设置
        self._load_current_settings()
        
        # 应用国际化文本
        self.retranslate_ui()
    
    # ============================================================
    # 公共方法
    # ============================================================
    
    def set_project_root(self, project_root: str) -> None:
        """设置项目根目录"""
        self._project_root = project_root
    
    def load_settings(self, project_root: str) -> None:
        """从项目配置加载设置"""
        self._project_root = project_root
        self._analysis_selector.load_selection(project_root)
        self._chart_selector.load_selection(project_root)
        self._load_current_settings()
    
    def save_settings(self, project_root: Optional[str] = None) -> bool:
        """保存设置到项目配置"""
        root = project_root or self._project_root
        if not root:
            self._logger.warning("未设置项目根目录，无法保存配置")
            return False
        
        self._sync_ui_to_selectors()
        
        success_analysis = self._analysis_selector.save_selection(root)
        success_chart = self._chart_selector.save_selection(root)
        
        return success_analysis and success_chart
    
    def apply_settings(self) -> None:
        """应用设置（同步 UI 到选择器，触发事件）"""
        self._sync_ui_to_selectors()
        self.settings_applied.emit()
    
    def reset_to_default(self) -> None:
        """重置为默认设置"""
        self._analysis_selector.reset_to_default(publish_event=False)
        self._chart_selector.reset_to_default(publish_event=False)
        self._load_current_settings()
        self.settings_changed.emit()
    
    def get_selected_analyses(self) -> List[AnalysisType]:
        """获取选中的分析类型"""
        return [
            at for at, cb in self._analysis_checkboxes.items()
            if cb.isChecked()
        ]
    
    def get_selected_charts(self) -> List[ChartType]:
        """获取选中的图表类型"""
        return [
            ct for ct, item in self._chart_items.items()
            if item.checkState(0) == Qt.CheckState.Checked
        ]
    
    def retranslate_ui(self) -> None:
        """更新国际化文本"""
        # 对话框标题
        self.setWindowTitle(self._get_text("sim_settings_title", "仿真设置"))
        
        # 标签页标题
        if self._tab_widget:
            self._tab_widget.setTabText(
                0, self._get_text("sim_settings_analysis_tab", "分析类型")
            )
            self._tab_widget.setTabText(
                1, self._get_text("sim_settings_chart_tab", "图表显示")
            )
        
        # 分析类型组标题
        if self._basic_group:
            self._basic_group.setTitle(
                self._get_text("sim_settings_basic_group", "基础分析")
            )
        if self._advanced_group:
            self._advanced_group.setTitle(
                self._get_text("sim_settings_advanced_group", "高级分析")
            )
        
        # 分析类型复选框文本
        for at, cb in self._analysis_checkboxes.items():
            cb.setText(AnalysisType.get_display_name(at))
        
        # 图表类别和项目文本
        self._update_chart_tree_texts()
        
        # 按钮文本
        if self._ok_btn:
            self._ok_btn.setText(self._get_text("btn_ok", "确定"))
        if self._apply_btn:
            self._apply_btn.setText(self._get_text("btn_apply", "应用"))
        if self._cancel_btn:
            self._cancel_btn.setText(self._get_text("btn_cancel", "取消"))
        if self._reset_btn:
            self._reset_btn.setText(self._get_text("btn_reset_default", "重置默认"))
    
    # ============================================================
    # UI 初始化
    # ============================================================
    
    def _setup_dialog(self) -> None:
        """设置对话框基本属性"""
        self.setWindowFlags(
            self.windowFlags() & ~Qt.WindowType.WindowContextHelpButtonHint
        )
        self.setMinimumWidth(500)
        self.setMinimumHeight(450)
        self.setModal(True)
    
    def _setup_ui(self) -> None:
        """设置 UI 布局"""
        main_layout = QVBoxLayout(self)
        main_layout.setSpacing(10)
        
        # 标签页容器
        self._tab_widget = QTabWidget()
        self._tab_widget.addTab(self._create_analysis_tab(), "分析类型")
        self._tab_widget.addTab(self._create_chart_tab(), "图表显示")
        main_layout.addWidget(self._tab_widget)
        
        # 按钮区域
        main_layout.addWidget(self._create_button_area())
    
    def _create_analysis_tab(self) -> QWidget:
        """创建分析类型标签页"""
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setSpacing(10)
        
        # 基础分析组
        self._basic_group = QGroupBox("基础分析")
        basic_layout = QVBoxLayout(self._basic_group)
        
        for at in self._analysis_selector.get_basic_analyses():
            cb = QCheckBox(AnalysisType.get_display_name(at))
            cb.stateChanged.connect(self._on_analysis_changed)
            self._analysis_checkboxes[at] = cb
            basic_layout.addWidget(cb)
        
        # 基础分析快捷按钮
        basic_btn_layout = QHBoxLayout()
        select_all_basic_btn = QPushButton("全选基础")
        select_all_basic_btn.clicked.connect(self._on_select_all_basic)
        basic_btn_layout.addWidget(select_all_basic_btn)
        basic_btn_layout.addStretch()
        basic_layout.addLayout(basic_btn_layout)
        
        layout.addWidget(self._basic_group)
        
        # 高级分析组
        self._advanced_group = QGroupBox("高级分析")
        advanced_layout = QVBoxLayout(self._advanced_group)
        
        for at in self._analysis_selector.get_advanced_analyses():
            cb = QCheckBox(AnalysisType.get_display_name(at))
            cb.stateChanged.connect(self._on_analysis_changed)
            self._analysis_checkboxes[at] = cb
            advanced_layout.addWidget(cb)
        
        # 高级分析快捷按钮
        advanced_btn_layout = QHBoxLayout()
        select_all_advanced_btn = QPushButton("全选高级")
        select_all_advanced_btn.clicked.connect(self._on_select_all_advanced)
        advanced_btn_layout.addWidget(select_all_advanced_btn)
        advanced_btn_layout.addStretch()
        advanced_layout.addLayout(advanced_btn_layout)
        
        layout.addWidget(self._advanced_group)
        
        # 执行顺序显示
        order_group = QGroupBox("执行顺序")
        order_layout = QVBoxLayout(order_group)
        self._execution_order_label = QLabel()
        self._execution_order_label.setWordWrap(True)
        self._execution_order_label.setStyleSheet(
            "color: #666; padding: 5px; background-color: #f5f5f5; "
            "border-radius: 4px;"
        )
        order_layout.addWidget(self._execution_order_label)
        layout.addWidget(order_group)
        
        layout.addStretch()
        return tab
    
    def _create_chart_tab(self) -> QWidget:
        """创建图表显示标签页"""
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setSpacing(10)
        
        # 图表分类树
        self._chart_tree = QTreeWidget()
        self._chart_tree.setHeaderHidden(True)
        self._chart_tree.itemChanged.connect(self._on_chart_item_changed)
        
        # 构建分类树
        self._build_chart_tree()
        
        layout.addWidget(self._chart_tree)
        
        # 快捷操作按钮
        btn_layout = QHBoxLayout()
        
        recommend_btn = QPushButton("推荐图表")
        recommend_btn.clicked.connect(self._on_recommend_charts)
        btn_layout.addWidget(recommend_btn)
        
        select_all_btn = QPushButton("全选")
        select_all_btn.clicked.connect(self._on_select_all_charts)
        btn_layout.addWidget(select_all_btn)
        
        deselect_all_btn = QPushButton("全不选")
        deselect_all_btn.clicked.connect(self._on_deselect_all_charts)
        btn_layout.addWidget(deselect_all_btn)
        
        btn_layout.addStretch()
        layout.addLayout(btn_layout)
        
        return tab
    
    def _build_chart_tree(self) -> None:
        """构建图表分类树"""
        if not self._chart_tree:
            return
        
        self._chart_tree.clear()
        self._chart_items.clear()
        self._category_items.clear()
        
        # 按类别组织图表
        categories: Dict[str, List[ChartType]] = {}
        for ct in ChartType:
            category = ChartType.get_category(ct)
            if category not in categories:
                categories[category] = []
            categories[category].append(ct)
        
        # 创建树节点
        for category, charts in categories.items():
            # 类别节点
            category_item = QTreeWidgetItem(self._chart_tree)
            category_name = CHART_CATEGORY_NAMES.get(category, category)
            category_item.setText(0, category_name)
            category_item.setFlags(
                category_item.flags() | Qt.ItemFlag.ItemIsAutoTristate
            )
            category_item.setCheckState(0, Qt.CheckState.Unchecked)
            self._category_items[category] = category_item
            
            # 图表节点
            for ct in charts:
                chart_item = QTreeWidgetItem(category_item)
                chart_item.setText(0, ChartType.get_display_name(ct))
                chart_item.setFlags(
                    chart_item.flags() | Qt.ItemFlag.ItemIsUserCheckable
                )
                chart_item.setCheckState(0, Qt.CheckState.Unchecked)
                chart_item.setData(0, Qt.ItemDataRole.UserRole, ct)
                self._chart_items[ct] = chart_item
        
        # 展开所有节点
        self._chart_tree.expandAll()
    
    def _create_button_area(self) -> QWidget:
        """创建按钮区域"""
        widget = QWidget()
        layout = QHBoxLayout(widget)
        layout.setContentsMargins(0, 10, 0, 0)
        
        # 重置默认按钮
        self._reset_btn = QPushButton("重置默认")
        self._reset_btn.clicked.connect(self._on_reset_default)
        layout.addWidget(self._reset_btn)
        
        layout.addStretch()
        
        # 确定按钮
        self._ok_btn = QPushButton("确定")
        self._ok_btn.setDefault(True)
        self._ok_btn.setStyleSheet(
            "QPushButton { background-color: #4a9eff; color: white; "
            "border: none; border-radius: 4px; padding: 8px 20px; }"
            "QPushButton:hover { background-color: #3d8ce6; }"
        )
        self._ok_btn.clicked.connect(self._on_ok)
        layout.addWidget(self._ok_btn)
        
        # 应用按钮
        self._apply_btn = QPushButton("应用")
        self._apply_btn.clicked.connect(self._on_apply)
        layout.addWidget(self._apply_btn)
        
        # 取消按钮
        self._cancel_btn = QPushButton("取消")
        self._cancel_btn.clicked.connect(self.reject)
        layout.addWidget(self._cancel_btn)
        
        return widget

    # ============================================================
    # 数据同步
    # ============================================================
    
    def _load_current_settings(self) -> None:
        """从选择器加载当前设置到 UI"""
        # 加载分析类型选择
        for at, cb in self._analysis_checkboxes.items():
            cb.blockSignals(True)
            cb.setChecked(self._analysis_selector.is_enabled(at))
            cb.blockSignals(False)
        
        # 加载图表选择
        if self._chart_tree:
            self._chart_tree.blockSignals(True)
            for ct, item in self._chart_items.items():
                is_enabled = self._chart_selector.is_enabled(ct)
                item.setCheckState(
                    0,
                    Qt.CheckState.Checked if is_enabled else Qt.CheckState.Unchecked
                )
            self._chart_tree.blockSignals(False)
        
        # 更新执行顺序显示
        self._update_execution_order_display()
    
    def _sync_ui_to_selectors(self) -> None:
        """同步 UI 状态到选择器"""
        # 同步分析类型
        enabled_analyses = [
            at for at, cb in self._analysis_checkboxes.items()
            if cb.isChecked()
        ]
        self._analysis_selector.set_selections_from_list(
            enabled_analyses, publish_event=True
        )
        
        # 同步图表选择
        enabled_charts = [
            ct for ct, item in self._chart_items.items()
            if item.checkState(0) == Qt.CheckState.Checked
        ]
        self._chart_selector.set_selections_from_list(
            enabled_charts, publish_event=True
        )
    
    def _update_execution_order_display(self) -> None:
        """更新执行顺序显示"""
        if not self._execution_order_label:
            return
        
        # 获取当前选中的分析类型
        selected = [
            at for at, cb in self._analysis_checkboxes.items()
            if cb.isChecked()
        ]
        
        if not selected:
            self._execution_order_label.setText(
                self._get_text("sim_settings_no_analysis", "未选择任何分析类型")
            )
            return
        
        # 按优先级排序
        sorted_analyses = sorted(
            selected,
            key=lambda at: self._analysis_selector.get_selection(at).priority
            if self._analysis_selector.get_selection(at) else 99
        )
        
        # 生成显示文本
        order_text = " → ".join(
            AnalysisType.get_display_name(at) for at in sorted_analyses
        )
        self._execution_order_label.setText(order_text)
    
    def _update_chart_tree_texts(self) -> None:
        """更新图表树的文本（国际化）"""
        # 更新类别文本
        for category, item in self._category_items.items():
            category_name = CHART_CATEGORY_NAMES.get(category, category)
            item.setText(0, category_name)
        
        # 更新图表项文本
        for ct, item in self._chart_items.items():
            item.setText(0, ChartType.get_display_name(ct))
    
    # ============================================================
    # 事件处理
    # ============================================================
    
    def _on_analysis_changed(self, state: int) -> None:
        """分析类型勾选变更"""
        self._update_execution_order_display()
        self.settings_changed.emit()
    
    def _on_chart_item_changed(self, item: QTreeWidgetItem, column: int) -> None:
        """图表项勾选变更"""
        self.settings_changed.emit()
    
    def _on_select_all_basic(self) -> None:
        """全选基础分析"""
        for at in self._analysis_selector.get_basic_analyses():
            if at in self._analysis_checkboxes:
                self._analysis_checkboxes[at].setChecked(True)
    
    def _on_select_all_advanced(self) -> None:
        """全选高级分析"""
        for at in self._analysis_selector.get_advanced_analyses():
            if at in self._analysis_checkboxes:
                self._analysis_checkboxes[at].setChecked(True)
    
    def _on_recommend_charts(self) -> None:
        """根据选中的分析类型推荐图表"""
        # 获取当前选中的分析类型
        selected_analyses = [
            at.value for at, cb in self._analysis_checkboxes.items()
            if cb.isChecked()
        ]
        
        if not selected_analyses:
            return
        
        # 获取推荐图表
        recommended = self._chart_selector.get_recommended_charts(selected_analyses)
        
        # 更新图表树
        if self._chart_tree:
            self._chart_tree.blockSignals(True)
            for ct, item in self._chart_items.items():
                item.setCheckState(
                    0,
                    Qt.CheckState.Checked if ct in recommended else Qt.CheckState.Unchecked
                )
            self._chart_tree.blockSignals(False)
        
        self.settings_changed.emit()
    
    def _on_select_all_charts(self) -> None:
        """全选图表"""
        if self._chart_tree:
            self._chart_tree.blockSignals(True)
            for item in self._chart_items.values():
                item.setCheckState(0, Qt.CheckState.Checked)
            self._chart_tree.blockSignals(False)
        self.settings_changed.emit()
    
    def _on_deselect_all_charts(self) -> None:
        """全不选图表"""
        if self._chart_tree:
            self._chart_tree.blockSignals(True)
            for item in self._chart_items.values():
                item.setCheckState(0, Qt.CheckState.Unchecked)
            self._chart_tree.blockSignals(False)
        self.settings_changed.emit()
    
    def _on_reset_default(self) -> None:
        """重置为默认设置"""
        self.reset_to_default()
    
    def _on_ok(self) -> None:
        """确定按钮点击"""
        if self._project_root:
            self.save_settings()
        self.apply_settings()
        self.accept()
    
    def _on_apply(self) -> None:
        """应用按钮点击"""
        if self._project_root:
            self.save_settings()
        self.apply_settings()
    
    # ============================================================
    # 辅助方法
    # ============================================================
    
    def _get_text(self, key: str, default: str) -> str:
        """获取国际化文本"""
        try:
            from shared.service_locator import ServiceLocator
            from shared.service_names import SVC_I18N_MANAGER
            i18n = ServiceLocator.get_optional(SVC_I18N_MANAGER)
            if i18n:
                return i18n.get_text(key, default)
        except Exception:
            pass
        return default


# ============================================================
# 模块导出
# ============================================================

__all__ = [
    "SimulationSettingsDialog",
    "CHART_CATEGORY_NAMES",
    "CHART_CATEGORY_NAMES_EN",
]
