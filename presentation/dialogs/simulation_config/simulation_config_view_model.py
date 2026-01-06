# Simulation Config ViewModel
"""
仿真配置对话框 ViewModel

职责：
- 作为 UI 与 SimulationConfigService 之间的中间层
- 管理配置编辑状态（脏标记、校验错误）
- 提供配置字段的更新方法
- 发射配置变更和校验失败信号

设计原则：
- 继承 BaseViewModel，使用统一的事件订阅和属性通知机制
- 不直接持有 UI 组件引用
- 通过信号通知 UI 更新

被调用方：
- simulation_config_dialog.py

使用示例：
    view_model = SimulationConfigViewModel()
    view_model.config_changed.connect(on_config_changed)
    view_model.validation_failed.connect(on_validation_failed)
    view_model.initialize()
    
    # 加载配置
    view_model.load_config("/path/to/project")
    
    # 更新字段
    view_model.update_ac_config("start_freq", 10.0)
    
    # 保存配置
    if view_model.validate_all():
        view_model.save_config("/path/to/project")
"""

import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from PyQt6.QtCore import pyqtSignal

from presentation.core.base_view_model import BaseViewModel
from domain.simulation.models.simulation_config import (
    ACAnalysisConfig,
    ConvergenceConfig,
    DCAnalysisConfig,
    GlobalSimulationConfig,
    NoiseConfig,
    TransientConfig,
)
from domain.simulation.service.simulation_config_service import (
    FullSimulationConfig,
    SimulationConfigService,
    ValidationError,
    ValidationResult,
    simulation_config_service,
)


