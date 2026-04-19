# Agent 主动仿真能力 · 通用 SimulationJob 架构与电路选择 Tab 实施计划

## 背景与目标

Agent 需要新增"主动执行电路仿真"的能力，且定位是与其他 tool 完全解耦的通用能力——必须能对**项目工作区内任意一个已有电路文件**发起仿真，而不是只能仿真用户当前在编辑器里打开的那一个。在此之上，后续还会陆续新增 `read_metrics` / `read_waveform` / `read_output_log` / `read_chart` 等一系列工件读取 tool，它们之间必须互相独立，可以在任意时刻任意顺序被调用，不依赖任何"当前仿真"session 的隐式状态。

同时，仿真面板需要配合通用化改造新增一个"电路选择"tab，让用户能以"按电路聚合"的视角浏览工作区里**所有已有仿真历史的电路**。点击某张电路卡片即把结果面板切到该电路最近一次仿真，而不是永远只能看"最新一条磁盘结果"或"刚跑完那次"。这条交互会和 agent 的多电路并发仿真互相加强：agent 在后台把多个电路各跑一遍，用户在电路选择 tab 里随意切换查看。

项目当前的仿真链路围绕"一次只跑一个电路、UI 展示最后那一次"的单仿真假设写死，散落多处：`SimulationCommandController` 持有单例任务、`SimulationService` 带运行态字段、事件不携带身份标识、`SimulationTab` 信任"最新磁盘文件就是当前所关心"、`ExportPanel` 用实例级 cache 覆盖式写入导出路径、历史索引只在 UI-owned 加载后才刷新。这套假设与"任意电路可被任意来源并发发起仿真、UI 和 agent 互不干扰"**根本冲突**。

此外通过对现有代码的核查，发现**两条更深层的根因缺陷**必须在 job 架构改造之前先解决：

- **磁盘上有两棵互不关联的"仿真结果树"**：`SimulationResultRepository.save()` 写扁平的 `.circuit_ai/sim_results/sim_<ts>_<uuid>.json`（存 `SimulationResult` 本体），`SimulationArtifactExporter.create_project_export_root()` 写结构化的 `simulation_results/<stem>/<ts>/...`（存 metrics / waveform / chart / log 等工件束）——两者之间没有任何权威链接字段，也没有在 bundle 内落 `result.json`。这直接让"`result_path` 主键 → 反查工件"这条 read tool 基座失去地基
- **工件束导出完全耦合 UI widget**：`SimulationExportCoordinator` 里的 `_chart_viewer.export_bundle(...)` / `_waveform_widget.export_bundle(...)` 依赖实时 Qt 组件；Agent 在后台 origin=AGENT_TOOL 的 job 完成后**不会产出**任何 chart / waveform 工件，让 `read_waveform` / `read_chart` 永远读空

因此本计划在 job 架构之前先开第 0 步把"磁盘布局 + 工件束 origin 无关性"这两件事一次性钉死，再做 job 架构改造；否则 Step 14 起的 agent tool 链路即使设计再优雅也没有合格数据源。

本计划的定位：**用一套权威的 `SimulationJob` 并发架构替换旧的单仿真链路，同时新增按电路聚合的选择视图**。所有仿真触发方（UI 编辑器按钮、agent tool、未来可能的批处理）都经过同一条受控通道提交、跟踪、消费各自的结果；UI 面板既能按"当前展示"的精细语义响应自己关心的 job，也能让用户按电路维度在历史结果间自由切换。

---

## 权威术语

- **`SimulationJob`**：一次仿真的权威实体，是仿真生命周期的唯一载体。任何代码想描述"一次仿真"都只能引用它，不许再发明 "is_running" / "current simulation" 之类分散状态。携带 job 标识、来源标签、电路文件、提交时间、终止状态、落盘后的结果路径与导出目录。一旦终止即不可变。

- **`SimulationJobManager`**：管理所有 job 的全局服务。对外职责：提交、查询、等待完成、登记取消意图；对内负责后台并发调度、事件广播、结果持久化回填。**所有发起仿真的通道都必须经过它**。

- **`JobOrigin`**：job 的身份标签，用于 UI 事件过滤、日志归因、未来可能的权限控制。最小集合包含"UI 编辑器按钮"和"agent tool"两类，视为必填身份，不是可选元数据。

- **`result_path`**：仿真结果在项目内的唯一稳定标识，指向 `simulation_results/<电路 stem>/<时间戳>/result.json` 的相对路径。**项目中一切与"某次仿真结果"相关的寻址都归此主键**。第 0 步落实的"单树磁盘布局"保证它与 export_root 同根——`result_path.parent` 即 export_root，无需反推。已在上一轮 artifact header 改造里沉淀的元数据（`# circuit_file` / `# analysis_type` / PNG tEXt chunks）保证这条主键可以被任何 tool 独立自证。

- **`export_root`**：`simulation_results/<stem>/<ts>/` 目录本身，承载所有该次仿真的 artifact（`result.json`、metrics、波形、输出日志、charts、raw_data…）。目录内文件布局视为稳定 schema。`result.json` 与各工件子目录共根存放，Agent 与 UI 对工件束的"取"与"写"完全对称。

- **`artifact bundle`**：`export_root` 目录及其子目录里的全部文件的合称，由第 0 步新建的 **无头工件持久化服务**（`SimulationArtifactPersistence`）在任何 job 完成时一次性写齐，与 job 的 origin 无关。**Agent 的 `read_*` tool 所依赖的磁盘工件就是这份 bundle**。

- **`CircuitResultGroup`**：按电路聚合后的仿真历史单元，承载"电路文件 + 它名下最近若干次仿真"的索引。是"电路选择"tab 与"历史结果"tab 共用的数据上游；不是数据库实体，只是 repository 层按电路 stem 聚合读取磁盘的结果视图。

- **`displayed_job_id` / `displayed_result_path` / `displayed_circuit_file`**：结果面板"当前展示"的三元定位。`displayed_job_id` 仅当展示来自一次刚完成的 job 时非空；来自历史加载或电路选择卡片的场景为空。**"当前展示"由此三元组权威定义**，不再由"最后一次 SIM_COMPLETE 事件"隐式决定。

- **"编辑器活动电路" vs "当前展示电路"**：两个独立概念。前者由编辑器 tab 状态决定，用于 Run 按钮；后者由结果面板三元组决定，用于结果展示。允许不一致——用户可能在编辑器里打开 A.cir、在结果面板里看 B.cir 的历史，这是"电路选择"tab 带来的自然结果，不应强行对齐。

---

## 实施原则

1. **禁止任何形式的兼容层、占位或"降到最小"**：旧的单仿真组件从代码里**物理消失**，而不是"标注 deprecated"、"保留空壳转发"、"改名留 alias"、"加一个 feature flag"。具体禁止：
   - 禁止留下旧类/函数的空实现、`@deprecated` 装饰器、warnings 包装
   - 禁止留下 `from legacy import X as Y` 这类 import shim
   - 禁止保留"缺字段时回落到旧路径"的分支，即使标注 TODO 也不行
   - 禁止把旧 API 实现成调用新 API 的 thin wrapper——旧 API 签名本身必须消失
   - 禁止"新旧并存"式的运行期开关（config / env / 常量都不行）
2. **事件契约一次性升级**：仿真相关事件 payload 一口气加全身份字段，所有订阅者同步改造；之后不再出现"payload 里 job_id 可能缺"的分支。
3. **"最新磁盘结果 = 当前展示"假设必须消失**：repository 按 `st_mtime` 选最新这一语义从 UI 路径里拔除，只作为历史浏览时的辅助排序依据。
4. **Agent tool 与 UI 面板完全隔离**：agent 在后台提交的 job 不得修改 UI 正在展示的内容；UI 面板自己跑的 job 也不得"渗透"进 agent tool 的返回值。
5. **SimulationService 去中心化**：降级为无状态纯执行函数，事件发布与运行态管理全部归 manager。
6. **Agent 仿真 tool 共享唯一寻址协议**：以 `result_path` 为主键，artifacts 文件布局视作稳定 schema；read tool 之间不共享状态。
7. **"电路选择" tab 与 "历史结果" tab 共用单一上游**：两者都基于 `CircuitResultGroup` 聚合读取，不允许各自扫磁盘；任何一条 job 结果落盘，两个视图在下一轮刷新里同时见到。

---

## 清理执行协议（贯穿所有步骤）

每一个触及旧代码的步骤，都必须包含"删除什么"的明确子清单，而不是只写"改造"。执行方遵循以下硬性协议，逐步骤兑现：

- **整文件删除优先于改写**：当一个文件的**全部职责**都被新组件取代（典型：`simulation_task.py`），必须走 `git rm`，而不是留空文件或空类
- **字段/方法删除优先于置空**：被替代的字段/方法整体从类定义里消失；禁止"保留字段但不再使用"的僵尸状态
- **import 清除是步骤的一部分**：每一步改造引入的符号消失后，必须在同一次提交里清掉所有 import 它的地方——允许用 grep 清单自证
- **测试联动删除**：测试里任何针对被删设计的用例在同一步里删除；允许改为新设计的回归测试，但禁止保留"断言旧行为"的用例
- **禁止兼容性注释**：不允许出现"// 兼容旧 XXX"、"# 兼容 legacy YYY"之类注释——如果需要解释为什么这么写，说明设计选择没把旧东西彻底清走
- **每步收尾执行一次局部 grep**：步骤结束后对被删符号做一次 grep，零命中才算完成；命中即回到本步继续清理
- **违反任一协议视为本步未完成**，不得推进到下一步；第 22 步的合并前总 grep 是最后一道关，前面任何步骤偷懒都会在那里暴露

以下每一步的"清理清单"都按此协议书写：每条都必须以"删除 / 整体消失 / 物理移除 / 文件删除 / 字面量清除"这类**可执行动作**开头，而不是"修改"、"优化"这种含糊动词。

---

## 开发步骤

### 第 0 步：磁盘布局统一 + 无头工件持久化服务（先决条件）

目标：把当前割裂的"`.circuit_ai/sim_results/` 扁平 JSON 树"与"`simulation_results/<stem>/<ts>/` 工件束树"物理合并为一棵权威单树；并把"工件束导出"从 UI widget 上剥离成一个无头 domain 服务。两件事一起做才能让后续 job 架构有合格的持久化基座——**任何一件拖到后面做，前 14 步都会在错误地基上发展**。

#### 实施点

- **单树磁盘布局**：项目根下的 `simulation_results/<stem>/<ts>/` 目录成为唯一权威结果容器。`<ts>` 沿用现有 `%Y%m%d_%H%M%S` 语义；若同秒并发碰撞，复用现有 `_ensure_unique_directory` 追加 `(2) / (3)` 后缀，保证 `export_root` 在磁盘上物理唯一
- **bundle 内落 `result.json`**：`SimulationResult` 的序列化从"写到 `.circuit_ai/sim_results/<uuid>.json`"整体迁移到"写到 `simulation_results/<stem>/<ts>/result.json`"，与工件子目录共根；`result.json` 顶部通过既有的电路关联 header 接口自证来源
- **`SimulationResultRepository` 重写寻址语义**：`save(project_root, result) -> str` 返回 `simulation_results/<stem>/<ts>/result.json`（相对项目根）；`load(project_root, result_path)` 继续接受该相对路径；`_generate_result_id` / `sim_<ts>_<uuid>` 式命名整体删除；repository 内部不再依赖 `.circuit_ai/sim_results/`
- **新服务 `SimulationArtifactPersistence`**（位于 `domain/simulation/data/` 下）：职责是"给定 `export_root` + `SimulationResult` + metrics 上下文，**无头**地写齐所有工件类"——metrics、waveform（含 PNG + CSV + header）、chart（按分析类型枚举全部 spec，不依赖 UI 选择）、output_log、analysis_info、raw_data、op_result、`export_manifest.json` 与 `charts.json` manifest 文件。**一律通过 matplotlib 或纯数据写盘，禁止依赖任何 Qt widget**
- **调用链路重定向**：`SimulationService.run_simulation` 在收到 `SimulationResult` 后先调 `SimulationResultRepository.save`（负责 `result.json`），再立即调 `SimulationArtifactPersistence.persist_bundle(export_root, result)`；两者对 `export_root` 严格幂等（都从 `result.file_path + timestamp` 解析）。**`SIM_COMPLETE` 事件只有在两步都落盘后才被发布**——任何 job origin 落盘出的 bundle 完整度一致
- **UI `ExportPanel` 角色彻底收窄**：不再承担"自动导出到项目目录"职责，只保留"手动导出到用户选择的外部目录"职能；`ExportPanel.auto_export_to_project` / `SimulationTab._auto_export_current_result` 整体删除。UI 的 chart 切换、waveform 渲染依然使用 Qt widget，但那是**展示**逻辑，与**落盘**逻辑永久分家
- **并发碰撞确定性回传**：`SimulationArtifactPersistence.persist_bundle` 返回真正使用的 `export_root`（包含 `_ensure_unique_directory` 解析的实际后缀）；service 据此构造最终 `result_path`；manager 把这个路径写入 `SimulationJob` 并随 `SIM_COMPLETE` 事件广播——绝不预测路径

