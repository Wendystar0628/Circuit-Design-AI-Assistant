"""
默认设置常量定义

职责：定义系统级默认配置值，作为配置缺失时的回退
设计原则：纯常量定义，无业务逻辑，便于全局引用
"""

from pathlib import Path

# ============================================================
# 工作流相关默认值
# ============================================================

DEFAULT_MAX_CHECKPOINTS = 20         # 最大检查点次数
DEFAULT_STAGNATION_THRESHOLD = 3     # 停滞判断阈值（连续N次无改进则停止）
DEFAULT_CONTEXT_LIMIT_RATIO = 0.8    # 上下文占用触发总结的阈值（80%）

# ============================================================
# 追踪相关常量（阶段 1.5）
# ============================================================

DEFAULT_TRACING_ENABLED = True                # 默认启用追踪
DEFAULT_TRACING_FLUSH_INTERVAL_MS = 500       # 追踪缓冲区刷新间隔（毫秒）
DEFAULT_TRACING_MAX_BUFFER_SIZE = 100         # 追踪缓冲区上限
DEFAULT_TRACING_RETENTION_DAYS = 7            # 追踪数据保留天数
DEFAULT_TRACING_LOG_INPUTS_OUTPUTS = True     # 是否记录输入输出
DEFAULT_DEBUG_RERAISE_ASYNC_ERRORS = False    # 异步槽异常是否重新抛出
DEFAULT_DEBUG_SHOW_DEVTOOLS_PANEL = True      # 是否显示调试面板
TRACING_DB_FILE = "traces.sqlite3"            # 追踪数据库文件名

# ============================================================
# 上下文压缩相关默认值
# ============================================================

# 压缩触发阈值
COMPRESS_AUTO_THRESHOLD = 0.80       # 自动压缩阈值（上下文占用 80% 时自动压缩）
COMPRESS_HINT_THRESHOLD = 0.60       # 手动压缩提示阈值（上下文占用 60% 时提示用户）

# 压缩目标（激进策略，参考现代 AI IDE 如 Cursor）
# 理由：128k 上下文的 20% = 25k tokens，足够电路设计场景
COMPRESS_TARGET_RATIO = 0.20         # 压缩后目标占用比例（20%）
DEFAULT_KEEP_RECENT_MESSAGES = 3     # 压缩时默认保留的最近消息数（减少到3条）

# 分层压缩策略（参考 Cursor/Windsurf 机制）
# 层级1：系统提示（始终保留完整）
# 层级2：当前任务上下文（最近 N 条消息，完整保留）
# 层级3：相关历史（按相关性检索，摘要形式）
# 层级4：全局摘要（结构化 JSON，极度压缩）
COMPRESS_LAYER_RECENT_FULL = 3       # 层级2：完整保留的最近消息数
COMPRESS_LAYER_HISTORY_SUMMARY = 10  # 层级3：保留摘要的历史消息数
COMPRESS_ENABLE_SEMANTIC_RETRIEVAL = True  # 是否启用语义检索历史（未来功能）

# ============================================================
# 增强清理策略配置（激进压缩）
# ============================================================

# 深度思考内容清理（reasoning_content 占用大量 token，激进清理）
KEEP_REASONING_RECENT_COUNT = 1      # 仅保留最近 1 条消息的 reasoning_content
REASONING_TRUNCATE_LENGTH = 0        # 旧消息 reasoning_content 完全清除

# 操作记录清理
OPERATIONS_MERGE_ENABLED = True      # 启用操作记录合并
OPERATIONS_MAX_PER_MESSAGE = 3       # 每条消息最多保留 3 个操作（减少）
OPERATIONS_DEDUP_ENABLED = True      # 启用操作记录去重

# 摘要管理（使用结构化摘要，更紧凑）
SUMMARY_REPLACE_ON_COMPRESS = True   # 压缩时用新摘要替换旧摘要
SUMMARY_MAX_LENGTH = 1000            # 摘要最大长度（减少到 1000 字符）
SUMMARY_USE_STRUCTURED = True        # 使用结构化 JSON 摘要（更紧凑）

# 消息内容截断（更激进）
OLD_MESSAGE_TRUNCATE_LENGTH = 500    # 旧消息 content 截断到 500 字符
TRUNCATE_PRESERVE_CODE_BLOCKS = False # 不保留代码块完整性（代码应通过 RAG 检索）

