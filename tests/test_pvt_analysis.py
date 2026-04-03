# Test PVT Analysis Module
"""
PVT 角点分析模块测试

测试内容：
- PVTCorner 数据类序列化/反序列化
- PVTAnalyzer 默认角点配置
- PVTAnalyzer 自定义角点创建
- PVTAnalysisResult 统计属性
- 设计目标检查逻辑
"""

import pytest
from unittest.mock import Mock, MagicMock, patch

from domain.simulation.analysis.pvt_analysis import (
    PVTAnalyzer,
    PVTCorner,
    PVTCornerResult,
    PVTAnalysisResult,
    ProcessCorner,
    DEFAULT_PVT_CORNERS,
)
from domain.simulation.models.simulation_result import SimulationResult, SimulationData


# ============================================================
# PVTCorner 数据类测试
# ============================================================

class TestPVTCorner:
    """PVTCorner 数据类测试"""
    
    def test_create_corner(self):
        """测试创建角点"""
        corner = PVTCorner(
            name="TT",
            process=ProcessCorner.TYPICAL,
            voltage_factor=1.0,
            temperature=25.0,
            description="典型角点",
        )
        
        assert corner.name == "TT"
        assert corner.process == ProcessCorner.TYPICAL
        assert corner.voltage_factor == 1.0
        assert corner.temperature == 25.0
        assert corner.description == "典型角点"
    
    def test_to_dict(self):
        """测试序列化"""
        corner = PVTCorner(
            name="FF",
            process=ProcessCorner.FAST,
            voltage_factor=1.1,
            temperature=-40.0,
        )
        
        data = corner.to_dict()
        
        assert data["name"] == "FF"
        assert data["process"] == "fast"
        assert data["voltage_factor"] == 1.1
        assert data["temperature"] == -40.0
    
    def test_from_dict(self):
        """测试反序列化"""
        data = {
            "name": "SS",
            "process": "slow",
            "voltage_factor": 0.9,
            "temperature": 85.0,
            "description": "慢速角点",
        }
        
        corner = PVTCorner.from_dict(data)
        
        assert corner.name == "SS"
        assert corner.process == ProcessCorner.SLOW
        assert corner.voltage_factor == 0.9
        assert corner.temperature == 85.0
        assert corner.description == "慢速角点"
    
    def test_roundtrip_serialization(self):
        """测试序列化往返"""
        original = PVTCorner(
            name="FS",
            process=ProcessCorner.FAST_NMOS_SLOW_PMOS,
            voltage_factor=1.0,
            temperature=25.0,
            description="FS 角点",
        )
        
        data = original.to_dict()
        restored = PVTCorner.from_dict(data)
        
        assert restored.name == original.name
        assert restored.process == original.process
        assert restored.voltage_factor == original.voltage_factor
        assert restored.temperature == original.temperature
        assert restored.description == original.description


# ============================================================
# PVTAnalysisResult 测试
# ============================================================

class TestPVTAnalysisResult:
    """PVTAnalysisResult 测试"""
    
    def test_failed_corners_property(self):
        """测试失败角点属性"""
        result = PVTAnalysisResult(
            circuit_file="test.cir",
            analysis_type="ac",
        )
        
        # 添加角点结果
        corner1 = PVTCorner("TT", ProcessCorner.TYPICAL, 1.0, 25.0)
        corner2 = PVTCorner("FF", ProcessCorner.FAST, 1.1, -40.0)
        
        mock_sim_result = Mock(spec=SimulationResult)
        mock_sim_result.success = True
        mock_sim_result.to_dict.return_value = {}
        
        result.corners = [
            PVTCornerResult(corner=corner1, simulation_result=mock_sim_result, passed=True),
            PVTCornerResult(corner=corner2, simulation_result=mock_sim_result, passed=False),
        ]
        
        assert result.failed_corners == ["FF"]
        assert result.passed_corners == ["TT"]
    
    def test_to_dict(self):
        """测试序列化"""
        result = PVTAnalysisResult(
            circuit_file="test.cir",
            analysis_type="ac",
            all_passed=True,
            worst_corner="TT",
            duration_seconds=10.5,
        )
        
        data = result.to_dict()
        
        assert data["circuit_file"] == "test.cir"
        assert data["analysis_type"] == "ac"
        assert data["all_passed"] is True
        assert data["worst_corner"] == "TT"
        assert data["duration_seconds"] == 10.5


# ============================================================
# PVTAnalyzer 测试
# ============================================================

