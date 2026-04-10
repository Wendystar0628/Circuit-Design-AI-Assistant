# 对话面板 React 重构设计文档

## 1. 文档目标

本文档用于指导 `circuit_design_ai` 的对话面板重构。

本轮重构的目标不是简单替换 UI 技术，而是建立一套新的、绝对权威的对话前端实现，使其同时满足以下要求：

- 保留当前已经实现的核心行为能力与刷新机制
- 将对话面板的视觉表现升级为更现代、更优雅、更紧凑的交互界面
- 让用户气泡和 agent 气泡使用统一的设计语言
- 在内容需要换行时尽量充分利用横向空间，不在横向空间仍充足时过早换行
- 显著收紧内边距、组件间距与圆角弧度
- 保证小动画流畅，不引入新的刷新冲突或多套状态源
- 将新的 React 前端设计落实为唯一权威显示实现
- 从物理上、代码层面彻底清除旧设计，避免双轨并存

本文档不写具体实现代码，只写：

- 当前实现能力与架构事实
- React 重构目标结构
- 分阶段迁移步骤
- 需要落实的细节与风险
- 旧设计的物理清除清单
- 验收与闭环检查项

---

## 2. 重构边界与非目标

### 2.1 本轮重构边界

本轮聚焦于：

- 右侧对话面板本体
- 对话显示区
- 输入区
- 历史记录 UI
- 撤回确认 UI
- 与对话直接相关的前端交互呈现

### 2.2 明确不做的事

本轮不应演变为以下方向：

- 不把整个应用外壳改成 Web / React
- 不把 `QMainWindow / QSplitter / PanelManager` 全部迁到前端
- 不在对话面板内重新实现详细 diff 审阅器
- 不让 React 成为会话、pending edit、rollback、runtime step 的第二权威数据源
- 不为了过渡保留长期双轨 UI

### 2.3 必须保留的原生壳层

仍应保留原生 Qt 作为应用壳层：

- `QMainWindow`
- 原生 panel 生命周期管理
- 原生 splitter / docking / tab 管理
- 原生主菜单和其他非对话面板架构

对话面板应成为：

- **原生 Qt 宿主中的单一 React Web Surface**

---

## 3. 当前真实实现盘点

## 3.1 当前对话面板组成

当前 `ConversationPanel` 并不是全 Web，而是三段式混合实现：

- **`presentation/panels/conversation_panel.py`**
  - 对话面板主协调器
  - 负责连接标题栏、消息区、输入区
  - 负责订阅 ViewModel 和事件总线
  - 负责发送、停止、撤回、附件、历史、模型卡片等动作转发

- **`presentation/panels/conversation/title_bar.py`**
  - 原生 Qt 标题栏
  - 负责会话名称显示/编辑
  - 负责新建对话、历史、压缩、清空按钮

- **`presentation/panels/conversation/message_area.py`**
  - 消息显示区包装层
  - 内部仅承载 `WebMessageView`

- **`presentation/panels/conversation/web_message_view.py`**
  - 当前消息显示的 Web 实现
  - 使用单个 `QWebEngineView`
  - 通过 Python 动态拼装 HTML / CSS / JS 渲染整个消息区
  - 不是 React，也不是独立前端工程

- **`presentation/panels/conversation/input_area.py`**
  - 原生 Qt 输入区
  - 负责文本输入、附件、发送/停止按钮、模型卡片、usage 展示

- **`presentation/panels/conversation/inline_attachment_text_edit.py`**
  - 原生 Qt 文本框扩展
  - 负责 inline 附件引用的插入、删除、序列化

- **`presentation/panels/conversation/pending_workspace_edit_bar.py`**
  - 原生 Qt 的 pending edit summary 展示条
  - 只展示 summary，不展示详细 diff

- **`presentation/dialogs/history_dialog.py`**
  - 原生 Qt 历史会话对话框
  - 负责预览、打开、删除、导出历史会话

- **`presentation/dialogs/rollback_confirmation_dialog.py`**
  - 原生 Qt 撤回确认对话框
  - 展示回滚会影响的消息与文件差异摘要

## 3.2 当前项目内已使用 Web 技术栈的区域

当前项目已经不是纯 Qt Widgets 项目，已经有多个区域采用 Web 技术栈：

- 顶部菜单栏
- 工作区文件浏览器
- 工作区标签栏
- 代码编辑器（Monaco）
- 对话消息显示区（当前仅消息区）
- 部分文档查看器与 Web 宿主型预览

这意味着：

- React 进入对话面板不是架构方向逆转
- 当前工程已经具备 `QWebEngineView + Web UI` 的组织基础
- 但对话面板目前仍停留在“原生壳 + 原生输入 + 内联 Web 消息区”的过渡态

## 3.3 当前对话功能的权威后端层

以下对象是当前真实的权威层，React 重构后仍应保留其职责：

- **`ConversationViewModel`**
  - 对话显示状态聚合层
  - 负责格式化消息、聚合 runtime steps、建议消息、usage、can_send

- **`SessionStateManager`**
  - 会话生命周期权威层
  - 负责新建、切换、保存、恢复、删除会话

