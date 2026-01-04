# SimulationConfig - Simulation Configuration Data Classes
"""
仿真配置数据类

职责：
- 定义仿真配置的数据结构（纯数据类，不含业务逻辑）
- 提供配置的序列化和反序列化
- 提供默认配置值

设计原则：
- 配置数据类仅定义结构，配置的读写、校验、持久化由 SimulationConfigService 处理
- 使用 dataclass 确保类型安全
- 提供合理的默认值作为初始状态
- 所有参数对用户透明可见、可编辑

使用示例：
    # 创建 AC 分析配置
    ac_config = ACAnalysisConfig(
        start_freq=1.0,
        stop_freq=1e9,
        points_per_decade=20,
        sweep_type="dec"
    )
    
    # 序列化
    config_dict = ac_config.to_dict()
    
    # 反序列化
    loaded_config = ACAnalysisConfig.from_dict(config_dict)
    
    # 获取默认配置
    default_config = ACAnalysisConfig.get_default()
"""

from dataclasses import dataclass, field
from typing import Any, Dict, Optional


# ============================================================
# ACAnalysisConfig - AC 分析配置
# ============================================================

@dataclass
class ACAnalysisConfig:
    """
    AC 分析配置
    
    Attributes:
        start_freq: 起始频率（Hz）
        stop_freq: 终止频率（Hz）
        points_per_decade: 每十倍频程点数
        sweep_type: 扫描类型（dec/oct/lin）
    """
    
    start_freq: float = 1.0
    """起始频率（Hz），默认 1 Hz"""
    
    stop_freq: float = 1e9
    """终止频率（Hz），默认 1 GHz"""
    
    points_per_decade: int = 20
    """每十倍频程点数，默认 20 点"""
    
    sweep_type: str = "dec"
    """扫描类型（dec=十倍频程, oct=八倍频程, lin=线性），默认 dec"""
    
    # ============================================================
    # 序列化方法
    # ============================================================
    
    def to_dict(self) -> Dict[str, Any]:
        """
        序列化为字典
        
        Returns:
            Dict: 序列化后的字典
        """
        return {
            "start_freq": self.start_freq,
            "stop_freq": self.stop_freq,
            "points_per_decade": self.points_per_decade,
            "sweep_type": self.sweep_type,
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ACAnalysisConfig":
        """
        从字典反序列化
        
        Args:
            data: 序列化的字典
            
        Returns:
            ACAnalysisConfig: 反序列化后的对象
        """
        return cls(
            start_freq=data.get("start_freq", 1.0),
            stop_freq=data.get("stop_freq", 1e9),
            points_per_decade=data.get("points_per_decade", 20),
            sweep_type=data.get("sweep_type", "dec"),
        )
    
    @classmethod
    def get_default(cls) -> "ACAnalysisConfig":
        """
        获取默认配置
        
        Returns:
            ACAnalysisConfig: 默认配置对象
        """
        return cls()


# ============================================================
# DCAnalysisConfig - DC 分析配置
# ============================================================

@dataclass
class DCAnalysisConfig:
    """
    DC 分析配置
    
    Attributes:
        source_name: 扫描源名称（如 "Vin", "Vdd"）
        start_value: 起始值（V 或 A）
        stop_value: 终止值（V 或 A）
        step: 步进值（V 或 A）
    """
    
    source_name: str = ""
    """扫描源名称（如 "Vin", "Vdd"），默认为空（需用户指定）"""
    
    start_value: float = 0.0
    """起始值（V 或 A），默认 0"""
    
    stop_value: float = 5.0
    """终止值（V 或 A），默认 5"""
    
    step: float = 0.1
    """步进值（V 或 A），默认 0.1"""
    
    # ============================================================
    # 序列化方法
    # ============================================================
    
    def to_dict(self) -> Dict[str, Any]:
        """
        序列化为字典
        
        Returns:
            Dict: 序列化后的字典
        """
        return {
            "source_name": self.source_name,
            "start_value": self.start_value,
            "stop_value": self.stop_value,
            "step": self.step,
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "DCAnalysisConfig":
        """
        从字典反序列化
        
        Args:
            data: 序列化的字典
            
        Returns:
            DCAnalysisConfig: 反序列化后的对象
        """
        return cls(
            source_name=data.get("source_name", ""),
            start_value=data.get("start_value", 0.0),
            stop_value=data.get("stop_value", 5.0),
            step=data.get("step", 0.1),
        )
    
    @classmethod
    def get_default(cls) -> "DCAnalysisConfig":
        """
        获取默认配置
        
        Returns:
            DCAnalysisConfig: 默认配置对象
        """
        return cls()


# ============================================================
# TransientConfig - 瞬态分析配置
# ============================================================

@dataclass
class TransientConfig:
    """
    瞬态分析配置
    
    Attributes:
        step_time: 时间步长（秒）
        end_time: 终止时间（秒）
        start_time: 起始时间（秒）
        max_step: 最大步长（秒，可选）
        use_initial_conditions: 是否使用初始条件
    """
    
    step_time: float = 1e-6
    """时间步长（秒），默认 1 μs"""
    
    end_time: float = 1e-3
    """终止时间（秒），默认 1 ms"""
    
    start_time: float = 0.0
    """起始时间（秒），默认 0"""
    
    max_step: Optional[float] = None
    """最大步长（秒），默认 None（由仿真器自动决定）"""
    
    use_initial_conditions: bool = False
    """是否使用初始条件，默认 False"""
    
    # ============================================================
    # 序列化方法
    # ============================================================
    
    def to_dict(self) -> Dict[str, Any]:
        """
        序列化为字典
        
        Returns:
            Dict: 序列化后的字典
        """
        return {
            "step_time": self.step_time,
            "end_time": self.end_time,
            "start_time": self.start_time,
            "max_step": self.max_step,
            "use_initial_conditions": self.use_initial_conditions,
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "TransientConfig":
        """
        从字典反序列化
        
        Args:
            data: 序列化的字典
            
        Returns:
            TransientConfig: 反序列化后的对象
        """
        return cls(
            step_time=data.get("step_time", 1e-6),
            end_time=data.get("end_time", 1e-3),
            start_time=data.get("start_time", 0.0),
            max_step=data.get("max_step"),
            use_initial_conditions=data.get("use_initial_conditions", False),
        )
    
    @classmethod
    def get_default(cls) -> "TransientConfig":
        """
        获取默认配置
        
        Returns:
            TransientConfig: 默认配置对象
        """
        return cls()


# ============================================================
# NoiseConfig - 噪声分析配置
# ============================================================

@dataclass
class NoiseConfig:
    """
    噪声分析配置
    
    Attributes:
        output_node: 输出节点（如 "out", "vout"）
        input_source: 输入源（如 "Vin", "Vsig"）
        start_freq: 起始频率（Hz）
        stop_freq: 终止频率（Hz）
    """
    
    output_node: str = ""
    """输出节点（如 "out", "vout"），默认为空（需用户指定）"""
    
    input_source: str = ""
    """输入源（如 "Vin", "Vsig"），默认为空（需用户指定）"""
    
    start_freq: float = 1.0
    """起始频率（Hz），默认 1 Hz"""
    
    stop_freq: float = 1e6
    """终止频率（Hz），默认 1 MHz"""
    
    # ============================================================
    # 序列化方法
    # ============================================================
    
    def to_dict(self) -> Dict[str, Any]:
        """
        序列化为字典
        
        Returns:
            Dict: 序列化后的字典
        """
        return {
            "output_node": self.output_node,
            "input_source": self.input_source,
            "start_freq": self.start_freq,
            "stop_freq": self.stop_freq,
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "NoiseConfig":
        """
        从字典反序列化
        
        Args:
            data: 序列化的字典
            
        Returns:
            NoiseConfig: 反序列化后的对象
        """
        return cls(
            output_node=data.get("output_node", ""),
            input_source=data.get("input_source", ""),
            start_freq=data.get("start_freq", 1.0),
            stop_freq=data.get("stop_freq", 1e6),
        )
    
    @classmethod
    def get_default(cls) -> "NoiseConfig":
        """
        获取默认配置
        
        Returns:
            NoiseConfig: 默认配置对象
        """
        return cls()


# ============================================================
# ConvergenceConfig - 收敛参数配置
# ============================================================

@dataclass
class ConvergenceConfig:
    """
    收敛参数配置（用户可调）
    
    Attributes:
        gmin: 最小电导（S）
        abstol: 绝对电流容差（A）
        reltol: 相对容差
        vntol: 电压容差（V）
        itl1: DC 迭代限制
        itl4: 瞬态迭代限制
    """
    
    gmin: float = 1e-12
    """最小电导（S），默认 1e-12"""
    
    abstol: float = 1e-12
    """绝对电流容差（A），默认 1e-12"""
    
    reltol: float = 1e-3
    """相对容差，默认 1e-3（0.1%）"""
    
    vntol: float = 1e-6
    """电压容差（V），默认 1 μV"""
    
    itl1: int = 100
    """DC 迭代限制，默认 100"""
    
    itl4: int = 10
    """瞬态迭代限制，默认 10"""
    
    # ============================================================
    # 序列化方法
    # ============================================================
    
    def to_dict(self) -> Dict[str, Any]:
        """
        序列化为字典
        
        Returns:
            Dict: 序列化后的字典
        """
        return {
            "gmin": self.gmin,
            "abstol": self.abstol,
            "reltol": self.reltol,
            "vntol": self.vntol,
            "itl1": self.itl1,
            "itl4": self.itl4,
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ConvergenceConfig":
        """
        从字典反序列化
        
        Args:
            data: 序列化的字典
            
        Returns:
            ConvergenceConfig: 反序列化后的对象
        """
        return cls(
            gmin=data.get("gmin", 1e-12),
            abstol=data.get("abstol", 1e-12),
            reltol=data.get("reltol", 1e-3),
            vntol=data.get("vntol", 1e-6),
            itl1=data.get("itl1", 100),
            itl4=data.get("itl4", 10),
        )
    
    @classmethod
    def get_default(cls) -> "ConvergenceConfig":
        """
        获取默认配置
        
        Returns:
            ConvergenceConfig: 默认配置对象
        """
        return cls()


# ============================================================
# GlobalSimulationConfig - 全局仿真配置
# ============================================================

@dataclass
class GlobalSimulationConfig:
    """
    全局仿真配置
    
    Attributes:
        timeout_seconds: 超时时间（秒）
        temperature: 仿真温度（摄氏度）
        convergence: 收敛参数配置
    """
    
    timeout_seconds: int = 300
    """超时时间（秒），默认 300 秒（5 分钟）"""
    
    temperature: float = 27.0
    """仿真温度（摄氏度），默认 27°C（300K）"""
    
    convergence: ConvergenceConfig = field(default_factory=ConvergenceConfig)
    """收敛参数配置，默认使用 ConvergenceConfig 的默认值"""
    
    # ============================================================
    # 序列化方法
    # ============================================================
    
    def to_dict(self) -> Dict[str, Any]:
        """
        序列化为字典
        
        Returns:
            Dict: 序列化后的字典
        """
        return {
            "timeout_seconds": self.timeout_seconds,
            "temperature": self.temperature,
            "convergence": self.convergence.to_dict(),
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "GlobalSimulationConfig":
        """
        从字典反序列化
        
        Args:
            data: 序列化的字典
            
        Returns:
            GlobalSimulationConfig: 反序列化后的对象
        """
        convergence_data = data.get("convergence", {})
        convergence = ConvergenceConfig.from_dict(convergence_data)
        
        return cls(
            timeout_seconds=data.get("timeout_seconds", 300),
            temperature=data.get("temperature", 27.0),
            convergence=convergence,
        )
    
    @classmethod
    def get_default(cls) -> "GlobalSimulationConfig":
        """
        获取默认配置
        
        Returns:
            GlobalSimulationConfig: 默认配置对象
        """
        return cls()


# ============================================================
# 模块导出
# ============================================================

__all__ = [
    "ACAnalysisConfig",
    "DCAnalysisConfig",
    "TransientConfig",
    "NoiseConfig",
    "ConvergenceConfig",
    "GlobalSimulationConfig",
]
