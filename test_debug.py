from domain.simulation.helpers.convergence_helper import ConvergenceHelper

helper = ConvergenceHelper()
netlist = """
* Test circuit
Vdd vdd 0 3.3
R1 vdd out 1k
"""

# 测试节点提取
nodes = helper._extract_all_nodes(netlist)
print(f"Nodes: {nodes}")

# 测试地节点检查
ground_nodes = {"0", "gnd", "ground", "vss"}
has_ground = bool(nodes & ground_nodes)
print(f"Has ground: {has_ground}")

# 测试完整验证
issues = helper.validate_netlist_connectivity(netlist)
print(f"Issues: {issues}")
