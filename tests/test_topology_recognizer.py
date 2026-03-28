# Test TopologyRecognizer
"""
拓扑识别器测试

测试内容：
- 器件统计解析
- 节点识别
- 各类拓扑识别
- 推荐分析和关键指标
"""

import pytest

import sys
from pathlib import Path

# 添加项目根目录到 Python 路径
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from domain.simulation.analysis.topology_recognizer import (
    TopologyRecognizer,
    TopologyType,
    AmplifierSubType,
    FilterSubType,
    PowerSubType,
    OscillatorSubType,
    DeviceStats,
)


# ============================================================
# 测试网表样本
# ============================================================

COMMON_SOURCE_NETLIST = """
* Common Source Amplifier
M1 out gate 0 0 NMOS W=10u L=1u
R1 vdd out 10k
Vin gate 0 AC 1
Vdd vdd 0 DC 3.3
.ac dec 100 1 1G
.end
"""

DIFFERENTIAL_PAIR_NETLIST = """
* Differential Pair Amplifier
M1 outp inp tail 0 NMOS W=10u L=1u
M2 outn inn tail 0 NMOS W=10u L=1u
M3 tail bias 0 0 NMOS W=20u L=1u
R1 vdd outp 10k
R2 vdd outn 10k
Vinp inp 0 AC 1
Vinn inn 0 AC -1
Vdd vdd 0 DC 3.3
Vbias bias 0 DC 0.8
.ac dec 100 1 1G
.end
"""

OPAMP_CIRCUIT_NETLIST = """
* Inverting Amplifier with OpAmp
X1 inp inn out vdd vss opamp_741
R1 in inp 10k
R2 inp out 100k
Vin in 0 AC 1
Vdd vdd 0 DC 5
Vss vss 0 DC -5
.ac dec 100 1 1G
.end
"""

SALLEN_KEY_FILTER_NETLIST = """
* Sallen-Key Low Pass Filter
X1 inp inn out vdd vss opamp
R1 in n1 10k
R2 n1 inp 10k
C1 n1 out 10n
C2 inp 0 10n
Vin in 0 AC 1
Vdd vdd 0 DC 5
Vss vss 0 DC -5
.ac dec 100 1 1G
.end
"""

LC_OSCILLATOR_NETLIST = """
* LC Oscillator
M1 out gate 0 0 NMOS W=10u L=1u
L1 vdd out 1u
C1 out 0 1n
R1 gate out 1M
Vdd vdd 0 DC 3.3
.tran 1n 10u
.end
"""

BUCK_CONVERTER_NETLIST = """
* Buck Converter
M1 sw in 0 0 NMOS W=100u L=0.5u
D1 0 sw diode
L1 sw out 10u
C1 out 0 100u
R_load out 0 10
Vpwm in 0 PULSE(0 5 0 1n 1n 500n 1u)
.tran 1n 100u
.end
"""

PASSIVE_RC_FILTER_NETLIST = """
* Simple RC Low Pass Filter
R1 in out 10k
C1 out 0 10n
Vin in 0 AC 1
.ac dec 100 1 1G
.end
"""


# ============================================================
# 测试类
# ============================================================

class TestDeviceStatsParsing:
    """器件统计解析测试"""
    
    def test_parse_mosfet_count(self):
        """测试 MOSFET 计数"""
        recognizer = TopologyRecognizer()
        stats = recognizer._parse_device_stats(COMMON_SOURCE_NETLIST)
        assert stats.mosfets == 1
    
    def test_parse_differential_pair_mosfets(self):
        """测试差分对 MOSFET 计数"""
        recognizer = TopologyRecognizer()
        stats = recognizer._parse_device_stats(DIFFERENTIAL_PAIR_NETLIST)
        assert stats.mosfets == 3
        assert stats.nmos_count == 3
    
    def test_parse_resistors(self):
        """测试电阻计数"""
        recognizer = TopologyRecognizer()
        stats = recognizer._parse_device_stats(COMMON_SOURCE_NETLIST)
        assert stats.resistors == 1
    
    def test_parse_capacitors(self):
        """测试电容计数"""
        recognizer = TopologyRecognizer()
        stats = recognizer._parse_device_stats(SALLEN_KEY_FILTER_NETLIST)
        assert stats.capacitors == 2
    
    def test_parse_inductors(self):
        """测试电感计数"""
        recognizer = TopologyRecognizer()
        stats = recognizer._parse_device_stats(LC_OSCILLATOR_NETLIST)
        assert stats.inductors == 1
    
    def test_parse_subcircuits(self):
        """测试子电路计数"""
        recognizer = TopologyRecognizer()
        stats = recognizer._parse_device_stats(OPAMP_CIRCUIT_NETLIST)
        assert stats.subcircuits == 1
        assert stats.opamps == 1
    
    def test_parse_voltage_sources(self):
        """测试电压源计数"""
        recognizer = TopologyRecognizer()
        stats = recognizer._parse_device_stats(COMMON_SOURCE_NETLIST)
        assert stats.voltage_sources == 2