# 代码块处理（参考 Cursor 机制）
CODE_BLOCK_MAX_LINES = 20            # 代码块最多保留 20 行
CODE_BLOCK_EXTRACT_TO_RAG = True     # 将代码块提取到 RAG 索引（未来功能）

# ============================================================
# 自适应压缩策略配置
# ============================================================

# 自适应压缩：根据压缩后实际占比动态调整策略
COMPRESS_ADAPTIVE_ENABLED = True     # 是否启用自适应压缩

# 压缩后占比 < 20%：正常，无需额外处理
# 压缩后占比 > 20%：触发更激进的压缩策略

# 二次压缩阈值和参数（当首次压缩未达标时）
COMPRESS_SECONDARY_THRESHOLD = 0.25  # 二次压缩触发阈值（首次压缩后 > 25%）
COMPRESS_SECONDARY_KEEP_RECENT = 2   # 二次压缩时保留的最近消息数（减少到2条）
COMPRESS_SECONDARY_TRUNCATE_LEN = 200  # 二次压缩时消息截断长度

# 极端压缩阈值和参数（当二次压缩仍未达标时）
COMPRESS_EXTREME_THRESHOLD = 0.30    # 极端压缩触发阈值（二次压缩后 > 30%）
COMPRESS_EXTREME_KEEP_RECENT = 1     # 极端压缩时仅保留最近 1 条消息
COMPRESS_EXTREME_SUMMARY_ONLY = True # 极端压缩时丢弃所有历史，仅保留摘要

# 压缩失败处理
COMPRESS_MAX_ATTEMPTS = 3            # 最大压缩尝试次数
COMPRESS_FALLBACK_NEW_CONVERSATION = True  # 压缩失败时是否建议开启新对话

# ============================================================
# LLM API 相关默认值
# ============================================================

DEFAULT_TIMEOUT = 60                 # LLM API 普通请求超时秒数
DEFAULT_STREAMING = True             # 默认启用流式输出
DEFAULT_LLM_PROVIDER = ""            # 默认 LLM 提供者（空表示未配置）
DEFAULT_MODEL = "glm-4.6"            # 默认模型名称
DEFAULT_BASE_URL = "https://open.bigmodel.cn/api/paas/v4"  # 智谱 API 默认端点

# ============================================================
# LLM 厂商常量
# ============================================================

LLM_PROVIDER_ZHIPU = "zhipu"           # 智谱 AI（已实现）
LLM_PROVIDER_SILICONFLOW = "siliconflow"  # 硅基流动（多模型聚合平台）
LLM_PROVIDER_DEEPSEEK = "deepseek"     # DeepSeek（占位）
LLM_PROVIDER_QWEN = "qwen"             # 阿里通义千问（占位）
LLM_PROVIDER_OPENAI = "openai"         # OpenAI（占位）
LLM_PROVIDER_ANTHROPIC = "anthropic"   # Anthropic Claude（占位）
LLM_PROVIDER_LOCAL = "local"           # 本地模型（Ollama）

SUPPORTED_LLM_PROVIDERS = [
    LLM_PROVIDER_ZHIPU,
    LLM_PROVIDER_SILICONFLOW,
    LLM_PROVIDER_DEEPSEEK,
    LLM_PROVIDER_QWEN,
    LLM_PROVIDER_OPENAI,
    LLM_PROVIDER_ANTHROPIC,
    LLM_PROVIDER_LOCAL,
]

