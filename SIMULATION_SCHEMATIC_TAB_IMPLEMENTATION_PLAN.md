# 仿真面板电路绘制 Tab 开发文档

## 1. 文档目标

本文档用于指导 `circuit_design_ai` 在现有仿真面板中新增一个基于本地 SPICE 电路代码的电路绘制结果面。

本文档只聚焦：

- 具体实施步骤
- 需要新增和修改的代码文件
- 前后端全链路数据流
- 自动布局与交互的实现细节
- 电路图中修改元件值并回写本地 SPICE 文件的权威语义

本文档不包含具体实现代码。

---

## 2. 当前代码事实

以下事实已经基于当前项目代码核对：

- 仿真面板前端入口为 `frontend/simulation-panel/src/app/SimulationApp.tsx`
- 当前顶层结果 tab 由 `SimulationLayoutShell -> SimulationTabBar -> ActiveResultTabRouter` 组织
- `RawDataTab` 已经采用独立挂载方式，在 `SimulationApp.tsx` 中通过 `tab-surface-shell` / `tab-surface-shell--hidden` 保持隐藏挂载
- 前端与 Qt 宿主之间的权威桥接链路为：
  - `presentation/panels/simulation/simulation_tab.py`
  - `presentation/panels/simulation/simulation_web_host.py`
  - `presentation/panels/simulation/simulation_web_bridge.py`
  - `frontend/simulation-panel/src/main.tsx`
  - `frontend/simulation-panel/src/bridge/bridge.ts`
- 仿真主状态的唯一前端序列化入口为 `presentation/panels/simulation/simulation_frontend_state_serializer.py`
- 当前基础 tab 顺序由以下位置共同定义：
  - `simulation_frontend_state_serializer.py` 中的 `_BASE_TABS`
  - `frontend/simulation-panel/src/types/state.ts` 中的 `SimulationTabId` 和 `EMPTY_SIMULATION_STATE.surface_tabs.available_tabs`
  - `frontend/simulation-panel/src/components/layout/SimulationTabBar.tsx` 中的 `TAB_LABELS`
- 当前 `SimulationResult` 与前端 `SimulationResultSummary` 已包含 `file_path` 字段，因此新增电路绘制能力时应优先复用当前结果对象里的源文件路径，而不是重新发明第二套来源定位机制
- 图表与波形页的按钮和画布样式已经具备统一视觉体系，当前可直接参考的类名包括：
  - `chart-header-button`
  - `chart-header-button--accent`
  - `content-card`
  - `content-card--canvas`
  - `toolbar-button`
  - `tab-surface-shell`
  - `tab-surface-shell--hidden`

---

## 3. 本次新增能力的目标与硬约束

### 3.1 必达目标

- 在仿真面板中新增一个新的结果 tab，tab 名称为 `电路`
- 该 tab 必须放在 `指标` 与 `图表` 之间
- 根据当前结果对应的本地 SPICE 文件自动生成电路图
- 电路图必须支持自动布局
- 电路图必须支持基础交互：
  - 平移
  - 缩放
  - Fit
  - 选中元件
  - 查看元件名称、类型、节点、数值
- 电路图中只允许修改元件值，不允许修改电路结构和元件种类
- 图中修改元件值必须直接写回本地工作目录中的 SPICE 文件
- 该写回效果必须与用户手动打开代码文件并修改完全等价

### 3.2 硬约束

- 本地 SPICE 文件是唯一真源
- 前端电路图不得成为第二份业务真相
- 前端不能本地乐观修改权威文档，只能发请求并等待后端回推最新状态
- 图中改值只能做精确文本写回，不允许首版把整个 netlist 重序列化覆盖
- 页面必须尽量简洁，不添加说明性质文字，不添加“此页面用于显示电路图”等冗余提示
- 按钮字号、字体、圆角、内边距、强调色必须参考图表和波形页现有设计

### 3.3 首版非目标

- 不支持改拓扑
- 不支持拖线
- 不支持增删元件
- 不支持改器件类型
- 不支持手工布局
- 不支持直接编辑 `.param` 传播链、复杂表达式、外部库模型内部参数

---

## 4. 推荐技术栈与职责分层

### 4.1 推荐技术栈

- 后端权威层：`Python`
- SPICE 文本解析与写回：自定义解析层 + source span patch
- 自动布局：`ELK.js`
- 前端渲染：`React + SVG`
- 集成宿主：复用现有 `SimulationWebHost + SimulationWebBridge + SimulationTab`

### 4.2 职责分层

#### 后端负责

- 找到当前结果对应的 SPICE 文件
- 解析 SPICE 文本
- 生成前端可消费的电路文档
- 判定哪些元件字段可编辑
- 执行值修改的合法性校验
- 对源文件做精确 patch 并落盘
- 监听外部文件变化并重新解析
- 推送新的权威电路文档和写回结果

#### 前端负责

