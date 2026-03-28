# RAG 重构设计文档
## 从 LightRAG（知识图谱）迁移到 Embedding-only 向量检索

---

## 决策背景

当前使用 LightRAG 的核心问题：**每个文本 chunk 都需要调用 LLM API 抽取实体/关系**，导致索引 1 个 PDF 需要 7~8 分钟。这是架构性瓶颈，无法通过调参解决。

Cursor、GitHub Copilot、Codeium 等主流 AI IDE 的索引方案均基于 **纯向量检索（Embedding-only RAG）**：

```
文件变更
  → 分块（无 LLM 调用）
  → 本地 Embedding 模型生成向量（~1ms/chunk）
  → 写入本地向量数据库
  
查询
  → 查询文本 Embedding（~1ms）
  → 余弦相似度 Top-K（~5ms）
  → 返回原文片段
```

索引 100 个 chunk 耗时从 **~70 分钟** 降至 **~1 秒**。代价是失去知识图谱推理能力，但对本项目（电路设计辅助）的实际检索需求，向量相似度已完全够用。

**已有依赖可直接复用**（requirements.txt 中已有）：
- `chromadb>=0.4.0` → 本地持久化向量数据库，替代 LightRAG 的 KV/Vector 存储
- `sentence-transformers>=3.3.0` → 本地 Embedding 模型，无网络调用

---

## 修改步骤

### Step 1：删除 `rag_service.py`

**操作**：整个文件删除。

**原因**：该文件是 LightRAG 实例的完整封装层（初始化 / LLM 适配 / Embedding 适配 / insert / query / delete / finalize）。新架构直接使用 ChromaDB 和 sentence-transformers，不再需要这一层。

**附带清理**：
- `requirements.txt` 中删除 `lightrag-hku==1.4.11` 这一行
- `domain/rag/__init__.py` 中删除 `from domain.rag.rag_service import RAGService` 和对应的 `__all__` 条目
- `bootstrap.py`（Application 层）中删除 `RAGService` 的创建和注入逻辑

---

### Step 2：新建 `domain/rag/chunker.py`（新增）

**职责**：将单个文件的文本内容拆分为适合向量检索的 chunk 列表。每个 chunk 携带元数据（起始字符位置、行号、所属结构名称）。

**设计要点**：

**按文件类型选择不同的分块策略，是本步骤最核心的设计。**

#### 策略 1：代码文件（`.py` `.js` `.ts` `.c` `.cpp` `.java` `.go` 等）

- **结构感知分块**：扫描文本行，以顶层结构定义行（如 `def ` / `class ` / `function ` 出现在行首，缩进为 0）作为 chunk 边界。每个顶层函数/类是一个 chunk。
- **元数据**：记录函数/类名称作为 `symbol_name` 写入 chunk 元数据，查询结果展示时可提示来自哪个函数。
- **最大 chunk 字符数**：3000 字符（约 800 token）。超长函数按 2000 字符重叠 200 字符切分。
- **文件头部（import / 全局变量区）**：单独作为一个 chunk，打上 `chunk_type=header` 标记。

#### 策略 2：电路仿真文件（`.cir` `.sp` `.spice` `.sub`）

- 按 `.subckt` / `.ends` 边界切分，每个子电路定义一个 chunk。
- 如果文件没有 `.subckt` 声明（顶层网表），按 500 行为单位切分，重叠 50 行。

#### 策略 3：Markdown / 文本文件（`.md` `.txt` `.rst`）

- 按**双换行（段落）**切分。连续的小段落合并，直到达到 1500 字符上限后截断为新 chunk。
- Markdown 的 `##` / `###` 标题行作为强制切分边界（即使未达到字符上限）。
- 重叠策略：每个 chunk 末尾保留最后一段内容作为下一个 chunk 的开头。

#### 策略 4：PDF（`.pdf`）

- `file_extractor.py` 已经逐页提取，每页文本作为天然边界。
- 在此基础上，若单页文本超过 2000 字符则按段落再次切分。
- 若单页文本少于 200 字符（页眉/页脚/图注），合并到相邻 chunk。

