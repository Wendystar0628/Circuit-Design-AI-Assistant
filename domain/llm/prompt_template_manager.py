# Prompt Template Manager - Unified Prompt Template Management
"""
Prompt 模板管理器 - 统一管理所有 Prompt 模板

职责：
- 从内置目录加载 Prompt 模板
- 支持模板变量填充
- 支持用户自定义模板覆盖

设计原则：
- 内置模板直接从 resources/prompts/ 加载，不复制到用户目录
- 用户自定义模板存储在 ~/.circuit_design_ai/prompts/custom/
- 无版本管理，始终使用当前内置模板
- 文件写入使用原子操作（临时文件 + 重命名）

使用示例：
    from domain.llm.prompt_template_manager import PromptTemplateManager
    from domain.llm.prompt_constants import PROMPT_EXTRACT_DESIGN_GOALS
    
    manager = PromptTemplateManager()
    prompt = manager.get_template(
        PROMPT_EXTRACT_DESIGN_GOALS,
        variables={"user_requirement": "Design a 20dB amplifier"}
    )
"""

import json
import logging
import os
import re
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

from domain.llm.prompt_constants import TEMPLATE_FORMAT_MAPPING


# ============================================================
# 常量定义
# ============================================================

# 内置模板目录（随软件分发）
BUILTIN_PROMPTS_DIR = Path(__file__).parent.parent.parent / "resources" / "prompts"

# 用户自定义模板目录
CUSTOM_PROMPTS_DIR = Path.home() / ".circuit_design_ai" / "prompts" / "custom"

# 模板文件名
TASK_PROMPTS_FILE = "task_prompts.json"
OUTPUT_FORMAT_PROMPTS_FILE = "output_format_prompts.json"
USER_PROMPTS_FILE = "user_prompts.json"


# ============================================================
# 数据类定义
# ============================================================

@dataclass
class TemplateMetadata:
    """模板元数据"""
    name: str
    description: str
    variables: List[str] = field(default_factory=list)
    required_variables: List[str] = field(default_factory=list)


@dataclass
class Template:
    """完整模板"""
    key: str
    metadata: TemplateMetadata
    content: str
    source: str  # "builtin", "custom", "fallback"


# ============================================================
# 硬编码回退模板（最小保护）
# ============================================================

FALLBACK_TEMPLATES: Dict[str, Dict[str, Any]] = {
    "EXTRACT_DESIGN_GOALS": {
        "name": "Design Goals Extraction",
        "description": "Extract design goals from user requirement",
        "variables": ["user_requirement"],
        "required_variables": ["user_requirement"],
        "content": "Extract the design goals from the following requirement:\n\n{user_requirement}"
    },
    "INITIAL_DESIGN": {
        "name": "Initial Design",
        "description": "Generate initial circuit design",
        "variables": ["design_goals"],
        "required_variables": ["design_goals"],
        "content": "Design a circuit based on these goals:\n\n{design_goals}"
    },
    "GENERAL_CONVERSATION": {
        "name": "General Conversation",
        "description": "Handle general conversation",
        "variables": ["user_message"],
        "required_variables": ["user_message"],
        "content": "Respond to the user:\n\n{user_message}"
    },
    "FREE_WORK_SYSTEM": {
        "name": "Free Work Mode",
        "description": "System prompt for free work mode",
        "variables": ["design_goals", "current_circuit"],
        "required_variables": [],
        "content": "You are a circuit design assistant.\n\nDesign Goals:\n{design_goals}\n\nCurrent Circuit:\n{current_circuit}"
    },
}


# ============================================================
# PromptTemplateManager 类
# ============================================================