#### bundle 子目录结构保持不变（严格向后兼容）

单树合并只改变"`result.json` 放在哪里"，**绝不改变**已有 bundle 子目录与文件名排布。现状结构视为长期合约，`SimulationArtifactPersistence` 内部仍然调既有的 `simulation_artifact_exporter.export_*` 函数以保证磁盘表现 byte-for-byte 一致。权威清单（每次成功仿真都必须全部存在）：

- `simulation_results/<stem>/<ts>/result.json`（**新增**；原 `.circuit_ai/sim_results/*.json` 迁移到此，内容结构不变）
- `simulation_results/<stem>/<ts>/metrics/metrics.csv` + `metrics.json`
- `simulation_results/<stem>/<ts>/charts/<NN>_<chart_type>.png` + `.csv` + `.json`（`NN` 两位补零；第 20 步会把 chart 枚举全落盘，此处保证文件命名模式不变）
- `simulation_results/<stem>/<ts>/charts/charts.json`（manifest）
- `simulation_results/<stem>/<ts>/charts/current_chart.png`（**保留**；对话附件 `attach_chart_image` 依赖此固定名）
- `simulation_results/<stem>/<ts>/waveforms/waveform.png` + `waveform.csv`
- `simulation_results/<stem>/<ts>/waveforms/current_waveform.png`（**保留**；对话附件 `attach_waveform_image` 依赖此固定名）
- `simulation_results/<stem>/<ts>/output_log/output_log.txt` + `output_log.json`
- `simulation_results/<stem>/<ts>/analysis_info/analysis_info.txt` + `analysis_info.json`
- `simulation_results/<stem>/<ts>/raw_data/raw_data.csv` + `raw_data.json`
- `simulation_results/<stem>/<ts>/op_result/op_result.txt` + `op_result.json`（仅 `.op`）
- `simulation_results/<stem>/<ts>/export_manifest.json`

**自证策略**：一次基线仿真跑两遍——Step 0 改造前与改造后——对 `<ts>` 目录做 `find . -type f | sort` 对比（忽略 `<ts>` 本身的时间戳差、忽略 `result.json` 位置变化），两次列表除增加 `result.json` 外应完全相同；此断言写进第 22 步回归测试。

#### 仿真面板加载链路的回归性保障（读路径一个都不能断）

Step 0 合并磁盘布局后，`SimulationTab` 现有三条"读"路径都必须保持可用。`SimulationResultRepository` 的新寻址语义要**一次性**把它们都迁干净，不在中间状态留"有时读旧树有时读新树"的分叉：

- **刚完成仿真展示**：`EVENT_SIM_COMPLETE` 的 `result_path` 指向新位置（`simulation_results/<stem>/<ts>/result.json`）；`SimulationTab._load_simulation_result(file_path)` 通过 repository `load(project_root, result_path)` 回读 → 同步刷新 metrics / charts / waveforms / op_result 等面板内组件。现有 `SimulationResult` 序列化格式**不变**，面板反序列化代码零改动
- **历史结果 tab**：`SimulationResultRepository.list(project_root)` 扫新树，按 `<stem>/<ts>/result.json` 递归列出；按时间倒序返回——输出给 tab 的 `HistoryResult` 数据形状不变，前端零改动
- **项目打开恢复**："进入项目时展示最近一条历史结果"走的就是 `list` + `load` 复用链路——Step 7 已明确其为"历史加载"语义
- **文件监控**：`EVENT_SIM_RESULT_FILE_CREATED` 的监控路径从 `.circuit_ai/sim_results/` 切到 `simulation_results/**/result.json`；事件 payload `file_path` 即新 `result_path`——`SimulationTab._on_sim_result_file_created` 的 `_should_reload(file_path)` 路径比较逻辑保持不变，因为 `file_path` 依然是 repository 的权威主键

**repository 兼容性边界**：旧树 `.circuit_ai/sim_results/*.json` 视为**不可迁移的废弃格式**——不写迁移脚本、不读旧文件；若用户升级时磁盘仍有旧 JSON，repository `list` 不会返回它们，UI 也不会展示（相当于一次"干净切换"）。这条策略写进升级说明即可，避免为一次性过渡引入脏兼容代码。

#### 对话附件五条链路的回归性保障（写路径一个都不能断）

`SimulationConversationAttachmentCoordinator` 的五个 `attach_*` 方法依赖固定路径 `<export_root>/<category>/<file>`。Step 0 不得破坏这些路径，且要顺便修复其中一个既有的**不良设计**：

- **`attach_metrics` / `attach_output_log` / `attach_op_result`**：期待 `root / metrics|output_log|op_result / <file>.{csv,txt,json}` 存在；Step 0 后它们由 `persist_bundle` 在仿真完成时**必定产出**，`attach_*` 内部的"文件不存在时即时 `export_*` 补打"分支**整段删除**（变成纯 `_ensure_file` 校验后 publish）——持久化不再与附件时机竞争
- **`attach_chart_image` / `attach_waveform_image`**：写 `current_chart.png` / `current_waveform.png` 的职责**保留在附件协调器里**（因为它们捕获的是 UI 当前选中视图，不是所有枚举 chart），但写完后的 PNG tEXt 注入走既有 `simulation_artifact_exporter.inject_png_linkage` 接口——不变
- **顺手修复的不良设计**：现行 `_resolve_export_root(project_root, export_root, result)` 在 `export_root` 为空时会 `create_project_export_root(project_root, result)` **重新建立一个新目录**——这会让附件写到一个新的空 `<stem>/<ts>/` 树里，和仿真面板正在展示的 bundle 脱节。Step 0 把这条兜底**整段删除**，改为：`export_root` 为空时直接从 `displayed_result_path` 反推（`Path(project_root) / result_path).parent`）；反推失败即 `raise ValueError("No active result bundle")`，由 UI 上游捕获提示"请先完成或选中一次仿真"——不再在附件路径下偷偷创建空目录
- **`SimulationTab._get_latest_project_export_root` 的来源**：原先从 `ExportPanel._latest_project_export_root` 读，而该字段由 `auto_export_to_project` 赋值；Step 0 删除 `auto_export_to_project` 后，改由 `SimulationTab` 从"当前展示三元组"（第 7 步定义）的 `displayed_result_path.parent` 直接推导——`ExportPanel` 不再承担这个推导职责，只保留"手动导出目录"这一个内部字段

#### 涉及文件

- **修改**：`domain/simulation/service/simulation_result_repository.py`（`save` / `load` / `list` / `_generate_result_id` 的磁盘定位全面迁到 `simulation_results/` 单树；删除 `SIM_RESULTS_DIR` 引用）
- **修改**：`shared/constants/paths.py`（**删除** `SIM_RESULTS_DIR` 常量；若无其它使用者，连带清理 `__init__.py` 导出）
- **新建**：`domain/simulation/data/simulation_artifact_persistence.py`（`SimulationArtifactPersistence` 服务）
- **修改**：`domain/simulation/data/simulation_artifact_exporter.py`（`create_project_export_root` 迁出 `PROJECT_EXPORTS_DIR_NAME` 概念，改为直接拿 `project_root`；现有 `export_*` 函数按类别拆分成 persistence 服务可调的 pure 函数，禁止保留"只能被 UI 路径调"的签名）
- **修改**：`presentation/panels/simulation/simulation_export_coordinator.py`（**整段删除** `export_to_project_directory` 分支与 `_chart_viewer.export_bundle` / `_waveform_widget.export_bundle` 两处 UI 依赖的调用；`export_to_base_directory` 改为委托 `SimulationArtifactPersistence` 的无头路径）
- **修改**：`presentation/panels/simulation/simulation_export_panel.py`（**整段删除** `auto_export_to_project` / `_latest_project_export_root` 字段的写入语义；改为从 UI-owned job 完成事件里接收由 persistence 生成的 export_root 展示给用户）
- **修改**：`presentation/panels/simulation/simulation_tab.py`（**整段删除** `_auto_export_current_result`；`_on_simulation_complete` 不再触发任何导出；`_get_latest_project_export_root` 改为从 `displayed_result_path.parent` 推导）
- **修改**：`presentation/panels/simulation/simulation_conversation_attachment_coordinator.py`（**整段删除** `_resolve_export_root` 内"`export_root` 为空即 `create_project_export_root` 新建目录"的兜底；`attach_metrics` / `attach_output_log` / `attach_op_result` 里的"文件不存在时即时补打 `export_*`"分支**整段删除**，改为纯 `_ensure_file` 校验）
- **修改**：`domain/services/simulation_service.py`（在 `save` 之后链式调 `SimulationArtifactPersistence.persist_bundle`；第 3 步进一步把 event 发布职责剥离）
- **核对与迁移**：`domain/simulation/service/simulation_result_watcher.py` / `domain/services/snapshot_service.py` / `application/project_service.py` / `application/graph/state.py` / `domain/rag/file_extractor.py` / `domain/simulation/data/simulation_output_reader.py` / `tests/test_simulation_independence.py` / `tests/test_simulation_export_consistency.py` 中所有对 `SIM_RESULTS_DIR` / `.circuit_ai/sim_results/` / `PROJECT_EXPORTS_DIR_NAME` 的引用，一次性收束到新的"`simulation_results/<stem>/<ts>/` 单树"

#### 清理清单

- **常量级删除**：`shared/constants/paths.py` 中的 `SIM_RESULTS_DIR` 常量**物理消失**；`simulation_artifact_exporter.py` 中的 `PROJECT_EXPORTS_DIR_NAME` 整体删除，改为直接用 `"simulation_results"` 字面量的**单处定义**迁到一个 `CANONICAL_RESULTS_DIR` 常量
- **文件级清理**：跑一次 `rg -n ".circuit_ai/sim_results"` 与 `rg -n "\.circuit_ai.*sim_results"` 全仓库零命中；`rg -n "SIM_RESULTS_DIR"` 零命中
- **函数级删除**：`ExportPanel.auto_export_to_project`、`SimulationTab._auto_export_current_result`、`SimulationExportCoordinator.export_to_project_directory` 整函数消失，不留 thin wrapper
- **UI 依赖清除**：`SimulationArtifactPersistence` 模块与其任何调用方都不得 `from PyQt` / `from PySide` / `from presentation`；grep 自证零命中
- **测试级更新**：`tests/test_simulation_independence.py` 中基于"两棵树"假设的 fixture 重写为单树；`tests/test_simulation_export_consistency.py` 中 "auto_export_to_project" 相关 case 重写为"任何 origin 的 job 完成后 bundle 完整"的 case
- **`_generate_result_id` 整函数删除**：`sim_<ts>_<uuid>` 命名方式废弃；结果目录只用 `<stem>/<ts>(/<N>)`，uuid 不再进入磁盘路径
- 执行 grep 自证：`"sim_" +` / `uuid4().hex\[:8\]` 在 repository 零命中；`auto_export_to_project` / `_auto_export_current_result` 在 `presentation/` 零命中

#### 输出

- 磁盘上只剩一棵 `simulation_results/<stem>/<ts>/` 树；任何 job origin 完成后在其中都有 `result.json` + 完整工件束
- `result_path` = `<stem>/<ts>/result.json`，`export_root` = `<stem>/<ts>/`，关系是 `export_root = result_path.parent`——后续 read tool 基座无需反推
- UI 与落盘永久解耦；Agent 后台跑出的 bundle 与 UI 前台跑出的**在磁盘上完全等价**——read tool 对两种 origin 的工件束不可区分

---

### 第 1 步：定义 `SimulationJob` 权威实体

目标：把"一次仿真"从隐式散落的状态聚拢成一个可被引用、传递、查询的对象。

实施点：

- 在 domain 层新增 `SimulationJob` 数据类，承载一次仿真从提交到终止的全部生命周期信息
- 定义 `JobOrigin` 枚举作为身份标签，定义 `JobStatus` 枚举作为状态机状态
- `job_id` 使用随机字符串生成，不使用递增整数，避免向 LLM 或 UI 暗示"顺序语义"
- 终止后的 job 视为不可变：状态转到终止态后其他字段不得再被修改
- 不把 `SimulationJob` 与 Qt 或 EventBus 耦合，它是纯 domain 数据类

涉及文件：

- 新建：`domain/simulation/models/simulation_job.py`

清理清单：

- 禁止在新文件内为旧概念保留占位：不写 `is_running` / `current_simulation` / `task_id` 这类字段，不从 legacy `SimulationTask` 继承任何类型 hint
- 禁止导入 `application.tasks.simulation_task` 的任何符号（包括仅为"类型对齐"的用途）

输出：

- 全项目"一次仿真"的唯一引用对象；后续 manager、事件 payload、agent tool 返回值全部指向它

---

### 第 2 步：建立 `SimulationJobManager` 并发执行底座

目标：把仿真的提交、线程调度、事件广播、结果登记全部集中到一个受控服务，让"发起仿真"只剩一条通道。

实施点：

