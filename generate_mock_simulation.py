# Generate Mock Simulation Result
"""
生成模拟仿真结果

用于预览仿真面板的展示效果。
运行此脚本后，打开软件并打开 Test 项目，即可在仿真面板中看到模拟数据。

使用方法：
    cd circuit_design_ai
    python generate_mock_simulation.py
"""

import json
import os
import sys
from datetime import datetime
from pathlib import Path
import math

# 添加项目根目录到路径
sys.path.insert(0, str(Path(__file__).parent))


def generate_ac_analysis_data():
    """生成 AC 分析的模拟数据"""
    import numpy as np
    
    # 频率范围：1Hz 到 100MHz
    frequency = np.logspace(0, 8, 500)  # 500 个点
    
    # 模拟一个运放的频率响应
    # 低频增益 60dB，带宽 10kHz，单位增益带宽 10MHz
    f_3db = 10e3  # 3dB 带宽
    gain_dc = 1000  # 低频增益（线性）
    
    # 一阶低通响应
    gain_linear = gain_dc / np.sqrt(1 + (frequency / f_3db) ** 2)
    gain_db = 20 * np.log10(gain_linear)
    
    # 相位响应
    phase = -np.arctan(frequency / f_3db) * 180 / np.pi
    
    # 输出电压（假设输入 1mV）
    v_out_mag = gain_linear * 1e-3
    
    return {
        "frequency": frequency.tolist(),
        "time": None,
        "signals": {
            "V(out)": v_out_mag.tolist(),
            "gain_db": gain_db.tolist(),
            "phase_deg": phase.tolist(),
        }
    }


def generate_transient_data():
    """生成瞬态分析的模拟数据"""
    import numpy as np
    
    # 时间范围：0 到 1ms
    time = np.linspace(0, 1e-3, 1000)
    
    # 模拟阶跃响应
    tau = 50e-6  # 时间常数 50us
    v_final = 2.5  # 最终电压
    v_out = v_final * (1 - np.exp(-time / tau))
    
    # 添加一些过冲
    overshoot = 0.1 * v_final * np.exp(-time / (tau * 2)) * np.sin(2 * np.pi * 20e3 * time)
    v_out = v_out + overshoot
    
    # 输入阶跃信号
    v_in = np.where(time > 10e-6, 1.0, 0.0)
    
    return {
        "frequency": None,
        "time": time.tolist(),
        "signals": {
            "V(out)": v_out.tolist(),
            "V(in)": v_in.tolist(),
        }
    }


def generate_metrics():
    """生成模拟的性能指标"""
    return {
        "gain": {
            "name": "gain",
            "display_name": "增益",
            "value": 60.2,
            "unit": "dB",
            "target": 60.0,
            "target_type": "min",
            "is_met": True,
            "category": "amplifier",
            "confidence": 1.0,
            "measurement_condition": "f=1kHz",
        },
        "bandwidth": {
            "name": "bandwidth",
            "display_name": "带宽",
            "value": 10.5e3,
            "unit": "Hz",
            "target": 10e3,
            "target_type": "min",
            "is_met": True,
            "category": "amplifier",
            "confidence": 1.0,
            "measurement_condition": "-3dB",
        },
        "gbw": {
            "name": "gbw",
            "display_name": "增益带宽积",
            "value": 10.8e6,
            "unit": "Hz",
            "target": 10e6,
            "target_type": "min",
            "is_met": True,
            "category": "amplifier",
            "confidence": 1.0,
        },
        "phase_margin": {
            "name": "phase_margin",
            "display_name": "相位裕度",
            "value": 65.3,
            "unit": "°",
            "target": 60.0,
            "target_type": "min",
            "is_met": True,
            "category": "amplifier",
            "confidence": 0.95,
        },
        "slew_rate": {
            "name": "slew_rate",
            "display_name": "压摆率",
            "value": 2.5e6,
            "unit": "V/s",
            "target": 2e6,
            "target_type": "min",
            "is_met": True,
            "category": "transient",
            "confidence": 1.0,
        },
        "rise_time": {
            "name": "rise_time",
            "display_name": "上升时间",
            "value": 35e-6,
            "unit": "s",
            "target": 50e-6,
            "target_type": "max",
            "is_met": True,
            "category": "transient",
            "confidence": 1.0,
            "measurement_condition": "10%-90%",
        },
        "overshoot": {
            "name": "overshoot",
            "display_name": "过冲",
            "value": 8.5,
            "unit": "%",
            "target": 10.0,
            "target_type": "max",
            "is_met": True,
            "category": "transient",
            "confidence": 1.0,
        },
        "power_consumption": {
            "name": "power_consumption",
            "display_name": "功耗",
            "value": 2.8e-3,
            "unit": "W",
            "target": 5e-3,
            "target_type": "max",
            "is_met": True,
            "category": "power",
            "confidence": 1.0,
        },
        "input_noise": {
            "name": "input_noise",
            "display_name": "输入噪声",
            "value": 15e-9,
            "unit": "V/√Hz",
            "target": 20e-9,
            "target_type": "max",
            "is_met": True,
            "category": "noise",
            "confidence": 0.9,
            "measurement_condition": "f=1kHz",
        },
        "thd": {
            "name": "thd",
            "display_name": "总谐波失真",
            "value": 0.05,
            "unit": "%",
            "target": 0.1,
            "target_type": "max",
            "is_met": True,
            "category": "distortion",
            "confidence": 1.0,
            "measurement_condition": "f=1kHz, Vout=1Vpp",
        },
    }