- 渲染电路图
- 对电路图做自动布局
- 支持平移缩放与选中态
- 展示元件属性面板
- 收集用户输入的新值并发给后端
- 等待后端回推新文档后刷新界面

#### 前端不负责

- 不负责定义元件真实值
- 不负责自行决定写入成功与否
- 不负责持久化 netlist
- 不负责维护第二套结构化电路真相

---

## 5. 需要修改的现有文件

本节只保留文件级摘要，具体实现顺序、状态流和开发提示以第 11 节为准。

### 5.1 后端现有文件

- `presentation/panels/simulation/simulation_backend_runtime.py`：挂载并清理电路文档运行时对象
- `presentation/panels/simulation/simulation_frontend_state_serializer.py`：扩展 `schematic` tab 顺序与独立电路文档序列化
- `presentation/panels/simulation/simulation_web_bridge.py`：增加电路值修改槽、请求规范化和 `schematic` tab 允许集合
- `presentation/panels/simulation/simulation_web_host.py`：缓存并下发 `schematic_document` 与 `schematic_write_result`
- `presentation/panels/simulation/simulation_tab.py`：作为后端总协调器管理权威电路状态、刷新与写回闭环

### 5.2 前端现有文件

- `frontend/simulation-panel/src/types/state.ts`：增加 `schematic` 类型、空状态和 normalize 逻辑
- `frontend/simulation-panel/src/bridge/bridge.ts`：增加 `updateSchematicValue(...)` 和宿主接口声明
- `frontend/simulation-panel/src/main.tsx`：挂载 `schematicDocument` 与 `schematicWriteResult` 本地 state
- `frontend/simulation-panel/src/components/layout/SimulationTabBar.tsx`：插入 `电路` tab 标签
- `frontend/simulation-panel/src/components/layout/ActiveResultTabRouter.tsx`：保持普通结果 tab 分发，避免直接承载大画布 tab
- `frontend/simulation-panel/src/app/SimulationApp.tsx`：用隐藏挂载方式接入 `SchematicTab`
- `frontend/simulation-panel/src/styles/layout.css`：补充电路页样式并复用现有视觉类

---

## 6. 建议新增的文件

### 6.1 后端新增文件

- `domain/simulation/spice/models.py`：定义电路解析与写回所需的数据模型
- `domain/simulation/spice/parser.py`：解析本地 SPICE 文本为结构化中间表示
- `domain/simulation/spice/schematic_builder.py`：生成前端可消费的电路文档
- `domain/simulation/spice/source_patcher.py`：精确写回源文件
- `presentation/panels/simulation/spice_schematic_document.py`：管理电路文档生命周期

### 6.2 前端新增文件

- `frontend/simulation-panel/src/components/tabs/SchematicTab.tsx`：电路页顶层容器
- `frontend/simulation-panel/src/components/schematic/SchematicCanvas.tsx`：SVG 画布与视口交互
- `frontend/simulation-panel/src/components/schematic/SchematicPropertyPanel.tsx`：属性展示与数值编辑
- `frontend/simulation-panel/src/components/schematic/elkLayout.ts`：ELK 输入转换与布局执行
- `frontend/simulation-panel/src/components/schematic/symbolRegistry.tsx`：元件符号注册与回退绘制

---

## 7. 电路文档协议设计

电路文档不应塞进主状态，而应像 raw data 一样走独立权威通道。

### 7.1 后端下发的 `schematic_document`

建议至少包含以下字段：

- `document_id`
- `revision`
- `file_path`
- `file_name`
- `has_schematic`
- `title`
- `components`
- `nets`
- `subcircuits`
- `parse_errors`
- `readonly_reasons`

### 7.2 元件项建议字段

每个元件至少包含：

- `id`
- `instance_name`
- `kind`
- `symbol_kind`
- `display_name`
- `display_value`
- `pins`
- `node_ids`
- `editable_fields`
- `scope_path`
- `source_file`

### 7.3 可编辑字段建议字段

每个字段至少包含：

- `field_key`
- `label`
- `raw_text`
- `display_text`
- `editable`
- `readonly_reason`
- `value_kind`

### 7.4 写回结果 `schematic_write_result`

建议字段：

- `document_id`
- `revision`
- `request_id`
- `success`
- `component_id`
- `field_key`
- `error_message`

---

## 8. 值修改写回的权威语义

这一部分是本功能的核心要求，必须严格执行。

### 8.1 唯一真源

- 本地工作目录中的 SPICE 文件是唯一真源
- 图中修改值，本质上必须等价于用户手动编辑该文件

### 8.2 必须满足的行为

- 直接修改原始 SPICE 文件
- 只替换目标字段对应的文本 token
- 不重写整个 netlist 文本
- 不重排元件顺序
- 不清理用户注释
- 不统一格式化用户手写空格与对齐方式
- 不把表达式自动展开成数值再写回

### 8.3 revision 冲突控制

前端发起修改请求时必须带上当前 `revision`。

如果出现以下情况：

