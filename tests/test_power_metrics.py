# test_power_metrics.py - Power Metrics Extraction Tests
"""
电源指标提取模块测试

测试覆盖：
- 静态电流提取
- 功耗计算
- 效率计算
- 负载调整率
- 线性调整率
- 压差提取
- 元件功耗分析
- 温升估算
"""

import numpy as np
import pytest

from domain.simulation.metrics.power_metrics import PowerMetrics, power_metrics
from domain.simulation.metrics.metric_result import MetricCategory
from domain.simulation.models.simulation_result import SimulationData


class TestPowerMetrics:
    """电源指标提取器测试"""
    
    @pytest.fixture
    def extractor(self):
        """创建提取器实例"""
        return PowerMetrics()
    
    @pytest.fixture
    def dc_data(self):
        """创建 DC 分析测试数据"""
        return SimulationData(
            frequency=None,
            time=None,
            signals={
                "I(Vdd)": np.array([0.001]),  # 1mA 静态电流
                "V(vdd)": np.array([3.3]),     # 3.3V 电源
                "V(out)": np.array([1.8]),     # 1.8V 输出
            }
        )
    
    @pytest.fixture
    def tran_data(self):
        """创建瞬态分析测试数据"""
        time = np.linspace(0, 1e-3, 1000)  # 1ms
        return SimulationData(
            frequency=None,
            time=time,
            signals={
                "I(Vdd)": np.ones(1000) * 0.001,  # 1mA 恒定电流
                "V(vdd)": np.ones(1000) * 3.3,
                "V(out)": np.ones(1000) * 1.8,
                "V(vin)": np.ones(1000) * 5.0,
                "I(Vin)": np.ones(1000) * 0.002,  # 2mA 输入电流
                "I(Rload)": np.ones(1000) * 0.01,  # 10mA 负载电流
            }
        )

    # ============================================================
    # 静态电流测试
    # ============================================================
    
    def test_extract_quiescent_current_dc(self, extractor, dc_data):
        """测试从 DC 数据提取静态电流"""
        result = extractor.extract_quiescent_current(dc_data, supply_current="I(Vdd)")
        
        assert result.is_valid
        assert result.name == "quiescent_current"
        assert result.category == MetricCategory.POWER
        assert result.unit == "A"
        assert result.value == pytest.approx(0.001, rel=1e-6)
    
    def test_extract_quiescent_current_tran(self, extractor, tran_data):
        """测试从瞬态数据提取静态电流（稳态平均）"""
        result = extractor.extract_quiescent_current(tran_data, supply_current="I(Vdd)")
        
        assert result.is_valid
        assert result.value == pytest.approx(0.001, rel=1e-6)
        assert "稳态平均" in result.measurement_condition
    
    def test_extract_quiescent_current_missing_signal(self, extractor):
        """测试缺少信号时返回错误"""
        data = SimulationData(signals={})
        result = extractor.extract_quiescent_current(data, supply_current="I(Vdd)")
        
        assert not result.is_valid
        assert result.error_message is not None
    
    # ============================================================
    # 功耗测试
    # ============================================================
    
    def test_extract_power_consumption_dc(self, extractor, dc_data):
        """测试从 DC 数据提取功耗"""
        result = extractor.extract_power_consumption(
            dc_data, 
            supply_voltage="V(vdd)", 
            supply_current="I(Vdd)"
        )
        
        assert result.is_valid
        assert result.name == "power_consumption"
        assert result.unit == "W"
        # 3.3V * 1mA = 3.3mW
        assert result.value == pytest.approx(0.0033, rel=1e-6)
    
    def test_extract_power_consumption_with_vdd_value(self, extractor, dc_data):
        """测试使用已知电源电压计算功耗"""
        result = extractor.extract_power_consumption(
            dc_data,
            supply_current="I(Vdd)",
            vdd_value=5.0
        )
        
        assert result.is_valid
        # 5.0V * 1mA = 5mW
        assert result.value == pytest.approx(0.005, rel=1e-6)
    
    # ============================================================
    # 效率测试
    # ============================================================
    
    def test_extract_efficiency(self, extractor, tran_data):
        """测试效率提取"""
        result = extractor.extract_efficiency(
            tran_data,
            output_voltage="V(out)",
            output_current="I(Rload)",
            input_voltage="V(vin)",
            input_current="I(Vin)"
        )
        
        assert result.is_valid
        assert result.name == "efficiency"
        assert result.unit == "%"
        # P_out = 1.8V * 10mA = 18mW
        # P_in = 5.0V * 2mA = 10mW
        # 效率 = 18/10 * 100 = 180% (测试数据不现实，但验证计算正确)
        expected_eff = (1.8 * 0.01) / (5.0 * 0.002) * 100.0
        assert result.value == pytest.approx(expected_eff, rel=1e-3)
    
    def test_extract_efficiency_missing_signals(self, extractor):
        """测试缺少信号时返回错误"""
        data = SimulationData(
            time=np.linspace(0, 1e-3, 100),
            signals={"V(out)": np.ones(100)}
        )
        result = extractor.extract_efficiency(data)
        
        assert not result.is_valid

    # ============================================================
    # 调整率测试
    # ============================================================
    
    def test_extract_load_regulation(self, extractor):
        """测试负载调整率提取"""
        # 创建负载扫描数据
        i_load = np.linspace(0, 0.1, 100)  # 0 到 100mA
        v_out = 3.3 - i_load * 0.1  # 负载调整率 0.1V/A，满载时 Vout = 3.29V
        
        data = SimulationData(
            signals={
                "V(out)": v_out,
                "I(Rload)": i_load
            }
        )
        
        result = extractor.extract_load_regulation(
            data,
            output_signal="V(out)",
            load_current_signal="I(Rload)",
            no_load_current=0.0,
            full_load_current=0.1
        )
        
        assert result.is_valid
        assert result.name == "load_regulation"
        assert result.unit == "%"
        # V_no_load = 3.3V, V_full_load = 3.3 - 0.1*0.1 = 3.29V
        # 负载调整率 = (3.3 - 3.29) / 3.3 * 100 ≈ 0.303%
        v_no_load = 3.3
        v_full_load = 3.3 - 0.1 * 0.1  # 3.29V
        expected = ((v_no_load - v_full_load) / v_no_load) * 100.0
        assert result.value == pytest.approx(expected, rel=1e-2)
    
    def test_extract_line_regulation(self, extractor):
        """测试线性调整率提取"""
        # 创建输入电压扫描数据
        v_in = np.linspace(4.0, 6.0, 100)  # 4V 到 6V
        v_out = 3.3 + (v_in - 5.0) * 0.01  # 10mV/V 线性调整率
        
        data = SimulationData(
            signals={
                "V(out)": v_out,
                "V(vin)": v_in
            }
        )
        
        result = extractor.extract_line_regulation(
            data,
            output_signal="V(out)",
            input_signal="V(vin)"
        )
        
        assert result.is_valid
        assert result.name == "line_regulation"
        assert result.unit == "mV/V"
        # ΔVout = 0.02V, ΔVin = 2V, 线性调整率 = 10mV/V
        assert result.value == pytest.approx(10.0, rel=1e-2)
    
    def test_extract_dropout_voltage(self, extractor):
        """测试压差提取"""
        # 创建 LDO 压差测试数据
        v_in = np.linspace(5.0, 2.0, 100)  # 从 5V 降到 2V
        # 输出在 Vin > 3.5V 时稳定在 3.3V，之后跟随 Vin
        v_out = np.where(v_in > 3.5, 3.3, v_in - 0.2)
        
        data = SimulationData(
            signals={
                "V(out)": v_out,
                "V(vin)": v_in
            }
        )
        
        result = extractor.extract_dropout_voltage(
            data,
            output_signal="V(out)",
            input_signal="V(vin)",
            target_vout=3.3,
            dropout_threshold=0.99
        )
        
        assert result.is_valid
        assert result.name == "dropout_voltage"
        assert result.unit == "V"
        # 压差应该在 0.2V 左右
        assert result.value > 0
    
    # ============================================================
    # 元件功耗测试
    # ============================================================
    
    def test_extract_component_power(self, extractor):
        """测试单个元件功耗提取"""
        data = SimulationData(
            time=np.linspace(0, 1e-3, 100),
            signals={
                "V(R1)": np.ones(100) * 1.0,  # 1V
                "I(R1)": np.ones(100) * 0.01,  # 10mA
            }
        )
        
        result = extractor.extract_component_power(data, "R1")
        
        assert result.is_valid
        assert result.name == "power_R1"
        assert result.unit == "W"
        # 1V * 10mA = 10mW
        assert result.value == pytest.approx(0.01, rel=1e-6)
    
    def test_extract_power_distribution(self, extractor):
        """测试功耗分布提取"""
        data = SimulationData(
            time=np.linspace(0, 1e-3, 100),
            signals={
                "V(R1)": np.ones(100) * 1.0,
                "I(R1)": np.ones(100) * 0.01,
                "V(R2)": np.ones(100) * 2.0,
                "I(R2)": np.ones(100) * 0.005,
            }
        )
        
        total_result, component_results = extractor.extract_power_distribution(
            data, 
            component_list=["R1", "R2"]
        )
        
        assert total_result.is_valid
        assert len(component_results) == 2
        # R1: 10mW, R2: 10mW, 总计 20mW
        assert total_result.value == pytest.approx(0.02, rel=1e-6)

    # ============================================================
    # 热分析测试
    # ============================================================
    
    def test_estimate_thermal_rise(self, extractor):
        """测试温升估算"""
        result = extractor.estimate_thermal_rise(
            power_dissipation=0.5,  # 500mW
            thermal_resistance=50.0,  # 50°C/W
            ambient_temperature=25.0
        )
        
        assert result.is_valid
        assert result.name == "thermal_rise"
        assert result.unit == "°C"
        # 温升 = 0.5W * 50°C/W = 25°C
        assert result.value == pytest.approx(25.0, rel=1e-6)
        # 结温 = 25 + 25 = 50°C
        assert result.metadata["junction_temperature_c"] == pytest.approx(50.0, rel=1e-6)
    
    def test_estimate_thermal_rise_negative_power(self, extractor):
        """测试负功耗时返回错误"""
        result = extractor.estimate_thermal_rise(
            power_dissipation=-0.1,
            thermal_resistance=50.0
        )
        
        assert not result.is_valid
        assert "负值" in result.error_message
    
    # ============================================================
    # 功耗损耗分解测试
    # ============================================================
    
    def test_extract_power_loss_breakdown(self, extractor):
        """测试功耗损耗分解"""
        data = SimulationData(signals={})
        
        result = extractor.extract_power_loss_breakdown(
            data,
            input_power=1.0,  # 1W 输入
            output_power=0.85  # 0.85W 输出，85% 效率
        )
        
        assert result.is_valid
        assert result.name == "power_loss_breakdown"
        assert result.unit == "W"
        # 总损耗 = 1.0 - 0.85 = 0.15W
        assert result.value == pytest.approx(0.15, rel=1e-6)
        assert result.metadata["efficiency_percent"] == pytest.approx(85.0, rel=1e-6)
    
    def test_extract_power_loss_breakdown_invalid(self, extractor):
        """测试输出大于输入时返回错误"""
        data = SimulationData(signals={})
        
        result = extractor.extract_power_loss_breakdown(
            data,
            input_power=0.5,
            output_power=1.0  # 输出大于输入
        )
        
        assert not result.is_valid
    
    # ============================================================
    # 模块级单例测试
    # ============================================================
    
    def test_module_singleton(self):
        """测试模块级单例"""
        assert power_metrics is not None
        assert isinstance(power_metrics, PowerMetrics)
    
    # ============================================================
    # 边界条件测试
    # ============================================================
    
    def test_empty_data(self, extractor):
        """测试空数据处理"""
        data = SimulationData(signals={})
        
        result = extractor.extract_quiescent_current(data)
        assert not result.is_valid
        
        result = extractor.extract_power_consumption(data)
        assert not result.is_valid
    
    def test_zero_values(self, extractor):
        """测试零值处理"""
        data = SimulationData(
            signals={
                "I(Vdd)": np.array([0.0]),
                "V(vdd)": np.array([0.0])
            }
        )
        
        result = extractor.extract_quiescent_current(data)
        assert result.is_valid
        assert result.value == 0.0
        
        result = extractor.extract_power_consumption(data, vdd_value=3.3)
        assert result.is_valid
        assert result.value == 0.0