def create_simulation_result(analysis_type: str = "ac"):
    """创建完整的仿真结果"""
    
    if analysis_type == "ac":
        data = generate_ac_analysis_data()
    else:
        data = generate_transient_data()
    
    result = {
        "id": f"sim_{datetime.now().strftime('%Y%m%d_%H%M%S')}_mock",
        "executor": "spice",
        "file_path": "inverting_amplifier.cir",
        "analysis_type": analysis_type,
        "success": True,
        "data": data,
        "metrics": generate_metrics(),
        "error": None,
        "raw_output": "ngspice simulation completed successfully.\nTotal time: 0.5s",
        "timestamp": datetime.now().isoformat(),
        "duration_seconds": 0.52,
        "version": 1,
        "session_id": datetime.now().strftime("%Y%m%d_%H%M%S"),
    }
    
    return result


def save_to_project(project_path: str, result: dict):
    """保存仿真结果到项目目录"""
    
    # 使用统一路径常量
    try:
        from shared.constants.paths import SIM_RESULTS_DIR
        sim_results_dir = Path(project_path) / SIM_RESULTS_DIR
    except ImportError:
        # 回退到硬编码路径
        sim_results_dir = Path(project_path) / ".circuit_ai" / "sim_results"
    
    sim_results_dir.mkdir(parents=True, exist_ok=True)
    
    # 保存结果文件
    result_file = sim_results_dir / f"{result['id']}.json"
    
    with open(result_file, "w", encoding="utf-8") as f:
        json.dump(result, f, indent=2, ensure_ascii=False)
    
    print(f"✓ 仿真结果已保存到: {result_file}")
    return result_file


def main():
    """主函数"""
    print("=" * 60)
    print("生成模拟仿真结果")
    print("=" * 60)
    
    # 确定项目路径（使用 Test 目录）
    script_dir = Path(__file__).parent
    test_project = script_dir.parent / "Test"
    
    if not test_project.exists():
        print(f"✗ 测试项目目录不存在: {test_project}")
        print("  请先创建 Test 目录或修改脚本中的项目路径")
        return
    
    print(f"项目路径: {test_project}")
    print()
    
    # 生成 AC 分析结果
    print("生成 AC 分析结果...")
    ac_result = create_simulation_result("ac")
    save_to_project(str(test_project), ac_result)
    
    # 生成瞬态分析结果
    print("\n生成瞬态分析结果...")
    tran_result = create_simulation_result("tran")
    tran_result["id"] = f"sim_{datetime.now().strftime('%Y%m%d_%H%M%S')}_tran_mock"
    save_to_project(str(test_project), tran_result)
    
    print()
    print("=" * 60)
    print("完成！")
    print()
    print("使用方法：")
    print("1. 启动软件: python main.py")
    print("2. 打开 Test 项目文件夹")
    print("3. 查看下方仿真面板中的模拟数据")
    print("=" * 60)


if __name__ == "__main__":
    main()