- 用户在编辑器里手动修改了 netlist
- 文件监听已经使后端文档进入新 revision
- 前端仍拿旧 revision 提交

则后端必须：

- 拒绝本次写入
- 返回冲突错误
- 推送最新权威文档
- 让前端提示用户基于最新版本重新修改

### 8.4 首版只读场景

以下场景首版建议只读：

- 值来自 `.param`
- 值来自复杂表达式
- 值来自外部 `.include` 的模型文件
- 写回后无法保证与手工修改语义一致的字段

原则：宁可只读，也不要实现一个看似可编辑但语义不等价的写回路径。

---

## 9. 页面布局与交互设计

### 9.1 页面结构

电路页应采用简洁结构：

- 顶部局部动作区
- 中央大画布区
- 右侧或浮动属性面板（仅在选中元件后显示）

不添加说明区，不添加摘要卡，不添加无意义引导语。

### 9.2 顶部动作区建议按钮

首版建议只保留必要按钮：

- `Fit`
- `重新布局`

可选按钮：

- `定位到源码`
- `刷新`

如果加入额外按钮，必须满足“对当前任务有明确价值”，否则不加。

### 9.3 视觉设计要求

电路页必须遵循图表与波形页已经建立的视觉规范。

直接参考：

- `ChartTab.tsx`
- `WaveformTab.tsx`
- `layout.css` 中的 `chart-header-button`
- `layout.css` 中的 `content-card--canvas`

具体要求：

- 按钮高度、字号、字体、圆角、横向内边距与 `chart-header-button` 保持一致
- 画布容器使用 `content-card content-card--canvas` 作为基底
- 面板边框、背景、阴影与现有结果页保持同一密度级别
- 不单独设计一套视觉 token

### 9.4 选中与属性面板

用户点击元件后：

- 元件高亮
- 显示元件属性面板
- 面板显示：
  - 实例名
  - 器件类型
  - 连接节点
  - 当前可见值
  - 可编辑字段列表

编辑方式建议：

- 通过右侧属性面板编辑
- 不建议首版直接在图上 inline 编辑
- 面板中对不可编辑字段显示只读态和原因

---

## 10. 自动布局实现要求

### 10.1 为什么使用 ELK.js

本项目要求自动布局且不手写布局算法，`ELK.js` 是更适合当前需求的布局引擎。

相对于简单 DAG 布局器，它更适合：

- 端口约束
- 正交连线
- 层级关系
- 较复杂电路的可读性

### 10.2 前端布局流程

前端收到新的 `schematic_document` 后：

1. 对 `components` 和 `nets` 做规范化
2. 转换为 ELK 的节点、端口、边模型
3. 执行布局
4. 将布局结果缓存到局部 state
5. 用 SVG 渲染最终图形

### 10.3 什么时候重跑布局

必须重跑布局的情况：

- `document_id` 变化
- `revision` 变化
- 用户点击 `重新布局`

不应重跑布局的情况：

- 仅切换到其他 tab 再切回来
- 仅改变当前选中元件
- 仅拖动或缩放视口

这也是为什么 `SchematicTab` 应采用隐藏挂载模式，而不是切 tab 就销毁重建。

---

## 11. 全链路实现步骤

本节已经吸收前文的目标、约束、协议、写回语义、UI 设计和自动布局要求。实际开发时，优先按本节逐步推进。

### 第 1 步：先锁定产品边界、tab 位置和唯一真源
 
 目标：在开始实现前，先把这个功能的边界固定，避免后面出现“能画图但语义不对”或“能编辑但不是改源码”的偏移。
 
 实施点：
 
 - 新增结果 tab `schematic`，显示名为 `电路`，位置严格放在 `metrics` 与 `chart` 之间
 - 当前结果对应的本地 SPICE 文件是唯一入口，优先复用 `SimulationResult.file_path`
 - 电路图的生成入口必须直接绑定当前结果对应的本地 SPICE 文件，不能脱离该文件单独构造展示数据
 - 若某些结果缺失有效 `file_path`，前端显示无电路状态，不猜路径，不推断其它文件
 - 本地 SPICE 文件是唯一真源，前端电路图只负责渲染和交互，不得维护第二份权威结构真相
 - 首版非目标在这一阶段直接锁死：不改拓扑、不拖线、不增删元件、不改器件类型、不做手工布局、不直接编辑 `.param` 传播链、复杂表达式、外部 `.include` 模型内部参数
 
 开发提示：
 
 - 这一步不是文档声明，而是后续解析、桥接、UI、写回语义的根约束
 - `simulation_frontend_state_serializer.py`、`state.ts`、`SimulationTabBar.tsx`、`simulation_web_bridge.py`、`simulation_tab.py` 中关于 tab 的允许集合和默认顺序要从一开始就同步到位
 
 输出：
 
 - `schematic` tab 可以被正确激活
 - 后续链路能够根据当前结果对应的本地 SPICE 文件自动生成电路图
 - 后续实现都以“本地 SPICE 文件唯一真源”为基础

 ### 第 2 步：建立后端解析模型，优先保证可定位、可渲染、可写回

