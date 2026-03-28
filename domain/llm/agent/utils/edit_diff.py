# Edit Diff Utils - 行尾归一化、模糊匹配、diff 生成工具函数
"""
编辑差异工具函数

职责：
- 检测和归一化行尾格式（CRLF / LF）
- BOM 剥离和恢复
- 模糊匹配文本（先精确后模糊，Unicode 归一化）
- 生成带行号的 unified diff 字符串

参考来源：
- pi-mono: packages/coding-agent/src/core/tools/edit-diff.ts
  - detectLineEnding(): 检测行尾格式
  - normalizeToLF(): 统一为 LF
  - restoreLineEndings(): 恢复原始行尾
  - stripBom(): BOM 剥离
  - normalizeForFuzzyMatch(): 模糊匹配归一化
  - fuzzyFindText(): 先精确后模糊查找
  - generateDiffString(): 带行号的 unified diff

设计说明：
- 函数签名和行为与 pi-mono edit-diff.ts 一一对应
- diff 生成使用 Python difflib 替代 Node.js 的 diff 库
- 模糊匹配归一化规则与 pi-mono 完全一致
"""

import difflib
import re
import unicodedata
from dataclasses import dataclass
from typing import Optional, Tuple


# ============================================================
# 行尾处理
# ============================================================

def detect_line_ending(content: str) -> str:
    """
    检测内容的行尾格式
    
    对应 pi-mono detectLineEnding()
    
    Args:
        content: 文件内容
        
    Returns:
        "\\r\\n" 或 "\\n"
    """
    crlf_idx = content.find('\r\n')
    lf_idx = content.find('\n')
    
    if lf_idx == -1:
        return '\n'
    if crlf_idx == -1:
        return '\n'
    
    return '\r\n' if crlf_idx < lf_idx else '\n'


def normalize_to_lf(text: str) -> str:
    """
    将所有行尾统一为 LF
    
    对应 pi-mono normalizeToLF()
    """
    return text.replace('\r\n', '\n').replace('\r', '\n')


def restore_line_endings(text: str, ending: str) -> str:
    """
    恢复原始行尾格式
    
    对应 pi-mono restoreLineEndings()
    
    Args:
        text: LF 格式的文本
        ending: 目标行尾格式（"\\r\\n" 或 "\\n"）
    """
    if ending == '\r\n':
        return text.replace('\n', '\r\n')
    return text


# ============================================================
# BOM 处理
# ============================================================

def strip_bom(content: str) -> Tuple[str, str]:
    """
    剥离 UTF-8 BOM
    
    对应 pi-mono stripBom()
    
    Args:
        content: 原始文件内容
        
    Returns:
        (bom, text) 元组
        - bom: BOM 字符串（"\\uFEFF" 或 ""）
        - text: 去除 BOM 后的内容
    """
    if content.startswith('\ufeff'):
        return '\ufeff', content[1:]
    return '', content


# ============================================================
# 模糊匹配
# ============================================================

# 智能引号 → ASCII 引号
_SMART_SINGLE_QUOTES = re.compile(r'[\u2018\u2019\u201A\u201B]')
_SMART_DOUBLE_QUOTES = re.compile(r'[\u201C\u201D\u201E\u201F]')

# 各种破折号/连字符 → ASCII 连字符
_UNICODE_DASHES = re.compile(r'[\u2010\u2011\u2012\u2013\u2014\u2015\u2212]')

# 特殊空格 → 普通空格
_UNICODE_SPACES = re.compile(r'[\u00A0\u2002-\u200A\u202F\u205F\u3000]')


