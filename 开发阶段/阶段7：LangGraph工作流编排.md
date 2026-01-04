## 阶段七：LangGraph工作流编排 (1周)

> **目标**：实现基于 LangGraph 的工作流编排，采用"基于引用的单一数据源"架构，GraphState 存储文件指针和轻量摘要，业务数据存储在文件系统

> **📚 LangGraph 参考资源**：
> - **必须参考本地项目**：`LangGraph/` 目录包含最新的 LangGraph 源码和文档
> - **核心概念文档**：`LangGraph/docs/docs/concepts/low_level.md`
> - **持久化文档**：`LangGraph/docs/docs/concepts/persistence.md`
> - **人机协作文档**：`LangGraph/docs/docs/concepts/human_in_the_loop.md`
> - **SQLite Checkpointer**：`LangGraph/libs/checkpoint-sqlite/`

> **⚠️ 核心架构：基于引用的单一数据源**
> - **GraphState 是目录**：存储文件路径（指针）和轻量摘要，不存储重数据
> - **文件系统是仓库**：仿真结果、设计目标等业务数据存储在文件中
> - **领域服务是搬运工**：无状态服务，输入 → 处理 → 输出到文件 → 返回路径
> - **LangGraph 管理版本**：SqliteSaver 持久化 GraphState，回滚时指针自动回退
> - **SnapshotManager 管理文件**：增量快照项目文件，支持文件级别回滚

> **⚠️ LangGraph API 要点**：
> - 使用 `interrupt(value)` 函数暂停，而非 `interrupt_before` 参数
> - 使用 `Command(resume=value)` 恢复执行
> - 使用 `add_messages` reducer 管理消息列表
> - 删除消息需返回 `RemoveMessage` 对象

> **⚠️ 跨阶段依赖**：
> - `shared/async_runtime.py` - qasync 异步运行时（阶段三）
> - `application/tool_execution/tool_executor.py` - 工具执行接口（阶段六）
> - `domain/services/` - 无状态领域服务（阶段 2.5）
> - `domain/services/iteration_history_service.py` - 迭代历史视图服务（阶段 2.5）
> - `domain/services/snapshot_service.py` - 全量快照服务（阶段 2.5）

---

### 7.0 LangGraph 最小集成验证

#### 7.0.1 最小状态图验证 (`tests/integration/test_langgraph_minimal.py`)

- [ ] **文件路径**：`tests/integration/test_langgraph_minimal.py`
- [ ] **验证目标**：确认 LangGraph 基础 API 可正常工作
- [ ] **验证内容**：
  - 创建包含 2-3 个节点的最小 StateGraph
  - 验证 GraphState 定义（含文件指针字段）
  - 验证节点间状态传递正常
  - 验证 SqliteSaver 检查点保存/恢复
  - 验证 `interrupt()` 和 `Command(resume=value)` 机制

---

### 7.1 工作模式设计

#### 7.1.1 工作模式概述

- [ ] **模式定义**：
  - **工作流模式（WORKFLOW）**：完整的电路设计辅助流程，包含设计目标提取、迭代优化、仿真验证等自动化编排
  - **自由工作模式（FREE_WORK）**：保留完整工具能力的自由交互模式，无自动化工作流干预
- [ ] **模式切换入口**：
  - 对话面板标题栏的模式切换按钮
  - 菜单栏"对话"→"切换模式"
  - 快捷键 `Ctrl+Shift+M`
- [ ] **模式状态存储**：
  - `work_mode` 字段存储在 GraphState 中
  - 模式选择随 GraphState 持久化到 SqliteSaver

#### 7.1.2 工作流模式行为

- [ ] **启用的功能**：
  - 从用户首条消息提取设计目标
  - 弹出设计目标确认对话框
  - 每轮迭代后显示建议选项消息
  - 检查点暂停和用户确认机制
  - 迭代历史记录和撤回功能
- [ ] **消息处理流程**：
  1. 用户发送消息
  2. 判断是否为首条消息 → 是则进入 `design_goals_node`
  3. 执行工作流节点（设计、仿真、分析等）
  4. 进入 `user_checkpoint_node` 暂停
  5. 显示建议选项消息，等待用户选择

#### 7.1.3 自由工作模式行为

