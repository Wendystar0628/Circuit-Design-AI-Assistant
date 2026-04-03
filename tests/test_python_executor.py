# test_python_executor.py - Python Executor Tests
"""
Python 执行器测试

测试内容：
- 基本执行流程
- 超时控制
- 错误处理
- JSON 输出解析
- 脚本格式校验
"""

import json
import sys
import time
from pathlib import Path
from typing import Dict, Any

import numpy as np
import pytest

from domain.simulation.executor.python_executor import (
    PythonExecutor,
    ENTRY_FUNCTION_NAME,
)
from domain.simulation.models.simulation_error import SimulationErrorType


# ============================================================
# 测试夹具
# ============================================================

@pytest.fixture
def executor():
    """创建 Python 执行器实例"""
    return PythonExecutor(timeout=10)


@pytest.fixture
def temp_script_dir(tmp_path):
    """创建临时脚本目录"""
    script_dir = tmp_path / "scripts"
    script_dir.mkdir()
    return script_dir


def create_test_script(script_dir: Path, script_name: str, script_content: str) -> str:
    """
    创建测试脚本
    
    Args:
        script_dir: 脚本目录
        script_name: 脚本名称
        script_content: 脚本内容
        
    Returns:
        str: 脚本文件路径
    """
    script_path = script_dir / script_name
    script_path.write_text(script_content, encoding='utf-8')
    return str(script_path)


# ============================================================
# 基本功能测试
# ============================================================

def test_executor_name(executor):
    """测试执行器名称"""
    assert executor.get_name() == "python"


def test_supported_extensions(executor):
    """测试支持的文件扩展名"""
    extensions = executor.get_supported_extensions()
    assert ".py" in extensions


def test_available_analyses(executor):
    """测试支持的分析类型"""
    analyses = executor.get_available_analyses()
    assert "custom" in analyses
    assert "ac" in analyses
    assert "monte_carlo" in analyses


def test_can_handle_python_file(executor):
    """测试能否处理 Python 文件"""
    assert executor.can_handle("test.py")
    assert not executor.can_handle("test.cir")
    assert not executor.can_handle("test.txt")


# ============================================================
# 脚本执行测试
# ============================================================

def test_execute_simple_script(executor, temp_script_dir):
    """测试执行简单脚本"""
    # 创建简单的测试脚本
    script_content = f"""
import json

def {ENTRY_FUNCTION_NAME}(config):
    return {{
        "success": True,
        "data": {{
            "frequency": [1e3, 1e4, 1e5],
            "signals": {{
                "output": [0.1, 1.0, 10.0]
            }}
        }},
        "measurements": [
            {{"name": "gain", "value": 20.0, "unit": "dB", "status": "OK"}}
        ]
    }}
"""
    
    script_path = create_test_script(temp_script_dir, "simple_test.py", script_content)
    
    # 执行脚本
    result = executor.execute(script_path, {"analysis_type": "custom"})
    
    # 验证结果
    assert result.success
    assert result.executor == "python"
    assert result.analysis_type == "custom"
    assert result.data is not None
    assert result.data.frequency is not None
    assert len(result.data.frequency) == 3
    assert "output" in result.data.signals
    assert result.measurements is not None
    assert result.get_metric("gain") == 20.0


def test_execute_with_config(executor, temp_script_dir):
    """测试执行带配置的脚本"""
    # 创建使用配置的脚本
    script_content = f"""
import json

def {ENTRY_FUNCTION_NAME}(config):
    # 从配置中读取参数
    param1 = config.get("param1", 0)
    param2 = config.get("param2", "")
    
    return {{
        "success": True,
        "data": {{
            "signals": {{
                "result": [param1 * 2]
            }}
        }},
        "measurements": [
            {{"name": "result_value", "value": float(param1 * 2), "status": "OK"}}
        ]
    }}
"""
    
    script_path = create_test_script(temp_script_dir, "config_test.py", script_content)
    
    # 执行脚本，传入配置
    config = {
        "analysis_type": "custom",
        "param1": 100,
        "param2": "test_value"
    }
    result = executor.execute(script_path, config)
    
    # 验证结果
    assert result.success
    assert result.data.signals["result"][0] == 200
    assert result.get_metric("result_value") == 200.0


