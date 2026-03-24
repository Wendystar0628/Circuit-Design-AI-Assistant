# pi-mono 借鉴：Agent 工具调用全链路实现步骤

> **前提**：本项目已实现 LLM 对话、流式输出、深度思考展示。本文档聚焦**从 pi-mono 项目迁移 Agent 工具调用能力到 circuit_design_ai 的全链路开发步骤**，每一步标注需要参考的 pi-mono 源码文件和本项目需要修改/新建的文件。不含具体实现代码。

---

## 第一步：修补流式工具调用解析（补齐已有链路缺口）

### 背景

当前 `StreamChunk` 数据类只有 `content`、`reasoning_content`、`is_finished`、`usage` 四个字段，**缺少 `tool_calls` 字段**。`ZhipuResponseParser._parse_stream_data()` 只提取了 `delta.content` 和 `delta.reasoning_content`，**未处理 `delta.tool_calls`**。这意味着 LLM 以流式方式返回工具调用时，当前代码无法捕获。

### 需要参考的 pi-mono 代码

pi-mono 没有直接的流式工具调用累积代码（它依赖 `@mariozechner/pi-ai` 底层库处理），但其消息事件中的 `toolcall_start` / `toolcall_delta` / `toolcall_end` 事件序列展示了流式工具调用的生命周期：

- **`packages/agent/src/agent-loop.ts`** 第 276-303 行：`streamAssistantResponse()` 函数处理流式事件，其中 `case "toolcall_start"` / `case "toolcall_delta"` / `case "toolcall_end"` 分支展示了工具调用如何在流式过程中增量构建

### 本项目需要修改的文件

1. **`infrastructure/llm_adapters/base_client.py`** 中的 `StreamChunk` 数据类
   - 新增 `tool_calls` 可选字段（类型为 `Optional[List[Dict[str, Any]]]`）
   - 新增 `finish_reason` 可选字段（用于区分 `"stop"` 和 `"tool_calls"` 两种结束原因）

2. **`infrastructure/llm_adapters/zhipu/zhipu_stream_handler.py`** 中的 `StreamState` 数据类
   - 已有 `tool_calls` 和 `current_tool_call` 字段（但目前未被使用）
   - 需要在 `_process_line()` 中增加工具调用累积逻辑

3. **`infrastructure/llm_adapters/zhipu/zhipu_response_parser.py`** 中的 `_parse_stream_data()` 方法
   - 从 `delta` 中提取 `tool_calls` 增量数据
   - 将 `finish_reason` 传递到 `StreamChunk` 中

### 实现思路

智谱 API 流式工具调用的数据格式（与 OpenAI 一致）：
- 每个 chunk 的 `delta.tool_calls` 是一个数组，每个元素包含 `index`（标识第几个并行工具调用）
- 第一个包含该 index 的 chunk 会携带 `function.name`
- 后续 chunk 携带 `function.arguments` 的增量字符串片段
- 需要在 `StreamState` 中按 `index` 累积，拼接 `arguments` 字符串
- 当 `finish_reason="tool_calls"` 时，将累积完成的 `tool_calls` 列表附加到最终的 `StreamChunk` 中
- 累积完成后对每个工具调用的 `arguments` 做 `json.loads()` 解析

### 验证方式

向智谱 API 发送一个带 `tools` 定义的流式请求，提问一个会触发工具调用的问题，检查流式输出中是否能正确累积并解析出 `tool_calls`。

---

## 第二步：定义工具基础类型体系

### 背景

pi-mono 的工具系统建立在一组精心设计的类型之上：`AgentTool`（工具接口）、`AgentToolResult`（执行结果）、`AgentToolCall`（调用描述）。本项目需要定义等价的 Python 类型体系。

### 需要参考的 pi-mono 代码

- **`packages/agent/src/types.ts`** 第 262-282 行：`AgentToolResult` 和 `AgentTool` 接口定义
  - `AgentToolResult` 包含 `content`（返回给 LLM 的内容块数组）和 `details`（供 UI 展示的结构化详情）
  - `AgentTool` 继承自 `Tool`，增加了 `label`（UI 显示名）和 `execute()` 方法（接收 `toolCallId`、`params`、`signal`、`onUpdate` 回调）
- **`packages/agent/src/types.ts`** 第 295-310 行：`AgentEvent` 联合类型定义
  - 展示了工具执行生命周期的完整事件类型：`tool_execution_start`、`tool_execution_update`、`tool_execution_end`
- **`packages/agent/src/types.ts`** 第 46-66 行：`BeforeToolCallResult` 和 `AfterToolCallResult` 接口
  - 前置拦截：返回 `{block: true, reason: "..."}` 可阻止工具执行
  - 后置修改：可覆盖工具结果的 `content`、`details`、`isError`

