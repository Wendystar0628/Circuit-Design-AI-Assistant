# Event Type Constants
"""
事件类型常量定义

职责：
- 集中定义所有事件类型常量
- 避免字符串硬编码
- 作为 EventBus 发布和订阅事件的键

设计原则：
- 纯常量定义，不依赖任何其他模块
- 所有事件名使用 EVENT_ 前缀
- 按功能模块分组组织
- 命名规范：EVENT_{模块}_{动作}，全大写下划线分隔

使用示例：
    from shared.event_types import EVENT_INIT_COMPLETE
    event_bus.subscribe(EVENT_INIT_COMPLETE, on_init_complete)
    event_bus.publish(EVENT_INIT_COMPLETE, {"timestamp": time.time()})
"""

# ============================================================
# 初始化事件
# ============================================================

# 启动阶段完成通知
EVENT_INIT_PHASE_COMPLETE = "init_phase_complete"

# 所有初始化完成
EVENT_INIT_COMPLETE = "init_complete"

# ============================================================
# UI 交互事件
# ============================================================

# 用户选择文件
EVENT_UI_FILE_SELECTED = "ui_file_selected"

# 用户发送消息
EVENT_UI_SEND_MESSAGE = "ui_send_message"

# 用户请求仿真
EVENT_UI_REQUEST_SIMULATION = "ui_request_simulation"

# ============================================================
# 面板管理事件
# ============================================================

# 面板可见性变更
# 携带数据：
#   - panel_id: str - 面板 ID
#   - visible: bool - 是否可见
#   - region: str - 面板所属区域
EVENT_PANEL_VISIBILITY_CHANGED = "panel_visibility_changed"

# 标签页切换
# 携带数据：
#   - previous_tab: str - 之前的标签页 ID
#   - current_tab: str - 当前标签页 ID
EVENT_TAB_CHANGED = "tab_changed"

# ============================================================
# 状态变更事件
# ============================================================

# 项目打开
# 携带数据：
#   - path: str - 项目路径
#   - name: str - 项目名称
#   - is_existing: bool - 是否为已有项目（存在 checkpoints.sqlite3）
#   - has_history: bool - 是否有历史对话和优化记录
#   - status: str - 项目状态（ready/degraded）
#   - degraded: bool - 是否为降级模式
EVENT_STATE_PROJECT_OPENED = "state_project_opened"

# 项目关闭
# 携带数据：
#   - path: str - 关闭的项目路径
EVENT_STATE_PROJECT_CLOSED = "state_project_closed"

# 配置变更
EVENT_STATE_CONFIG_CHANGED = "state_config_changed"

# 迭代状态更新
EVENT_STATE_ITERATION_UPDATED = "state_iteration_updated"


# ============================================================
# Worker 事件
# ============================================================

# Worker 启动
EVENT_WORKER_STARTED = "worker_started"

# Worker 进度更新
EVENT_WORKER_PROGRESS = "worker_progress"

# Worker 完成
EVENT_WORKER_COMPLETE = "worker_complete"

# Worker 错误
EVENT_WORKER_ERROR = "worker_error"

# ============================================================
# 异步任务事件
# ============================================================

# 任务启动
# 携带数据：
#   - task_id: str - 任务 ID
#   - task_type: str - 任务类型
EVENT_TASK_STARTED = "task_started"

# 任务完成
# 携带数据：
#   - task_id: str - 任务 ID
#   - task_type: str - 任务类型
#   - result: Any - 任务结果
EVENT_TASK_COMPLETED = "task_completed"

# 任务失败
# 携带数据：
#   - task_id: str - 任务 ID
#   - task_type: str - 任务类型
#   - error: str - 错误信息
EVENT_TASK_FAILED = "task_failed"

# 任务取消
# 携带数据：
#   - task_id: str - 任务 ID
#   - task_type: str - 任务类型
EVENT_TASK_CANCELLED = "task_cancelled"

# ============================================================
# LLM 事件
# ============================================================

