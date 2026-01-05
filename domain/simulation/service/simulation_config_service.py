# SimulationConfigService - Simulation Configuration Management Service
"""
仿真配置服务

职责：
- 管理仿真配置的读取、校验、持久化
- 提供配置的默认值和重置功能
- 发布配置变更事件

设计原则：
- 仿真参数由用户通过 UI 手动设置，软件不内置硬编码的预设配置
- 配置数据类仅定义结构，本服务处理读写、校验、持久化
- 配置变更时发布事件通知订阅者

配置存储路径：
- {project_root}/.circuit_ai/simulation_config.json

使用示例：
    from domain.simulation.service import simulation_config_service
    
    # 加载配置
    config = simulation_config_service.load_config("/path/to/project")
    
    # 校验配置
    result = simulation_config_service.validate_config(config)
    if not result.is_valid:
        for error in result.errors:
            print(f"{error.field}: {error.message}")
    
    # 保存配置
    simulation_config_service.save_config("/path/to/project", config)
"""

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

from domain.simulation.models.simulation_config import (
    ACAnalysisConfig,
    ConvergenceConfig,
    DCAnalysisConfig,
    GlobalSimulationConfig,
    NoiseConfig,
    TransientConfig,
)
from shared.event_bus import EventBus
from shared.event_types import EVENT_SIM_CONFIG_CHANGED


# ============================================================
# 常量定义
# ============================================================

CONFIG_FILE_NAME = "simulation_config.json"
CONFIG_DIR = ".circuit_ai"
CONFIG_VERSION = "1.0"


# ============================================================
# ValidationError - 校验错误
# ============================================================

@dataclass
class ValidationError:
    """
    校验错误
    
    Attributes:
        field: 字段路径（如 "ac.start_freq", "global.convergence.reltol"）
        message: 错误消息
        value: 当前值
    """
    field: str
    message: str
    value: Any = None


# ============================================================
# ValidationResult - 校验结果
# ============================================================

@dataclass
class ValidationResult:
    """
    校验结果
    
    Attributes:
        is_valid: 是否通过校验
        errors: 错误列表
    """
    is_valid: bool
    errors: List[ValidationError] = field(default_factory=list)
    
    @classmethod
    def success(cls) -> "ValidationResult":
        """创建成功结果"""
        return cls(is_valid=True, errors=[])
    
    @classmethod
    def failure(cls, errors: List[ValidationError]) -> "ValidationResult":
        """创建失败结果"""
        return cls(is_valid=False, errors=errors)
    
    def add_error(self, field: str, message: str, value: Any = None) -> None:
        """添加错误"""
        self.errors.append(ValidationError(field=field, message=message, value=value))
        self.is_valid = False


# ============================================================
# FullSimulationConfig - 完整仿真配置
# ============================================================

