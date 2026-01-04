# SimulationExecutor - Abstract Base Class for Simulation Executors
"""
仿真执行器抽象基类

职责：
- 定义统一的仿真执行接口
- 规范仿真执行器的行为契约
- 提供文件类型判断和校验的通用逻辑

设计原则：
- 策略模式：将仿真执行方式与文件选择方式解耦
- 开闭原则：新增仿真方式只需实现此接口并注册
- 依赖倒置：高层模块依赖抽象接口，不依赖具体实现

使用示例：
    # 实现具体执行器
    class SpiceExecutor(SimulationExecutor):
        def get_name(self) -> str:
            return "spice"
        
        def get_supported_extensions(self) -> List[str]:
            return [".cir", ".sp", ".spice"]
        
        def execute(self, file_path: str, analysis_config: Dict) -> SimulationResult:
            # 实现 SPICE 仿真逻辑
            pass
    
    # 使用执行器
    executor = SpiceExecutor()
    if executor.can_handle("amplifier.cir"):
        result = executor.execute("amplifier.cir", {})
"""

from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any, Dict, List, Optional

from domain.simulation.models.simulation_result import SimulationResult


# ============================================================
# SimulationExecutor - 仿真执行器抽象基类
# ============================================================

class SimulationExecutor(ABC):
    """
    仿真执行器抽象基类
    
    定义了所有仿真执行器必须实现的接口方法，确保不同执行器之间的行为一致性
    
    子类必须实现：
    - get_name(): 返回执行器名称
    - get_supported_extensions(): 返回支持的文件扩展名列表
    - execute(): 执行仿真并返回标准化结果
    - get_available_analyses(): 返回支持的分析类型列表
    
    子类可选实现：
    - validate_file(): 校验文件格式（默认实现仅检查文件存在性）
    - can_handle(): 判断是否能处理文件（默认基于扩展名判断）
    """
    
    # ============================================================
    # 抽象方法（子类必须实现）
    # ============================================================
    
    @abstractmethod
    def get_name(self) -> str:
        """
        返回执行器名称
        
        用于执行器注册和日志记录
        
        Returns:
            str: 执行器名称（如 "spice", "python"）
            
        示例：
            >>> executor.get_name()
            "spice"
        """
        pass
    
    @abstractmethod
    def get_supported_extensions(self) -> List[str]:
        """
        返回支持的文件扩展名列表
        
        用于自动选择合适的执行器
        
        Returns:
            List[str]: 文件扩展名列表（包含点号，如 [".cir", ".sp"]）
            
        示例：
            >>> executor.get_supported_extensions()
            [".cir", ".sp", ".spice", ".net", ".ckt"]
        """
        pass
    
    @abstractmethod
    def execute(
        self,
        file_path: str,
        analysis_config: Optional[Dict[str, Any]] = None
    ) -> SimulationResult:
        """
        执行仿真并返回标准化结果
        
        这是执行器的核心方法，负责：
        1. 加载电路文件
        2. 配置仿真参数
        3. 执行仿真
        4. 解析结果
        5. 返回标准化的 SimulationResult 对象
        
        Args:
            file_path: 电路文件路径（绝对路径或相对路径）
            analysis_config: 仿真配置字典（可选）
                - analysis_type: 分析类型（"ac", "dc", "tran", "noise"）
                - 其他参数根据分析类型而定
        
        Returns:
            SimulationResult: 标准化的仿真结果对象
            
        Raises:
            FileNotFoundError: 文件不存在
            ValueError: 配置参数无效
            RuntimeError: 仿真执行失败
            
        示例：
            >>> result = executor.execute(
            ...     "amplifier.cir",
            ...     {"analysis_type": "ac", "start_freq": 1.0, "stop_freq": 1e9}
            ... )
            >>> if result.success:
            ...     print(f"仿真成功，耗时 {result.duration_seconds:.2f}s")
        """
        pass
    
    @abstractmethod
    def get_available_analyses(self) -> List[str]:
        """
        返回支持的分析类型列表
        
        用于 UI 显示和配置验证
        
        Returns:
            List[str]: 分析类型列表（如 ["ac", "dc", "tran", "noise"]）
            
        示例：
            >>> executor.get_available_analyses()
            ["ac", "dc", "tran", "noise", "op"]
        """
        pass
    
    # ============================================================
    # 具体方法（子类可选覆盖）
    # ============================================================
    
    def can_handle(self, file_path: str) -> bool:
        """
        判断是否能处理指定文件
        
        默认实现基于文件扩展名判断，子类可覆盖此方法实现更复杂的判断逻辑
        
        Args:
            file_path: 文件路径
            
        Returns:
            bool: 是否能处理该文件
            
        示例：
            >>> executor.can_handle("amplifier.cir")
            True
            >>> executor.can_handle("script.py")
            False
        """
        file_ext = Path(file_path).suffix.lower()
        supported_exts = [ext.lower() for ext in self.get_supported_extensions()]
        return file_ext in supported_exts
    
    def validate_file(self, file_path: str) -> tuple[bool, Optional[str]]:
        """
        校验文件格式是否有效
        
        默认实现仅检查文件存在性，子类可覆盖此方法实现更严格的校验
        
        Args:
            file_path: 文件路径
            
        Returns:
            tuple[bool, Optional[str]]: (是否有效, 错误消息)
            - 有效时返回 (True, None)
            - 无效时返回 (False, "错误消息")
            
        示例：
            >>> valid, error = executor.validate_file("amplifier.cir")
            >>> if not valid:
            ...     print(f"文件无效: {error}")
        """
        path = Path(file_path)
        
        # 检查文件是否存在
        if not path.exists():
            return False, f"文件不存在: {file_path}"
        
        # 检查是否为文件（而非目录）
        if not path.is_file():
            return False, f"路径不是文件: {file_path}"
        
        # 检查文件扩展名
        if not self.can_handle(file_path):
            supported = ", ".join(self.get_supported_extensions())
            return False, f"不支持的文件类型，支持的扩展名: {supported}"
        
        # 检查文件是否可读
        try:
            with open(path, 'r', encoding='utf-8', errors='ignore') as f:
                f.read(1)  # 尝试读取一个字符
        except PermissionError:
            return False, f"无权限读取文件: {file_path}"
        except Exception as e:
            return False, f"文件读取失败: {e}"
        
        return True, None
    
    def get_executor_info(self) -> Dict[str, Any]:
        """
        获取执行器信息（用于调试和日志）
        
        Returns:
            Dict: 执行器信息字典
            
        示例：
            >>> info = executor.get_executor_info()
            >>> print(info)
            {
                "name": "spice",
                "supported_extensions": [".cir", ".sp", ".spice"],
                "available_analyses": ["ac", "dc", "tran", "noise"]
            }
        """
        return {
            "name": self.get_name(),
            "supported_extensions": self.get_supported_extensions(),
            "available_analyses": self.get_available_analyses(),
        }
    
    def __str__(self) -> str:
        """
        返回执行器的字符串表示
        
        Returns:
            str: 执行器描述
        """
        return f"{self.__class__.__name__}(name={self.get_name()})"
    
    def __repr__(self) -> str:
        """
        返回执行器的详细表示
        
        Returns:
            str: 执行器详细描述
        """
        return (
            f"{self.__class__.__name__}("
            f"name={self.get_name()}, "
            f"extensions={self.get_supported_extensions()}, "
            f"analyses={self.get_available_analyses()})"
        )