# LLM 配置变更请求
# 由界面层在保存配置后发布，由应用层（bootstrap）订阅并刷新 LLM 运行时。
# 携带数据：
#   - provider: str - LLM 厂商 ID
#   - model: str - 模型名称
#   - source: str - 触发来源
EVENT_LLM_CONFIG_CHANGED = "llm_config_changed"

# 模型切换
# 携带数据：
#   - new_model_id: str - 新模型 ID（格式: "provider:model_name"）
#   - old_model_id: str - 旧模型 ID（可能为空字符串）
#   - provider: str - 厂商 ID
#   - model_name: str - 模型名称
#   - display_name: str - 模型显示名称
#   - supports_thinking: bool - 是否支持深度思考
#   - supports_vision: bool - 是否支持视觉
EVENT_MODEL_CHANGED = "model_changed"

# ============================================================
# 嵌入模型事件
# ============================================================

# 嵌入模型厂商切换
# 携带数据：
#   - old_provider: str - 旧厂商 ID
#   - new_provider: str - 新厂商 ID
EVENT_EMBEDDING_PROVIDER_CHANGED = "embedding_provider_changed"

# 嵌入模型就绪
# 携带数据：
#   - provider: str - 嵌入模型厂商 ID
#   - model: str - 嵌入模型名称
EVENT_EMBEDDING_MODEL_READY = "embedding_model_ready"

# ============================================================
# 联网搜索事件
# ============================================================

# 联网搜索开始
# 携带数据：
#   - query: str - 搜索查询
#   - search_type: str - 搜索类型（"provider" | "general"）
#   - provider: str - 搜索提供商（"zhipu" | "google" | "bing"）
EVENT_WEB_SEARCH_STARTED = "web_search_started"

# 联网搜索完成
# 携带数据：
#   - query: str - 搜索查询
#   - results: list - 搜索结果列表
#   - result_count: int - 结果数量
#   - search_type: str - 搜索类型
#   - provider: str - 搜索提供商
EVENT_WEB_SEARCH_COMPLETE = "web_search_complete"

# 联网搜索错误
# 携带数据：
#   - query: str - 搜索查询
#   - error: str - 错误信息
#   - provider: str - 搜索提供商
EVENT_WEB_SEARCH_ERROR = "web_search_error"

# ============================================================
# 仿真事件
# ============================================================

# 仿真开始
# 携带数据：
#   - circuit_file: str - 电路文件路径
#   - simulation_type: str - 仿真类型（"transient", "ac", "dc", "noise" 等）
#   - config: dict - 仿真配置参数
EVENT_SIM_STARTED = "sim_started"

# 仿真进度
# 携带数据：
#   - progress: float - 进度百分比（0.0-1.0）
#   - current_step: str - 当前步骤描述
#   - elapsed_seconds: float - 已用时间（秒）
#   - estimated_remaining: float - 预计剩余时间（秒，可选）
EVENT_SIM_PROGRESS = "sim_progress"

# 仿真完成
# 携带数据：
#   - result_path: str - 结果文件路径
#   - metrics: dict - 性能指标摘要
#   - duration_seconds: float - 总耗时（秒）
EVENT_SIM_COMPLETE = "sim_complete"

# 仿真错误
# 携带数据：
#   - error_type: str - 错误类型
#   - error_message: str - 错误信息
#   - file: str - 错误文件（可选）
#   - line: int - 错误行号（可选）
#   - recoverable: bool - 是否可恢复
EVENT_SIM_ERROR = "sim_error"

# 仿真取消
# 携带数据：
#   - reason: str - 取消原因（"user_requested", "timeout", "error"）
#   - partial_result_path: str - 部分结果文件路径（若有）
EVENT_SIM_CANCELLED = "sim_cancelled"

# 仿真暂停
# 携带数据：
#   - progress: float - 暂停时的进度
#   - state_snapshot: str - 状态快照路径（用于恢复）
EVENT_SIM_PAUSED = "sim_paused"

# 仿真恢复
# 携带数据：
#   - resumed_from: float - 恢复时的进度
EVENT_SIM_RESUMED = "sim_resumed"

