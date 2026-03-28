# LightRAG 集成开发指南

> 纯开发步骤文档。覆盖从库配置到完整实现的全部环节。

---

## 一、环境与依赖配置

### 1.1 安装 LightRAG

```
pip install -e ../LightRAG-main
pip install zhipuai>=2.0.0
```

- 第一条命令以 editable install 引入 LightRAG，自动安装所有核心依赖
- 第二条命令显式安装智谱官方 SDK，**仅供 LightRAG 的 `zhipu_embedding` / `zhipu_complete` 函数使用**。本项目的 Chat 客户端（`ZhipuClient`）基于 httpx 直接调用 REST API，不使用此 SDK。预装是为了避免 LightRAG 的 `pipmaster` 在运行时自动 `pip install`

### 1.2 核心依赖清单（自动安装，供审计）

| 依赖包 | 用途 |
|--------|------|
| `nano-vectordb` | 轻量向量数据库（默认向量后端） |
| `networkx` | 知识图谱存储（默认图后端） |
| `numpy>=1.24.0` | 向量计算 |
| `tiktoken` | Token 分块 tokenizer |
| `json_repair` | 修复 LLM 输出的非标准 JSON |
| `tenacity` | 重试机制 |
| `aiohttp` | 异步 HTTP |
| `pydantic` | 数据模型验证 |
| `pypinyin` | 中文拼音处理（实体名归一化） |
| `python-dotenv` | .env 加载 |
| `pipmaster` | 动态依赖安装（**需注意桌面应用中禁用**） |
| `pandas>=2.0.0` | 数据处理 |
| `google-api-core`, `google-genai` | 核心依赖（本项目不使用但会被安装） |

### 1.3 pipmaster 处理

`lightrag/llm/zhipu.py` 中 `pm.install("zhipuai")` 会在 import 时触发。只要 `zhipuai` 已预装，`is_installed()` 返回 True 不会触发安装。若需彻底禁用，可在 RAGService 初始化前设置 pipmaster 全局开关。

---

## 二、Shared 层常量注册

### 2.1 `shared/service_names.py`

新增：
```python
SVC_RAG_SERVICE = "rag_service"
SVC_RAG_MANAGER = "rag_manager"
```

### 2.2 `shared/event_types.py`

新增：
```python
EVENT_RAG_MODE_CHANGED = "rag.mode_changed"       # {"enabled": bool}
EVENT_RAG_INDEX_STARTED = "rag.index_started"      # {"total_files": int, "track_id": str}
EVENT_RAG_INDEX_PROGRESS = "rag.index_progress"    # {"processed": int, "total": int, "current_file": str}
EVENT_RAG_INDEX_COMPLETE = "rag.index_complete"    # {"total_indexed": int, "failed": int, "duration_s": float}
EVENT_RAG_INDEX_ERROR = "rag.index_error"          # {"file_path": str, "error": str}
EVENT_RAG_QUERY_COMPLETE = "rag.query_complete"    # {"query": str, "results_count": int}
```

### 2.3 `infrastructure/config/settings.py`

新增 RAG 配置常量：
```python
DEFAULT_RAG_ENABLED = False
DEFAULT_RAG_STORAGE_DIR = ".circuit_ai/rag_storage"
DEFAULT_RAG_CHUNK_SIZE = 1200
DEFAULT_RAG_CHUNK_OVERLAP = 100
DEFAULT_RAG_QUERY_MODE = "mix"
DEFAULT_RAG_TOP_K = 10
DEFAULT_RAG_CONTEXT_TOKEN_BUDGET = 2000
DEFAULT_RAG_AUTO_INDEX = True
DEFAULT_RAG_ENTITY_TYPES = ["Component", "Circuit", "Parameter", "Specification", "Topology", "Signal", "Tool", "Standard", "Material", "Method"]
DEFAULT_RAG_LANGUAGE = "Chinese"
DEFAULT_EMBEDDING_MODEL = "embedding-3"
DEFAULT_EMBEDDING_DIM = 1024
```