class TestEfficiencyCurve:
    """效率曲线测试"""
    
    def test_extract_efficiency_curve(self):
        """测试效率曲线提取"""
        extractor = PowerMetrics()
        
        # 创建负载变化的瞬态数据
        time = np.linspace(0, 1e-3, 200)
        i_load = np.linspace(0.001, 0.1, 200)  # 1mA 到 100mA
        
        # 模拟效率随负载变化（轻载效率低，中等负载效率高）
        v_out = np.ones(200) * 3.3
        v_in = np.ones(200) * 5.0
        # 输入电流随负载增加
        i_in = 0.001 + i_load * 0.7  # 静态电流 + 负载相关电流
        
        data = SimulationData(
            time=time,
            signals={
                "V(out)": v_out,
                "I(Rload)": i_load,
                "V(vin)": v_in,
                "I(Vin)": i_in
            }
        )
        
        result = extractor.extract_efficiency_curve(
            data,
            output_voltage="V(out)",
            output_current="I(Rload)",
            input_voltage="V(vin)",
            input_current="I(Vin)"
        )
        
        assert result.is_valid
        assert result.name == "efficiency_curve"
        assert "load_current_a" in result.metadata
        assert "efficiency_percent" in result.metadata
        assert "peak_efficiency" in result.metadata
