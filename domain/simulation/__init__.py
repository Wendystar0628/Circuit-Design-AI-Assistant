# Simulation Domain
"""
仿真执行域

包含：
- models/: 数据模型定义
  - simulation_result.py: 仿真结果数据类
  - simulation_error.py: 仿真错误数据类
  - simulation_config.py: 仿真配置数据类
- executor/: 仿真执行器模块组
  - simulation_executor.py: 执行器抽象基类
  - executor_registry.py: 执行器注册表
  - spice_executor.py: SPICE 执行器（工作目录切换策略）
  - python_executor.py: Python 执行器（基础进程隔离）
  - circuit_analyzer.py: 电路文件分析器（含文件扫描功能）
- service/: 仿真服务层
  - simulation_config_service.py: 配置管理服务（读写、校验、持久化）
- analysis/: 高级仿真分析模块组
  - pvt_analysis.py: PVT 角点仿真
  - monte_carlo_analysis.py: 蒙特卡洛分析

服务层（位于 domain/services/）：
- simulation_service.py: 仿真服务（统一入口）

设计说明：
- SPICE 执行器采用工作目录切换策略，利用 ngspice 原生的相对路径解析能力
- Python 执行器采用基础进程隔离，不实现完整沙箱
- CircuitAnalyzer 整合了文件扫描和主电路检测功能
- SimulationService 作为仿真域的统一入口，协调执行器和配置
- SimulationConfigService 管理配置的读写、校验、持久化，发布配置变更事件
- PVTAnalyzer 执行多角点仿真，验证电路在极端条件下的性能
- MonteCarloAnalyzer 执行统计分析，评估工艺偏差和元件容差影响
"""