- 新建 manager 服务，按 `ServiceLocator` 规则注册为全局单例
- 对外职责：提交、查询单个 job、按来源或电路文件过滤列表、等待完成（同步 + 异步双版本）、登记取消意图
- 对内职责：维护活跃 job 索引、终止 job 短期索引（用于刚完成事件的路由）、后台调度
- 内部执行使用线程池，让两个不同电路的 job 真正并发；同一个 job 在自己的 worker 内部仍然同步串行
- `await_completion_async` 的关键实现细节：每个 job 对应一个 `asyncio.Future`，worker 线程完成后必须走 `loop.call_soon_threadsafe(future.set_result, outcome)` 唤醒主事件循环上的 agent tool `await` 点；禁止在后台线程里直接 `set_result`（会触发 `RuntimeError: non-thread-safe`）
- 事件广播由 manager 独占：job 开始、完成、失败各广播一次，payload 填全身份字段。`SimulationService` 不再发事件。EventBus 的 `publish()` 本身已自动把 handler 调度到主线程（见 `shared/event_bus.py` 的 `QMetaObject.invokeMethod`），manager 只管填对 payload，不需再做跨线程编排
- 取消语义：`PENDING` 的 job 直接终止；`RUNNING` 的 job 只登记"取消意图"让 `await_completion_async` 返回 CANCELLED，不强杀 NgSpice 子进程——MVP 的已知边界，不写成永久死结构

涉及文件：

- 新建：`domain/services/simulation_job_manager.py`
- 修改：`shared/service_names.py`（登记新服务名）
- 修改：应用启动时注册 `SVC_EVENT_BUS` 的那条路径，并列注册 `SVC_SIMULATION_JOB_MANAGER`

清理清单：

- 禁止在 manager 内保留任何 "legacy task wrapper" 入口——manager 的公开方法表里只允许 `submit / query / list / await_completion / await_completion_async / cancel`，任何 "run_simulation_compat" / "start_task" / "set_running" 都不得出现
- 禁止对外暴露 `is_running` property（运行态只经 `query(job_id).status`）
- 禁止新 manager 内部持有 `SimulationTask` / `SimulationWorker` 类型的字段或参数
- `SVC_SIMULATION_JOB_MANAGER` 登记后，`shared/service_names.py` 里若仍有旧的 `SVC_SIMULATION_TASK` 之类常量**整行删除**

输出：

- 仓库里唯一能启动仿真的入口
- 可被 UI 和 agent 同时安全调用的并发底座

---

### 第 3 步：`SimulationService` 收束为无状态执行函数

目标：消除运行态字段，移除事件发布职责，让 service 回归"只负责跑一次"的纯函数语义，可以被 manager 的任意 worker 线程重入调用。

实施点：

- 移除 service 身上所有"当前是否正在跑"、"上一次跑的什么文件"相关字段
- 移除 service 对 `EventBus` 的所有引用
- 执行入口职责收窄为：接受文件路径与配置 → 选择执行器 → 跑仿真 → **链式调用 `SimulationResultRepository.save` + `SimulationArtifactPersistence.persist_bundle`**（第 0 步已落地）→ 返回 `(SimulationResult, result_path)` 二元组；`result_path` = bundle 内 `result.json` 的项目相对路径
- **返回签名必须改为二元组**：现有 `run_simulation(...) -> SimulationResult` 显式消失，替换为明确带路径的签名；任何调用方（旧 `SimulationTask`、新 `SimulationJobManager` worker）都必须拿到这对值才继续
- service 允许被多线程并发实例化或调用，内部不得持有任何会被并发读写的可变状态

涉及文件：

- 修改：`domain/services/simulation_service.py`
- 核对：`domain/simulation/service/simulation_result_repository.save(...)` 返回"落盘后的相对路径"这一稳定标识

清理清单：

- **整体删除** service 类上的 `_is_running` 字段与所有对应 property / getter / setter，不允许保留返回常量的兼容实现
- **整体删除** `_last_simulation_file` 字段及其 getter——任何外部查询"上一次跑的啥"的代码都应迁移到 `SimulationJobManager.query`
- **整体删除** service 内部所有 `_publish_*_event` 方法及其调用点；禁止留空 stub 或转发到 manager 的 wrapper
- **物理移除** service 模块顶部的 `_event_bus` 模块级变量与 `_get_event_bus` 函数；整行不留
- **import 清理**：service 模块不得再 import `EventBus` / `event_types` 任何符号
- 执行 grep 自证：`_is_running` / `_last_simulation_file` / `_publish_.*_event` / `_get_event_bus` 在 `domain/services/simulation_service.py` 与其调用方零命中

输出：

- 运行状态的唯一事实源从此归 manager，service 退位为底层可重入执行函数

---

### 第 4 步：删除旧异步调度器 `SimulationTask` / `SimulationWorker`

目标：项目里不再存在第二条仿真异步入口。

实施点：

- `git rm` 整个 `application/tasks/simulation_task.py` 文件——**不允许留空文件、空类、moved-to 注释**
- 全局 grep 消除所有对 `SimulationTask` / `SimulationWorker` 的 import；禁止以 `try/except ImportError` 方式保留 legacy 兼容
- `application/tasks/__init__.py` 若因此变成空模块，评估是否整个包都可删除；能删就删，不留空 `__init__.py` 占位
- 仅存调用点（`SimulationCommandController`）在第 6 步改造为通过 manager 触发——第 6 步之前允许短暂编译失败，不允许在本步添加 thin shim 让旧调用点暂时"跑起来"
- 测试里任何直接引用 `SimulationTask` / `SimulationWorker` 的用例在本步**一并删除**（不迁移到新设计——新设计测试在第 22 步重写）

涉及文件：

- **删除**：`application/tasks/simulation_task.py`
- 扫描并修改：`application/tasks/__init__.py`、`presentation/simulation_command_controller.py`、`tests/` 下相关测试

清理清单：

- **文件级删除**：`application/tasks/simulation_task.py` 物理不存在于仓库
- **符号级删除**：`SimulationTask` / `SimulationWorker` / `SimulationTaskSignals`（如存在）在全仓库零命中
- **import 清除**：`from application.tasks.simulation_task import` 在全仓库零命中；`import application.tasks.simulation_task` 同理零命中
- **测试级删除**：`tests/` 下任何 `test_simulation_task*` 文件整体 `git rm`；断言 `SimulationTask.*` 行为的 fixture / parametrize 条目一并删除
- **包级评估**：若 `application/tasks/` 目录因此变空，整个目录 `git rm`
- 执行 grep 自证：上述符号串在仓库内 `rg -n` 零命中

输出：

- 仓库内 grep 不到这两个符号，且 `application/tasks/simulation_task.py` 物理不存在

---

### 第 5 步：EventBus 仿真事件契约升级

目标：让"一次仿真发生了什么"可以被任意消费者按 `job_id` 精确 routing，而不是按"最近哪个事件刚到"猜。

实施点：

- `EVENT_SIM_STARTED` / `EVENT_SIM_COMPLETE` / `EVENT_SIM_ERROR` 的 payload 在事件类型文档里一次性明确为带 `job_id` / `origin` / `circuit_file` / `project_root` / `result_path` 等完整身份字段的权威 schema
- 失败事件也带 `result_path`，因为失败仍会落盘日志供 agent 读取
- manager 发事件时严格按 schema 填全，缺字段视为 bug
- 所有订阅者同步改造为"先看 job_id，再决定要不要处理"的 routing 模式；不允许存在"payload 里可能缺 job_id 就回落到老路径"的分支

涉及文件：

- 修改：`shared/event_types.py`（补 schema 说明）
- 扫描并修改：所有订阅 `EVENT_SIM_*` 的点（`SimulationTab`、`SimulationViewModel`、`SimulationCommandController`、`iteration/*`、文件监控链路）

清理清单：

- **整段删除**所有"payload 里没有 `result_path` 就退化扫 `get_latest`"的兜底分支（若扫代码发现此模式，整块删，不是加 TODO）
- **整段删除**任何按 `circuit_file` / 文件 mtime 启发式猜"这是不是我关心的那次"的逻辑
- **字段级删除**订阅者内部用于"记住上一次事件"的 `_last_event_*` 这类私有缓存（已被 `displayed_job_id` 取代）
- **禁止保留**事件 payload 的"可选字段"注释：本次升级后 `job_id / origin / circuit_file / result_path` 四项在 payload 里都是必填，缺字段直接视作 producer bug
- **测试级删除**：任何断言"payload 可以缺 `job_id`"或"缺字段时回落"的测试一并删除
- 执行 grep 自证：`EVENT_SIM_COMPLETE` 所有订阅者入口第一行都应是 `job_id` 过滤语句，否则视为未完成

输出：

- 仿真事件契约收束成唯一版本；所有消费者按身份字段精确匹配

---

### 第 6 步：`SimulationCommandController` 改造为 job 提交方

目标：UI 编辑器的 Run 按钮不再自己持有仿真线程，只负责"提交 job、跟踪自己提交过的 job 的状态"。

实施点：

- 删除控制器身上的单例 task 持有、信号连接、`is_running` 代理查询
- 控制器改为持有一个小集合，登记"本控制器提交过的 job id"——这是它判断"我关心的那次是否在跑/是否完成"的唯一依据
- Run 按钮校验路径（项目已开、活动文件可仿真、脏文件已保存）保持不变；校验通过后调 manager 提交 `origin=UI_EDITOR` 的 job，把返回的 job id 塞进登记集合，立即刷新 UI 状态
- 控制器订阅 `EVENT_SIM_*` 后，handler 入口先按 job id 过滤——不是自己登记过的 id 直接忽略，这样 agent 后台跑的 job 不会误触发 UI 按钮状态变化
- `_build_ui_state` 的"是否正在跑"改为查 manager 里本控制器登记过的 job 的状态
- job 终止后从登记集合移除；失败时仅对自己登记过的 job 弹错误对话框
- MVP 继续保持"UI 同时只提交一个 job"的 UX 策略，但在注释里明确写成 UX policy 而非架构约束——底层 manager 已能并发，UI 只是选择不暴露
- **`SimulationTab` 与 controller 之间禁止新增 signal 或直接方法调用**：两者共同订阅 `EVENT_SIM_*`，各自按身份字段过滤（controller 按自己登记的 job id 集合，tab 按 `origin=UI_EDITOR`——因为 UX policy 保证 UI 同时只有一个 UI-owned job，`origin` 就是 tab 判定"这是不是我该展示的"的权威标签）。这样任何一端被替换都不用改另一端——满足权威单源且解耦

涉及文件：

- 修改：`presentation/simulation_command_controller.py`
- 核对：`presentation/main_window.py` 在构造控制器时能通过 `ServiceLocator` 取到 manager

清理清单：

- **整体删除**控制器的 `_task` 字段（及任何 `_current_task` / `_pending_task` 同语义别名），以及对它的所有信号连接
- **整体删除**原先直接绑定 `SimulationTask` 信号的三个 handler（`_on_task_started` / `_on_task_finished` / `_on_task_failed`）——不允许改成同名方法接 EventBus 后保留旧名作遗留引用入口，必须换成语义清晰的 `_on_sim_*_event(job_id, payload)`
- **字段级删除**控制器里用于代理"是否在跑"的 `is_running` property（`_build_ui_state` 直接查 manager）
- **import 清理**：`simulation_command_controller.py` 不得再 import `SimulationTask` 相关符号
- **测试级删除**：断言"controller 持有 task 实例"的测试用例一并删除
- 执行 grep 自证：`_task` / `SimulationTask` / `is_running` 在本文件零命中

输出：

- 编辑器按钮彻底变成"提交者 + 自己 job 的观察者"，与其他 origin 互不干扰

---

### 第 7 步：`SimulationTab` 绑定"当前展示"三元组，彻底丢弃"最新磁盘兜底"

目标：结果面板只在自己关心的事件发生时刷新，不再被 agent 在后台跑的仿真或文件监控随手改动掉用户正在看的内容。

实施点：

- 面板用"当前展示三元组"（`displayed_job_id` / `displayed_result_path` / `displayed_circuit_file`）作为权威展示定位，替代旧的 `_last_loaded_result_path` 单点
- 三种展示来源各有明确路径：
  1. **UI 提交的 job 完成**：面板独立订阅 `EVENT_SIM_*`，`_on_simulation_started` 见到 `origin=UI_EDITOR` 的 payload 即写入 `displayed_job_id=payload.job_id` 与 `displayed_circuit_file=payload.circuit_file`（UX policy 保证 UI 同时只有一个 UI-owned job，无歧义）；后续匹配 `job_id` 的 `SIM_COMPLETE` 填 `displayed_result_path`
  2. **历史加载**（历史结果 tab + 本计划新加的电路选择 tab）：`displayed_job_id` 显式置空，`displayed_result_path` 与 `displayed_circuit_file` 按选中的历史项填充
  3. **项目打开恢复**：保留"进入项目时展示最近一条历史结果"UX 很方便，但必须明确这是历史加载语义，走同一条历史加载分支，不伪装成事件回调
