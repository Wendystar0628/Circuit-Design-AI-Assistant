# Content Hash - Standardized Content Hashing
"""
内容哈希计算器

职责：
- 提供标准化的内容哈希计算
- 确保不同来源的相同内容产生相同哈希
- 处理换行符差异（CRLF vs LF）

设计背景：
LLM 工具调用存在"读取-思考-写入"的时间窗口（可能长达 10-30 秒），
期间用户可能在编辑器中修改并保存文件。需要通过内容哈希校验检测此类冲突。

规范化规则：
- 统一换行符为 LF（\r\n → \n，\r → \n）
- 不去除末尾换行符（保留 POSIX 规范的文件末尾换行）
- 不去除行尾空格（保持内容原样，仅处理换行符）

规范化原因：
- Windows 上 Qt 编辑器可能使用 CRLF
- Python open() 在不同模式下换行符处理不同
- 不规范化会导致相同内容产生不同哈希，造成误报冲突

使用示例：
    from infrastructure.persistence.content_hash import compute_content_hash
    
    # 计算内容哈希
    hash1 = compute_content_hash("R1 10K\\nR2 20K\\n")
    hash2 = compute_content_hash("R1 10K\\r\\nR2 20K\\r\\n")
    assert hash1 == hash2  # 换行符差异被规范化
"""

import hashlib
from pathlib import Path
from typing import Optional


def normalize_content(content: str) -> str:
    """
    规范化内容（处理换行符差异）
    
    规范化规则：
    - 统一换行符为 LF（\r\n → \n，\r → \n）
    - 不去除末尾换行符（保留 POSIX 规范）
    - 不去除行尾空格（保持内容原样）
    
    Args:
        content: 原始内容
        
    Returns:
        str: 规范化后的内容
    """
    # 先处理 CRLF，再处理单独的 CR
    normalized = content.replace('\r\n', '\n').replace('\r', '\n')
    return normalized


def compute_content_hash(content: str) -> str:
    """
    计算内容哈希（SHA-256）
    
    内容会先经过规范化处理，确保不同换行符格式的相同内容产生相同哈希。
    
    Args:
        content: 文件内容
        
    Returns:
        str: SHA-256 哈希值（十六进制字符串）
    """
    normalized = normalize_content(content)
    return hashlib.sha256(normalized.encode('utf-8')).hexdigest()


def compute_file_hash(file_path: str, encoding: str = 'utf-8') -> Optional[str]:
    """
    计算文件内容哈希
    
    Args:
        file_path: 文件路径
        encoding: 文件编码（默认 UTF-8）
        
    Returns:
        str: SHA-256 哈希值，文件不存在时返回 None
    """
    path = Path(file_path)
    if not path.exists():
        return None
    
    try:
        content = path.read_text(encoding=encoding)
        return compute_content_hash(content)
    except (IOError, UnicodeDecodeError):
        return None


# ============================================================
# 模块导出
# ============================================================

__all__ = [
    "normalize_content",
    "compute_content_hash",
    "compute_file_hash",
]