@dataclass
class FullSimulationConfig:
    """
    完整仿真配置（包含所有分析类型配置）
    
    Attributes:
        version: 配置版本
        global_config: 全局配置
        ac: AC 分析配置
        dc: DC 分析配置
        transient: 瞬态分析配置
        noise: 噪声分析配置
    """
    version: str = CONFIG_VERSION
    global_config: GlobalSimulationConfig = field(default_factory=GlobalSimulationConfig)
    ac: ACAnalysisConfig = field(default_factory=ACAnalysisConfig)
    dc: DCAnalysisConfig = field(default_factory=DCAnalysisConfig)
    transient: TransientConfig = field(default_factory=TransientConfig)
    noise: NoiseConfig = field(default_factory=NoiseConfig)
    
    def to_dict(self) -> Dict[str, Any]:
        """序列化为字典"""
        return {
            "version": self.version,
            "global": self.global_config.to_dict(),
            "ac": self.ac.to_dict(),
            "dc": self.dc.to_dict(),
            "transient": self.transient.to_dict(),
            "noise": self.noise.to_dict(),
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "FullSimulationConfig":
        """从字典反序列化"""
        return cls(
            version=data.get("version", CONFIG_VERSION),
            global_config=GlobalSimulationConfig.from_dict(data.get("global", {})),
            ac=ACAnalysisConfig.from_dict(data.get("ac", {})),
            dc=DCAnalysisConfig.from_dict(data.get("dc", {})),
            transient=TransientConfig.from_dict(data.get("transient", {})),
            noise=NoiseConfig.from_dict(data.get("noise", {})),
        )
    
    @classmethod
    def get_default(cls) -> "FullSimulationConfig":
        """获取默认配置"""
        return cls()


# ============================================================
# SimulationConfigService - 仿真配置服务
# ============================================================

class SimulationConfigService:
    """
    仿真配置服务
    
    管理仿真配置的读取、校验、持久化。
    """
    
    def __init__(self, event_bus: Optional[EventBus] = None):
        """
        初始化服务
        
        Args:
            event_bus: 事件总线（可选，用于发布配置变更事件）
        """
        self._logger = logging.getLogger(__name__)
        self._event_bus = event_bus
    
    def _get_event_bus(self) -> Optional[EventBus]:
        """获取事件总线"""
        if self._event_bus is not None:
            return self._event_bus
        try:
            from shared.service_locator import ServiceLocator
            from shared.service_names import SERVICE_EVENT_BUS
            return ServiceLocator.get(SERVICE_EVENT_BUS)
        except Exception:
            return None
    
    def _get_config_path(self, project_root: str) -> Path:
        """获取配置文件路径"""
        return Path(project_root) / CONFIG_DIR / CONFIG_FILE_NAME
    
    # ============================================================
    # 配置加载
    # ============================================================
    
    def load_config(self, project_root: str) -> FullSimulationConfig:
        """
        加载项目配置
        
        如果配置文件不存在，返回默认配置。
        如果配置文件解析失败，记录警告并返回默认配置。
        
        Args:
            project_root: 项目根目录路径
            
        Returns:
            FullSimulationConfig: 配置对象
        """
        config_path = self._get_config_path(project_root)
        
        if not config_path.exists():
            self._logger.debug(f"配置文件不存在，使用默认配置: {config_path}")
            return FullSimulationConfig.get_default()
        
        try:
            content = config_path.read_text(encoding="utf-8")
            data = json.loads(content)
            config = FullSimulationConfig.from_dict(data)
            self._logger.debug(f"已加载配置: {config_path}")
            return config
        except json.JSONDecodeError as e:
            self._logger.warning(f"配置文件 JSON 解析失败，使用默认配置: {e}")
            return FullSimulationConfig.get_default()
        except Exception as e:
            self._logger.warning(f"加载配置失败，使用默认配置: {e}")
            return FullSimulationConfig.get_default()
    
    # ============================================================
    # 配置保存
    # ============================================================
    
    def save_config(
        self,
        project_root: str,
        config: FullSimulationConfig,
        *,
        publish_event: bool = True,
    ) -> bool:
        """
        保存配置到项目
        
        Args:
            project_root: 项目根目录路径
            config: 配置对象
            publish_event: 是否发布配置变更事件
            
        Returns:
            bool: 是否保存成功
        """
        config_path = self._get_config_path(project_root)
        
        try:
            config_path.parent.mkdir(parents=True, exist_ok=True)
            content = json.dumps(config.to_dict(), indent=2, ensure_ascii=False)
            config_path.write_text(content, encoding="utf-8")
            self._logger.info(f"配置已保存: {config_path}")
            
            if publish_event:
                self._publish_config_changed_event(project_root)
            
            return True
        except Exception as e:
            self._logger.error(f"保存配置失败: {e}")
            return False
    
    # ============================================================
    # 配置校验
    # ============================================================
    
    def validate_config(self, config: FullSimulationConfig) -> ValidationResult:
        """
        校验配置有效性
        
        校验规则：
        - 频率参数：start_freq > 0，stop_freq > start_freq
        - 时间参数：step_time > 0，end_time > start_time
        - 收敛参数：gmin > 0，abstol > 0，reltol 在 (0, 1) 范围内
        
        Args:
            config: 配置对象
            
        Returns:
            ValidationResult: 校验结果
        """
        result = ValidationResult.success()
        
        # 校验全局配置
        self._validate_global_config(config.global_config, result)
        
        # 校验 AC 配置
        self._validate_ac_config(config.ac, result)
        
        # 校验 DC 配置
        self._validate_dc_config(config.dc, result)
        
        # 校验瞬态配置
        self._validate_transient_config(config.transient, result)
        
        # 校验噪声配置
        self._validate_noise_config(config.noise, result)
        
        return result
    
    def _validate_global_config(
        self,
        config: GlobalSimulationConfig,
        result: ValidationResult,
    ) -> None:
        """校验全局配置"""
        if config.timeout_seconds <= 0:
            result.add_error(
                "global.timeout_seconds",
                "超时时间必须大于 0",
                config.timeout_seconds,
            )
        
        # 校验收敛参数
        conv = config.convergence
        if conv.gmin <= 0:
            result.add_error("global.convergence.gmin", "gmin 必须大于 0", conv.gmin)
        if conv.abstol <= 0:
            result.add_error("global.convergence.abstol", "abstol 必须大于 0", conv.abstol)
        if not (0 < conv.reltol < 1):
            result.add_error(
                "global.convergence.reltol",
                "reltol 必须在 (0, 1) 范围内",
                conv.reltol,
            )
        if conv.vntol <= 0:
            result.add_error("global.convergence.vntol", "vntol 必须大于 0", conv.vntol)
        if conv.itl1 <= 0:
            result.add_error("global.convergence.itl1", "itl1 必须大于 0", conv.itl1)
        if conv.itl4 <= 0:
            result.add_error("global.convergence.itl4", "itl4 必须大于 0", conv.itl4)
    
    def _validate_ac_config(
        self,
        config: ACAnalysisConfig,
        result: ValidationResult,
    ) -> None:
        """校验 AC 配置"""
        if config.start_freq <= 0:
            result.add_error("ac.start_freq", "起始频率必须大于 0", config.start_freq)
        if config.stop_freq <= config.start_freq:
            result.add_error(
                "ac.stop_freq",
                "终止频率必须大于起始频率",
                config.stop_freq,
            )
        if config.points_per_decade <= 0:
            result.add_error(
                "ac.points_per_decade",
                "每十倍频程点数必须大于 0",
                config.points_per_decade,
            )
        if config.sweep_type not in ("dec", "oct", "lin"):
            result.add_error(
                "ac.sweep_type",
                "扫描类型必须是 dec、oct 或 lin",
                config.sweep_type,
            )
    
    def _validate_dc_config(
        self,
        config: DCAnalysisConfig,
        result: ValidationResult,
    ) -> None:
        """校验 DC 配置"""
        if config.step <= 0:
            result.add_error("dc.step", "步进值必须大于 0", config.step)
        if config.stop_value <= config.start_value:
            result.add_error(
                "dc.stop_value",
                "终止值必须大于起始值",
                config.stop_value,
            )
    
    def _validate_transient_config(
        self,
        config: TransientConfig,
        result: ValidationResult,
    ) -> None:
        """校验瞬态配置"""
        if config.step_time <= 0:
            result.add_error("transient.step_time", "时间步长必须大于 0", config.step_time)
        if config.end_time <= config.start_time:
            result.add_error(
                "transient.end_time",
                "终止时间必须大于起始时间",
                config.end_time,
            )
        if config.max_step is not None and config.max_step <= 0:
            result.add_error(
                "transient.max_step",
                "最大步长必须大于 0",
                config.max_step,
            )
    
    def _validate_noise_config(
        self,
        config: NoiseConfig,
        result: ValidationResult,
    ) -> None:
        """校验噪声配置"""
        if config.start_freq <= 0:
            result.add_error("noise.start_freq", "起始频率必须大于 0", config.start_freq)
        if config.stop_freq <= config.start_freq:
            result.add_error(
                "noise.stop_freq",
                "终止频率必须大于起始频率",
                config.stop_freq,
            )
    
    # ============================================================
    # 默认配置
    # ============================================================
    
    def get_default_config(self) -> FullSimulationConfig:
        """
        获取默认配置
        
        Returns:
            FullSimulationConfig: 默认配置对象
        """
        return FullSimulationConfig.get_default()
    
    def reset_to_default(self, project_root: str) -> bool:
        """
        重置为默认配置
        
        Args:
            project_root: 项目根目录路径
            
        Returns:
            bool: 是否重置成功
        """
        default_config = self.get_default_config()
        return self.save_config(project_root, default_config)
    
    # ============================================================
    # 配置文件管理
    # ============================================================
    
    def config_exists(self, project_root: str) -> bool:
        """
        检查配置文件是否存在
        
        Args:
            project_root: 项目根目录路径
            
        Returns:
            bool: 是否存在
        """
        return self._get_config_path(project_root).exists()
    
    def delete_config(self, project_root: str) -> bool:
        """
        删除配置文件
        
        Args:
            project_root: 项目根目录路径
            
        Returns:
            bool: 是否删除成功
        """
        config_path = self._get_config_path(project_root)
        if config_path.exists():
            try:
                config_path.unlink()
                self._logger.info(f"配置文件已删除: {config_path}")
                return True
            except Exception as e:
                self._logger.error(f"删除配置文件失败: {e}")
                return False
        return True
    
    # ============================================================
    # 事件发布
    # ============================================================
    
    def _publish_config_changed_event(self, project_root: str) -> None:
        """发布配置变更事件"""
        bus = self._get_event_bus()
        if bus:
            bus.publish(EVENT_SIM_CONFIG_CHANGED, {
                "project_root": project_root,
            })


# ============================================================
# 模块级单例
# ============================================================

simulation_config_service = SimulationConfigService()


# ============================================================
# 模块导出
# ============================================================

__all__ = [
    "SimulationConfigService",
    "FullSimulationConfig",
    "ValidationResult",
    "ValidationError",
    "simulation_config_service",
    "CONFIG_FILE_NAME",
    "CONFIG_DIR",
]
