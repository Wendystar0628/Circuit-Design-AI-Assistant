# Simulation Domain
"""
仿真执行域

包含：
- executor/: 仿真执行器模块组
  - simulation_executor.py: 执行器抽象基类
  - executor_registry.py: 执行器注册表
  - spice_executor.py: SPICE 执行器
  - python_executor.py: Python 执行器
  - process_monitor.py: 进程监控
- service/: 仿真服务层
  - simulation_service.py: 门面类
  - basic_simulation_runner.py: 基础仿真执行
  - advanced_simulation_runner.py: 高级仿真执行
- metrics/: 指标提取模块组
  - metrics_extractor.py: 门面类
  - amplifier_metrics.py: 放大器指标
- visualization/: 可视化模块
  - streaming/: 大数据波形流式渲染子模块
    - waveform_data_service.py: 波形数据服务门面类
    - lttb_downsampler.py: LTTB 降采样算法
    - resolution_pyramid.py: 多分辨率金字塔管理
    - viewport_data_provider.py: 视口感知数据提供器
    - waveform_prefetcher.py: 预加载服务
    - binary_data_encoder.py: 二进制数据编码器
  - chart_generator.py: 图表生成（集成降采样）
  - simulation_result_storage.py: 仿真结果存储（含分辨率金字塔）
- schematic/: 电路图生成子域
  - schematic_service.py: 电路图服务门面类
"""