- [ ] **关闭的功能**：
  - 不自动提取设计目标
  - 不弹出设计目标确认对话框
  - 不显示建议选项消息
  - 无检查点暂停
- [ ] **保留的功能**：
  - LLM 对话能力
  - 完整工具调用能力（文件操作、仿真、RAG 检索等）
  - 会话管理
- [ ] **消息处理流程**：
  1. 用户发送消息
  2. 直接进入 `free_work_node` 处理
  3. 调用 LLM 生成回复（可能包含工具调用）
  4. 若有工具调用 → 执行工具 → 继续 LLM 处理
  5. 显示最终回复



#### 7.1.4 自由工作节点 (`application/graph/nodes/free_work_node.py`)

- [ ] **文件路径**：`application/graph/nodes/free_work_node.py`
- [ ] **职责**：处理自由工作模式下的用户消息
- [ ] **输入**：从 GraphState 读取 `user_input`、`session_id`
- [ ] **执行流程**：
  1. 调用 `ContextService.load_messages()` 获取对话历史
  2. 调用 `RAGService.retrieve()` 获取相关上下文（按需）
  3. 构建 Prompt 并调用 LLM
  4. 若有工具调用 → 执行工具 → 继续 LLM 处理（Agentic Loop）
  5. 调用 `ContextService.append_message()` 保存对话
  6. 返回 GraphState 更新
- [ ] **输出**：`return {"current_node": "free_work", "is_completed": False}`

#### 7.1.5 模式切换机制

- [ ] **切换流程**：
  1. 更新 GraphState 的 `work_mode` 字段
  2. 发布 `EVENT_WORK_MODE_CHANGED` 事件
  3. UI 组件订阅事件并更新显示
- [ ] **切换限制**：
  - 工作流正在执行时禁止切换
- [ ] **模式指示器 UI**：
  - 位置：对话面板标题栏右侧
  - 工作流模式：🔧 + "工作流"
  - 自由工作模式：💬 + "自由工作"

---

### 7.2 GraphState 定义 (`application/graph/state.py`)

> **核心原则**：GraphState 是唯一真理来源，存储文件指针和轻量摘要，不存储重数据

- [ ] **文件路径**：`application/graph/state.py`
- [ ] **职责**：定义 LangGraph 工作流的状态结构

#### 7.2.1 GraphState 字段定义

- [ ] **会话与模式控制**：
  - `session_id: str` - 会话标识
  - `work_mode: str` - 工作模式（"workflow" | "free_work"）
  - `project_root: str` - 项目根目录路径
- [ ] **流转控制**：
  - `current_node: str` - 当前节点名称
  - `previous_node: str` - 上一个节点名称
  - `user_input: str` - 用户最新输入
  - `user_intent: str` - 用户意图类型
  - `is_completed: bool` - 是否完成
  - `termination_reason: str` - 终止原因
- [ ] **文件指针**（核心：存路径不存内容）：
  - `circuit_file_path: str` - 主电路文件相对路径
  - `sim_result_path: str` - 最新仿真结果文件路径
  - `design_goals_path: str` - 设计目标文件路径
- [ ] **轻量摘要**（用于条件边判断）：
  - `design_goals_summary: dict` - 设计目标摘要
  - `last_metrics: dict` - 最新仿真指标摘要
  - `error_context: str` - 错误上下文
- [ ] **计数器**：
  - `iteration_count: int` - 迭代次数
  - `checkpoint_count: int` - 检查点计数
  - `stagnation_count: int` - 停滞计数（连续无改善次数）
  - `consecutive_fix_attempts: int` - 连续修复尝试次数（用于错误修复熔断机制）
- [ ] **控制标志**：
  - `force_resimulate: bool` - 强制重新仿真标志（UI 发现文件缺失时设置，router_node 检测后路由到 simulation_node）
- [ ] **追踪上下文持久化**（解决 interrupt/resume 断链问题，见阶段 1.5.3.1）：
  - `_trace_id: str` - 当前追踪链路 ID（跨 interrupt 保持）
  - `_last_span_id: str` - 最后一个 Span ID（用于恢复后的父子关系）
  - `_trace_checkpoint_count: int` - 追踪检查点计数（用于 UI 显示跨 checkpoint 标记）
- [ ] **消息聚合**：
  - `messages: Annotated[list[AnyMessage], add_messages]` - LangGraph 内部消息

