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

服务层（位于 domain/services/）：
- simulation_service.py: 仿真服务（统一入口）

设计说明：
- SPICE 执行器采用工作目录切换策略，利用 ngspice 原生的相对路径解析能力
- Python 执行器采用基础进程隔离，不实现完整沙箱
- CircuitAnalyzer 整合了文件扫描和主电路检测功能
- SimulationService 作为仿真域的统一入口，协调执行器和配置
"""
