# File Utils - Cross-Platform File Operations
"""
跨平台文件操作工具

职责：
- 提供跨平台（Windows/macOS/Linux）的文件路径处理工具
- 文件类型判断
- 安全文件名生成

使用示例：
    from infrastructure.utils.file_utils import (
        normalize_path,
        is_spice_file,
        get_safe_filename
    )
    
    # 规范化路径
    path = normalize_path("~/projects/../test.cir")
    
    # 判断文件类型
    if is_spice_file("circuit.cir"):
        print("这是SPICE文件")
    
    # 生成安全文件名
    safe_name = get_safe_filename("test<>file.txt")
"""

import os
import re
import unicodedata
from pathlib import Path
from typing import Optional, Union


# ============================================================
# SPICE 文件扩展名
# ============================================================

# 可仿真的 SPICE 文件扩展名
SPICE_EXTENSIONS = {'.cir', '.sp', '.spice', '.net', '.ckt'}

# SPICE 库文件扩展名（不可直接仿真）
SPICE_LIB_EXTENSIONS = {'.lib', '.mod', '.sub'}

# 所有 SPICE 相关文件扩展名
ALL_SPICE_EXTENSIONS = SPICE_EXTENSIONS | SPICE_LIB_EXTENSIONS

# ============================================================
# Python 文件扩展名
# ============================================================

PYTHON_EXTENSIONS = {'.py'}

# ============================================================
# 图片文件扩展名
# ============================================================

IMAGE_EXTENSIONS = {'.png', '.jpg', '.jpeg', '.gif', '.bmp', '.webp', '.svg', '.ico'}

# ============================================================
# 文档文件扩展名
# ============================================================

MARKDOWN_EXTENSIONS = {'.md', '.markdown'}
WORD_EXTENSIONS = {'.docx'}  # 仅支持 .docx，不支持旧版 .doc
PDF_EXTENSIONS = {'.pdf'}
DOCUMENT_EXTENSIONS = MARKDOWN_EXTENSIONS | WORD_EXTENSIONS | PDF_EXTENSIONS

# ============================================================
# 文本文件扩展名
# ============================================================

TEXT_EXTENSIONS = {
    '.txt', '.md', '.json', '.yaml', '.yml', '.xml', '.html', '.css', '.js',
    '.py', '.c', '.cpp', '.h', '.hpp', '.java', '.rs', '.go', '.ts',
    '.cir', '.sp', '.spice', '.net', '.lib', '.mod', '.sub',
    '.log', '.csv', '.ini', '.cfg', '.conf', '.toml'
}

# ============================================================
# Windows 非法文件名字符
# ============================================================

WINDOWS_ILLEGAL_CHARS = r'[<>:"/\\|?*]'
WINDOWS_RESERVED_NAMES = {
    'CON', 'PRN', 'AUX', 'NUL',
    'COM1', 'COM2', 'COM3', 'COM4', 'COM5', 'COM6', 'COM7', 'COM8', 'COM9',
    'LPT1', 'LPT2', 'LPT3', 'LPT4', 'LPT5', 'LPT6', 'LPT7', 'LPT8', 'LPT9'
}


# ============================================================
# 路径处理函数
# ============================================================

def normalize_path(path: Union[str, Path]) -> Path:
    """
    规范化路径
    
    处理：
    - ~ 展开为用户目录
    - 相对路径转绝对路径
    - 路径分隔符统一
    - 解析 .. 和 .
    
    Args:
        path: 原始路径
        
    Returns:
        Path: 规范化后的路径
    """
    path_str = str(path)
    
    # 展开 ~
    if path_str.startswith('~'):
        path_str = os.path.expanduser(path_str)
    
    # 展开环境变量
    path_str = os.path.expandvars(path_str)
    
    # 转换为 Path 并解析
    return Path(path_str).resolve()


