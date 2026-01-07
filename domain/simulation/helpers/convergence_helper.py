# ConvergenceHelper - Simulation Convergence Diagnostic Tool
"""
仿真收敛诊断工具

职责：
- 诊断仿真收敛问题类型和原因
- 生成修复建议供 LLM 或用户参考
- 验证网表连通性
- 建议初始条件设置

设计原则：
- 仅负责诊断和建议生成，不执行自动修复
- 修复操作由 LLM 根据诊断结果决定如何处理
- 返回结构化的 ConvergenceDiagnosis 结果

使用示例：
    from domain.simulation.helpers.convergence_helper import convergence_helper
    
    # 诊断收敛问题
    diagnosis = convergence_helper.diagnose_convergence_issue(error_output)
    
    # 获取修复建议供 LLM 参考
    for fix in diagnosis.suggested_fixes:
        print(f"建议: {fix.description}")
"""

import logging
import re
from datetime import datetime
from typing import Dict, List, Optional, Set

from domain.simulation.models.analysis_result import (
    ConvergenceDiagnosis,
    SuggestedFix,
)


# ============================================================
# 常量定义
# ============================================================

# 收敛问题类型
ISSUE_DC_CONVERGENCE = "dc_convergence"
ISSUE_TRAN_CONVERGENCE = "tran_convergence"
ISSUE_FLOATING_NODE = "floating_node"
ISSUE_MODEL_PROBLEM = "model_problem"
ISSUE_UNKNOWN = "unknown"

# 严重程度
SEVERITY_LOW = "low"
SEVERITY_MEDIUM = "medium"
SEVERITY_HIGH = "high"
SEVERITY_CRITICAL = "critical"

# 修复操作类型（供 LLM 参考）
ACTION_ADD_RESISTOR = "add_resistor"
ACTION_ADJUST_PARAM = "adjust_param"
ACTION_ADD_IC = "add_ic"
ACTION_ADD_NODESET = "add_nodeset"
ACTION_REDUCE_TIMESTEP = "reduce_timestep"

# 错误模式匹配正则
_PATTERNS: Dict[str, List[re.Pattern]] = {
    "floating_node": [
        re.compile(r"(?:floating|no dc path|unconnected)\s*(?:node|to ground)", re.I),
        re.compile(r"node\s+(\w+)\s+(?:is\s+)?floating", re.I),
        re.compile(r"no\s+dc\s+path\s+to\s+ground\s+(?:for|from)\s+node\s+(\w+)", re.I),
    ],
    "dc_convergence": [
        re.compile(r"(?:dc|operating point)\s*(?:analysis)?\s*(?:did not|failed to)\s*converge", re.I),
        re.compile(r"no\s+convergence\s+in\s+dc", re.I),
        re.compile(r"singular\s+matrix", re.I),
        re.compile(r"gmin\s+stepping\s+failed", re.I),
    ],
    "tran_convergence": [
        re.compile(r"(?:transient|tran)\s*(?:analysis)?\s*(?:did not|failed to)\s*converge", re.I),
        re.compile(r"timestep\s+too\s+small", re.I),
        re.compile(r"time\s*=\s*([\d.e+-]+)\s*.*(?:convergence|iteration)", re.I),
        re.compile(r"internal\s+timestep\s+limit", re.I),
    ],
    "model_problem": [
        re.compile(r"model\s+(\w+)\s+(?:not found|undefined|unknown)", re.I),
        re.compile(r"(?:invalid|illegal)\s+model\s+parameter", re.I),
    ],
}

# 节点名提取正则
_NODE_PATTERNS = [
    re.compile(r"node\s+['\"]?(\w+)['\"]?", re.I),
    re.compile(r"at\s+node\s+['\"]?(\w+)['\"]?", re.I),
    re.compile(r"floating\s+node[:\s]+['\"]?(\w+)['\"]?", re.I),
]


# ============================================================
# ConvergenceHelper - 收敛诊断工具类
# ============================================================