- **`ConversationRollbackService`**
  - rollback 权威层
  - 负责 checkpoint、preview、rollback execute、snapshot restore

- **`PendingWorkspaceEditService`**
  - pending edit 权威层
  - 对话面板只能消费其 summary 级状态

- **`ContextManager`**
  - 对话消息与上下文工作状态来源

- **`LLMExecutor`**
  - Agent runtime / stream / tool execution 事件来源

- **`StopController`**
  - 停止生成流程的权威控制器

---

## 4. 当前已实现功能清单

## 4.1 消息显示与气泡能力

当前消息区已经支持以下消息类型和显示能力：

- **用户消息**
  - 文本内容显示
  - inline 文件引用显示
  - 图片附件 gallery 显示
  - 撤回按钮显示

- **助手消息**
  - 当前不是单一文本泡泡
  - 以 `agent_steps` 作为核心渲染单元
  - 一个助手回复可展开为多个 step 卡片

- **建议消息**
  - 支持 suggestion 列表
  - 支持 `active / selected / expired` 状态
  - 支持点击建议后反馈到后端

- **系统消息**
  - 当前在 ViewModel 中被过滤，不进入主消息显示

## 4.2 深度思考、工具调用、联网搜索

当前 `WebMessageView` 已经实现：

- **思考过程折叠卡**
- **联网搜索折叠卡**
- **工具调用折叠卡**
- **工具参数摘要**
- **工具结果摘要**
- **运行中 / 完成 / 错误状态显示**
- **部分响应 badge**
  - 用户停止
  - 超时
  - 错误
  - 会话切换中断
  - 应用关闭中断

## 4.3 运行时步骤与持久化消息同时显示

当前消息显示不是“只显示历史消息”，而是分两类：

- **持久化消息**
  - 来自 `ConversationViewModel.messages`

- **运行时步骤**
  - 来自 `ConversationViewModel.active_agent_steps`

显示层会同时渲染这两部分。

这保证：

- 模型在流式生成时能展示正在进行的 step
- 完成后再落盘为最终消息
- 用户能区分“已持久化”和“仍在运行”的内容

## 4.4 小动画能力

当前对话相关动画已经存在两类：

- **输入区动作按钮动画**
  - `AnimatedActionButton`
  - 使用 `QTimer`
  - 在 `stopping` / `rollbacking` 状态下显示 spinner 与 dots

- **消息区状态动画**
  - 在 `WebMessageView` 的 CSS 中实现
  - thinking / running 卡片带 spinner 与 dots pulse 动画

React 重构后必须保留这两类语义，但实现方式应改成更适合 Web UI 的形式。

## 4.5 滚动与展开体验

当前 `WebMessageView` 已经实现：

- 粘底滚动逻辑
- 用户手动滚离底部后不强制拉回
- detail 卡内部滚动位置保留
- detail 卡展开 / 收起状态保留
- 刷新后尽量维持可读位置

这部分已经是成熟体验逻辑，React 版必须继承，而不能退化成每次刷新都重置滚动位置。

## 4.6 停止生成与部分结果保存

当前停止流程支持：

- 用户主动停止
- 部分 runtime step 标记为 partial
- 在允许的情况下保留部分结果
- 将部分响应同步写回上下文
- 自动保存当前会话
- 恢复发送能力

这套流程与 UI 显示高度耦合，React 迁移时必须完整保留。

## 4.7 撤回机制与撤回 UI

当前已经具备完整 rollback 机制：

- 用户消息节点可显示撤回按钮
- 撤回目标必须是 user anchor message
- 先执行 rollback preview
- 再展示撤回确认 UI
- 最后执行 snapshot 恢复与 session reload

当前撤回确认 UI 已能展示：

- 回滚锚点
- 将移除的消息数
- 将影响的工作区文件数量
- 增删行统计
- 将被移除的消息预览
- 工作区文件差异预览

## 4.8 历史会话能力

当前历史会话链路已经实现：

- 打开历史列表
- 当前会话自动持久化后再进入历史视图
- 历史列表预览
- 历史详情加载
- 打开历史会话
- 删除历史会话
- 导出历史会话
- 随 session 变化刷新历史列表

## 4.9 输入、附件与引用能力

当前输入区已经实现：

- 文本输入
- `Enter` 发送
- `Shift+Enter` 换行
- `Esc` 停止
- 图片附件添加与缩略图展示
- 普通文件附件 inline 引用插入
- inline 附件删除
- 拖放添加附件
- 模型卡片显示
- usage 与 token 占用展示
- 发送 / 停止 / 正在停止 / 正在撤回 状态切换

## 4.10 difference 编辑文件总览与接受/拒绝

当前对话面板只承担 **pending workspace edit summary** 的显示职责。

它已支持：

- 待确认文件数
- 总增删行统计
- 文件列表
- 接受全部
- 拒绝全部
- 点击文件跳转

但它**不负责**：

- per-file diff 审阅
- per-hunk accept / reject
- 详细编辑差异可视化

这些能力当前归 editor panel 所有，React 重构后必须继续保持这个边界。