### 本项目需要新建的文件

在 `domain/llm/` 下新建 `agent/` 子目录，作为 Agent 功能的模块根：

1. **`domain/llm/agent/__init__.py`**
2. **`domain/llm/agent/types.py`** — Agent 工具相关的所有基础类型定义

### 实现思路

需要定义以下核心类型（使用 Python dataclass 或 TypedDict）：

- **`ToolResult`**：对应 pi-mono 的 `AgentToolResult`
  - `content: str` — 返回给 LLM 的纯文本内容（智谱 API 的 `role: tool` 消息只接受字符串）
  - `details: Optional[Dict[str, Any]]` — 供 UI 展示的结构化详情（如 diff、行号等）
  - `is_error: bool` — 标记是否为错误结果

- **`ToolSchema`**：工具的 JSON Schema 定义
  - `name: str`
  - `description: str`
  - `parameters: Dict[str, Any]` — JSON Schema 格式的参数定义

- **`BaseTool`**：抽象基类，对应 pi-mono 的 `AgentTool`
  - 属性：`name`、`label`、`description`、`parameters`（JSON Schema）
  - 方法：`get_schema()` → 返回 OpenAI Function Calling 格式的工具定义
  - 方法：`execute(tool_call_id, params, context)` → 返回 `ToolResult`（异步）

- **`ToolContext`**：工具执行时的上下文环境
  - `project_root: str` — 当前项目根目录
  - `current_file: Optional[str]` — 当前编辑器打开的文件

- **`ToolCallInfo`**：描述一次工具调用的信息（从 LLM 响应中解析得到）
  - `id: str` — 工具调用 ID（由 LLM API 生成）
  - `name: str` — 工具名
  - `arguments: Dict[str, Any]` — 已解析的参数字典

### 设计要点

- `BaseTool.get_schema()` 返回的格式必须是 `{"type": "function", "function": {"name": ..., "description": ..., "parameters": ...}}`，这是 OpenAI Function Calling 的标准格式，智谱 API 直接兼容
- `ToolResult.content` 是字符串而非内容块数组（pi-mono 支持图片内容块，但本项目当前不需要，智谱的 `role: tool` 消息也只接受字符串）
- `ToolResult.details` 是给 UI 用的，不会发送给 LLM

---

## 第三步：实现工具注册表

### 背景

pi-mono 通过 `index.ts` 中的工具注册和分组函数管理所有工具。本项目需要一个集中的注册表，供 ReAct 循环查找工具、供 LLM 请求构建器获取工具 schema 列表。

### 需要参考的 pi-mono 代码

- **`packages/coding-agent/src/core/tools/index.ts`** 全文（194 行）
  - 第 110-121 行：`codingTools`、`readOnlyTools`、`allTools` 等预定义工具集合
  - 第 140-168 行：`createCodingToolDefinitions(cwd)`、`createAllToolDefinitions(cwd)` 等工厂函数，展示了如何用 `cwd` 参数创建带上下文的工具实例
- **`packages/coding-agent/src/core/tools/tool-definition-wrapper.ts`** 全文（42 行）
  - 展示了 `ToolDefinition`（带渲染能力的完整定义）到 `AgentTool`（纯运行时接口）的转换

### 本项目需要新建的文件

1. **`domain/llm/agent/tool_registry.py`** — 工具注册表

### 实现思路

`ToolRegistry` 是一个单例或模块级对象，职责如下：

- **注册**：`register(tool: BaseTool)` — 将工具实例存入内部字典（key 为工具名）
- **查找**：`get(name: str) -> Optional[BaseTool]` — 根据名称查找工具
- **获取全部 schema**：`get_all_schemas() -> List[Dict]` — 遍历所有已注册工具，调用每个工具的 `get_schema()` 方法，返回列表。这个列表直接传给 `ZhipuClient.chat()` 的 `tools` 参数
- **工具分组**（可选）：支持按类别（文件操作 / 搜索 / 仿真）获取子集，便于不同场景只启用部分工具

借鉴 pi-mono 的 `createAllTools(cwd)` 模式：注册表在初始化时接收 `ToolContext`，将其传递给每个工具的构造函数。这样工具就能在执行时访问项目根目录等上下文信息。

---

## 第四步：实现文件操作基础工具集

### 背景

pi-mono 的核心工具是 `read`、`edit`、`write`。本项目需要实现等价的 `read_file`、`patch_file`、`rewrite_file`。这三个工具构成最小可用的文件编辑闭环。