def normalize_for_fuzzy_match(text: str) -> str:
    """
    模糊匹配归一化
    
    对应 pi-mono normalizeForFuzzyMatch()：
    1. NFKC 归一化
    2. 每行去除行尾空白
    3. 智能引号 → ASCII 引号
    4. Unicode 破折号 → ASCII 连字符
    5. 特殊空格 → 普通空格
    
    Args:
        text: 原始文本
        
    Returns:
        归一化后的文本
    """
    # NFKC 归一化
    result = unicodedata.normalize('NFKC', text)
    
    # 每行去除行尾空白
    result = '\n'.join(line.rstrip() for line in result.split('\n'))
    
    # 智能引号 → ASCII
    result = _SMART_SINGLE_QUOTES.sub("'", result)
    result = _SMART_DOUBLE_QUOTES.sub('"', result)
    
    # 破折号 → 连字符
    result = _UNICODE_DASHES.sub('-', result)
    
    # 特殊空格 → 普通空格
    result = _UNICODE_SPACES.sub(' ', result)
    
    return result


@dataclass
class FuzzyMatchResult:
    """
    模糊匹配结果
    
    对应 pi-mono FuzzyMatchResult 接口
    
    Attributes:
        found: 是否找到匹配
        index: 匹配起始位置（在 content_for_replacement 中的索引）
        match_length: 匹配文本长度
        used_fuzzy_match: 是否使用了模糊匹配（False = 精确匹配）
        content_for_replacement: 用于替换操作的内容
            精确匹配时为原始内容，模糊匹配时为归一化后的内容
    """
    found: bool
    index: int
    match_length: int
    used_fuzzy_match: bool
    content_for_replacement: str


def fuzzy_find_text(content: str, old_text: str) -> FuzzyMatchResult:
    """
    查找文本，先精确匹配，失败后模糊匹配
    
    对应 pi-mono fuzzyFindText()：
    1. 先尝试精确匹配（str.find）
    2. 精确失败则对内容和搜索文本都做归一化后再匹配
    3. 模糊匹配时，content_for_replacement 为归一化后的内容
    
    Args:
        content: 文件内容（已归一化为 LF）
        old_text: 要查找的文本（已归一化为 LF）
        
    Returns:
        FuzzyMatchResult
    """
    # 先精确匹配
    exact_index = content.find(old_text)
    if exact_index != -1:
        return FuzzyMatchResult(
            found=True,
            index=exact_index,
            match_length=len(old_text),
            used_fuzzy_match=False,
            content_for_replacement=content,
        )
    
    # 模糊匹配——在归一化空间中查找
    fuzzy_content = normalize_for_fuzzy_match(content)
    fuzzy_old_text = normalize_for_fuzzy_match(old_text)
    fuzzy_index = fuzzy_content.find(fuzzy_old_text)
    
    if fuzzy_index == -1:
        return FuzzyMatchResult(
            found=False,
            index=-1,
            match_length=0,
            used_fuzzy_match=False,
            content_for_replacement=content,
        )
    
    # 模糊匹配成功，后续替换在归一化空间中进行
    return FuzzyMatchResult(
        found=True,
        index=fuzzy_index,
        match_length=len(fuzzy_old_text),
        used_fuzzy_match=True,
        content_for_replacement=fuzzy_content,
    )


# ============================================================
# Diff 生成
# ============================================================

@dataclass
class DiffResult:
    """
    Diff 生成结果
    
    Attributes:
        diff: 带行号的 unified diff 字符串
        first_changed_line: 新文件中第一个变更行号（1-indexed）
    """
    diff: str
    first_changed_line: Optional[int]


