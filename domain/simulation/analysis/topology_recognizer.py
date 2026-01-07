# TopologyRecognizer - Circuit Topology Recognition
"""
电路拓扑识别模块

职责：
- 自动识别电路拓扑类型（放大器、滤波器、电源、振荡器等）
- 为仿真配置和指标提取提供指导
- 识别关键节点

设计原则：
- 基于网表结构分析识别拓扑
- 基于器件组合模式识别典型电路结构
- 基于仿真控制语句推断分析意图
- 返回结构化的 TopologyResult

使用示例：
    from domain.simulation.analysis.topology_recognizer import TopologyRecognizer
    
    recognizer = TopologyRecognizer()
    
    # 从网表识别拓扑
    result = recognizer.recognize_topology(netlist_content)
    print(f"拓扑类型: {result.topology_type}/{result.sub_type}")
    print(f"置信度: {result.confidence:.0%}")
    
    # 获取推荐分析
    analyses = recognizer.get_recommended_analyses(result.topology_type)
    
    # 获取关键指标
    metrics = recognizer.get_key_metrics(result.topology_type)
"""

import logging
import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Set, Tuple

from domain.simulation.models.analysis_result import TopologyResult


# ============================================================
# 拓扑类型枚举
# ============================================================

class TopologyType(str, Enum):
    """拓扑主类型"""
    AMPLIFIER = "amplifier"
    FILTER = "filter"
    POWER = "power"
    OSCILLATOR = "oscillator"
    COMPARATOR = "comparator"
    CONVERTER = "converter"
    UNKNOWN = "unknown"


class AmplifierSubType(str, Enum):
    """放大器子类型"""
    COMMON_SOURCE = "common_source"
    COMMON_DRAIN = "common_drain"
    COMMON_GATE = "common_gate"
    COMMON_EMITTER = "common_emitter"
    COMMON_COLLECTOR = "common_collector"
    COMMON_BASE = "common_base"
    DIFFERENTIAL_PAIR = "differential_pair"
    OPAMP = "opamp"
    INSTRUMENTATION_AMP = "instrumentation_amp"
    CASCODE = "cascode"
    FOLDED_CASCODE = "folded_cascode"
    TWO_STAGE = "two_stage"
    UNKNOWN = "unknown"


class FilterSubType(str, Enum):
    """滤波器子类型"""
    LOWPASS = "lowpass"
    HIGHPASS = "highpass"
    BANDPASS = "bandpass"
    BANDSTOP = "bandstop"
    ALLPASS = "allpass"
    SALLEN_KEY = "sallen_key"
    MFB = "mfb"
    STATE_VARIABLE = "state_variable"
    UNKNOWN = "unknown"


class PowerSubType(str, Enum):
    """电源子类型"""
    LDO = "ldo"
    BUCK = "buck"
    BOOST = "boost"
    BUCK_BOOST = "buck_boost"
    FLYBACK = "flyback"
    CHARGE_PUMP = "charge_pump"
    UNKNOWN = "unknown"


class OscillatorSubType(str, Enum):
    """振荡器子类型"""
    RING = "ring"
    LC = "lc"
    CRYSTAL = "crystal"
    RC = "rc"
    RELAXATION = "relaxation"
    UNKNOWN = "unknown"


# ============================================================
# 器件统计数据类
# ============================================================

@dataclass
class DeviceStats:
    """器件统计"""
    mosfets: int = 0
    bjts: int = 0
    resistors: int = 0
    capacitors: int = 0
    inductors: int = 0
    diodes: int = 0
    opamps: int = 0
    voltage_sources: int = 0
    current_sources: int = 0
    subcircuits: int = 0
    
    # 详细信息
    nmos_count: int = 0
    pmos_count: int = 0
    npn_count: int = 0
    pnp_count: int = 0
    
    def total_active(self) -> int:
        """有源器件总数"""
        return self.mosfets + self.bjts + self.opamps
    
    def total_passive(self) -> int:
        """无源器件总数"""
        return self.resistors + self.capacitors + self.inductors
    
    def has_feedback_elements(self) -> bool:
        """是否有反馈元件（电阻或电容）"""
        return self.resistors > 0 or self.capacitors > 0


