# Test Simulation ViewModel
"""
SimulationViewModel 单元测试

测试内容：
- 状态管理
- 指标格式化
- 事件处理
- 数据导出
"""

import pytest
import numpy as np
from unittest.mock import Mock, patch, MagicMock

from presentation.panels.simulation.simulation_view_model import (
    SimulationViewModel,
    SimulationStatus,
    DisplayMetric,
    TuningParameter,
)
from domain.simulation.models.simulation_result import (
    SimulationResult,
    SimulationData,
)


class TestSimulationStatus:
    """测试 SimulationStatus 枚举"""
    
    def test_status_values(self):
        """测试状态枚举值"""
        assert SimulationStatus.IDLE.value == "idle"
        assert SimulationStatus.RUNNING.value == "running"
        assert SimulationStatus.COMPLETE.value == "complete"
        assert SimulationStatus.ERROR.value == "error"
        assert SimulationStatus.CANCELLED.value == "cancelled"


class TestDisplayMetric:
    """测试 DisplayMetric 数据类"""
    
    def test_create_display_metric(self):
        """测试创建 DisplayMetric"""
        metric = DisplayMetric(
            name="gain",
            display_name="增益",
            value="20.5 dB",
            unit="dB",
            target="≥ 20 dB",
            is_met=True,
            trend="up",
            category="amplifier",
            raw_value=20.5,
            confidence=1.0,
        )
        
        assert metric.name == "gain"
        assert metric.display_name == "增益"
        assert metric.value == "20.5 dB"
        assert metric.is_met is True
        assert metric.trend == "up"
        assert metric.raw_value == 20.5
    
    def test_display_metric_with_error(self):
        """测试带错误信息的 DisplayMetric"""
        metric = DisplayMetric(
            name="bandwidth",
            display_name="带宽",
            value="N/A",
            unit="Hz",
            target="",
            is_met=None,
            trend="unknown",
            category="amplifier",
            error_message="AC 分析数据不足",
        )
        
        assert metric.error_message == "AC 分析数据不足"
        assert metric.is_met is None


class TestTuningParameter:
    """测试 TuningParameter 数据类"""
    
    def test_create_tuning_parameter(self):
        """测试创建 TuningParameter"""
        param = TuningParameter(
            name="R1",
            current_value=10000.0,
            min_value=1000.0,
            max_value=100000.0,
            step=1000.0,
            unit="Ω",
            source_file="amplifier.cir",
            source_line=15,
        )
        
        assert param.name == "R1"
        assert param.current_value == 10000.0
        assert param.min_value == 1000.0
        assert param.max_value == 100000.0