#### 7.2.2 状态修改规范

- [ ] **图节点返回值模式**：
  - 通过返回字典修改 GraphState
  - 只返回需要更新的字段
  - 示例：`return {"sim_result_path": "sim_results/run_003.json", "last_metrics": {...}}`
- [ ] **禁止的操作**：
  - 禁止直接修改传入的 `state` 参数
  - 禁止在 GraphState 中存储大型数据

#### 7.2.3 GraphStateProjector - 状态投影器 (`application/graph_state_projector.py`)

> **初始化顺序**：Phase 3.6，依赖 SessionState、EventBus

- [ ] **文件路径**：`application/graph_state_projector.py`
- [ ] **职责**：监听 GraphState 变更，自动投影到 SessionState，发布变更事件
- [ ] **设计原则**：
  - 单向数据流的核心组件
  - 自动计算派生状态（如 workflow_locked）
  - 变更时发布细粒度事件，UI 组件按需订阅
- [ ] **核心方法**：
  - `on_graph_state_changed(old_state, new_state)` - GraphState 变更回调
  - `project_field(field_name, old_value, new_value)` - 投影单个字段
  - `compute_derived_state(state)` - 计算派生状态
- [ ] **投影规则**：
  - `session_id` → 直接投影
  - `work_mode` → 直接投影，发布 `EVENT_WORK_MODE_CHANGED`
  - `current_node` → 直接投影，同时计算 `workflow_locked`
  - `circuit_file_path` → 投影为 `active_circuit_file`，发布 `EVENT_ACTIVE_FILE_CHANGED`
  - `last_metrics` → 直接投影，发布 `EVENT_METRICS_UPDATED`
  - `iteration_count` → 直接投影，发布 `EVENT_ITERATION_UPDATED`
  - `project_root` → 直接投影
- [ ] **工作流锁定计算**：
  - 锁定条件：`current_node not in ["", "start", "end", "free_work", "user_checkpoint"]`
  - 锁定时发布 `EVENT_WORKFLOW_LOCKED`
  - 解锁时发布 `EVENT_WORKFLOW_UNLOCKED`
- [ ] **与 LangGraph 运行时集成**：
  - 在图执行回调中调用 `on_graph_state_changed()`
  - 每次节点执行完成后触发投影
- [ ] **被调用方**：LangGraph 运行时（图节点执行后）

---

### 7.3 图节点设计 (`application/graph/nodes/`)

> **目录结构**：
> ```
> application/graph/nodes/
> ├── __init__.py
> ├── design_goals_node.py      # 设计目标提取
> ├── initial_design_node.py    # 初始设计生成
> ├── simulation_node.py        # 仿真执行
> ├── analysis_node.py          # 结果分析
> ├── user_checkpoint_node.py   # 用户检查点
> ├── action_node.py            # 行动处理
> ├── free_work_node.py         # 自由工作
> └── undo_node.py              # 撤回处理
> ```



#### 7.3.1 `design_goals_node.py` - 设计目标提取节点

- [ ] **文件路径**：`application/graph/nodes/design_goals_node.py`
- [ ] **职责**：从用户需求中提取设计目标，保存到文件
- [ ] **执行流程**：
  1. 调用 LLM 提取设计目标
  2. 弹出确认对话框让用户确认/修改
  3. 调用 `DesignService.save_design_goals()` 保存到文件
  4. 返回文件路径和摘要到 GraphState
- [ ] **输出**：
  ```python
  return {
      "design_goals_path": ".circuit_ai/design_goals.json",
      "design_goals_summary": {"gain": ">20dB", "bandwidth": ">10MHz"},
      "current_node": "design_goals"
  }
  ```

#### 7.3.2 `initial_design_node.py` - 初始设计生成节点

- [ ] **文件路径**：`application/graph/nodes/initial_design_node.py`
- [ ] **职责**：根据设计目标生成初始电路代码
- [ ] **执行流程**：
  1. 从 GraphState 获取 `design_goals_path`
  2. 调用 `DesignService.load_design_goals()` 读取设计目标
  3. 调用 LLM 生成电路代码
  4. 通过工具调用创建电路文件
  5. 返回电路文件路径到 GraphState
- [ ] **输出**：
  ```python
  return {
      "circuit_file_path": "amplifier.cir",
      "current_node": "initial_design"
  }
  ```