def get_relative_path(
    path: Union[str, Path],
    base: Union[str, Path]
) -> str:
    """
    获取相对路径
    
    Args:
        path: 目标路径
        base: 基准路径
        
    Returns:
        str: 相对路径，如果无法计算则返回绝对路径
    """
    try:
        path = normalize_path(path)
        base = normalize_path(base)
        return str(path.relative_to(base))
    except ValueError:
        # 无法计算相对路径，返回绝对路径
        return str(path)


def is_subpath(
    path: Union[str, Path],
    parent: Union[str, Path]
) -> bool:
    """
    检查路径是否在父目录下
    
    Args:
        path: 要检查的路径
        parent: 父目录路径
        
    Returns:
        bool: 是否在父目录下
    """
    try:
        path = normalize_path(path)
        parent = normalize_path(parent)
        path.relative_to(parent)
        return True
    except ValueError:
        return False


def get_file_extension(path: Union[str, Path]) -> str:
    """
    获取文件扩展名（小写）
    
    Args:
        path: 文件路径
        
    Returns:
        str: 扩展名（包含点号），如 ".txt"
    """
    return Path(path).suffix.lower()


def get_file_stem(path: Union[str, Path]) -> str:
    """
    获取文件名（不含扩展名）
    
    Args:
        path: 文件路径
        
    Returns:
        str: 文件名
    """
    return Path(path).stem


def get_file_name(path: Union[str, Path]) -> str:
    """
    获取完整文件名（含扩展名）
    
    Args:
        path: 文件路径
        
    Returns:
        str: 文件名
    """
    return Path(path).name


# ============================================================
# 文件类型判断
# ============================================================

def is_spice_file(path: Union[str, Path]) -> bool:
    """
    判断是否为可仿真的 SPICE 文件
    
    支持的扩展名：.cir, .sp, .spice, .net, .ckt
    
    Args:
        path: 文件路径
        
    Returns:
        bool: 是否为可仿真的 SPICE 文件
    """
    ext = get_file_extension(path)
    return ext in SPICE_EXTENSIONS


def is_spice_lib_file(path: Union[str, Path]) -> bool:
    """
    判断是否为 SPICE 库文件（不可直接仿真）
    
    支持的扩展名：.lib, .mod, .sub
    
    Args:
        path: 文件路径
        
    Returns:
        bool: 是否为 SPICE 库文件
    """
    ext = get_file_extension(path)
    return ext in SPICE_LIB_EXTENSIONS


def is_any_spice_file(path: Union[str, Path]) -> bool:
    """
    判断是否为任意 SPICE 相关文件（包括库文件）
    
    支持的扩展名：.cir, .sp, .spice, .net, .ckt, .lib, .mod, .sub
    
    Args:
        path: 文件路径
        
    Returns:
        bool: 是否为 SPICE 相关文件
    """
    ext = get_file_extension(path)
    return ext in ALL_SPICE_EXTENSIONS


def is_python_file(path: Union[str, Path]) -> bool:
    """
    判断是否为 Python 文件
    
    支持的扩展名：.py
    
    Args:
        path: 文件路径
        
    Returns:
        bool: 是否为 Python 文件
    """
    ext = get_file_extension(path)
    return ext in PYTHON_EXTENSIONS


def is_simulatable_file(
    path: Union[str, Path],
    supported_extensions: Optional[set] = None
) -> bool:
    """
    判断是否为可仿真文件
    
    根据已注册执行器支持的扩展名判断。
    如果未提供 supported_extensions，则使用默认的 SPICE 和 Python 扩展名。
    
    Args:
        path: 文件路径
        supported_extensions: 支持的扩展名集合（可选，从 executor_registry 获取）
        
    Returns:
        bool: 是否为可仿真文件
    """
    ext = get_file_extension(path)
    
    if supported_extensions is not None:
        return ext in supported_extensions
    
    # 默认支持 SPICE 文件和 Python 脚本
    default_extensions = SPICE_EXTENSIONS | PYTHON_EXTENSIONS
    return ext in default_extensions