- `_on_simulation_complete` / `_on_simulation_error` / `_on_simulation_started` 入口一律先按 `job_id` 过滤；不是 `displayed_job_id` 的事件一律忽略
- `_on_sim_result_file_created` 文件监控回调角色重新定位：不负责改变"当前展示"，只负责触发"历史索引刷新"，让两个历史 tab 能看到 agent 在后台刚落盘的仿真
- `ExportPanel` 的"最近项目导出目录"不再跟随 `set_result` 被隐式清空、在 `auto_export_to_project` 时隐式赋值。改为面板收到"我关心的 job 完成"后显式推送；历史加载时也显式推送——确保 export 目录始终与"当前展示三元组"同步
- **两条分支（历史加载 vs job 完成）在代码里视觉可区分**：不共用一个函数的两个分支，而是两个函数各自清晰，只在真正复用的地方（如调 `load_result`）汇合

涉及文件：

- 修改：`presentation/panels/simulation/simulation_tab.py`
- 修改：`presentation/panels/simulation/simulation_export_panel.py`
- 核对：`presentation/panels/simulation/simulation_view_model.py` 是否需要同步按 `job_id` 过滤

清理清单：

- **整段删除** `_load_project_simulation_result` 中"payload 缺 `result_path` 时退化扫磁盘"的分支——整个函数若因此只剩一行调用，整体 inline 到唯一调用点并删除函数；不保留单函数空壳
- **字段级删除** `_last_loaded_result_path` / `_last_loaded_circuit_file` 这类旧单点字段，由"当前展示三元组"完全替代
- **整段删除** `_restore_project_result_after_project_opened` 里对 `get_latest` 的直调——改为走第 8 步的按电路聚合列表；禁止保留"先试 get_latest、失败回退聚合"的双路径
- **整段删除** `ExportPanel._latest_project_export_root` 的"随 `set_result` 隐式清空"逻辑——`set_result` 内不再碰 export 字段；改为面板显式调 `set_latest_export_root(path)`
- **整段删除** `_on_sim_result_file_created` 中"把刚监控到的文件路径设为当前展示"的任何代码——该回调本步起只做一件事：触发历史索引刷新
- **禁止保留**"payload 里 job_id 为空就走老路径"的分支
- **测试级删除**：任何断言"事件到达后面板自动切换展示"的测试一并删除或改写成"只当 job_id 匹配才切换"
- 执行 grep 自证：`_last_loaded_result_path` / `_load_project_simulation_result` / `get_latest` 在 `simulation_tab.py` 与 `simulation_export_panel.py` 零命中

输出：

- 面板"当前展示"三元组由面板自己权威控制；agent 后台跑的仿真不会替换用户正在看的结果

---

### 第 8 步：`simulation_result_repository` 从"最新优先"降级为"按电路聚合"

目标：`get_latest` 不再作为 UI 面板的"当前"入口；按电路聚合的读取成为历史结果 tab 与电路选择 tab 的共同上游。

实施点：

- repository 新增"按电路聚合列表"职责：扫 `simulation_results/<stem>/<ts>/` 目录树，按电路 stem 归组，每组内按时间戳倒序，返回若干 `CircuitResultGroup`——每组含电路文件的绝对路径/相对路径、最近若干次仿真的 `result_path` 列表及其元数据摘要（分析类型、时间戳、成功/失败）
- 每条仿真结果的"所属电路文件"直接读取 `result.json` 的 header（电路关联 header 已完成，这份元数据是权威的，不用反向猜 stem 与磁盘文件名）——对同一 stem 但路径被移动或重命名过的仿真依然有效
- 原有扁平 `list(project_root, limit)` 保留但定位明确为"最近 N 条不分组的时间倒序列表"，docstring 标注只能用于历史浏览辅助排序，不得作为"当前结果"判定
- 原有 `get_latest` 保留作为**纯历史辅助**，docstring 写明不得用于判断 UI/agent 关心的仿真；第 7 步 `_restore_project_result_after_project_opened` 改为调用"按电路聚合列表"取第一组的第一条
- 新增按 `result_path` 反推 `export_root` 的解析能力，供 agent tool 与 `ExportPanel` 共用
- 新增按相对路径加载的明确命名方法（如果当前 `load` 已具备语义则核对签名与文档，不具备则补），让 agent tool 与 UI 面板共用

涉及文件：

- 修改：`domain/simulation/service/simulation_result_repository.py`
- 扫描：所有调用 `get_latest` 的地方重新审视定位，该改的改，该删的删

清理清单：

- **调用点级删除**：全仓库扫一遍 `get_latest` 的所有调用点，按"是否是历史辅助语义"二分——纯历史辅助保留，其余**整调用点删除或迁移**；不允许"新旧各留一半"
- **字面量清除**：任何位置手拼 `simulation_results/<stem>/<ts>/` / `Path(...) / "simulation_results"` 的字符串/拼接，**整表达式删除**并替换为 repository 路径解析 API；`frontend/` 与 `presentation/` 与 `domain/llm/` 子树里的此类硬编码零容忍
- **字段级删除**：repository 内部若有 `_latest_cache` / `_last_result_path` 这类"记住最后一次"的字段，整体删除——repository 要保持无状态
- **docstring 硬约束**：`get_latest` 函数首行 docstring 必须是"⚠️ 仅用于历史浏览辅助排序，禁止用于判定 UI/agent 关心的仿真"，且函数体本身不得被 UI 路径调用（静态扫描保证）
- **禁止保留**"掉链时用 stem 反推电路文件名"的启发式代码——电路文件权威字段只来自 `result.json` 的 header
- 执行 grep 自证：`get_latest(` 在 `presentation/` 与 `domain/llm/` 零命中；`"simulation_results"` 字符串字面量仅在 repository 内部出现

输出：

- repository 职责清晰分为三层：按路径加载、扁平时间倒序浏览、按电路聚合浏览
- "当前态判定"彻底从 repository 语义里剥离

---

### 第 9 步：引入"仿真历史索引缓存"的单一刷新链路

目标：让"按电路聚合的历史索引"在任何一条仿真结果落盘后都会被刷新，不再只在 UI-owned 加载成功后顺带刷新；让电路选择 tab 与历史结果 tab 永远共用同一份最新缓存。

实施点：

- 在结果面板内部维护一份"按电路聚合的历史索引"缓存，作为电路选择 tab 与历史结果 tab 共同的数据源
- 明确刷新时机（**覆盖所有 origin 的 job**，不再与"UI 加载哪次结果"耦合）：
  - 项目打开时全量构建一次
  - `EVENT_SIM_COMPLETE` 到达后刷新一次，无论 job 的 origin 是 UI 还是 agent，也无论当前展示是否会被替换——这直接解决"agent 在后台跑完了但电路选择 tab 没更新"的问题
  - `EVENT_SIM_ERROR` 到达后也刷新一次，因为失败结果同样落盘，用户在选择 tab 上应该能看到失败历史
  - `EVENT_SIM_RESULT_FILE_CREATED` 文件监控事件保留作为兜底刷新源（用户手工把外部仿真结果拷贝进 `simulation_results/` 时也能被看到）
  - 项目关闭时清空
- 刷新动作本身只做一次磁盘扫描，得到的聚合结果供两个 view state 序列化复用——不允许两个 tab 各自扫一遍
- 序列化时对两个 tab 各自投射出需要的视图状态：历史结果 tab 仍保留扁平时间倒序列表形态，电路选择 tab 得到的是按电路聚合的卡片数据
- 刷新在主线程执行即可：EventBus 已有跨线程投递到主线程的保障，刷新逻辑假设自己在主线程，不自建锁

涉及文件：

- 修改：`presentation/panels/simulation/simulation_tab.py`
- 新建或重构：历史索引缓存的承载对象可以放在 `simulation_tab.py` 内部作为私有状态，也可抽出为独立 view model 辅助类。从关注点分离角度推荐抽出，但不作强制；关键是刷新链路单点化

清理清单：

- **调用点级删除**：现有 `_refresh_history_results_cache` 所有"只在 UI-owned 加载成功后顺带调用"的触发点**整行删除**，替换为第 9 步规定的事件订阅触发；禁止新旧两条触发路径共存
- **整段删除**任何"拿历史列表时重新调 `simulation_result_repository.list`"的重复扫盘代码；历史视图数据必须来自本步新建的单一缓存
- **字段级删除**旧的 `_history_index` / `_cached_history` 这类按 tab 各自维护的重复缓存（如存在）
- **函数级删除**：若旧 `_refresh_history_results_cache` 在新链路下已无调用点，整函数删除；禁止保留"仅供向后兼容"空壳
- 执行 grep 自证：`simulation_result_repository.list(` 在 `presentation/panels/simulation/` 以外零命中；整个 `presentation/panels/simulation/` 内只允许一处 list 调用作为缓存刷新入口

输出：

- "agent 在后台跑完一次仿真"这个动作的副作用稳定落实到两个 tab 的视图——用户在电路选择 tab 立即看到新卡片或更新的最新时间戳
- 历史索引是仿真生命周期的全局只读副产品，不再被"谁加载了"污染

---  

### 第 10 步：前端与后端同步注册 `circuit_selection` tab

目标：让新 tab 按用户要求的位置（"仿真面板"标题之后、"指标"按钮之前）显示，并与既有 tab 路由机制无缝对接。

实施点：

- 前端类型层：在 `SimulationTabId` union 里新增 `circuit_selection`；在 `TAB_LABELS` 里给它配中文标签"电路选择"；在前端默认的 `available_tabs` 列表首位插入它，让空项目启动时 tab bar 也有这张卡片
- 前端路由层：在 `ActiveResultTabRouter` 里加分支，把 `circuit_selection` 映射到新的 `CircuitSelectionTab` 组件
- 前端空态层：`SimulationLayoutShell` 原本在 `activeTab !== 'history'` 时显示全局空态卡；新 tab 本身就展示历史列表，不需外部空态——把条件改为一个明确的"自含内容 tab 白名单"集合（包含 `history` 和 `circuit_selection`），替换零散的 `!== 'history'` 判断。**这是本次顺手改正的不良设计**：用硬编码"唯一例外"来表达白名单会随 tab 增加持续劣化，改为集合后任何新增"自含内容"tab 的规则统一
- 后端允许列表：`SimulationTab._is_allowed_frontend_tab` 的白名单补入新 tab id
- 后端默认顺序：在 `SimulationFrontendStateSerializer` 里把 `circuit_selection` 置于 `available_tabs` 列表首位（标题条按数组顺序渲染）
- 前后端 `available_tabs` 默认顺序对齐：`circuit_selection → metrics → schematic → chart → waveform → analysis_info → raw_data → output_log → export → history → op_result`

涉及文件：

- 修改：`frontend/simulation-panel/src/types/state.ts`
- 修改：`frontend/simulation-panel/src/components/layout/SimulationTabBar.tsx`（TAB_LABELS 与默认顺序）
- 修改：`frontend/simulation-panel/src/components/layout/SimulationLayoutShell.tsx`（空态白名单集合）
- 修改：`frontend/simulation-panel/src/components/layout/ActiveResultTabRouter.tsx`
- 修改：`presentation/panels/simulation/simulation_tab.py`（`_is_allowed_frontend_tab`）
- 修改：`presentation/panels/simulation/simulation_frontend_state_serializer.py`（默认 `available_tabs` 与序列化入口）

清理清单：

- **整行删除** `SimulationLayoutShell.tsx` 里所有 `activeTab !== 'history'` / `activeTab === 'history'` 式的硬编码判断——替换为 `SELF_CONTAINED_TABS` 白名单集合的 `has(activeTab)` 查询
- **整段删除** `_is_allowed_frontend_tab` 原有"按单一例外列表过滤"的实现——重写为基于集合常量的成员查询，避免每次加 tab 都要改 if/elif
- **字面量清除**：前后端 `available_tabs` 的 tab id 顺序只允许在一个权威常量里定义；禁止"前端写一份、后端写一份"各自维护——若当前两端各一份，在本步抽到 shared schema 或由后端序列化时下发
- **禁止新增** `if activeTab === 'circuit_selection'` 单一分支；所有 tab 路由都走数据驱动的 `TAB_COMPONENT_MAP`（`ActiveResultTabRouter` 本身就是 map 形式，确保新 tab 不破坏这个模式）
- 执行 grep 自证：`'history'` 字符串字面量在 `SimulationLayoutShell.tsx` 以"单一 tab 名"形式零命中（应被集合替代）

输出：

- 新 tab 的前后端类型/路由/白名单骨架打通
- `SimulationLayoutShell` 的空态判断从"单一例外"升级为"白名单集合"，后续扩展不再滑坡

---

### 第 11 步：后端序列化"电路选择"视图状态

目标：让前端拿到结构化的按电路聚合数据，并能识别每张卡片背后对应哪次具体的 `result_path`。

实施点：

- 前端类型定义新增 `CircuitSelectionItemState` 与 `CircuitSelectionViewState`；每张卡片至少包含：电路显示名（通常是 stem）、电路文件相对路径、最近一次仿真的时间戳与分析类型、最近一次仿真的成功/失败状态、最近一次仿真的 `result_path`、历史仿真次数、是否当前展示（`is_current`）
- 把该视图状态加入 `SimulationMainState` 整体状态；`normalizeSimulationState` 补齐 normalizer 与 `EMPTY_SIMULATION_STATE` 的默认值
- 后端 `SimulationFrontendStateSerializer` 的主状态序列化中新增"电路选择视图"字段，数据源直接取第 9 步建立的"按电路聚合历史索引"，不重新扫盘
- `is_current` 的判定：当前展示三元组的 `displayed_circuit_file` 与卡片电路相等时为真；与"具体是哪一次"无关——用户切换卡片是"换电路"，不是"换具体那次"，所以卡片级别的 current 只看电路维度
- 卡片排序：按"该电路最近一次仿真时间戳"倒序，使最近活跃的电路靠前，适应多电路迭代的使用场景
- 卡片数量：展示所有已有仿真的电路，不截断——电路数量天然有限，截断反而让用户找不到"前几天跑过的那个"；每个电路的"历史次数"字段允许用总数或截断值展示