目标：把 SPICE 文本解析成既能画图、又能精确回写源码的中间结构，而不是只做一个用于展示的松散模型。

实施点：
 
 - 在 `domain/simulation/spice/models.py` 定义元件实例、节点、子电路、可编辑字段、source span、token span 等基础模型
 - 在 `domain/simulation/spice/parser.py` 解析常见实例行、节点关系、`.subckt`、`.include`
 - 后端在这一阶段承担 SPICE 文本解析和元件字段可编辑性判定，不把这些判定责任下放给前端
 - 为每个元件生成稳定 id，并记录 `scope_path`、`source_file`、节点列表等后续渲染和写回都要用到的信息
 - 在模型层为元件补充图标绘制必需信息：`symbol_kind`、`symbol_variant`、引脚角色、极性标记、首选端口顺序、必要的朝向提示
 - 对常见器件前缀和实例类型做规范映射，让前端最终只消费稳定的符号类别，如电阻、电容、电感、二极管、独立源、地、BJT、MOS、运放、子电路 block、unknown
 - 对有方向性的器件记录语义引脚顺序，例如 `anode/cathode`、`+/−`、`gate/drain/source`、`collector/base/emitter`，避免前端靠名称猜符号方向
 - 为每个值字段记录源码位置，确保后面可以精确定位到原始文本 token
 - 在解析阶段就明确字段编辑能力：哪些字段可直接编辑，哪些字段必须只读，并提前生成 `readonly_reason`
 - 遇到 `.param` 引用、复杂表达式、外部包含文件中的模型值、或任何无法保证“写回效果等同手工编辑”的字段，首版一律只读

开发提示：

- 解析层的第一优先级不是支持所有 SPICE 方言，而是为可支持场景提供稳定 id 和精确 span
- 宁可在首版少支持一部分可编辑字段，也不要牺牲写回语义准确性

输出：

- 结构化中间模型
- 每个元件与字段都有稳定标识、来源文件和源码定位信息

### 第 3 步：生成独立电路文档协议，不把大对象塞进主状态

目标：把解析结果转换成前端可消费的权威 `schematic_document`，并保持它与主状态解耦。

实施点：
 
 - 在 `domain/simulation/spice/schematic_builder.py` 中把解析结果转换为前端协议
 - 后端负责生成前端可消费的电路文档，前端只消费协议，不自行重建第二套结构化真相
 - `document_id` 与 `revision` 只能由后端解析/重解析链路生成，前端不得自行派生、递增或重写
 - 文档层至少包含：`document_id`、`revision`、`file_path`、`file_name`、`has_schematic`、`title`、`components`、`nets`、`subcircuits`、`parse_errors`、`readonly_reasons`
 - 元件层至少包含：`id`、`instance_name`、`kind`、`symbol_kind`、`display_name`、`display_value`、`pins`、`node_ids`、`editable_fields`、`scope_path`、`source_file`
 - 元件协议中除 `symbol_kind` 外，还应提供图标绘制提示，如 `symbol_variant`、`pin_roles`、`port_side_hints`、`label_slots`、`polarity_marks` 或等价 `render_hints`
 - 前端选择元件图标时只能基于后端给出的规范字段，不根据实例名前缀、显示文案或值文本再做二次猜测
 - 未知或暂不支持的器件也必须在协议中明确落成 `symbol_kind = 'unknown'` 或 block 类别，保证前端仍可渲染、选中和显示属性
 - 可编辑字段层至少包含：`field_key`、`label`、`raw_text`、`display_text`、`editable`、`readonly_reason`、`value_kind`
 - 写回结果对象 `schematic_write_result` 至少包含：`document_id`、`revision`、`request_id`、`success`、`component_id`、`field_key`、`error_message`
 - 电路文档必须像 `raw_data_document` 一样走独立推送通道，不能塞进 `SimulationMainState`

开发提示：

- 前端收到的是用于渲染的权威文档，而不是允许本地长期篡改的业务真值
- 文档层如果设计干净，后面的布局、属性面板、写回回执都会更稳

输出：

- 独立的 `schematic_document`
- 独立的 `schematic_write_result`

### 第 4 步：实现源文件精确写回器，把“图中改值 = 手工改代码”做成硬语义

目标：支持对单个值字段做精确文本修改，并保证修改结果与用户手动编辑源码完全等价。

实施点：
 
 - 在 `domain/simulation/spice/source_patcher.py` 中根据 `component_id + field_key + token span` 精确定位目标文本
 - SPICE 文本解析与写回层继续以 `Python` 后端权威实现为主，采用自定义解析 + source span patch，而不是让前端自行推导源码改写结果
 - patch 的目标必须是原始 SPICE 源文件文本本身，不允许先在其它中间表示上完成改写后再整体回灌
 - 前端发起修改请求时必须携带 `documentId`、`revision`、`componentId`、`fieldKey`、`newText`、`requestId`
 - 只替换目标字段对应的文本 token，不重写整个 netlist，不重排元件顺序，不清理用户注释，不统一格式化用户手写空格和对齐
 - 不把表达式自动求值后写回，也不把派生值伪装成用户写下的新文本