#### 策略 5：配置 / 数据文件（`.json` `.yaml` `.toml` `.xml`）

- 固定大小滑动窗口：2000 字符，重叠 400 字符。
- JSON 文件尝试在顶层 key 边界切分（按行扫描顶层 `"key":` 结构）。

#### 策略 6：DOCX / 其他文本

- 按段落切分（python-docx 提供段落列表），合并小段落，上限 1500 字符。

**输出结构**：`chunker.py` 导出一个 `Chunk` 数据类和 `chunk_file(content, file_type, file_path) -> List[Chunk]` 函数。每个 `Chunk` 包含：
- `content: str` — chunk 原文
- `chunk_id: str` — `{file_path_hash}_{chunk_index}` 作为向量数据库主键
- `metadata: dict` — `{file_path, chunk_index, file_type, start_char, end_char, symbol_name}`

---

### Step 3：新建 `domain/rag/embedder.py`（新增）

**职责**：封装本地 Embedding 模型，提供批量向量化接口。

**设计要点**：

**模型选择**：`all-MiniLM-L6-v2`（句子级语义相似度，384 维，模型文件约 90MB，推理 ~0.5ms/chunk，适合代码和文档混合场景）。句子向量模型第一次调用时会下载模型权重到本地缓存，之后完全离线。

**懒加载**：模型在第一次索引触发时才加载进内存，不在 bootstrap 阶段阻塞 UI 启动。用 `threading.Lock` 保证多线程安全的单例初始化。

**批量处理**：接受 `List[str]` 输入，内部以 64 个为一批调用 `model.encode(batch)`，返回 `numpy.ndarray`（shape: `[n, 384]`）。批量处理可将总耗时从 n×0.5ms 降低到 n×0.15ms（GPU 加速时差异更大）。

**接口**：`embed_texts(texts: List[str]) -> List[List[float]]`，调用方不感知模型细节。

**模型路径**：通过 `settings.py` 中新增 `DEFAULT_EMBEDDING_MODEL_NAME = "all-MiniLM-L6-v2"` 统一管理，不硬编码。

---

### Step 4：新建 `domain/rag/vector_store.py`（新增）

**职责**：封装 ChromaDB，提供 chunk 级别的 CRUD 和向量检索接口。

**设计要点**：

**Collection 隔离策略**：每个项目使用独立 ChromaDB Collection，Collection 名称为 `project_{md5(project_root_abs_path)[:12]}`。Collection 创建时指定 `cosine` 距离函数。

**持久化路径**：ChromaDB 的 `persist_directory` 设为 `{project_root}/.circuit_ai/vector_store/`，与现有 `rag_storage/` 平行，不混用。

**Upsert 语义**（单文件重索引的核心）：索引单个文件时，先按 `where={"file_path": rel_path}` 删除该文件的所有旧 chunk，再批量插入新 chunk。这保证了文件修改后旧向量不残留。

**插入接口**：`upsert_chunks(chunks: List[Chunk], vectors: List[List[float]])` — 将 chunk 的 `chunk_id` 作为 ChromaDB document id，`content` 作为 document，`vector` 直接写入（跳过 ChromaDB 内置 embedding，因为我们自己管理向量）。

**查询接口**：`query(vector: List[float], top_k: int, filter_path: str = None) -> List[QueryHit]`，返回 `QueryHit` 列表，每项包含 `content`、`metadata`、`score`（距离转相似度）。支持可选的 `filter_path` 将检索范围限制在单个文件内。

**ChromaDB 客户端模式**：使用 `chromadb.PersistentClient`（ChromaDB 0.4+ API），不启动独立服务进程，完全嵌入式运行，与 LightRAG 的 JSON 文件存储类似。

---

### Step 5：重构 `rag_manager.py`

这是改动最集中的文件。保持对外公共接口不变（`index_project_files` / `index_single_file` / `query` / `trigger_index` / `trigger_index_single_file`），内部全部重写。

**5.1 构造函数**