### 4A：`read_file` 工具

#### 需要参考的 pi-mono 代码

- **`packages/coding-agent/src/core/tools/read.ts`** 全文（270 行）
  - 第 17-21 行：`readSchema` — 参数定义（`path`、`offset`、`limit`）
  - 第 127-249 行：`execute()` 方法的完整实现
    - 第 148-153 行：文件存在性检查和图片检测
    - 第 186-237 行：文本文件读取的核心逻辑——offset/limit 切片、truncateHead 截断、行号显示、续读提示
  - 第 114-126 行：`createReadToolDefinition()` 展示了工具 schema 的 `description` 如何包含截断限制说明（告诉 LLM "输出会被截断到 2000 行或 50KB"）
- **`packages/coding-agent/src/core/tools/truncate.ts`** 全文（266 行）
  - 第 11-13 行：`DEFAULT_MAX_LINES = 2000`、`DEFAULT_MAX_BYTES = 50 * 1024` 默认限制
  - 第 15-38 行：`TruncationResult` 结构——记录截断状态、原始行数/字节数、输出行数/字节数
  - 第 67-149 行：`truncateHead()` 函数——从头截断，保留完整行，按行数或字节数限制
- **`packages/coding-agent/src/core/tools/path-utils.ts`** 全文（95 行）
  - 第 54-60 行：`resolveToCwd()` — 将相对路径解析为绝对路径
  - 第 39-48 行：`expandPath()` — 处理 `~` 前缀和 Unicode 空格

#### 本项目需要新建的文件

1. **`domain/llm/agent/tools/read_file.py`** — read_file 工具实现
2. **`domain/llm/agent/tools/__init__.py`** — 工具包初始化
3. **`domain/llm/agent/utils/truncate.py`** — 截断工具函数
4. **`domain/llm/agent/utils/path_utils.py`** — 路径工具函数

#### 实现思路

**参数定义**：
- `path`（必填）：文件路径，相对于项目根目录或绝对路径
- `offset`（可选）：起始行号（1-indexed）
- `limit`（可选）：最大读取行数

**核心执行流程**（借鉴 `read.ts` 第 186-237 行）：
1. 将 `path` 解析为绝对路径（参考 `path-utils.ts` 的 `resolveToCwd`），并检查是否在项目目录内（安全校验）
2. 检查文件是否存在且可读
3. 读取文件全部内容为文本
4. 按 `offset`/`limit` 切片选取目标行
5. 对选取内容应用截断（参考 `truncate.ts` 的 `truncateHead`）——按最大行数和最大字节数两个维度，先触及哪个就在哪里截断
6. 如果发生截断，在返回内容末尾追加续读提示：`"[Showing lines X-Y of Z. Use offset=N to continue.]"`（参考 `read.ts` 第 221-225 行）
7. 如果用户指定了 `limit` 但文件还有更多内容，也追加续读提示（参考 `read.ts` 第 227-231 行）
8. 返回内容时每行带行号前缀，方便 LLM 后续引用

**关键设计细节**：
- `offset` 超出文件总行数时，返回错误而非空内容（参考 `read.ts` 第 195-197 行）
- 截断粒度为完整行，不会在行中间截断（参考 `truncateHead` 的设计）
- 截断阈值建议：最大 2000 行或 50KB（与 pi-mono 一致），可通过配置调整
- 返回内容的 `details` 中包含 `TruncationResult`，供 UI 显示截断提示

### 4B：`patch_file` 工具（搜索替换式编辑）

#### 需要参考的 pi-mono 代码

- **`packages/coding-agent/src/core/tools/edit.ts`** 全文（336 行）
  - 第 30-34 行：`editSchema` — 参数定义（`path`、`oldText`、`newText`）
  - 第 118-295 行：`createEditToolDefinition()` 中的 `execute()` 方法
    - 第 184-186 行：读取文件
    - 第 193-194 行：BOM 剥离（`stripBom`）
    - 第 196-199 行：行尾归一化（`detectLineEnding` + `normalizeToLF`）
    - 第 201-214 行：模糊匹配查找（`fuzzyFindText`），未找到时抛错
    - 第 216-231 行：唯一性检查，多处匹配时抛错
    - 第 238-244 行：执行替换
    - 第 246-257 行：空操作检查（替换前后内容相同时报错）
    - 第 259-260 行：恢复行尾格式 + 恢复 BOM + 写入文件
    - 第 272-281 行：生成 diff 和首个变更行号
  - 第 140 行：`withFileMutationQueue(absolutePath, ...)` — 文件写入互斥保护