涉及文件：

- 修改：`frontend/simulation-panel/src/types/state.ts`（新类型 + normalizer + 默认值）
- 修改：`presentation/panels/simulation/simulation_frontend_state_serializer.py`
- 修改：`presentation/panels/simulation/simulation_tab.py`（把历史索引取出给 serializer）

清理清单：

- **禁止新增独立数据源**：电路选择视图的数据必须取自第 9 步的单一历史索引缓存；若 serializer 里出现独立的 `_build_circuit_selection_from_disk` / 自行 `list()` 的路径，整段删除
- **字段级去重**：`CircuitSelectionItemState` 的字段如果与历史结果 tab 的 item 有重叠（如 `analysis_type` / `timestamp`），不要各自定义两套命名，共用同一套 snake_case 字段名，避免前端 normalizer 两边 patch
- **禁止保留** `is_current` 基于 `result_path` 的匹配逻辑——该字段只看电路维度（`displayed_circuit_file`），不看"具体哪次"
- 执行 grep 自证：`CircuitSelectionItemState` 的字段构造只出现在 serializer 的一个函数里，不被其他模块 re-construct

输出：

- 前端拿到一份结构清晰的、按电路聚合的权威卡片数据；数据源与历史结果 tab 共用，永远一致

---

### 第 12 步：前端实现"电路选择"tab 的 UI

目标：卡片布局视觉上与现有面板语言完全一致，卡片点击交互无缝接入现有加载链路。

实施点：

- UI 骨架复用现有容器：外层 `tab-surface`、卡片容器用 `content-card`（必要时叠加 `content-card--scrollable`）——与历史结果 tab、指标 tab 保持一致
- 卡片元素直接复用 `history-item` / `history-item--button` / `history-item--active`：它们已定义边框、圆角（`--sim-radius-md`）、内边距（`--sim-gap-sm` / `--sim-pad-inner`）、悬浮态、当前态配色，与历史结果 tab 的卡片视觉完全统一。卡片内部结构放：电路名（`history-item__title` 样式）、次要元数据（`history-item__meta` 样式，如 "最近一次：AC · 昨天 15:42 · 共 5 条仿真"）、右侧极小标记区（当前展示用小徽标，最近一次失败用红色小点）
- 字体字号：标题沿用 `.history-item__title` 的 12px / 600；次要元数据沿用 `.history-item__meta` 的 11px；**不新增字号、不新增字体**
- 圆角沿用 `--sim-radius-md`；卡片间距沿用 `--sim-gap-sm`
- 排版密度：单列纵向排列足够直观，避免跨列碎片化。响应式下空间充裕时允许两列（flex-wrap 或 `ResponsivePane`），保持同样的卡片内边距与间距 tokens
- 卡片顶部保留一条轻量的语义提示行（复用 `history-filter-row` 或 `CompactToolbar`），如 "按最近活跃时间排序"；不提供复杂的筛选/搜索控件，交互克制
- 点击卡片的交互：**完全复用 `bridge.loadHistoryResult(result_path)`**——把卡片的"最近一次 result_path"作为参数传过去。后端走原有 `_load_simulation_result` 路径，但在第 7 步改造后该路径会清空 `displayed_job_id` 并写入新的 `displayed_result_path` / `displayed_circuit_file`，自然满足语义；**不需要新增 bridge 方法**
- 空态：没有卡片时显示"尚无仿真历史，请先运行一次仿真"信息卡，用已有 `surface-state-card surface-state-card--empty` 样式，与 `SimulationLayoutShell` 的全局空态保持视觉一致

设计守则（保持与其他面板一致）：

- 文字色：主 `var(--sim-text-primary)`、次要 `var(--sim-text-secondary)`、成功态 `var(--sim-success)`、失败态 `var(--sim-error)`
- 悬浮与激活态不自己写过渡，完全依赖 `.history-item--button` 的现有行为
- 不加阴影、不加自定义边框色、不加手写渐变——项目视觉风格扁平、克制

涉及文件：

- 新建：`frontend/simulation-panel/src/components/tabs/CircuitSelectionTab.tsx`
- 修改：`frontend/simulation-panel/src/components/layout/ActiveResultTabRouter.tsx`（挂载新组件）
- **不新增 CSS**：本 tab 只复用 `layout.css` 已有类与 tokens

清理清单：

- **禁止新增**局部 `styled-components` / `*.module.css` / 行内 `style={{...}}` 覆盖——本 tab 一行私有样式都不许出现，视觉偏移必须靠现有 tokens 调节
- **禁止新增** bridge 方法：点击卡片的加载必须走既有 `bridge.loadHistoryResult(result_path)`（或后端已有的等价方法），不得增补"仅供 circuit selection 使用"的新接口
- **禁止保留**任何"卡片本地记忆当前选择"的状态——`is_current` 由后端序列化字段单向驱动
- **字体字号硬约束**：`CircuitSelectionTab.tsx` 内不得出现 `font-size` / `font-weight` / `color:` 行内样式字符串；grep 自证零命中
- 执行 grep 自证：`CircuitSelectionTab.tsx` 文件内 `style=` 与 `className="` 之外的字符串字面量零 CSS

输出：

- 一个与现有所有面板视觉语言完全统一、交互回路完全复用的电路选择 tab

---

### 第 13 步：扩展 `ToolContext` 注入 `SimulationJobManager`

目标：给 agent tool 一条干净的依赖通道，不让 tool 直接摸 `ServiceLocator` 全局单例。

实施点：

- `ToolContext` 新增"仿真 job manager"字段；同时新增"当前编辑器活动电路文件"字段，作为 agent 不传 `file_path` 时的回落项（明确标为可选）
- `LLMExecutor.execute_agent` 在构造 `ToolContext` 时从 `ServiceLocator` 取 manager 注入；从会话/编辑器状态读"活动电路文件"注入（无活动文件时留空即可）
- 其他 tool 不受影响

涉及文件：

- 修改：`domain/llm/agent/types.py`
- 修改：`domain/llm/llm_executor.py`

清理清单：

- **调用点级删除**：既有任何 tool 内部 `from presentation.service_locator import ServiceLocator` / `ServiceLocator.get_instance()` 的 import 与调用整体删除；tool 若需要服务，走 `ToolContext` 注入
- **禁止保留**"context 里没有就回落到 ServiceLocator"的双路径——要么 context 提供，要么 tool 认为是调用方 bug 返回 is_error
- **字段级禁止**：`ToolContext` 新增字段一律以**显式类型注解**方式加入；禁止用 `**kwargs` / `context.extras['sim_job_manager']` 这种字符串键的弱类型绕过
- 执行 grep 自证：`domain/llm/agent/tools/**.py` 内 `ServiceLocator` 零命中

输出：

- Tool 层与服务定位解耦；context 变成 tool 的唯一依赖入口

---

### 第 14 步：实现通用 `run_simulation` tool

目标：agent 可以对项目内**任意**电路文件发起仿真；返回值稳定、可被后续任何 artifact 读取 tool 寻址；不污染 UI 展示。

实施点：

- Tool 入参语义：一个可选的电路文件路径（相对 `project_root` 或绝对，但必须在 `project_root` 之下）；MVP 不暴露分析配置——让 LLM 只跑电路文件自带的 analysis 指令，避免 LLM 随手写错复杂的 NgSpice 语法
- 执行语义五阶段：
  1. 解析文件路径：优先 LLM 显式传入；否则回落到 context 的编辑器活动电路；都没有则返回错误明确要求提供路径
  2. 校验：文件存在、扩展名可仿真、物理路径在 `project_root` 之下
  3. 并发守护：查 manager 的活跃 job 列表过滤出 origin 为 agent 的；若已有 agent 正在对同一电路跑，直接返回错误让 LLM 自己决定"等还是换事做"——不排队，把决策权还给 LLM
  4. 提交并等待：调 manager 提交 `origin=AGENT_TOOL` 的 job；在 `await_completion_async` 上等待；等待期间若 agent 被用户取消，`CancelledError` 沿栈抵达，except 分支调 manager 登记取消意图再 raise，与既有取消协议对齐
  5. 结果分派：成功时用紧凑 markdown 描述（分析类型、耗时、核心指标表格），把 `result_path` / `export_root` / `job_id` 放 `details` 字段；失败时 `is_error=True`，告诉 LLM 简要原因并引导它用后续 tool 读完整 output_log；取消时同理
- 返回给 LLM 的 `content` 保持精简：**绝不**塞 raw_data / 波形 / 完整日志——这些由后续 read tool 按需获取
- 在 `tool_factory.create_default_tools` 注册
- 在 `agent_prompt_builder` 的 prompt guidelines 补一段（硬约束语义）：
  - 修改电路文件后用 `run_simulation` 验证
  - **拿到 `result_path` 后，后续同轮任何 `read_*` tool 调用都必须显式传入这个 `result_path`**（禁止依赖基座回落到 `current_file`；`current_file` 回落仅适用于用户刚让你“看一下此刻这个电路的仿真”这种无上下文的新问题）
  - 对同一电路 “跑仿真 → 读结果” 完整闭环结束前不得再起新的 `run_simulation`
  - 此 tool 与编辑器解耦，可对项目内任何电路发起
  - 失败时优先先调 `read_output_log` 诊断，而不是盲重试仿真

涉及文件：

- 新建：`domain/llm/agent/tools/run_simulation.py`
- 修改：`domain/llm/agent/tool_factory.py`
- 修改：`domain/llm/agent/agent_prompt_builder.py`

清理清单：

- **禁止回传大体量数据**：`content` / `details` 里不得出现 `raw_data` / `waveform csv 全文` / `output_log 全文` / `chart png base64`；grep 自证 tool 文件内无 `base64` / `read_text()` 于 `.csv` / `.txt` 的调用
- **禁止 UI 状态读写**：tool 内不得 import 任何 `presentation/*` 模块；也不得调用 `SimulationCommandController` 或触碰 `SimulationTab` / `ExportPanel`
- **禁止"顺手刷新 UI"**：tool 执行结束不主动 emit UI 信号；UI 的刷新由第 9 步的事件订阅链路自然完成
- **禁止保留** `analysis_config` 入参（MVP 明确不暴露）——将来要加时显式新增 task 一并评估
- 执行 grep 自证：`domain/llm/agent/tools/run_simulation.py` 内 `from presentation` 零命中

输出：

- Agent 获得"对项目内任意电路主动发起仿真"的能力
- 返回值与 UI 展示完全隔离，同时与后续 read tool 形成稳定寻址协议

---

### 第 15 步：为后续 artifact 读取 tool 固化寻址协议

目标：未来的 `read_metrics` / `read_waveform` / `read_output_log` / `read_chart` 等 tool 能完全无状态、互相独立，不依赖任何共享 session 就能工作。

实施点：

- **主键统一为 `result_path`**：一个相对 `project_root` 的字符串，指向具体那次仿真的 `result.json`；所有未来 read tool 都以它作为寻址入口
- 每个 read tool 的统一动作：用 repository 的"按路径加载"取 `SimulationResult`；用"按路径反推 export_root"取导出目录；按稳定文件布局 schema 读对应 artifact；调用 artifact 文件顶部 header（或 PNG tEXt chunks）自证来源；返回给 LLM 的 content 压缩为摘要，大体量数据（完整 CSV、完整 PNG base64）**不直接塞**，只给路径或头尾切片
- 稳定文件布局 schema 在本文件显式记录（见下文"稳定 Artifact 布局 Schema"），后续 tool 严禁重新硬编码相对路径字符串，必须统一调 `SimulationArtifactExporter` 暴露的 canonical path helper
- `SimulationArtifactExporter` 在本步补齐各类 artifact 的 canonical path helper；现有导出代码改为"先调 helper 拿路径，再写文件"，消除各 exporter 自己拼路径的重复
- 本步**不实现**具体 read tool——只搭好寻址协议与 helper，把"加一个 read tool 等于写 schema + 调 helper + 压缩返回"三段式框架落实

涉及文件：

- 修改：`domain/simulation/data/simulation_artifact_exporter.py`（补 canonical path helpers；把现有导出逻辑切到 helper）
- 修改：本文件（schema 作为长期合约维护）

清理清单：

- **字面量级删除**：exporter 内部所有现存的 `"metrics"` / `"waveforms"` / `"output_log"` / `"charts"` 之类的目录名字面量，整条收束到 **一个** `_CANONICAL_SUBDIRS` 常量映射；其他函数只从这个映射读取
- **整段删除** exporter 里"自己 `Path(export_root) / "metrics" / "metrics.json"`"这类现场拼路径的逻辑——全部改为调用 helper 返回
- **禁止新增** helper 的"参数自适应分支"：每类 artifact 一个 helper，签名明确（`(export_root, ...) -> Path`），禁止 `kind: str` 多态 helper 用 if/elif 内部分派
- 执行 grep 自证：`"metrics.json"` / `"waveform.csv"` / `"output_log.txt"` / `"charts.json"` 这类字符串字面量**只**出现在 exporter 与本文档 schema 章节；其他文件引用均走 helper