def is_image_file(path: Union[str, Path]) -> bool:
    """
    判断是否为图片文件
    
    支持的扩展名：.png, .jpg, .jpeg, .gif, .bmp, .webp, .svg, .ico
    
    Args:
        path: 文件路径
        
    Returns:
        bool: 是否为图片文件
    """
    ext = get_file_extension(path)
    return ext in IMAGE_EXTENSIONS


def is_text_file(path: Union[str, Path]) -> bool:
    """
    判断是否为文本文件
    
    Args:
        path: 文件路径
        
    Returns:
        bool: 是否为文本文件
    """
    ext = get_file_extension(path)
    return ext in TEXT_EXTENSIONS


def is_markdown_file(path: Union[str, Path]) -> bool:
    """
    判断是否为 Markdown 文件
    
    支持的扩展名：.md, .markdown
    
    Args:
        path: 文件路径
        
    Returns:
        bool: 是否为 Markdown 文件
    """
    ext = get_file_extension(path)
    return ext in MARKDOWN_EXTENSIONS


def is_word_file(path: Union[str, Path]) -> bool:
    """
    判断是否为 Word 文档
    
    支持的扩展名：.docx（不支持旧版 .doc）
    
    Args:
        path: 文件路径
        
    Returns:
        bool: 是否为 Word 文档
    """
    ext = get_file_extension(path)
    return ext in WORD_EXTENSIONS


def is_pdf_file(path: Union[str, Path]) -> bool:
    """
    判断是否为 PDF 文档
    
    Args:
        path: 文件路径
        
    Returns:
        bool: 是否为 PDF 文档
    """
    ext = get_file_extension(path)
    return ext in PDF_EXTENSIONS


def is_document_file(path: Union[str, Path]) -> bool:
    """
    判断是否为文档文件（Markdown、Word、PDF）
    
    Args:
        path: 文件路径
        
    Returns:
        bool: 是否为文档文件
    """
    ext = get_file_extension(path)
    return ext in DOCUMENT_EXTENSIONS


def is_hidden_file(path: Union[str, Path]) -> bool:
    """
    判断是否为隐藏文件
    
    - Unix: 以 . 开头
    - Windows: 检查文件属性
    
    Args:
        path: 文件路径
        
    Returns:
        bool: 是否为隐藏文件
    """
    name = Path(path).name
    
    # Unix 风格隐藏文件
    if name.startswith('.'):
        return True
    
    # Windows 隐藏属性
    if os.name == 'nt':
        try:
            import ctypes
            attrs = ctypes.windll.kernel32.GetFileAttributesW(str(path))
            if attrs != -1:
                FILE_ATTRIBUTE_HIDDEN = 0x02
                return bool(attrs & FILE_ATTRIBUTE_HIDDEN)
        except Exception:
            pass
    
    return False


def get_file_type(path: Union[str, Path]) -> str:
    """
    获取文件类型描述
    
    Args:
        path: 文件路径
        
    Returns:
        str: 文件类型描述（spice/spice_lib/python/image/markdown/word/pdf/text/binary）
    """
    if is_spice_file(path):
        return "spice"
    elif is_spice_lib_file(path):
        return "spice_lib"
    elif is_python_file(path):
        return "python"
    elif is_image_file(path):
        return "image"
    elif is_markdown_file(path):
        return "markdown"
    elif is_word_file(path):
        return "word"
    elif is_pdf_file(path):
        return "pdf"
    elif is_text_file(path):
        return "text"
    else:
        return "binary"


# ============================================================
# 安全文件名处理
# ============================================================