#### 7.3.3 `simulation_node.py` - 仿真执行节点

- [ ] **文件路径**：`application/graph/nodes/simulation_node.py`
- [ ] **职责**：执行仿真并保存结果到文件
- [ ] **执行流程**：
  1. 从 GraphState 获取 `circuit_file_path`
  2. 调用 `SimulationService.run_simulation()` 执行仿真
  3. 仿真结果自动保存到文件，返回路径和指标摘要
  4. 返回结果路径和摘要到 GraphState
- [ ] **输出**：
  ```python
  return {
      "sim_result_path": ".circuit_ai/sim_results/run_001.json",
      "last_metrics": {"gain": "18dB", "bandwidth": "12MHz"},
      "current_node": "simulation"
  }
  ```

#### 7.3.4 `analysis_node.py` - 结果分析节点

- [ ] **文件路径**：`application/graph/nodes/analysis_node.py`
- [ ] **职责**：分析仿真结果，与设计目标比对，生成历史对比信息供 LLM 决策
- [ ] **执行流程**：
  1. 从 GraphState 获取 `sim_result_path` 和 `design_goals_path`
  2. 调用领域服务加载仿真结果和设计目标
  3. 调用 `IterationHistoryService.get_metrics_trend()` 获取历史指标趋势
  4. 生成历史对比信息（当前指标 vs 上次指标，变化量，是否改善）
  5. 将对比信息作为 LLM 上下文的一部分，调用 LLM 分析结果并生成改进建议
  6. 调用 `IterationHistoryService.check_stagnation()` 判断是否停滞
  7. 更新 GraphState 的 `iteration_count` 和 `stagnation_count`
- [ ] **历史对比信息生成**：
  - 调用 `get_metrics_trend(checkpointer, thread_id, metric_key)` 获取各指标的历史值
  - 计算当前值与上一次的差值（delta）
  - 根据设计目标判断变化是否为改善（如增益越高越好，功耗越低越好）
  - 格式化为 LLM 可理解的文本，例如：
    ```
    历史对比：
    - 增益: 18.5dB (上次: 17.5dB, ↑+1.0dB, 改善)
    - 带宽: 12.3MHz (上次: 11.8MHz, ↑+0.5MHz, 改善)
    - 相位裕度: 65° (上次: 68°, ↓-3°, 退化)
    ```
- [ ] **停滞判断逻辑**：
  - 从 SqliteSaver 查询最近 N 次迭代的 `last_metrics`
  - 比较关键指标是否有改善
  - 若连续 N 次无改善，增加 `stagnation_count`
- [ ] **输出**：
  ```python
  return {
      "iteration_count": state["iteration_count"] + 1,
      "stagnation_count": 0,  # 或 +1 如果未改善
      "current_node": "analysis"
  }
  ```
- [ ] **注意**：迭代记录不独立存储，GraphState 本身就是迭代记录，由 SqliteSaver 自动持久化
- [ ] **依赖服务**：
  - `SimulationService.load_sim_result()` - 加载仿真结果
  - `DesignService.load_design_goals()` - 加载设计目标
  - `IterationHistoryService.get_metrics_trend()` - 获取历史指标趋势
  - `IterationHistoryService.check_stagnation()` - 检查优化是否停滞

#### 7.3.5 `user_checkpoint_node.py` - 用户检查点节点

- [ ] **文件路径**：`application/graph/nodes/user_checkpoint_node.py`
- [ ] **职责**：暂停执行，等待用户确认
- [ ] **执行流程**：
  1. 调用 `SnapshotManager.create_snapshot()` 创建文件快照
  2. **保存追踪上下文到 GraphState**（见阶段 1.5.3.1）
  3. 调用 `interrupt()` 暂停图执行
  4. 等待用户通过 `Command(resume=value)` 恢复
  5. 解析用户意图，更新 GraphState
- [ ] **追踪上下文保存**：
  ```python
  # 在 interrupt() 前保存追踪上下文
  tracing_context = TracingContext.export_to_graph_state()
  return {
      **tracing_context,  # 包含 _trace_id, _last_span_id
      "_trace_checkpoint_count": state.get("_trace_checkpoint_count", 0) + 1,
      "checkpoint_count": state["checkpoint_count"] + 1,
      # ... 其他字段
  }
  ```