- **`packages/coding-agent/src/core/tools/edit-diff.ts`** 全文（310 行）
  - 第 11-25 行：`detectLineEnding()`、`normalizeToLF()`、`restoreLineEndings()` — 行尾归一化三件套
  - 第 34-55 行：`normalizeForFuzzyMatch()` — 模糊匹配归一化（去尾部空白、Unicode 引号/破折号/空格统一）
  - 第 79-117 行：`fuzzyFindText()` — 先精确匹配，失败后模糊匹配，返回匹配位置和用于替换的内容
  - 第 119-122 行：`stripBom()` — BOM 剥离
  - 第 128-228 行：`generateDiffString()` — 带行号的 unified diff 生成
- **`packages/coding-agent/src/core/tools/file-mutation-queue.ts`** 全文（40 行）
  - 第 19-39 行：`withFileMutationQueue()` — 基于 Promise 链的文件互斥队列，同一文件路径的操作串行执行，不同文件并行

#### 本项目需要新建的文件

1. **`domain/llm/agent/tools/patch_file.py`** — patch_file 工具实现
2. **`domain/llm/agent/utils/edit_diff.py`** — 行尾归一化、模糊匹配、diff 生成工具函数
3. **`domain/llm/agent/utils/file_mutex.py`** — 文件写入互斥队列

#### 实现思路

**参数定义**：
- `path`（必填）：文件路径
- `old_text`（必填）：要查找的原始文本（必须精确匹配或模糊匹配唯一）
- `new_text`（必填）：替换后的新文本

**核心执行流程**（严格对照 `edit.ts` 第 166-294 行）：

1. 路径解析 + 安全校验
2. **文件互斥队列保护**（参考 `file-mutation-queue.ts`）：使用 `asyncio.Lock` 实现按文件路径的互斥。维护一个 `Dict[str, asyncio.Lock]` 映射，同一文件路径共享同一把锁，不同文件的锁互不影响
3. 检查文件是否存在且可读写
4. 读取文件内容
5. **BOM 处理**（参考 `edit-diff.ts` 第 119-122 行）：检测并剥离 UTF-8 BOM（`\xEF\xBB\xBF`），记录是否存在 BOM
6. **行尾归一化**（参考 `edit-diff.ts` 第 11-25 行）：检测原始行尾格式（CRLF 或 LF），将内容和搜索/替换文本统一转换为 LF
7. **查找匹配**（参考 `edit-diff.ts` 第 79-117 行）：
   - 先尝试精确匹配（`str.find()`）
   - 精确匹配失败则尝试模糊匹配：将内容和搜索文本都做归一化（去行尾空白、统一 Unicode 标点），再匹配
   - 两者都失败 → 抛错"未找到匹配内容"
8. **唯一性检查**（参考 `edit.ts` 第 216-231 行）：用模糊归一化后的内容检查搜索文本出现次数，大于 1 次 → 抛错"找到 N 处匹配"
9. **执行替换**：在匹配位置用 `new_text` 替换 `old_text`
10. **空操作检查**（参考 `edit.ts` 第 246-257 行）：替换前后内容相同 → 抛错
11. **写回文件**：恢复原始行尾格式 + 恢复 BOM + 写入
12. **生成 diff**（参考 `edit-diff.ts` 第 128-228 行）：生成带行号的 unified diff 字符串，记录首个变更行号
13. 返回 `ToolResult`，`content` 为成功消息，`details` 包含 diff 和首个变更行号

**edit_diff.py 需要实现的函数**（一一对应 `edit-diff.ts`）：
- `detect_line_ending(content)` → `"\r\n"` 或 `"\n"`
- `normalize_to_lf(text)` → 将所有 `\r\n` 和 `\r` 替换为 `\n`
- `restore_line_endings(text, ending)` → 恢复原始行尾
- `strip_bom(content)` → 返回 `(bom, text)` 元组
- `normalize_for_fuzzy_match(text)` → Unicode NFKC 归一化 + 去行尾空白 + 统一引号/破折号/空格
- `fuzzy_find_text(content, old_text)` → 先精确后模糊，返回 `(found, index, match_length, used_fuzzy, content_for_replacement)`
- `generate_diff_string(old_content, new_content, context_lines=4)` → 返回 `(diff_str, first_changed_line)`

### 4C：`rewrite_file` 工具（整体写入）

#### 需要参考的 pi-mono 代码

- **`packages/coding-agent/src/core/tools/write.ts`** 全文（286 行）
  - 第 14-17 行：`writeSchema` — 参数定义（`path`、`content`）
  - 第 25-35 行：`WriteOperations` 接口 — `writeFile()` 和 `mkdir()` 两个可插拔操作
  - 需要关注 `execute()` 中的目录创建逻辑（`dirname` + `mkdir recursive`）和 `withFileMutationQueue` 互斥保护