输出：

- 后续每新增一个 artifact read tool 都是三段式工作，没有共享状态、不依赖本次跑了哪个 job

---

### 第 16 步：Read tool 公共基座——寻址、定位、返回值的权威子程序

目标：把"读一次仿真的某一类 artifact"这件事拆成共享子程序，让后续四个 read tool 只负责"读哪一类 + 怎么压缩返回"两件事；让"哪一次仿真"的解析语义集中到一处权威逻辑，任何新加的 read tool 都不许再重发明。

#### 权威的"哪一次仿真"解析链（本基座的核心）

Read tool 之所以能"只读一个电路"而不是乱读，是因为参数优先级链被写成单一权威逻辑。四个 read tool 共用同一条链，结果是一个确定的 `(result_path, SimulationResult, export_root)` 三元组或一条可操作的错误：

1. **显式 `result_path`**（最高优先级，权威主键）：LLM 在上一轮 `run_simulation` 的返回里拿到过它，也可能从 `EVENT_SIM_COMPLETE` 历史上下文里复制过来；给出后直接走 repository 按路径加载，加载失败即 is_error、content 里列出可选 `result_path`
2. **`circuit_file`**（按电路寻址）：LLM 明确知道"我要读哪个电路"但不记得具体是哪一次 → 查按电路聚合历史索引取该电路最近一次 `result_path`
3. **回落到 `ToolContext.current_file`**：LLM 两个参数都没给 → 用编辑器当前活动电路兜底；这是"用户一问一答、上下文就是眼下这一个"的自然语义。**注意**：这条回落不应覆盖 LLM 刚在上一轮对另一个电路跑过 `run_simulation` 的情形——prompt guideline 必须把"优先引用上一轮 `run_simulation` 返回的 `result_path`"写成硬约束（见第 14 步 guideline），避免 LLM 因 context fallback 误读别的电路
4. **仍解析不到**（项目未打开 / 目标电路从未仿真 / 路径越界）→ is_error，content 列出"工作区里所有已有仿真历史的电路 + 各自最新 `result_path`"让 LLM 下一轮调用可以基于事实精准修正

三元组一旦定下，本次 tool 调用的全过程**只读这一次仿真**——不跨电路扫、不"顺便"找更新的结果。

**`export_root` 的解析是纯路径运算**（第 0 步单树布局的直接红利）：`export_root = Path(project_root) / result_path).parent`——**绝对不再反推 `<stem>/<ts>/` 或查常量表**；read tool 基座内部禁止出现任何式如 `Path(...) / result.file_path.stem / result.timestamp` 的现场拼装；grep 自证基座文件内 `.timestamp` / `.file_path` 均不参与路径运算

#### 实施点

- 新建 `domain/llm/agent/tools/simulation_artifact_reader_base.py`，承载上述参数解析链、SimulationResult 加载、export_root 反推、artifact 缺失的兜底分派；所有四个 read tool 的 `execute` 首行即调它
- 新增一个 `base_parameters()` 构造器供四个 tool 复用参数 schema，避免四份 `result_path / circuit_file` 字段拷贝；每个 tool 只在上面追加自己专属参数（如 `read_output_log` 的 `section`、`read_chart` 的 `chart_index`）
- 自证步骤：加载到的 `SimulationResult` 元数据与 LLM 传入的 `circuit_file` 做核对，若不一致以 result.json 为准、在返回 content 里显式告知差异，避免 LLM 以为"读错了"而反复重试
- 缺失 artifact 的兜底：目标文件不存在时 is_error，content 建议一个具体的替代 tool（`.op` 分析没 waveform → 提示 `read_op_result` 或 `read_metrics`），让错误路径也给 LLM 清晰的下一步
- 所有 read tool 输出统一以两行自证 header 起：`# result_path: ...` / `# circuit_file: ...`，LLM 即使在长对话里也能一眼看出"这块返回对应的是哪一次仿真"；后续正文才是本 tool 的摘要
- `details` 字段统一形状（只给 UI）：`result_path` / `circuit_file` / `artifact_type` / `artifact_files`（本次读的物理文件相对路径列表）/ `truncation` 压缩信息 / 失败时附 `failure_kind`（`no_result` / `missing_artifact` / `invalid_params` / `load_failed` / `out_of_project` 枚举）
- 基座严禁依赖任何 UI 状态——`displayed_job_id` / `_latest_project_export_root` 之类的面板内态一律不读；read tool 与 UI 面板完全正交

#### 涉及文件

- 新建：`domain/llm/agent/tools/simulation_artifact_reader_base.py`
- 修改：`domain/llm/agent/types.py`（`ToolContext` 里补注入 repository 与"按电路聚合历史索引"的只读 getter；注入方式与第 13 步的 manager 注入对齐）
- 修改：`domain/llm/llm_executor.py`（构造 `ToolContext` 时把 getter 一并传入）
- 修改：`domain/llm/agent/agent_prompt_builder.py`（补段：read tool 的首选参数是上一轮 `run_simulation` 返回的 `result_path`；明确告知 LLM 四个 read tool 共享同一条优先级链，不需要每个 tool 各自学习）

#### 清理清单

- **调用点级删除**：任何 read tool 内调用 `simulation_result_repository.get_latest` / `list` 的代码整行删除，一律改走公共基座；禁止"基座失败时回落到 get_latest"的双路径
- **字面量级删除**：任何 read tool 内出现 `f"{stem}/{ts}/..."` / `Path(...) / "metrics"` 之类自拼相对路径字符串的表达式整体删除，强制走 canonical path helper
- **参数解析唯一化**：四级优先级链（`result_path` / `circuit_file` / `current_file` / 错误）**只在基座里实现一次**；单个 read tool 内禁止再写 `if not result_path: ...` 的参数分支
- **禁止保留**任何 read tool 持有的"缓存上次读过的 result_path"字段——每次调用都重新解析
- **禁止"顺手读相邻 artifact"**：`read_metrics` 不许顺带返回 waveform 摘要、`read_waveform` 不许顺带回 metrics；职责单一
- 执行 grep 自证：`domain/llm/agent/tools/read_*.py` 内 `get_latest(` / `list(` on repository / `"simulation_results"` 字符串字面量零命中

#### 输出

- 四个 read tool 的"读哪一次"语义集中到一处 15 行内的逻辑；单一权威解析链写完后永不重复
- LLM 天然支持的"根据对话上下文挑正确 result_path"能力被基座的参数 schema 与 prompt guideline 放大成"基于事实的选择"，不是猜

---

### 第 17 步：`read_metrics` tool

目标：让 LLM 在一轮调用内拿到某一次仿真的全部性能指标（含 target 与达标判定），不依赖任何 UI 状态。

#### 实施点

- 入口走第 16 步公共基座拿 `(result_path, result, export_root)`
- 读取源优先级：`export_root/metrics/metrics.json`（结构化最优，`data.rows` 一次性全拿到）；缺失时回落到 `metrics.csv`（带自证 header 的纯文本）
- 返回组织成 markdown：顶部两行自证 header → 摘要块（`指标总数 / 带 target 数 / 已达标数 / 未达标数`）→ 主表（列：`display_name | value | unit | target | 状态`；未达标指标置顶；target 为空的指标合并成尾部的"无目标"段落，避免把"没目标"和"未达标"混淆）
- 达标判定语义：直接复用 exporter 产出的 `raw_value` 与 `target` 字符串；如果 target 已被 `MetricTargetService` 规范化为带方向/单位的比较式，基座提供一个只读的判定 util，read_metrics 共用；不在 tool 里重复发明比较逻辑
- 不回传 `raw_value` 浮点原值给 LLM——LLM 视角无用、只增 token
- `metrics.json` 缺失（仿真失败或未产出指标）→ is_error，content 引导 `read_output_log` 诊断
- 输出总量自带行数 cap（500 行），触达时尾部截断并在 content 末尾明确附 `metrics.csv` 绝对路径，方便 LLM 建议用户或自己用 `read_file` 跟进

#### 涉及文件

- 新建：`domain/llm/agent/tools/read_metrics.py`
- 修改：`domain/llm/agent/tool_factory.py`（在 `create_default_tools` 内注册）
- 修改：`domain/llm/agent/agent_prompt_builder.py`（guideline：改完电路跑完 `run_simulation` → 优先用 `read_metrics` 看是否达标；拿到未达标项再决定是否深入 `read_waveform` / `read_output_log`）

#### 清理清单

- **禁止本地比较逻辑**：达标判定只调基座里集中的只读 util；`read_metrics.py` 内禁止出现 `if raw_value > target` / `if raw_value < target` 这类手写判定
- **禁止回传 `raw_value` 浮点原值**——字段一律使用已格式化字符串；grep 自证 tool 文件内 `raw_value` 字段不出现在返回 content 构造中
- **禁止"metrics.json 缺失则现场扫描 result.json 的 metrics 字段"**——缺失即 is_error 引导 `read_output_log`，不做隐式二次数据源
- 执行 grep 自证：`domain/llm/agent/tools/read_metrics.py` 内 `> target` / `< target` / `MetricTargetService` 直接调用零命中（都应通过基座 util）

#### 输出

- LLM 闭环：改电路 → `run_simulation` → `read_metrics` → 比对 target → 决策下一步

---

### 第 18 步：`read_waveform` tool

目标：让 LLM 拿到波形"形状特征"的紧凑摘要，而不是 PNG base64 或全量采样点——同时保留"这张图具体在哪"的路径，给用户/UI 侧留回溯入口。

#### 实施点

- 入口走第 16 步公共基座
- 绝不回传 PNG base64：token 膨胀且 LLM 并不"看图"；只在 `details` 与 content 正文里给 `waveform.png` 的相对路径，声明"图像供用户查看，数值特征在下方表格"
- 数值特征来源：读 `export_root/waveforms/waveform.csv`（自证 header + 数据块），每条信号给一行摘要：`name | 采样点数 | min | max | mean | 初始值 | 末值 | 过零次数 | 峰峰值`
- 额外提供"等距锚点采样"：默认 12~16 个锚点，形态为 `(x, y1, y2, ...)` 的 markdown 小表；给 LLM 一种"粗粒度时序扫视"能力
- 按分析类型轻度定制（在公共基座之上的一个小分派）：
  - `.tran` / `.dc`：上述默认形态
  - `.ac`：锚点改为对数频率采样；把 bandwidth / gain margin / phase margin 这类派生量**直接引用 `metrics.json` 的条目**而不在 read_waveform 里独立计算，避免重复逻辑漂移
- `export_root/waveforms/` 缺失（.op 分析等）→ is_error，引导 `read_op_result` 或 `read_metrics`
- 采样点数极大时（>10 万行）只扫一遍算统计量，不把 CSV 全体塞进内存；仅读前/后两段 + 均匀跳采取锚点

#### 涉及文件

- 新建：`domain/llm/agent/tools/read_waveform.py`
- 修改：`domain/llm/agent/tool_factory.py`（注册）
- 修改：`domain/llm/agent/agent_prompt_builder.py`（guideline：不要为了"看波形"直接让 tool 返回图像；`read_waveform` 给数值特征、图像路径留给最终回复）

#### 清理清单

- **禁止 PNG base64 回传**：tool 文件内禁止 `base64` / `Path(...).read_bytes()` 用于 `.png`；grep 自证零命中
- **series_summary 唯一出处**：统计量 util 定义在基座或共用 helper 里，`read_waveform.py` 与 `read_chart.py` 共用；禁止两份实现
- **禁止全量读入**：超过 10 万行 CSV 必须使用"前后段 + 跳采"策略；grep 自证 tool 内没有 `read_text()` / `readlines()` 把 waveform csv 全读进内存的调用
- **禁止在 `.ac` 分支里重算 bandwidth / gain margin / phase margin**——引用 `metrics.json`；grep 自证 tool 内无 `bandwidth` / `gain_margin` 等本地计算的表达式

#### 输出

- LLM 可用几百 token 读懂一次仿真波形的形状，同时用户还能按路径打开原图

---

### 第 19 步：`read_output_log` tool

目标：让 LLM 读到 NgSpice 原始输出里真正重要的那几十行，而不是几万行原文；支持分级按需精细读取。

#### 实施点

- 入口走第 16 步公共基座
- 读取源优先级：`export_root/output_log/output_log.json`（已经拆好 `lines` + `summary.error_count / warning_count / first_error`，零额外扫描）；缺失时回落到 `output_log.txt` 并现场分级
- 默认返回按重要性分四层：
  1. 自证两行 header
  2. `summary` 块：`total_lines / error_count / warning_count / first_error`，直接复用 json 的 summary 字段
  3. `errors` 段：**全量列出**（工程里错误天然有限，不截断）
  4. `warnings` 段：默认前 20 条，溢出截断并在块尾给"完整列表参见 output_log.txt 路径"
  5. `tail` 段：文件末尾固定 20 行（NgSpice 的收敛/时间步失败信息常压在末尾）