def test_execute_script_with_time_data(executor, temp_script_dir):
    """测试执行返回时间数据的脚本"""
    script_content = f"""
import json
import numpy as np

def {ENTRY_FUNCTION_NAME}(config):
    # 生成时间序列数据
    time = np.linspace(0, 1, 100)
    signal = np.sin(2 * np.pi * np.array(time))
    
    return {{
        "success": True,
        "data": {{
            "time": time.tolist(),
            "signals": {{
                "sine_wave": signal.tolist()
            }}
        }}
    }}
"""
    
    script_path = create_test_script(temp_script_dir, "time_test.py", script_content)
    
    # 执行脚本
    result = executor.execute(script_path, {"analysis_type": "tran"})
    
    # 验证结果
    assert result.success
    assert result.data.time is not None
    assert len(result.data.time) == 100
    assert "sine_wave" in result.data.signals
    assert len(result.data.signals["sine_wave"]) == 100


# ============================================================
# 错误处理测试
# ============================================================

def test_execute_nonexistent_file(executor):
    """测试执行不存在的文件"""
    result = executor.execute("nonexistent.py", {})
    
    assert not result.success
    assert result.error is not None
    assert result.error.type == SimulationErrorType.FILE_ACCESS


def test_execute_script_without_entry_function(executor, temp_script_dir):
    """测试执行没有入口函数的脚本"""
    # 创建没有入口函数的脚本
    script_content = """
def some_other_function():
    pass
"""
    
    script_path = create_test_script(temp_script_dir, "no_entry.py", script_content)
    
    # 执行脚本
    result = executor.execute(script_path, {})
    
    # 验证结果
    assert not result.success
    assert result.error is not None
    assert result.error.type == SimulationErrorType.SYNTAX_ERROR


def test_execute_script_with_runtime_error(executor, temp_script_dir):
    """测试执行有运行时错误的脚本"""
    # 创建会抛出异常的脚本
    script_content = f"""
def {ENTRY_FUNCTION_NAME}(config):
    # 故意触发除零错误
    x = 1 / 0
    return {{"success": True}}
"""
    
    script_path = create_test_script(temp_script_dir, "error_test.py", script_content)
    
    # 执行脚本
    result = executor.execute(script_path, {})
    
    # 验证结果
    assert not result.success
    assert result.error is not None
    assert result.error.type == SimulationErrorType.SCRIPT_ERROR


def test_execute_script_returning_failure(executor, temp_script_dir):
    """测试执行返回失败的脚本"""
    # 创建返回失败的脚本
    script_content = f"""
def {ENTRY_FUNCTION_NAME}(config):
    return {{
        "success": False,
        "error": "自定义错误消息"
    }}
"""
    
    script_path = create_test_script(temp_script_dir, "failure_test.py", script_content)
    
    # 执行脚本
    result = executor.execute(script_path, {})
    
    # 验证结果
    assert not result.success
    assert result.error is not None
    assert "自定义错误消息" in result.error.message


def test_execute_script_with_invalid_json(executor, temp_script_dir):
    """测试执行返回无效 JSON 的脚本"""
    # 创建返回无效 JSON 的脚本（不输出任何 JSON）
    script_content = f"""
def {ENTRY_FUNCTION_NAME}(config):
    # 直接打印非 JSON 内容，不返回任何结果
    print("This is not JSON")
    print("Another line of text")
    # 不返回字典，导致错误
"""
    
    script_path = create_test_script(temp_script_dir, "invalid_json.py", script_content)
    
    # 执行脚本
    result = executor.execute(script_path, {})
    
    # 验证结果
    assert not result.success
    assert result.error is not None
    assert result.error.type == SimulationErrorType.OUTPUT_PARSE_ERROR