# 仿真配置变更
# 携带数据：
#   - config_key: str - 变更的配置项
#   - old_value: Any - 旧值
#   - new_value: Any - 新值
EVENT_SIM_CONFIG_CHANGED = "sim_config_changed"

# 主电路变更
# 携带数据：
#   - old_path: str - 旧主电路路径（可选）
#   - new_path: str - 新主电路路径
#   - detection_method: str - 检测方式（"auto", "user_selected"）
EVENT_MAIN_CIRCUIT_CHANGED = "main_circuit_changed"

# 电路分析完成
# 携带数据：
#   - circuit_file: str - 电路文件路径
#   - analysis_type: str - 分析类型
#   - components: dict - 元件统计
EVENT_CIRCUIT_ANALYSIS_COMPLETE = "circuit_analysis_complete"

# 仿真执行失败（错误已收集，准备下一轮修复）
# 携带数据：
#   - error_type: str - 错误类型
#   - error_message: str - 错误信息
#   - file: str - 错误文件（可选）
#   - line: int - 错误行号（可选）
EVENT_SIMULATION_ERROR_COLLECTED = "simulation_error_collected"

# 仿真结果文件创建（文件监控触发）
# 携带数据：
#   - file_path: str - 结果文件相对路径
#   - project_root: str - 项目根目录
EVENT_SIM_RESULT_FILE_CREATED = "sim_result_file_created"

# 仿真执行器注册
# 携带数据：
#   - name: str - 执行器名称
#   - extensions: list - 支持的文件扩展名列表
EVENT_EXECUTOR_REGISTERED = "executor_registered"

# 仿真执行器注销
# 携带数据：
#   - name: str - 执行器名称
EVENT_EXECUTOR_UNREGISTERED = "executor_unregistered"

# 波形数据请求
# 携带数据：
#   - signal_name: str - 信号名称
#   - x_min: float - X 轴最小值
#   - x_max: float - X 轴最大值
#   - viewport_width: int - 视口宽度（像素）
EVENT_WAVEFORM_DATA_REQUESTED = "waveform_data_requested"

# 波形数据就绪
# 携带数据：
#   - signal_name: str - 信号名称
#   - point_count: int - 数据点数量
#   - resolution_level: int - 分辨率层级
#   - is_full_resolution: bool - 是否为原始分辨率
EVENT_WAVEFORM_DATA_READY = "waveform_data_ready"

# 分辨率金字塔构建完成
# 携带数据：
#   - signal_name: str - 信号名称
#   - original_points: int - 原始数据点数
#   - levels: list - 生成的分辨率层级列表
#   - build_time_ms: float - 构建耗时（毫秒）
EVENT_PYRAMID_BUILD_COMPLETE = "pyramid_build_complete"

# ============================================================
# 分析选择事件
# ============================================================

# ============================================================
# 电路图事件
# ============================================================

# 电路图加载完成
# 携带数据：
#   - source_file: str - 源网表文件路径
#   - element_count: int - 元件数量
#   - connection_count: int - 连接数量
#   - layout_algorithm: str - 使用的布局算法
EVENT_SCHEMATIC_LOADED = "schematic_loaded"

# 电路图元件选中
# 携带数据：
#   - element_id: str - 元件 ID
#   - element_type: str - 元件类型（"R", "C", "L", "M", "X" 等）
#   - element_name: str - 元件名称
#   - properties: dict - 元件属性
#   - source_line: int - 网表中的行号
EVENT_SCHEMATIC_ELEMENT_SELECTED = "schematic_element_selected"

# 电路图元件悬停
# 携带数据：
#   - element_id: str - 元件 ID
#   - element_type: str - 元件类型
#   - element_name: str - 元件名称
#   - position: tuple - 鼠标位置 (x, y)
EVENT_SCHEMATIC_ELEMENT_HOVERED = "schematic_element_hovered"

# 跳转到源码
# 携带数据：
#   - file_path: str - 文件路径
#   - line_number: int - 行号
#   - element_name: str - 元件名称
EVENT_SCHEMATIC_JUMP_TO_SOURCE = "schematic_jump_to_source"