class PromptTemplateManager:
    """
    Prompt 模板管理器
    
    模板加载优先级：
    1. 用户自定义模板（~/.circuit_design_ai/prompts/custom/user_prompts.json）
    2. 内置模板（resources/prompts/task_prompts.json）
    3. 硬编码最小模板（回退保护）
    
    文件写入策略：
    - 使用原子写入（临时文件 + 重命名）
    - 写入失败时保留原文件
    """
    
    def __init__(self):
        """初始化模板管理器"""
        self._logger = logging.getLogger(__name__)
        self._task_templates: Dict[str, Template] = {}
        self._format_templates: Dict[str, Template] = {}
        
        self._ensure_custom_directory()
        self.load_templates()
    
    def _ensure_custom_directory(self) -> None:
        """确保用户自定义目录存在"""
        try:
            CUSTOM_PROMPTS_DIR.mkdir(parents=True, exist_ok=True)
        except Exception as e:
            self._logger.warning(f"无法创建自定义模板目录: {e}")
    
    # ============================================================
    # 模板加载
    # ============================================================
    
    def load_templates(self) -> None:
        """加载所有模板到内存"""
        self._task_templates.clear()
        self._format_templates.clear()
        
        # 1. 加载内置模板
        self._load_builtin_templates()
        
        # 2. 加载用户自定义模板（覆盖同名）
        self._load_custom_templates()
        
        # 3. 填补硬编码回退模板
        self._load_fallback_templates()
        
        self._logger.info(
            f"模板加载完成: {len(self._task_templates)} 个任务模板, "
            f"{len(self._format_templates)} 个格式模板"
        )
    
    def _load_builtin_templates(self) -> None:
        """加载内置模板"""
        task_file = BUILTIN_PROMPTS_DIR / TASK_PROMPTS_FILE
        if task_file.exists():
            self._load_from_file(task_file, self._task_templates, "builtin")
        else:
            self._logger.warning(f"内置任务模板文件不存在: {task_file}")
        
        format_file = BUILTIN_PROMPTS_DIR / OUTPUT_FORMAT_PROMPTS_FILE
        if format_file.exists():
            self._load_from_file(format_file, self._format_templates, "builtin")
    
    def _load_custom_templates(self) -> None:
        """加载用户自定义模板"""
        custom_file = CUSTOM_PROMPTS_DIR / USER_PROMPTS_FILE
        if not custom_file.exists():
            return
        
        try:
            with open(custom_file, "r", encoding="utf-8") as f:
                custom_data = json.load(f)
            
            for key, data in custom_data.items():
                if key in self._task_templates:
                    # 继承内置模板的元数据，只覆盖 content
                    base = self._task_templates[key]
                    merged = self._merge_with_base(base, data)
                    self._task_templates[key] = self._create_template(key, merged, "custom")
                else:
                    self._task_templates[key] = self._create_template(key, data, "custom")
                self._logger.debug(f"已加载自定义模板: {key}")
        except json.JSONDecodeError as e:
            self._logger.error(f"自定义模板 JSON 解析失败: {e}")
        except Exception as e:
            self._logger.warning(f"加载自定义模板失败: {e}")
    
    def _load_fallback_templates(self) -> None:
        """加载硬编码回退模板（填补缺失）"""
        for key, data in FALLBACK_TEMPLATES.items():
            if key not in self._task_templates:
                self._task_templates[key] = self._create_template(key, data, "fallback")
                self._logger.warning(f"使用回退模板: {key}")
    
    def _load_from_file(self, path: Path, target: Dict[str, Template], source: str) -> None:
        """从 JSON 文件加载模板"""
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            for key, template_data in data.items():
                target[key] = self._create_template(key, template_data, source)
        except json.JSONDecodeError as e:
            self._logger.error(f"JSON 解析错误 {path}: {e}")
        except Exception as e:
            self._logger.error(f"加载模板文件失败 {path}: {e}")
    
    def _create_template(self, key: str, data: Dict[str, Any], source: str) -> Template:
        """创建模板对象"""
        metadata = TemplateMetadata(
            name=data.get("name", key),
            description=data.get("description", ""),
            variables=data.get("variables", []),
            required_variables=data.get("required_variables", []),
        )
        return Template(key=key, metadata=metadata, content=data.get("content", ""), source=source)
    
    def _merge_with_base(self, base: Template, custom_data: Dict[str, Any]) -> Dict[str, Any]:
        """合并用户自定义数据和内置模板"""
        return {
            "name": custom_data.get("name", base.metadata.name),
            "description": custom_data.get("description", base.metadata.description),
            "variables": custom_data.get("variables", base.metadata.variables),
            "required_variables": custom_data.get("required_variables", base.metadata.required_variables),
            "content": custom_data.get("content", base.content),
        }

    # ============================================================
    # 模板获取和变量填充
    # ============================================================
    
    def get_template(
        self,
        template_name: str,
        variables: Optional[Dict[str, Any]] = None,
        include_format: bool = True
    ) -> str:
        """
        获取填充变量后的模板
        
        Args:
            template_name: 模板名称常量
            variables: 变量字典
            include_format: 是否自动附加输出格式规范
            
        Returns:
            填充变量后的完整 Prompt 字符串
            
        Raises:
            ValueError: 模板不存在或缺少必需变量
        """
        variables = variables or {}
        
        template = self._task_templates.get(template_name)
        if not template:
            raise ValueError(f"模板不存在: {template_name}")
        
        # 校验必需变量
        missing = set(template.metadata.required_variables) - set(variables.keys())
        if missing:
            raise ValueError(f"缺少必需变量: {list(missing)}")
        
        # 填充变量
        content = self._fill_variables(template.content, variables)
        
        # 附加输出格式规范
        if include_format:
            format_content = self._get_format_content(template_name)
            if format_content:
                content = content + "\n" + format_content
        
        return content
    
    def get_template_raw(self, template_name: str) -> Optional[str]:
        """
        获取原始模板内容（不填充变量）
        
        Args:
            template_name: 模板名称
            
        Returns:
            原始模板内容，模板不存在时返回 None
        """
        template = self._task_templates.get(template_name)
        return template.content if template else None
    
    def has_template(self, template_name: str) -> bool:
        """
        检查模板是否存在
        
        Args:
            template_name: 模板名称
            
        Returns:
            模板是否存在
        """
        return template_name in self._task_templates
    
    def _fill_variables(self, content: str, variables: Dict[str, Any]) -> str:
        """填充模板变量，支持嵌套访问"""
        result = content
        placeholders = re.findall(r'\{([^{}]+)\}', content)
        
        for placeholder in placeholders:
            value = self._get_nested_value(placeholder, variables)
            if value is None:
                str_value = ""
            elif isinstance(value, (dict, list)):
                str_value = json.dumps(value, ensure_ascii=False, indent=2)
            else:
                str_value = str(value)
            result = result.replace(f"{{{placeholder}}}", str_value)
        
        return result
    
    def _get_nested_value(self, key: str, variables: Dict[str, Any]) -> Any:
        """获取嵌套变量值（支持点号访问）"""
        parts = key.split(".")
        value = variables
        for part in parts:
            if isinstance(value, dict):
                value = value.get(part)
            else:
                return None
            if value is None:
                return None
        return value
    
    def _get_format_content(self, template_name: str) -> Optional[str]:
        """获取模板对应的输出格式规范"""
        format_name = TEMPLATE_FORMAT_MAPPING.get(template_name)
        if not format_name:
            return None
        format_template = self._format_templates.get(format_name)
        return format_template.content if format_template else None

    # ============================================================
    # 模板查询
    # ============================================================
    
    def list_templates(self) -> List[str]:
        """列出所有可用的任务模板名称"""
        return list(self._task_templates.keys())
    
    def list_format_templates(self) -> List[str]:
        """列出所有可用的输出格式模板名称"""
        return list(self._format_templates.keys())
    
    def get_template_metadata(self, template_name: str) -> Optional[TemplateMetadata]:
        """获取模板元数据"""
        template = self._task_templates.get(template_name)
        return template.metadata if template else None
    
    def get_template_source(self, template_name: str) -> Optional[str]:
        """获取模板来源（builtin/custom/fallback）"""
        template = self._task_templates.get(template_name)
        return template.source if template else None
    
    def get_all_templates(self) -> Dict[str, Template]:
        """
        获取所有模板的完整信息（供编辑器使用）
        
        Returns:
            模板名称到 Template 对象的映射
        """
        return dict(self._task_templates)
    
    def validate_template(self, template_name: str, variables: Dict[str, Any]) -> Dict[str, Any]:
        """
        校验模板变量完整性
        
        Args:
            template_name: 模板名称
            variables: 待校验的变量字典
            
        Returns:
            校验结果字典，包含 valid、missing_required、missing_optional、extra_variables
        """
        template = self._task_templates.get(template_name)
        if not template:
            return {"valid": False, "error": f"模板不存在: {template_name}"}
        
        provided = set(variables.keys())
        required = set(template.metadata.required_variables)
        all_vars = set(template.metadata.variables)
        
        return {
            "valid": required.issubset(provided),
            "missing_required": list(required - provided),
            "missing_optional": list((all_vars - required) - provided),
            "extra_variables": list(provided - all_vars),
        }
    
    # ============================================================
    # 用户自定义模板管理
    # ============================================================
    
    def register_custom_template(
        self,
        name: str,
        content: str,
        metadata: Optional[Dict[str, Any]] = None
    ) -> bool:
        """
        注册用户自定义模板
        
        Args:
            name: 模板名称
            content: 模板内容
            metadata: 可选的元数据（name, description, variables, required_variables）
            
        Returns:
            是否注册成功
        """
        try:
            template_data = metadata.copy() if metadata else {}
            template_data["content"] = content
            
            # 如果覆盖现有模板，继承元数据
            if name in self._task_templates:
                base = self._task_templates[name]
                template_data = self._merge_with_base(base, template_data)
            
            self._task_templates[name] = self._create_template(name, template_data, "custom")
            self._save_custom_templates()
            self._logger.info(f"已注册自定义模板: {name}")
            return True
        except Exception as e:
            self._logger.error(f"注册自定义模板失败 {name}: {e}")
            return False
    
    def reset_to_default(self, template_name: str) -> bool:
        """
        重置模板为内置默认
        
        Args:
            template_name: 模板名称
            
        Returns:
            是否重置成功
        """
        try:
            # 从内置模板重新加载
            task_file = BUILTIN_PROMPTS_DIR / TASK_PROMPTS_FILE
            if task_file.exists():
                with open(task_file, "r", encoding="utf-8") as f:
                    builtin_data = json.load(f)
                if template_name in builtin_data:
                    self._task_templates[template_name] = self._create_template(
                        template_name, builtin_data[template_name], "builtin"
                    )
                    self._remove_from_custom_file(template_name)
                    self._logger.info(f"已重置模板为默认: {template_name}")
                    return True
            
            # 回退到硬编码模板
            if template_name in FALLBACK_TEMPLATES:
                self._task_templates[template_name] = self._create_template(
                    template_name, FALLBACK_TEMPLATES[template_name], "fallback"
                )
                self._remove_from_custom_file(template_name)
                return True
            
            return False
        except Exception as e:
            self._logger.error(f"重置模板失败 {template_name}: {e}")
            return False
    
    def _save_custom_templates(self) -> None:
        """
        保存用户自定义模板到文件
        
        使用原子写入策略：先写入临时文件，成功后重命名
        """
        custom_file = CUSTOM_PROMPTS_DIR / USER_PROMPTS_FILE
        custom_data = {}
        
        for key, template in self._task_templates.items():
            if template.source == "custom":
                custom_data[key] = {
                    "name": template.metadata.name,
                    "description": template.metadata.description,
                    "variables": template.metadata.variables,
                    "required_variables": template.metadata.required_variables,
                    "content": template.content,
                }
        
        try:
            # 原子写入：先写临时文件，再重命名
            fd, temp_path = tempfile.mkstemp(
                suffix=".json",
                prefix="user_prompts_",
                dir=CUSTOM_PROMPTS_DIR
            )
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as f:
                    json.dump(custom_data, f, ensure_ascii=False, indent=2)
                
                # 在 Windows 上需要先删除目标文件
                if custom_file.exists():
                    custom_file.unlink()
                
                Path(temp_path).rename(custom_file)
                self._logger.debug(f"自定义模板已保存: {custom_file}")
            except Exception:
                # 清理临时文件
                if Path(temp_path).exists():
                    Path(temp_path).unlink()
                raise
        except Exception as e:
            self._logger.error(f"保存自定义模板失败: {e}")
    
    def _remove_from_custom_file(self, template_name: str) -> None:
        """从用户自定义文件中移除模板"""
        custom_file = CUSTOM_PROMPTS_DIR / USER_PROMPTS_FILE
        if not custom_file.exists():
            return
        
        try:
            with open(custom_file, "r", encoding="utf-8") as f:
                custom_data = json.load(f)
            
            if template_name in custom_data:
                del custom_data[template_name]
                
                # 使用原子写入
                fd, temp_path = tempfile.mkstemp(
                    suffix=".json",
                    prefix="user_prompts_",
                    dir=CUSTOM_PROMPTS_DIR
                )
                try:
                    with os.fdopen(fd, "w", encoding="utf-8") as f:
                        json.dump(custom_data, f, ensure_ascii=False, indent=2)
                    
                    if custom_file.exists():
                        custom_file.unlink()
                    
                    Path(temp_path).rename(custom_file)
                except Exception:
                    if Path(temp_path).exists():
                        Path(temp_path).unlink()
                    raise
        except Exception as e:
            self._logger.warning(f"从自定义文件移除模板失败: {e}")
    
    def reload_templates(self) -> None:
        """重新加载所有模板（支持热更新）"""
        self._logger.info("正在重新加载模板...")
        self.load_templates()


# ============================================================
# 模块导出
# ============================================================

__all__ = [
    "PromptTemplateManager",
    "Template",
    "TemplateMetadata",
    "BUILTIN_PROMPTS_DIR",
    "CUSTOM_PROMPTS_DIR",
]