# ============================================================
# 辅助函数
# ============================================================

def validate_analysis_config(
    analysis_config: Optional[Dict[str, Any]],
    required_keys: List[str]
) -> tuple[bool, Optional[str]]:
    """
    校验分析配置是否包含必需的键
    
    Args:
        analysis_config: 分析配置字典
        required_keys: 必需的键列表
        
    Returns:
        tuple[bool, Optional[str]]: (是否有效, 错误消息)
        
    示例：
        >>> valid, error = validate_analysis_config(
        ...     {"analysis_type": "ac"},
        ...     ["analysis_type", "start_freq", "stop_freq"]
        ... )
        >>> if not valid:
        ...     print(error)
        "缺少必需的配置项: start_freq, stop_freq"
    """
    if analysis_config is None:
        if required_keys:
            return False, f"缺少必需的配置项: {', '.join(required_keys)}"
        return True, None
    
    missing_keys = [key for key in required_keys if key not in analysis_config]
    
    if missing_keys:
        return False, f"缺少必需的配置项: {', '.join(missing_keys)}"
    
    return True, None


def get_analysis_type(analysis_config: Optional[Dict[str, Any]]) -> str:
    """
    从配置中提取分析类型
    
    Args:
        analysis_config: 分析配置字典
        
    Returns:
        str: 分析类型（默认为 "ac"）
        
    示例:
        >>> get_analysis_type({"analysis_type": "dc"})
        "dc"
        >>> get_analysis_type({})
        "ac"
        >>> get_analysis_type(None)
        "ac"
    """
    if analysis_config is None:
        return "ac"
    
    return analysis_config.get("analysis_type", "ac")


# ============================================================
# 模块导出
# ============================================================

__all__ = [
    "SimulationExecutor",
    "validate_analysis_config",
    "get_analysis_type",
]
