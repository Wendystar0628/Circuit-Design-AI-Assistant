# Patch File Tool - 搜索替换式编辑工具
"""
搜索替换式编辑工具

职责：
- 在文件中查找精确文本并替换为新文本
- 支持模糊匹配（Unicode 归一化后匹配）
- 唯一性检查（匹配必须唯一）
- BOM 和行尾格式保留
- 文件写入互斥保护
- 生成 diff 供 UI 展示

参考来源：
- pi-mono: packages/coding-agent/src/core/tools/edit.ts
  - editSchema: path, oldText, newText 参数定义
  - execute(): 完整的编辑流程（第 166-294 行）
- pi-mono: packages/coding-agent/src/core/tools/edit-diff.ts
  - stripBom, detectLineEnding, normalizeToLF, fuzzyFindText 等
- pi-mono: packages/coding-agent/src/core/tools/file-mutation-queue.ts
  - withFileMutationQueue: 文件互斥队列

使用示例：
    tool = PatchFileTool()
    result = await tool.execute(
        tool_call_id="call_456",
        params={
            "path": "src/main.cir",
            "old_text": "R1 1 0 1k",
            "new_text": "R1 1 0 2.2k",
        },
        context=ToolContext(project_root="/project"),
    )
"""

from typing import Any, Dict, List, Optional

from domain.llm.agent.types import BaseTool, ToolContext, ToolResult
from domain.llm.agent.utils.path_utils import validate_file_path
from domain.llm.agent.utils.edit_diff import (
    detect_line_ending,
    normalize_to_lf,
    restore_line_endings,
    strip_bom,
    normalize_for_fuzzy_match,
    fuzzy_find_text,
    generate_diff_string,
)
from domain.llm.agent.utils.file_mutex import with_file_mutex