# 电路图缩放变更
# 携带数据：
#   - zoom_level: float - 缩放级别
#   - center_x: float - 视图中心 X
#   - center_y: float - 视图中心 Y
EVENT_SCHEMATIC_ZOOM_CHANGED = "schematic_zoom_changed"

# ============================================================
# RAG 事件
# ============================================================

# RAG 初始化完成（服务就绪，可能还未索引）
# 携带数据：
#   - project_root: str - 项目根目录
#   - status: str - "ready" | "error"
#   - error: str - 错误信息（仅 status=error 时）
EVENT_RAG_INIT_COMPLETE = "rag.init_complete"

# RAG 索引开始
# 携带数据：
#   - total_files: int - 总文件数
#   - track_id: str - 追踪 ID
EVENT_RAG_INDEX_STARTED = "rag.index_started"

# RAG 索引进度
# 携带数据：
#   - processed: int - 已处理文件数
#   - total: int - 总文件数
#   - current_file: str - 当前处理的文件（相对路径）
#   - track_id: str - 追踪 ID
EVENT_RAG_INDEX_PROGRESS = "rag.index_progress"

# RAG 索引完成
# 携带数据：
#   - total_indexed: int - 已索引文件总数
#   - failed: int - 失败文件数
#   - duration_s: float - 耗时（秒）
#   - entities_count: int - 提取的实体数
#   - relations_count: int - 提取的关系数
EVENT_RAG_INDEX_COMPLETE = "rag.index_complete"

# RAG 索引错误（单文件级别）
# 携带数据：
#   - file_path: str - 失败文件路径（相对路径）
#   - error: str - 错误信息
#   - track_id: str - 追踪 ID
EVENT_RAG_INDEX_ERROR = "rag.index_error"

# RAG 检索完成
# 携带数据：
#   - query: str - 查询文本
#   - mode: str - 检索模式（naive/local/global/hybrid/mix）
#   - results_count: int - 检索结果数
#   - entities_found: int - 匹配实体数
#   - relations_found: int - 匹配关系数
#   - chunks_found: int - 匹配分块数
EVENT_RAG_QUERY_COMPLETE = "rag.query_complete"

# ============================================================
# 上下文压缩事件
# ============================================================

# 请求压缩上下文
EVENT_CONTEXT_COMPRESS_REQUESTED = "context_compress_requested"

# 压缩预览就绪
EVENT_CONTEXT_COMPRESS_PREVIEW_READY = "context_compress_preview_ready"

# 压缩完成
EVENT_CONTEXT_COMPRESS_COMPLETE = "context_compress_complete"

# ============================================================
# 对话管理事件
# ============================================================

# 会话状态变更（由 SessionStateManager 发布）
# 携带数据：
#   - session_name: str - 当前会话名称
#   - message_count: int - 消息数量
#   - action: str - 触发动作（"new", "switch", "delete", "rename"）
#   - previous_session_name: str - 之前的会话名称（可选）
EVENT_SESSION_CHANGED = "session_changed"


# ============================================================
# 错误处理事件
# ============================================================

# 错误发生
EVENT_ERROR_OCCURRED = "error_occurred"

# 错误恢复
EVENT_ERROR_RECOVERED = "error_recovered"

# 异步槽函数错误（qasync @asyncSlot 异常）
# 携带数据：
#   - function: str - 函数名
#   - error: str - 错误信息
#   - error_type: str - 错误类型名
#   - traceback: str - 完整堆栈跟踪
EVENT_ASYNC_SLOT_ERROR = "async_slot_error"

# ============================================================
# 文件操作事件
# ============================================================

# 文件变更
EVENT_FILE_CHANGED = "file_changed"

# 文件锁定
EVENT_FILE_LOCKED = "file_locked"

# 文件解锁
EVENT_FILE_UNLOCKED = "file_unlocked"

# 文件外部修改冲突检测（TOCTOU 竞态条件）
# 携带数据：
#   - file_path: str - 冲突的文件路径
#   - action: str - 后续动作（"retry" 表示 LLM 将重新读取）
EVENT_FILE_CONFLICT_DETECTED = "file_conflict_detected"