def test_execute_script_with_deprecated_metrics_payload(executor, temp_script_dir):
    """测试返回已废弃 metrics 字段的脚本会失败"""
    script_content = f"""
def {ENTRY_FUNCTION_NAME}(config):
    return {{
        "success": True,
        "data": {{"signals": {{"out": [1.0]}}}},
        "metrics": {{"gain": 20.0}}
    }}
"""

    script_path = create_test_script(temp_script_dir, "deprecated_metrics.py", script_content)
    result = executor.execute(script_path, {"analysis_type": "custom"})

    assert not result.success
    assert result.error is not None
    assert result.error.type == SimulationErrorType.OUTPUT_PARSE_ERROR
    assert "metrics" in result.error.message


def test_execute_script_without_success_field(executor, temp_script_dir):
    """测试执行返回缺少 success 字段的脚本"""
    # 创建返回缺少 success 字段的脚本
    script_content = f"""
import json

def {ENTRY_FUNCTION_NAME}(config):
    result = {{"data": {{"signals": {{}}}}}}
    print(json.dumps(result))
    return result
"""
    
    script_path = create_test_script(temp_script_dir, "no_success.py", script_content)
    
    # 执行脚本
    result = executor.execute(script_path, {})
    
    # 验证结果
    assert not result.success
    assert result.error is not None
    assert result.error.type == SimulationErrorType.OUTPUT_PARSE_ERROR


# ============================================================
# 超时控制测试
# ============================================================

def test_execute_timeout(executor, temp_script_dir):
    """测试执行超时控制"""
    # 创建会长时间运行的脚本
    script_content = f"""
import time

def {ENTRY_FUNCTION_NAME}(config):
    # 睡眠 20 秒（超过默认超时时间）
    time.sleep(20)
    return {{"success": True}}
"""
    
    script_path = create_test_script(temp_script_dir, "timeout_test.py", script_content)
    
    # 设置较短的超时时间
    executor.set_timeout(2)
    
    # 执行脚本
    start_time = time.time()
    result = executor.execute(script_path, {})
    duration = time.time() - start_time
    
    # 验证结果
    assert not result.success
    assert result.error is not None
    assert result.error.type == SimulationErrorType.TIMEOUT
    assert duration < 5  # 应该在超时后立即返回


def test_execute_with_custom_timeout(executor, temp_script_dir):
    """测试使用自定义超时时间"""
    # 创建会运行一段时间的脚本
    script_content = f"""
import time

def {ENTRY_FUNCTION_NAME}(config):
    time.sleep(1)
    return {{"success": True, "data": {{"signals": {{}}}}}}
"""
    
    script_path = create_test_script(temp_script_dir, "custom_timeout.py", script_content)
    
    # 使用配置中的超时时间
    config = {
        "analysis_type": "custom",
        "timeout": 5
    }
    result = executor.execute(script_path, config)
    
    # 验证结果（应该成功，因为超时时间足够）
    assert result.success


# ============================================================
# 数据提取测试
# ============================================================

def test_extract_complex_data(executor, temp_script_dir):
    """测试提取复杂数据结构"""
    script_content = f"""
import json

def {ENTRY_FUNCTION_NAME}(config):
    return {{
        "success": True,
        "data": {{
            "frequency": [1e3, 1e4, 1e5, 1e6],
            "time": [0, 0.001, 0.002, 0.003],
            "signals": {{
                "V(out)": [0.1, 1.0, 10.0, 100.0],
                "I(R1)": [0.01, 0.1, 1.0, 10.0],
                "phase": [-90, -45, 0, 45]
            }}
        }},
        "measurements": [
            {{"name": "gain_db", "value": 20.0, "unit": "dB", "status": "OK"}},
            {{"name": "bandwidth_hz", "value": 1e6, "unit": "Hz", "status": "OK"}},
            {{"name": "phase_margin_deg", "value": 60.0, "unit": "°", "status": "OK"}}
        ]
    }}
"""
    
    script_path = create_test_script(temp_script_dir, "complex_data.py", script_content)
    
    # 执行脚本
    result = executor.execute(script_path, {"analysis_type": "ac"})
    
    # 验证结果
    assert result.success
    assert result.data.frequency is not None
    assert result.data.time is not None
    assert len(result.data.signals) == 3
    assert "V(out)" in result.data.signals
    assert "I(R1)" in result.data.signals
    assert "phase" in result.data.signals
    assert result.get_metric("gain_db") == 20.0
    assert result.get_metric("bandwidth_hz") == 1e6