class PatchFileTool(BaseTool):
    """
    搜索替换式编辑工具
    
    对应 pi-mono 的 edit 工具（edit.ts）。
    在文件中查找精确文本并替换，是最常用的文件编辑方式。
    
    执行流程（严格对照 edit.ts 第 166-294 行）：
    1. 路径解析 + 安全校验
    2. 文件互斥队列保护
    3. 读取文件 → BOM 剥离 → 行尾归一化
    4. 查找匹配（先精确后模糊）
    5. 唯一性检查
    6. 执行替换 → 空操作检查
    7. 恢复行尾 + BOM → 写回文件
    8. 生成 diff → 返回结果
    """
    
    @property
    def name(self) -> str:
        return "patch_file"
    
    @property
    def label(self) -> str:
        return "Patch File"
    
    @property
    def description(self) -> str:
        return (
            "Edit a file by replacing exact text. "
            "The old_text must match exactly (including whitespace). "
            "Use this for precise, surgical edits."
        )
    
    @property
    def parameters(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Path to the file to edit (relative to project root or absolute)",
                },
                "old_text": {
                    "type": "string",
                    "description": "Exact text to find and replace (must match exactly)",
                },
                "new_text": {
                    "type": "string",
                    "description": "New text to replace the old text with",
                },
            },
            "required": ["path", "old_text", "new_text"],
        }
    
    @property
    def prompt_snippet(self) -> Optional[str]:
        return "Make surgical edits to files (find exact text and replace)"
    
    @property
    def prompt_guidelines(self) -> Optional[List[str]]:
        return [
            "Use patch_file for precise changes (old_text must match exactly).",
            "Include enough context in old_text to make the match unique within the file.",
        ]
    
    async def execute(
        self,
        tool_call_id: str,
        params: Dict[str, Any],
        context: ToolContext,
    ) -> ToolResult:
        """
        执行文件编辑
        
        完整流程对照 pi-mono edit.ts 第 166-294 行。
        """
        path = params.get("path", "")
        old_text = params.get("old_text", "")
        new_text = params.get("new_text", "")
        
        # ---- 参数校验 ----
        if not path:
            return ToolResult(content="Error: 'path' parameter is required", is_error=True)
        if not old_text:
            return ToolResult(content="Error: 'old_text' parameter is required", is_error=True)
        # new_text 允许为空字符串（表示删除 old_text）
        
        # ---- 1. 路径解析 + 安全校验 + 存在性检查 ----
        abs_path, error = validate_file_path(path, context.project_root)
        if error:
            return ToolResult(content=f"Error: {error}", is_error=True)

        # ---- 1.5. 校验 ToolContext 提供的 PendingWorkspaceEditService ----
        # 权威设计：tool 不从全局服务定位器自取服务，
        # 调用方没提供就直接判作 is_error，禁止双路径回落。
        pending_edit_service = context.pending_workspace_edit_service
        if pending_edit_service is None:
            return ToolResult(
                content=(
                    "Error: PendingWorkspaceEditService is not provided by the "
                    "caller via ToolContext; the patch_file tool refuses to "
                    "write without an approval queue."
                ),
                is_error=True,
            )

        # ---- 2. 文件互斥队列保护 ----
        async with with_file_mutex(abs_path):
            return await self._execute_edit(
                abs_path, path, old_text, new_text, tool_call_id,
                pending_edit_service,
            )
    
    async def _execute_edit(
        self,
        abs_path: str,
        display_path: str,
        old_text: str,
        new_text: str,
        tool_call_id: str,
        pending_edit_service: Any,
    ) -> ToolResult:
        """
        在互斥锁保护下执行编辑操作
        
        Args:
            abs_path: 绝对路径
            display_path: 用于错误消息的显示路径
            old_text: 要查找的文本
            new_text: 替换后的文本
        """
        # ---- 3. 读取文件 ----
        try:
            with open(abs_path, 'r', encoding='utf-8', errors='replace', newline='') as f:
                raw_content = f.read()
        except PermissionError:
            return ToolResult(
                content=f"Error: Permission denied: {display_path}",
                is_error=True,
            )
        except Exception as e:
            return ToolResult(
                content=f"Error reading file '{display_path}': {e}",
                is_error=True,
            )
        
        # BOM 剥离（对应 edit.ts 第 194 行）
        bom, content = strip_bom(raw_content)
        
        # 行尾归一化（对应 edit.ts 第 196-199 行）
        original_ending = detect_line_ending(content)
        normalized_content = normalize_to_lf(content)
        normalized_old_text = normalize_to_lf(old_text)
        normalized_new_text = normalize_to_lf(new_text)
        
        # ---- 4. 查找匹配（对应 edit.ts 第 201-214 行）----
        match_result = fuzzy_find_text(normalized_content, normalized_old_text)
        
        if not match_result.found:
            return ToolResult(
                content=(
                    f"Error: Could not find the exact text in {display_path}. "
                    f"The old_text must match exactly including all whitespace and newlines."
                ),
                is_error=True,
            )
        
        # ---- 5. 唯一性检查（对应 edit.ts 第 216-231 行）----
        fuzzy_content = normalize_for_fuzzy_match(normalized_content)
        fuzzy_old_text = normalize_for_fuzzy_match(normalized_old_text)
        occurrences = fuzzy_content.count(fuzzy_old_text)
        
        if occurrences > 1:
            return ToolResult(
                content=(
                    f"Error: Found {occurrences} occurrences of the text in {display_path}. "
                    f"The text must be unique. Please provide more context to make it unique."
                ),
                is_error=True,
            )
        
        # ---- 6. 执行替换（对应 edit.ts 第 238-244 行）----
        base_content = match_result.content_for_replacement
        new_content = (
            base_content[:match_result.index]
            + normalized_new_text
            + base_content[match_result.index + match_result.match_length:]
        )
        
        # 空操作检查（对应 edit.ts 第 246-257 行）
        if base_content == new_content:
            return ToolResult(
                content=(
                    f"Error: No changes made to {display_path}. "
                    f"The replacement produced identical content."
                ),
                is_error=True,
            )
        
        # ---- 7. 写回文件（对应 edit.ts 第 259-260 行）----
        final_content = bom + restore_line_endings(new_content, original_ending)

        try:
            pending_edit_service.record_agent_edit(
                abs_path,
                final_content,
                tool_name=self.name,
                tool_call_id=tool_call_id,
            )
        except PermissionError:
            return ToolResult(
                content=f"Error: Permission denied writing to {display_path}",
                is_error=True,
            )
        except Exception as e:
            return ToolResult(
                content=f"Error writing file '{display_path}': {e}",
                is_error=True,
            )
        
        # ---- 8. 生成 diff（对应 edit.ts 第 272-281 行）----
        diff_result = generate_diff_string(base_content, new_content)
        
        return ToolResult(
            content=f"Successfully replaced text in {display_path}.",
            is_error=False,
            details={
                "diff": diff_result.diff,
                "first_changed_line": diff_result.first_changed_line,
                "path": abs_path,
            },
        )


# ============================================================
# 模块导出
# ============================================================

__all__ = ["PatchFileTool"]