## 4.11 标题栏动作、压缩与 clear display 语义

当前标题栏与会话控制还有几条非常重要的既有语义，React 重构时必须原样保留：

- **`start_new_conversation()` 不是本地清空 UI**
  - 它委托 `SessionStateManager.create_session()` 创建真实的新 session
  - 不应被替换成“前端直接重置列表和输入框”

- **`request_history()` 只是请求打开历史视图**
  - 它本身不直接切换 session
  - 真正的 session 打开仍应走 `SessionStateManager`

- **`request_compress_context()` 只是发起压缩请求**
  - 压缩完成结果通过事件回流
  - 当前压缩完成链路依赖 `EVENT_CONTEXT_COMPRESS_COMPLETE`

- **`clear_display()` 当前不是删除对话数据**
  - 其语义仅是清空显示区和输入区附件
  - 不清空 `ConversationViewModel` 中的真实消息数据
  - 不删除当前 session 持久化历史

另外，压缩按钮状态当前由上下文 usage ratio 推导，至少存在以下三态：

- `normal`
- `warning`
- `critical`

React 版必须继续保留这些语义，不得将 `clear display` 偷偷改成“删除消息”，也不得将“压缩上下文”弱化成单纯的前端视觉动作。

---

## 5. 当前权威刷新与状态流

## 5.1 当前唯一权威显示刷新路径

当前真实的显示刷新主链路是：

1. `ConversationViewModel` 产出最新显示状态
2. `ConversationViewModel.display_state_changed.emit()`
3. `ConversationPanel._on_display_state_changed()`
4. `ConversationPanel.refresh_display()`
5. `MessageArea.render_conversation(messages, runtime_steps)`
6. `WebMessageView.render_conversation(messages, runtime_steps)`
7. 前端执行 `replaceConversation(messageHtml, runtimeHtml)`

这意味着：

- 当前主刷新路径已经基本收敛为**单一权威入口**
- React 迁移后必须继续保持“单一 full-state refresh”原则
- 不应再回到多路增量 patch 的脆弱模式

## 5.2 当前发送与 runtime 事件流

当前发送一条消息后，主要流程为：

1. 输入区序列化文本与附件
2. `ConversationViewModel.send_message()`
3. `ConversationRollbackService.capture_user_turn_checkpoint()`
4. `ContextManager.add_user_message()`
5. `ConversationViewModel.load_messages()`
6. `ConversationViewModel._start_agent_run()`
7. `ConversationViewModel._trigger_llm_call()`
8. `LLMExecutor` 持续发出：
   - `agent_turn_started`
   - `stream_chunk`
   - `tool_execution_started`
   - `tool_execution_finished`
9. `ConversationViewModel` 更新 `active_agent_steps`
10. `display_state_changed` 持续刷新消息显示
11. 完成后写回 assistant message 并自动保存会话

React 迁移时，前端必须能完整承接 runtime step 的变化，但不能成为这些状态的权威源。

## 5.3 当前停止生成流程

当前停止流程为：

1. 输入区发出 `stop_clicked`
2. `ConversationViewModel.request_stop()`
3. `StopController.request_stop()`
4. `stop_requested` 信号更新 UI 为 `STOPPING`
5. `stop_completed` 信号返回部分结果处理结果
6. `ConversationViewModel._save_partial_response()` 尝试保存部分响应
7. 重新加载消息 / 恢复按钮状态

React 版必须完整承接：

- 停止按钮状态切换
- 部分响应 badge 展示
- 刷新后的状态恢复

## 5.4 当前 rollback 流程

当前 rollback 流程为：

1. 用户点击消息上的 rollback 按钮
2. `ConversationPanel._confirm_and_perform_rollback(message_id)`
3. `ConversationViewModel.preview_rollback_to_message(message_id)`
4. 打开 `RollbackConfirmationDialog`
5. 用户确认后执行 `rollback_to_message()`
6. `ConversationRollbackService.rollback_to_anchor()`
7. 恢复 snapshot
8. `SessionStateManager.reload_current_session(action="rollback")`
9. 发布 `EVENT_SESSION_CHANGED`
10. `ConversationViewModel.load_messages()` 重新拉起显示

React 版必须保留 preview 与 execute 分离，不得将撤回简化成无预览直接执行。

## 5.5 当前历史会话流程

历史会话流程为：

1. `MainWindow` / `ActionHandler` / `ConversationPanel` 发起 history 请求
2. `HistoryDialog` 打开
3. `HistoryDialog.load_sessions()`
4. 先持久化当前会话
5. 从 `SessionStateManager.get_all_sessions()` 加载历史列表
6. 详情区预览会话消息
7. 用户选择打开 / 删除 / 导出
8. 打开时调用 `SessionStateManager.switch_session()`
9. 发布 `EVENT_SESSION_CHANGED`
10. `ConversationViewModel.load_messages()` 更新面板显示

React 迁移后，历史列表与详情预览仍要遵循这一后端权威链路。

## 5.6 当前 pending edit summary 流程

当前 pending edit 流程为：