- 写回前必须校验当前 `revision`，发现前端 revision 已过期时拒绝写入并返回冲突结果
 - 写回后必须重新解析文件并生成新的 `revision`
 - 回写时保留原编码和原换行风格

开发提示：

- 这一层必须宁可拒绝写入，也不要做近似 patch
- 如果某个字段无法保证“图中改值 = 手工改源码”的语义等价，就不要开放编辑

输出：

- 写回成功或失败结果
- 最新权威电路文档

### 第 5 步：实现电路文档运行时对象，统一加载、监听、重解析和写回

 目标：让电路图像 raw data 一样拥有独立权威状态源，并把加载、监听、重解析、写回都收束在同一个运行时对象里。
 
 实施点：
 
 - 新建 `presentation/panels/simulation/spice_schematic_document.py`
 - `spice_schematic_document.py` 保持为非可视运行时服务对象，不新增第二个结果宿主或额外 Qt 可视页面
 - 负责根据当前结果文件路径加载 SPICE 源文件
 - 负责触发解析和文档构建
 - 只监听当前激活结果对应的源文件及其 `.include` 依赖，不扫描整个工作区；结果切换或清空时及时释放旧 watcher
 - 仅在结果文件切换、依赖文件变化或写回成功后重建文档；tab 切换、选中变化、平移缩放都不触发后端重解析
 - 负责监听当前源文件和相关 `.include` 文件变化，并做必要的防抖刷新
 - 负责接收前端值修改请求并调用 `source_patcher.py`
 - 写回成功触发的主动重解析与文件 watcher 触发的被动重解析要按 `revision` 或文档内容去重，避免同一次修改向前端重复推送
 - 负责产出最新 `schematic_document` 与 `schematic_write_result`
 - 后端在该运行时对象中统一承担合法性校验、外部文件变化监听、重新解析和权威状态推送
 - 在 `simulation_backend_runtime.py` 中挂载这个对象，并在 `clear()` 时一起清空

 开发提示：

- “用户在编辑器里直接改源码” 和 “用户在电路图里改值” 必须最终走到同一条重解析与重推送链路
- 不要做两套互不相认的刷新机制

输出：

- 后端可持续维护的电路文档运行时对象
- 文件变更与图内写回共用的统一同步机制

### 第 6 步：接入 `SimulationTab` / `SimulationWebHost` / `SimulationWebBridge`，让后端成为唯一权威发布者

 目标：打通当前项目已有的 Qt 宿主链路，使电路页完整复用现有仿真面板的权威状态架构。
 
 实施点：
 
 - 集成宿主直接复用现有 `SimulationWebHost + SimulationWebBridge + SimulationTab` 这条链路，不额外引入新的承载壳层
 - `SimulationTab` 继续作为权威协调器，`SimulationWebHost` 只做缓存与 JavaScript 分发，`SimulationWebBridge` 只做前端请求入口与 payload 归一化
 - 在 `simulation_tab.py` 中新增电路文档相关 signal、缓存字段和 getter，并在仿真完成、结果切换、项目切换、外部文件变化时刷新电路文档
 - 在 `simulation_tab.py` 中把电路文档更新路径与 `_update_frontend_payloads(...)` 并列放置，不把主状态与电路文档混成一个大对象
 - 主状态刷新不应隐式重复触发 schematic 文档重发；电路文档和写回回执继续作为独立通道按需下发
 - 在 `simulation_web_host.py` 中缓存 `_schematic_document` 与 `_schematic_write_result`，提供对应的 `set...` / `dispatch...` 下发入口
 - `simulation_web_host.py` 中对 schematic 文档与写回结果也沿用现有 raw data 模式的变更短路，未变化时不重复执行 JavaScript 下发
 - 在 `simulation_web_host.py` 中于 `loadFinished`、前端 `ready`、状态更新、`attach_simulation_tab(...)` 以及清理时同步电路相关状态
 - 在 `simulation_web_bridge.py` 中新增 `schematic_value_update_requested` 及其 slot，并在 `_normalize_tab_id()` 的允许集合中加入 `schematic`
 - `simulation_web_bridge.py` 不负责字段合法性、revision 冲突或写回策略判断，只负责 payload 归一化和 signal 转发
 - 电路相关前端请求仍通过 `SimulationTab.bind_web_bridge(...)` 接入现有统一绑定入口，不新增平行消息总线或第二套 JS 通道
 - 在 `simulation_frontend_state_serializer.py` 中将 `schematic` 插入 `_BASE_TABS`，位置放在 `metrics` 与 `chart` 之间，并新增 `serialize_schematic_document(...)` 与 `serialize_schematic_write_result(...)`

 开发提示：

