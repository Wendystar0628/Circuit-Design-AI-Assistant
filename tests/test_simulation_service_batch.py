# Test SimulationService Batch Execution
"""
测试 SimulationService 批量执行功能

测试内容：
- run_selected_analyses 方法的基本功能
- 事件发布机制
- 配置构建逻辑
"""

import pytest
from unittest.mock import MagicMock, patch, call
from pathlib import Path

from domain.services.simulation_service import SimulationService
from domain.simulation.models.simulation_result import SimulationResult, SimulationData


class TestRunSelectedAnalyses:
    """测试 run_selected_analyses 方法"""
    
    @pytest.fixture
    def mock_registry(self):
        """模拟执行器注册表"""
        registry = MagicMock()
        executor = MagicMock()
        executor.get_name.return_value = "spice"
        executor.execute.return_value = SimulationResult(
            executor="spice",
            file_path="test.cir",
            analysis_type="ac",
            success=True,
            data=None,
            measurements=[{"name": "gain", "value": 20.0, "unit": "dB", "status": "OK"}],
            error=None,
            raw_output="",
            timestamp="2024-01-01T00:00:00",
            duration_seconds=1.0,
            version=1,
            session_id="",
        )
        registry.get_executor_for_file.return_value = executor
        return registry
    
    @pytest.fixture
    def service(self, mock_registry):
        """创建服务实例"""
        return SimulationService(registry=mock_registry)
    
    def test_empty_selection_returns_empty_dict(self, service):
        """测试没有选中分析时返回空字典"""
        with patch("domain.simulation.service.analysis_selector.analysis_selector") as mock_selector:
            mock_selector.get_execution_order.return_value = []
            
            results = service.run_selected_analyses(
                file_path="test.cir",
                project_root="/tmp/project",
            )
            
            assert results == {}
    
    def test_single_analysis_execution(self, service, mock_registry):
        """测试单个分析执行"""
        from domain.simulation.service.analysis_selector import AnalysisType
        
        with patch("domain.simulation.service.analysis_selector.analysis_selector") as mock_selector, \
             patch("domain.simulation.service.simulation_config_service.simulation_config_service") as mock_config:
            
            mock_selector.get_execution_order.return_value = [AnalysisType.AC]
            mock_config.load_config.return_value = self._create_mock_config()
            
            results = service.run_selected_analyses(
                file_path="test.cir",
                project_root="/tmp/project",
            )
            
            assert "ac" in results
            assert results["ac"].success is True
    
    def test_multiple_analyses_execution_order(self, service, mock_registry):
        """测试多个分析按顺序执行"""
        from domain.simulation.service.analysis_selector import AnalysisType
        
        call_order = []
        
        def track_execute(file_path, config):
            call_order.append(config.get("analysis_type"))
            return SimulationResult(
                executor="spice",
                file_path=file_path,
                analysis_type=config.get("analysis_type", "ac"),
                success=True,
                data=None,
                measurements=[],
                error=None,
                raw_output="",
                timestamp="2024-01-01T00:00:00",
                duration_seconds=0.5,
                version=1,
                session_id="",
            )
        
        mock_registry.get_executor_for_file.return_value.execute.side_effect = track_execute
        
        with patch("domain.simulation.service.analysis_selector.analysis_selector") as mock_selector, \
             patch("domain.simulation.service.simulation_config_service.simulation_config_service") as mock_config:
            
            mock_selector.get_execution_order.return_value = [
                AnalysisType.OP,
                AnalysisType.AC,
                AnalysisType.TRANSIENT,
            ]
            mock_config.load_config.return_value = self._create_mock_config()
            
            results = service.run_selected_analyses(
                file_path="test.cir",
                project_root="/tmp/project",
            )
            
            assert call_order == ["op", "ac", "tran"]
            assert len(results) == 3
    
    def test_partial_failure_continues_execution(self, service, mock_registry):
        """测试部分失败时继续执行后续分析"""
        from domain.simulation.service.analysis_selector import AnalysisType
        from domain.simulation.models.simulation_error import (
            SimulationError,
            SimulationErrorType,
            ErrorSeverity,
        )
        
        execution_count = [0]
        
        def execute_with_failure(file_path, config):
            execution_count[0] += 1
            analysis_type = config.get("analysis_type", "ac")
            
            # 第二个分析失败
            if execution_count[0] == 2:
                return SimulationResult(
                    executor="spice",
                    file_path=file_path,
                    analysis_type=analysis_type,
                    success=False,
                    data=None,
                    measurements=None,
                    error=SimulationError(
                        code="E001",
                        type=SimulationErrorType.CONVERGENCE_DC,
                        severity=ErrorSeverity.HIGH,
                        message="Convergence failed",
                    ),
                    raw_output="",
                    timestamp="2024-01-01T00:00:00",
                    duration_seconds=0.5,
                    version=1,
                    session_id="",
                )
            
            return SimulationResult(
                executor="spice",
                file_path=file_path,
                analysis_type=analysis_type,
                success=True,
                data=None,
                measurements=[],
                error=None,
                raw_output="",
                timestamp="2024-01-01T00:00:00",
                duration_seconds=0.5,
                version=1,
                session_id="",
            )
        
        mock_registry.get_executor_for_file.return_value.execute.side_effect = execute_with_failure
        
        with patch("domain.simulation.service.analysis_selector.analysis_selector") as mock_selector, \
             patch("domain.simulation.service.simulation_config_service.simulation_config_service") as mock_config:
            
            mock_selector.get_execution_order.return_value = [
                AnalysisType.OP,
                AnalysisType.AC,
                AnalysisType.TRANSIENT,
            ]
            mock_config.load_config.return_value = self._create_mock_config()
            
            results = service.run_selected_analyses(
                file_path="test.cir",
                project_root="/tmp/project",
            )
            
            # 所有分析都应该执行
            assert execution_count[0] == 3
            assert len(results) == 3
            
            # 检查成功/失败状态
            assert results["op"].success is True
            assert results["ac"].success is False
            assert results["tran"].success is True
    
    def test_event_publishing(self, service, mock_registry):
        """测试事件发布"""
        from domain.simulation.service.analysis_selector import AnalysisType
        
        published_events = []
        
        def capture_publish(event_name, data):
            published_events.append((event_name, data))
        
        with patch("domain.simulation.service.analysis_selector.analysis_selector") as mock_selector, \
             patch("domain.simulation.service.simulation_config_service.simulation_config_service") as mock_config, \
             patch("domain.services.simulation_service._get_event_bus") as mock_get_bus:
            
            mock_bus = MagicMock()
            mock_bus.publish.side_effect = capture_publish
            mock_get_bus.return_value = mock_bus
            
            mock_selector.get_execution_order.return_value = [
                AnalysisType.AC,
                AnalysisType.DC,
            ]
            mock_config.load_config.return_value = self._create_mock_config()
            
            service.run_selected_analyses(
                file_path="test.cir",
                project_root="/tmp/project",
            )
            
            # 检查事件发布
            event_names = [e[0] for e in published_events]
            
            # 应该有 sim_started, sim_complete 各两次
            # 加上 analysis_complete 两次和 all_analyses_complete 一次
            assert event_names.count("analysis_complete") == 2
            assert event_names.count("all_analyses_complete") == 1
    
    def _create_mock_config(self):
        """创建模拟配置"""
        from domain.simulation.service.simulation_config_service import FullSimulationConfig
        return FullSimulationConfig.get_default()