1. `PendingWorkspaceEditService` 维护完整 diff 状态
2. 对话面板只订阅 `summary_changed`
3. `ConversationPanel` 将 `summary_state` 转发给输入区 summary bar
4. summary bar 展示 aggregate 统计
5. `accept_all_edits()` / `reject_all_edits()` 继续由服务层执行

这条边界必须严格保留。

## 5.7 当前实现中已经不应再被视为权威的旧说法

现有代码中仍有一些注释沿用旧说法，例如：

- `messages_changed`
- `_on_messages_changed`
- “JavaScript 增量更新”

但从真实调用链看，当前主链路已经是：

- **`display_state_changed` 驱动完整显示更新**

因此后续重构必须以真实链路为准，而不是被旧注释带偏。

---

## 6. React 重构核心判断

## 6.1 唯一权威原则

React 重构后，必须只有一个权威前端实现。

不允许长期保留：

- 旧 Qt 标题栏
- 旧 Qt 输入区
- 旧 WebMessageView
- 旧 Qt 历史对话框
- 旧 Qt rollback 对话框
- 新 React 对话面板

这些并行共存。

最终必须收敛到：

- **一个 React conversation frontend**
- **一个 Python authority backend**

## 6.2 Qt 壳层保留，内容面板 Web 化

推荐方向不是“全应用改成 React”，而是：

- 原生 Qt 继续做应用壳层
- 对话面板内部改成单一 React surface

## 6.3 不再使用导航拦截式交互协议

旧 `WebMessageView` 依赖过以下导航拦截语义：

- `suggestion://`
- `rollback://`
- `file://`

这类协议过去已经带来过 `loadFinished(False)` 导致页面假死的风险。

React 版不应继续使用这种交互方式。

React 版必须改成：

- **QWebChannel bridge 直接发动作**
- 不再用 URL 导航作为 UI 行为协议

## 6.4 对话显示仍必须走 full-state refresh

React 版不应建立新的多轨刷新模式。

禁止以下设计：

- 一部分消息走 full refresh
- 一部分 runtime steps 走前端 append
- suggestion 走本地 patch
- stop / rollback 再独立改 UI

正确做法是：

- Python 侧继续产出统一显示状态
- 前端根据完整显示状态统一渲染
- 前端只保留局部瞬时 UI 状态

## 6.5 Pending edit 继续保持 summary-only 边界

对话面板只能继续消费：

- `PendingWorkspaceEditService.summary_changed`
- `get_summary_state()`

不能在 React 对话面板中重建 detailed diff authority。

## 6.6 架构必须继续对 AI agent 友好

新的前端结构应尽量满足：

- 文件职责清晰
- 状态来源唯一
- bridge 接口收敛
- 避免复杂的前端状态库与隐式依赖
- 便于 AI agent 在代码中追踪“谁发状态、谁消费状态、谁触发动作”

---

## 7. 目标架构

## 7.1 目标总结构

目标结构应为：

- **`ConversationPanel`**
  - 保留为原生 Qt 面板入口
  - 只负责承载新的 Web host
  - 不再自己管理 TitleBar / MessageArea / InputArea 三段式原生子组件

- **`ConversationViewModel`**
  - 保留为显示状态权威聚合层

- **单一 `QWebEngineView`**
  - 负责承载整个 React 对话面板

- **单一 `QWebChannel bridge`**
  - 负责前后端动作通信

- **单一 React app**
  - 负责：
    - 标题栏
    - 消息列表
    - 输入区
    - 历史记录模态框
    - rollback 预览模态框
    - pending edit summary bar

## 7.2 React 组件树建议

建议 React 组件树拆分为：

- `ConversationApp`
- `ConversationHeader`
- `SessionTitleEditor`
- `ConversationActions`
- `MessageViewport`
- `MessageList`
- `UserMessageBubble`
- `AgentStepBubble`
- `ThinkingDetailCard`
- `SearchDetailCard`
- `ToolCallDetailCard`
- `SuggestionMessageCard`
- `AttachmentGallery`
- `InlineFileReference`
- `Composer`
- `ComposerAttachmentTray`
- `PendingEditSummaryBar`
- `UsageIndicator`
- `ModelChip`
- `HistoryModal`
- `HistorySessionList`
- `HistorySessionDetail`
- `RollbackPreviewModal`
- `RollbackChangedFilesList`
- `RollbackRemovedMessagesList`
- `ImageLightbox`（若决定将图片预览也统一到 React）

## 7.3 前端只允许持有的本地 UI 状态

React 前端允许持有以下局部状态：

- detail 折叠 / 展开状态
- 滚动位置与 stick-to-bottom
- modal / drawer 打开关闭状态
- 输入框草稿态
- hover / focus / selection
- 当前选中的历史会话项
- 当前选中的 rollback 文件项

## 7.4 仍由 Python 权威维护的状态

以下必须继续由 Python 权威维护：

- 当前 session 与会话列表
- 消息列表
- runtime steps
- suggestion 状态
- loading / can_send 状态
- usage 信息
- 当前模型信息
- rollback preview 数据
- pending edit summary
- stop / rollback / session switch 的业务结果