#### 本项目需要新建的文件

1. **`domain/llm/agent/tools/rewrite_file.py`** — rewrite_file 工具实现

#### 实现思路

**参数定义**：
- `path`（必填）：文件路径
- `content`（必填）：要写入的完整内容

**核心执行流程**：
1. 路径解析 + 安全校验（必须在项目目录内）
2. 文件互斥队列保护
3. 如果父目录不存在，递归创建（`os.makedirs(exist_ok=True)`）
4. 写入文件内容（先写临时文件再 rename，保证原子性）
5. 返回 `ToolResult`，`content` 为 `"Successfully wrote to {path}"`，`details` 包含写入字节数和行数

**安全考虑**：
- 禁止写入项目目录外的路径
- 对超大内容（如超过 150 行）给出警告信息，提示 LLM 考虑使用 `patch_file` 做局部修改

---

## 第五步：实现 ReAct 循环控制器

### 背景

这是整个 Agent 功能的核心——一个异步循环，负责"发送请求 → 解析响应 → 执行工具 → 回传结果 → 再次发送"的多轮交互。

### 需要参考的 pi-mono 代码

- **`packages/agent/src/agent-loop.ts`** 全文（617 行），这是最关键的参考文件：
  - 第 31-54 行：`agentLoop()` 入口函数 — 接收 prompts、context、config、signal，返回事件流
  - 第 155-232 行：`runLoop()` — 主循环逻辑
    - 第 168-229 行：外层 while 循环 + 内层 while 循环的双层结构
    - 第 191 行：`streamAssistantResponse()` 获取 LLM 回复
    - 第 194-198 行：检查 `stopReason`（error/aborted 则退出）
    - 第 201-202 行：从 assistant message 中过滤出 `toolCall` 类型的 content block
    - 第 205-212 行：有工具调用则执行并将结果推入消息列表
    - 第 214 行：发射 `turn_end` 事件
  - 第 238-331 行：`streamAssistantResponse()` — LLM 调用和流式处理
    - 第 246-252 行：`transformContext` → `convertToLlm` 消息转换链路
    - 第 254-259 行：构建 LLM 上下文（systemPrompt + messages + tools）
    - 第 267-271 行：调用 streamFunction 获取流式响应
    - 第 276-320 行：遍历流式事件并发射对应 AgentEvent
  - 第 336-348 行：`executeToolCalls()` — 根据配置选择顺序或并行执行
  - 第 350-388 行：`executeToolCallsSequential()` — 顺序执行
    - 三阶段：`prepareToolCall` → `executePreparedToolCall` → `finalizeExecutedToolCall`
  - 第 390-438 行：`executeToolCallsParallel()` — 并行执行
    - prepare 阶段顺序执行（因为可能有阻止逻辑），execute 阶段并行
  - 第 458-507 行：`prepareToolCall()` — 查找工具 + 参数校验 + beforeToolCall 拦截
    - 第 465-472 行：工具不存在 → 返回 `ImmediateToolCallOutcome` 错误
    - 第 475 行：`validateToolArguments(tool, toolCall)` 参数校验
    - 第 476-493 行：`beforeToolCall` 钩子可阻止执行
  - 第 509-544 行：`executePreparedToolCall()` — 实际执行工具 + 异常捕获
    - 第 517 行：调用 `tool.execute()` 
    - 第 537-543 行：异常 → 包装为 `createErrorToolResult`
  - 第 546-580 行：`finalizeExecutedToolCall()` — afterToolCall 钩子 + 结果可覆盖
  - 第 582-587 行：`createErrorToolResult()` — 创建错误工具结果
  - 第 589-616 行：`emitToolCallOutcome()` — 发射 `tool_execution_end` 事件并构建 `ToolResultMessage`

### 本项目需要新建的文件

1. **`domain/llm/agent/agent_loop.py`** — ReAct 循环控制器

### 本项目需要修改的文件

1. **`domain/llm/llm_executor.py`** — 需要新增 Agent 模式的入口方法
2. **`shared/event_types.py`** — 需要新增 Agent 相关事件常量

### 实现思路

**循环控制器的核心方法** `run(user_message, context)` 的流程（对照 `runLoop()` 第 155-232 行）：

