"""
AI 模型运行时路径配置模块

职责：
- 检测运行环境（开发环境 vs PyInstaller 打包环境）
- 配置 AI 模型路径（嵌入模型、重排序模型）
- 设置 HuggingFace 缓存环境变量
- 提供模型路径获取接口

调用时机：
- 在 main.py 的 Phase 0 阶段调用
- 在 ngspice 配置之后、Logger 初始化之前

使用示例：
    # main.py 中
    from infrastructure.utils.model_config import configure_models
    configure_models()
    
    # embeddings.py 中
    from infrastructure.utils.model_config import get_embedding_model_path
    model_path = get_embedding_model_path()
"""

import os
import sys
from pathlib import Path
from typing import Optional
from enum import Enum


# ============================================================
# 模型类型枚举
# ============================================================

class ModelType(Enum):
    """AI 模型类型"""
    EMBEDDING = "embedding"
    RERANKER = "reranker"


# ============================================================
# 模型配置常量
# ============================================================

# 相对于项目根目录的 vendor 路径
VENDOR_MODELS_DIR = "vendor/models"
EMBEDDINGS_SUBDIR = "embeddings"
RERANKERS_SUBDIR = "rerankers"

# 模型目录名（与 HuggingFace 仓库名对应）
EMBEDDING_MODEL_DIR = "gte-modernbert-base"
RERANKER_MODEL_DIR = "mxbai-rerank-base-v1"

# HuggingFace 模型 ID（用于回退到在线下载）
EMBEDDING_MODEL_ID = "Alibaba-NLP/gte-modernbert-base"
RERANKER_MODEL_ID = "mixedbread-ai/mxbai-rerank-base-v1"

# 模型必需文件（用于验证完整性）
REQUIRED_FILES = {
    ModelType.EMBEDDING: ["config.json", "model.safetensors", "tokenizer.json"],
    ModelType.RERANKER: ["config.json", "model.safetensors", "tokenizer.json"],
}


# ============================================================
# 模块级状态变量
# ============================================================

_models_configured: bool = False           # 是否已执行配置
_embedding_model_path: Optional[Path] = None   # 嵌入模型路径
_reranker_model_path: Optional[Path] = None    # 重排序模型路径
_configuration_errors: dict = {}           # 配置错误信息


# ============================================================
# 内部辅助函数
# ============================================================

def _is_packaged() -> bool:
    """
    检测是否为 PyInstaller 打包环境
    
    Returns:
        bool: True 表示打包环境，False 表示开发环境
    """
    return getattr(sys, '_MEIPASS', None) is not None


def _get_base_path() -> Path:
    """
    获取基础路径（项目根目录或打包临时目录）
    
    开发环境：返回 circuit_design_ai/ 目录
    打包环境：返回 sys._MEIPASS 临时目录
    
    Returns:
        Path: 基础路径
    """
    if _is_packaged():
        return Path(sys._MEIPASS)
    else:
        # 开发环境：从当前文件向上三级到达 circuit_design_ai/
        # model_config.py -> utils/ -> infrastructure/ -> circuit_design_ai/
        return Path(__file__).parent.parent.parent


def _find_local_model_path(model_type: ModelType) -> Optional[Path]:
    """
    查找本地模型路径
    
    Args:
        model_type: 模型类型
        
    Returns:
        Path: 模型目录路径，未找到返回 None
    """
    base_path = _get_base_path()
    
    if model_type == ModelType.EMBEDDING:
        model_path = base_path / VENDOR_MODELS_DIR / EMBEDDINGS_SUBDIR / EMBEDDING_MODEL_DIR
    elif model_type == ModelType.RERANKER:
        model_path = base_path / VENDOR_MODELS_DIR / RERANKERS_SUBDIR / RERANKER_MODEL_DIR
    else:
        return None
    
    if model_path.exists() and model_path.is_dir():
        return model_path
    
    return None


def _validate_model_path(model_path: Path, model_type: ModelType) -> bool:
    """
    验证模型路径的完整性
    
    检查必要的文件是否存在
    
    Args:
        model_path: 模型目录路径
        model_type: 模型类型
        
    Returns:
        bool: 路径是否有效
    """
    if not model_path or not model_path.exists():
        return False
    
    required_files = REQUIRED_FILES.get(model_type, [])
    for filename in required_files:
        if not (model_path / filename).exists():
            return False
    
    return True


def _get_huggingface_cache_path(model_type: ModelType) -> Optional[Path]:
    """
    获取 HuggingFace 缓存中的模型路径
    
    Args:
        model_type: 模型类型
        
    Returns:
        Path: 缓存中的模型路径，未找到返回 None
    """
    # HuggingFace 默认缓存目录
    hf_home = os.environ.get("HF_HOME", Path.home() / ".cache" / "huggingface")
    hf_cache = Path(hf_home) / "hub"
    
    if model_type == ModelType.EMBEDDING:
        model_id = EMBEDDING_MODEL_ID
    elif model_type == ModelType.RERANKER:
        model_id = RERANKER_MODEL_ID
    else:
        return None
    
    # HuggingFace 缓存目录格式: models--{org}--{model_name}
    cache_dir_name = f"models--{model_id.replace('/', '--')}"
    cache_path = hf_cache / cache_dir_name
    
    if cache_path.exists():
        # 查找 snapshots 目录下的最新版本
        snapshots_dir = cache_path / "snapshots"
        if snapshots_dir.exists():
            # 获取最新的 snapshot（按修改时间排序）
            snapshots = list(snapshots_dir.iterdir())
            if snapshots:
                latest_snapshot = max(snapshots, key=lambda p: p.stat().st_mtime)
                return latest_snapshot
    
    return None


