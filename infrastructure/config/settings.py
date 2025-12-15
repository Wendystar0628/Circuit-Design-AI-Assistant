"""
默认设置常量定义

职责：定义系统级默认配置值，作为配置缺失时的回退
设计原则：纯常量定义，无业务逻辑，便于全局引用
"""

from pathlib import Path

# ============================================================
# 工作流相关默认值
# ============================================================

DEFAULT_MAX_ITERATIONS = 20          # 最大迭代次数
DEFAULT_STAGNATION_THRESHOLD = 3     # 停滞判断阈值（连续N次无改进则停止）
DEFAULT_CONTEXT_LIMIT_RATIO = 0.8    # 上下文占用触发总结的阈值（80%）

# ============================================================
# LLM API 相关默认值
# ============================================================

DEFAULT_TIMEOUT = 60                 # LLM API 普通请求超时秒数
DEFAULT_STREAMING = True             # 默认启用流式输出
DEFAULT_LLM_PROVIDER = ""            # 默认 LLM 提供者（空表示未配置）
DEFAULT_MODEL = "glm-4.6"            # 默认模型名称
DEFAULT_BASE_URL = "https://open.bigmodel.cn/api/paas/v4"  # 智谱 API 默认端点

# ============================================================
# 深度思考相关默认值
# ============================================================

DEFAULT_ENABLE_THINKING = True       # 默认开启深度思考
DEFAULT_THINKING_MAX_TOKENS = 65536  # 深度思考模式下的 max_tokens
DEFAULT_THINKING_TEMPERATURE = 1.0   # 深度思考模式下的 temperature（固定值）
DEFAULT_THINKING_TIMEOUT = 300       # 深度思考模式下的超时秒数

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
# 路径相关常量
# ============================================================

# 全局配置目录（用户主目录下）
GLOBAL_CONFIG_DIR = Path.home() / ".circuit_design_ai"

# 全局配置文件路径
GLOBAL_CONFIG_FILE = GLOBAL_CONFIG_DIR / "config.json"

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

DEFAULT_ENABLE_WEB_SEARCH = False    # 联网搜索开关（默认关闭）
DEFAULT_WEB_SEARCH_PROVIDER = "zhipu_web_search"  # 搜索提供者（zhipu_web_search/google/bing）

# ============================================================
# 联网搜索提供商常量
# ============================================================

WEB_SEARCH_ZHIPU = "zhipu_web_search"  # 智谱联网搜索（仅限智谱模型，无需额外 API Key）
WEB_SEARCH_GOOGLE = "google"            # Google Custom Search（通用，需科学上网）
WEB_SEARCH_BING = "bing"                # Bing Web Search（通用，需科学上网）
SUPPORTED_WEB_SEARCH_PROVIDERS = [WEB_SEARCH_ZHIPU, WEB_SEARCH_GOOGLE, WEB_SEARCH_BING]

# ============================================================
# 配置字段名常量（避免字符串硬编码）
# ============================================================

CONFIG_LANGUAGE = "language"
CONFIG_LLM_PROVIDER = "llm_provider"
CONFIG_API_KEY = "api_key"
CONFIG_BASE_URL = "base_url"
CONFIG_MODEL = "model"
CONFIG_TIMEOUT = "timeout"
CONFIG_STREAMING = "streaming"
CONFIG_ENABLE_THINKING = "enable_thinking"
CONFIG_THINKING_MAX_TOKENS = "thinking_max_tokens"
CONFIG_THINKING_TEMPERATURE = "thinking_temperature"
CONFIG_THINKING_TIMEOUT = "thinking_timeout"
CONFIG_ENABLE_WEB_SEARCH = "enable_web_search"
CONFIG_WEB_SEARCH_PROVIDER = "web_search_provider"
CONFIG_WEB_SEARCH_API_KEY = "web_search_api_key"
CONFIG_GOOGLE_SEARCH_CX = "google_search_cx"  # Google 自定义搜索引擎 ID

# ============================================================
# 默认配置模板
# ============================================================

DEFAULT_CONFIG = {
    CONFIG_LANGUAGE: DEFAULT_LANGUAGE,
    CONFIG_LLM_PROVIDER: DEFAULT_LLM_PROVIDER,
    CONFIG_API_KEY: "",
    CONFIG_BASE_URL: DEFAULT_BASE_URL,
    CONFIG_MODEL: DEFAULT_MODEL,
    CONFIG_TIMEOUT: DEFAULT_TIMEOUT,
    CONFIG_STREAMING: DEFAULT_STREAMING,
    CONFIG_ENABLE_THINKING: DEFAULT_ENABLE_THINKING,
    CONFIG_THINKING_MAX_TOKENS: DEFAULT_THINKING_MAX_TOKENS,
    CONFIG_THINKING_TEMPERATURE: DEFAULT_THINKING_TEMPERATURE,
    CONFIG_THINKING_TIMEOUT: DEFAULT_THINKING_TIMEOUT,
    CONFIG_ENABLE_WEB_SEARCH: DEFAULT_ENABLE_WEB_SEARCH,
    CONFIG_WEB_SEARCH_PROVIDER: DEFAULT_WEB_SEARCH_PROVIDER,
    CONFIG_WEB_SEARCH_API_KEY: "",
    CONFIG_GOOGLE_SEARCH_CX: "",  # Google 自定义搜索引擎 ID
}

# ============================================================
# 加密相关常量
# ============================================================

# 需要加密存储的配置字段
ENCRYPTED_FIELDS = [CONFIG_API_KEY, CONFIG_WEB_SEARCH_API_KEY]

# 加密盐值（用于密钥派生）
ENCRYPTION_SALT = b"circuit_design_ai_v1"