移除 `RAGService` 依赖。改为依赖注入 `Embedder` 和 `VectorStore`（或在构造函数内直接实例化）。`RAGWorkerThread` 依然保留（仍需在后台线程处理，避免 Qt UI 卡顿）。

**5.2 `is_available` 属性**

旧实现依赖 `RAGService.is_initialized`（需要 LightRAG 完成异步初始化才能使用）。新实现简化为：ChromaDB PersistentClient 存在 + Embedder 能正常加载即可。初始化变成同步操作，不需要等待 LightRAG 的 `initialize_storages()`。

**5.3 `_async_init_for_project()`**

旧实现：调用 `RAGService.initialize()`（异步，耗时 2~5 秒），等待 LightRAG storages 就绪。

新实现：
1. 创建 `{project_root}/.circuit_ai/vector_store/` 目录
2. 实例化 `VectorStore`（同步，~100ms）
3. 加载 `index_meta.json`（同步）
4. 触发增量索引

整个初始化时间从 **5 秒** 降到 **< 200ms**。

**5.4 `_index_single_file_internal()`**

旧实现：
1. `_read_file_safe()` 读取内容
2. `await rag_service.insert()` → LLM 抽取实体 → 写入 KV/Vector 存储

新实现：
1. `extract_content(abs_path)` 读取内容（沿用 `file_extractor.py`，逻辑不变）
2. `chunker.chunk_file(content, file_type, rel_path)` → `List[Chunk]`
3. `embedder.embed_texts([c.content for c in chunks])` → `vectors`
4. `vector_store.upsert_chunks(chunks, vectors)`
5. 更新 `index_meta` 记录 `mtime`、`chunks_count`、`status="processed"`

整个函数不再是 `async`，改为同步函数（Embedding 和 ChromaDB 都是同步 API）。

**5.5 `query()`**

旧实现：`await rag_service.query()` → LightRAG 图谱遍历 + 向量检索 → `RAGQueryResult`

新实现：
1. `vector = embedder.embed_texts([query_text])[0]`
2. `hits = vector_store.query(vector, top_k=top_k)`
3. 构造 `RAGQueryResult`（见 Step 6）

**5.6 线程模型调整**

旧实现：`RAGWorkerThread` 持有专用 asyncio 事件循环，因为 LightRAG 的 `ainsert/aquery` 是 async 协程。`submit()` 用 `asyncio.run_coroutine_threadsafe()` 跨线程提交协程。

新实现：Embedding 和 ChromaDB 都是同步阻塞调用，不需要 asyncio。`RAGWorkerThread` 改为普通后台线程 + `concurrent.futures.ThreadPoolExecutor`（1 worker），`submit()` 用 `executor.submit(fn)` 替代 `asyncio.run_coroutine_threadsafe`，返回 `Future` 接口保持不变，上层调用方（`trigger_index`、`query_async`）无需修改。

**5.7 删除的方法**

- `_init_lightrag()` — LightRAG 初始化，整体删除
- `_finalize_for_project()` — LightRAG `finalize_storages()`，整体删除
- `_cleanup_deleted_files()` 中的 `await rag_service.delete_document(doc_id)` — 改为 `vector_store.delete_by_file(rel_path)`

---

### Step 6：重构 `RAGQueryResult`（在 `vector_store.py` 中定义）

旧 `RAGQueryResult` 的字段：`entities`、`relationships`、`chunks`、`references`、`metadata`——大部分是知识图谱概念。

新 `RAGQueryResult` 简化为：
- `chunks: List[ChunkHit]`，每项包含 `content`、`file_path`、`score`、`symbol_name`
- `is_empty: bool`
- `format_as_context(max_tokens) -> str`：保持现有实现逻辑，只需将数据来源从 `self.chunks` 改为新字段

`format_as_context` 格式改为：
```
### {file_path}  [{symbol_name}]
{chunk content}
---
```

`rag_search` 工具使用 `format_as_context()` 格式化结果注入 Agent 上下文，接口不变，无需修改工具代码。

---

### Step 7：简化 `rag_worker.py`