def _setup_environment() -> None:
    """
    设置 HuggingFace 相关的环境变量
    
    配置离线模式和缓存路径，优先使用本地模型
    """
    base_path = _get_base_path()
    vendor_models_path = base_path / VENDOR_MODELS_DIR
    
    # 如果本地模型目录存在，设置为优先缓存路径
    if vendor_models_path.exists():
        # 设置 TRANSFORMERS_OFFLINE=1 可以强制离线模式
        # 但我们不强制，允许回退到在线下载
        pass
    
    # 禁用 symlinks（Windows 兼容性）
    os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS_WARNING", "1")


# ============================================================
# 公开接口
# ============================================================

def configure_models() -> bool:
    """
    配置 AI 模型路径
    
    此函数执行以下步骤：
    1. 检测运行环境
    2. 查找本地嵌入模型
    3. 查找本地重排序模型
    4. 设置环境变量
    5. 如果本地模型不可用，记录回退信息
    
    Returns:
        bool: 配置是否成功（至少有一个模型可用）
    """
    global _models_configured, _embedding_model_path, _reranker_model_path, _configuration_errors
    
    # 避免重复配置
    if _models_configured:
        return _embedding_model_path is not None or _reranker_model_path is not None
    
    _models_configured = True
    _configuration_errors = {}
    
    # 设置环境变量
    _setup_environment()
    
    # 配置嵌入模型
    embedding_path = _find_local_model_path(ModelType.EMBEDDING)
    if embedding_path and _validate_model_path(embedding_path, ModelType.EMBEDDING):
        _embedding_model_path = embedding_path
    else:
        # 尝试 HuggingFace 缓存
        cache_path = _get_huggingface_cache_path(ModelType.EMBEDDING)
        if cache_path and _validate_model_path(cache_path, ModelType.EMBEDDING):
            _embedding_model_path = cache_path
        else:
            _configuration_errors[ModelType.EMBEDDING] = (
                f"嵌入模型未找到，将在首次使用时从 HuggingFace 下载: {EMBEDDING_MODEL_ID}"
            )
    
    # 配置重排序模型
    reranker_path = _find_local_model_path(ModelType.RERANKER)
    if reranker_path and _validate_model_path(reranker_path, ModelType.RERANKER):
        _reranker_model_path = reranker_path
    else:
        # 尝试 HuggingFace 缓存
        cache_path = _get_huggingface_cache_path(ModelType.RERANKER)
        if cache_path and _validate_model_path(cache_path, ModelType.RERANKER):
            _reranker_model_path = cache_path
        else:
            _configuration_errors[ModelType.RERANKER] = (
                f"重排序模型未找到，将在首次使用时从 HuggingFace 下载: {RERANKER_MODEL_ID}"
            )
    
    # 至少有一个模型可用即视为成功
    return _embedding_model_path is not None or _reranker_model_path is not None


def get_embedding_model_path() -> Optional[str]:
    """
    获取嵌入模型本地路径
    
    如果本地模型可用，返回本地路径；
    否则返回 HuggingFace 模型 ID（将触发在线下载）
    
    Returns:
        str: 模型路径或模型 ID
    """
    if _embedding_model_path:
        return str(_embedding_model_path)
    return EMBEDDING_MODEL_ID


def get_reranker_model_path() -> Optional[str]:
    """
    获取重排序模型本地路径
    
    如果本地模型可用，返回本地路径；
    否则返回 HuggingFace 模型 ID（将触发在线下载）
    
    Returns:
        str: 模型路径或模型 ID
    """
    if _reranker_model_path:
        return str(_reranker_model_path)
    return RERANKER_MODEL_ID


def is_model_available(model_type: ModelType) -> bool:
    """
    检查指定模型是否可用（本地已下载）
    
    Args:
        model_type: 模型类型
        
    Returns:
        bool: 模型是否本地可用
    """
    if model_type == ModelType.EMBEDDING:
        return _embedding_model_path is not None
    elif model_type == ModelType.RERANKER:
        return _reranker_model_path is not None
    return False


def is_embedding_available() -> bool:
    """
    检查嵌入模型是否本地可用
    
    Returns:
        bool: 嵌入模型是否本地可用
    """
    return is_model_available(ModelType.EMBEDDING)


def is_reranker_available() -> bool:
    """
    检查重排序模型是否本地可用
    
    Returns:
        bool: 重排序模型是否本地可用
    """
    return is_model_available(ModelType.RERANKER)


def get_configuration_errors() -> dict:
    """
    获取配置错误/警告信息
    
    Returns:
        dict: 模型类型到错误信息的映射
    """
    return _configuration_errors.copy()


def get_model_info() -> dict:
    """
    获取模型配置的详细信息
    
    用于调试和诊断
    
    Returns:
        dict: 包含配置状态的字典
    """
    return {
        "configured": _models_configured,
        "embedding": {
            "available": _embedding_model_path is not None,
            "path": str(_embedding_model_path) if _embedding_model_path else None,
            "model_id": EMBEDDING_MODEL_ID,
            "error": _configuration_errors.get(ModelType.EMBEDDING),
        },
        "reranker": {
            "available": _reranker_model_path is not None,
            "path": str(_reranker_model_path) if _reranker_model_path else None,
            "model_id": RERANKER_MODEL_ID,
            "error": _configuration_errors.get(ModelType.RERANKER),
        },
        "packaged": _is_packaged(),
        "base_path": str(_get_base_path()),
    }


# ============================================================
# 模块导出
# ============================================================

__all__ = [
    "ModelType",
    "configure_models",
    "get_embedding_model_path",
    "get_reranker_model_path",
    "is_model_available",
    "is_embedding_available",
    "is_reranker_available",
    "get_configuration_errors",
    "get_model_info",
    # 常量导出
    "EMBEDDING_MODEL_ID",
    "RERANKER_MODEL_ID",
]
