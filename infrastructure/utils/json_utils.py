"""
JSON 序列化/反序列化工具

职责：提供增强的 JSON 处理功能，支持特殊类型序列化

使用方式：
    from infrastructure.utils.json_utils import safe_json_loads, safe_json_dumps
    
    # 安全解析 JSON
    data = safe_json_loads('{"key": "value"}', default={})
    
    # 安全序列化（支持特殊类型）
    from datetime import datetime
    from pathlib import Path
    
    data = {
        "time": datetime.now(),
        "path": Path("/some/path"),
        "array": numpy.array([1, 2, 3])
    }
    json_str = safe_json_dumps(data)
"""

import json
import dataclasses
from datetime import datetime, date
from pathlib import Path, PurePath
from typing import Any, Optional, Type

# 尝试导入 numpy（可选依赖）
try:
    import numpy as np
    HAS_NUMPY = True
except ImportError:
    HAS_NUMPY = False


# ============================================================
# 自定义 JSON 编码器
# ============================================================

class CustomJSONEncoder(json.JSONEncoder):
    """
    自定义 JSON 编码器
    
    支持以下类型的序列化：
    - datetime/date → ISO 格式字符串
    - Path/PurePath → 字符串
    - numpy.ndarray → 列表
    - dataclass → 字典
    - set/frozenset → 列表
    - bytes → Base64 字符串
    """
    
    def default(self, obj: Any) -> Any:
        """
        处理无法直接序列化的对象
        
        Args:
            obj: 待序列化的对象
            
        Returns:
            可序列化的值
        """
        # datetime/date → ISO 格式字符串
        if isinstance(obj, datetime):
            return obj.isoformat()
        
        if isinstance(obj, date):
            return obj.isoformat()
        
        # Path → 字符串
        if isinstance(obj, (Path, PurePath)):
            return str(obj)
        
        # numpy.ndarray → 列表
        if HAS_NUMPY and isinstance(obj, np.ndarray):
            return obj.tolist()
        
        # numpy 标量类型 → Python 原生类型
        if HAS_NUMPY:
            if isinstance(obj, (np.integer, np.int64, np.int32)):
                return int(obj)
            if isinstance(obj, (np.floating, np.float64, np.float32)):
                return float(obj)
            if isinstance(obj, np.bool_):
                return bool(obj)
        
        # dataclass → 字典
        if dataclasses.is_dataclass(obj) and not isinstance(obj, type):
            return dataclasses.asdict(obj)
        
        # set/frozenset → 列表
        if isinstance(obj, (set, frozenset)):
            return list(obj)
        
        # bytes → Base64 字符串
        if isinstance(obj, bytes):
            import base64
            return base64.b64encode(obj).decode('ascii')
        
        # 其他类型尝试转换为字符串
        try:
            return str(obj)
        except Exception:
            return super().default(obj)


# ============================================================
# 核心功能
# ============================================================

def safe_json_loads(
    text: str,
    default: Any = None,
    encoding: str = 'utf-8'
) -> Any:
    """
    安全解析 JSON 字符串
    
    解析失败时返回默认值而非抛出异常
    
    Args:
        text: JSON 字符串
        default: 解析失败时的默认值
        encoding: 字符编码（如果 text 是 bytes）
        
    Returns:
        解析后的对象，失败时返回 default
    """
    if text is None:
        return default
    
    # 处理 bytes 输入
    if isinstance(text, bytes):
        try:
            text = text.decode(encoding)
        except UnicodeDecodeError:
            _log_warning(f"JSON 解码失败: 无法使用 {encoding} 解码")
            return default
    
    # 处理空字符串
    if not text or not text.strip():
        return default
    
    try:
        return json.loads(text)
    except json.JSONDecodeError as e:
        _log_warning(f"JSON 解析失败: {e}")
        return default
    except Exception as e:
        _log_warning(f"JSON 解析异常: {e}")
        return default


