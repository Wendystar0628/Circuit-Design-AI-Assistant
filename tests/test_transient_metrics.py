# test_transient_metrics.py - Tests for TransientMetrics
"""
瞬态指标提取模块测试

测试内容：
- 上升时间提取
- 下降时间提取
- 传播延迟提取
- 占空比提取
- 振荡频率提取
- 边界条件和错误处理
"""

import numpy as np
import pytest

from domain.simulation.metrics.transient_metrics import TransientMetrics, transient_metrics
from domain.simulation.metrics.metric_result import MetricCategory
from domain.simulation.models.simulation_result import SimulationData


class TestTransientMetrics:
    """瞬态指标提取器测试类"""
    
    @pytest.fixture
    def extractor(self):
        """创建提取器实例"""
        return TransientMetrics()
    
    @pytest.fixture
    def step_response_data(self):
        """创建阶跃响应测试数据"""
        # 模拟一个典型的阶跃响应（RC 充电曲线）
        time = np.linspace(0, 1e-6, 1000)  # 1μs
        tau = 100e-9  # 100ns 时间常数
        v_final = 3.3
        signal = v_final * (1 - np.exp(-time / tau))
        
        return SimulationData(
            time=time,
            signals={"V(out)": signal}
        )
    
    @pytest.fixture
    def square_wave_data(self):
        """创建方波测试数据"""
        # 1MHz 方波，50% 占空比
        freq = 1e6
        period = 1 / freq
        time = np.linspace(0, 5 * period, 5000)  # 5 个周期
        
        # 生成方波（带有限上升/下降时间）
        signal = np.zeros_like(time)
        rise_time = period * 0.05  # 5% 的周期作为上升时间
        
        for i, t in enumerate(time):
            t_in_period = t % period
            if t_in_period < period * 0.5:
                # 高电平阶段
                if t_in_period < rise_time:
                    signal[i] = 3.3 * (t_in_period / rise_time)
                else:
                    signal[i] = 3.3
            else:
                # 低电平阶段
                t_fall = t_in_period - period * 0.5
                if t_fall < rise_time:
                    signal[i] = 3.3 * (1 - t_fall / rise_time)
                else:
                    signal[i] = 0.0
        
        return SimulationData(
            time=time,
            signals={"V(out)": signal}
        )
    
    @pytest.fixture
    def inverter_data(self):
        """创建反相器传播延迟测试数据"""
        time = np.linspace(0, 100e-9, 1000)  # 100ns
        
        # 输入：在 20ns 处上升
        input_signal = np.where(time < 20e-9, 0.0, 3.3)
        
        # 输出：在 25ns 处下降（5ns 传播延迟）
        output_signal = np.where(time < 25e-9, 3.3, 0.0)
        
        return SimulationData(
            time=time,
            signals={
                "V(in)": input_signal,
                "V(out)": output_signal
            }
        )

    # ============================================================
    # 上升时间测试
    # ============================================================
    
    def test_extract_rise_time_success(self, extractor, step_response_data):
        """测试上升时间提取成功"""
        result = extractor.extract_rise_time(step_response_data, output_signal="V(out)")
        
        assert result.is_valid
        assert result.name == "rise_time"
        assert result.unit == "s"
        assert result.category == MetricCategory.TRANSIENT
        assert result.value > 0
        # RC 电路 10%-90% 上升时间约为 2.2τ
        expected_rise_time = 2.2 * 100e-9  # 约 220ns
        assert abs(result.value - expected_rise_time) < 50e-9  # 允许 50ns 误差
    
    def test_extract_rise_time_custom_thresholds(self, extractor, step_response_data):
        """测试自定义阈值的上升时间提取"""
        result = extractor.extract_rise_time(
            step_response_data,
            output_signal="V(out)",
            low_percent=20.0,
            high_percent=80.0
        )
        
        assert result.is_valid
        assert "20%-80%" in result.measurement_condition
    
    def test_extract_rise_time_no_signal(self, extractor):
        """测试信号不存在时的错误处理"""
        data = SimulationData(
            time=np.linspace(0, 1e-6, 100),
            signals={}
        )
        
        result = extractor.extract_rise_time(data, output_signal="V(out)")
        
        assert not result.is_valid
        assert "未找到输出信号" in result.error_message
    
    def test_extract_rise_time_no_time_data(self, extractor):
        """测试无时间数据时的错误处理"""
        data = SimulationData(
            time=None,
            signals={"V(out)": np.array([1, 2, 3])}
        )
        
        result = extractor.extract_rise_time(data, output_signal="V(out)")
        
        assert not result.is_valid
        assert "时间数据不足" in result.error_message
    
    def test_extract_rise_time_flat_signal(self, extractor):
        """测试平坦信号时的错误处理"""
        data = SimulationData(
            time=np.linspace(0, 1e-6, 100),
            signals={"V(out)": np.ones(100) * 1.5}
        )
        
        result = extractor.extract_rise_time(data, output_signal="V(out)")
        
        assert not result.is_valid
        assert "幅度过小" in result.error_message
    
    # ============================================================
    # 下降时间测试
    # ============================================================
    
    def test_extract_fall_time_success(self, extractor, square_wave_data):
        """测试下降时间提取成功"""
        result = extractor.extract_fall_time(square_wave_data, output_signal="V(out)")
        
        assert result.is_valid
        assert result.name == "fall_time"
        assert result.unit == "s"
        assert result.value > 0
    
    def test_extract_fall_time_no_falling_edge(self, extractor, step_response_data):
        """测试无下降沿时的错误处理"""
        result = extractor.extract_fall_time(step_response_data, output_signal="V(out)")
        
        assert not result.is_valid
        assert "未找到有效下降沿" in result.error_message
    
    # ============================================================
    # 传播延迟测试
    # ============================================================
    
    def test_extract_propagation_delay_success(self, extractor, inverter_data):
        """测试传播延迟提取成功"""
        tpLH, tpHL = extractor.extract_propagation_delay(
            inverter_data,
            input_signal="V(in)",
            output_signal="V(out)"
        )
        
        # 对于反相器，输入上升 -> 输出下降，所以 tpHL 应该有效
        assert tpHL.is_valid
        assert tpHL.name == "tpHL"
        assert tpHL.unit == "s"
        # 预期延迟约 5ns
        assert abs(tpHL.value - 5e-9) < 1e-9
    
    def test_extract_average_propagation_delay(self, extractor, inverter_data):
        """测试平均传播延迟提取"""
        result = extractor.extract_average_propagation_delay(
            inverter_data,
            input_signal="V(in)",
            output_signal="V(out)"
        )
        
        # 即使只有一个方向有效，也应该返回结果
        assert result.is_valid or "无法计算" in result.error_message
    
    def test_extract_propagation_delay_no_input(self, extractor):
        """测试无输入信号时的错误处理"""
        data = SimulationData(
            time=np.linspace(0, 1e-6, 100),
            signals={"V(out)": np.ones(100)}
        )
        
        tpLH, tpHL = extractor.extract_propagation_delay(
            data,
            input_signal="V(in)",
            output_signal="V(out)"
        )
        
        assert not tpLH.is_valid
        assert "未找到输入信号" in tpLH.error_message

    # ============================================================
    # 占空比测试
    # ============================================================
    
    def test_extract_duty_cycle_success(self, extractor, square_wave_data):
        """测试占空比提取成功"""
        result = extractor.extract_duty_cycle(square_wave_data, output_signal="V(out)")
        
        assert result.is_valid
        assert result.name == "duty_cycle"
        assert result.unit == "%"
        # 预期 50% 占空比
        assert abs(result.value - 50.0) < 5.0  # 允许 5% 误差
    
    def test_extract_duty_cycle_metadata(self, extractor, square_wave_data):
        """测试占空比元数据"""
        result = extractor.extract_duty_cycle(square_wave_data, output_signal="V(out)")
        
        assert result.is_valid
        assert "num_cycles" in result.metadata
        assert result.metadata["num_cycles"] >= 1
    
    def test_extract_duty_cycle_no_cycles(self, extractor, step_response_data):
        """测试无完整周期时的错误处理"""
        result = extractor.extract_duty_cycle(step_response_data, output_signal="V(out)")
        
        assert not result.is_valid
    
    # ============================================================
    # 振荡频率测试
    # ============================================================
    
    def test_extract_frequency_success(self, extractor, square_wave_data):
        """测试振荡频率提取成功"""
        result = extractor.extract_frequency(square_wave_data, output_signal="V(out)")
        
        assert result.is_valid
        assert result.name == "frequency"
        assert result.unit == "Hz"
        # 预期 1MHz
        assert abs(result.value - 1e6) < 1e5  # 允许 10% 误差
    
    def test_extract_frequency_metadata(self, extractor, square_wave_data):
        """测试振荡频率元数据"""
        result = extractor.extract_frequency(square_wave_data, output_signal="V(out)")
        
        assert result.is_valid
        assert "avg_period" in result.metadata
        assert "num_periods" in result.metadata
        assert result.metadata["num_periods"] >= 1
    
    def test_extract_period_success(self, extractor, square_wave_data):
        """测试振荡周期提取成功"""
        result = extractor.extract_period(square_wave_data, output_signal="V(out)")
        
        assert result.is_valid
        assert result.name == "period"
        assert result.unit == "s"
        # 预期 1μs 周期
        assert abs(result.value - 1e-6) < 1e-7
    
    def test_extract_frequency_no_oscillation(self, extractor, step_response_data):
        """测试无振荡时的错误处理"""
        result = extractor.extract_frequency(step_response_data, output_signal="V(out)")
        
        assert not result.is_valid
        assert "未找到足够的周期" in result.error_message
    
    # ============================================================
    # 模块级单例测试
    # ============================================================
    
    def test_module_singleton(self):
        """测试模块级单例"""
        assert transient_metrics is not None
        assert isinstance(transient_metrics, TransientMetrics)
    
    # ============================================================
    # 边界条件测试
    # ============================================================
    
    def test_minimum_data_points(self, extractor):
        """测试最小数据点数"""
        # 只有 2 个点，应该失败
        data = SimulationData(
            time=np.array([0, 1e-6]),
            signals={"V(out)": np.array([0, 3.3])}
        )
        
        result = extractor.extract_rise_time(data, output_signal="V(out)")
        assert not result.is_valid
    
    def test_complex_signal_handling(self, extractor):
        """测试复数信号处理（应取实部）"""
        time = np.linspace(0, 1e-6, 100)
        # 创建复数信号
        signal = (1 - np.exp(-time / 100e-9)) * 3.3 + 0j
        
        data = SimulationData(
            time=time,
            signals={"V(out)": signal}
        )
        
        result = extractor.extract_rise_time(data, output_signal="V(out)")
        # 应该能正常处理复数信号
        assert result.is_valid or "未找到" in result.error_message


