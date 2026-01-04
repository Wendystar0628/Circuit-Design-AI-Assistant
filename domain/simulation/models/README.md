# Simulation Models Module

仿真数据模型模块，定义标准化的仿真结果数据结构。

## 模块概览

- `SimulationData`: 仿真数据容器，存储频率、时间和信号数据
- `SimulationResult`: 标准化仿真结果，包含执行信息、数据、指标和错误信息

## 使用示例

### 创建成功的仿真结果

```python
import numpy as np
from circuit_design_ai.domain.simulation.models import (
    SimulationData,
    create_success_result,
)

# 创建仿真数据
data = SimulationData(
    frequency=np.array([1e3, 1e4, 1e5, 1e6]),
    signals={
        "V(out)": np.array([0.1, 1.0, 10.0, 5.0]),
        "V(in)": np.array([1.0, 1.0, 1.0, 1.0]),
    }
)

# 创建成功结果
result = create_success_result(
    executor="spice",
    file_path="amplifier.cir",
    analysis_type="ac",
    data=data,
    metrics={
        "gain": "20dB",
        "bandwidth": "10MHz",
        "phase_margin": "45°"
    },
    duration_seconds=2.5,
    version=1
)

print(result.get_summary())
# 输出: SimulationResult(executor=spice, file=amplifier.cir, type=ac, status=成功, duration=2.50s, version=1)
```

### 创建失败的仿真结果

```python
from circuit_design_ai.domain.simulation.models import create_error_result

# 创建失败结果
result = create_error_result(
    executor="spice",
    file_path="amplifier.cir",
    analysis_type="ac",
    error="Convergence failed at DC operating point",
    raw_output="Error: no convergence in 100 iterations",
    duration_seconds=1.0,
    version=1
)

if not result.is_successful():
    print(f"仿真失败: {result.error}")
```

### 序列化和反序列化

```python
import json
from circuit_design_ai.domain.simulation.models import SimulationResult

# 序列化为字典
result_dict = result.to_dict()

# 保存到 JSON 文件
with open(".circuit_ai/sim_results/run_001.json", "w") as f:
    json.dump(result_dict, f, indent=2)

# 从 JSON 文件加载
with open(".circuit_ai/sim_results/run_001.json", "r") as f:
    loaded_dict = json.load(f)

# 反序列化
restored_result = SimulationResult.from_dict(loaded_dict)
```

### 查询信号数据

```python
# 获取指定信号
output_signal = result.get_signal("V(out)")
if output_signal is not None:
    print(f"输出信号: {output_signal}")

# 检查信号是否存在
if result.data.has_signal("V(out)"):
    print("包含输出信号")

# 获取所有信号名称
signal_names = result.data.get_signal_names()
print(f"信号列表: {signal_names}")
```

### 查询性能指标

```python
# 检查是否包含指标
if result.has_metrics():
    # 获取指定指标
    gain = result.get_metric("gain")
    bandwidth = result.get_metric("bandwidth")
    
    # 获取不存在的指标（返回默认值）
    phase_margin = result.get_metric("phase_margin", "N/A")
    
    print(f"增益: {gain}, 带宽: {bandwidth}, 相位裕度: {phase_margin}")
```

### 检查数据新鲜度

```python
# 检查数据是否在 5 分钟内
if result.is_fresh(max_age_seconds=300):
    print("使用缓存的仿真结果")
else:
    print("数据过期，需要重新仿真")

# 获取数据年龄
age = result.get_age_seconds()
print(f"数据年龄: {age:.1f} 秒")
```

## 数据结构

### SimulationData

```python
@dataclass
class SimulationData:
    frequency: Optional[np.ndarray] = None  # AC 分析频率点
    time: Optional[np.ndarray] = None       # 瞬态分析时间点
    signals: Dict[str, np.ndarray] = {}     # 信号数据字典
```

### SimulationResult

```python
@dataclass
class SimulationResult:
    executor: str                           # 执行器名称
    file_path: str                          # 仿真文件路径
    analysis_type: str                      # 分析类型
    success: bool                           # 是否成功
    data: Optional[SimulationData] = None   # 仿真数据
    metrics: Optional[Dict] = None          # 性能指标
    error: Optional[Any] = None             # 错误信息
    raw_output: Optional[str] = None        # 原始输出
    timestamp: str = ...                    # ISO 格式时间戳
    duration_seconds: float = 0.0           # 执行耗时
    version: int = 1                        # 版本号
```

## 设计原则

1. **类型安全**: 使用 dataclass 和类型注解确保类型安全
2. **序列化支持**: 提供 `to_dict()` 和 `from_dict()` 方法支持 JSON 序列化
3. **numpy 兼容**: 正确处理 numpy 数组的序列化和反序列化
4. **数据新鲜度**: 支持基于时间戳的缓存验证
5. **版本控制**: 使用版本号追踪仿真结果的迭代

## 与其他模块的集成

- **SimulationService**: 使用 `SimulationResult` 作为返回类型
- **SpiceExecutor**: 生成 `SimulationResult` 对象
- **MetricsExtractor**: 从 `SimulationData` 提取性能指标
- **ChartGenerator**: 从 `SimulationData` 生成图表
- **GraphState**: 存储 `sim_result_path` 指向序列化的结果文件

## 注意事项

1. **numpy 数组序列化**: 序列化时自动转换为列表，反序列化时恢复为 numpy 数组
2. **时间戳格式**: 使用 ISO 8601 格式（如 `2024-12-20T14:30:22.123456`）
3. **错误信息**: 当前作为字符串处理，后续将集成 `SimulationError` 数据类
4. **版本号**: 每次仿真递增，用于验证数据新鲜度和追踪迭代
