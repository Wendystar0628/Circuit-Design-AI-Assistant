"""
测试完整的仿真链路

验证从 SimulationService 到结果保存的完整流程
"""

import sys
import os

# 确保可以导入项目模块
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# 首先配置 ngspice
from infrastructure.utils.ngspice_config import configure_ngspice, get_ngspice_info

print("=" * 60)
print("Step 1: 配置 ngspice")
print("=" * 60)

result = configure_ngspice()
print(f"配置结果: {result}")

if not result:
    print("ngspice 配置失败，退出测试")
    sys.exit(1)

print("\n" + "=" * 60)
print("Step 2: 初始化 ExecutorRegistry")
print("=" * 60)

try:
    from domain.simulation.executor import (
        executor_registry,
        SpiceExecutor,
    )
    
    # 注册 SpiceExecutor
    spice_executor = SpiceExecutor()
    executor_registry.register(spice_executor)
    
    registry_info = executor_registry.get_registry_info()
    print(f"已注册 {registry_info['executor_count']} 个执行器")
    for e in registry_info['executors']:
        print(f"  - {e['name']}: {e['supported_extensions']}")
    
except Exception as e:
    print(f"错误: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)

print("\n" + "=" * 60)
print("Step 3: 测试 SimulationService.run_simulation")
print("=" * 60)

try:
    from domain.services.simulation_service import SimulationService
    
    service = SimulationService()
    
    # 使用 Test 目录作为项目根目录
    project_root = os.path.abspath("../Test")
    file_path = os.path.join(project_root, "rc_test.cir")
    
    print(f"项目根目录: {project_root}")
    print(f"电路文件: {file_path}")
    print(f"文件存在: {os.path.exists(file_path)}")
    
    # 执行仿真
    print("\n执行仿真...")
    result = service.run_simulation(
        file_path=file_path,
        analysis_config={
            "analysis_type": "ac",
            "start_freq": 1.0,
            "stop_freq": 1e6,
            "points_per_decade": 20,
        },
        project_root=project_root,
    )
    
    print(f"\n仿真结果:")
    print(f"  success: {result.success}")
    print(f"  duration: {result.duration_seconds:.3f}s")
    print(f"  analysis_type: {result.analysis_type}")
    print(f"  file_path: {result.file_path}")
    
    if result.success:
        print(f"  signals: {list(result.data.signals.keys())}")
        if result.data.frequency is not None:
            print(f"  frequency points: {len(result.data.frequency)}")
            print(f"  frequency range: {result.data.frequency[0]:.2f} - {result.data.frequency[-1]:.2e} Hz")
    else:
        print(f"  error: {result.error}")
        if result.raw_output:
            print(f"  raw_output (last 500 chars): {result.raw_output[-500:]}")
    
    # 检查结果文件是否保存
    print("\n检查结果文件...")
    results_dir = os.path.join(project_root, ".circuit_ai", "sim_results")
    if os.path.exists(results_dir):
        files = os.listdir(results_dir)
        print(f"  结果目录存在: {results_dir}")
        print(f"  文件数量: {len(files)}")
        for f in files[-3:]:  # 显示最后 3 个文件
            print(f"    - {f}")
    else:
        print(f"  结果目录不存在: {results_dir}")
    
except Exception as e:
    print(f"错误: {e}")
    import traceback
    traceback.print_exc()

print("\n" + "=" * 60)
print("测试完成")
print("=" * 60)