## 7.5 推荐的技术栈与集成方式

推荐前端技术栈如下：

- **React 18**
- **TypeScript**
- **Vite** 仅作为本地构建工具
- **纯 CSS / CSS Modules 或极简设计 token**
- **QWebChannel** 作为桥接协议
- **本地静态资源加载**，不依赖在线资源

不建议：

- Next.js
- 重型状态管理框架（除非状态复杂度后续明显超过 React 自身能力）
- CSS-in-JS 大量动态样式方案
- 将桥接动作拆成多套通信机制

### 推荐目录结构

建议引入以下结构：

- `frontend/conversation_panel/`
  - React 源码目录
- `resources/conversation_panel/`
  - 构建后的运行时静态资源
- `presentation/panels/conversation/react_conversation_host.py`
  - React Web host
- `presentation/panels/conversation/conversation_web_bridge.py`
  - QWebChannel bridge

运行时应加载 `resources/conversation_panel/` 的构建产物，而不是直接加载源代码目录。

### Markdown / KaTeX 建议

第一阶段建议继续沿用已有成熟能力：

- 允许 Python 继续提供 markdown 渲染能力或原始 markdown 数据
- 保留本地 KaTeX 资源
- React 先接管布局、交互与统一视觉
- 不在第一阶段同时重写 markdown / math 整套渲染语义

## 7.6 建议的 full-state payload 分层

为了避免 React 端重新生长出第二套业务真相，建议将状态下发明确分为两类：

### 主显示 payload

这部分用于高频刷新，由 `ConversationViewModel.display_state_changed` 驱动。

建议至少包含：

- **`session`**
  - 当前 session id
  - 当前 session name
  - 是否允许重命名、是否允许新建等 header 所需能力标记

- **`conversation`**
  - 持久化消息列表
  - runtime steps 列表
  - 当前 loading 状态
  - 当前 can_send 状态
  - suggestion 相关显示状态

- **`composer`**
  - usage 信息
  - compress button state
  - 当前模型摘要信息
  - send / stop / stopping / rollbacking 等动作态
  - pending workspace edit summary

- **`view_flags`**
  - 当前是否存在可 rollback 锚点
  - 当前是否允许执行特定动作

### 按需 payload

这部分不需要每次消息刷新都携带，但一旦请求打开某个模态框，应仍以下发结构化状态为主，而不是发送 DOM 命令：

- **`history_modal_state`**
  - session 列表
  - 当前选中项
  - 详情预览数据
  - 删除 / 导出 / 打开时的 busy 状态

- **`rollback_preview_state`**
  - anchor message 信息
  - summary 统计
  - changed files 列表
  - removed messages 列表
  - 当前选中 diff 详情

### 本地 UI 状态与业务状态的边界

以下内容允许继续仅存在于 React 本地状态中：

- 发送前草稿文本
- 发送前附件草稿
- detail 折叠 / 展开状态
- 滚动位置
- modal / drawer 打开关闭状态
- 输入框草稿态
- hover / focus / selection
- 当前选中的历史会话项
- 当前选中的 rollback 文件项

## 7.7 建议的 bridge contract 规则

新的 bridge 不应是“前端调用一堆零散方法去直接改 UI”，而应遵守以下规则：

- **动作只表达用户意图，不表达最终状态**
  - 例如“请求发送消息”“请求停止生成”“请求打开某个 session”
  - 不应存在“前端自己把某条消息标成完成”这种接口

- **动作完成后以状态回流为准**
  - action 调用成功，不代表 UI 立即可信
  - 最终显示应以后端新的 state dispatch 为准

- **长流程动作必须有显式过渡状态**
  - stopping
  - rollbacking
  - history loading
  - rollback preview loading

- **相同业务动作只保留一个入口**
  - 不允许同时存在“openHistory”和“showHistoryDialog”两套长期并行接口

- **不要提供 DOM 命令式桥接**
  - 不要让 Python 直接命令 React “append 一个节点”“打开某个折叠面板”
  - Python 只发送业务状态，React 自己声明式渲染

### 建议的动作分组

- **conversation**
  - send
  - request_stop
  - select_suggestion
  - clear_display

- **session**
  - create
  - rename
  - open_history
  - open_session
  - delete_session
  - export_session

- **context**
  - request_compress

- **rollback**
  - preview
  - confirm
  - cancel

- **pending_edits**
  - accept_all
  - reject_all
  - open_file

- **attachments / file_refs**
  - pick_files
  - pick_images
  - drop_attachments
  - open_file_reference
  - preview_image

## 7.8 文件职责替换关系

建议在正式迁移时明确建立“旧文件职责归属到哪里”的映射，避免只新增不替换。