class TestBuildAnalysisConfig:
    """测试 _build_analysis_config 方法"""
    
    @pytest.fixture
    def service(self):
        """创建服务实例"""
        return SimulationService()
    
    def test_ac_config_building(self, service):
        """测试 AC 分析配置构建"""
        from domain.simulation.service.analysis_selector import AnalysisType
        from domain.simulation.service.simulation_config_service import FullSimulationConfig
        
        config = FullSimulationConfig.get_default()
        config.ac.start_freq = 100.0
        config.ac.stop_freq = 1e9
        
        result = service._build_analysis_config(AnalysisType.AC, config)
        
        assert result["analysis_type"] == "ac"
        assert result["start_freq"] == 100.0
        assert result["stop_freq"] == 1e9
        assert "timeout_seconds" in result
        assert "convergence" in result
    
    def test_dc_config_building(self, service):
        """测试 DC 分析配置构建"""
        from domain.simulation.service.analysis_selector import AnalysisType
        from domain.simulation.service.simulation_config_service import FullSimulationConfig
        
        config = FullSimulationConfig.get_default()
        config.dc.source_name = "Vin"
        config.dc.start_value = 0.0
        config.dc.stop_value = 5.0
        
        result = service._build_analysis_config(AnalysisType.DC, config)
        
        assert result["analysis_type"] == "dc"
        assert result["source_name"] == "Vin"
        assert result["start_value"] == 0.0
        assert result["stop_value"] == 5.0
    
    def test_transient_config_building(self, service):
        """测试瞬态分析配置构建"""
        from domain.simulation.service.analysis_selector import AnalysisType
        from domain.simulation.service.simulation_config_service import FullSimulationConfig
        
        config = FullSimulationConfig.get_default()
        config.transient.step_time = 1e-9
        config.transient.end_time = 1e-3
        
        result = service._build_analysis_config(AnalysisType.TRANSIENT, config)
        
        assert result["analysis_type"] == "tran"
        assert result["step_time"] == 1e-9
        assert result["end_time"] == 1e-3
    
    def test_op_config_minimal(self, service):
        """测试 OP 分析配置（最小配置）"""
        from domain.simulation.service.analysis_selector import AnalysisType
        from domain.simulation.service.simulation_config_service import FullSimulationConfig
        
        config = FullSimulationConfig.get_default()
        
        result = service._build_analysis_config(AnalysisType.OP, config)
        
        assert result["analysis_type"] == "op"
        assert "timeout_seconds" in result
        assert "convergence" in result
    
    def test_noise_config_building(self, service):
        """测试噪声分析配置构建"""
        from domain.simulation.service.analysis_selector import AnalysisType
        from domain.simulation.service.simulation_config_service import FullSimulationConfig
        
        config = FullSimulationConfig.get_default()
        config.noise.output_node = "out"
        config.noise.input_source = "Vin"
        
        result = service._build_analysis_config(AnalysisType.NOISE, config)
        
        assert result["analysis_type"] == "noise"
        assert result["output_node"] == "out"
        assert result["input_source"] == "Vin"