# ============================================================
# 依赖健康检查事件
# ============================================================

# 依赖扫描开始
# 携带数据：
#   - project_path: str - 项目路径
EVENT_DEPENDENCY_SCAN_STARTED = "dependency.scan_started"

# 依赖扫描完成
# 携带数据：
#   - project_path: str - 项目路径
#   - total_dependencies: int - 总依赖数
#   - missing_count: int - 缺失依赖数
#   - resolved_count: int - 已解析依赖数
#   - has_issues: bool - 是否存在问题
EVENT_DEPENDENCY_SCAN_COMPLETE = "dependency.scan_complete"

# 依赖健康报告更新
# 携带数据：
#   - report_path: str - 报告文件路径
#   - missing_dependencies: list - 缺失依赖列表
#   - resolution_suggestions: list - 解析建议列表
EVENT_DEPENDENCY_REPORT_UPDATED = "dependency.report_updated"

# 依赖解析请求（用户请求尝试解析缺失依赖）
# 携带数据：
#   - dependency_id: str - 依赖项 ID
#   - source: str - 解析来源（"local", "global_lib", "marketplace"）
EVENT_DEPENDENCY_RESOLUTION_REQUESTED = "dependency.resolution_requested"

# 依赖解析完成
# 携带数据：
#   - dependency_id: str - 依赖项 ID
#   - success: bool - 是否成功
#   - resolved_path: str - 解析后的路径（若成功）
#   - error_message: str - 错误信息（若失败）
EVENT_DEPENDENCY_RESOLUTION_COMPLETE = "dependency.resolution_complete"

# ============================================================
# 智能文件操作事件（File Intelligence）
# ============================================================

# 搜索索引更新完成
# 携带数据：
#   - file_count: int - 索引的文件数量
#   - build_time_ms: float - 构建耗时（毫秒）
EVENT_FILE_SEARCH_INDEX_UPDATED = "file_intelligence.search_index_updated"

# 符号定位完成
# 携带数据：
#   - symbol_name: str - 符号名称
#   - file_path: str - 定位到的文件路径
#   - line: int - 行号
#   - scope: str - 定位范围（current_file/include_files/project）
EVENT_SYMBOL_LOCATED = "file_intelligence.symbol_located"

# 引用查找完成
# 携带数据：
#   - symbol_name: str - 符号名称
#   - reference_count: int - 引用数量
#   - files_searched: int - 搜索的文件数量
EVENT_REFERENCES_FOUND = "file_intelligence.references_found"

# ============================================================
# 外部服务事件
# ============================================================

# 熔断器打开
EVENT_SERVICE_CIRCUIT_OPEN = "service_circuit_open"

# 熔断器关闭
EVENT_SERVICE_CIRCUIT_CLOSE = "service_circuit_close"

# ============================================================
# 国际化事件
# ============================================================

# 语言切换
EVENT_LANGUAGE_CHANGED = "language_changed"

# ============================================================
# 迭代确认事件
# ============================================================

# 等待用户确认
EVENT_ITERATION_AWAITING_CONFIRMATION = "iteration_awaiting_confirmation"

# 用户确认继续
EVENT_ITERATION_USER_CONFIRMED = "iteration_user_confirmed"

# 用户停止
EVENT_ITERATION_USER_STOPPED = "iteration_user_stopped"

# 当前激活文件变更
# 携带数据：
#   - old_path: str - 旧文件路径
#   - new_path: str - 新文件路径
EVENT_ACTIVE_FILE_CHANGED = "active_file_changed"

# ============================================================
# 设计目标事件
# ============================================================

# 设计目标更新
# 携带数据：
#   - goals: list - 更新后的设计目标列表
#   - source: str - 更新来源（"dialog" 表示用户通过对话框编辑，"llm" 表示 LLM 提取）
#   - previous_goals: list - 更新前的设计目标（用于撤销）
EVENT_DESIGN_GOALS_UPDATED = "design_goals_updated"