- 这一段应直接参照当前 raw data 的模式，而不是再发明第三套状态推送风格
- 如果桥接层忘记把 `schematic` 加入允许集合，前端点 tab 时会被回退到 `metrics`

输出：

- 前端能收到独立的权威电路文档
- 前端能向后端发起值修改请求

### 第 7 步：扩展前端根状态与 tab 骨架，先打通状态接线再做页面细节

目标：让前端具备独立消费电路文档的能力，并确保新 tab 顺序与后端权威顺序一致。

 实施点：
 
 - 在 `frontend/simulation-panel/src/types/state.ts` 中加入 `'schematic'`、`SchematicDocumentState`、`SchematicComponentState`、`SchematicEditableFieldState`、`SchematicNetState`、`SchematicWriteResultState` 以及对应的空状态和 normalize 逻辑
 - 在 `state.ts` 中更新 `EMPTY_SIMULATION_STATE.surface_tabs.available_tabs`，默认顺序为 `metrics -> schematic -> chart -> waveform -> analysis_info -> raw_data -> output_log -> export`，再按现有逻辑条件追加 `history`、`op_result`
 - 在 `frontend/simulation-panel/src/bridge/bridge.ts` 中新增 `updateSchematicValue(payload)`，并补充 `setSchematicDocument(...)`、`finishSchematicWrite(...)` 的宿主接口声明
 - 在 `frontend/simulation-panel/src/main.tsx` 中增加 `schematicDocument` 与 `schematicWriteResult` state，并把对应 setter 注册到 `window.simulationApp`
 - `main.tsx` 中对 `schematicDocument` / `schematicWriteResult` 的接线方式应与现有 `rawDataDocument` / `rawDataCopyResult` 保持平行，维持独立 setter，不把 schematic 状态重新折回 `state`
 - 在 `frontend/simulation-panel/src/components/layout/SimulationTabBar.tsx` 中加入 `schematic: '电路'`
 - 在 `frontend/simulation-panel/src/components/layout/ActiveResultTabRouter.tsx` 中保持普通结果页分发逻辑，不直接承载 `SchematicTab`
 - 在 `frontend/simulation-panel/src/app/SimulationApp.tsx` 中为 `SchematicTab` 预留独立挂载位置

 开发提示：

- tab 顺序必须跟随 `available_tabs` 的权威顺序，不要在前端再偷偷维护第二套排序规则
- 这一阶段的目标是先把状态和挂载骨架接通，不急于一次做完完整 UI

输出：

- 电路状态与主状态、raw data 状态并列存在
- 顶层 tab 已具备渲染 `电路` 页的状态基础

### 第 8 步：在 `SimulationApp.tsx` 中独立挂载 `SchematicTab`，保住布局和视口状态

目标：避免电路画布在切换 tab 时被反复销毁，保证布局、缩放、平移和选中状态可持续保留。

 实施点：
 
 - 在 `SimulationApp.tsx` 中引入 `SchematicTab`
 - 增加 `shouldMountSchematicSurface`
 - `shouldMountSchematicSurface` 的判断应与现有 `RawDataTab` 的保活模式保持平行，优先依据 `activeTab === 'schematic'` 或已有 `schematic_document` 决定是否持续挂载
 - 用 `tab-surface-shell` / `tab-surface-shell--hidden` 对电路页做隐藏挂载，复用 `RawDataTab` 已验证可行的模式
 - 调整现有 `activeTab === 'raw_data' ? null : <ActiveResultTabRouter ... />` 的分支逻辑，避免 `schematic` 激活时仍然落回 router 默认的 `MetricsTab`
 - `RawDataTab` 与 `SchematicTab` 都允许在非激活时隐藏挂载，而不是卸载

 开发提示：

- 电路图是大画布场景，切 tab 销毁重建会直接破坏交互体验
- 这一步做对后，后面的 ELK 布局和 SVG 视口管理都会简单很多

输出：
- 切换 tab 后电路页仍能保留布局、缩放、平移和选中状态

### 第 9 步：实现 `SchematicTab` 页面与属性编辑面板，但保持页面极简

目标：在仿真面板里提供一个一眼可用的电路结果页，重点展示电路本体和必要交互，不增加多余说明。

实施点：