旧实现：`RAGWorkerThread` 创建专用 asyncio 事件循环（`asyncio.new_event_loop()` / `loop.run_forever()`），因为 LightRAG 是纯 async 设计。

新实现：改为 `threading.Thread` + 内置 `ThreadPoolExecutor(max_workers=1)`：
- `run()`：创建 executor，设置 `_ready` 事件
- `submit(fn, *args)`：改为 `executor.submit(fn, *args)` 返回 `concurrent.futures.Future`
- `stop()`：`executor.shutdown(wait=True)`

`query_async()` 在 `rag_manager.py` 中依然使用 `await asyncio.wrap_future(future)`，Qt 协程侧完全不需要修改。

---

### Step 8：保持 `document_watcher.py` 不变

`DocumentWatcher` 监听 `EVENT_FILE_EXTERNALLY_MODIFIED` → 防抖 2 秒 → 调用 `manager.trigger_index_single_file(file_path)` 的逻辑完全正确，无需修改。

---

### Step 9：保持 `file_extractor.py` 不变

内容提取逻辑（PDF/DOCX/代码文本提取）与向量化逻辑解耦，`extract_content()` 作为 `chunker.py` 的上游输入保持不变。

---

### Step 10：更新 `domain/rag/__init__.py`

- 删除 `from domain.rag.rag_service import RAGService`
- 新增 `from domain.rag.vector_store import VectorStore, RAGQueryResult`
- 新增 `from domain.rag.chunker import chunk_file, Chunk`
- 新增 `from domain.rag.embedder import Embedder`
- 更新 `__all__`

---

### Step 11：更新 `infrastructure/config/settings.py`

新增以下配置常量：
- `DEFAULT_EMBEDDING_MODEL_NAME = "all-MiniLM-L6-v2"` — 可替换为更大模型
- `DEFAULT_VECTOR_STORE_DIR = ".circuit_ai/vector_store"` — ChromaDB 存储路径
- `DEFAULT_CHUNK_MAX_CHARS = 3000` — 代码分块上限
- `DEFAULT_CHUNK_OVERLAP_CHARS = 200` — 分块重叠

删除不再使用的 LightRAG 相关常量：
- `DEFAULT_RAG_CHUNK_SIZE`
- `DEFAULT_RAG_CHUNK_OVERLAP`
- `DEFAULT_RAG_ENTITY_TYPES`
- `DEFAULT_RAG_LANGUAGE`
- `DEFAULT_EMBEDDING_DIM`
- `DEFAULT_EMBEDDING_MAX_TOKEN_SIZE`

---

## 实施顺序建议

| 顺序 | 步骤 | 风险 |
|------|------|------|
| 1 | Step 2：实现 `chunker.py` | 纯逻辑，无依赖，可单独测试 |
| 2 | Step 3：实现 `embedder.py` | 依赖 sentence-transformers，验证模型可正常加载 |
| 3 | Step 4：实现 `vector_store.py` | 验证 ChromaDB upsert/query 行为 |
| 4 | Step 5+6：重构 `rag_manager.py` 和 `RAGQueryResult` | 核心，完成后可端对端测试 |
| 5 | Step 7：简化 `rag_worker.py` | 影响线程模型，需确认 Qt 主线程不被阻塞 |
| 6 | Step 1：删除 `rag_service.py` + LightRAG | 放最后，确认新链路完全工作后再删 |
| 7 | Step 10+11：清理 imports 和 settings | 收尾 |

---

## 预期效果对比

| 指标 | 旧（LightRAG） | 新（Embedding-only） |
|------|---------------|----------------------|
| 索引 1 PDF（10 chunk）| ~470 秒 | ~2 秒 |
| 索引 1 代码文件（20 chunk）| ~200 秒 | < 1 秒 |
| 查询延迟 | ~3 秒（API 往返） | ~50ms（本地计算） |
| 首次启动初始化 | ~5 秒 | < 200ms |
| 知识图谱推理 | ✓ | ✗ |
| 语义相似度检索 | ✓ | ✓ |
| 网络依赖（索引时） | 必须联网 | 完全离线 |