# 设计完成
# 携带数据：
#   - termination_reason: str - 终止原因（"user_accepted", "goals_satisfied", "max_checkpoints", "stagnated", "user_stopped"）
#   - final_score: float - 最终性能得分
#   - checkpoint_count: int - 总检查点次数
#   - report_path: str - 生成的报告路径（若有）
EVENT_DESIGN_COMPLETED = "design_completed"

# 设计被接受
EVENT_DESIGN_ACCEPTED = "design_accepted"

# 设计被停止
EVENT_DESIGN_STOPPED = "design_stopped"

# ============================================================
# 信息卡片事件（阶段九）
# ============================================================

# 信息卡片添加
# 携带数据：
#   - card_id: str - 卡片 ID
#   - category: str - 信息类别
#   - card_type: str - 卡片类型
#   - session_id: str - 所属会话 ID
EVENT_INFO_CARD_ADDED = "info_panel.card_added"

# 信息卡片更新
# 携带数据：
#   - card_id: str - 卡片 ID
#   - updates: dict - 更新的字段
EVENT_INFO_CARD_UPDATED = "info_panel.card_updated"

# 信息卡片移除
# 携带数据：
#   - card_id: str - 卡片 ID
EVENT_INFO_CARD_REMOVED = "info_panel.card_removed"

# 信息卡片置顶
# 携带数据：
#   - card_id: str - 卡片 ID
#   - is_pinned: bool - 是否置顶
EVENT_INFO_CARD_PINNED = "info_panel.card_pinned"

# 信息卡片批量加载完成（会话切换后）
# 携带数据：
#   - session_id: str - 会话 ID
#   - card_count: int - 加载的卡片数量
EVENT_INFO_CARDS_LOADED = "info_panel.cards_loaded"

# 信息面板类别切换
# 携带数据：
#   - previous_category: str - 之前的类别
#   - current_category: str - 当前类别
EVENT_INFO_PANEL_CATEGORY_CHANGED = "info_panel.category_changed"

# 信息面板清空
# 携带数据：
#   - category: str - 被清空的类别（若为 None 表示全部清空）
EVENT_INFO_PANEL_CLEARED = "info_panel.cleared"


# ============================================================
# 撤回操作事件
# ============================================================

# 撤回开始
# 携带数据：
#   - target_iteration: int - 目标迭代号
#   - current_iteration: int - 当前迭代号
EVENT_UNDO_STARTED = "undo_started"

# 撤回完成
# 携带数据：
#   - restored_iteration: int - 恢复到的迭代号
#   - previous_iteration: int - 撤回前的迭代号
EVENT_UNDO_COMPLETED = "undo_completed"

# 撤回失败
# 携带数据：
#   - error_code: str - 错误码
#   - error_message: str - 错误信息
#   - target_iteration: int - 目标迭代号
EVENT_UNDO_FAILED = "undo_failed"

# ============================================================
# 文件引用校验事件
# ============================================================

# UI 请求重新仿真（文件缺失时触发）
# 携带数据：
#   - reason: str - 触发原因（"sim_result_file_missing"）
#   - missing_path: str - 缺失的文件路径
EVENT_REQUEST_RESIMULATION = "ui.request_resimulation"

# ============================================================
# 参数调整事件
# ============================================================

# 参数提取完成
# 携带数据：
#   - file_path: str - 电路文件路径
#   - parameter_count: int - 提取的参数数量
#   - parameters: list - 参数列表
EVENT_PARAMETERS_EXTRACTED = "tuning.parameters_extracted"

# 参数值变更
# 携带数据：
#   - param_name: str - 参数名称
#   - old_value: float - 旧值
#   - new_value: float - 新值
#   - source: str - 变更来源（"slider", "input", "reset"）
EVENT_PARAMETER_VALUE_CHANGED = "tuning.parameter_value_changed"

# 参数应用到电路文件
# 携带数据：
#   - file_path: str - 电路文件路径
#   - parameters: dict - 应用的参数字典 {name: value}
#   - success: bool - 是否成功
EVENT_PARAMETERS_APPLIED = "tuning.parameters_applied"

