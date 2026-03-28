# test_waveform_math_service.py - Tests for WaveformMathService
"""
波形数学运算服务测试

测试内容：
- 基本算术运算（加、减、乘、除）
- 数学函数（abs, sqrt, log, sin, cos 等）
- 微分和积分运算
- dB 转换和相位计算
- 表达式验证
- 错误处理
"""

import pytest
import numpy as np
from datetime import datetime

from domain.simulation.data.waveform_math_service import (
    WaveformMathService,
    MathResult,
    MathErrorCode,
    PresetOperation,
    PRESET_OPERATIONS,
    waveform_math_service,
)
from domain.simulation.models.simulation_result import (
    SimulationResult,
    SimulationData,
)


# ============================================================
# 测试夹具
# ============================================================

@pytest.fixture
def math_service():
    """创建数学运算服务实例"""
    return WaveformMathService()


@pytest.fixture
def sample_simulation_result():
    """创建示例仿真结果"""
    # 创建时间轴
    time = np.linspace(0, 1e-3, 1000)  # 0 到 1ms，1000 个点
    
    # 创建信号数据
    v_in = np.sin(2 * np.pi * 1000 * time)  # 1kHz 正弦波
    v_out = 2 * np.sin(2 * np.pi * 1000 * time + np.pi/4)  # 放大 2 倍，相移 45 度
    i_r1 = v_in / 1000  # 假设 1kΩ 电阻
    
    data = SimulationData(
        time=time,
        signals={
            "V(in)": v_in,
            "V(out)": v_out,
            "I(R1)": i_r1,
        }
    )
    
    return SimulationResult(
        executor="spice",
        file_path="test.cir",
        analysis_type="tran",
        success=True,
        data=data,
        timestamp=datetime.now().isoformat(),
    )


@pytest.fixture
def ac_simulation_result():
    """创建 AC 分析仿真结果"""
    # 创建频率轴
    frequency = np.logspace(1, 6, 100)  # 10Hz 到 1MHz
    
    # 创建复数信号数据（模拟 AC 分析结果）
    # 简单的一阶低通滤波器响应
    fc = 10000  # 截止频率 10kHz
    h = 1 / (1 + 1j * frequency / fc)
    
    v_out = np.abs(h)
    phase = np.angle(h, deg=True)
    
    data = SimulationData(
        frequency=frequency,
        signals={
            "V(out)": v_out,
            "V(out)_phase": phase,
        }
    )
    
    return SimulationResult(
        executor="spice",
        file_path="test.cir",
        analysis_type="ac",
        success=True,
        data=data,
        timestamp=datetime.now().isoformat(),
    )


# ============================================================
# 基本功能测试
# ============================================================

class TestBasicOperations:
    """基本运算测试"""
    
    def test_signal_addition(self, math_service, sample_simulation_result):
        """测试信号相加"""
        result = math_service.evaluate(
            sample_simulation_result,
            "V(in) + V(out)"
        )
        
        assert result.success
        assert result.data is not None
        assert result.data.point_count == 1000
        
        # 验证计算结果
        expected = (
            sample_simulation_result.data.signals["V(in)"] +
            sample_simulation_result.data.signals["V(out)"]
        )
        np.testing.assert_array_almost_equal(result.data.y_data, expected)
    
    def test_signal_subtraction(self, math_service, sample_simulation_result):
        """测试信号相减"""
        result = math_service.evaluate(
            sample_simulation_result,
            "V(out) - V(in)"
        )
        
        assert result.success
        assert result.data is not None
        
        expected = (
            sample_simulation_result.data.signals["V(out)"] -
            sample_simulation_result.data.signals["V(in)"]
        )
        np.testing.assert_array_almost_equal(result.data.y_data, expected)
    
    def test_signal_multiplication(self, math_service, sample_simulation_result):
        """测试信号相乘"""
        result = math_service.evaluate(
            sample_simulation_result,
            "V(in) * V(out)"
        )
        
        assert result.success
        assert result.data is not None
        
        expected = (
            sample_simulation_result.data.signals["V(in)"] *
            sample_simulation_result.data.signals["V(out)"]
        )
        np.testing.assert_array_almost_equal(result.data.y_data, expected)
    
    def test_signal_division(self, math_service, sample_simulation_result):
        """测试信号相除"""
        result = math_service.evaluate(
            sample_simulation_result,
            "V(out) / V(in)"
        )
        
        assert result.success
        assert result.data is not None
        
        # 注意：除法可能产生 inf 或 nan（当 V(in) 为 0 时）
        expected = (
            sample_simulation_result.data.signals["V(out)"] /
            sample_simulation_result.data.signals["V(in)"]
        )
        np.testing.assert_array_almost_equal(
            result.data.y_data, expected, decimal=5
        )
    
    def test_scalar_multiplication(self, math_service, sample_simulation_result):
        """测试标量乘法"""
        result = math_service.evaluate(
            sample_simulation_result,
            "2 * V(in)"
        )
        
        assert result.success
        assert result.data is not None
        
        expected = 2 * sample_simulation_result.data.signals["V(in)"]
        np.testing.assert_array_almost_equal(result.data.y_data, expected)


