# File Size Limits Constants
"""
文件大小限制常量

职责：
- 集中定义所有文件大小限制常量
- 确保各模块使用一致的阈值
- 防止 LLM 工具层 Context Window 爆炸

被调用方：
- tool_dispatcher.py（阶段六）- read_file 工具执行时检查
- file_analyzer.py（阶段二）- analyze_file 工具执行时检查
- token_budget_allocator.py（阶段五）- 截断时快速估算
- spice_symbol_extractor.py（阶段二）- 符号提取前检查
- python_symbol_extractor.py（阶段二）- 符号提取前检查
"""

# ============================================================
# read_file 工具限制
# ============================================================

# read_file 工具硬性字节限制（200KB）
# 超过此限制的文件，read_file 工具直接拒绝读取
READ_FILE_MAX_BYTES = 200 * 1024

# read_file 工具默认 Token 预算
# 返回内容超过此限制时自动截断
READ_FILE_DEFAULT_TOKENS = 2000

# ============================================================
# analyze_file 工具限制
# ============================================================

# analyze_file 工具硬性字节限制（5MB）
# 超过此限制的文件，analyze_file 工具直接拒绝分析
ANALYZE_FILE_MAX_BYTES = 5 * 1024 * 1024

# ============================================================
# 大文件警告阈值
# ============================================================

# 大文件警告阈值（行数）
# 超过此阈值的文件，返回结果中附加提示信息
LARGE_FILE_WARNING_LINES = 500

# 大文件警告阈值（字节数，50KB）
# 超过此阈值的文件，返回结果中附加提示信息
LARGE_FILE_WARNING_BYTES = 50 * 1024

# ============================================================
# Token 估算
# ============================================================

# Token 估算系数（字符数/token）
# 用于快速估算 Token 数，避免调用 tokenizer 的 O(N) 开销
# 经验值：英文约 4 字符/token，中文约 2 字符/token
# 取保守值 4，确保不会低估
CHARS_PER_TOKEN_ESTIMATE = 4


# ============================================================
# 模块导出
# ============================================================

__all__ = [
    "READ_FILE_MAX_BYTES",
    "READ_FILE_DEFAULT_TOKENS",
    "ANALYZE_FILE_MAX_BYTES",
    "LARGE_FILE_WARNING_LINES",
    "LARGE_FILE_WARNING_BYTES",
    "CHARS_PER_TOKEN_ESTIMATE",
]
