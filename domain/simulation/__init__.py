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
  - parameter_extractor.py: 参数提取服务
  - tuning_service.py: 调参服务

服务层（位于 domain/services/）：
- simulation_service.py: 无状态、可重入的仿真执行函数
  （接受文件 + 配置 → 选执行器 → 跑 → 落盘 → 返回
  ``(SimulationResult, result_path)``）
- simulation_job_manager.py: 仿真生命周期的权威入口，唯一对外
  暴露的仿真"提交 / 查询 / 取消 / 等待"通道，并独占发布
  ``EVENT_SIM_STARTED`` / ``EVENT_SIM_COMPLETE`` / ``EVENT_SIM_ERROR``

设计说明：
- SPICE 执行器采用工作目录切换策略，利用 ngspice 原生的相对路径解析能力
- Python 执行器采用基础进程隔离，不实现完整沙箱
- CircuitAnalyzer 提供电路文件扫描和依赖关系分析功能
- SimulationJobManager 是仿真在仓库中唯一的启动入口；
  SimulationService 只作为 manager worker 里的"跑一次"原子操作，
  不持有运行态、不发事件，可被任意线程重入调用
"""