class TestSimulationViewModel:
    """测试 SimulationViewModel"""
    
    @pytest.fixture
    def view_model(self):
        """创建 ViewModel 实例"""
        vm = SimulationViewModel()
        return vm
    
    @pytest.fixture
    def mock_simulation_result(self):
        """创建模拟仿真结果"""
        data = SimulationData(
            frequency=np.array([1e3, 1e4, 1e5, 1e6]),
            signals={
                "V(out)": np.array([0.1, 1.0, 10.0, 5.0]),
                "V(in)": np.array([0.01, 0.01, 0.01, 0.01]),
            }
        )
        return SimulationResult(
            executor="spice",
            file_path="test.cir",
            analysis_type="ac",
            success=True,
            data=data,
            measurements=[
                {"name": "gain", "value": 20.0, "unit": "dB", "status": "OK"}
            ],
            duration_seconds=1.5,
        )
    
    def test_initial_state(self, view_model):
        """测试初始状态"""
        assert view_model.simulation_status == SimulationStatus.IDLE
        assert view_model.progress == 0.0
        assert view_model.error_message == ""
        assert view_model.metrics_list == []
        assert view_model.overall_score == 0.0
    
    def test_load_result_from_measurements(self, view_model, mock_simulation_result):
        """测试从 measurements 加载显示指标"""
        view_model.load_result(mock_simulation_result)

        assert view_model.simulation_status == SimulationStatus.COMPLETE
        assert len(view_model.metrics_list) == 1
        assert view_model.metrics_list[0].name == "gain"
        assert view_model.metrics_list[0].category == "amplifier"
    
    def test_load_result_uses_measurement_metadata(self, view_model):
        """测试 measurements 元数据用于显示"""
        result = SimulationResult(
            executor="spice",
            file_path="measure_test.cir",
            analysis_type="tran",
            success=True,
            data=SimulationData(
                time=np.array([0.0, 1e-6]),
                signals={"V(out)": np.array([0.0, 1.0])},
            ),
            measurements=[
                {
                    "name": "bandwidth",
                    "value": 1e6,
                    "unit": "Hz",
                    "status": "OK",
                    "display_name": "Bandwidth",
                    "category": "amplifier",
                }
            ],
        )

        view_model.load_result(result)

        assert len(view_model.metrics_list) == 1
        assert view_model.metrics_list[0].name == "bandwidth"
        assert view_model.metrics_list[0].display_name == "Bandwidth"
        assert view_model.metrics_list[0].category == "amplifier"
    
    def test_calculate_trend_up(self, view_model):
        """测试上升趋势计算"""
        # 设置历史值
        view_model._previous_metrics["gain"] = 18.0
        
        trend = view_model._calculate_trend("gain", 20.0)
        
        assert trend == "up"
    
    def test_calculate_trend_down(self, view_model):
        """测试下降趋势计算"""
        view_model._previous_metrics["gain"] = 22.0
        
        trend = view_model._calculate_trend("gain", 20.0)
        
        assert trend == "down"
    
    def test_calculate_trend_stable(self, view_model):
        """测试稳定趋势计算"""
        view_model._previous_metrics["gain"] = 20.0
        
        trend = view_model._calculate_trend("gain", 20.1)
        
        assert trend == "stable"
    
    def test_calculate_trend_unknown(self, view_model):
        """测试未知趋势（无历史数据）"""
        trend = view_model._calculate_trend("gain", 20.0)
        
        assert trend == "unknown"
    
    def test_on_simulation_started(self, view_model):
        """测试仿真开始事件处理"""
        property_changes = []
        view_model.property_changed.connect(
            lambda name, value: property_changes.append((name, value))
        )
        
        view_model._on_simulation_started({
            "circuit_file": "test.cir",
            "simulation_type": "ac",
        })
        
        assert view_model.simulation_status == SimulationStatus.RUNNING
        assert view_model.progress == 0.0
        assert ("simulation_status", SimulationStatus.RUNNING) in property_changes
    
    def test_on_simulation_progress(self, view_model):
        """测试仿真进度事件处理"""
        view_model._on_simulation_progress({"progress": 0.5})
        
        assert view_model.progress == 50.0
    
    def test_on_simulation_complete(self, view_model):
        """测试仿真完成事件处理"""
        view_model._on_simulation_complete({})
        
        assert view_model.simulation_status == SimulationStatus.COMPLETE
        assert view_model.progress == 100.0
    
    def test_on_simulation_error(self, view_model):
        """测试仿真错误事件处理"""
        view_model._on_simulation_error({
            "error_message": "Convergence failed"
        })
        
        assert view_model.simulation_status == SimulationStatus.ERROR
        assert view_model.error_message == "Convergence failed"
    
    def test_on_simulation_cancelled(self, view_model):
        """测试仿真取消事件处理"""
        view_model._on_simulation_cancelled({})
        
        assert view_model.simulation_status == SimulationStatus.CANCELLED
    
    def test_calculate_overall_score_all_met(self, view_model):
        """测试综合评分计算（全部达标）"""
        view_model._metrics_list = [
            DisplayMetric(
                name="gain", display_name="增益", value="20 dB",
                unit="dB", target="≥ 20", is_met=True, trend="stable",
                category="amplifier"
            ),
            DisplayMetric(
                name="bandwidth", display_name="带宽", value="10 MHz",
                unit="Hz", target="≥ 1 MHz", is_met=True, trend="stable",
                category="amplifier"
            ),
        ]
        
        view_model._calculate_overall_score()
        
        assert view_model.overall_score == 100.0
    
    def test_calculate_overall_score_partial(self, view_model):
        """测试综合评分计算（部分达标）"""
        view_model._metrics_list = [
            DisplayMetric(
                name="gain", display_name="增益", value="20 dB",
                unit="dB", target="≥ 20", is_met=True, trend="stable",
                category="amplifier"
            ),
            DisplayMetric(
                name="bandwidth", display_name="带宽", value="500 kHz",
                unit="Hz", target="≥ 1 MHz", is_met=False, trend="stable",
                category="amplifier"
            ),
        ]
        
        view_model._calculate_overall_score()
        
        assert view_model.overall_score == 50.0
    
    def test_get_metrics_by_category(self, view_model):
        """测试按类别获取指标"""
        view_model._metrics_list = [
            DisplayMetric(
                name="gain", display_name="增益", value="20 dB",
                unit="dB", target="", is_met=None, trend="stable",
                category="amplifier"
            ),
            DisplayMetric(
                name="thd", display_name="THD", value="0.1%",
                unit="%", target="", is_met=None, trend="stable",
                category="distortion"
            ),
        ]
        
        amplifier_metrics = view_model.get_metrics_by_category("amplifier")
        
        assert len(amplifier_metrics) == 1
        assert amplifier_metrics[0].name == "gain"
    
    def test_get_metric_by_name(self, view_model):
        """测试按名称获取指标"""
        view_model._metrics_list = [
            DisplayMetric(
                name="gain", display_name="增益", value="20 dB",
                unit="dB", target="", is_met=None, trend="stable",
                category="amplifier"
            ),
        ]
        
        metric = view_model.get_metric_by_name("gain")
        
        assert metric is not None
        assert metric.name == "gain"
    
    def test_get_metric_by_name_not_found(self, view_model):
        """测试按名称获取不存在的指标"""
        metric = view_model.get_metric_by_name("nonexistent")
        
        assert metric is None
    
    def test_clear(self, view_model):
        """测试清空数据"""
        # 设置一些数据
        view_model._simulation_status = SimulationStatus.COMPLETE
        view_model._progress = 100.0
        view_model._overall_score = 80.0
        
        view_model.clear()
        
        assert view_model.simulation_status == SimulationStatus.IDLE
        assert view_model.progress == 0.0
        assert view_model.overall_score == 0.0
        assert view_model.metrics_list == []
    
    def test_update_tuning_parameter(self, view_model):
        """测试更新调参参数"""
        view_model._tuning_parameters = [
            TuningParameter(
                name="R1", current_value=10000.0,
                min_value=1000.0, max_value=100000.0,
                step=1000.0, unit="Ω",
                source_file="test.cir", source_line=10
            ),
        ]
        
        view_model.update_tuning_parameter("R1", 20000.0)
        
        assert view_model._tuning_parameters[0].current_value == 20000.0
    
    def test_format_value_with_unit_large(self, view_model):
        """测试大数值格式化"""
        result = view_model._format_value_with_unit(1e9, "Hz")
        assert "G" in result
        
        result = view_model._format_value_with_unit(1e6, "Hz")
        assert "M" in result
        
        result = view_model._format_value_with_unit(1e3, "Hz")
        assert "k" in result
    
    def test_format_value_with_unit_small(self, view_model):
        """测试小数值格式化"""
        result = view_model._format_value_with_unit(1e-3, "V")
        assert "m" in result
        
        result = view_model._format_value_with_unit(1e-6, "V")
        assert "μ" in result
        
        result = view_model._format_value_with_unit(1e-9, "V")
        assert "n" in result