class TestPVTAnalyzer:
    """PVTAnalyzer 测试"""
    
    def test_get_default_corners(self):
        """测试获取默认角点"""
        analyzer = PVTAnalyzer()
        corners = analyzer.get_default_corners()
        
        assert len(corners) == 5
        
        # 检查角点名称
        names = [c.name for c in corners]
        assert "TT" in names
        assert "FF" in names
        assert "SS" in names
        assert "FS" in names
        assert "SF" in names
    
    def test_add_custom_corner(self):
        """测试添加自定义角点"""
        analyzer = PVTAnalyzer()
        
        corner = analyzer.add_custom_corner(
            name="CUSTOM",
            process=ProcessCorner.TYPICAL,
            voltage_factor=0.95,
            temperature=50.0,
            description="自定义角点",
        )
        
        assert corner.name == "CUSTOM"
        assert corner.process == ProcessCorner.TYPICAL
        assert corner.voltage_factor == 0.95
        assert corner.temperature == 50.0
    
    def test_default_corners_configuration(self):
        """测试默认角点配置正确性"""
        # TT 角点
        tt = DEFAULT_PVT_CORNERS[0]
        assert tt.name == "TT"
        assert tt.process == ProcessCorner.TYPICAL
        assert tt.voltage_factor == 1.0
        assert tt.temperature == 25.0
        
        # FF 角点
        ff = DEFAULT_PVT_CORNERS[1]
        assert ff.name == "FF"
        assert ff.process == ProcessCorner.FAST
        assert ff.voltage_factor == 1.1
        assert ff.temperature == -40.0
        
        # SS 角点
        ss = DEFAULT_PVT_CORNERS[2]
        assert ss.name == "SS"
        assert ss.process == ProcessCorner.SLOW
        assert ss.voltage_factor == 0.9
        assert ss.temperature == 85.0
    
    @patch('domain.simulation.analysis.pvt_analysis.SpiceExecutor')
    def test_run_pvt_corners_with_mock(self, mock_executor_class):
        """测试 PVT 角点仿真（使用 Mock）"""
        # 设置 Mock 执行器
        mock_executor = Mock()
        mock_executor_class.return_value = mock_executor
        
        # 模拟仿真结果
        mock_result = Mock(spec=SimulationResult)
        mock_result.success = True
        mock_result.metric_values = {"gain": 20.0}
        mock_result.to_dict.return_value = {"success": True}
        mock_executor.execute.return_value = mock_result
        
        analyzer = PVTAnalyzer(executor=mock_executor)
        
        # 只运行 2 个角点以加快测试
        corners = [
            PVTCorner("TT", ProcessCorner.TYPICAL, 1.0, 25.0),
            PVTCorner("FF", ProcessCorner.FAST, 1.1, -40.0),
        ]
        
        result = analyzer.run_pvt_corners(
            circuit_file="test.cir",
            analysis_config={"analysis_type": "ac"},
            corners=corners,
        )
        
        assert result.circuit_file == "test.cir"
        assert result.analysis_type == "ac"
        assert len(result.corners) == 2
        assert mock_executor.execute.call_count == 2
    
    def test_check_design_goals_pass(self):
        """测试设计目标检查 - 通过"""
        analyzer = PVTAnalyzer()
        
        metrics = {"gain": 25.0, "bandwidth": 1e6}
        goals = {
            "gain": {"min": 20.0},
            "bandwidth": {"min": 1e5, "max": 1e7},
        }
        
        passed, failed = analyzer._check_design_goals(metrics, goals)
        
        assert passed is True
        assert len(failed) == 0
    
    def test_check_design_goals_fail(self):
        """测试设计目标检查 - 失败"""
        analyzer = PVTAnalyzer()
        
        metrics = {"gain": 15.0, "bandwidth": 1e6}
        goals = {
            "gain": {"min": 20.0},
        }
        
        passed, failed = analyzer._check_design_goals(metrics, goals)
        
        assert passed is False
        assert len(failed) == 1
        assert "gain" in failed[0]
    
    def test_generate_pvt_report(self):
        """测试生成 PVT 报告"""
        analyzer = PVTAnalyzer()
        
        result = PVTAnalysisResult(
            circuit_file="amplifier.cir",
            analysis_type="ac",
            all_passed=True,
            worst_corner="SS",
            duration_seconds=5.0,
        )
        
        # 添加角点结果
        corner = PVTCorner("TT", ProcessCorner.TYPICAL, 1.0, 25.0, "典型角点")
        mock_sim = Mock(spec=SimulationResult)
        mock_sim.success = True
        mock_sim.to_dict.return_value = {}
        
        result.corners = [
            PVTCornerResult(
                corner=corner,
                simulation_result=mock_sim,
                metrics={"gain": 20.0},
                passed=True,
            )
        ]
        
        report = analyzer.generate_pvt_report(result)
        
        assert "# PVT 角点分析报告" in report
        assert "amplifier.cir" in report
        assert "TT" in report
        assert "典型角点" in report


# ============================================================
# ProcessCorner 枚举测试
# ============================================================

class TestProcessCorner:
    """ProcessCorner 枚举测试"""
    
    def test_enum_values(self):
        """测试枚举值"""
        assert ProcessCorner.TYPICAL.value == "typical"
        assert ProcessCorner.FAST.value == "fast"
        assert ProcessCorner.SLOW.value == "slow"
        assert ProcessCorner.FAST_NMOS_SLOW_PMOS.value == "fs"
        assert ProcessCorner.SLOW_NMOS_FAST_PMOS.value == "sf"
    
    def test_enum_from_value(self):
        """测试从值创建枚举"""
        assert ProcessCorner("typical") == ProcessCorner.TYPICAL
        assert ProcessCorner("fast") == ProcessCorner.FAST
        assert ProcessCorner("slow") == ProcessCorner.SLOW


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