---

## 三、Domain 层实现

### 3.1 `domain/rag/rag_service.py` — LightRAG 封装层

**职责**：封装 LightRAG 实例的创建、初始化、销毁；适配 LLM 和 Embedding 函数。

**存储后端**：JsonKVStorage + NanoVectorDBStorage + NetworkXStorage（LightRAG 默认，无需外部数据库）。

**工作目录**：`{project_root}/.circuit_ai/rag_storage/`，项目切换时销毁旧实例创建新实例。

**实例生命周期方法**：
- `create(project_root, llm_func, embedding_func)` → 创建 LightRAG 实例
- `initialize()` → `initialize_storages()`
- `finalize()` → `finalize_storages()`，项目关闭时必须调用

**LLM 适配器**（写在 rag_service.py 内部）：
- LightRAG 要求签名：`async def(prompt, system_prompt=None, history_messages=None, **kwargs) -> str`
- 从 ServiceLocator 获取 LLM 客户端
- `prompt` → `messages` 列表（user role），`system_prompt` → system message
- 收集流式 chunk 拼接为完整字符串
- `keyword_extraction=True` 时禁用流式
- 异常映射：LLMError → LightRAG 可理解的异常

**Embedding**（无需适配器文件）：
```python
from functools import partial
from lightrag.llm.zhipu import zhipu_embedding

embedding_func = partial(zhipu_embedding, api_key=api_key)  # api_key 从 CredentialManager 获取
# 传入 LightRAG(embedding_func=embedding_func)
```
- `zhipu_embedding` 已实现 `EmbeddingFunc`（dim=1024, max_token=8192, model=embedding-3）
- 内置 3 次重试 + 指数退避
- API Key 与 Chat API 共用，用户无需额外配置

### 3.2 `domain/rag/rag_manager.py` — 业务逻辑管理器

**方法清单**：

| 方法 | 功能 |
|------|------|
| `set_rag_enabled(enabled: bool)` | 切换 RAG 模式。开启时触发初始化，关闭时仅跳过检索（不销毁实例） |
| `index_project_files()` | 扫描项目目录，收集文件，调用 `RAGService.insert()` |
| `index_single_file(path: str)` | 单文件增量索引（先删后插） |
| `query(query_text, mode="mix") -> RAGQueryResult` | 调用 `aquery_data()` 获取纯数据，返回 entities/relations/chunks/references |
| `get_index_status() -> IndexStatus` | 返回索引状态 |
| `delete_document(doc_id: str)` | 删除文档及关联实体和关系 |

**文件扫描规则**：
- 包含：`.cir`, `.sp`, `.spice`, `.lib`, `.inc`, `.md`, `.txt`
- 排除：`.circuit_ai/`, `__pycache__`, `.git`, 二进制文件
- file_path 使用相对于 `project_root` 的路径

**增量索引**：
- 项目打开时：对比 `index_meta.json` 中 `mtime` 与磁盘实际 mtime
- 文件保存时：监听 `EVENT_FILE_EXTERNALLY_MODIFIED` 触发单文件重索引
- 手动触发：RAG 面板中全量重索引按钮

**`index_meta.json`** 位于 `{project_root}/.circuit_ai/rag_storage/`：
```json
{
  "version": 1,
  "project_root": "（绝对路径，仅校验用）",
  "last_full_index": "2024-01-15T10:30:00Z",
  "files": {
    "src/amp.cir": {
      "doc_id": "doc-a1b2c3...",
      "mtime": 1705312200.0,
      "size": 2048,
      "status": "processed",
      "chunks_count": 4,
      "indexed_at": "2024-01-15T10:30:05Z"
    }
  },
  "stats": { "total_files": 12, "processed": 11, "failed": 1, "total_chunks": 156, "total_entities": 89, "total_relations": 134 }
}
```