def test_extract_empty_data(executor, temp_script_dir):
    """测试提取空数据"""
    script_content = f"""
import json

def {ENTRY_FUNCTION_NAME}(config):
    return {{
        "success": True,
        "data": {{}}
    }}
"""
    
    script_path = create_test_script(temp_script_dir, "empty_data.py", script_content)
    
    # 执行脚本
    result = executor.execute(script_path, {})
    
    # 验证结果
    assert result.success
    assert result.data.frequency is None
    assert result.data.time is None
    assert len(result.data.signals) == 0


# ============================================================
# 集成测试
# ============================================================

def test_monte_carlo_simulation(executor, temp_script_dir):
    """测试蒙特卡洛仿真脚本"""
    script_content = f"""
import json
import numpy as np

def {ENTRY_FUNCTION_NAME}(config):
    # 模拟蒙特卡洛分析
    num_runs = config.get("num_runs", 100)
    
    # 生成随机结果
    np.random.seed(42)
    results = np.random.normal(1.0, 0.1, num_runs)
    
    return {{
        "success": True,
        "data": {{
            "signals": {{
                "gain_distribution": results.tolist()
            }}
        }},
        "measurements": [
            {{"name": "mean", "value": float(np.mean(results)), "status": "OK"}},
            {{"name": "std", "value": float(np.std(results)), "status": "OK"}},
            {{"name": "min", "value": float(np.min(results)), "status": "OK"}},
            {{"name": "max", "value": float(np.max(results)), "status": "OK"}}
        ]
    }}
"""
    
    script_path = create_test_script(temp_script_dir, "monte_carlo.py", script_content)
    
    # 执行脚本
    config = {
        "analysis_type": "monte_carlo",
        "num_runs": 100
    }
    result = executor.execute(script_path, config)
    
    # 验证结果
    assert result.success
    assert "gain_distribution" in result.data.signals
    assert len(result.data.signals["gain_distribution"]) == 100
    assert result.get_metric("mean") is not None
    assert result.get_metric("std") is not None


def test_parameter_sweep(executor, temp_script_dir):
    """测试参数扫描脚本"""
    script_content = f"""
import json
import numpy as np

def {ENTRY_FUNCTION_NAME}(config):
    # 模拟参数扫描
    start = config.get("start", 0)
    stop = config.get("stop", 10)
    steps = config.get("steps", 11)
    
    param_values = np.linspace(start, stop, steps)
    output_values = param_values ** 2  # 简单的二次关系
    
    return {{
        "success": True,
        "data": {{
            "signals": {{
                "parameter": param_values.tolist(),
                "output": output_values.tolist()
            }}
        }},
        "measurements": [
            {{"name": "num_points", "value": float(steps), "status": "OK"}}
        ]
    }}
"""
    
    script_path = create_test_script(temp_script_dir, "param_sweep.py", script_content)
    
    # 执行脚本
    config = {
        "analysis_type": "parameter_sweep",
        "start": 0,
        "stop": 10,
        "steps": 11
    }
    result = executor.execute(script_path, config)
    
    # 验证结果
    assert result.success
    assert "parameter" in result.data.signals
    assert "output" in result.data.signals
    assert len(result.data.signals["parameter"]) == 11
    assert result.get_metric("num_points") == 11.0


# ============================================================
# 运行测试
# ============================================================

if __name__ == "__main__":
    pytest.main([__file__, "-v"])