- 参数 `section` 枚举 `errors / warnings / tail / all` 让 LLM 在默认失灵时精细定向；`all` 走复用 `ReadFileTool.truncate_head` 的 2000 行 / 50KB 兜底
- 源文件完全缺失 → is_error 且引导 `read_metrics` 或检查 `run_simulation` 是否成功；不伪装成"空日志读完了"

#### 涉及文件

- 新建：`domain/llm/agent/tools/read_output_log.py`
- 修改：`domain/llm/agent/tool_factory.py`（注册）
- 修改：`domain/llm/agent/agent_prompt_builder.py`（guideline：仿真失败先 `read_output_log` 的默认 section；不要一上来就 `section=all`；`first_error` 可独立引导下一步）

#### 清理清单

- **分级判定唯一出处**：`error_count` / `warning_count` / `first_error` 的判定优先使用 `output_log.json` 的 `summary` 字段；现场分级回落路径只在本 tool 内实现一次，禁止再在 exporter / result repository 侧重复
- **`section=all` 必须走共享截断**：复用 `ReadFileTool.truncate_head` 的 2000 行 / 50KB 上限常量，禁止 tool 内自己写 `if len(lines) > 2000`
- **禁止伪装"空日志读完"**：源文件完全缺失即 is_error，不返回空 summary
- 执行 grep 自证：`domain/llm/agent/tools/read_output_log.py` 内"错误/警告"正则、阈值常量不重复定义——均来自 `output_log.json` 或基座常量

#### 输出

- LLM 能在一轮调用内拿到"够诊断"的日志信息，需要时再二次 `section=all` 读全文

---

### 第 19.5 步：`read_op_result` tool

目标：让 LLM 能单独寻址一次 `.op` 工作点分析的节点电压、支路电流与设备偏置——这是模拟电路调优最高频的问题，但它的数据形态与波形 / 图表 / 日志均不同，不能被 `read_metrics` / `read_waveform` 代替，爱被第 18、19 步的错误分支引用——不单独定义即成死引用。

#### 实施点

- 入口走第 16 步公共基座拿 `(result_path, result, export_root)`
- 读取源优先级：`export_root/op_result/op_result.txt`（带自证 header 的已预处理版）；缺失时回落到 `result.data.op_result` 结构化字段，现场补打成同样 header 版本返回——两者语义完全等价，减少 LLM 波动
- 分三段返回：自证 header → `nodes` 表（`name | voltage | formatted`，按中义排列：电源节点 → 信号路径 → 水平探测节点，不字母序）→ `branches` 表（`device | current | formatted`）→ `devices` 表（`device | operating_region | key_parameters`，仅当 result 里有 device 工作区识别时输出，否则该段整段省略）
- 节点中义排序：债给公共基座的判定 util（`read_metrics` 也可复用于排序同类表），避免本 tool 内自发明
- `export_root/op_result/` 缺失且 `result.data.op_result` 空 → is_error，引导 `read_metrics`（用户可能当初跑的不是 `.op`）

#### 涉及文件

- 新建：`domain/llm/agent/tools/read_op_result.py`
- 修改：`domain/llm/agent/tool_factory.py`（注册）
- 修改：`domain/llm/agent/agent_prompt_builder.py`（guideline：仅对 `.op` 分析使用；AC / TRAN / DC 不要调用此 tool）

#### 清理清单

- **禁止本地节点排序实现**：排序 util 收束到基座，与 `read_metrics` 共享；grep 自证 `read_op_result.py` 内无 `sort(` 封装
- **禁止回传原始 `result.data.op_result` 结构**给 LLM：只给格式化后的 markdown 表格
- **禁止对 AC / TRAN / DC 分析调用此 tool 时无错误返回**：非 `.op` 的 `result` 一律 is_error、引导 `read_metrics` / `read_waveform`

#### 输出

- 填封第 18、19 步已经引用的 `read_op_result` 显式定义；死引用消失

---

### 第 20 步：`read_chart` tool + 主动改正的 chart 导出不良设计

#### 主动识别到的不良设计

`presentation/panels/simulation/analysis_chart_viewer.py` 的 `export_bundle()` 里 `chart_index = 1` 是硬编码的，只导出 UI 当前选中的那一张 chart，但 `export_root/charts/charts.json` 的 manifest 结构明显是为多图预留的。这是典型的"UI 视选语义漏到导出层"：agent 视角只能看到用户最后一次选过的那张图，其余 chart spec 对它全是黑箱。

同时 `AnalysisChartViewer` 把"给哪张 chart 构造 payload"这件事与"把它画到 UI"强耦合——导致"无头导出"不可能，`SimulationArtifactExporter` 不能独立按 `SimulationResult` 枚举 chart。

#### 改正方向（本步必须顺手做）

- 在 `SimulationArtifactExporter` 侧新增权威入口"按 `SimulationResult` 的 `analysis_type` 枚举该分析理论上可产出的 chart spec"，以及"对给定 spec 构造 chart payload"的无头实现（不依赖任何 Qt / page 对象）
- `AnalysisChartViewer.export_bundle` 退位为 thin 适配层：调用 exporter 的枚举 → 循环对每个 spec 落 `<index>_<type>.{png,csv,json}` → 最终写 `charts.json` 列全部条目；PNG 的无头渲染优先走 matplotlib 直出（与 UI 的 QtChart 渲染完全解耦），保证 agent tool 看到的 chart 集合是"这次仿真理论上有的全部"，不是"用户恰好点过的那一张"
- 现有 UI 的图表显示路径**不变**（用户在 UI 里仍按 spec 切换），只是"落盘"一次性对所有 spec 执行
- 此后 `read_chart` 才是真正可用的

#### `read_chart` tool 本体

- 入口走第 16 步公共基座取 `(result_path, result, export_root)`
- 额外参数：`chart_index`（int，可选）或 `chart_type`（str，可选，二选一）；两者都没给 → 默认返回 `export_root/charts/charts.json` 的 manifest 概览——列出所有 chart 的 `index / type / title`，让 LLM 下一轮精准寻址
- 指定 chart 后读 `<index>_<type>.json` 压缩返回：
  1. 自证两行 header
  2. chart 基础元数据（`type / title / x_label / y_label / series_count / row_count`）
  3. 每条 series 的压缩统计——**复用 `read_waveform` 的 `series_summary` util**（统计量逻辑唯一来源，不漂移）
  4. 等距锚点（默认 12 个）
  5. PNG 相对路径字符串（不塞 base64）
- `details` 带 `chart_index / chart_type / png_path / csv_path / json_path`
- 指定了不存在的 `chart_index` → is_error 且 content 列出 manifest 可用 index；`charts/` 目录整体缺失 → 引导 `read_waveform` / `read_metrics`

#### 涉及文件

- 新建：`domain/llm/agent/tools/read_chart.py`
- 修改：`domain/llm/agent/tool_factory.py`（注册）
- 修改：`domain/simulation/data/simulation_artifact_exporter.py`（新增"按 analysis_type 枚举 chart spec + 无头落盘"接口；补 canonical path helper）
- 修改：`presentation/panels/simulation/analysis_chart_viewer.py`（`export_bundle` 改 thin 适配层；删除 `chart_index = 1` 硬编码）
- 修改：`presentation/panels/simulation/chart_export_utils.py`（若 UI 侧的 `ChartSpec` 构造与无头枚举有公共部分，提炼成共用；不允许 viewer 与 exporter 各自一份）

#### 清理清单

- **字面量级删除**：`analysis_chart_viewer.py` 里的 `chart_index = 1` 硬编码；grep 自证零命中
- **整段删除**"UI 当前选中就是 agent 可见全部"的所有隐含假设与基于 `self._current_spec` / `self.current_chart_index` 等 UI 状态决定"导出哪张"的所有分支
- **整段删除** `export_bundle` 内直接写 manifest 的自我耦合逻辑——manifest 的构造必须全部委托给 exporter 的公共入口；viewer 一行不许自己拼 `charts.json`
- **禁止重复** ChartSpec 枚举逻辑：UI 切换用的 spec 列表与 exporter 无头枚举必须来自同一个 util；grep 自证 `ChartSpec` / `chart_specs_for` 等生成位点仅一处
- **禁止 Qt 依赖泄漏到 exporter**：无头落盘使用 matplotlib 直出或纯 numpy 渲染；`domain/simulation/data/simulation_artifact_exporter.py` 内 `from PyQt` / `from PySide` / `QtChart` 零命中
- **禁止回落"UI 渲染后截图"**：若 matplotlib 直出失败即 is_error，不要降级到"拉起 QApplication 离屏渲染"

#### 输出

- 仿真一次完成 → 该分析所有理论 chart spec 一次性落盘
- Agent 按 index/type 精准寻址；manifest 是探索入口
- UI 与 agent 对 chart 的可见性统一到"exporter 的枚举结果"这个权威

---

### 第 21 步：并发、失败、取消路径的边界收口

目标：让架构在非理想路径下依然可控，而不是只在成功路径上可用。

实施点：

- **并发同文件提交**：manager 层允许；两个 job 的 `result_path` 因时间戳天然互不覆盖，导出目录独立；两个 job id 在日志里都出现便于排查。但 agent tool 层拒绝（第 14 步已说明），避免 LLM 过度重复
- **不同文件并发**：完全允许；manager 线程池同时调度
- **失败 job**：manager 的 worker 捕获所有异常，把 job 标 FAILED，广播 `SIM_ERROR` 时仍填 `result_path`（至少 output_log 落盘让 agent 可 `read_file` 查看）；绝不让 `await_completion_async` 永远 pending
- **NgSpice 崩溃**：同上，视为失败路径
- **取消意图**：PENDING 立即终止；RUNNING 只登记意图让 `await_completion_async` 返回 CANCELLED；NgSpice 子进程不强杀——MVP 已知限制，不写成死结构
- **agent 被停止时 tool 正在等待**：`CancelledError` 沿 await 栈上抛；tool 在 except 分支登记取消意图再 raise
- **事件 payload 缺字段**：不兜底，直接 raise 让 bug 暴露在最近的边界

涉及文件：

- 修改：`domain/services/simulation_job_manager.py`
- 修改：`domain/llm/agent/tools/run_simulation.py`

清理清单：

- **禁止"`_is_running` 兜底"**：manager 内禁止恢复全局忙标志；并发判定完全由"job state + origin"在 manager 里决定
- **禁止 silent swallow**：worker 异常必须写入 job `error_message` 并广播 `SIM_ERROR`，禁止 `except Exception: pass` 或只打 log 不改状态
- **失败事件也必须带 `result_path`**：即使只有 output_log 落盘——manager 里构造 `SIM_ERROR` payload 的代码路径必须从 SimulationService 拿到已落盘路径；禁止 `result_path=None` 的失败事件
- **取消语义单一来源**：`CancelRequested` 标志只在 manager 持有，tool 不得自维护取消状态；grep 自证 `run_simulation.py` 内无 `self._cancelled` / `cancel_event` 字段
- **不挂死防护**：`await_completion_async` 必须在 FAILED / CANCELLED / COMPLETED 三种终态下都立即返回，由单元测试强制覆盖——禁止只覆盖 COMPLETED 分支
- 执行 grep 自证：`SIM_ERROR` 事件 payload 构造处的 `result_path=` 参数从不为 `None` 字面量

输出：

- 失败与取消路径语义明确；并发路径不互相污染；不挂死

---

### 第 22 步：测试与旧设计清除验证

目标：把新架构权威行为钉死在测试里；用 grep 自证旧设计被连根拔除，不仅仅是"被降到最小"。

实施点：

- 新增测试覆盖：
  - `SimulationJobManager` 的并发多 job 完成、同文件并发不覆盖、worker 异常被捕获并标 FAILED、取消语义生效、事件 payload 身份字段完整
  - `run_simulation` tool 的路径解析（显式 / 回落 / 无效）、并发守护、成功/失败/取消三条返回路径、`details` 字段结构
  - `SimulationTab` 在收到不属于 `displayed_job_id` 的事件时**不**刷新展示
  - 历史索引缓存在 agent-owned job 完成后也被刷新；电路选择 tab 的视图状态反映这次新增
  - `CircuitSelectionTab` 点击卡片后 bridge 被调用、`displayed_job_id` 被清空、`displayed_circuit_file` 被切换
  - `ExportPanel` 的"最近导出目录"随"当前展示三元组"变化，不再受 `set_result` 隐式重置
  - Read tool 公共基座的四级优先级链：显式 `result_path` / `circuit_file` / `current_file` 回落 / 都没给 的错误分支；错误分支必须列出可选 `result_path`
  - `read_metrics` 在含 target 的 fixture 上返回未达标指标置顶；`metrics.json` 缺失时引导 `read_output_log`
  - `read_waveform` 的返回 content 永不含 base64；统计列齐全；`.ac` 分析引用 `metrics.json` 而不在自己里面重算派生量
  - `read_output_log` 默认返回含 `errors` 全量 + `warnings` 前 20 条 + `tail` 20 行；`section=all` 触发 `truncate_head` 兜底
  - `read_chart` 无参数时返回 manifest；指定合法 `chart_index` 时 content 含该 chart 的 `series_summary`；不存在的 index 触发 is_error 且列出可用 index
  - Chart 导出多图落盘：对 `.ac` 分析的 fixture 调一次 `export_bundle`，`charts/` 下应生成多条 `<index>_<type>.{png,csv,json}`，`charts.json` manifest 条目数 = 理论 chart spec 数；`analysis_chart_viewer.py` 不再出现 `chart_index = 1` 字面量