| 当前文件 | 迁移后职责归属 | 最终处理 |
| --- | --- | --- |
| `presentation/panels/conversation_panel.py` | 保留为 Qt 宿主与协调入口 | 收敛、瘦身、保留 |
| `presentation/panels/conversation/title_bar.py` | `ConversationHeader` | 删除 |
| `presentation/panels/conversation/message_area.py` | `MessageViewport / MessageList` | 删除 |
| `presentation/panels/conversation/web_message_view.py` | React 消息显示层 | 删除 |
| `presentation/panels/conversation/input_area.py` | `Composer` | 删除 |
| `presentation/panels/conversation/inline_attachment_text_edit.py` | React 草稿附件与 inline 引用层 | 删除 |
| `presentation/panels/conversation/pending_workspace_edit_bar.py` | React summary bar | 删除 |
| `presentation/dialogs/history_dialog.py` | `HistoryModal` | 删除 |
| `presentation/dialogs/rollback_confirmation_dialog.py` | `RollbackPreviewModal` | 删除 |
| `presentation/panels/conversation/conversation_view_model.py` | 继续作为后端权威聚合层 | 保留 |
| `presentation/panels/conversation/conversation_web_bridge.py` | 新 QWebChannel bridge | 新增 |
| `presentation/panels/conversation/react_conversation_host.py` | 新 React 宿主 | 新增 |

如果后续发现 `ConversationPanel` 本体承担了过多 JSON 序列化与状态拼装职责，建议再新增一个专用状态适配层，例如：

- `presentation/panels/conversation/conversation_state_serializer.py`

其职责应仅限于：

- 将后端对象转换为前端可消费的结构化 payload
- 集中维护字段命名
- 避免把 payload 组装逻辑散落在 panel、bridge、view model 三处

---

## 8. 分阶段重构步骤

## Phase 0：冻结权威契约与验收基线

### 目标

在动手替换 UI 之前，先把当前权威契约冻结下来，避免迁移中语义漂移。

### 必须落实

- 记录当前对话显示 payload 的真实组成
- 记录当前动作入口清单
- 建立功能对等清单
- 建立视觉目标清单
- 明确哪些层是 authority、哪些层只允许渲染

### 必须核对的现有权威对象

- `ConversationViewModel`
- `SessionStateManager`
- `ConversationRollbackService`
- `PendingWorkspaceEditService`
- `StopController`
- `ContextManager`

### 输出结果

- 一份稳定的 state contract 说明
- 一份动作 contract 说明
- 一份功能验收矩阵

---

## Phase 1：建立新的 React Host 与单一 Bridge

### 目标

在不改变后端权威业务语义的前提下，先建立新的 React 宿主入口。

### 必须落实

- `ConversationPanel` 改为承载新的 Web host
- 建立新的 `QWebChannel bridge`
- React 页面能够接收完整显示状态
- React 页面能够把动作回传给 Python

### Bridge 动作至少应覆盖

- 发送消息
- 请求停止生成
- suggestion 选择
- 请求新建对话
- 请求打开历史
- 请求删除历史
- 请求打开历史会话
- 请求导出历史会话
- 请求编辑会话名
- 请求压缩上下文
- 请求 clear display
- 请求 rollback preview
- 请求确认 rollback
- 请求接受全部 pending edits
- 请求拒绝全部 pending edits
- 请求打开 pending edit 对应文件
- 请求打开文件引用
- 请求图片预览
- 请求选择文件 / 图片
- 请求添加拖放附件

### 此阶段不能做的事

- 不删除现有权威业务逻辑
- 不在 React 端引入第二份消息状态源
- 不把 session / rollback / pending edit 语义搬到前端自己维护

---

## Phase 2：迁移消息显示层

### 目标

先将当前 `WebMessageView` 的消息显示职责迁到 React 组件树。

### 必须迁移的能力

- 用户消息泡泡
- agent step 泡泡
- suggestion message 卡片
- thinking detail 卡
- search detail 卡
- tool call detail 卡
- partial badge
- inline file references
- 图片 gallery
- runtime steps 与 persisted messages 同屏显示
- scroll / stick-to-bottom / detail 展开态保留

### 必须保留的行为细节

- 运行中 step 可以持续更新
- 生成完成后能被持久化消息替代
- detail 展开状态不要每次刷新都丢失
- 用户滚离底部后不要强制拉回
- rollback 按钮显示条件不改变

### 这一阶段完成后应删除的旧设计

当 React 消息区达到功能对等后，应准备删除：

- `presentation/panels/conversation/message_area.py`
- `presentation/panels/conversation/web_message_view.py`

同时删除以下旧机制：

- 内联 HTML / CSS / JS 字符串拼装渲染
- `suggestion://` 导航拦截
- `rollback://` 导航拦截
- `file://` 导航拦截作为 UI 动作协议

---

## Phase 3：迁移输入区、附件与 summary bar

### 目标

将当前原生 `InputArea` 能力完整迁入 React。

### 必须迁移的能力

- 文本输入
- Enter 发送
- Shift+Enter 换行
- Esc 停止
- usage 指示
- token 信息展示
- 模型卡片
- 发送 / 停止 / 正在停止 / 正在撤回 状态
- 图片附件 tray
- 普通文件 inline 引用
- drag & drop 附件
- pending workspace edit summary bar

### 必须落实的契约

