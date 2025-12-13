# Utilities
"""
工具函数模块

包含：
- ngspice_config.py: ngspice 运行时路径配置
- model_config.py: AI 模型运行时路径配置
- logger.py: 统一日志管理器
- json_utils.py: JSON序列化/反序列化
- file_utils.py: 跨平台文件操作（阶段二）
- token_counter.py: 多模型Token计数（阶段三）
"""

from .ngspice_config import (
    configure_ngspice,
    get_ngspice_path,
    is_ngspice_available,
    get_configuration_error,
    get_ngspice_info,
)

from .model_config import (
    configure_models,
    get_embedding_model_path,
    get_reranker_model_path,
    is_embedding_available,
    is_reranker_available,
    get_model_info,
)

from .logger import (
    setup_logger,
    get_logger,
    sanitize_message,
    truncate_content,
    log_performance,
    log_api_call,
    log_file_operation,
    log_simulation,
    cleanup_old_logs,
)

from .json_utils import (
    safe_json_loads,
    safe_json_dumps,
    safe_json_load_file,
    safe_json_dump_file,
    CustomJSONEncoder,
    merge_json_objects,
    extract_json_from_text,
)

__all__ = [
    # ngspice 配置
    "configure_ngspice",
    "get_ngspice_path",
    "is_ngspice_available",
    "get_configuration_error",
    "get_ngspice_info",
    # AI 模型配置
    "configure_models",
    "get_embedding_model_path",
    "get_reranker_model_path",
    "is_embedding_available",
    "is_reranker_available",
    "get_model_info",
    # 日志
    "setup_logger",
    "get_logger",
    "sanitize_message",
    "truncate_content",
    "log_performance",
    "log_api_call",
    "log_file_operation",
    "log_simulation",
    "cleanup_old_logs",
    # JSON
    "safe_json_loads",
    "safe_json_dumps",
    "safe_json_load_file",
    "safe_json_dump_file",
    "CustomJSONEncoder",
    "merge_json_objects",
    "extract_json_from_text",
]