# 调参应用完成（由 TuningService 发布）
# 携带数据：
#   - file_path: str - 电路文件路径
#   - changes: dict - 应用的参数变更 {name: value}
#   - modified_lines: list - 修改的行号列表
#   - backup_path: str - 备份文件路径
EVENT_TUNING_APPLIED = "tuning.applied"

# 文件已恢复（由 TuningService 发布）
# 携带数据：
#   - file_path: str - 电路文件路径
#   - backup_path: str - 备份文件路径
EVENT_TUNING_RESTORED = "tuning.restored"

# 请求自动仿真（参数变更后触发）
# 携带数据：
#   - changed_params: dict - 变更的参数字典
#   - trigger_source: str - 触发来源（"auto_sim", "manual"）
EVENT_TUNING_REQUEST_SIMULATION = "tuning.request_simulation"

# 自动仿真模式变更
# 携带数据：
#   - enabled: bool - 是否启用自动仿真
EVENT_AUTO_SIMULATION_CHANGED = "tuning.auto_simulation_changed"

# ============================================================
# Agent 循环事件
# ============================================================

# Agent 工具修改了文件（通知编辑器刷新）
# 携带数据：
#   - path: str - 被修改文件的绝对路径
#   - tool_name: str - 修改文件的工具名称
EVENT_AGENT_FILE_MODIFIED = "agent.file_modified"

# ============================================================
# 关键事件列表（需要特殊保护）
# ============================================================

CRITICAL_EVENTS = [
    EVENT_ITERATION_AWAITING_CONFIRMATION,
    EVENT_ERROR_OCCURRED,
]


# ============================================================
# 模块导出
# ============================================================

