#!/usr/bin/env python3
"""
代码行数统计工具

统计 circuit_design_ai 目录下的 Python 代码行数
排除：空行、注释行、__pycache__ 目录

使用方法：
    python count_lines.py
"""

import os
import re
from pathlib import Path
from typing import Dict, List, Tuple


def is_comment_or_empty(line: str, in_docstring: bool) -> Tuple[bool, bool]:
    """
    判断一行是否为注释或空行
    
    Args:
        line: 代码行
        in_docstring: 是否在多行字符串中
        
    Returns:
        Tuple[是否跳过该行, 更新后的 in_docstring 状态]
    """
    stripped = line.strip()
    
    # 空行
    if not stripped:
        return True, in_docstring
    
    # 检查多行字符串（docstring）的开始/结束
    triple_quotes = ['"""', "'''"]
    
    for quote in triple_quotes:
        count = stripped.count(quote)
        if count > 0:
            if count >= 2 and stripped.startswith(quote) and stripped.endswith(quote):
                # 单行 docstring，如 """这是注释"""
                return True, in_docstring
            elif count == 1:
                # 多行 docstring 的开始或结束
                in_docstring = not in_docstring
                return True, in_docstring
    
    # 在 docstring 中
    if in_docstring:
        return True, in_docstring
    
    # 单行注释
    if stripped.startswith('#'):
        return True, in_docstring
    
    return False, in_docstring


def count_file_lines(filepath: Path) -> Dict[str, int]:
    """
    统计单个文件的行数
    
    Returns:
        Dict: {total: 总行数, code: 代码行数, comment: 注释/空行数}
    """
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            lines = f.readlines()
    except Exception as e:
        print(f"  警告: 无法读取 {filepath}: {e}")
        return {"total": 0, "code": 0, "comment": 0}
    
    total = len(lines)
    code_lines = 0
    in_docstring = False
    
    for line in lines:
        skip, in_docstring = is_comment_or_empty(line, in_docstring)
        if not skip:
            code_lines += 1
    
    return {
        "total": total,
        "code": code_lines,
        "comment": total - code_lines
    }


def count_directory(root_path: Path) -> Dict[str, Dict]:
    """
    递归统计目录下所有 Python 文件
    
    Returns:
        Dict: {文件路径: {total, code, comment}}
    """
    results = {}
    
    # 排除的目录模式
    exclude_dirs = {
        "__pycache__",
        "circuit",      # 虚拟环境
        "venv",         # 虚拟环境
        ".venv",        # 虚拟环境
        "env",          # 虚拟环境
        ".env",         # 虚拟环境
        "site-packages",
        ".git",
        "node_modules",
        "vendor",       # 第三方库
        "tests",        # 测试文件
    }
    
    for filepath in root_path.rglob("*.py"):
        # 检查是否在排除目录中
        parts = filepath.relative_to(root_path).parts
        if any(part in exclude_dirs for part in parts):
            continue
        
        # 排除本统计脚本
        if filepath.name == "count_lines.py":
            continue
        
        relative_path = filepath.relative_to(root_path)
        results[str(relative_path)] = count_file_lines(filepath)
    
    return results


def print_report(results: Dict[str, Dict], root_path: Path) -> None:
    """打印统计报告"""
    # 按目录分组
    by_directory: Dict[str, List[Tuple[str, Dict]]] = {}
    
    for filepath, stats in sorted(results.items()):
        parts = Path(filepath).parts
        if len(parts) > 1:
            directory = str(Path(*parts[:-1]))
        else:
            directory = "."
        
        if directory not in by_directory:
            by_directory[directory] = []
        by_directory[directory].append((filepath, stats))
    
    # 打印报告
    print("=" * 70)
    print(f"代码行数统计报告 - {root_path}")
    print("=" * 70)
    print()
    
    total_all = {"total": 0, "code": 0, "comment": 0}
    dir_totals = {}
    
    for directory in sorted(by_directory.keys()):
        files = by_directory[directory]
        dir_total = {"total": 0, "code": 0, "comment": 0}
        
        print(f"📁 {directory}/")
        print("-" * 50)
        
        for filepath, stats in files:
            filename = Path(filepath).name
            print(f"  {filename:<35} {stats['code']:>6} 行")
            
            for key in dir_total:
                dir_total[key] += stats[key]
                total_all[key] += stats[key]
        
        print(f"  {'小计':<35} {dir_total['code']:>6} 行")
        print()
        
        dir_totals[directory] = dir_total
    
    # 打印汇总
    print("=" * 70)
    print("按目录汇总（有效代码行）")
    print("=" * 70)
    
    for directory in sorted(dir_totals.keys()):
        stats = dir_totals[directory]
        print(f"  {directory:<40} {stats['code']:>6} 行")
    
    print("-" * 70)
    print(f"  {'总计':<40} {total_all['code']:>6} 行")
    print()
    print(f"  总行数（含空行和注释）: {total_all['total']} 行")
    print(f"  有效代码行: {total_all['code']} 行")
    print(f"  空行和注释: {total_all['comment']} 行")
    print(f"  代码占比: {total_all['code'] / total_all['total'] * 100:.1f}%")
    print("=" * 70)


def main():
    # 获取脚本所在目录
    script_dir = Path(__file__).parent.resolve()
    
    print(f"正在统计 {script_dir} 目录下的 Python 代码...")
    print()
    
    results = count_directory(script_dir)
    
    if not results:
        print("未找到任何 Python 文件")
        return
    
    print_report(results, script_dir)


if __name__ == "__main__":
    main()