- 新建 `SchematicTab.tsx`、`SchematicCanvas.tsx`、`SchematicPropertyPanel.tsx`、`symbolRegistry.tsx`
- `symbolRegistry.tsx` 采用手写 `React + SVG` 符号注册表方案，首版不依赖外部电路图标包，也不引入位图资源作为元件本体
- 首版至少覆盖：电阻、电容、电感、二极管、独立电压源、独立电流源、地、子电路 block、unknown fallback；BJT、MOS、运放、受控源按优先级继续补充
- 页面结构保持简洁：顶部局部动作区 + 中央大画布区 + 选中后才出现的属性面板
- 属性面板优先采用右侧或浮动形式，仅在选中元件后显示，避免常驻占用主画布
- 基础交互至少包括：平移、缩放、`Fit`、选中元件，以及查看元件名称、类型、连接节点和数值
- 前端在这一阶段负责渲染电路图、展示属性面板、收集用户输入的新值并发给后端
- 页面不添加说明区、摘要卡和引导文案，不写“此页面用于显示电路图”等冗余说明
- 顶部首版按钮只保留必要动作：`Fit`、`重新布局`；只有在确有开发价值时才增加 `定位到源码`、`刷新`
- 如果需要加入额外按钮，必须能直接服务当前任务闭环，否则首版不加
- 画布容器使用 `content-card content-card--canvas`
- 按钮视觉直接复用 `chart-header-button`、`chart-header-button--accent`、`toolbar-button`、`tab-surface-shell` 等现有样式语义
- 按钮字号、字体、圆角、内边距、强调色与图表页、波形页保持一致，不单独发明新的视觉 token
- 现有 `resources/icons/*` 只复用于按钮、空状态和错误提示，不作为元件本体符号来源
- 属性面板的边框、背景与阴影密度直接参考现有结果页实现，保持与 `ChartTab.tsx`、`WaveformTab.tsx` 和 `layout.css` 中相关样式同一视觉等级
- 点击元件后高亮选中，并在属性面板中显示实例名、器件类型、连接节点、当前值和可编辑字段列表
- 符号主体、端口和标签应使用统一的 hover / selected / readonly 视觉规则，避免只有外框变化而元件本体无反馈
- 首版只通过属性面板编辑数值，不建议直接在图上 inline 编辑
- 对不可编辑字段显示只读态和 `readonly_reason`

开发提示：

- 前端负责渲染、平移、缩放、选中、收集输入，不负责定义真实值、不负责自行判定写回成功、不负责持久化 netlist
- 前端也不负责维护第二套结构化电路真相，页面刷新必须以后端回推文档为准
- 页面主视觉必须始终是电路图本体，而不是旁枝说明信息

输出：

- 极简且风格统一的电路结果页 UI
- 基础交互与元件信息查看能力可用
- 元件选中与属性编辑交互可用

### 第 10 步：接入 ELK 自动布局与 SVG 渲染，并明确何时重排、何时保持状态

目标：得到可读、稳定、可维护的自动布局结果，避免手写布局算法。

实施点：
 
 - 前端负责基于 `React + SVG` 完成电路渲染，并使用 `ELK.js` 承担自动布局
 - ELK 布局结果、视口、选中态只保存在 `SchematicTab` 前端局部 state 中，不回写后端，也不进入 `SimulationMainState`
 - 符号绘制层先根据 `symbol_kind` 选择 SVG 组件，再把 ELK 输出的节点框、端口坐标和必要朝向提示映射到统一绘制坐标
 - 使用 `ELK.js`，由前端把 `components` 转换为节点、`pins` 转换为端口、`nets` 转换为边
 - 布局结果输出给 SVG 渲染层，显示元件符号、网络线、名称和值标签
 - 每个符号组件使用归一化局部坐标系和稳定的端口锚点；文本长度不能反向拉伸符号几何本体，只影响标签偏移
 - 二端器件优先复用统一左右端口骨架；带方向器件根据 `pin_roles`、极性标记和 `symbol_variant` 决定极板、箭头、三角、晶体管支路方向
 - 标签渲染遵循固定槽位：实例名优先上方或左上，数值优先下方或右下，空间不足时做有限偏移，尽量不压住连线
 - 图标朝向首版只支持少量规范方向和必要镜像，不开放任意自由旋转；unknown 与子电路 block 也必须保持稳定尺寸并参与标准布局
 - 布局输入只来源于最新 `schematic_document`，`schematic_write_result` 和临时 UI 草稿不参与布局计算
 - 布局计算应按前端异步任务处理；若旧 `revision` 的布局尚未完成而新文档已到达，只采纳最新 `document_id + revision` 对应的结果
 - 支持正交连线、层级关系和端口约束

 - 布局重跑条件只包括：`document_id` 变化、`revision` 变化、用户点击 `重新布局`
 - 以下情况不重跑布局：仅切换 tab、仅改变选中元件、仅平移或缩放视口

- 首版布局提示保持简单但明确：输入尽量在左、输出尽量在右、电源优先上方、地优先下方、子电路实例作为 block 处理、未知器件回退为通用方框符号但仍参与标准布局

开发提示：

- 之所以必须采用隐藏挂载，是因为布局结果和视口状态都不应在切 tab 时丢失
- `ELK.js` 在当前需求下比手写布局或简单 DAG 布局更适合，因为它更擅长端口、正交连线和层级关系

输出：

- 自动布局后的稳定电路图
- 切换 tab 后仍能保留当前视口和布局结果

### 第 11 步：打通“图中改值 -> 写回文件 -> 文档刷新 -> 重新渲染”闭环