**`IndexStatus` 数据结构**：
```
IndexStatus:
  enabled: bool
  indexing: bool
  current_track_id: str | None
  stats: { total_files, processed, failed, total_chunks, total_entities, total_relations, storage_size_mb }
  files: list[FileIndexInfo]
    - relative_path: str
    - status: "processed" | "processing" | "failed" | "pending"
    - chunks_count: int
    - indexed_at: str
    - error: str | None
```

### 3.3 `domain/rag/document_watcher.py` — 文件变更检测

- 订阅 `EVENT_FILE_EXTERNALLY_MODIFIED` 和 FileWatcher 文件变更通知
- QTimer 2 秒防抖，批量处理累积变更
- 仅 RAG 模式开启时响应，仅处理符合扫描规则的扩展名

### 3.4 `domain/llm/agent/tools/rag_search.py` — Agent 工具

```
name: rag_search
description: 在项目知识库中搜索与查询相关的实体、关系和文档片段
parameters: query (str), mode (str, optional, default "mix")
返回: 格式化检索结果文本
```

- 仅在 RAG 模式开启且 RAGService 已初始化时注册到 ToolRegistry
- RAG 关闭时不注册

### 3.5 上下文自动注入

**修改 `domain/llm/agent/agent_prompt_builder.py`**：
- 构建系统提示词时检查 RAG 模式
- 开启则从 RAGManager 获取检索结果
- 作为 `## 知识库参考信息` 段落附加到系统提示词末尾
- Token 预算上限 2000（可配置），结果为空则不注入

**修改 `domain/llm/context_retrieval/`**：
- ContextRetriever 现有流程第 5 步后新增第 5.5 步：RAG 检索
- 条件：RAG 开启且 RAGService 可用
- 结果转 `ContextItem` 列表，source="rag"
- ContextAssembler 中为 RAG 来源定义优先级

---

## 四、Infrastructure 层实现

### 4.1 Embedding 可用性检测（已实现）

RAG 首次开启时，发送测试文本 `"test"` 调用 `zhipu_embedding` 验证 API Key：
- 失败 → 阻止 RAG 开启，EventBus 发布 `EVENT_RAG_INDEX_ERROR`，GUI 弹窗提示
- 成功 → `_embedding_verified = True`，后续不再重复验证
- API Key 变更时调用 `invalidate_embedding_cache()` 重置缓存

实现位置：`RAGManager.set_rag_enabled()` 中的 `_embedding_verified` 缓存机制 + `RAGService.test_embedding()`

### 4.2 `infrastructure/config/config_manager.py`（已实现）

新增方法：
- `get_rag_config(project_root: str) -> dict` — 读取 per-project RAG 配置
- `set_rag_config(project_root: str, config: dict) -> bool` — 保存 per-project RAG 配置
- 持久化到 `{project_root}/.circuit_ai/rag_config.json`（而非全局配置目录）
- 配置字段：`rag_enabled`、`rag_auto_index`、`rag_query_mode`、`rag_remember_state`

### 4.3 `infrastructure/config/settings.py` 新增常量（已实现）

```python
# RAG 配置字段名（per-project rag_config.json）
CONFIG_RAG_ENABLED = "rag_enabled"
CONFIG_RAG_AUTO_INDEX = "rag_auto_index"
CONFIG_RAG_QUERY_MODE = "rag_query_mode"
CONFIG_RAG_REMEMBER_STATE = "rag_remember_state"
RAG_CONFIG_FILE = "rag_config.json"
```

---

## 五、Application 层实现

### 5.1 `application/bootstrap.py`（已实现）