__all__ = [
    # 初始化事件
    "EVENT_INIT_PHASE_COMPLETE",
    "EVENT_INIT_COMPLETE",
    # UI 交互事件
    "EVENT_UI_FILE_SELECTED",
    "EVENT_UI_SEND_MESSAGE",
    "EVENT_UI_REQUEST_SIMULATION",
    # 面板管理事件
    "EVENT_PANEL_VISIBILITY_CHANGED",
    "EVENT_TAB_CHANGED",
    # 状态变更事件
    "EVENT_STATE_PROJECT_OPENED",
    "EVENT_STATE_PROJECT_CLOSED",
    "EVENT_STATE_CONFIG_CHANGED",
    "EVENT_STATE_ITERATION_UPDATED",
    # Worker 事件
    "EVENT_WORKER_STARTED",
    "EVENT_WORKER_PROGRESS",
    "EVENT_WORKER_COMPLETE",
    "EVENT_WORKER_ERROR",
    # 异步任务事件
    "EVENT_TASK_STARTED",
    "EVENT_TASK_COMPLETED",
    "EVENT_TASK_FAILED",
    "EVENT_TASK_CANCELLED",
    "EVENT_LLM_CONFIG_CHANGED",
    "EVENT_MODEL_CHANGED",
    # 嵌入模型事件
    "EVENT_EMBEDDING_PROVIDER_CHANGED",
    "EVENT_EMBEDDING_MODEL_READY",
    # 联网搜索事件
    "EVENT_WEB_SEARCH_STARTED",
    "EVENT_WEB_SEARCH_COMPLETE",
    "EVENT_WEB_SEARCH_ERROR",
    # 仿真事件
    "EVENT_SIM_STARTED",
    "EVENT_SIM_PROGRESS",
    "EVENT_SIM_COMPLETE",
    "EVENT_SIM_ERROR",
    "EVENT_SIM_CANCELLED",
    "EVENT_SIM_PAUSED",
    "EVENT_SIM_RESUMED",
    "EVENT_SIM_CONFIG_CHANGED",
    "EVENT_MAIN_CIRCUIT_CHANGED",
    "EVENT_CIRCUIT_ANALYSIS_COMPLETE",
    "EVENT_SIMULATION_ERROR_COLLECTED",
    "EVENT_SIM_RESULT_FILE_CREATED",
    "EVENT_EXECUTOR_REGISTERED",
    "EVENT_EXECUTOR_UNREGISTERED",
    "EVENT_WAVEFORM_DATA_REQUESTED",
    "EVENT_WAVEFORM_DATA_READY",
    "EVENT_PYRAMID_BUILD_COMPLETE",
    # 电路图事件
    "EVENT_SCHEMATIC_LOADED",
    "EVENT_SCHEMATIC_ELEMENT_SELECTED",
    "EVENT_SCHEMATIC_ELEMENT_HOVERED",
    "EVENT_SCHEMATIC_JUMP_TO_SOURCE",
    "EVENT_SCHEMATIC_ZOOM_CHANGED",
    # RAG 事件
    "EVENT_RAG_INIT_COMPLETE",
    "EVENT_RAG_INDEX_STARTED",
    "EVENT_RAG_INDEX_PROGRESS",
    "EVENT_RAG_INDEX_COMPLETE",
    # 上下文压缩事件
    "EVENT_CONTEXT_COMPRESS_REQUESTED",
    "EVENT_CONTEXT_COMPRESS_PREVIEW_READY",
    "EVENT_CONTEXT_COMPRESS_COMPLETE",
    # 错误处理事件
    "EVENT_ERROR_OCCURRED",
    "EVENT_ERROR_RECOVERED",
    "EVENT_ASYNC_SLOT_ERROR",
    # 文件操作事件
    "EVENT_FILE_CHANGED",
    "EVENT_FILE_LOCKED",
    "EVENT_FILE_UNLOCKED",
    "EVENT_FILE_CONFLICT_DETECTED",
    # 依赖健康检查事件
    "EVENT_DEPENDENCY_SCAN_STARTED",
    "EVENT_DEPENDENCY_SCAN_COMPLETE",
    "EVENT_DEPENDENCY_REPORT_UPDATED",
    "EVENT_DEPENDENCY_RESOLUTION_REQUESTED",
    "EVENT_DEPENDENCY_RESOLUTION_COMPLETE",
    # 智能文件操作事件
    "EVENT_FILE_SEARCH_INDEX_UPDATED",
    "EVENT_SYMBOL_LOCATED",
    "EVENT_REFERENCES_FOUND",
    # 外部服务事件
    "EVENT_SERVICE_CIRCUIT_OPEN",
    "EVENT_SERVICE_CIRCUIT_CLOSE",
    # 国际化事件
    "EVENT_LANGUAGE_CHANGED",
    # 迭代确认事件
    "EVENT_ITERATION_AWAITING_CONFIRMATION",
    "EVENT_ITERATION_USER_CONFIRMED",
    "EVENT_ITERATION_USER_STOPPED",
    "EVENT_ACTIVE_FILE_CHANGED",
    # 设计目标事件
    "EVENT_DESIGN_GOALS_UPDATED",
    "EVENT_DESIGN_COMPLETED",
    "EVENT_DESIGN_ACCEPTED",
    "EVENT_DESIGN_STOPPED",
    # 信息卡片事件
    "EVENT_INFO_CARD_ADDED",
    "EVENT_INFO_CARD_UPDATED",
    "EVENT_INFO_CARD_REMOVED",
    "EVENT_INFO_CARD_PINNED",
    "EVENT_INFO_CARDS_LOADED",
    "EVENT_INFO_PANEL_CATEGORY_CHANGED",
    "EVENT_INFO_PANEL_CLEARED",
    # 撤回操作事件
    "EVENT_UNDO_STARTED",
    "EVENT_UNDO_COMPLETED",
    "EVENT_UNDO_FAILED",
    # 文件引用校验事件
    "EVENT_REQUEST_RESIMULATION",
    # 参数调整事件
    "EVENT_PARAMETERS_EXTRACTED",
    "EVENT_PARAMETER_VALUE_CHANGED",
    "EVENT_PARAMETERS_APPLIED",
    "EVENT_TUNING_APPLIED",
    "EVENT_TUNING_RESTORED",
    "EVENT_TUNING_REQUEST_SIMULATION",
    "EVENT_AUTO_SIMULATION_CHANGED",
    "EVENT_AGENT_FILE_MODIFIED",
    # 关键事件列表
    "CRITICAL_EVENTS",
]