class TestMathFunctions:
    """数学函数测试"""
    
    def test_abs_function(self, math_service, sample_simulation_result):
        """测试绝对值函数"""
        result = math_service.evaluate(
            sample_simulation_result,
            "abs(V(in))"
        )
        
        assert result.success
        assert result.data is not None
        
        expected = np.abs(sample_simulation_result.data.signals["V(in)"])
        np.testing.assert_array_almost_equal(result.data.y_data, expected)
    
    def test_sqrt_function(self, math_service, sample_simulation_result):
        """测试平方根函数"""
        result = math_service.evaluate(
            sample_simulation_result,
            "sqrt(abs(V(in)))"
        )
        
        assert result.success
        assert result.data is not None
        
        expected = np.sqrt(np.abs(sample_simulation_result.data.signals["V(in)"]))
        np.testing.assert_array_almost_equal(result.data.y_data, expected)
    
    def test_log10_function(self, math_service, sample_simulation_result):
        """测试 log10 函数"""
        result = math_service.evaluate(
            sample_simulation_result,
            "log10(abs(V(out)) + 0.001)"  # 加小值避免 log(0)
        )
        
        assert result.success
        assert result.data is not None
    
    def test_sin_cos_functions(self, math_service, sample_simulation_result):
        """测试三角函数"""
        result = math_service.evaluate(
            sample_simulation_result,
            "sin(V(in)) + cos(V(out))"
        )
        
        assert result.success
        assert result.data is not None


class TestSpecialOperations:
    """特殊运算测试"""
    
    def test_db_conversion(self, math_service, ac_simulation_result):
        """测试 dB 转换"""
        result = math_service.evaluate(
            ac_simulation_result,
            "db(V(out))"
        )
        
        assert result.success
        assert result.data is not None
        
        # dB = 20 * log10(|x|)
        expected = 20 * np.log10(
            np.abs(ac_simulation_result.data.signals["V(out)"])
        )
        np.testing.assert_array_almost_equal(
            result.data.y_data, expected, decimal=5
        )
    
    def test_derivative(self, math_service, sample_simulation_result):
        """测试微分运算"""
        result = math_service.evaluate(
            sample_simulation_result,
            "deriv(V(in))"
        )
        
        assert result.success
        assert result.data is not None
        assert result.data.point_count == 1000
        
        # 微分结果应该是余弦波（正弦波的导数）
        # 由于数值微分，精度有限，只检查形状
        assert np.max(np.abs(result.data.y_data)) > 0
    
    def test_integral(self, math_service, sample_simulation_result):
        """测试积分运算"""
        result = math_service.evaluate(
            sample_simulation_result,
            "integ(V(in))"
        )
        
        assert result.success
        assert result.data is not None
        assert result.data.point_count == 1000
        
        # 积分结果应该从 0 开始
        assert result.data.y_data[0] == 0