Phase 3 新增 `_init_rag_services()` 函数：
- **Phase 3.8.1**：创建 `RAGService` 实例 → 注册 `SVC_RAG_SERVICE`（仅创建，不初始化存储）
- **Phase 3.8.2**：创建 `RAGManager`（注入 RAGService）→ 注册 `SVC_RAG_MANAGER` → `subscribe_lifecycle_events()` 订阅 `EVENT_STATE_PROJECT_OPENED` / `EVENT_STATE_PROJECT_CLOSED`
- **Phase 3.8.3**：创建 `DocumentWatcher` → `start()` 订阅文件变更事件
- **Phase 3.8.4**：`GraphStateProjector.subscribe_rag_events()` — RAG 事件投影到 SessionState

### 5.2 项目生命周期联动（已实现）

**项目打开**（RAGManager.\_on\_project\_opened 收到 `EVENT_STATE_PROJECT_OPENED`）：
1. `set_project_root(project_root)` — 切换项目根目录，加载 `index_meta.json`
2. `_load_rag_config()` — 从 `rag_config.json` 读取上次 RAG 状态
3. 若 `rag_remember_state && rag_enabled` → `set_rag_enabled(True)` 恢复 RAG
4. `set_rag_enabled(True)` 内部：初始化 LightRAG（从磁盘加载已有存储）→ 验证 Embedding → 自动增量索引

**项目关闭**（RAGManager.\_on\_project\_closed 收到 `EVENT_STATE_PROJECT_CLOSED`）：
1. `_save_rag_config()` — 保存当前 RAG 状态到 `rag_config.json`
2. `RAGService.finalize()` — `finalize_storages()` 刷盘持久化
3. 清理内存中的 LightRAG 实例和元数据

### 5.3 `application/session_state.py`（已实现）

新增只读属性（由 `GraphStateProjector` 订阅 RAG 事件后投影更新）：
- `rag_enabled: bool` — RAG 是否开启
- `rag_indexing: bool` — 是否正在索引
- `rag_index_status: dict` — 索引状态详情（status/total_files/processed/error 等）

常量：`SESSION_RAG_ENABLED`、`SESSION_RAG_INDEXING`、`SESSION_RAG_INDEX_STATUS`

### 5.4 `application/graph_state_projector.py`（已实现）

新增 `subscribe_rag_events()` 方法，订阅以下 RAG 事件并投影到 SessionState：
- `EVENT_RAG_MODE_CHANGED` → `SESSION_RAG_ENABLED`
- `EVENT_RAG_INDEX_STARTED` → `SESSION_RAG_INDEXING=True` + 状态详情
- `EVENT_RAG_INDEX_PROGRESS` → 更新进度信息
- `EVENT_RAG_INDEX_COMPLETE` → `SESSION_RAG_INDEXING=False` + 完成统计
- `EVENT_RAG_INDEX_ERROR` → 错误状态

`clear_project_state()` 同时重置 RAG 状态字段

### 5.5 RAG 索引持久化机制（已实现）

**三层持久化架构：**

| 层级 | 存储位置 | 内容 | 更新时机 |
|------|---------|------|----------|
| LightRAG 存储 | `{project_root}/.circuit_ai/rag_storage/` | KV/Vector/Graph 数据 | `finalize_storages()` 刷盘 |
| 索引元数据 | `.circuit_ai/rag_storage/index_meta.json` | 文件 doc_id/mtime/status | 每次索引操作后 |
| RAG 配置 | `.circuit_ai/rag_config.json` | enabled/auto_index/mode | 模式切换/项目关闭时 |

**持久化场景验证：**
- RAG OFF→ON→OFF→ON：关闭时不销毁存储，重新开启时从磁盘加载
- 跨 session：`finalize_storages()` 刷盘 + `rag_config.json` 记录状态 → 下次打开自动恢复
- 增量更新：mtime 对比仅索引变更文件 + 删除文件自动清理
- 实时监听：DocumentWatcher 2s 防抖单文件重索引

---

## 六、Presentation 层实现

### 6.1 RAG 知识库 Tab（`presentation/panels/rag_panel.py`，新增）