@dataclass
class NodeInfo:
    """节点信息"""
    name: str
    connected_devices: List[str] = field(default_factory=list)
    is_power: bool = False
    is_ground: bool = False
    is_input: bool = False
    is_output: bool = False


# ============================================================
# TopologyRecognizer - 电路拓扑识别器
# ============================================================

class TopologyRecognizer:
    """
    电路拓扑识别器
    
    通过分析 SPICE 网表内容识别电路拓扑类型。
    """
    
    # 电源节点名称模式
    POWER_NODE_PATTERNS = [
        r'^vdd$', r'^vcc$', r'^vss$', r'^vee$',
        r'^avdd$', r'^dvdd$', r'^v\+$', r'^v-$',
        r'^supply$', r'^pwr$'
    ]
    
    # 地节点名称模式
    GROUND_NODE_PATTERNS = [
        r'^0$', r'^gnd$', r'^ground$', r'^vss$', r'^gnda$', r'^gndd$'
    ]
    
    # 输入节点名称模式
    INPUT_NODE_PATTERNS = [
        r'^in$', r'^inp$', r'^inn$', r'^vin$', r'^vinp$', r'^vinn$',
        r'^input$', r'^in\+$', r'^in-$', r'^sig$', r'^signal$'
    ]
    
    # 输出节点名称模式
    OUTPUT_NODE_PATTERNS = [
        r'^out$', r'^outp$', r'^outn$', r'^vout$', r'^voutp$', r'^voutn$',
        r'^output$', r'^out\+$', r'^out-$'
    ]
    
    def __init__(self):
        """初始化拓扑识别器"""
        self._logger = logging.getLogger(__name__)
    
    # ============================================================
    # 公开接口
    # ============================================================
    
    def recognize_topology(self, spice_netlist: str) -> TopologyResult:
        """
        识别电路拓扑类型
        
        Args:
            spice_netlist: SPICE 网表内容
            
        Returns:
            TopologyResult: 拓扑识别结果
        """
        # 解析网表
        device_stats = self._parse_device_stats(spice_netlist)
        nodes = self._parse_nodes(spice_netlist)
        sim_commands = self._parse_simulation_commands(spice_netlist)
        
        # 识别拓扑类型
        topology_type, sub_type, confidence = self._identify_topology(
            device_stats, nodes, sim_commands, spice_netlist
        )
        
        # 获取推荐分析和关键指标
        recommended_analyses = self.get_recommended_analyses(topology_type)
        key_metrics = self.get_key_metrics(topology_type)
        critical_nodes = self._identify_critical_nodes(nodes, topology_type)
        
        # 生成摘要
        summary = self._generate_summary(topology_type, sub_type, confidence)
        
        return TopologyResult(
            analysis_type="topology",
            success=True,
            summary=summary,
            topology_type=topology_type,
            sub_type=sub_type,
            confidence=confidence,
            recommended_analyses=recommended_analyses,
            key_metrics=key_metrics,
            critical_nodes=critical_nodes,
        )

    
    def get_recommended_analyses(self, topology_type: str) -> List[str]:
        """
        获取推荐的分析类型
        
        Args:
            topology_type: 拓扑类型
            
        Returns:
            List[str]: 推荐的分析类型列表
        """
        recommendations = {
            TopologyType.AMPLIFIER.value: ["ac", "tran", "noise", "dc"],
            TopologyType.FILTER.value: ["ac", "tran"],
            TopologyType.POWER.value: ["tran", "dc"],
            TopologyType.OSCILLATOR.value: ["tran"],
            TopologyType.COMPARATOR.value: ["tran", "dc"],
            TopologyType.CONVERTER.value: ["tran", "dc", "noise"],
            TopologyType.UNKNOWN.value: ["dc", "ac", "tran"],
        }
        return recommendations.get(topology_type, ["dc", "ac", "tran"])
    
    def get_key_metrics(self, topology_type: str) -> List[str]:
        """
        获取关键性能指标列表
        
        Args:
            topology_type: 拓扑类型
            
        Returns:
            List[str]: 关键性能指标列表
        """
        metrics = {
            TopologyType.AMPLIFIER.value: [
                "gain", "bandwidth", "gbw", "phase_margin", "gain_margin",
                "input_impedance", "output_impedance", "slew_rate",
                "cmrr", "psrr", "noise"
            ],
            TopologyType.FILTER.value: [
                "cutoff_frequency", "passband_gain", "stopband_attenuation",
                "quality_factor", "group_delay", "phase_response"
            ],
            TopologyType.POWER.value: [
                "efficiency", "load_regulation", "line_regulation",
                "dropout_voltage", "output_ripple", "transient_response"
            ],
            TopologyType.OSCILLATOR.value: [
                "frequency", "phase_noise", "startup_time",
                "amplitude", "duty_cycle", "jitter"
            ],
            TopologyType.COMPARATOR.value: [
                "propagation_delay", "hysteresis", "input_offset",
                "overdrive_recovery", "output_swing"
            ],
            TopologyType.CONVERTER.value: [
                "resolution", "snr", "thd", "sfdr", "enob",
                "conversion_rate", "dnl", "inl"
            ],
            TopologyType.UNKNOWN.value: [
                "dc_operating_point", "frequency_response", "transient_response"
            ],
        }
        return metrics.get(topology_type, metrics[TopologyType.UNKNOWN.value])
    
    def get_typical_specs(self, topology_type: str) -> Dict[str, Tuple[float, float, str]]:
        """
        获取典型规格范围
        
        Args:
            topology_type: 拓扑类型
            
        Returns:
            Dict[str, Tuple[float, float, str]]: 指标名 -> (最小值, 最大值, 单位)
        """
        specs = {
            TopologyType.AMPLIFIER.value: {
                "gain": (20.0, 100.0, "dB"),
                "bandwidth": (1e3, 1e9, "Hz"),
                "phase_margin": (45.0, 90.0, "deg"),
                "gain_margin": (6.0, 20.0, "dB"),
                "slew_rate": (0.1, 1000.0, "V/us"),
            },
            TopologyType.FILTER.value: {
                "cutoff_frequency": (1.0, 1e9, "Hz"),
                "passband_gain": (-3.0, 0.0, "dB"),
                "stopband_attenuation": (-60.0, -20.0, "dB"),
                "quality_factor": (0.5, 10.0, ""),
            },
            TopologyType.POWER.value: {
                "efficiency": (70.0, 98.0, "%"),
                "load_regulation": (0.01, 5.0, "%"),
                "line_regulation": (0.01, 2.0, "%"),
                "dropout_voltage": (0.1, 1.0, "V"),
            },
        }
        return specs.get(topology_type, {})

    
    # ============================================================
    # 网表解析方法
    # ============================================================
    
    def _parse_device_stats(self, netlist: str) -> DeviceStats:
        """解析器件统计"""
        stats = DeviceStats()
        lines = netlist.splitlines()
        
        for line in lines:
            line = line.strip()
            if not line or line.startswith('*') or line.startswith(';'):
                continue
            
            # 跳过 SPICE 指令
            if line.startswith('.'):
                continue
            
            # 获取器件类型（首字符）
            first_char = line[0].upper()
            
            if first_char == 'M':
                stats.mosfets += 1
                # 检查 NMOS/PMOS
                line_upper = line.upper()
                if 'NMOS' in line_upper or 'NFET' in line_upper:
                    stats.nmos_count += 1
                elif 'PMOS' in line_upper or 'PFET' in line_upper:
                    stats.pmos_count += 1
            elif first_char == 'Q':
                stats.bjts += 1
                line_upper = line.upper()
                if 'NPN' in line_upper:
                    stats.npn_count += 1
                elif 'PNP' in line_upper:
                    stats.pnp_count += 1
            elif first_char == 'R':
                stats.resistors += 1
            elif first_char == 'C':
                stats.capacitors += 1
            elif first_char == 'L':
                stats.inductors += 1
            elif first_char == 'D':
                stats.diodes += 1
            elif first_char == 'V':
                stats.voltage_sources += 1
            elif first_char == 'I':
                stats.current_sources += 1
            elif first_char == 'X':
                stats.subcircuits += 1
                # 检查是否为运放子电路
                line_lower = line.lower()
                if any(op in line_lower for op in ['opamp', 'op_amp', 'lm741', 'ua741', 'tl07', 'opa']):
                    stats.opamps += 1
        
        return stats
    
    def _parse_nodes(self, netlist: str) -> Dict[str, NodeInfo]:
        """解析节点信息"""
        nodes: Dict[str, NodeInfo] = {}
        lines = netlist.splitlines()
        
        for line in lines:
            line = line.strip()
            if not line or line.startswith('*') or line.startswith(';') or line.startswith('.'):
                continue
            
            # 解析器件行，提取节点
            parts = line.split()
            if len(parts) < 2:
                continue
            
            device_name = parts[0]
            # 根据器件类型确定节点位置
            node_names = self._extract_node_names(parts)
            
            for node_name in node_names:
                if node_name not in nodes:
                    nodes[node_name] = NodeInfo(name=node_name)
                    # 识别特殊节点
                    nodes[node_name].is_power = self._is_power_node(node_name)
                    nodes[node_name].is_ground = self._is_ground_node(node_name)
                    nodes[node_name].is_input = self._is_input_node(node_name)
                    nodes[node_name].is_output = self._is_output_node(node_name)
                
                nodes[node_name].connected_devices.append(device_name)
        
        return nodes
    
    def _extract_node_names(self, parts: List[str]) -> List[str]:
        """从器件行提取节点名称"""
        if len(parts) < 2:
            return []
        
        device_type = parts[0][0].upper()
        
        # 不同器件类型的节点位置
        if device_type in ['R', 'C', 'L', 'V', 'I', 'D']:
            # 两端器件：name node1 node2 value
            return parts[1:3] if len(parts) >= 3 else []
        elif device_type == 'M':
            # MOSFET：name drain gate source bulk model
            return parts[1:5] if len(parts) >= 5 else parts[1:4] if len(parts) >= 4 else []
        elif device_type == 'Q':
            # BJT：name collector base emitter model
            return parts[1:4] if len(parts) >= 4 else []
        elif device_type == 'X':
            # 子电路：name nodes... subckt_name
            # 节点在 name 和 subckt_name 之间
            if len(parts) >= 3:
                return parts[1:-1]
            return []
        
        return []
    
    def _parse_simulation_commands(self, netlist: str) -> Set[str]:
        """解析仿真控制语句"""
        commands = set()
        lines = netlist.splitlines()
        
        sim_patterns = {
            '.ac': 'ac',
            '.dc': 'dc',
            '.tran': 'tran',
            '.noise': 'noise',
            '.op': 'op',
            '.tf': 'tf',
            '.sens': 'sens',
            '.pz': 'pz',
            '.disto': 'disto',
        }
        
        for line in lines:
            line_lower = line.strip().lower()
            for pattern, cmd in sim_patterns.items():
                if line_lower.startswith(pattern):
                    commands.add(cmd)
        
        return commands

    
    # ============================================================
    # 节点识别辅助方法
    # ============================================================
    
    def _is_power_node(self, node_name: str) -> bool:
        """判断是否为电源节点"""
        node_lower = node_name.lower()
        for pattern in self.POWER_NODE_PATTERNS:
            if re.match(pattern, node_lower):
                return True
        return False
    
    def _is_ground_node(self, node_name: str) -> bool:
        """判断是否为地节点"""
        node_lower = node_name.lower()
        for pattern in self.GROUND_NODE_PATTERNS:
            if re.match(pattern, node_lower):
                return True
        return False
    
    def _is_input_node(self, node_name: str) -> bool:
        """判断是否为输入节点"""
        node_lower = node_name.lower()
        for pattern in self.INPUT_NODE_PATTERNS:
            if re.match(pattern, node_lower):
                return True
        return False
    
    def _is_output_node(self, node_name: str) -> bool:
        """判断是否为输出节点"""
        node_lower = node_name.lower()
        for pattern in self.OUTPUT_NODE_PATTERNS:
            if re.match(pattern, node_lower):
                return True
        return False
    
    # ============================================================
    # 拓扑识别核心逻辑
    # ============================================================
    
    def _identify_topology(
        self,
        stats: DeviceStats,
        nodes: Dict[str, NodeInfo],
        sim_commands: Set[str],
        netlist: str
    ) -> Tuple[str, str, float]:
        """
        识别拓扑类型
        
        Returns:
            Tuple[str, str, float]: (主类型, 子类型, 置信度)
        """
        # 检查是否有运放
        if stats.opamps > 0:
            return self._identify_opamp_topology(stats, nodes, netlist)
        
        # 检查是否有 LC 组合（可能是振荡器或滤波器）
        if stats.inductors > 0 and stats.capacitors > 0:
            return self._identify_lc_topology(stats, nodes, netlist)
        
        # 检查是否有开关元件（电源转换器）
        if self._has_switching_elements(netlist):
            return self._identify_power_topology(stats, nodes, netlist)
        
        # 检查是否为晶体管放大器
        if stats.mosfets > 0 or stats.bjts > 0:
            return self._identify_transistor_topology(stats, nodes, netlist)
        
        # 检查是否为 RC 滤波器
        if stats.resistors > 0 and stats.capacitors > 0 and stats.total_active() == 0:
            return self._identify_passive_filter(stats, nodes, netlist)
        
        return TopologyType.UNKNOWN.value, "unknown", 0.3
    
    def _identify_opamp_topology(
        self,
        stats: DeviceStats,
        nodes: Dict[str, NodeInfo],
        netlist: str
    ) -> Tuple[str, str, float]:
        """识别运放电路拓扑"""
        netlist_lower = netlist.lower()
        
        # 检查是否为仪表放大器（3个运放）
        if stats.opamps >= 3:
            return TopologyType.AMPLIFIER.value, AmplifierSubType.INSTRUMENTATION_AMP.value, 0.8
        
        # 检查是否为滤波器（Sallen-Key, MFB 等）
        if stats.capacitors >= 2:
            if 'sallen' in netlist_lower or 'key' in netlist_lower:
                return TopologyType.FILTER.value, FilterSubType.SALLEN_KEY.value, 0.9
            if stats.opamps == 1 and stats.capacitors == 2:
                # 可能是二阶有源滤波器
                return TopologyType.FILTER.value, FilterSubType.SALLEN_KEY.value, 0.6
        
        # 检查是否为比较器
        if self._is_comparator_circuit(netlist):
            return TopologyType.COMPARATOR.value, "single_ended", 0.7
        
        # 默认为运放放大器
        return TopologyType.AMPLIFIER.value, AmplifierSubType.OPAMP.value, 0.7
    
    def _identify_lc_topology(
        self,
        stats: DeviceStats,
        nodes: Dict[str, NodeInfo],
        netlist: str
    ) -> Tuple[str, str, float]:
        """识别 LC 电路拓扑"""
        # 检查是否有有源器件（振荡器需要有源器件）
        if stats.total_active() > 0:
            return TopologyType.OSCILLATOR.value, OscillatorSubType.LC.value, 0.7
        
        # 无源 LC 滤波器
        return TopologyType.FILTER.value, FilterSubType.UNKNOWN.value, 0.6
    
    def _identify_power_topology(
        self,
        stats: DeviceStats,
        nodes: Dict[str, NodeInfo],
        netlist: str
    ) -> Tuple[str, str, float]:
        """识别电源拓扑"""
        netlist_lower = netlist.lower()
        
        # 检查关键字
        if 'buck' in netlist_lower:
            return TopologyType.POWER.value, PowerSubType.BUCK.value, 0.8
        if 'boost' in netlist_lower:
            return TopologyType.POWER.value, PowerSubType.BOOST.value, 0.8
        if 'ldo' in netlist_lower:
            return TopologyType.POWER.value, PowerSubType.LDO.value, 0.8
        if 'flyback' in netlist_lower:
            return TopologyType.POWER.value, PowerSubType.FLYBACK.value, 0.8
        
        # 根据电感和开关判断
        if stats.inductors > 0 and stats.diodes > 0:
            return TopologyType.POWER.value, PowerSubType.BUCK.value, 0.5
        
        return TopologyType.POWER.value, PowerSubType.UNKNOWN.value, 0.4

    
    def _identify_transistor_topology(
        self,
        stats: DeviceStats,
        nodes: Dict[str, NodeInfo],
        netlist: str
    ) -> Tuple[str, str, float]:
        """识别晶体管放大器拓扑"""
        netlist_lower = netlist.lower()
        
        # 检查是否为差分对
        if self._is_differential_pair(stats, nodes, netlist):
            # 检查是否为两级运放
            if stats.mosfets >= 4 or stats.bjts >= 4:
                return TopologyType.AMPLIFIER.value, AmplifierSubType.TWO_STAGE.value, 0.7
            return TopologyType.AMPLIFIER.value, AmplifierSubType.DIFFERENTIAL_PAIR.value, 0.8
        
        # 检查是否为 cascode
        if 'cascode' in netlist_lower:
            if 'folded' in netlist_lower:
                return TopologyType.AMPLIFIER.value, AmplifierSubType.FOLDED_CASCODE.value, 0.9
            return TopologyType.AMPLIFIER.value, AmplifierSubType.CASCODE.value, 0.9
        
        # 检查是否为环形振荡器
        if self._is_ring_oscillator(stats, nodes, netlist):
            return TopologyType.OSCILLATOR.value, OscillatorSubType.RING.value, 0.8
        
        # 单管放大器
        if stats.mosfets == 1:
            return self._identify_single_mosfet_config(nodes, netlist)
        if stats.bjts == 1:
            return self._identify_single_bjt_config(nodes, netlist)
        
        # 默认为放大器
        return TopologyType.AMPLIFIER.value, AmplifierSubType.UNKNOWN.value, 0.4
    
    def _identify_passive_filter(
        self,
        stats: DeviceStats,
        nodes: Dict[str, NodeInfo],
        netlist: str
    ) -> Tuple[str, str, float]:
        """识别无源滤波器"""
        # 简单 RC 滤波器
        if stats.resistors == 1 and stats.capacitors == 1:
            return TopologyType.FILTER.value, FilterSubType.LOWPASS.value, 0.6
        
        return TopologyType.FILTER.value, FilterSubType.UNKNOWN.value, 0.5
    
    def _is_differential_pair(
        self,
        stats: DeviceStats,
        nodes: Dict[str, NodeInfo],
        netlist: str
    ) -> bool:
        """检查是否为差分对"""
        # 检查是否有成对的晶体管
        if stats.mosfets >= 2:
            if stats.nmos_count >= 2 or stats.pmos_count >= 2:
                return True
        if stats.bjts >= 2:
            if stats.npn_count >= 2 or stats.pnp_count >= 2:
                return True
        
        # 检查是否有差分输入节点
        has_inp = any(n.is_input and 'p' in n.name.lower() for n in nodes.values())
        has_inn = any(n.is_input and 'n' in n.name.lower() for n in nodes.values())
        if has_inp and has_inn:
            return True
        
        return False
    
    def _is_ring_oscillator(
        self,
        stats: DeviceStats,
        nodes: Dict[str, NodeInfo],
        netlist: str
    ) -> bool:
        """检查是否为环形振荡器"""
        # 环形振荡器通常有奇数个反相器（3, 5, 7...）
        # 每个反相器需要 2 个 MOSFET（CMOS）或 1 个 BJT
        if stats.mosfets >= 6 and stats.mosfets % 2 == 0:
            # 可能是 CMOS 环形振荡器
            if stats.nmos_count == stats.pmos_count:
                return True
        
        return False
    
    def _is_comparator_circuit(self, netlist: str) -> bool:
        """检查是否为比较器电路"""
        netlist_lower = netlist.lower()
        comparator_keywords = ['comparator', 'comp', 'lm311', 'lm339', 'hysteresis']
        return any(kw in netlist_lower for kw in comparator_keywords)
    
    def _has_switching_elements(self, netlist: str) -> bool:
        """检查是否有开关元件"""
        netlist_lower = netlist.lower()
        switch_keywords = ['switch', 'pwm', 'pulse', 'sw_', 'mosfet_sw']
        return any(kw in netlist_lower for kw in switch_keywords)
    
    def _identify_single_mosfet_config(
        self,
        nodes: Dict[str, NodeInfo],
        netlist: str
    ) -> Tuple[str, str, float]:
        """识别单管 MOSFET 配置"""
        netlist_lower = netlist.lower()
        
        if 'common_source' in netlist_lower or 'cs_' in netlist_lower:
            return TopologyType.AMPLIFIER.value, AmplifierSubType.COMMON_SOURCE.value, 0.9
        if 'common_drain' in netlist_lower or 'source_follower' in netlist_lower:
            return TopologyType.AMPLIFIER.value, AmplifierSubType.COMMON_DRAIN.value, 0.9
        if 'common_gate' in netlist_lower:
            return TopologyType.AMPLIFIER.value, AmplifierSubType.COMMON_GATE.value, 0.9
        
        # 默认假设为共源
        return TopologyType.AMPLIFIER.value, AmplifierSubType.COMMON_SOURCE.value, 0.5
    
    def _identify_single_bjt_config(
        self,
        nodes: Dict[str, NodeInfo],
        netlist: str
    ) -> Tuple[str, str, float]:
        """识别单管 BJT 配置"""
        netlist_lower = netlist.lower()
        
        if 'common_emitter' in netlist_lower or 'ce_' in netlist_lower:
            return TopologyType.AMPLIFIER.value, AmplifierSubType.COMMON_EMITTER.value, 0.9
        if 'common_collector' in netlist_lower or 'emitter_follower' in netlist_lower:
            return TopologyType.AMPLIFIER.value, AmplifierSubType.COMMON_COLLECTOR.value, 0.9
        if 'common_base' in netlist_lower:
            return TopologyType.AMPLIFIER.value, AmplifierSubType.COMMON_BASE.value, 0.9
        
        # 默认假设为共射
        return TopologyType.AMPLIFIER.value, AmplifierSubType.COMMON_EMITTER.value, 0.5

    
    # ============================================================
    # 关键节点识别
    # ============================================================
    
    def _identify_critical_nodes(
        self,
        nodes: Dict[str, NodeInfo],
        topology_type: str
    ) -> List[str]:
        """识别关键节点"""
        critical = []
        
        # 输入输出节点始终是关键节点
        for name, info in nodes.items():
            if info.is_input or info.is_output:
                critical.append(name)
        
        # 根据拓扑类型添加特定关键节点
        if topology_type == TopologyType.AMPLIFIER.value:
            # 放大器：高阻抗节点、反馈节点
            for name, info in nodes.items():
                name_lower = name.lower()
                if any(kw in name_lower for kw in ['bias', 'fb', 'feedback', 'mirror']):
                    if name not in critical:
                        critical.append(name)
        
        elif topology_type == TopologyType.POWER.value:
            # 电源：开关节点、输出节点
            for name, info in nodes.items():
                name_lower = name.lower()
                if any(kw in name_lower for kw in ['sw', 'switch', 'lx', 'phase']):
                    if name not in critical:
                        critical.append(name)
        
        elif topology_type == TopologyType.OSCILLATOR.value:
            # 振荡器：振荡节点
            for name, info in nodes.items():
                name_lower = name.lower()
                if any(kw in name_lower for kw in ['osc', 'ring', 'tank']):
                    if name not in critical:
                        critical.append(name)
        
        return critical
    
    def _generate_summary(
        self,
        topology_type: str,
        sub_type: str,
        confidence: float
    ) -> str:
        """生成识别结果摘要"""
        type_names = {
            TopologyType.AMPLIFIER.value: "放大器",
            TopologyType.FILTER.value: "滤波器",
            TopologyType.POWER.value: "电源",
            TopologyType.OSCILLATOR.value: "振荡器",
            TopologyType.COMPARATOR.value: "比较器",
            TopologyType.CONVERTER.value: "数据转换器",
            TopologyType.UNKNOWN.value: "未知",
        }
        
        type_name = type_names.get(topology_type, "未知")
        
        if sub_type and sub_type != "unknown":
            return f"拓扑识别: {type_name} ({sub_type}) - 置信度: {confidence:.0%}"
        return f"拓扑识别: {type_name} - 置信度: {confidence:.0%}"


# ============================================================
# 模块导出
# ============================================================

__all__ = [
    "TopologyRecognizer",
    "TopologyType",
    "AmplifierSubType",
    "FilterSubType",
    "PowerSubType",
    "OscillatorSubType",
    "DeviceStats",
    "NodeInfo",
]