class TestExpressionValidation:
    """表达式验证测试"""
    
    def test_valid_expression(self, math_service, sample_simulation_result):
        """测试有效表达式"""
        valid, error = math_service.validate_expression(
            sample_simulation_result,
            "V(in) + V(out)"
        )
        
        assert valid
        assert error == ""
    
    def test_invalid_signal(self, math_service, sample_simulation_result):
        """测试无效信号"""
        valid, error = math_service.validate_expression(
            sample_simulation_result,
            "V(nonexistent)"
        )
        
        assert not valid
        assert "不存在" in error or "nonexistent" in error.lower()
    
    def test_empty_expression(self, math_service, sample_simulation_result):
        """测试空表达式"""
        valid, error = math_service.validate_expression(
            sample_simulation_result,
            ""
        )
        
        assert not valid
        assert "空" in error or "empty" in error.lower()
    
    def test_syntax_error(self, math_service, sample_simulation_result):
        """测试语法错误"""
        valid, error = math_service.validate_expression(
            sample_simulation_result,
            "V(in) +"  # 不完整的表达式
        )
        
        assert not valid


class TestErrorHandling:
    """错误处理测试"""
    
    def test_no_data(self, math_service):
        """测试无数据情况"""
        result = SimulationResult(
            executor="spice",
            file_path="test.cir",
            analysis_type="tran",
            success=False,
            data=None,
        )
        
        math_result = math_service.evaluate(result, "V(in)")
        
        assert not math_result.success
        assert math_result.error_code == MathErrorCode.NO_DATA
    
    def test_signal_not_found(self, math_service, sample_simulation_result):
        """测试信号不存在"""
        result = math_service.evaluate(
            sample_simulation_result,
            "V(nonexistent)"
        )
        
        assert not result.success
        assert result.error_code == MathErrorCode.INVALID_EXPRESSION


class TestPresetOperations:
    """预设运算测试"""
    
    def test_preset_list(self, math_service):
        """测试预设运算列表"""
        presets = math_service.get_preset_operations()
        
        assert len(presets) > 0
        assert all(isinstance(p, PresetOperation) for p in presets)
    
    def test_build_single_signal_expression(self, math_service):
        """测试构建单信号表达式"""
        preset = next(p for p in PRESET_OPERATIONS if p.name == "abs")
        
        expression = math_service.build_expression(preset, "V(in)")
        
        assert "V(in)" in expression
        assert "abs" in expression
    
    def test_build_two_signal_expression(self, math_service):
        """测试构建双信号表达式"""
        preset = next(p for p in PRESET_OPERATIONS if p.name == "add")
        
        expression = math_service.build_expression(preset, "V(in)", "V(out)")
        
        assert "V(in)" in expression
        assert "V(out)" in expression
        assert "+" in expression


class TestAvailableSignals:
    """可用信号测试"""
    
    def test_get_available_signals(self, math_service, sample_simulation_result):
        """测试获取可用信号列表"""
        signals = math_service.get_available_signals(sample_simulation_result)
        
        assert "V(in)" in signals
        assert "V(out)" in signals
        assert "I(R1)" in signals
    
    def test_empty_signals_on_failure(self, math_service):
        """测试失败结果返回空信号列表"""
        result = SimulationResult(
            executor="spice",
            file_path="test.cir",
            analysis_type="tran",
            success=False,
            data=None,
        )
        
        signals = math_service.get_available_signals(result)
        
        assert signals == []


class TestModuleSingleton:
    """模块单例测试"""
    
    def test_singleton_exists(self):
        """测试单例存在"""
        assert waveform_math_service is not None
        assert isinstance(waveform_math_service, WaveformMathService)


# ============================================================
# 集成测试
# ============================================================

class TestIntegration:
    """集成测试"""
    
    def test_complex_expression(self, math_service, sample_simulation_result):
        """测试复杂表达式"""
        result = math_service.evaluate(
            sample_simulation_result,
            "abs(V(out) - V(in)) * 2 + 1"
        )
        
        assert result.success
        assert result.data is not None
    
    def test_gain_calculation(self, math_service, ac_simulation_result):
        """测试增益计算"""
        # 添加 V(in) 信号用于增益计算
        ac_simulation_result.data.signals["V(in)"] = np.ones(100)
        
        result = math_service.evaluate(
            ac_simulation_result,
            "db(V(out)/V(in))"
        )
        
        assert result.success
        assert result.data is not None
    
    def test_result_name(self, math_service, sample_simulation_result):
        """测试结果名称"""
        result = math_service.evaluate(
            sample_simulation_result,
            "V(in) + V(out)",
            result_name="Sum Signal"
        )
        
        assert result.success
        assert result.data.signal_name == "Sum Signal"
