# Test SimulationResult Data Class
"""
测试仿真结果数据类

测试内容：
- SimulationData 的序列化和反序列化
- SimulationResult 的序列化和反序列化
- 辅助方法的正确性
- numpy 数组的正确处理
"""

import json
from datetime import datetime, timedelta

import numpy as np
import pytest

from circuit_design_ai.domain.simulation.models.simulation_result import (
    SimulationData,
    SimulationResult,
    create_error_result,
    create_success_result,
)


class TestSimulationData:
    """测试 SimulationData 数据类"""
    
    def test_create_empty(self):
        """测试创建空数据"""
        data = SimulationData()
        assert data.frequency is None
        assert data.time is None
        assert len(data.signals) == 0
    
    def test_create_with_data(self):
        """测试创建包含数据的对象"""
        freq = np.array([1e3, 1e4, 1e5])
        signals = {
            "V(out)": np.array([0.1, 1.0, 10.0]),
            "V(in)": np.array([1.0, 1.0, 1.0]),
        }
        
        data = SimulationData(frequency=freq, signals=signals)
        
        assert np.array_equal(data.frequency, freq)
        assert data.time is None
        assert len(data.signals) == 2
        assert np.array_equal(data.signals["V(out)"], signals["V(out)"])
    
    def test_serialization(self):
        """测试序列化"""
        freq = np.array([1e3, 1e4, 1e5])
        signals = {"V(out)": np.array([0.1, 1.0, 10.0])}
        
        data = SimulationData(frequency=freq, signals=signals)
        data_dict = data.to_dict()
        
        # 检查序列化结果
        assert isinstance(data_dict["frequency"], list)
        assert isinstance(data_dict["signals"]["V(out)"], list)
        assert data_dict["frequency"] == [1e3, 1e4, 1e5]
        assert data_dict["signals"]["V(out)"] == [0.1, 1.0, 10.0]
    
    def test_deserialization(self):
        """测试反序列化"""
        data_dict = {
            "frequency": [1e3, 1e4, 1e5],
            "time": None,
            "signals": {
                "V(out)": [0.1, 1.0, 10.0],
            },
        }
        
        data = SimulationData.from_dict(data_dict)
        
        # 检查反序列化结果
        assert isinstance(data.frequency, np.ndarray)
        assert isinstance(data.signals["V(out)"], np.ndarray)
        assert np.array_equal(data.frequency, np.array([1e3, 1e4, 1e5]))
        assert np.array_equal(data.signals["V(out)"], np.array([0.1, 1.0, 10.0]))
    
    def test_round_trip(self):
        """测试序列化-反序列化往返"""
        freq = np.array([1e3, 1e4, 1e5])
        time = np.array([0.0, 1e-6, 2e-6])
        signals = {
            "V(out)": np.array([0.1, 1.0, 10.0]),
            "I(R1)": np.array([1e-3, 1e-2, 1e-1]),
        }
        
        original = SimulationData(frequency=freq, time=time, signals=signals)
        data_dict = original.to_dict()
        restored = SimulationData.from_dict(data_dict)
        
        # 检查往返后数据一致
        assert np.array_equal(restored.frequency, original.frequency)
        assert np.array_equal(restored.time, original.time)
        assert len(restored.signals) == len(original.signals)
        for name in original.signals:
            assert np.array_equal(restored.signals[name], original.signals[name])
    
    def test_get_signal(self):
        """测试获取信号"""
        signals = {"V(out)": np.array([0.1, 1.0, 10.0])}
        data = SimulationData(signals=signals)
        
        # 存在的信号
        signal = data.get_signal("V(out)")
        assert signal is not None
        assert np.array_equal(signal, np.array([0.1, 1.0, 10.0]))
        
        # 不存在的信号
        signal = data.get_signal("V(in)")
        assert signal is None
    
    def test_has_signal(self):
        """测试检查信号是否存在"""
        signals = {"V(out)": np.array([0.1, 1.0, 10.0])}
        data = SimulationData(signals=signals)
        
        assert data.has_signal("V(out)") is True
        assert data.has_signal("V(in)") is False
    
    def test_get_signal_names(self):
        """测试获取信号名称列表"""
        signals = {
            "V(out)": np.array([0.1, 1.0, 10.0]),
            "V(in)": np.array([1.0, 1.0, 1.0]),
        }
        data = SimulationData(signals=signals)
        
        names = data.get_signal_names()
        assert len(names) == 2
        assert "V(out)" in names
        assert "V(in)" in names