- 旧设计清除 grep 清单（合并前必须零命中，或命中点有明确注释解释为何保留）：
  - `SimulationTask` / `SimulationWorker` 符号
  - `SimulationService._is_running` / `_last_simulation_file`
  - `_publish_started_event` / `_publish_complete_event`
  - `_get_event_bus` 在 `simulation_service.py` 里
  - `get_latest` 出现在 `presentation/` 或 `domain/llm/` 子树
  - `EVENT_SIM_COMPLETE` 订阅者没有 `job_id` 过滤分支
  - `_latest_project_export_root` 字段被"随 set_result 隐式清空"的模式
  - 重复扫 `simulation_result_repository.list` 的不同调用点（期望全部汇聚到第 9 步的单一刷新链路）
  - `SimulationLayoutShell` 里 `activeTab !== 'history'` 这种单一例外硬编码
  - `analysis_chart_viewer.py` 里的 `chart_index = 1` 硬编码字面量
  - `domain/llm/agent/tools/read_*.py` 内自拼 `<stem>/<ts>/<category>/` 路径字符串或 `get_latest` 直调

涉及文件：

- 新建测试：`tests/test_simulation_job_manager.py`、`tests/test_run_simulation_tool.py`、`tests/test_simulation_tab_job_routing.py`、`tests/test_circuit_selection_view.py`、`tests/test_simulation_artifact_reader_base.py`、`tests/test_read_metrics_tool.py`、`tests/test_read_waveform_tool.py`、`tests/test_read_output_log_tool.py`、`tests/test_read_chart_tool.py`、`tests/test_chart_multi_export.py`
- 更新/删除：仍引用旧单仿真路径的既有测试
- 合并前执行一次全仓库 grep，把命中结果贴进 PR 描述

输出：

- 新架构关键行为有回归测试保护
- 旧设计在仓库里不存在——不是"被标记废弃"、不是"被包在兼容层里"

---

## 稳定的 Artifact 布局 Schema（长期合约）

以下清单视为项目长期合约，后续所有 artifact 相关的读写都以此为准；不再允许在其他模块里重新硬编码相对路径字符串。所有文件都已带"电路关联 header"（文本类为 `# circuit_file / # file_path / # analysis_type / # executor / # timestamp` 行；PNG 为等价 tEXt chunks），read tool 可据此自证来源；`result.json` 与子目录共根存放，任何 job origin 完成后在磁盘上都存在（第 0 步保障）：

- `simulation_results/<stem>/<ts>/result.json`：**权威入口**，`SimulationResult` 的序列化（第 0 步从 `.circuit_ai/sim_results/*.json` 合并到此）
- `simulation_results/<stem>/<ts>/metrics/metrics.json`、`.../metrics.csv`：指标
- `simulation_results/<stem>/<ts>/waveforms/waveform.png`、`.../waveform.csv`：波形
- `simulation_results/<stem>/<ts>/output_log/output_log.txt`、`.../output_log.json`：NgSpice 输出原文与分级摘要
- `simulation_results/<stem>/<ts>/analysis_info/analysis_info.txt`：分析命令与参数
- `simulation_results/<stem>/<ts>/raw_data/raw_data.csv`、`.../raw_data.json`：原始采样数据
- `simulation_results/<stem>/<ts>/charts/<index>_<name>.{png,csv,json}`：该分析理论上能产出的**全部** chart spec 一次性落盘，`<index>` 从 01 起按枚举顺序递增；agent `read_chart` 按 index 或 type 精确寻址
- `simulation_results/<stem>/<ts>/charts/charts.json`：chart manifest，含所有 chart 的 `index / type / title / files` 条目，是 agent 探索 chart 的入口
- `simulation_results/<stem>/<ts>/op_result/op_result.txt`：仅 .op 分析
- `simulation_results/<stem>/<ts>/export_manifest.json`：bundle 内所有文件清单（由 `SimulationArtifactPersistence` 自动生成）

**磁盘上不应再存在的位置**（第 0 步清掉）：

- `.circuit_ai/sim_results/`：扁平 `sim_<ts>_<uuid>.json`，整树废弃
- 任何 `PROJECT_EXPORTS_DIR_NAME` 的别名常量：收束到单一 `CANONICAL_RESULTS_DIR = "simulation_results"`

---

## 旧设计清除清单（一次性 grep 核验）

合并前以下 grep 必须零命中，或命中点有明确注释解释：

**第 0 步磁盘布局 / 无头持久化**

- `SIM_RESULTS_DIR` 常量与 `sim_results` 字面量（扁平树已废弃）
- `.circuit_ai/sim_results`（整棵树废弃）
- `sim_<ts>_<uuid>` / `uuid4().hex\[:8\]` 命名在 repository 零命中（`_generate_result_id` 已删除）
- `PROJECT_EXPORTS_DIR_NAME` 常量（改为 `CANONICAL_RESULTS_DIR`；单处定义）
- `auto_export_to_project` / `_auto_export_current_result` 在 `presentation/` 零命中（职责迁入 `SimulationArtifactPersistence`）
- `_chart_viewer.export_bundle` / `_waveform_widget.export_bundle` 在 `export_coordinator` 零命中（改为无头导出）
- `from PyQt` / `from PySide` 在 `domain/simulation/data/simulation_artifact_persistence.py` 零命中

**Job 架构 / 事件契约**

- `from application.tasks.simulation_task`
- `class SimulationTask\b` / `class SimulationWorker\b`
- `SimulationService.*_is_running`
- `SimulationService.*_last_simulation_file`
- `_publish_started_event` / `_publish_complete_event`
- `_publish_.*_event` 在 `SimulationService` 内零命中（事件归 manager）
- `EVENT_SIM_COMPLETE` 订阅者里不含 `job_id` 过滤的分支
- controller↔tab 之间自定义 signal 的 `connect`（两者只走 EventBus + origin/job_id 过滤）

**UI / 历史索引 / 结果面板**

- `get_latest` 在 `presentation/` 和 `domain/llm/agent/tools/` 下
- `_latest_project_export_root` 在 `ExportPanel` 之外
- `SimulationTab.*_load_project_simulation_result` 作为事件兜底路径的调用
- `activeTab !== 'history'`（应已改为白名单集合检查）
- `analysis_chart_viewer.py` 里的 `chart_index = 1` 硬编码（应来自 exporter 枚举）

**Read tool 基座**

- `domain/llm/agent/tools/read_*.py` 里任何自拼 `<stem>/<ts>/<category>/...` 字符串或直接 `get_latest` 调用（全部应走公共基座 + canonical path helper）
- `domain/llm/agent/tools/simulation_artifact_reader_base.py` 内 `.timestamp` / `.file_path` 参与路径运算（export_root 只能 `result_path.parent`）
- `read_op_result` 仅在 Step 19.5 与 prompt / agent guideline 中引用；再无"未定义"状态

---

## 非目标（本次明确不做）

- NgSpice 子进程强杀（`cancel(RUNNING)` 只登记意图）
- 为 agent 暴露 `analysis_config` 参数
- 任何把 PNG / 完整波形 base64 塞进 LLM 上下文的 read 路径（`read_waveform` / `read_chart` 永远只给路径 + 数值摘要）
- UI 面板并发展示多个 job 结果的多标签 UX（`SimulationCommandController` 保持"UI 同时一个 job"的 UX policy，底层已解锁）
- 电路选择 tab 的筛选/搜索控件（交互克制；若未来有明确用例再加）

---

## 验收标准

- **磁盘单树**：用户手动或 agent 后台跑完任意一次仿真，磁盘上只在 `<project_root>/simulation_results/<stem>/<ts>/` 下看到 `result.json + metrics/ + waveforms/ + charts/ + output_log/ + analysis_info/ + raw_data/ + op_result/(可选) + export_manifest.json`；`.circuit_ai/sim_results/` 目录不再被创建
- **Agent bundle 完整性**：用 pytest fixture 在 UI 未加载的情况下触发 `run_simulation` tool，完成后磁盘上 bundle 与 UI 跑出的 bundle 在 `find` 列举下文件集合相同（含 charts 全部 spec、含 waveform png）——证明工件束不再与 UI 绑定
- **Bundle 结构向后兼容**：Step 0 改造前后各跑一遍基线仿真，对 `simulation_results/<stem>/<ts>/` 做 `find . -type f | sort`；除新增 `result.json` 与 `charts/` 下多出的枚举 spec 外，两次文件集合**完全一致**（`metrics/metrics.{csv,json}` / `waveforms/waveform.{png,csv}` / `charts/current_chart.png` / `waveforms/current_waveform.png` / `output_log/output_log.{txt,json}` / `analysis_info/analysis_info.{txt,json}` / `raw_data/raw_data.{csv,json}` / `op_result/op_result.{txt,json}` / `export_manifest.json` 一个不少一个不多一字不错）
- **仿真面板加载链路回归**：`SimulationTab` 在"刚完成仿真展示"、"历史结果 tab 选中加载"、"项目打开恢复"、"文件监控触发重载"四个入口上任意一个都能把 `simulation_results/<stem>/<ts>/result.json` 正确回读并刷新面板内 metrics / charts / waveforms / output_log / analysis_info / raw_data / op_result 所有子组件；pytest 用 fake repository + headless SimulationTab 覆盖四条路径
- **对话附件链路回归**：五个 `attach_*` 方法（metrics / chart_image / waveform_image / output_log / op_result）在 `displayed_result_path` 已定的前提下，都能从 bundle 找到固定路径文件并经 EventBus publish 到对话面板；pytest 断言 `EVENT_UI_ATTACH_FILES_TO_CONVERSATION` 的 payload 路径恰好命中 `<export_root>/<category>/<file>`
- **attach 路径不再偷偷新建目录**：在 `displayed_result_path` 为空时调 `attach_*` 必须抛 `ValueError("No active result bundle")`，不得在磁盘上创建新的空 `<stem>/<ts>/` 目录；用 pytest fixture 对改造后的磁盘做 `assert not list((project_root / "simulation_results").iterdir())` 断言
- **UI 与 Agent 并发隔离**：用户在编辑器里跑仿真，agent 在同一项目里对另一个 `.cir` 跑仿真：两者互不阻塞，UI 面板不被 agent 的结果篡改，agent tool 返回的 `result_path` 指向 agent 自己那次仿真
- **电路选择 tab 响应后台 agent job**：agent 在后台跑完一个此前没仿真过的电路：电路选择 tab 下一次刷新出现新卡片，用户点击后结果面板切换到该电路最近一次仿真
- **项目恢复语义清晰**：关闭项目再打开：UI 面板按"历史加载"语义展示最近一条，而不是伪装成"刚完成了一次仿真"；历史结果 tab 与电路选择 tab 都可用
- **编辑器解耦验证**：关闭电路文件后，agent 仍可通过 `run_simulation(file_path="some/other.cir")` 对项目内任意电路发起仿真
- **失败路径可读**：仿真失败时 agent 能拿到 `result_path` 并通过 `read_output_log` 的默认分级读取或 `read_file` 查看 `output_log.txt`
- **无上下文 fallback 的严格错误**：任意一个 read tool 在未给定 `result_path` 且无 `circuit_file`、`current_file` 也为空时，返回的 is_error content 必须是 LLM 可执行的"列出工作区已有仿真电路及各自最新 result_path"的清单；**绝不**返回任何未明确指定的电路数据
- **跨 job 数据零泄漏**：`read_metrics` / `read_waveform` / `read_output_log` / `read_op_result` / `read_chart` 每次执行只覆盖一个 `result_path` 对应的那一次仿真；在并发多电路 fixture 上反复调用各 read tool，跨电路数据不泄漏
- **多 chart 完整可寻址**：`read_chart` 能读到一次 `.ac` 仿真产出的所有 chart spec（bode / phase / ... 至少两类），而不是只有"UI 最后选过的那张"
- **Tab 顺序 + 视觉一致**：仿真面板 tab bar 按 `仿真面板 → 电路选择 → 指标 → 电路 → 图表 → 波形 → 分析信息 → 原始数据 → 输出日志 → 导出 → 历史结果 → 工作点结果` 顺序渲染；电路选择 tab 的视觉语言（字体、字号、圆角、内边距、卡片样式）与历史结果 tab 完全一致
- **LLM 上下文一致性**：prompt guideline 约束生效——LLM 在同轮调用 `run_simulation` 后的 `read_*` 一律显式携带 `result_path`；单元测试用 mock LLM 校验这条硬约束在系统提示中存在且措辞无歧义
- **grep 全清**：仓库内上述 grep 清单全部零命中
- **header 依旧存在**：所有 artifacts 依旧带电路关联 header（上一轮工作已完成，本轮不破坏）
