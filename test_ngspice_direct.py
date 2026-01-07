"""
测试 ngspice 直接调用（不使用 PySpice）

验证 ngspice_shared.py 和 spice_executor.py 的实现是否正确
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

info = get_ngspice_info()
for key, value in info.items():
    print(f"  {key}: {value}")

if not result:
    print("ngspice 配置失败，退出测试")
    sys.exit(1)

print("\n" + "=" * 60)
print("Step 2: 测试 NgSpiceWrapper")
print("=" * 60)

try:
    from domain.simulation.executor.ngspice_shared import NgSpiceWrapper
    
    ngspice = NgSpiceWrapper()
    print(f"NgSpiceWrapper 初始化成功")
    print(f"  initialized: {ngspice.initialized}")
    print(f"  dll_path: {ngspice.dll_path}")
    
    # 测试加载简单网表
    netlist = [
        ".title RC Test",
        "VIN in 0 DC 0 AC 1",
        "R1 in out 1k",
        "C1 out 0 100n",
        ".ac dec 10 1 1meg",
        ".end"
    ]
    
    print("\n加载网表...")
    if ngspice.load_netlist(netlist):
        print("网表加载成功")
        
        print("\n执行仿真...")
        if ngspice.run():
            print("仿真执行成功")
            
            # 获取结果
            plot = ngspice.get_current_plot()
            print(f"\n当前 plot: {plot}")
            
            vectors = ngspice.get_all_vectors()
            print(f"向量列表: {vectors}")
            
            # 获取频率数据
            freq = ngspice.get_vector_data("frequency")
            if freq is not None:
                print(f"\n频率数据: {len(freq)} 点")
                print(f"  范围: {freq[0]:.2f} Hz - {freq[-1]:.2e} Hz")
            
            # 获取输出电压
            vout = ngspice.get_complex_vector_data("v(out)")
            if vout is not None:
                import numpy as np
                mag = np.abs(vout)
                print(f"\n输出电压幅度:")
                print(f"  DC (1Hz): {mag[0]:.4f}")
                print(f"  截止频率附近: {mag[len(mag)//2]:.4f}")
        else:
            print("仿真执行失败")
            print(f"输出: {ngspice.get_stdout()}")
    else:
        print("网表加载失败")
        print(f"输出: {ngspice.get_stdout()}")
        
except Exception as e:
    print(f"错误: {e}")
    import traceback
    traceback.print_exc()

print("\n" + "=" * 60)
print("Step 3: 测试 SpiceExecutor")
print("=" * 60)

try:
    from domain.simulation.executor.spice_executor import SpiceExecutor
    
    executor = SpiceExecutor()
    print(f"SpiceExecutor 初始化完成")
    print(f"  is_available: {executor.is_available()}")
    print(f"  name: {executor.get_name()}")
    print(f"  supported_extensions: {executor.get_supported_extensions()}")
    
    if executor.is_available():
        # 测试执行仿真（使用 Test 目录下的文件）
        test_file = "../Test/rc_lowpass_simple.cir"
        if os.path.exists(test_file):
            print(f"\n执行仿真: {test_file}")
            result = executor.execute(test_file, {
                "analysis_type": "ac",
                "start_freq": 1.0,
                "stop_freq": 1e6,
                "points_per_decade": 10,
            })
            
            print(f"仿真结果:")
            print(f"  success: {result.success}")
            print(f"  duration: {result.duration_seconds:.3f}s")
            
            if result.success:
                print(f"  signals: {list(result.data.signals.keys())}")
                if result.data.frequency is not None:
                    print(f"  frequency points: {len(result.data.frequency)}")
            else:
                print(f"  error: {result.error}")
        else:
            print(f"测试文件不存在: {test_file}")
    else:
        print("SpiceExecutor 不可用")
        
except Exception as e:
    print(f"错误: {e}")
    import traceback
    traceback.print_exc()

print("\n" + "=" * 60)
print("测试完成")
print("=" * 60)