class TestSimulationResult:
    """测试 SimulationResult 数据类"""
    
    def test_create_success_result(self):
        """测试创建成功结果"""
        data = SimulationData(
            frequency=np.array([1e3, 1e4, 1e5]),
            signals={"V(out)": np.array([0.1, 1.0, 10.0])},
        )
        
        result = create_success_result(
            executor="spice",
            file_path="amplifier.cir",
            analysis_type="ac",
            data=data,
            measurements=[{"name": "gain", "value": 20.0, "unit": "dB", "status": "OK"}],
            duration_seconds=2.5,
            version=1,
        )
        
        assert result.success is True
        assert result.executor == "spice"
        assert result.file_path == "amplifier.cir"
        assert result.analysis_type == "ac"
        assert result.data is not None
        assert result.measurements is not None
        assert result.measurements[0].name == "gain"
        assert result.error is None
        assert result.duration_seconds == 2.5
        assert result.version == 1
    
    def test_create_error_result(self):
        """测试创建失败结果"""
        result = create_error_result(
            executor="spice",
            file_path="amplifier.cir",
            analysis_type="ac",
            error="Convergence failed",
            duration_seconds=1.0,
            version=1,
        )
        
        assert result.success is False
        assert result.executor == "spice"
        assert result.data is None
        assert result.error == "Convergence failed"
    
    def test_serialization(self):
        """测试序列化"""
        data = SimulationData(
            frequency=np.array([1e3, 1e4, 1e5]),
            signals={"V(out)": np.array([0.1, 1.0, 10.0])},
        )
        
        result = create_success_result(
            executor="spice",
            file_path="amplifier.cir",
            analysis_type="ac",
            data=data,
            measurements=[{"name": "gain", "value": 20.0, "unit": "dB", "status": "OK"}],
            duration_seconds=2.5,
            version=1,
        )
        
        result_dict = result.to_dict()
        
        # 检查序列化结果
        assert result_dict["executor"] == "spice"
        assert result_dict["success"] is True
        assert isinstance(result_dict["data"], dict)
        assert isinstance(result_dict["data"]["frequency"], list)
        assert result_dict["measurements"][0]["name"] == "gain"
    
    def test_deserialization(self):
        """测试反序列化"""
        result_dict = {
            "executor": "spice",
            "file_path": "amplifier.cir",
            "analysis_type": "ac",
            "success": True,
            "data": {
                "frequency": [1e3, 1e4, 1e5],
                "time": None,
                "signals": {"V(out)": [0.1, 1.0, 10.0]},
            },
            "measurements": [
                {"name": "gain", "value": 20.0, "unit": "dB", "status": "OK"}
            ],
            "error": None,
            "raw_output": None,
            "timestamp": "2024-12-20T14:30:22.123456",
            "duration_seconds": 2.5,
            "version": 1,
        }
        
        result = SimulationResult.from_dict(result_dict)
        
        # 检查反序列化结果
        assert result.executor == "spice"
        assert result.success is True
        assert result.data is not None
        assert isinstance(result.data.frequency, np.ndarray)
        assert result.measurements is not None
        assert result.measurements[0].unit == "dB"
    
    def test_round_trip(self):
        """测试序列化-反序列化往返"""
        data = SimulationData(
            frequency=np.array([1e3, 1e4, 1e5]),
            signals={"V(out)": np.array([0.1, 1.0, 10.0])},
        )
        
        original = create_success_result(
            executor="spice",
            file_path="amplifier.cir",
            analysis_type="ac",
            data=data,
            measurements=[{"name": "gain", "value": 20.0, "unit": "dB", "status": "OK"}],
            duration_seconds=2.5,
            version=1,
        )
        
        result_dict = original.to_dict()
        restored = SimulationResult.from_dict(result_dict)
        
        # 检查往返后数据一致
        assert restored.executor == original.executor
        assert restored.success == original.success
        assert restored.measurements is not None
        assert original.measurements is not None
        assert restored.measurements[0].name == original.measurements[0].name
        assert restored.measurements[0].value == original.measurements[0].value
        assert np.array_equal(
            restored.data.frequency,
            original.data.frequency
        )
    
    def test_json_serialization(self):
        """测试 JSON 序列化（完整流程）"""
        data = SimulationData(
            frequency=np.array([1e3, 1e4, 1e5]),
            signals={"V(out)": np.array([0.1, 1.0, 10.0])},
        )
        
        result = create_success_result(
            executor="spice",
            file_path="amplifier.cir",
            analysis_type="ac",
            data=data,
            measurements=[{"name": "gain", "value": 20.0, "unit": "dB", "status": "OK"}],
            duration_seconds=2.5,
            version=1,
        )
        
        # 序列化为 JSON 字符串
        result_dict = result.to_dict()
        json_str = json.dumps(result_dict)
        
        # 从 JSON 字符串反序列化
        loaded_dict = json.loads(json_str)
        restored = SimulationResult.from_dict(loaded_dict)
        
        # 检查数据一致
        assert restored.executor == result.executor
        assert restored.success == result.success
        assert np.array_equal(
            restored.data.frequency,
            result.data.frequency
        )
    
    def test_is_successful(self):
        """测试判断是否成功"""
        success_result = create_success_result(
            executor="spice",
            file_path="test.cir",
            analysis_type="ac",
            data=SimulationData(),
        )
        
        error_result = create_error_result(
            executor="spice",
            file_path="test.cir",
            analysis_type="ac",
            error="Error",
        )
        
        assert success_result.is_successful() is True
        assert error_result.is_successful() is False
    
    def test_get_signal(self):
        """测试获取信号"""
        data = SimulationData(
            signals={"V(out)": np.array([0.1, 1.0, 10.0])},
        )
        
        result = create_success_result(
            executor="spice",
            file_path="test.cir",
            analysis_type="ac",
            data=data,
        )
        
        # 成功结果可以获取信号
        signal = result.get_signal("V(out)")
        assert signal is not None
        assert np.array_equal(signal, np.array([0.1, 1.0, 10.0]))
        
        # 不存在的信号返回 None
        signal = result.get_signal("V(in)")
        assert signal is None
        
        # 失败结果返回 None
        error_result = create_error_result(
            executor="spice",
            file_path="test.cir",
            analysis_type="ac",
            error="Error",
        )
        signal = error_result.get_signal("V(out)")
        assert signal is None
    
    def test_is_fresh(self):
        """测试检查数据新鲜度"""
        # 创建一个刚生成的结果
        result = create_success_result(
            executor="spice",
            file_path="test.cir",
            analysis_type="ac",
            data=SimulationData(),
        )
        
        # 应该是新鲜的
        assert result.is_fresh(max_age_seconds=300) is True
        
        # 创建一个旧的结果
        old_timestamp = (datetime.now() - timedelta(seconds=400)).isoformat()
        old_result = SimulationResult(
            executor="spice",
            file_path="test.cir",
            analysis_type="ac",
            success=True,
            timestamp=old_timestamp,
        )
        
        # 应该是过期的
        assert old_result.is_fresh(max_age_seconds=300) is False
    
    def test_get_age_seconds(self):
        """测试获取数据年龄"""
        result = create_success_result(
            executor="spice",
            file_path="test.cir",
            analysis_type="ac",
            data=SimulationData(),
        )
        
        age = result.get_age_seconds()
        # 刚创建的结果年龄应该接近 0
        assert 0 <= age < 1.0
    
    def test_has_metrics(self):
        """测试检查是否包含性能指标"""
        result_with_metrics = create_success_result(
            executor="spice",
            file_path="test.cir",
            analysis_type="ac",
            data=SimulationData(),
            measurements=[{"name": "gain", "value": 20.0, "unit": "dB", "status": "OK"}],
        )
        
        result_without_metrics = create_success_result(
            executor="spice",
            file_path="test.cir",
            analysis_type="ac",
            data=SimulationData(),
        )
        
        assert result_with_metrics.has_metrics() is True
        assert result_without_metrics.has_metrics() is False
    
    def test_get_metric(self):
        """测试获取性能指标"""
        result = create_success_result(
            executor="spice",
            file_path="test.cir",
            analysis_type="ac",
            data=SimulationData(),
            measurements=[
                {"name": "gain", "value": 20.0, "unit": "dB", "status": "OK"},
                {"name": "bandwidth", "value": 1e7, "unit": "Hz", "status": "OK"},
            ],
        )
        
        # 存在的指标
        assert result.get_metric("gain") == 20.0
        assert result.get_metric("bandwidth") == 1e7
        
        # 不存在的指标返回默认值
        assert result.get_metric("phase_margin") is None
        assert result.get_metric("phase_margin", "N/A") == "N/A"
    
    def test_get_summary(self):
        """测试获取结果摘要"""
        result = create_success_result(
            executor="spice",
            file_path="amplifier.cir",
            analysis_type="ac",
            data=SimulationData(),
            duration_seconds=2.5,
            version=1,
        )
        
        summary = result.get_summary()
        
        # 检查摘要包含关键信息
        assert "spice" in summary
        assert "amplifier.cir" in summary
        assert "ac" in summary
        assert "成功" in summary
        assert "2.50s" in summary
        assert "version=1" in summary


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