目标：实现完整双向同步，并让图中编辑的语义严格等同于用户手动编辑本地 SPICE 源码。

实施点：
 
 - 用户选中元件后，在属性面板输入新值
 - 图中交互层只允许修改元件值，不开放电路结构调整、连线改动或器件种类修改
 - 前端调用 `bridge.updateSchematicValue(...)`，只发送请求，不本地乐观修改权威文档
 - 写回请求 payload 保持最小化，只传字段定位和 revision 校验所需信息，不传整个元件树、布局结果或视口状态
 - 前端职责止于发起请求并等待后端回推新文档，不自行决定写入成功与否
 - 前端可以显示提交中状态，但不能把本地草稿当成新的真实值长期保留
 - 后端校验 `revision`、字段可编辑性、文件可写性，然后执行精确 patch
 - 值修改必须直接写回本地工作目录中的 SPICE 源文件，而不是只更新前端显示态或中间缓存
 - 文件落盘后，由统一的重解析链路重新生成文档并推送到前端
 - `schematic_write_result` 仅作为短时回执与错误提示通道，新的 `schematic_document` 才是重新渲染的唯一依据
 - 前端收到新的 `schematic_document` 和 `schematic_write_result` 后，再决定是否重跑布局或局部刷新
 - 最终行为必须满足：本地文件内容真实变化、diff 表现与手工编辑一致、重新仿真会真实受到新值影响

开发提示：

- 这里的核心不是“界面上看起来改成功”，而是“文件层面的实际修改完全成立”
- 如果修改结果不能通过源码 diff 自证与手工编辑一致，就说明实现还不合格

输出：

- 图中值编辑与手工修改源文件语义完全一致
- 形成可重复验证的写回闭环

### 第 12 步：补齐异常、冲突和外部编辑同步，用同一条刷新链路收口

目标：让这个功能在失败路径和并发修改场景下依然可控，而不是只在理想路径上可用。

实施点：
 
 - revision 失效时返回冲突结果，拒绝本次写入，并推送最新权威文档
 - 前端收到冲突结果后，应基于后端刚推送的最新权威文档提示用户重新修改，不继续沿用旧 `revision` 重试
 - 冲突或外部刷新发生后，前端应丢弃基于旧 `revision` 的本地编辑草稿，避免过期状态继续参与交互
 - 文件只读或不可写时明确返回错误
 - 解析失败时显示 compact 错误状态卡，而不是让页面沉默失效
 - 对不可编辑字段持续显示只读原因
 - 对 `.param` 派生值、复杂表达式、外部 `.include` 模型值以及任何无法保证手工改码等价性的字段，首版继续保持只读
- 必须支持以下场景：用户在编辑器里直接修改当前 SPICE 文件、用户修改 `.include` 进来的本地子文件、用户保存后回到仿真面板
- 外部文件变化时，后端文件监听负责触发解析、文档重建、`revision` 更新和前端刷新
- “图中改值后刷新” 与 “外部修改后刷新” 必须共用同一条链路，不能形成两套互不相认的机制

开发提示：
 
- 冲突处理是语义正确性的必要组成部分，不是可选增强项
- 只要后端 revision 已经前进，前端旧 revision 提交就必须被拒绝

输出：

- 完整的异常处理链路
- 文件监听与图中编辑共用的统一同步机制

### 第 13 步：按测试清单做闭环验收，避免“能画但不能维护”

目标：用解析、写回、同步、UI 和端到端验收一起收口，而不是只看页面是否渲染出图。

实施点：

- 后端建议新增测试：`tests/test_spice_schematic_parser.py`、`tests/test_spice_source_patcher.py`、`tests/test_schematic_document_snapshot.py`、`tests/test_schematic_value_writeback.py`
- 后端重点覆盖：常见器件解析、`.subckt` / `.include` 解析、可编辑字段识别、精确 token patch、revision 冲突、外部文件修改后的文档刷新
- 前端至少完成：`npx tsc --noEmit`、前端构建验证、电路 tab 切换验证、自动布局验证、选中与属性面板验证、写回成功与失败路径验证
- 前端还应补充元件符号相关验证：常见器件图标快照、unknown fallback、极性/方向正确性、端口与连线对齐、选中高亮、长标签下的可读性
- 端到端必须验证：运行仿真后 `电路` tab 能正确显示当前 netlist；手动改源文件后电路图自动刷新；图中改值后本地文件真实变化；修改后的 diff 与手工编辑一致；再次仿真确实受新值影响
- 端到端还应验证：遇到暂不支持的器件时不会空白或消失，而是以 block / fallback 符号稳定显示，并且仍可选中和查看属性

开发提示：

- 如果最终只能证明“前端显示改了”，不能证明“本地源码真实改了且仿真结果受影响”，那就不算完成
- 验收必须以源码、diff 和重新仿真结果三者同时成立为标准

输出：

- 可持续维护的测试基线
- 真正满足需求的端到端验收结果