- [ ] **输出**：
  ```python
  return {
      "user_intent": "optimize",  # 从 resume value 解析
      "checkpoint_count": state["checkpoint_count"] + 1,
      "_trace_id": TracingContext.get_current_trace_id(),
      "_last_span_id": TracingContext.get_current_span_id(),
      "_trace_checkpoint_count": state.get("_trace_checkpoint_count", 0) + 1
  }
  ```

#### 7.3.6 `action_node.py` - 行动处理节点

- [ ] **文件路径**：`application/graph/nodes/action_node.py`
- [ ] **职责**：根据用户意图执行相应操作
- [ ] **执行流程**：
  1. **从 GraphState 恢复追踪上下文**（见阶段 1.5.3.1）
  2. 从 GraphState 获取 `user_intent`
  3. 根据意图调用 LLM 生成操作（可能包含工具调用）
  4. 执行 Agentic Loop 直到完成（内部自动创建 Sub-Spans，见阶段 3.3.2.5.1）
  5. 更新相关文件路径到 GraphState
- [ ] **追踪上下文恢复**：
  ```python
  async def action_node(state: GraphState, config: RunnableConfig):
      # 优先从 GraphState 恢复（处理 interrupt/resume 场景）
      restored = TracingContext.restore_from_graph_state(state)
      if not restored:
          # 回退到从 config 恢复（处理普通节点调用场景）
          TracingContext.restore_from_langgraph(config)
      
      # 创建节点 Span，标记是否从 checkpoint 恢复
      async with TracingContext.span("action_node", "graph") as span:
          if restored:
              span.add_metadata("resumed_from_checkpoint", True)
              span.add_metadata("checkpoint_count", state.get("_trace_checkpoint_count", 0))
          
          # 执行 Agentic Loop（内部自动创建 Sub-Spans）
          controller = AgenticLoopController()
          loop_state = await controller.run(messages, tools)
          
          # ... 其余逻辑
  ```
- [ ] **输出**：根据操作类型返回更新的文件路径

#### 7.3.7 `undo_node.py` - 撤回处理节点

- [ ] **文件路径**：`application/graph/nodes/undo_node.py`
- [ ] **职责**：恢复到上一个检查点（线性撤回）
- [ ] **执行流程**：
  1. 写入恢复意图日志（RecoveryLogService）
  2. 调用 `SnapshotService.restore_snapshot()` 恢复文件
  3. 通过 `initialize_project` 从磁盘文件重建 GraphState
  4. 清理恢复日志
- [ ] **崩溃恢复**：启动时检查未完成的恢复日志，自动完成或提示用户

---

### 7.4 图结构与路由 (`application/graph/`)

> **目录结构**：
> ```
> application/graph/
> ├── __init__.py
> ├── state.py          # GraphState 定义
> ├── builder.py        # StateGraph 编译
> ├── runtime.py        # 图运行时
> ├── edges.py          # 条件边与路由
> └── nodes/            # 图节点目录
> ```

#### 7.4.1 `edges.py` - 条件边与路由

- [ ] **文件路径**：`application/graph/edges.py`
- [ ] **职责**：定义图的流转逻辑
- [ ] **条件边函数**：
  - `route_by_work_mode(state)` - 根据工作模式路由
  - `route_after_analysis(state)` - 分析后路由（检查 `last_metrics` 是否达标）
  - `route_by_user_intent(state)` - 根据用户意图路由
  - `route_after_action(state)` - 行动后路由（检查是否有文件修改）
  - `route_with_force_resimulate_check(state)` - 带强制重仿真检查的路由（优先级最高）
- [ ] **`force_resimulate` 检查逻辑**：
  - 在 `route_by_work_mode` 和 `route_after_analysis` 开头检查 `state.force_resimulate`
  - 若为 True，直接返回 `"simulation_node"`，跳过其他路由逻辑
  - `simulation_node` 执行完成后返回 `{"force_resimulate": False}` 重置标志



#### 7.4.2 图流转逻辑

