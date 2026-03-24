# Path Utils - 路径解析与安全校验工具函数
"""
路径工具函数

职责：
- 将 LLM 返回的相对路径解析为绝对路径
- 处理 ~ 前缀和 Unicode 空格
- 安全校验：确保路径在项目目录内

参考来源：
- pi-mono: packages/coding-agent/src/core/tools/path-utils.ts
  - expandPath(): ~ 展开、Unicode 空格归一化、@ 前缀去除
  - resolveToCwd(): 相对路径解析为绝对路径
  - resolveReadPath(): 尝试多种文件名变体（macOS 兼容）

使用示例：
    from domain.llm.agent.utils.path_utils import resolve_to_cwd, is_path_within

    abs_path = resolve_to_cwd("src/main.cir", "/project/root")
    if is_path_within(abs_path, "/project/root"):
        # 安全，可以操作
        ...
"""

import os
import re
import unicodedata
from pathlib import Path
from typing import Optional


# Unicode 空格字符正则（与 pi-mono 一致）
_UNICODE_SPACES = re.compile(
    r'[\u00A0\u2000-\u200A\u202F\u205F\u3000]'
)


def _normalize_unicode_spaces(text: str) -> str:
    """将 Unicode 特殊空格替换为普通空格"""
    return _UNICODE_SPACES.sub(' ', text)


def _normalize_at_prefix(file_path: str) -> str:
    """去除 @ 前缀（某些 LLM 输出路径时可能带 @ 前缀）"""
    if file_path.startswith('@'):
        return file_path[1:]
    return file_path


def expand_path(file_path: str) -> str:
    """
    展开路径中的特殊前缀和字符
    
    处理逻辑（对应 pi-mono expandPath）：
    1. 去除 @ 前缀
    2. Unicode 空格归一化
    3. ~ 展开为用户目录
    
    Args:
        file_path: 原始路径字符串
        
    Returns:
        展开后的路径字符串
    """
    normalized = _normalize_unicode_spaces(_normalize_at_prefix(file_path.strip()))
    
    if normalized == '~':
        return os.path.expanduser('~')
    if normalized.startswith('~/') or normalized.startswith('~\\'):
        return os.path.expanduser('~') + normalized[1:]
    
    return normalized


def resolve_to_cwd(file_path: str, cwd: str) -> str:
    """
    将路径解析为绝对路径
    
    对应 pi-mono 的 resolveToCwd(filePath, cwd)：
    - 如果路径已经是绝对路径，直接返回（规范化后）
    - 否则相对于 cwd 解析
    
    Args:
        file_path: 文件路径（LLM 返回的路径，可能是相对或绝对）
        cwd: 当前工作目录（通常是 ToolContext.project_root）
        
    Returns:
        绝对路径字符串（已规范化）
    """
    expanded = expand_path(file_path)
    
    if os.path.isabs(expanded):
        return os.path.normpath(expanded)
    
    return os.path.normpath(os.path.join(cwd, expanded))


def resolve_read_path(file_path: str, cwd: str) -> str:
    """
    解析用于读取的文件路径，尝试多种变体
    
    对应 pi-mono 的 resolveReadPath(filePath, cwd)：
    - 先解析为绝对路径
    - 如果文件存在直接返回
    - 否则尝试 Unicode NFC/NFD 变体（跨平台文件名兼容）
    
    本项目运行在 Windows 上，主要处理 NFC/NFD 差异。
    macOS 特有的截图路径变体在本项目中暂不需要。
    
    Args:
        file_path: 文件路径
        cwd: 当前工作目录
        
    Returns:
        解析后的绝对路径（尽力查找存在的文件）
    """
    resolved = resolve_to_cwd(file_path, cwd)
    
    if os.path.exists(resolved):
        return resolved
    
    # 尝试 NFC 归一化（Unicode 组合字符差异）
    nfc_variant = unicodedata.normalize('NFC', resolved)
    if nfc_variant != resolved and os.path.exists(nfc_variant):
        return nfc_variant
    
    # 尝试 NFD 归一化
    nfd_variant = unicodedata.normalize('NFD', resolved)
    if nfd_variant != resolved and os.path.exists(nfd_variant):
        return nfd_variant
    
    # 未找到变体，返回原始解析结果（让调用方处理文件不存在的错误）
    return resolved


def is_path_within(file_path: str, root_dir: str) -> bool:
    """
    检查路径是否在指定目录内（安全校验）
    
    防止 LLM 通过 "../" 等方式访问项目目录外的文件。
    使用 Path.resolve() 解析符号链接和 .. 后再比较。
    
    Args:
        file_path: 待检查的绝对路径
        root_dir: 允许的根目录
        
    Returns:
        True 如果路径在根目录内（包括根目录本身）
    """
    try:
        resolved_path = Path(file_path).resolve()
        resolved_root = Path(root_dir).resolve()
        
        # 检查 resolved_path 是否是 resolved_root 的子路径
        # 使用 is_relative_to (Python 3.9+)
        return resolved_path == resolved_root or resolved_path.is_relative_to(resolved_root)
    except (ValueError, OSError):
        return False


def validate_file_path(
    file_path: str,
    project_root: str,
    must_exist: bool = True,
) -> Optional[str]:
    """
    完整的文件路径校验流程（供工具 execute 方法调用）
    
    流程：
    1. resolve_read_path 解析为绝对路径
    2. is_path_within 安全校验
    3. 可选的存在性检查
    
    Args:
        file_path: LLM 返回的文件路径
        project_root: 项目根目录
        must_exist: 是否要求文件必须存在
        
    Returns:
        None: 校验通过
        str: 错误描述（校验失败时）
    """
    abs_path = resolve_read_path(file_path, project_root)
    
    # 安全校验
    if not is_path_within(abs_path, project_root):
        return (
            f"Access denied: path '{file_path}' resolves to '{abs_path}' "
            f"which is outside the project directory '{project_root}'"
        )
    
    # 存在性检查
    if must_exist and not os.path.exists(abs_path):
        return f"File not found: '{abs_path}'"
    
    if must_exist and not os.path.isfile(abs_path):
        return f"Path is not a file: '{abs_path}'"
    
    return None


# ============================================================
# 模块导出
# ============================================================

__all__ = [
    "expand_path",
    "resolve_to_cwd",
    "resolve_read_path",
    "is_path_within",
    "validate_file_path",
]