# ============================================================
# 厂商基础配置（仅包含 UI 显示和厂商级别信息）
# 
# 模型列表、模型能力等从 ModelRegistry 动态获取
# 参见：shared/model_registry.py
# ============================================================
PROVIDER_DEFAULTS = {
    LLM_PROVIDER_ZHIPU: {
        "base_url": "https://open.bigmodel.cn/api/paas/v4",
        "default_model": "glm-4.6",
        "supports_web_search": True,  # 厂商专属联网搜索
        "requires_api_key": True,     # 需要 API Key
        "implemented": True,
    },
    LLM_PROVIDER_SILICONFLOW: {
        "base_url": "https://api.siliconflow.cn/v1",
        "default_model": "",  # 无默认模型，用户必须手动输入
        "supports_web_search": False,
        "requires_api_key": True,
        "model_input_mode": "text",  # 纯文本输入模式，不使用下拉选择
        "model_name_hint": "从模型广场复制模型名称，如 Qwen/Qwen2.5-72B-Instruct",
        "model_gallery_url": "https://cloud.siliconflow.cn/models",  # 模型广场链接
        "implemented": True,
    },
    LLM_PROVIDER_DEEPSEEK: {
        "base_url": "https://api.deepseek.com/v1",
        "default_model": "deepseek-chat",
        "supports_web_search": False,
        "requires_api_key": True,
        "implemented": False,
    },
    LLM_PROVIDER_QWEN: {
        "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
        "default_model": "qwen-max",
        "supports_web_search": False,
        "requires_api_key": True,
        "implemented": False,
    },
    LLM_PROVIDER_OPENAI: {
        "base_url": "https://api.openai.com/v1",
        "default_model": "gpt-4o",
        "supports_web_search": False,
        "requires_api_key": True,
        "implemented": False,
    },
    LLM_PROVIDER_ANTHROPIC: {
        "base_url": "https://api.anthropic.com/v1",
        "default_model": "claude-3-5-sonnet-20241022",
        "supports_web_search": False,
        "requires_api_key": True,
        "implemented": False,
    },
    LLM_PROVIDER_LOCAL: {
        "base_url": "http://localhost:11434",  # Ollama 默认地址
        "default_model": "qwen2.5:7b",
        "supports_web_search": False,
        "requires_api_key": False,    # 本地模型无需 API Key
        "is_local": True,             # 标识为本地厂商
        "implemented": True,
    },
}

# ============================================================
# 深度思考相关默认值
# ============================================================

DEFAULT_ENABLE_THINKING = True       # 默认开启深度思考（全局开关）
DEFAULT_THINKING_TIMEOUT = 300       # 深度思考模式下的超时秒数

# ============================================================
# 本地大模型相关常量
# ============================================================

DEFAULT_LOCAL_LLM_HOST = "http://localhost:11434"  # Ollama 默认服务地址
DEFAULT_LOCAL_LLM_MODEL = "qwen2.5:7b"             # 默认本地模型（推荐 Qwen2.5 7B）
LOCAL_LLM_CONNECT_TIMEOUT = 5                      # 本地服务连接超时秒数
LOCAL_LLM_REQUEST_TIMEOUT = 300                    # 本地模型请求超时秒数（本地推理较慢）
LOCAL_LLM_HEALTH_CHECK_INTERVAL = 30               # 健康检查间隔秒数

# ============================================================
# RAG 相关默认值
# ============================================================

DEFAULT_CHUNK_SIZE = 1500            # RAG 分块大小（tokens，利用 ModernBERT 8192 长上下文优势）
DEFAULT_CHUNK_OVERLAP = 0.1          # 分块重叠比例（10%）
DEFAULT_RAG_TOP_K = 5                # RAG 检索返回数量
DEFAULT_HYBRID_SEARCH = True         # 默认启用混合检索
DEFAULT_ENABLE_RERANKING = True      # 默认开启重排序

# ============================================================
# AI 模型相关常量
# ============================================================

DEFAULT_EMBEDDING_MODEL = "Alibaba-NLP/gte-modernbert-base"  # 默认嵌入模型（英文）
DEFAULT_RERANKER_MODEL = "mixedbread-ai/mxbai-rerank-base-v1"  # 默认重排序模型

# 内嵌模型目录
VENDOR_MODELS_DIR = "vendor/models/"
EMBEDDINGS_MODEL_DIR = "vendor/models/embeddings/"
RERANKERS_MODEL_DIR = "vendor/models/rerankers/"

# ============================================================
# 嵌入模型厂商相关常量
# ============================================================

EMBEDDING_PROVIDER_LOCAL = "local"     # 本地嵌入模型（默认，使用内嵌模型）
EMBEDDING_PROVIDER_ZHIPU = "zhipu"     # 智谱嵌入模型（Embedding-3）
EMBEDDING_PROVIDER_OPENAI = "openai"   # OpenAI 嵌入模型（占位）

SUPPORTED_EMBEDDING_PROVIDERS = ["local", "zhipu", "openai"]
DEFAULT_EMBEDDING_PROVIDER = "local"   # 默认使用本地嵌入模型