```
[用户发送消息]
      ↓
[route_by_work_mode] ─────────────────────────────────────────────┐
      │                                                           │
      │ mode == WORKFLOW                          mode == FREE_WORK
      ↓                                                           ↓
design_goals_node → initial_design_node → simulation_node    free_work_node
     ↑                                         ↓                  │
     │                              ←── analysis_node             │
     │                                         ↓                  │
     │                              [route_after_analysis]        │
     │                                    ↓ 未达成                │
     │                            user_checkpoint_node            │
     │                                    ↓                       │
     │                            [route_by_user_intent]          │
     │        ┌──────────────────────┬──────────┬──────────┐      │
     │        ↓                      ↓          ↓          ↓      │
     │   action_node            accept_node  undo_node    END     │
     │        │                    END          │                 │
     │        ↓                                 │                 │
     │  [route_after_action]                    │                 │
     │    ├─ 有文件修改 → simulation_node       │                 │
     │    └─ 无文件修改 → user_checkpoint_node ←┘                 │
     │        │                                                   │
     └────────┴───────────────────────────────────────────────────┘
```

#### 7.4.3 `builder.py` - StateGraph 编译

- [ ] **文件路径**：`application/graph/builder.py`
- [ ] **职责**：组装节点和边，编译为可执行图
- [ ] **核心功能**：
  - `build_graph()` - 构建完整的状态图
  - `compile_graph(checkpointer)` - 编译图并绑定 SqliteSaver
- [ ] **编译配置**：
  - 绑定 SqliteSaver 作为检查点器
  - 设置递归限制

#### 7.4.4 `runtime.py` - 图运行时

- [ ] **文件路径**：`application/graph/runtime.py`
- [ ] **职责**：桥接 GUI 与 Graph 执行
- [ ] **核心功能**：
  - `execute_graph(graph, initial_state, config)` - 执行图
  - `stream_events(graph, state)` - 流式获取执行事件
  - `forward_to_gui(event)` - 将事件转发给 GUI
- [ ] **StreamMode 选项**：
  - `"values"` - 每步后输出完整状态
  - `"updates"` - 仅输出节点更新
  - `"messages"` - LLM token 级流式输出

---

### 7.5 与快照子系统的集成

#### 7.5.1 检查点创建流程

```
[图节点执行完成]
       │
       ├─→ 图节点调用领域服务
       │   └─→ 领域服务将数据写入文件
       │       └─→ 返回文件路径
       │
       ├─→ 图节点返回 GraphState 更新
       │   └─→ {"sim_result_path": "...", "last_metrics": {...}}
       │
       ├─→ LangGraph 运行时调用 SqliteSaver
       │   └─→ 保存 GraphState 到 SQLite
       │
       └─→ 在 user_checkpoint_node 调用 SnapshotManager
           └─→ 创建项目文件的增量快照
```

#### 7.5.2 检查点恢复流程（线性撤回）

> **⚠️ 简化设计**：放弃 LangGraph Time Travel 分支机制，采用"文件快照恢复 + GraphState 重建"的线性撤回方案

```
[用户请求回滚]
       │
       ├─→ RecoveryLogService 写入恢复意图日志
       │
       ├─→ SnapshotService.restore_snapshot()
       │   └─→ 恢复项目文件到快照状态
       │
       ├─→ initialize_project() 重建 GraphState
       │   └─→ 从磁盘文件重新构建内存状态
       │
       └─→ RecoveryLogService 清理恢复日志
```

---

### 7.6 阶段检查点

#### 7.6.1 架构验证检查项

- [ ] GraphState 包含文件指针和轻量摘要字段
- [ ] 图节点通过领域服务读写文件
- [ ] 图节点通过返回值更新 GraphState
- [ ] 业务数据存储在文件系统中

#### 7.6.2 功能验证检查项

- [ ] 各图节点能正确执行
- [ ] 条件边能正确路由
- [ ] 工作模式切换正常
- [ ] SqliteSaver 正确持久化 GraphState
- [ ] interrupt/resume 机制正常工作

#### 7.6.3 回滚验证检查项

- [ ] SnapshotService 正确恢复项目文件
- [ ] RecoveryLogService 正确记录和清理恢复日志
- [ ] initialize_project 正确重建 GraphState
- [ ] 回滚后系统状态一致
- [ ] 崩溃恢复机制正常工作

#### 7.6.4 自由工作模式验证

- [ ] free_work_node 正确处理用户消息
- [ ] Agentic Loop 正确执行工具调用
- [ ] 不触发工作流自动化编排