class TestNodeParsing:
    """节点解析测试"""
    
    def test_parse_power_node(self):
        """测试电源节点识别"""
        recognizer = TopologyRecognizer()
        nodes = recognizer._parse_nodes(COMMON_SOURCE_NETLIST)
        assert 'vdd' in nodes
        assert nodes['vdd'].is_power
    
    def test_parse_ground_node(self):
        """测试地节点识别"""
        recognizer = TopologyRecognizer()
        nodes = recognizer._parse_nodes(COMMON_SOURCE_NETLIST)
        assert '0' in nodes
        assert nodes['0'].is_ground
    
    def test_parse_input_node(self):
        """测试输入节点识别"""
        recognizer = TopologyRecognizer()
        nodes = recognizer._parse_nodes(DIFFERENTIAL_PAIR_NETLIST)
        assert 'inp' in nodes
        assert nodes['inp'].is_input
    
    def test_parse_output_node(self):
        """测试输出节点识别"""
        recognizer = TopologyRecognizer()
        nodes = recognizer._parse_nodes(COMMON_SOURCE_NETLIST)
        assert 'out' in nodes
        assert nodes['out'].is_output


class TestTopologyRecognition:
    """拓扑识别测试"""
    
    def test_recognize_common_source(self):
        """测试共源放大器识别"""
        recognizer = TopologyRecognizer()
        result = recognizer.recognize_topology(COMMON_SOURCE_NETLIST)
        assert result.success
        assert result.topology_type == TopologyType.AMPLIFIER.value
    
    def test_recognize_differential_pair(self):
        """测试差分对识别"""
        recognizer = TopologyRecognizer()
        result = recognizer.recognize_topology(DIFFERENTIAL_PAIR_NETLIST)
        assert result.success
        assert result.topology_type == TopologyType.AMPLIFIER.value
        assert result.sub_type in [
            AmplifierSubType.DIFFERENTIAL_PAIR.value,
            AmplifierSubType.TWO_STAGE.value
        ]
    
    def test_recognize_opamp_circuit(self):
        """测试运放电路识别"""
        recognizer = TopologyRecognizer()
        result = recognizer.recognize_topology(OPAMP_CIRCUIT_NETLIST)
        assert result.success
        assert result.topology_type == TopologyType.AMPLIFIER.value
        assert result.sub_type == AmplifierSubType.OPAMP.value
    
    def test_recognize_sallen_key_filter(self):
        """测试 Sallen-Key 滤波器识别"""
        recognizer = TopologyRecognizer()
        result = recognizer.recognize_topology(SALLEN_KEY_FILTER_NETLIST)
        assert result.success
        assert result.topology_type == TopologyType.FILTER.value
    
    def test_recognize_lc_oscillator(self):
        """测试 LC 振荡器识别"""
        recognizer = TopologyRecognizer()
        result = recognizer.recognize_topology(LC_OSCILLATOR_NETLIST)
        assert result.success
        assert result.topology_type == TopologyType.OSCILLATOR.value
        assert result.sub_type == OscillatorSubType.LC.value
    
    def test_recognize_passive_filter(self):
        """测试无源滤波器识别"""
        recognizer = TopologyRecognizer()
        result = recognizer.recognize_topology(PASSIVE_RC_FILTER_NETLIST)
        assert result.success
        assert result.topology_type == TopologyType.FILTER.value
    
    def test_confidence_range(self):
        """测试置信度范围"""
        recognizer = TopologyRecognizer()
        result = recognizer.recognize_topology(COMMON_SOURCE_NETLIST)
        assert 0.0 <= result.confidence <= 1.0