# 嵌入模型厂商配置字典
EMBEDDING_PROVIDER_DEFAULTS = {
    EMBEDDING_PROVIDER_LOCAL: {
        "display_name": "本地模型",
        "default_model": "gte-modernbert-base",
        "requires_api_key": False,
        "is_local": True,
        "implemented": True,
    },
    EMBEDDING_PROVIDER_ZHIPU: {
        "display_name": "智谱 AI",
        "base_url": "https://open.bigmodel.cn/api/paas/v4/embeddings",
        "default_model": "embedding-3",
        "requires_api_key": True,
        "is_local": False,
        "implemented": True,
        "dimensions": 2048,  # Embedding-3 输出维度
        "max_tokens": 8192,  # 单次请求最大 token 数
    },
    EMBEDDING_PROVIDER_OPENAI: {
        "display_name": "OpenAI",
        "base_url": "https://api.openai.com/v1/embeddings",
        "default_model": "text-embedding-3-small",
        "requires_api_key": True,
        "is_local": False,
        "implemented": False,
    },
}

# 嵌入模型相关默认值
DEFAULT_EMBEDDING_BATCH_SIZE = 32      # 批量嵌入请求大小
DEFAULT_EMBEDDING_TIMEOUT = 30         # 嵌入 API 请求超时秒数

# ============================================================
# 路径相关常量
# ============================================================

# 全局配置目录（用户主目录下）
GLOBAL_CONFIG_DIR = Path.home() / ".circuit_design_ai"

# 全局配置文件路径
GLOBAL_CONFIG_FILE = GLOBAL_CONFIG_DIR / "config.json"

# 凭证存储文件名
CREDENTIALS_FILE = "credentials.json"

# 全局日志目录
GLOBAL_LOG_DIR = GLOBAL_CONFIG_DIR / "logs"

# 工作文件夹隐藏目录名（项目内）
WORK_FOLDER_HIDDEN_DIR = ".circuit_ai"

# ============================================================
# 国际化相关常量
# ============================================================

DEFAULT_LANGUAGE = "en_US"           # 默认界面语言
SUPPORTED_LANGUAGES = ["en_US", "zh_CN"]  # 支持的语言列表

# ============================================================
# 功能开关默认值
# ============================================================

# 联网搜索配置
# 注意：厂商专属联网搜索与通用联网搜索互斥，只能启用其一
# 原因：避免搜索结果冲突和重复计费

# 厂商专属联网搜索（如智谱内置搜索）
DEFAULT_ENABLE_PROVIDER_WEB_SEARCH = False

# 通用联网搜索（Google/Bing，与厂商无关）
DEFAULT_ENABLE_GENERAL_WEB_SEARCH = False
DEFAULT_GENERAL_WEB_SEARCH_PROVIDER = "google"

# ============================================================
# 联网搜索提供商常量
# ============================================================

# 通用联网搜索（与 LLM 厂商无关）
WEB_SEARCH_GOOGLE = "google"            # Google Custom Search（需 API Key + cx）
WEB_SEARCH_BING = "bing"                # Bing Web Search（需 API Key）
SUPPORTED_GENERAL_WEB_SEARCH = [WEB_SEARCH_GOOGLE, WEB_SEARCH_BING]

# ============================================================
# 配置字段名常量（避免字符串硬编码）
# ============================================================

# 通用配置
CONFIG_LANGUAGE = "language"

# LLM 厂商配置
CONFIG_LLM_PROVIDER = "llm_provider"
CONFIG_LLM_MODEL = "llm_model"
CONFIG_LLM_BASE_URL = "llm_base_url"
CONFIG_LLM_TIMEOUT = "llm_timeout"
CONFIG_LLM_STREAMING = "llm_streaming"

# 旧版配置字段（保留兼容）
CONFIG_API_KEY = "api_key"
CONFIG_BASE_URL = "base_url"
CONFIG_MODEL = "model"
CONFIG_TIMEOUT = "timeout"
CONFIG_STREAMING = "streaming"

# 硅基流动配置
CONFIG_SILICONFLOW_MODEL = "siliconflow_model"
CONFIG_SILICONFLOW_BASE_URL = "siliconflow_base_url"

# 本地大模型配置
CONFIG_LOCAL_LLM_HOST = "local_llm_host"
CONFIG_LOCAL_LLM_MODEL = "local_llm_model"

# 深度思考配置
CONFIG_ENABLE_THINKING = "enable_thinking"
CONFIG_THINKING_TIMEOUT = "thinking_timeout"

# 厂商专属联网搜索配置
CONFIG_ENABLE_PROVIDER_WEB_SEARCH = "enable_provider_web_search"

# 通用联网搜索配置
CONFIG_ENABLE_GENERAL_WEB_SEARCH = "enable_general_web_search"
CONFIG_GENERAL_WEB_SEARCH_PROVIDER = "general_web_search_provider"
CONFIG_GENERAL_WEB_SEARCH_API_KEY = "general_web_search_api_key"
CONFIG_GOOGLE_SEARCH_CX = "google_search_cx"  # Google 自定义搜索引擎 ID

