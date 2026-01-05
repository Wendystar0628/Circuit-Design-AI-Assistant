# PythonExecutor - Python Script Simulation Executor
"""
Python 脚本仿真执行器

职责：
- 实现 SimulationExecutor 接口
- 在隔离子进程中执行用户自定义的 Python 仿真脚本
- 支持超时控制和错误处理
- 解析脚本输出为标准化仿真结果

执行模式说明：
- 使用 subprocess.run() 在独立子进程中执行脚本
- 子进程崩溃不影响主程序稳定性
- 通过 stdout 获取 JSON 格式的执行结果
- 通过 stderr 获取错误信息和调试日志

脚本约定：
- 脚本必须定义 run_simulation(config: dict) -> dict 入口函数
- 入口函数接收配置字典作为参数
- 返回字典需包含：
  - success: bool - 执行状态
  - data: dict - 仿真数据（frequency, time, signals）
  - metrics: dict - 性能指标（可选）
- 脚本通过 stdout 以 JSON 格式输出结果

安全声明：
- 本模块不提供完整的安全沙箱
- 不限制模块导入、文件系统访问、网络访问
- 用户应仅执行可信的脚本
- UI 层需明确提示用户相关安全风险

使用示例：
    from domain.simulation.executor.python_executor import PythonExecutor
    
    executor = PythonExecutor()
    
    # 执行仿真脚本
    result = executor.execute(
        "custom_simulation.py",
        {
            "analysis_type": "custom",
            "param1": 100,
            "param2": "value"
        }
    )
    
    if result.success:
        print(f"仿真成功，耗时 {result.duration_seconds:.2f}s")
        # 获取输出信号
        output = result.get_signal("output")
"""

import json
import logging
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

import numpy as np

from domain.simulation.executor.simulation_executor import SimulationExecutor
from domain.simulation.models.simulation_result import (
    SimulationData,
    SimulationResult,
    create_error_result,
    create_success_result,
)
from domain.simulation.models.simulation_error import (
    SimulationError,
    SimulationErrorType,
    ErrorSeverity,
    create_syntax_error,
    create_timeout_error,
)


# ============================================================
# 常量定义
# ============================================================

# 支持的文件扩展名
SUPPORTED_EXTENSIONS = [".py"]

# 支持的分析类型（Python 脚本可以实现任意分析类型）
SUPPORTED_ANALYSES = ["custom", "ac", "dc", "tran", "noise", "op", "monte_carlo", "parameter_sweep"]

# 默认超时时间（秒）
DEFAULT_TIMEOUT = 600

# 脚本入口函数名称
ENTRY_FUNCTION_NAME = "run_simulation"


# ============================================================
# PythonExecutor - Python 脚本仿真执行器
# ============================================================