class TestRecommendedAnalyses:
    """推荐分析测试"""
    
    def test_amplifier_recommendations(self):
        """测试放大器推荐分析"""
        recognizer = TopologyRecognizer()
        analyses = recognizer.get_recommended_analyses(TopologyType.AMPLIFIER.value)
        assert 'ac' in analyses
        assert 'tran' in analyses
        assert 'noise' in analyses
    
    def test_filter_recommendations(self):
        """测试滤波器推荐分析"""
        recognizer = TopologyRecognizer()
        analyses = recognizer.get_recommended_analyses(TopologyType.FILTER.value)
        assert 'ac' in analyses
        assert 'tran' in analyses
    
    def test_power_recommendations(self):
        """测试电源推荐分析"""
        recognizer = TopologyRecognizer()
        analyses = recognizer.get_recommended_analyses(TopologyType.POWER.value)
        assert 'tran' in analyses
        assert 'dc' in analyses
    
    def test_oscillator_recommendations(self):
        """测试振荡器推荐分析"""
        recognizer = TopologyRecognizer()
        analyses = recognizer.get_recommended_analyses(TopologyType.OSCILLATOR.value)
        assert 'tran' in analyses


class TestKeyMetrics:
    """关键指标测试"""
    
    def test_amplifier_metrics(self):
        """测试放大器关键指标"""
        recognizer = TopologyRecognizer()
        metrics = recognizer.get_key_metrics(TopologyType.AMPLIFIER.value)
        assert 'gain' in metrics
        assert 'bandwidth' in metrics
        assert 'phase_margin' in metrics
    
    def test_filter_metrics(self):
        """测试滤波器关键指标"""
        recognizer = TopologyRecognizer()
        metrics = recognizer.get_key_metrics(TopologyType.FILTER.value)
        assert 'cutoff_frequency' in metrics
        assert 'passband_gain' in metrics
    
    def test_power_metrics(self):
        """测试电源关键指标"""
        recognizer = TopologyRecognizer()
        metrics = recognizer.get_key_metrics(TopologyType.POWER.value)
        assert 'efficiency' in metrics
        assert 'load_regulation' in metrics


class TestTypicalSpecs:
    """典型规格测试"""
    
    def test_amplifier_specs(self):
        """测试放大器典型规格"""
        recognizer = TopologyRecognizer()
        specs = recognizer.get_typical_specs(TopologyType.AMPLIFIER.value)
        assert 'gain' in specs
        assert len(specs['gain']) == 3  # (min, max, unit)
    
    def test_filter_specs(self):
        """测试滤波器典型规格"""
        recognizer = TopologyRecognizer()
        specs = recognizer.get_typical_specs(TopologyType.FILTER.value)
        assert 'cutoff_frequency' in specs


class TestCriticalNodes:
    """关键节点测试"""
    
    def test_critical_nodes_include_io(self):
        """测试关键节点包含输入输出"""
        recognizer = TopologyRecognizer()
        result = recognizer.recognize_topology(COMMON_SOURCE_NETLIST)
        # 输出节点应该在关键节点中
        assert 'out' in result.critical_nodes


class TestResultSerialization:
    """结果序列化测试"""
    
    def test_to_dict(self):
        """测试序列化为字典"""
        recognizer = TopologyRecognizer()
        result = recognizer.recognize_topology(COMMON_SOURCE_NETLIST)
        data = result.to_dict()
        assert 'topology_type' in data
        assert 'sub_type' in data
        assert 'confidence' in data
        assert 'recommended_analyses' in data
        assert 'key_metrics' in data
    
    def test_display_summary(self):
        """测试显示摘要"""
        recognizer = TopologyRecognizer()
        result = recognizer.recognize_topology(COMMON_SOURCE_NETLIST)
        summary = result.get_display_summary()
        assert '放大器' in summary or 'amplifier' in summary.lower()


class TestEdgeCases:
    """边界情况测试"""
    
    def test_empty_netlist(self):
        """测试空网表"""
        recognizer = TopologyRecognizer()
        result = recognizer.recognize_topology("")
        assert result.success
        assert result.topology_type == TopologyType.UNKNOWN.value
    
    def test_comments_only_netlist(self):
        """测试仅包含注释的网表"""
        netlist = """
        * This is a comment
        * Another comment
        """
        recognizer = TopologyRecognizer()
        result = recognizer.recognize_topology(netlist)
        assert result.success
        assert result.topology_type == TopologyType.UNKNOWN.value
    
    def test_netlist_with_special_characters(self):
        """测试包含特殊字符的网表"""
        netlist = """
        * Test circuit with special chars
        R1 in+ out- 10k
        C1 out- 0 10n
        """
        recognizer = TopologyRecognizer()
        result = recognizer.recognize_topology(netlist)
        assert result.success