def get_safe_filename(
    name: str,
    replacement: str = '_',
    max_length: int = 255
) -> str:
    """
    生成安全的文件名
    
    - 移除/替换非法字符
    - 处理 Windows 保留名
    - 限制长度
    - 处理 Unicode 字符
    
    Args:
        name: 原始文件名
        replacement: 替换非法字符的字符
        max_length: 最大长度
        
    Returns:
        str: 安全的文件名
    """
    if not name:
        return "unnamed"
    
    # 规范化 Unicode
    name = unicodedata.normalize('NFKC', name)
    
    # 替换非法字符
    name = re.sub(WINDOWS_ILLEGAL_CHARS, replacement, name)
    
    # 移除控制字符
    name = ''.join(c for c in name if unicodedata.category(c) != 'Cc')
    
    # 移除首尾空格和点号
    name = name.strip(' .')
    
    # 处理 Windows 保留名
    stem = Path(name).stem.upper()
    if stem in WINDOWS_RESERVED_NAMES:
        name = f"_{name}"
    
    # 限制长度
    if len(name) > max_length:
        # 保留扩展名
        ext = Path(name).suffix
        stem = Path(name).stem
        max_stem_length = max_length - len(ext)
        name = stem[:max_stem_length] + ext
    
    # 确保不为空
    if not name:
        return "unnamed"
    
    return name


def sanitize_path_component(component: str) -> str:
    """
    清理路径组件（目录名或文件名）
    
    Args:
        component: 路径组件
        
    Returns:
        str: 清理后的路径组件
    """
    return get_safe_filename(component)


# ============================================================
# 路径构建
# ============================================================

def join_path(*parts: Union[str, Path]) -> Path:
    """
    安全地连接路径组件
    
    Args:
        *parts: 路径组件
        
    Returns:
        Path: 连接后的路径
    """
    if not parts:
        return Path('.')
    
    result = Path(parts[0])
    for part in parts[1:]:
        result = result / part
    
    return result


def ensure_extension(
    path: Union[str, Path],
    extension: str
) -> Path:
    """
    确保文件有指定的扩展名
    
    Args:
        path: 文件路径
        extension: 期望的扩展名（如 ".txt"）
        
    Returns:
        Path: 带有正确扩展名的路径
    """
    path = Path(path)
    
    # 确保扩展名以点号开头
    if not extension.startswith('.'):
        extension = '.' + extension
    
    if path.suffix.lower() != extension.lower():
        return path.with_suffix(extension)
    
    return path


def get_unique_path(
    path: Union[str, Path],
    separator: str = '_'
) -> Path:
    """
    获取唯一的文件路径
    
    如果文件已存在，添加数字后缀
    
    Args:
        path: 原始路径
        separator: 数字前的分隔符
        
    Returns:
        Path: 唯一的文件路径
    """
    path = Path(path)
    
    if not path.exists():
        return path
    
    stem = path.stem
    suffix = path.suffix
    parent = path.parent
    
    counter = 1
    while True:
        new_name = f"{stem}{separator}{counter}{suffix}"
        new_path = parent / new_name
        if not new_path.exists():
            return new_path
        counter += 1


# ============================================================
# 模块导出
# ============================================================

__all__ = [
    # 常量
    "SPICE_EXTENSIONS",
    "SPICE_LIB_EXTENSIONS",
    "ALL_SPICE_EXTENSIONS",
    "PYTHON_EXTENSIONS",
    "IMAGE_EXTENSIONS",
    "TEXT_EXTENSIONS",
    "MARKDOWN_EXTENSIONS",
    "WORD_EXTENSIONS",
    "PDF_EXTENSIONS",
    "DOCUMENT_EXTENSIONS",
    # 路径处理
    "normalize_path",
    "get_relative_path",
    "is_subpath",
    "get_file_extension",
    "get_file_stem",
    "get_file_name",
    # 文件类型判断
    "is_spice_file",
    "is_spice_lib_file",
    "is_any_spice_file",
    "is_python_file",
    "is_simulatable_file",
    "is_image_file",
    "is_text_file",
    "is_markdown_file",
    "is_word_file",
    "is_pdf_file",
    "is_document_file",
    "is_hidden_file",
    "get_file_type",
    # 安全文件名
    "get_safe_filename",
    "sanitize_path_component",
    # 路径构建
    "join_path",
    "ensure_extension",
    "get_unique_path",
]