class PythonExecutor(SimulationExecutor):
    """
    Python 脚本仿真执行器
    
    在独立子进程中执行用户自定义的 Python 仿真脚本。
    支持超时控制、错误处理和标准化结果输出。
    
    特性：
    - 进程隔离：脚本在独立子进程中执行，崩溃不影响主程序
    - 超时控制：支持设置执行时限，超时自动终止
    - 标准化结果：返回统一的 SimulationResult 数据结构
    - 错误处理：捕获并解析脚本错误，提供恢复建议
    
    安全限制：
    - 仅提供基础进程隔离，不实现完整沙箱
    - 不限制模块导入、文件访问、网络访问
    - 用户应仅执行可信脚本
    """
    
    def __init__(self, timeout: int = DEFAULT_TIMEOUT):
        """
        初始化 Python 执行器
        
        Args:
            timeout: 执行超时时间（秒），默认 600 秒
        """
        self._logger = logging.getLogger(__name__)
        self._timeout = timeout
        self._logger.debug(f"PythonExecutor 初始化完成，超时时间: {timeout}s")
    
    # ============================================================
    # SimulationExecutor 接口实现
    # ============================================================
    
    def get_name(self) -> str:
        """返回执行器名称"""
        return "python"
    
    def get_supported_extensions(self) -> List[str]:
        """返回支持的文件扩展名列表"""
        return SUPPORTED_EXTENSIONS.copy()
    
    def get_available_analyses(self) -> List[str]:
        """返回支持的分析类型列表"""
        return SUPPORTED_ANALYSES.copy()
    
    def execute(
        self,
        file_path: str,
        analysis_config: Optional[Dict[str, Any]] = None
    ) -> SimulationResult:
        """
        执行仿真并返回标准化结果
        
        Args:
            file_path: Python 脚本文件路径
            analysis_config: 仿真配置字典
                - analysis_type: 分析类型（默认 "custom"）
                - timeout: 超时时间（秒，可选）
                - 其他参数由脚本自定义
        
        Returns:
            SimulationResult: 标准化的仿真结果对象
        """
        start_time = time.time()
        analysis_type = self._get_analysis_type(analysis_config)
        
        # 1. 校验文件
        valid, error_msg = self.validate_file(file_path)
        if not valid:
            return create_error_result(
                executor=self.get_name(),
                file_path=file_path,
                analysis_type=analysis_type,
                error=SimulationError(
                    code="E009",
                    type=SimulationErrorType.FILE_ACCESS,
                    severity=ErrorSeverity.HIGH,
                    message=error_msg or "文件校验失败",
                    file_path=file_path,
                ),
                duration_seconds=time.time() - start_time,
            )
        
        # 2. 校验脚本格式（检查是否定义了入口函数）
        valid, error_msg = self._validate_script_format(file_path)
        if not valid:
            return create_error_result(
                executor=self.get_name(),
                file_path=file_path,
                analysis_type=analysis_type,
                error=create_syntax_error(
                    message=error_msg or "脚本格式错误",
                    file_path=file_path,
                    recovery_suggestion=f"请确保脚本定义了 {ENTRY_FUNCTION_NAME}(config: dict) -> dict 入口函数",
                ),
                duration_seconds=time.time() - start_time,
            )
        
        # 3. 执行脚本
        try:
            result = self._run_in_subprocess(file_path, analysis_config or {})
            result.duration_seconds = time.time() - start_time
            return result
            
        except subprocess.TimeoutExpired:
            # 超时错误
            return create_error_result(
                executor=self.get_name(),
                file_path=file_path,
                analysis_type=analysis_type,
                error=create_timeout_error(
                    message=f"脚本执行超时（{self._timeout}秒）",
                    file_path=file_path,
                ),
                duration_seconds=time.time() - start_time,
            )
            
        except Exception as e:
            # 其他异常
            self._logger.exception(f"脚本执行异常: {e}")
            return create_error_result(
                executor=self.get_name(),
                file_path=file_path,
                analysis_type=analysis_type,
                error=self._parse_exception(e, file_path),
                duration_seconds=time.time() - start_time,
            )
    
    # ============================================================
    # 公开辅助方法
    # ============================================================
    
    def set_timeout(self, timeout: int) -> None:
        """
        设置执行超时时间
        
        Args:
            timeout: 超时时间（秒）
        """
        self._timeout = timeout
        self._logger.debug(f"超时时间已更新: {timeout}s")
    
    def get_timeout(self) -> int:
        """
        获取当前超时时间
        
        Returns:
            int: 超时时间（秒）
        """
        return self._timeout
    
    # ============================================================
    # 内部方法
    # ============================================================
    
    def _get_analysis_type(self, analysis_config: Optional[Dict[str, Any]]) -> str:
        """从配置中提取分析类型"""
        if analysis_config is None:
            return "custom"
        return analysis_config.get("analysis_type", "custom")
    
    def _validate_script_format(self, file_path: str) -> tuple[bool, Optional[str]]:
        """
        校验脚本格式（检查是否定义了入口函数）
        
        Args:
            file_path: 脚本文件路径
            
        Returns:
            tuple[bool, Optional[str]]: (是否有效, 错误消息)
        """
        try:
            # 读取脚本内容
            script_content = Path(file_path).read_text(encoding='utf-8')
            
            # 检查是否定义了入口函数
            # 简单的字符串匹配，不进行完整的 AST 解析
            if f"def {ENTRY_FUNCTION_NAME}" not in script_content:
                return False, f"脚本未定义 {ENTRY_FUNCTION_NAME}(config: dict) -> dict 入口函数"
            
            return True, None
            
        except Exception as e:
            return False, f"读取脚本文件失败: {e}"
    
    def _run_in_subprocess(
        self,
        file_path: str,
        config: Dict[str, Any]
    ) -> SimulationResult:
        """
        在子进程中执行脚本
        
        Args:
            file_path: 脚本文件路径
            config: 配置字典
            
        Returns:
            SimulationResult: 仿真结果
            
        Raises:
            subprocess.TimeoutExpired: 执行超时
            Exception: 其他执行错误
        """
        analysis_type = config.get("analysis_type", "custom")
        
        # 获取超时时间（优先使用配置中的值）
        timeout = config.get("timeout", self._timeout)
        
        # 构建执行命令
        # 使用 -c 参数执行内联代码，避免创建临时文件
        script_path = Path(file_path).resolve()
        
        # 构建 Python 代码：导入脚本模块并调用入口函数
        python_code = f"""
import sys
import json
from pathlib import Path

# 添加脚本所在目录到 sys.path
script_dir = Path(r'{script_path.parent}').resolve()
if str(script_dir) not in sys.path:
    sys.path.insert(0, str(script_dir))

# 导入脚本模块
script_name = '{script_path.stem}'
try:
    module = __import__(script_name)
except ImportError as e:
    print(json.dumps({{"success": False, "error": f"导入脚本失败: {{e}}"}}))
    sys.exit(1)

# 检查入口函数是否存在
if not hasattr(module, '{ENTRY_FUNCTION_NAME}'):
    print(json.dumps({{"success": False, "error": "脚本未定义 {ENTRY_FUNCTION_NAME} 函数"}}))
    sys.exit(1)

# 调用入口函数
config = {json.dumps(config)}
try:
    result = module.{ENTRY_FUNCTION_NAME}(config)
    # 输出结果（JSON 格式）
    print(json.dumps(result, default=str))
except Exception as e:
    print(json.dumps({{"success": False, "error": f"执行失败: {{e}}"}}))
    sys.exit(1)
"""
        
        # 执行子进程
        try:
            process = subprocess.run(
                [sys.executable, "-c", python_code],
                capture_output=True,
                text=True,
                timeout=timeout,
                cwd=script_path.parent,  # 设置工作目录为脚本所在目录
            )
            
            # 解析输出
            return self._parse_output(
                stdout=process.stdout,
                stderr=process.stderr,
                returncode=process.returncode,
                file_path=file_path,
                analysis_type=analysis_type,
            )
            
        except subprocess.TimeoutExpired as e:
            # 超时异常，向上传播
            self._logger.warning(f"脚本执行超时: {file_path}, 超时时间: {timeout}s")
            raise
    
    def _parse_output(
        self,
        stdout: str,
        stderr: str,
        returncode: int,
        file_path: str,
        analysis_type: str
    ) -> SimulationResult:
        """
        解析脚本输出为标准化仿真结果
        
        Args:
            stdout: 标准输出
            stderr: 标准错误输出
            returncode: 返回码
            file_path: 脚本文件路径
            analysis_type: 分析类型
            
        Returns:
            SimulationResult: 仿真结果
        """
        # 记录 stderr（用于调试）
        if stderr:
            self._logger.debug(f"脚本 stderr 输出:\n{stderr}")
        
        # 检查返回码
        if returncode != 0:
            error_msg = stderr or "脚本执行失败"
            return create_error_result(
                executor=self.get_name(),
                file_path=file_path,
                analysis_type=analysis_type,
                error=SimulationError(
                    code="E011",
                    type=SimulationErrorType.SCRIPT_ERROR,
                    severity=ErrorSeverity.HIGH,
                    message=f"脚本执行失败（返回码 {returncode}）: {error_msg}",
                    file_path=file_path,
                    recovery_suggestion="请检查脚本逻辑和错误输出",
                ),
                raw_output=stdout,
            )
        
        # 解析 JSON 输出
        try:
            # 提取最后一个有效的 JSON 对象
            # 脚本可能在 stdout 中输出调试信息，我们只关心最后的 JSON 结果
            json_lines = [line.strip() for line in stdout.strip().split('\n') if line.strip()]
            
            if not json_lines:
                return create_error_result(
                    executor=self.get_name(),
                    file_path=file_path,
                    analysis_type=analysis_type,
                    error=SimulationError(
                        code="E012",
                        type=SimulationErrorType.OUTPUT_PARSE_ERROR,
                        severity=ErrorSeverity.HIGH,
                        message="脚本未输出任何结果",
                        file_path=file_path,
                        recovery_suggestion="请确保脚本通过 print(json.dumps(result)) 输出结果",
                    ),
                    raw_output=stdout,
                )
            
            # 尝试解析最后一行为 JSON
            result_dict = json.loads(json_lines[-1])
            
            # 校验结果格式
            if not isinstance(result_dict, dict):
                return create_error_result(
                    executor=self.get_name(),
                    file_path=file_path,
                    analysis_type=analysis_type,
                    error=SimulationError(
                        code="E012",
                        type=SimulationErrorType.OUTPUT_PARSE_ERROR,
                        severity=ErrorSeverity.HIGH,
                        message="脚本输出格式错误：结果必须是字典",
                        file_path=file_path,
                        recovery_suggestion="请确保 run_simulation 函数返回字典",
                    ),
                    raw_output=stdout,
                )
            
            # 检查 success 字段
            if "success" not in result_dict:
                return create_error_result(
                    executor=self.get_name(),
                    file_path=file_path,
                    analysis_type=analysis_type,
                    error=SimulationError(
                        code="E012",
                        type=SimulationErrorType.OUTPUT_PARSE_ERROR,
                        severity=ErrorSeverity.HIGH,
                        message="脚本输出缺少 'success' 字段",
                        file_path=file_path,
                        recovery_suggestion="请确保返回字典包含 'success' 布尔字段",
                    ),
                    raw_output=stdout,
                )
            
            # 根据 success 字段判断结果
            if not result_dict["success"]:
                # 脚本执行失败
                error_msg = result_dict.get("error", "脚本执行失败（未提供错误信息）")
                return create_error_result(
                    executor=self.get_name(),
                    file_path=file_path,
                    analysis_type=analysis_type,
                    error=SimulationError(
                        code="E011",
                        type=SimulationErrorType.SCRIPT_ERROR,
                        severity=ErrorSeverity.HIGH,
                        message=error_msg,
                        file_path=file_path,
                        recovery_suggestion="请检查脚本逻辑和输入参数",
                    ),
                    raw_output=stdout,
                )
            
            # 脚本执行成功，提取数据
            sim_data = self._extract_simulation_data(result_dict)
            metrics = result_dict.get("metrics")
            
            return create_success_result(
                executor=self.get_name(),
                file_path=file_path,
                analysis_type=analysis_type,
                data=sim_data,
                metrics=metrics,
                raw_output=stdout,
            )
            
        except json.JSONDecodeError as e:
            # JSON 解析失败
            return create_error_result(
                executor=self.get_name(),
                file_path=file_path,
                analysis_type=analysis_type,
                error=SimulationError(
                    code="E012",
                    type=SimulationErrorType.OUTPUT_PARSE_ERROR,
                    severity=ErrorSeverity.HIGH,
                    message=f"JSON 解析失败: {e}",
                    file_path=file_path,
                    recovery_suggestion="请确保脚本输出有效的 JSON 格式",
                ),
                raw_output=stdout,
            )
        
        except Exception as e:
            # 其他解析错误
            self._logger.exception(f"解析脚本输出时出错: {e}")
            return create_error_result(
                executor=self.get_name(),
                file_path=file_path,
                analysis_type=analysis_type,
                error=SimulationError(
                    code="E012",
                    type=SimulationErrorType.OUTPUT_PARSE_ERROR,
                    severity=ErrorSeverity.HIGH,
                    message=f"解析输出失败: {e}",
                    file_path=file_path,
                ),
                raw_output=stdout,
            )
    
    def _extract_simulation_data(self, result_dict: Dict[str, Any]) -> SimulationData:
        """
        从脚本输出字典中提取仿真数据
        
        Args:
            result_dict: 脚本返回的字典
            
        Returns:
            SimulationData: 标准化的仿真数据
        """
        data_dict = result_dict.get("data", {})
        
        # 提取频率数据
        frequency = None
        if "frequency" in data_dict and data_dict["frequency"] is not None:
            frequency = np.array(data_dict["frequency"])
        
        # 提取时间数据
        time_data = None
        if "time" in data_dict and data_dict["time"] is not None:
            time_data = np.array(data_dict["time"])
        
        # 提取信号数据
        signals = {}
        if "signals" in data_dict and isinstance(data_dict["signals"], dict):
            for name, signal_data in data_dict["signals"].items():
                if signal_data is not None:
                    signals[name] = np.array(signal_data)
        
        return SimulationData(
            frequency=frequency,
            time=time_data,
            signals=signals,
        )
    
    def _parse_exception(
        self,
        exception: Exception,
        file_path: str
    ) -> SimulationError:
        """
        解析异常并转换为 SimulationError
        
        Args:
            exception: 捕获的异常
            file_path: 脚本文件路径
            
        Returns:
            SimulationError: 结构化的错误信息
        """
        error_msg = str(exception)
        error_lower = error_msg.lower()
        
        # 根据错误消息判断错误类型
        if "timeout" in error_lower:
            return create_timeout_error(
                message=error_msg,
                file_path=file_path,
            )
        
        if "syntax" in error_lower or "parse" in error_lower:
            return create_syntax_error(
                message=error_msg,
                file_path=file_path,
                recovery_suggestion="请检查脚本语法是否正确",
            )
        
        if "import" in error_lower or "module" in error_lower:
            return SimulationError(
                code="E013",
                type=SimulationErrorType.DEPENDENCY_MISSING,
                severity=ErrorSeverity.HIGH,
                message=error_msg,
                file_path=file_path,
                recovery_suggestion="请检查脚本依赖的模块是否已安装",
            )
        
        # 默认错误类型
        return SimulationError(
            code="E011",
            type=SimulationErrorType.SCRIPT_ERROR,
            severity=ErrorSeverity.HIGH,
            message=error_msg,
            file_path=file_path,
            recovery_suggestion="请检查脚本逻辑和错误输出",
        )


# ============================================================
# 模块导出
# ============================================================

__all__ = [
    "PythonExecutor",
    "SUPPORTED_EXTENSIONS",
    "SUPPORTED_ANALYSES",
    "ENTRY_FUNCTION_NAME",
]