class ConvergenceHelper:
    """
    仿真收敛诊断工具
    
    提供收敛问题诊断和修复建议生成功能。
    不执行自动修复，修复操作由 LLM 或用户决定。
    """
    
    def __init__(self):
        """初始化收敛诊断工具"""
        self._logger = logging.getLogger(__name__)
    
    def diagnose_convergence_issue(
        self,
        error_output: str,
        netlist: Optional[str] = None,
        file_path: Optional[str] = None
    ) -> ConvergenceDiagnosis:
        """
        诊断收敛问题
        
        分析仿真错误输出，识别问题类型、受影响节点，生成修复建议。
        
        Args:
            error_output: 仿真错误输出文本
            netlist: 网表内容（可选，用于更精确的诊断）
            file_path: 电路文件路径（可选）
            
        Returns:
            ConvergenceDiagnosis: 诊断结果
        """
        start_time = datetime.now()
        
        issue_type = self._identify_issue_type(error_output)
        affected_nodes = self._extract_affected_nodes(error_output, issue_type)
        severity = self._determine_severity(issue_type, affected_nodes)
        suggested_fixes = self._generate_fixes(issue_type, affected_nodes, netlist)
        summary = self._generate_summary(issue_type, severity, affected_nodes)
        
        duration = (datetime.now() - start_time).total_seconds()
        
        diagnosis = ConvergenceDiagnosis(
            analysis_type="convergence_diagnosis",
            timestamp=datetime.now().isoformat(),
            duration_seconds=duration,
            success=True,
            summary=summary,
            issue_type=issue_type,
            severity=severity,
            affected_nodes=affected_nodes,
            suggested_fixes=suggested_fixes,
            auto_fix_available=False,  # 不支持自动修复
        )
        
        self._publish_diagnosis_event(diagnosis, file_path)
        return diagnosis

    def suggest_initial_conditions(
        self,
        netlist: str,
        affected_nodes: Optional[List[str]] = None
    ) -> List[str]:
        """
        建议初始条件设置
        
        分析电路拓扑，识别需要初始条件的节点，生成 .ic 语句建议。
        
        Args:
            netlist: 网表内容
            affected_nodes: 受影响的节点列表（可选）
            
        Returns:
            List[str]: .ic 语句建议列表
        """
        suggestions = []
        nodes_to_init = set(affected_nodes) if affected_nodes else set()
        
        # 从网表中提取电源电压
        vdd = self._extract_supply_voltage(netlist)
        
        # 分析需要初始条件的节点
        if not nodes_to_init:
            nodes_to_init = self._find_nodes_needing_ic(netlist)
        
        for node in nodes_to_init:
            # 根据节点名称猜测合理的初始值
            init_value = self._estimate_initial_value(node, vdd)
            suggestions.append(f".ic V({node})={init_value}")
        
        return suggestions
    
    def validate_netlist_connectivity(self, netlist: str) -> List[str]:
        """
        验证网表连通性
        
        检查电路中是否存在潜在的连通性问题。
        
        Args:
            netlist: 网表内容
            
        Returns:
            List[str]: 问题描述列表（空列表表示无问题）
        """
        issues = []
        
        # 提取所有节点
        all_nodes = self._extract_all_nodes(netlist)
        
        # 检查是否有地节点
        ground_nodes = {"0", "gnd", "ground", "vss"}
        has_ground = bool(all_nodes & ground_nodes)
        if not has_ground:
            issues.append("电路中未找到地节点（0/gnd/ground/vss）")
        
        # 检查电源连接
        if not self._has_power_source(netlist):
            issues.append("电路中未找到电源（V 或 I 源）")
        
        # 检查 .include 文件引用
        missing_includes = self._check_include_files(netlist)
        for inc in missing_includes:
            issues.append(f"引用的文件可能不存在: {inc}")
        
        return issues

    def get_convergence_param_suggestions(
        self,
        issue_type: str,
        current_params: Optional[Dict[str, float]] = None
    ) -> Dict[str, float]:
        """
        获取收敛参数调整建议
        
        根据问题类型建议调整的仿真参数值。
        
        Args:
            issue_type: 问题类型
            current_params: 当前参数值（可选）
            
        Returns:
            Dict[str, float]: 建议的参数值
        """
        suggestions = {}
        
        if issue_type == ISSUE_DC_CONVERGENCE:
            # DC 收敛问题：放宽容差
            suggestions["gmin"] = 1e-9  # 增大最小电导
            suggestions["reltol"] = 1e-2  # 放宽相对容差
            suggestions["abstol"] = 1e-9  # 放宽绝对容差
            suggestions["itl1"] = 200  # 增加 DC 迭代次数
            
        elif issue_type == ISSUE_TRAN_CONVERGENCE:
            # 瞬态收敛问题：减小步长
            suggestions["reltol"] = 1e-2
            suggestions["itl4"] = 50  # 增加瞬态迭代次数
            # 建议减小 max_step（具体值需根据仿真时间确定）
            
        elif issue_type == ISSUE_FLOATING_NODE:
            # 浮空节点：增大 gmin
            suggestions["gmin"] = 1e-9
        
        return suggestions
    
    # ============================================================
    # 内部方法
    # ============================================================
    
    def _identify_issue_type(self, error_output: str) -> str:
        """识别问题类型"""
        error_lower = error_output.lower()
        
        # 按优先级检查各类问题
        for issue_type, patterns in _PATTERNS.items():
            for pattern in patterns:
                if pattern.search(error_output):
                    return issue_type
        
        # 额外的关键词检查
        if "floating" in error_lower or "no dc path" in error_lower:
            return ISSUE_FLOATING_NODE
        if "convergence" in error_lower:
            if "dc" in error_lower or "operating" in error_lower:
                return ISSUE_DC_CONVERGENCE
            if "tran" in error_lower or "timestep" in error_lower:
                return ISSUE_TRAN_CONVERGENCE
        if "model" in error_lower and ("not found" in error_lower or "unknown" in error_lower):
            return ISSUE_MODEL_PROBLEM
        
        return ISSUE_UNKNOWN

    def _extract_affected_nodes(self, error_output: str, issue_type: str) -> List[str]:
        """提取受影响的节点"""
        nodes: Set[str] = set()
        
        for pattern in _NODE_PATTERNS:
            for match in pattern.finditer(error_output):
                node = match.group(1)
                # 过滤掉常见的非节点词
                if node.lower() not in {"the", "a", "an", "is", "at", "to", "from"}:
                    nodes.add(node)
        
        # 针对特定问题类型的额外提取
        if issue_type == ISSUE_FLOATING_NODE:
            # 尝试提取浮空节点名
            float_pattern = re.compile(r"(?:floating|no dc path)[^:]*:\s*(\w+)", re.I)
            for match in float_pattern.finditer(error_output):
                nodes.add(match.group(1))
        
        return list(nodes)
    
    def _determine_severity(self, issue_type: str, affected_nodes: List[str]) -> str:
        """确定严重程度"""
        if issue_type == ISSUE_FLOATING_NODE:
            return SEVERITY_HIGH if len(affected_nodes) > 3 else SEVERITY_MEDIUM
        elif issue_type == ISSUE_DC_CONVERGENCE:
            return SEVERITY_HIGH
        elif issue_type == ISSUE_TRAN_CONVERGENCE:
            return SEVERITY_MEDIUM
        elif issue_type == ISSUE_MODEL_PROBLEM:
            return SEVERITY_HIGH
        return SEVERITY_MEDIUM
    
    def _generate_fixes(
        self,
        issue_type: str,
        affected_nodes: List[str],
        netlist: Optional[str]
    ) -> List[SuggestedFix]:
        """生成修复建议"""
        fixes = []
        
        if issue_type == ISSUE_FLOATING_NODE:
            fixes.extend(self._fixes_for_floating_node(affected_nodes))
        elif issue_type == ISSUE_DC_CONVERGENCE:
            fixes.extend(self._fixes_for_dc_convergence(affected_nodes, netlist))
        elif issue_type == ISSUE_TRAN_CONVERGENCE:
            fixes.extend(self._fixes_for_tran_convergence())
        elif issue_type == ISSUE_MODEL_PROBLEM:
            fixes.extend(self._fixes_for_model_problem())
        else:
            fixes.append(SuggestedFix(
                description="检查电路连接和仿真配置",
                action_type="check_circuit",
                parameters={},
            ))
        
        return fixes

    def _fixes_for_floating_node(self, affected_nodes: List[str]) -> List[SuggestedFix]:
        """浮空节点的修复建议"""
        fixes = []
        
        for node in affected_nodes:
            fixes.append(SuggestedFix(
                description=f"在节点 {node} 和地之间添加高阻电阻（如 1GΩ）",
                action_type=ACTION_ADD_RESISTOR,
                parameters={
                    "node": node,
                    "ground": "0",
                    "value": "1G",
                    "spice_line": f"R_leak_{node} {node} 0 1G",
                },
            ))
        
        if affected_nodes:
            fixes.append(SuggestedFix(
                description="检查电路连接，确保所有节点都有到地的直流路径",
                action_type="check_circuit",
                parameters={"nodes": affected_nodes},
            ))
        
        return fixes
    
    def _fixes_for_dc_convergence(
        self,
        affected_nodes: List[str],
        netlist: Optional[str]
    ) -> List[SuggestedFix]:
        """DC 收敛问题的修复建议"""
        fixes = []
        
        # 建议调整收敛参数
        fixes.append(SuggestedFix(
            description="放宽收敛参数：增大 gmin、reltol",
            action_type=ACTION_ADJUST_PARAM,
            parameters={
                "gmin": 1e-9,
                "reltol": 1e-2,
                "spice_options": ".options gmin=1e-9 reltol=1e-2",
            },
        ))
        
        # 建议添加初始条件
        if affected_nodes:
            ic_lines = [f"V({node})=0" for node in affected_nodes[:5]]
            fixes.append(SuggestedFix(
                description="为关键节点添加初始条件",
                action_type=ACTION_ADD_IC,
                parameters={
                    "nodes": affected_nodes[:5],
                    "spice_line": f".ic {' '.join(ic_lines)}",
                },
            ))
        
        # 建议使用 nodeset
        fixes.append(SuggestedFix(
            description="使用 .nodeset 设置初始猜测值",
            action_type=ACTION_ADD_NODESET,
            parameters={
                "description": "为难以收敛的节点设置初始猜测值",
            },
        ))
        
        return fixes

    def _fixes_for_tran_convergence(self) -> List[SuggestedFix]:
        """瞬态收敛问题的修复建议"""
        return [
            SuggestedFix(
                description="减小最大时间步长",
                action_type=ACTION_REDUCE_TIMESTEP,
                parameters={
                    "description": "在 .tran 语句中添加 max_step 参数",
                    "example": ".tran 1n 10u 0 10n",
                },
            ),
            SuggestedFix(
                description="放宽瞬态分析容差",
                action_type=ACTION_ADJUST_PARAM,
                parameters={
                    "reltol": 1e-2,
                    "itl4": 50,
                    "spice_options": ".options reltol=1e-2 itl4=50",
                },
            ),
            SuggestedFix(
                description="使用初始条件启动瞬态分析",
                action_type=ACTION_ADD_IC,
                parameters={
                    "description": "添加 .ic 语句或在 .tran 中使用 uic",
                    "example": ".tran 1n 10u uic",
                },
            ),
        ]
    
    def _fixes_for_model_problem(self) -> List[SuggestedFix]:
        """模型问题的修复建议"""
        return [
            SuggestedFix(
                description="检查模型文件路径是否正确",
                action_type="check_model",
                parameters={"description": "确保 .include 或 .lib 语句指向正确的模型文件"},
            ),
            SuggestedFix(
                description="使用简化的内置模型替代",
                action_type="use_builtin_model",
                parameters={"description": "对于缺失的复杂模型，可尝试使用 ngspice 内置模型"},
            ),
        ]
    
    def _generate_summary(
        self,
        issue_type: str,
        severity: str,
        affected_nodes: List[str]
    ) -> str:
        """生成诊断摘要"""
        type_names = {
            ISSUE_DC_CONVERGENCE: "DC 工作点收敛失败",
            ISSUE_TRAN_CONVERGENCE: "瞬态分析收敛失败",
            ISSUE_FLOATING_NODE: "浮空节点",
            ISSUE_MODEL_PROBLEM: "模型问题",
            ISSUE_UNKNOWN: "未知收敛问题",
        }
        
        type_name = type_names.get(issue_type, "收敛问题")
        node_info = f"，涉及节点: {', '.join(affected_nodes[:3])}" if affected_nodes else ""
        if len(affected_nodes) > 3:
            node_info += f" 等 {len(affected_nodes)} 个"
        
        return f"{type_name} ({severity}){node_info}"

    def _publish_diagnosis_event(
        self,
        diagnosis: ConvergenceDiagnosis,
        file_path: Optional[str]
    ) -> None:
        """发布诊断完成事件"""
        try:
            from shared.event_bus import event_bus
            from shared.event_types import EVENT_CONVERGENCE_DIAGNOSED
            
            event_bus.publish(EVENT_CONVERGENCE_DIAGNOSED, {
                "diagnosis": diagnosis,
                "file_path": file_path,
                "issue_type": diagnosis.issue_type,
                "severity": diagnosis.severity,
                "auto_fix_available": diagnosis.auto_fix_available,
            })
        except ImportError:
            self._logger.debug("EventBus 不可用，跳过事件发布")
    
    def _extract_supply_voltage(self, netlist: str) -> float:
        """从网表中提取电源电压"""
        # 匹配 Vdd/Vcc 电源定义
        patterns = [
            re.compile(r"V(?:dd|cc|supply)\s+\w+\s+\w+\s+([\d.]+)", re.I),
            re.compile(r"\.param\s+(?:vdd|vcc)\s*=\s*([\d.]+)", re.I),
        ]
        
        for pattern in patterns:
            match = pattern.search(netlist)
            if match:
                try:
                    return float(match.group(1))
                except ValueError:
                    pass
        
        return 3.3  # 默认电源电压
    
    def _find_nodes_needing_ic(self, netlist: str) -> Set[str]:
        """找出需要初始条件的节点"""
        nodes = set()
        
        # 查找电容连接的节点（可能需要初始条件）
        cap_pattern = re.compile(r"C\w+\s+(\w+)\s+(\w+)", re.I)
        for match in cap_pattern.finditer(netlist):
            node1, node2 = match.group(1), match.group(2)
            if node1.lower() not in {"0", "gnd", "ground"}:
                nodes.add(node1)
            if node2.lower() not in {"0", "gnd", "ground"}:
                nodes.add(node2)
        
        return nodes

    def _estimate_initial_value(self, node: str, vdd: float) -> float:
        """估算节点的初始值"""
        node_lower = node.lower()
        
        # 根据节点名称猜测
        if "vdd" in node_lower or "vcc" in node_lower or "supply" in node_lower:
            return vdd
        if "vss" in node_lower or "gnd" in node_lower:
            return 0.0
        if "out" in node_lower:
            return vdd / 2  # 输出节点通常在中点
        if "bias" in node_lower:
            return vdd / 2
        
        return 0.0  # 默认初始值
    
    def _extract_all_nodes(self, netlist: str) -> Set[str]:
        """提取网表中的所有节点"""
        nodes = set()
        
        # 匹配元件行中的节点（包括电压源 V、电流源 I、电阻 R 等）
        # 允许行首有空格
        element_pattern = re.compile(r"^\s*[RVCLMQJDXIE]\w*\s+(.+)$", re.I | re.M)
        for match in element_pattern.finditer(netlist):
            parts = match.group(1).split()
            for part in parts:
                # 节点名通常是字母数字组合，或者是 "0"
                if re.match(r"^[a-zA-Z_]\w*$", part) or part == "0":
                    nodes.add(part.lower())
        
        return nodes
    
    def _has_power_source(self, netlist: str) -> bool:
        """检查是否有电源"""
        # 允许行首有空格
        source_pattern = re.compile(r"^\s*[VI]\w+\s+", re.I | re.M)
        return bool(source_pattern.search(netlist))
    
    def _check_include_files(self, netlist: str) -> List[str]:
        """检查 .include 文件引用"""
        missing = []
        include_pattern = re.compile(r"\.include\s+['\"]?([^'\"]+)['\"]?", re.I)
        
        for match in include_pattern.finditer(netlist):
            file_path = match.group(1)
            # 这里只返回文件名，实际检查需要在调用方进行
            missing.append(file_path)
        
        return []  # 返回空列表，实际文件检查由调用方负责


# ============================================================
# 模块级单例
# ============================================================

convergence_helper = ConvergenceHelper()


# ============================================================
# 模块导出
# ============================================================

__all__ = [
    "ConvergenceHelper",
    "convergence_helper",
    # 常量
    "ISSUE_DC_CONVERGENCE",
    "ISSUE_TRAN_CONVERGENCE",
    "ISSUE_FLOATING_NODE",
    "ISSUE_MODEL_PROBLEM",
    "ISSUE_UNKNOWN",
    "SEVERITY_LOW",
    "SEVERITY_MEDIUM",
    "SEVERITY_HIGH",
    "SEVERITY_CRITICAL",
]
