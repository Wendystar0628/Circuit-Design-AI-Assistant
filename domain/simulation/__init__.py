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
  - spice_error_parser.py: SPICE 错误解析
  - spice_error_recovery.py: SPICE 错误恢复
  - python_executor.py: Python 执行器（基础进程隔离）
  - circuit_analyzer.py: 电路文件分析器
  - file_discovery.py: 文件发现策略
- service/: 仿真服务层
  - simulation_service.py: 门面类
  - basic_simulation_runner.py: 基础仿真执行
  - advanced_simulation_runner.py: 高级仿真执行
  - tuning_service.py: 快速调参服务
  - simulation_control_service.py: 仿真进度控制
  - main_circuit_detector.py: 主电路检测
  - simulation_state_manager.py: 状态管理
  - simulation_config_service.py: 配置服务
- analysis/: 高级分析模块
  - pvt_analysis.py: PVT 角点仿真
  - monte_carlo_analysis.py: 蒙特卡洛分析
  - parametric_sweep.py: 参数扫描
  - worst_case_analysis.py: 最坏情况分析
  - sensitivity_analysis.py: 敏感度分析
  - post_processor.py: 仿真后处理
  - topology_recognizer.py: 电路拓扑识别
- metrics/: 指标提取模块组
  - metrics_extractor.py: 门面类
  - metric_result.py: 指标结果数据类
  - amplifier_metrics.py: 放大器指标
  - noise_metrics.py: 噪声指标
  - distortion_metrics.py: 失真指标
  - power_metrics.py: 电源指标
  - transient_metrics.py: 瞬态指标
- visualization/: 可视化模块
  - streaming/: 大数据波形流式渲染子模块
    - waveform_data_service.py: 波形数据服务门面类
    - lttb_downsampler.py: LTTB 降采样算法
    - resolution_pyramid.py: 多分辨率金字塔管理
    - viewport_data_provider.py: 视口感知数据提供器
    - waveform_prefetcher.py: 预加载服务
    - binary_data_encoder.py: 二进制数据编码器
  - chart_generator.py: 图表生成（集成降采样）
  - waveform_measurement.py: 波形测量
  - waveform_math.py: 波形数学运算
  - simulation_result_storage.py: 仿真结果存储（含分辨率金字塔）
  - data_exporter.py: 数据导出
  - report_generator.py: PDF报告生成
- schematic/: 电路图生成子域
  - schematic_service.py: 电路图服务门面类
  - models/: 电路图数据模型
  - parser/: 网表解析器
  - layout/: 布局引擎
  - renderer/: 渲染器
- convergence_helper.py: 收敛辅助
- feedback_generator.py: 反馈生成器
- library_manager.py: 子电路库管理

设计说明：
- SPICE 执行器采用工作目录切换策略，利用 ngspice 原生的相对路径解析能力
- Python 执行器采用基础进程隔离，不实现完整沙箱
- 错误恢复机制增加了最大重试次数限制
- 文件发现策略简化命名（FileDiscovery 替代 FileDiscoveryStrategy）
"""