- 输入文本仍能序列化成后端现有可消费的格式
- inline 附件 marker 语义保持兼容
- 图片与普通文件仍进入现有附件模型
- summary bar 仍只消费 `PendingWorkspaceEditService.summary_changed`

### 小动画要求

React 版应保留：

- send / stop / rollback 动作按钮动画
- runtime thinking / running 状态动画

但实现方式应改为：

- CSS 动画
- 组件局部更新
- 避免整棵消息树重渲染驱动动画

### 这一阶段完成后应删除的旧设计

- `presentation/panels/conversation/input_area.py`
- `presentation/panels/conversation/inline_attachment_text_edit.py`
- `presentation/panels/conversation/pending_workspace_edit_bar.py`

---

## Phase 4：迁移标题栏、历史会话 UI、rollback 预览 UI

### 目标

将当前原生对话框与原生标题栏统一纳入 React 对话 surface。

### 必须迁移的能力

- 会话标题显示与编辑
- 新建对话
- 历史会话列表
- 历史预览详情
- 打开会话
- 删除会话
- 导出会话
- rollback preview 概览
- rollback changed files 列表
- rollback removed messages 列表
- rollback diff 详情

### 推荐形态

建议统一改为：

- React modal / drawer / side sheet

而不是继续保留原生 Qt dialog。

### 仍由 Python 负责的业务部分

- 历史列表读取
- session 打开 / 删除 / 导出
- rollback preview 计算
- rollback execute

### 这一阶段完成后应删除的旧设计

- `presentation/panels/conversation/title_bar.py`
- `presentation/dialogs/history_dialog.py`
- `presentation/dialogs/rollback_confirmation_dialog.py`

并同步删除：

- `MainWindow` 中直接构造这些原生对话框的路径
- 相关原生信号转发与专用 UI 适配逻辑

---

## Phase 5：切换为绝对权威实现并清理旧路径

### 目标

完成真正的 cutover，让 React 版成为唯一可运行的对话前端。

### 必须落实

- `ConversationPanel` 只保留 React host
- 所有对话相关显示与交互统一进入 React surface
- 所有旧 UI 组件停止被导入、停止被构造、停止被调用
- 删除旧刷新路径和旧注释

### 必须删除的旧设计类型

- 旧 Qt 子组件
- 旧 WebMessageView
- 旧原生历史对话框
- 旧原生 rollback 对话框
- 旧导航拦截式前端动作协议
- 旧多入口刷新路径
- 与新设计冲突的旧注释与过时描述

### 不允许保留的过渡形态

- “默认使用 React，异常时 fallback 到旧 Qt 输入区”
- “历史对话 React 化，但 rollback 仍留原生对话框长期存在”
- “消息区是 React，但输入区继续永久保留 Qt 原生实现”

这些都不是最终架构，只会制造第二权威。

---

## Phase 6：视觉统一与交互打磨

### 目标

在行为完全对等后，再做一轮视觉与交互收紧，落实本次设计目标。

### 必须落实的视觉目标

- 用户气泡与 agent 气泡使用同一设计语言
- 差异主要来自颜色层级与布局语义，不来自完全不同的造型体系
- 更小的圆角
- 更小的内边距
- 更紧凑的卡片间距
- 更高的横向利用率
- 避免过早换行
- 输入框风格与项目其他 Web surface 对齐

### 必须落实的交互目标

- 小动画流畅
- 消息滚动稳定
- detail 展开不抖动
- 生成态、停止态、撤回态切换自然
- 不因为局部状态切换导致全区闪烁

---

## 9. 旧设计的物理清除清单

以下清理不是建议，而是为了建立新设计绝对权威所必须执行的内容。

## 9.1 文件级删除清单

在 React 对等实现完成后，应删除以下文件：

- `presentation/panels/conversation/message_area.py`
- `presentation/panels/conversation/web_message_view.py`
- `presentation/panels/conversation/input_area.py`
- `presentation/panels/conversation/inline_attachment_text_edit.py`
- `presentation/panels/conversation/pending_workspace_edit_bar.py`
- `presentation/panels/conversation/title_bar.py`
- `presentation/dialogs/history_dialog.py`
- `presentation/dialogs/rollback_confirmation_dialog.py`

## 9.2 方法与路径级清理清单

删除以下旧路径或将其替换为新的 React 实现入口：

- `ConversationPanel._setup_ui()` 中对子组件三段式结构的构造逻辑
- `ConversationPanel._connect_component_signals()` 中旧子组件信号连接
- `ConversationPanel.refresh_display()` 中对 `MessageArea` 的旧渲染调用
- `MainWindow._on_show_history_dialog()` 中直接构造原生 `HistoryDialog` 的路径
- 旧 rollback dialog 打开路径
- 旧图片预览弹窗路径（若决定统一到 React lightbox）

## 9.3 协议级清理清单

删除以下旧协议：

- `suggestion://`
- `rollback://`
- `file://` 作为 UI 行为协议的使用

保留真正需要的文件打开能力时，应通过 bridge action 或明确的 native service action 调用，而不是导航拦截。

## 9.4 注释与文档级清理清单

必须同步清理以下误导性内容：