class SimulationConfigViewModel(BaseViewModel):
    """
    仿真配置对话框 ViewModel
    
    管理仿真配置的编辑状态，提供配置加载、更新、校验、保存功能。
    """
    
    # 信号定义
    config_changed = pyqtSignal()
    """配置变更时发射"""
    
    validation_failed = pyqtSignal(list)
    """校验失败时发射，携带错误列表 List[str]"""
    
    save_completed = pyqtSignal(bool)
    """保存完成时发射，携带是否成功"""
    
    def __init__(
        self,
        config_service: Optional[SimulationConfigService] = None,
    ):
        super().__init__()
        
        self._logger = logging.getLogger(__name__)
        
        # 服务引用
        self._config_service = config_service or simulation_config_service
        
        # 配置数据（编辑中的副本）
        self._config: FullSimulationConfig = FullSimulationConfig.get_default()
        
        # 原始配置（用于检测变更）
        self._original_config: Optional[FullSimulationConfig] = None
        
        # 状态
        self._is_dirty: bool = False
        self._validation_errors: List[str] = []
        self._project_root: Optional[str] = None
    
    # ============================================================
    # 属性访问器
    # ============================================================
    
    @property
    def ac_config(self) -> ACAnalysisConfig:
        """AC 分析配置"""
        return self._config.ac
    
    @property
    def dc_config(self) -> DCAnalysisConfig:
        """DC 分析配置"""
        return self._config.dc
    
    @property
    def transient_config(self) -> TransientConfig:
        """瞬态分析配置"""
        return self._config.transient
    
    @property
    def noise_config(self) -> NoiseConfig:
        """噪声分析配置"""
        return self._config.noise
    
    @property
    def convergence_config(self) -> ConvergenceConfig:
        """收敛参数配置"""
        return self._config.global_config.convergence
    
    @property
    def global_config(self) -> GlobalSimulationConfig:
        """全局配置"""
        return self._config.global_config
    
    @property
    def validation_errors(self) -> List[str]:
        """校验错误列表"""
        return self._validation_errors
    
    @property
    def is_dirty(self) -> bool:
        """是否有未保存的修改"""
        return self._is_dirty
    
    @property
    def project_root(self) -> Optional[str]:
        """当前项目根目录"""
        return self._project_root
    
    # ============================================================
    # 生命周期
    # ============================================================
    
    def initialize(self):
        """初始化 ViewModel"""
        super().initialize()
        self._logger.info("SimulationConfigViewModel initialized")
    
    # ============================================================
    # 配置加载
    # ============================================================
    
    def load_config(self, project_root: str) -> bool:
        """
        从项目加载配置
        
        Args:
            project_root: 项目根目录
            
        Returns:
            bool: 是否加载成功
        """
        self._project_root = project_root
        
        try:
            self._config = self._config_service.load_config(project_root)
            self._original_config = FullSimulationConfig.from_dict(
                self._config.to_dict()
            )
            self._is_dirty = False
            self._validation_errors = []
            
            self._notify_all_properties()
            self._logger.info(f"Config loaded from {project_root}")
            return True
            
        except Exception as e:
            self._logger.error(f"Failed to load config: {e}")
            return False
    
    # ============================================================
    # 配置保存
    # ============================================================
    
    def save_config(self, project_root: Optional[str] = None) -> bool:
        """
        保存配置到项目
        
        Args:
            project_root: 项目根目录（可选，默认使用加载时的路径）
            
        Returns:
            bool: 是否保存成功
        """
        root = project_root or self._project_root
        if not root:
            self._logger.error("No project root specified")
            self.save_completed.emit(False)
            return False
        
        # 先校验
        if not self.validate_all():
            self.save_completed.emit(False)
            return False
        
        try:
            success = self._config_service.save_config(root, self._config)
            
            if success:
                self._original_config = FullSimulationConfig.from_dict(
                    self._config.to_dict()
                )
                self._is_dirty = False
                self.notify_property_changed("is_dirty", False)
                self._logger.info(f"Config saved to {root}")
            
            self.save_completed.emit(success)
            return success
            
        except Exception as e:
            self._logger.error(f"Failed to save config: {e}")
            self.save_completed.emit(False)
            return False
    
    # ============================================================
    # 配置校验
    # ============================================================
    
    def validate_all(self) -> bool:
        """
        校验所有配置
        
        Returns:
            bool: 是否通过校验
        """
        result = self._config_service.validate_config(self._config)
        
        if result.is_valid:
            self._validation_errors = []
            return True
        
        # 转换错误为字符串列表
        self._validation_errors = [
            f"{err.field}: {err.message}" for err in result.errors
        ]
        
        self.validation_failed.emit(self._validation_errors)
        self.notify_property_changed("validation_errors", self._validation_errors)
        
        return False
    
    def validate_field(self, config_type: str, field_name: str) -> Optional[str]:
        """
        校验单个字段
        
        Args:
            config_type: 配置类型（"ac", "dc", "transient", "noise", "convergence", "global"）
            field_name: 字段名
            
        Returns:
            Optional[str]: 错误消息，None 表示通过
        """
        result = self._config_service.validate_config(self._config)
        
        full_field = f"{config_type}.{field_name}"
        for err in result.errors:
            if err.field == full_field:
                return err.message
        
        return None
    
    # ============================================================
    # 配置重置
    # ============================================================
    
    def reset_to_default(self) -> None:
        """重置为默认配置"""
        self._config = FullSimulationConfig.get_default()
        self._mark_dirty()
        self._notify_all_properties()
        self._logger.info("Config reset to default")
    
    def revert_changes(self) -> None:
        """撤销所有未保存的修改"""
        if self._original_config:
            self._config = FullSimulationConfig.from_dict(
                self._original_config.to_dict()
            )
            self._is_dirty = False
            self._validation_errors = []
            self._notify_all_properties()
            self._logger.info("Changes reverted")
    
    # ============================================================
    # AC 配置更新
    # ============================================================
    
    def update_ac_config(self, field: str, value: Any) -> None:
        """
        更新 AC 配置字段
        
        Args:
            field: 字段名（start_freq, stop_freq, points_per_decade, sweep_type）
            value: 新值
        """
        if not hasattr(self._config.ac, field):
            self._logger.warning(f"Unknown AC config field: {field}")
            return
        
        setattr(self._config.ac, field, value)
        self._mark_dirty()
        self.notify_property_changed("ac_config", self._config.ac)
    
    def set_ac_config(self, config: ACAnalysisConfig) -> None:
        """
        设置完整的 AC 配置
        
        Args:
            config: AC 配置对象
        """
        self._config.ac = config
        self._mark_dirty()
        self.notify_property_changed("ac_config", self._config.ac)
    
    # ============================================================
    # DC 配置更新
    # ============================================================
    
    def update_dc_config(self, field: str, value: Any) -> None:
        """
        更新 DC 配置字段
        
        Args:
            field: 字段名（source_name, start_value, stop_value, step）
            value: 新值
        """
        if not hasattr(self._config.dc, field):
            self._logger.warning(f"Unknown DC config field: {field}")
            return
        
        setattr(self._config.dc, field, value)
        self._mark_dirty()
        self.notify_property_changed("dc_config", self._config.dc)
    
    def set_dc_config(self, config: DCAnalysisConfig) -> None:
        """
        设置完整的 DC 配置
        
        Args:
            config: DC 配置对象
        """
        self._config.dc = config
        self._mark_dirty()
        self.notify_property_changed("dc_config", self._config.dc)
    
    # ============================================================
    # 瞬态配置更新
    # ============================================================
    
    def update_transient_config(self, field: str, value: Any) -> None:
        """
        更新瞬态配置字段
        
        Args:
            field: 字段名（step_time, end_time, start_time, max_step, use_initial_conditions）
            value: 新值
        """
        if not hasattr(self._config.transient, field):
            self._logger.warning(f"Unknown transient config field: {field}")
            return
        
        setattr(self._config.transient, field, value)
        self._mark_dirty()
        self.notify_property_changed("transient_config", self._config.transient)
    
    def set_transient_config(self, config: TransientConfig) -> None:
        """
        设置完整的瞬态配置
        
        Args:
            config: 瞬态配置对象
        """
        self._config.transient = config
        self._mark_dirty()
        self.notify_property_changed("transient_config", self._config.transient)
    
    # ============================================================
    # 噪声配置更新
    # ============================================================
    
    def update_noise_config(self, field: str, value: Any) -> None:
        """
        更新噪声配置字段
        
        Args:
            field: 字段名（output_node, input_source, start_freq, stop_freq）
            value: 新值
        """
        if not hasattr(self._config.noise, field):
            self._logger.warning(f"Unknown noise config field: {field}")
            return
        
        setattr(self._config.noise, field, value)
        self._mark_dirty()
        self.notify_property_changed("noise_config", self._config.noise)
    
    def set_noise_config(self, config: NoiseConfig) -> None:
        """
        设置完整的噪声配置
        
        Args:
            config: 噪声配置对象
        """
        self._config.noise = config
        self._mark_dirty()
        self.notify_property_changed("noise_config", self._config.noise)
    
    # ============================================================
    # 收敛配置更新
    # ============================================================
    
    def update_convergence_config(self, field: str, value: Any) -> None:
        """
        更新收敛配置字段
        
        Args:
            field: 字段名（gmin, abstol, reltol, vntol, itl1, itl4）
            value: 新值
        """
        if not hasattr(self._config.global_config.convergence, field):
            self._logger.warning(f"Unknown convergence config field: {field}")
            return
        
        setattr(self._config.global_config.convergence, field, value)
        self._mark_dirty()
        self.notify_property_changed(
            "convergence_config", self._config.global_config.convergence
        )
    
    def set_convergence_config(self, config: ConvergenceConfig) -> None:
        """
        设置完整的收敛配置
        
        Args:
            config: 收敛配置对象
        """
        self._config.global_config.convergence = config
        self._mark_dirty()
        self.notify_property_changed(
            "convergence_config", self._config.global_config.convergence
        )
    
    # ============================================================
    # 全局配置更新
    # ============================================================
    
    def update_global_config(self, field: str, value: Any) -> None:
        """
        更新全局配置字段
        
        Args:
            field: 字段名（timeout_seconds, temperature）
            value: 新值
        """
        if field == "convergence":
            self._logger.warning("Use update_convergence_config for convergence")
            return
        
        if not hasattr(self._config.global_config, field):
            self._logger.warning(f"Unknown global config field: {field}")
            return
        
        setattr(self._config.global_config, field, value)
        self._mark_dirty()
        self.notify_property_changed("global_config", self._config.global_config)
    
    def set_global_config(self, config: GlobalSimulationConfig) -> None:
        """
        设置完整的全局配置
        
        Args:
            config: 全局配置对象
        """
        self._config.global_config = config
        self._mark_dirty()
        self.notify_property_changed("global_config", self._config.global_config)
    
    # ============================================================
    # 辅助方法
    # ============================================================
    
    def _mark_dirty(self) -> None:
        """标记配置已修改"""
        if not self._is_dirty:
            self._is_dirty = True
            self.notify_property_changed("is_dirty", True)
        self.config_changed.emit()
    
    def _notify_all_properties(self) -> None:
        """通知所有属性变更"""
        self.notify_properties_changed({
            "ac_config": self._config.ac,
            "dc_config": self._config.dc,
            "transient_config": self._config.transient,
            "noise_config": self._config.noise,
            "convergence_config": self._config.global_config.convergence,
            "global_config": self._config.global_config,
            "is_dirty": self._is_dirty,
            "validation_errors": self._validation_errors,
        })
    
    def get_config_dict(self) -> Dict[str, Any]:
        """
        获取配置的字典表示
        
        Returns:
            Dict: 配置字典
        """
        return self._config.to_dict()
    
    def get_full_config(self) -> FullSimulationConfig:
        """
        获取完整配置对象
        
        Returns:
            FullSimulationConfig: 配置对象
        """
        return self._config


# ============================================================
# 模块导出
# ============================================================

__all__ = [
    "SimulationConfigViewModel",
]