RAG 面板作为**顶层 Tab 标签页**，与「对话」「调试」并列，成为主界面第三个一级入口。

**Tab 标签**：图标 + "知识库"，Tab 上可附加微型状态指示（如索引中的小圆点动画）。

**面板布局**（从上到下）：

1. **顶栏**：RAG 总开关（Switch）+ 状态标签（"已就绪" / "索引中 5/12" / "未开启"）
2. **统计概览行**：文档数 / 分块数 / 实体数 / 关系数 / 存储占用（紧凑单行）
3. **索引操作区**：
   - 按钮：「索引项目文件」「清空知识库」
   - 索引进度条（仅索引中可见）
4. **已索引文档列表**：
   - 列：文件名、相对路径、状态（颜色编码）、分块数、索引时间
   - 右侧操作：重新索引 / 移除
   - 失败项红标，双击打开文件
5. **检索测试区**（折叠面板）：
   - 输入框 + 检索模式选择（local/global/mix）+ 执行按钮
   - 结果区：实体、关系、文档片段分 tab 展示
6. **配置区**（折叠面板）：
   - 基础：自动索引开关 / 检索模式 / 记住 RAG 状态
   - 高级：分块大小 / 重叠 / top_k / Token 预算 / 实体类型 / 提取语言

**交互行为**：
- 总开关触发 `RAGManager.set_rag_enabled()`，监听 `EVENT_RAG_MODE_CHANGED` 更新 UI
- 索引操作触发 `RAGManager.index_project_files()`，监听进度/完成事件更新列表和进度条
- 面板状态通过 `SessionState.rag_enabled` / `rag_indexing` / `rag_index_status` 读取

### 6.2 对话面板中的 RAG 来源卡片

**修改 `presentation/panels/conversation/web_message_view.py`**：

- 助手消息上方折叠卡片："参考了 N 个知识库来源"
- 展开：文件路径（可点击跳转）、文本片段摘要、相关度分数
- 样式与现有 ops-card 一致
- 数据来源：消息 metadata 中的 `rag_references`

### 6.3 底部状态栏 RAG 指示

**修改 `presentation/panels/bottom_panel.py`**：
- RAG 关闭时不显示 | 空闲：图标 + "RAG" | 索引中：图标 + "索引中 5/12" + 微型进度条
- 点击切换到知识库 Tab

---

## 七、LLM 集成（统一 RAG 注入）

### 设计原则

RAG 检索统一在 **`ContextRetriever`（步骤 5.5）** 中完成，作为上下文组装流水线的一个环节。无论 LLM 以常规模式还是 Agent 模式运行，RAG 结果都通过同一条路径注入，LLM 无需感知 RAG 的存在。

**不再需要**：
- ~~`llm_executor.py` 中单独查询 RAG~~
- ~~`agent_prompt_builder.py` 中的 `rag_context` 参数~~
- ~~`RAGSearchTool` Agent 工具~~

### 7.1 `domain/llm/context_retrieval/context_retriever.py`（已实现）

现有上下文组装流程中，步骤 5.5 自动检查 RAG 模式：
1. `RAGManager.enabled` 为 True 且 `RAGService.is_initialized`
2. 提取用户查询 → `RAGManager.query()` 获取结构化结果
3. 将 entities / relationships / chunks 转为 `RetrievalResult` 列表
4. 由 `ContextAssembler` 统一分配 Token 预算，与其他上下文来源合并

### 7.2 检索结果持久化

**修改 `conversation_view_model.py`**：
- `_on_llm_generation_complete` 中将 `rag_references` 保存到消息 metadata
- 历史消息加载时还原来源卡片

---

## 八、实施阶段与验证

### 阶段一：基础设施搭建（已完成）

