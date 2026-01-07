import re

# 测试用例中的网表（有前导空格）
netlist = """
        * Test circuit
        Vdd vdd 0 3.3
        R1 vdd out 1k
        """

print(f"Netlist repr: {repr(netlist[:80])}")

nodes = set()
element_pattern = re.compile(r'^[RVCLMQJDXIE]\w*\s+(.+)$', re.I | re.M)

print("=== 匹配的行 ===")
for match in element_pattern.finditer(netlist):
    line = match.group(0)
    rest = match.group(1)
    parts = rest.split()
    print(f"Line: '{line}'")
    print(f"Rest: '{rest}'")
    print(f"Parts: {parts}")
    
    for part in parts:
        if re.match(r'^[a-zA-Z_]\w*$', part) or part == '0':
            nodes.add(part.lower())
            print(f"  Added node: {part}")
        else:
            print(f"  Skipped: {part}")
    print()

print(f"=== 最终节点集合 ===")
print(f"Nodes: {nodes}")

ground_nodes = {'0', 'gnd', 'ground', 'vss'}
has_ground = bool(nodes & ground_nodes)
print(f"Has ground: {has_ground}")
print(f"Intersection: {nodes & ground_nodes}")