- 仍在描述 `messages_changed` 为主刷新路径的注释
- 仍在描述“JavaScript 增量更新”为主设计的注释
- 仍在描述已不存在旧 UI 路径的文档说明

否则 AI agent 和后续维护者会被错误信息误导。

---

## 10. 功能对等验收清单

## 10.1 消息显示验收

- 用户消息显示正确
- agent step 显示正确
- suggestion message 显示正确
- thinking / search / tool 卡正确显示
- partial badge 正确显示
- rollback 按钮显示条件正确
- 图片与文件引用显示正确

## 10.2 刷新验收

- 单一显示状态刷新入口有效
- 不存在双重刷新
- 不存在 runtime step 重复渲染
- session 切换后不会残留旧 runtime step
- stop 后不会出现 UI 状态卡死
- rollback 后不会出现旧消息残留

## 10.3 输入与附件验收

- Enter 发送
- Shift+Enter 换行
- Esc 停止
- 图片附件添加、预览、删除
- 普通文件 inline 引用插入、删除
- drag & drop 正常
- usage 与 model card 正常

## 10.4 标题栏与会话控制验收

- 会话标题正确显示当前名称
- 会话重命名能正确回写并刷新 UI
- 新建对话通过 `SessionStateManager` 创建真实新 session，而不是只重置前端
- `clear display` 只清空可见消息区与未发送附件，不删除真实会话数据
- 压缩按钮状态能正确反映 `normal / warning / critical`
- 压缩完成后 header 与 composer 状态能随事件回流正确更新

## 10.5 历史会话验收

- 打开历史列表前会持久化当前会话
- 历史列表与当前 session 同步
- 详情预览正确
- 打开会话正确
- 删除会话正确
- 导出会话正确

## 10.6 rollback 验收

- 只允许对 user anchor message 撤回
- preview 展示数据正确
- removed messages 列表正确
- workspace changed files 列表正确
- diff preview 正确
- rollback execute 后 session 与 workspace 正确恢复

## 10.7 pending edit 验收

- 对话面板只显示 summary
- accept all / reject all 正常
- 点击文件跳转正常
- detailed diff 仍只在 editor panel 中权威展示

## 10.8 视觉与紧凑度验收

- 用户与 agent 气泡设计语言统一
- 圆角明显收紧
- padding 明显收紧
- 横向空间利用率显著提高
- 不在横向空间仍大量剩余时过早换行
- 输入框与项目其他 Web 面板风格统一

## 10.9 动画验收

- stopping 动画顺滑
- rollbacking 动画顺滑
- thinking / running 状态动画顺滑
- 动画不会带动整列表闪烁或跳动

---

## 11. 重构前需要额外核查的事项

以下问题不是本次文档的主目标，但在正式迁移前应补核：

### 11.1 部分响应保存实现需要核实

在 `ConversationViewModel._save_partial_response()` 中，当前可见代码存在 `latest_reasoning` 引用，但可见范围内未看到对应赋值。

在正式开始 React 重构前，应确认：

- 这是截断阅读导致未看到的定义
- 还是当前代码中确实存在潜在遗漏

如果这是实际问题，应在迁移前优先修正，否则会影响 stop 后部分响应保存与显示的验收。

### 11.2 旧注释存在误导风险

当前有部分注释仍描述旧刷新语义，应在重构时同步清理，避免新旧设计混淆。

### 11.3 图片预览的最终归属需尽早拍板

当前图片预览走原生 `ImagePreviewDialog`。

需要在迁移早期明确：

- 是继续保留原生预览服务，只将触发入口放到 React 中
- 还是将图片预览也统一迁入 React lightbox

若希望视觉彻底统一，推荐后一种；若优先迁移风险最小，可先保留 native service。

---

## 12. 最终权威定义

重构完成后，对话面板必须满足以下定义：

### 12.1 显示权威

- 只有一个对话前端显示实现：React conversation app
- 不再存在旧 Qt / 旧 WebMessageView 的并行显示实现

### 12.2 状态权威

- 只有一条显示状态主链路
- 只有一套后端 authority
- React 只管理局部瞬时 UI 状态，不管理业务真相

### 12.3 交互权威

- 所有对话相关 UI 动作统一通过 bridge 发回 Python
- 不再保留导航拦截式动作协议

### 12.4 会话权威

- `SessionStateManager` 继续是会话生命周期唯一权威

### 12.5 回滚权威

- `ConversationRollbackService` 继续是 rollback preview 与 execute 的唯一权威

### 12.6 Pending edit 权威

- `PendingWorkspaceEditService` 继续是 pending edit 的唯一权威
- 对话面板始终只展示 summary 级状态

---

## 13. 结论

对话面板适合迁移到 React，但必须遵守以下前提：

- 保留当前后端行为能力
- 保留单一权威刷新原则
- 保留 session / rollback / pending edit 的后端 authority
- 不让 React 前端和旧 Qt UI 长期双轨并存
- 在 cutover 时物理删除旧设计

只有这样，这次重构才不是“换皮”，而是真正建立新的、干净的、绝对权威的对话前端架构。