class TestSimulationViewModelExport:
    """测试数据导出功能"""
    
    @pytest.fixture
    def view_model_with_result(self, tmp_path):
        """创建带仿真结果的 ViewModel"""
        vm = SimulationViewModel()
        
        data = SimulationData(
            time=np.array([0.0, 1e-6, 2e-6, 3e-6]),
            signals={
                "V(out)": np.array([0.0, 1.0, 2.0, 1.5]),
                "V(in)": np.array([0.0, 0.1, 0.2, 0.15]),
            }
        )
        
        vm._current_result = SimulationResult(
            executor="spice",
            file_path="test.cir",
            analysis_type="tran",
            success=True,
            data=data,
        )
        
        return vm, tmp_path
    
    def test_export_csv(self, view_model_with_result):
        """测试 CSV 导出"""
        vm, tmp_path = view_model_with_result
        export_path = tmp_path / "export.csv"
        
        result = vm.export_result("csv", str(export_path))
        
        assert result is True
        assert export_path.exists()
        
        content = export_path.read_text()
        assert "time" in content
        assert "V(out)" in content
    
    def test_export_json(self, view_model_with_result):
        """测试 JSON 导出"""
        import json
        
        vm, tmp_path = view_model_with_result
        export_path = tmp_path / "export.json"
        
        result = vm.export_result("json", str(export_path))
        
        assert result is True
        assert export_path.exists()
        
        data = json.loads(export_path.read_text())
        assert "time" in data
        assert "signals" in data
        assert "V(out)" in data["signals"]
    
    def test_export_no_result(self):
        """测试无结果时导出"""
        vm = SimulationViewModel()
        
        result = vm.export_result("csv", "test.csv")
        
        assert result is False
    
    def test_export_unsupported_format(self, view_model_with_result):
        """测试不支持的导出格式"""
        vm, tmp_path = view_model_with_result
        
        result = vm.export_result("xyz", str(tmp_path / "export.xyz"))
        
        assert result is False