def safe_json_dumps(
    data: Any,
    indent: int = 2,
    ensure_ascii: bool = False,
    sort_keys: bool = False,
    default_handler: Optional[callable] = None
) -> str:
    """
    安全序列化为 JSON 字符串
    
    使用 CustomJSONEncoder 处理特殊类型
    
    Args:
        data: 待序列化的数据
        indent: 缩进空格数，None 表示紧凑格式
        ensure_ascii: 是否转义非 ASCII 字符
        sort_keys: 是否按键排序
        default_handler: 自定义默认处理函数
        
    Returns:
        JSON 字符串，失败时返回空字符串
    """
    try:
        encoder_cls = CustomJSONEncoder
        
        # 如果提供了自定义处理函数，创建新的编码器类
        if default_handler is not None:
            class ExtendedEncoder(CustomJSONEncoder):
                def default(self, obj):
                    try:
                        return default_handler(obj)
                    except (TypeError, ValueError):
                        return super().default(obj)
            encoder_cls = ExtendedEncoder
        
        return json.dumps(
            data,
            cls=encoder_cls,
            indent=indent,
            ensure_ascii=ensure_ascii,
            sort_keys=sort_keys
        )
    except Exception as e:
        _log_warning(f"JSON 序列化失败: {e}")
        return ""


def safe_json_load_file(
    file_path: Path,
    default: Any = None,
    encoding: str = 'utf-8'
) -> Any:
    """
    安全从文件加载 JSON
    
    Args:
        file_path: 文件路径
        default: 加载失败时的默认值
        encoding: 文件编码
        
    Returns:
        解析后的对象，失败时返回 default
    """
    try:
        if not file_path.exists():
            return default
        
        with open(file_path, 'r', encoding=encoding) as f:
            return json.load(f)
    except json.JSONDecodeError as e:
        _log_warning(f"JSON 文件解析失败 {file_path}: {e}")
        return default
    except Exception as e:
        _log_warning(f"JSON 文件读取失败 {file_path}: {e}")
        return default


def safe_json_dump_file(
    data: Any,
    file_path: Path,
    indent: int = 2,
    ensure_ascii: bool = False,
    encoding: str = 'utf-8'
) -> bool:
    """
    安全将数据写入 JSON 文件
    
    Args:
        data: 待写入的数据
        file_path: 文件路径
        indent: 缩进空格数
        ensure_ascii: 是否转义非 ASCII 字符
        encoding: 文件编码
        
    Returns:
        bool: 写入是否成功
    """
    try:
        # 确保父目录存在
        file_path.parent.mkdir(parents=True, exist_ok=True)
        
        with open(file_path, 'w', encoding=encoding) as f:
            json.dump(
                data,
                f,
                cls=CustomJSONEncoder,
                indent=indent,
                ensure_ascii=ensure_ascii
            )
        return True
    except Exception as e:
        _log_warning(f"JSON 文件写入失败 {file_path}: {e}")
        return False


# ============================================================
# 辅助函数
# ============================================================

def merge_json_objects(base: dict, override: dict, deep: bool = True) -> dict:
    """
    合并两个 JSON 对象
    
    override 中的值会覆盖 base 中的同名键
    
    Args:
        base: 基础对象
        override: 覆盖对象
        deep: 是否深度合并嵌套字典
        
    Returns:
        合并后的新字典
    """
    result = base.copy()
    
    for key, value in override.items():
        if deep and key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = merge_json_objects(result[key], value, deep=True)
        else:
            result[key] = value
    
    return result


def extract_json_from_text(text: str) -> Optional[dict]:
    """
    从文本中提取 JSON 对象
    
    用于从 LLM 响应中提取 JSON 代码块
    
    Args:
        text: 包含 JSON 的文本
        
    Returns:
        解析后的 JSON 对象，未找到或解析失败返回 None
    """
    import re
    
    # 尝试直接解析
    result = safe_json_loads(text.strip())
    if result is not None:
        return result
    
    # 尝试从 markdown 代码块中提取
    patterns = [
        r'```json\s*([\s\S]*?)\s*```',  # ```json ... ```
        r'```\s*([\s\S]*?)\s*```',       # ``` ... ```
        r'\{[\s\S]*\}',                   # { ... }
    ]
    
    for pattern in patterns:
        matches = re.findall(pattern, text)
        for match in matches:
            result = safe_json_loads(match.strip())
            if result is not None and isinstance(result, dict):
                return result
    
    return None


# ============================================================
# 内部日志函数（避免循环依赖）
# ============================================================

def _log_warning(message: str) -> None:
    """记录警告日志（避免循环依赖）"""
    try:
        from infrastructure.utils.logger import get_logger
        get_logger("json_utils").warning(message)
    except Exception:
        print(f"[WARNING] json_utils: {message}")


# ============================================================
# 模块导出
# ============================================================

__all__ = [
    # 核心功能
    "safe_json_loads",
    "safe_json_dumps",
    "safe_json_load_file",
    "safe_json_dump_file",
    # 自定义编码器
    "CustomJSONEncoder",
    # 辅助函数
    "merge_json_objects",
    "extract_json_from_text",
]