1. **初始化消息列表**：包含 system 消息 + 历史消息 + 新的 user 消息
2. **获取工具 schema 列表**：从 `ToolRegistry` 获取 `get_all_schemas()`
3. **进入循环**（设置最大轮次，如 15 轮）：
   a. 发射 `turn_start` 事件
   b. 调用 `BaseLLMClient.chat_stream(messages, tools=schemas)` 获取流式响应
   c. 累积流式响应，期间发射 `message_update` 事件（UI 实时展示 LLM 输出）
   d. 流式结束后，检查是否包含 `tool_calls`：
      - **无 tool_calls**（`finish_reason != "tool_calls"`）→ 循环结束，发射 `agent_end`
      - **有 tool_calls** → 进入步骤 e
   e. 将 LLM 的 assistant 消息（包含 `tool_calls` 字段）追加到消息列表
   f. **三阶段执行每个工具调用**（对照 `agent-loop.ts` 第 458-580 行）：
      - **prepare**：从 `ToolRegistry.get(name)` 查找工具；参数校验；可选的前置拦截
      - **execute**：调用 `tool.execute()`，try-except 捕获异常包装为错误结果
      - **finalize**：发射 `tool_execution_end` 事件
   g. 将每个工具执行结果以 `{"role": "tool", "tool_call_id": "xxx", "content": "..."}` 格式追加到消息列表
   h. 回到步骤 3a

**与现有 LLMExecutor 的集成**：
- `LLMExecutor` 当前管理普通对话的异步任务。需要新增一个 `execute_agent()` 或类似入口方法
- Agent 循环期间的流式输出仍然通过 `LLMExecutor` 的信号/事件机制通知 UI
- Agent 循环的取消通过 `StopController` 的现有停止机制实现

**消息格式的关键细节**（对照 pi-mono `emitToolCallOutcome()` 第 589-616 行）：
- assistant 消息中的 `tool_calls` 字段必须完整保留并回传给下一轮 API 调用
- `role: tool` 消息的 `tool_call_id` 必须与对应的 `tool_calls` 中的 `id` 完全一致
- 如果 LLM 一次返回了多个 `tool_calls`（并行调用），需要为每一个都生成对应的 `role: tool` 消息，且顺序与 `tool_calls` 中的顺序一致

---

## 第六步：构建 Agent 系统提示词

### 背景

Agent 模式需要专用的系统提示词，告诉 LLM 有哪些工具可用、使用规范和项目上下文。

### 需要参考的 pi-mono 代码

- **`packages/coding-agent/src/core/system-prompt.ts`** 全文（169 行）
  - 第 8-25 行：`BuildSystemPromptOptions` — 选项接口（selectedTools、toolSnippets、promptGuidelines、contextFiles 等）
  - 第 28-168 行：`buildSystemPrompt()` 函数
    - 第 85-88 行：动态生成工具列表（格式：`- toolName: one-line description`）
    - 第 90-125 行：根据可用工具动态生成 guidelines（如有 grep/find/ls 工具则建议优先使用而非 bash）
    - 第 127-143 行：默认系统提示词模板——角色定义 + 工具列表 + 指南
    - 第 149-156 行：注入项目上下文文件
    - 第 163-165 行：注入当前日期和工作目录

- **`packages/coding-agent/src/core/tools/read.ts`** 第 123-126 行：工具自带的 `promptSnippet` 和 `promptGuidelines`
  - 每个工具可以声明自己的提示词片段，在构建系统提示词时自动汇总

### 本项目需要新建的文件

1. **`domain/llm/agent/agent_prompt_builder.py`** — Agent 系统提示词构建器

### 本项目可能需要修改的文件

1. **`domain/llm/identity_prompt_manager.py`** 或 **`domain/llm/system_prompt_injector.py`** — 需要支持在 Agent 模式下注入工具相关提示词

### 实现思路

**提示词构建流程**（对照 `buildSystemPrompt()` 第 28-168 行）：

1. **角色定义**：说明 LLM 是一个电路设计助手，可以通过工具读取和编辑本地文件
2. **可用工具列表**：从 `ToolRegistry` 获取每个工具的名称和一句话描述（参考 pi-mono 每个工具的 `promptSnippet` 字段），格式如 `- read_file: 读取文件内容，支持行号范围` 
3. **使用指南**：
   - "修改文件前先用 read_file 查看当前内容"
   - "小文件或新文件用 rewrite_file，大文件用 patch_file 做局部修改"
   - "patch_file 的 old_text 必须精确匹配文件中的内容"
   - "每次只做一处修改，完成后用 read_file 验证"
   - "SPICE 文件（.cir/.sp/.spice）使用特定语法，注意保留注释和格式"
4. **项目上下文**：
   - 当前工作目录
   - 当前打开的文件路径（如果有）
   - 当前日期
5. **组合**：将以上部分拼接为完整的系统提示词