# 嵌入模型配置
CONFIG_EMBEDDING_PROVIDER = "embedding_provider"
CONFIG_EMBEDDING_MODEL = "embedding_model"
CONFIG_EMBEDDING_BASE_URL = "embedding_base_url"
CONFIG_EMBEDDING_TIMEOUT = "embedding_timeout"
CONFIG_EMBEDDING_BATCH_SIZE = "embedding_batch_size"

# ============================================================
# 默认配置模板
# ============================================================

DEFAULT_CONFIG = {
    # 通用配置
    CONFIG_LANGUAGE: DEFAULT_LANGUAGE,
    
    # LLM 厂商配置
    CONFIG_LLM_PROVIDER: DEFAULT_LLM_PROVIDER,
    CONFIG_LLM_MODEL: DEFAULT_MODEL,
    CONFIG_LLM_BASE_URL: "",  # 空则使用厂商默认
    CONFIG_LLM_TIMEOUT: DEFAULT_TIMEOUT,
    CONFIG_LLM_STREAMING: DEFAULT_STREAMING,
    
    # 旧版配置字段（保留兼容）
    CONFIG_API_KEY: "",
    CONFIG_BASE_URL: DEFAULT_BASE_URL,
    CONFIG_MODEL: DEFAULT_MODEL,
    CONFIG_TIMEOUT: DEFAULT_TIMEOUT,
    CONFIG_STREAMING: DEFAULT_STREAMING,
    
    # 硅基流动配置
    CONFIG_SILICONFLOW_MODEL: "",  # 用户手动输入
    CONFIG_SILICONFLOW_BASE_URL: "https://api.siliconflow.cn/v1",
    
    # 本地大模型配置
    CONFIG_LOCAL_LLM_HOST: DEFAULT_LOCAL_LLM_HOST,
    CONFIG_LOCAL_LLM_MODEL: DEFAULT_LOCAL_LLM_MODEL,
    
    # 深度思考配置
    CONFIG_ENABLE_THINKING: DEFAULT_ENABLE_THINKING,
    CONFIG_THINKING_TIMEOUT: DEFAULT_THINKING_TIMEOUT,
    
    # 厂商专属联网搜索配置
    CONFIG_ENABLE_PROVIDER_WEB_SEARCH: DEFAULT_ENABLE_PROVIDER_WEB_SEARCH,
    
    # 通用联网搜索配置
    CONFIG_ENABLE_GENERAL_WEB_SEARCH: DEFAULT_ENABLE_GENERAL_WEB_SEARCH,
    CONFIG_GENERAL_WEB_SEARCH_PROVIDER: DEFAULT_GENERAL_WEB_SEARCH_PROVIDER,
    CONFIG_GENERAL_WEB_SEARCH_API_KEY: "",
    CONFIG_GOOGLE_SEARCH_CX: "",
    
    # 嵌入模型配置
    CONFIG_EMBEDDING_PROVIDER: DEFAULT_EMBEDDING_PROVIDER,
    CONFIG_EMBEDDING_MODEL: "",  # 空则使用厂商默认
    CONFIG_EMBEDDING_BASE_URL: "",  # 空则使用厂商默认
    CONFIG_EMBEDDING_TIMEOUT: DEFAULT_EMBEDDING_TIMEOUT,
    CONFIG_EMBEDDING_BATCH_SIZE: DEFAULT_EMBEDDING_BATCH_SIZE,
}

# ============================================================
# 加密相关常量
# ============================================================

# 需要加密存储的配置字段
ENCRYPTED_FIELDS = [CONFIG_API_KEY, CONFIG_GENERAL_WEB_SEARCH_API_KEY]

# 加密盐值（用于密钥派生）
ENCRYPTION_SALT = b"circuit_design_ai_v1"

# ============================================================
# 凭证类型常量
# ============================================================

CREDENTIAL_TYPE_LLM = "llm"           # LLM 厂商凭证类型
CREDENTIAL_TYPE_SEARCH = "search"     # 搜索厂商凭证类型
CREDENTIAL_TYPE_EMBEDDING = "embedding"  # 嵌入模型厂商凭证类型
CREDENTIAL_TYPE_COMPONENT = "component"  # 元器件商城凭证类型（阶段十）