1. `pip install -e ../LightRAG-main` + `pip install zhipuai>=2.0.0`
2. 创建 `domain/rag/` 目录结构
3. 实现 `rag_service.py`、`rag_manager.py`、`document_watcher.py`
4. 在 `settings.py` / `service_names.py` / `event_types.py` 添加常量
5. 在 `bootstrap.py` Phase 3.8 注册服务 + 生命周期事件订阅
6. 在 `config_manager.py` 新增 per-project RAG 配置持久化
7. 在 `session_state.py` / `graph_state_projector.py` 新增 RAG 状态投影

**验证**：命令行脚本测试文档摄入和检索

### 阶段二：LLM 集成（已完成）

1. 修改 `context_retriever.py`：步骤 5.5 RAG 检索，统一注入上下文

**验证**：对话中开启 RAG，确认回答包含知识库信息

### 阶段三：GUI 集成（已完成）

1. 新建 `rag_panel.py`：知识库 Tab 标签页（与对话/调试并列）— 开关、索引操作、进度、文档列表、检索测试区
2. `main_window.py` 注册 RAG Tab + `_retranslate_tab_titles` 更新
3. `tab_controller.py` 添加 `TAB_RAG` 常量 + `core/__init__.py` 导出
4. 创建 `resources/icons/panel/knowledge.svg` 图标
5. 修改 `statusbar_manager.py`：RAG 状态指示（开关/索引进度/点击切换 Tab）
6. 修改 `web_message_view.py`：RAG 来源卡片（折叠式紫色卡片 + CSS + JS toggle）
7. 修改 `conversation_view_model.py`：`DisplayMessage` 新增 `rag_references` 字段，加载时从 LangChain 消息读取
8. `rag_references` 全链路传递：`ContextRetriever` → `LLMExecutor` → `ContextManager` → `MessageStore` → `DisplayMessage`
9. `llm_executor.py`：`execute_agent` 中调用 `ContextRetriever.retrieve_async` 注入 RAG 上下文到系统提示词
10. 清理冗余 RAG 代码：`agent_prompt_builder` 移除 `rag_context`，`tools/__init__.py` 移除 `RAGSearchTool`

**验证**：完整用户流程（开启 → 索引 → 对话 → 查看来源）

### 阶段四：增强功能（已完成）

1. 文件变更自动增量索引（`DocumentWatcher` 已实现）
2. 检索测试面板（`rag_panel.py` 折叠式检索测试区）
3. 项目生命周期联动完善（已实现）

**验证**：自动索引、增量更新、配置持久化

---

## 九、风险缓解备忘

| 风险 | 缓解 |
|------|------|
| Embedding API 调用成本 | LightRAG 内置 `embedding_cache_config`；异步执行不阻塞 UI；手动触发选项 |
| 实体提取 LLM 耗时 | LightRAG `enable_llm_cache`；进度事件反馈；支持取消；分批处理 |
| asyncio 事件循环冲突 | 所有 LightRAG 异步调用通过 qasync 事件循环执行；适配 `always_get_an_event_loop()` |
| NanoVectorDB 内存占用 | 电路项目文件通常不大；提供清理机制 |
| Token 预算超支 | ContextAssembler 统一管理；RAG 上下文设独立预算上限 |

---

## 十、测试清单

### 单元测试
- `test_rag_service.py`：初始化、插入、查询、销毁
- `test_rag_manager.py`：模式切换、文件扫描、增量索引
- `test_embedding_availability.py`：`zhipu_embedding` + API Key 可用性、返回维度
- `test_rag_search_tool.py`：参数验证、执行

### 集成测试
- 完整摄入：项目文件 → 分块 → 实体提取 → 存储
- 完整检索：查询 → 关键词提取 → 向量检索 → 上下文构建
- 对话集成：RAG 模式下回答质量
- 生命周期：打开 → 索引 → 关闭 → 重新打开 → 数据恢复

### GUI 测试
- RAG 开关状态同步
- 索引进度实时更新
- 来源卡片渲染和交互
- 文件跳转