**与现有提示词系统的集成**：
- 现有的 `identity_prompt_manager.py` 管理基础身份提示词
- Agent 模式下，需要在基础身份提示词的基础上追加工具相关提示词
- 可以通过 `system_prompt_injector.py` 的注入机制实现

---

## 第七步：集成到对话面板和 UI

### 背景

ReAct 循环产生的事件需要在对话面板中可视化呈现：LLM 文本输出实时流式展示，工具调用以卡片形式展示（工具名、参数、结果/diff）。

### 需要参考的 pi-mono 代码

pi-mono 的 UI 是终端 TUI，渲染方式与本项目的 Qt 界面差异很大，但其**事件 → UI 更新**的映射关系值得借鉴：

- **`packages/agent/src/types.ts`** 第 295-310 行：`AgentEvent` 联合类型
  - `tool_execution_start` → UI 开始显示工具调用卡片（工具名 + 参数）
  - `tool_execution_update` → UI 更新工具执行进度
  - `tool_execution_end` → UI 显示工具执行结果（成功/失败 + 详情）
  - `message_update` → UI 实时更新 LLM 流式输出文本
  - `turn_start` / `turn_end` → UI 显示轮次分隔

- **`packages/coding-agent/src/core/extensions/types.ts`** 第 326-397 行：`ToolRenderResultOptions` 和 `ToolDefinition` 的渲染相关接口
  - 展示了工具渲染分为 `renderCall`（调用时展示）和 `renderResult`（结果展示）两个阶段

### 本项目需要修改的文件

1. **`shared/event_types.py`** — 新增 Agent 相关事件常量
2. **`presentation/panels/chat/`** 相关文件 — 对话面板渲染逻辑
3. **`domain/llm/llm_executor.py`** — 新增 Agent 模式入口

### 实现思路

**事件定义**（新增到 `event_types.py`）：
- `EVENT_AGENT_TURN_START` — 新一轮循环开始
- `EVENT_AGENT_TURN_END` — 一轮循环结束
- `EVENT_TOOL_EXECUTION_START` — 工具开始执行（携带 tool_name、args）
- `EVENT_TOOL_EXECUTION_END` — 工具执行完毕（携带 result、is_error）
- `EVENT_AGENT_END` — Agent 循环结束

**对话面板集成**：
- Agent 循环期间的 LLM 流式文本输出，复用现有的流式展示逻辑
- 订阅 `EVENT_TOOL_EXECUTION_START` → 在对话面板中插入一个工具调用卡片（展示工具名和参数摘要）
- 订阅 `EVENT_TOOL_EXECUTION_END` → 更新工具调用卡片（展示执行结果，如果是 patch_file 则展示 diff）
- 订阅 `EVENT_AGENT_TURN_START` → 可选地显示"Agent 第 N 轮思考中..."

**LLMExecutor 集成**：
- 新增 `execute_agent(user_message, context)` 方法
- 该方法内部创建 `AgentLoop` 实例并运行
- 通过现有的 `stream_chunk` 信号传递流式文本输出
- 通过 `EventBus` 发布工具执行事件
- 支持通过 `StopController` 取消

---

## 第八步：端到端联调和验证

### 背景

所有组件实现后，需要端到端测试完整的 Agent 工具调用流程。

### 验证场景

1. **基础对话不受影响**：不涉及工具调用的普通对话仍正常工作
2. **read_file 基础测试**：用户提问"帮我查看 xxx.cir 文件的内容"，LLM 应调用 `read_file` 工具，UI 展示文件内容
3. **rewrite_file 基础测试**：用户提问"创建一个新的电路文件 test.cir"，LLM 应调用 `rewrite_file` 工具
4. **patch_file 基础测试**：用户提问"把 xxx.cir 中的电阻 R1 的值从 1k 改为 2k"，LLM 应先调用 `read_file` 查看文件，再调用 `patch_file` 修改
5. **多轮循环测试**：LLM 需要先读后改的场景，验证 ReAct 循环是否正确执行多轮
6. **错误恢复测试**：文件不存在、匹配失败等场景，LLM 应能根据错误反馈自行调整
7. **中断测试**：在 Agent 循环执行期间点击停止按钮，验证是否正确中断
8. **流式展示测试**：验证 LLM 的流式文本输出和工具调用卡片的渲染时序

### 需要关注的边界条件

- CRLF 行尾的 `.cir` 文件编辑是否正确
- 包含中文注释的电路文件读写是否正确
- 大文件（如超过 2000 行的网表）的截断和分段读取
- 多个 `tool_calls` 并行返回时的执行顺序
- 智谱 API 的深度思考模式与工具调用是否冲突

---