def generate_diff_string(
    old_content: str,
    new_content: str,
    context_lines: int = 4,
) -> DiffResult:
    """
    生成带行号的 unified diff 字符串
    
    对应 pi-mono generateDiffString()。
    使用 difflib.unified_diff 生成差异，然后格式化为带行号的输出。
    
    输出格式（与 pi-mono 一致）：
        +  5 new line added
        - 10 old line removed
           7 context line
              ...
    
    Args:
        old_content: 原始内容
        new_content: 修改后的内容
        context_lines: 上下文行数（默认 4）
        
    Returns:
        DiffResult
    """
    old_lines = old_content.split('\n')
    new_lines = new_content.split('\n')
    
    max_line_num = max(len(old_lines), len(new_lines))
    line_num_width = len(str(max_line_num))
    
    # 使用 difflib 获取操作码
    matcher = difflib.SequenceMatcher(None, old_lines, new_lines)
    opcodes = matcher.get_opcodes()
    
    output = []
    first_changed_line = None
    
    for tag, i1, i2, j1, j2 in opcodes:
        if tag == 'equal':
            # 上下文行——只显示与变更相邻的部分
            equal_lines = old_lines[i1:i2]
            total = len(equal_lines)
            
            if total == 0:
                continue
            
            # 判断前后是否有变更
            # 找到该 opcode 在列表中的位置
            op_idx = opcodes.index((tag, i1, i2, j1, j2))
            has_prev_change = op_idx > 0 and opcodes[op_idx - 1][0] != 'equal'
            has_next_change = op_idx < len(opcodes) - 1 and opcodes[op_idx + 1][0] != 'equal'
            
            if has_prev_change and has_next_change:
                # 前后都有变更，显示尾部上下文 + 省略 + 头部上下文
                if total <= context_lines * 2:
                    # 太短，全部显示
                    for k, line in enumerate(equal_lines):
                        ln = str(i1 + k + 1).rjust(line_num_width)
                        output.append(f' {ln} {line}')
                else:
                    # 显示尾部上下文
                    for k in range(context_lines):
                        ln = str(i1 + k + 1).rjust(line_num_width)
                        output.append(f' {ln} {equal_lines[k]}')
                    # 省略号
                    output.append(f' {"".rjust(line_num_width)} ...')
                    # 显示头部上下文（为下一个变更准备）
                    start = total - context_lines
                    for k in range(start, total):
                        ln = str(i1 + k + 1).rjust(line_num_width)
                        output.append(f' {ln} {equal_lines[k]}')
            elif has_prev_change:
                # 只有前面有变更，显示尾部上下文
                show = min(total, context_lines)
                for k in range(show):
                    ln = str(i1 + k + 1).rjust(line_num_width)
                    output.append(f' {ln} {equal_lines[k]}')
                if show < total:
                    output.append(f' {"".rjust(line_num_width)} ...')
            elif has_next_change:
                # 只有后面有变更，显示头部上下文
                start = max(0, total - context_lines)
                if start > 0:
                    output.append(f' {"".rjust(line_num_width)} ...')
                for k in range(start, total):
                    ln = str(i1 + k + 1).rjust(line_num_width)
                    output.append(f' {ln} {equal_lines[k]}')
            # 如果前后都没有变更，完全跳过
            
        elif tag == 'replace':
            # 替换：先显示删除行，再显示添加行
            if first_changed_line is None:
                first_changed_line = j1 + 1
            for k in range(i1, i2):
                ln = str(k + 1).rjust(line_num_width)
                output.append(f'-{ln} {old_lines[k]}')
            for k in range(j1, j2):
                ln = str(k + 1).rjust(line_num_width)
                output.append(f'+{ln} {new_lines[k]}')
                
        elif tag == 'delete':
            if first_changed_line is None:
                first_changed_line = j1 + 1
            for k in range(i1, i2):
                ln = str(k + 1).rjust(line_num_width)
                output.append(f'-{ln} {old_lines[k]}')
                
        elif tag == 'insert':
            if first_changed_line is None:
                first_changed_line = j1 + 1
            for k in range(j1, j2):
                ln = str(k + 1).rjust(line_num_width)
                output.append(f'+{ln} {new_lines[k]}')
    
    return DiffResult(
        diff='\n'.join(output),
        first_changed_line=first_changed_line,
    )


# ============================================================
# 模块导出
# ============================================================

__all__ = [
    "detect_line_ending",
    "normalize_to_lf",
    "restore_line_endings",
    "strip_bom",
    "normalize_for_fuzzy_match",
    "FuzzyMatchResult",
    "fuzzy_find_text",
    "DiffResult",
    "generate_diff_string",
]