class TestTransientMetricsIntegration:
    """瞬态指标提取器集成测试"""
    
    def test_full_analysis_workflow(self):
        """测试完整分析工作流"""
        extractor = TransientMetrics()
        
        # 创建一个完整的测试波形
        freq = 100e3  # 100kHz
        period = 1 / freq
        time = np.linspace(0, 10 * period, 10000)
        
        # 生成带有限边沿的方波
        signal = np.zeros_like(time)
        rise_time_target = period * 0.02  # 2% 的周期
        
        for i, t in enumerate(time):
            t_in_period = t % period
            duty = 0.6  # 60% 占空比
            
            if t_in_period < period * duty:
                if t_in_period < rise_time_target:
                    signal[i] = 5.0 * (t_in_period / rise_time_target)
                else:
                    signal[i] = 5.0
            else:
                t_fall = t_in_period - period * duty
                if t_fall < rise_time_target:
                    signal[i] = 5.0 * (1 - t_fall / rise_time_target)
                else:
                    signal[i] = 0.0
        
        data = SimulationData(time=time, signals={"V(out)": signal})
        
        # 提取所有指标
        rise_result = extractor.extract_rise_time(data)
        fall_result = extractor.extract_fall_time(data)
        duty_result = extractor.extract_duty_cycle(data)
        freq_result = extractor.extract_frequency(data)
        
        # 验证所有指标都成功提取
        assert rise_result.is_valid, f"Rise time failed: {rise_result.error_message}"
        assert fall_result.is_valid, f"Fall time failed: {fall_result.error_message}"
        assert duty_result.is_valid, f"Duty cycle failed: {duty_result.error_message}"
        assert freq_result.is_valid, f"Frequency failed: {freq_result.error_message}"
        
        # 验证值的合理性
        assert abs(duty_result.value - 60.0) < 5.0  # 60% ± 5%
        assert abs(freq_result.value - 100e3) < 10e3  # 100kHz ± 10kHz