## 附录 A：智谱模型兼容性与多厂商适配

### 智谱模型工具调用能力

智谱 GLM-4 系列（GLM-4.7 / GLM-4.6V）原生支持 OpenAI 兼容的 Function Calling 协议。本项目的 `ZhipuRequestBuilder._apply_tools_config()` 和 `ZhipuResponseParser._normalize_tool_calls()` 已实现工具定义注入和响应解析。实现上述全部步骤后，智谱模型可以直接工作。

**特殊注意事项**：
- Agent 模式下建议默认关闭深度思考（`thinking=False`），确保工具调用稳定性
- `tool_calls` 消息的 assistant 消息必须完整回传（含 `tool_calls` 字段）
- 每个 `role: tool` 消息的 `tool_call_id` 必须与 LLM 返回的 `id` 完全对应

### 其他厂商适配

本项目的 `BaseLLMClient` 抽象基类已包含 `tools` 参数和 `ChatResponse.tool_calls` 字段，ReAct 循环控制器只依赖此接口。新增厂商只需实现 `BaseLLMClient` 子类，循环层和工具层零修改。

- **OpenAI / DeepSeek**：格式完全兼容，适配工作量极小
- **Anthropic Claude**：需在客户端层做格式转换（`parameters` → `input_schema`，`tool_use` block → `tool_calls` 字段）
- **国内厂商（百度/阿里）**：大部分兼容 OpenAI 格式

---

## 附录 B：pi-mono 关键文件速查表

| 文件路径 | 内容 | 被哪些步骤参考 |
|----------|------|----------------|
| `packages/agent/src/types.ts` | AgentTool、AgentToolResult、AgentEvent 类型定义 | 第二步、第五步、第七步 |
| `packages/agent/src/agent-loop.ts` | ReAct 循环实现、三阶段工具执行 | 第一步、第五步 |
| `packages/coding-agent/src/core/tools/read.ts` | read 工具完整实现 | 第四步 4A |
| `packages/coding-agent/src/core/tools/edit.ts` | edit 工具完整实现 | 第四步 4B |
| `packages/coding-agent/src/core/tools/write.ts` | write 工具完整实现 | 第四步 4C |
| `packages/coding-agent/src/core/tools/edit-diff.ts` | 行尾归一化、模糊匹配、BOM、diff 生成 | 第四步 4B |
| `packages/coding-agent/src/core/tools/file-mutation-queue.ts` | 文件写入互斥队列 | 第四步 4B |
| `packages/coding-agent/src/core/tools/truncate.ts` | 内容截断（按行数/字节数） | 第四步 4A |
| `packages/coding-agent/src/core/tools/path-utils.ts` | 路径解析和安全处理 | 第四步 4A |
| `packages/coding-agent/src/core/tools/index.ts` | 工具注册和分组 | 第三步 |
| `packages/coding-agent/src/core/system-prompt.ts` | 系统提示词构建 | 第六步 |
| `packages/coding-agent/src/core/extensions/types.ts` | ToolDefinition、事件类型、渲染接口 | 第二步、第七步 |

---

## 附录 C：本项目新建文件清单

| 新建文件 | 内容 | 所属步骤 |
|----------|------|----------|
| `domain/llm/agent/__init__.py` | Agent 模块初始化 | 第二步 |
| `domain/llm/agent/types.py` | BaseTool、ToolResult、ToolContext 等类型 | 第二步 |
| `domain/llm/agent/tool_registry.py` | 工具注册表 | 第三步 |
| `domain/llm/agent/tools/__init__.py` | 工具包初始化 | 第四步 |
| `domain/llm/agent/tools/read_file.py` | read_file 工具 | 第四步 4A |
| `domain/llm/agent/tools/patch_file.py` | patch_file 工具 | 第四步 4B |
| `domain/llm/agent/tools/rewrite_file.py` | rewrite_file 工具 | 第四步 4C |
| `domain/llm/agent/utils/__init__.py` | 工具函数包初始化 | 第四步 |
| `domain/llm/agent/utils/truncate.py` | 内容截断函数 | 第四步 4A |
| `domain/llm/agent/utils/path_utils.py` | 路径解析函数 | 第四步 4A |
| `domain/llm/agent/utils/edit_diff.py` | 行尾归一化、模糊匹配、diff | 第四步 4B |
| `domain/llm/agent/utils/file_mutex.py` | 文件写入互斥队列 | 第四步 4B |
| `domain/llm/agent/agent_loop.py` | ReAct 循环控制器 | 第五步 |
| `domain/llm/agent/agent_prompt_builder.py` | Agent 系统提示词构建 | 第六步 |
