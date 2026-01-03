# Prompt Template Manager - Unified Prompt Template Management
"""
Prompt 模板管理器 - 统一管理所有 Prompt 模板

职责：
- 加载和管理所有 Prompt 模板
- 支持模板变量填充
- 支持用户自定义模板覆盖
- 版本控制和热更新

初始化顺序：Phase 3 延迟初始化阶段

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
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

from domain.llm.prompt_constants import (
    TEMPLATE_FORMAT_MAPPING,
    FORMAT_SPICE_OUTPUT,
    FORMAT_JSON_OUTPUT,
    FORMAT_ANALYSIS_OUTPUT,
)


# ============================================================
# 常量定义
# ============================================================

# 全局配置目录
GLOBAL_CONFIG_DIR = Path.home() / ".circuit_design_ai"
PROMPTS_DIR = GLOBAL_CONFIG_DIR / "prompts"
SYSTEM_PROMPTS_DIR = PROMPTS_DIR / "system"
CUSTOM_PROMPTS_DIR = PROMPTS_DIR / "custom"

# 内置模板目录（resources/prompts/）
BUILTIN_PROMPTS_DIR = Path(__file__).parent.parent.parent / "resources" / "prompts"

# 模板文件名
TASK_PROMPTS_FILE = "task_prompts.json"
OUTPUT_FORMAT_PROMPTS_FILE = "output_format_prompts.json"
VERSION_FILE = "version.json"
USER_PROMPTS_FILE = "user_prompts.json"


# ============================================================
# 数据类定义
# ============================================================

@dataclass
class TemplateMetadata:
    """模板元数据"""
    name: str
    description: str
    version: str
    variables: List[str] = field(default_factory=list)
    required_variables: List[str] = field(default_factory=list)


@dataclass
class Template:
    """完整模板"""
    key: str
    metadata: TemplateMetadata
    content: str
    source: str  # "system", "custom", "fallback"


# ============================================================
# 硬编码回退模板（最小保护）
# ============================================================

FALLBACK_TEMPLATES: Dict[str, Dict[str, Any]] = {
    "EXTRACT_DESIGN_GOALS": {
        "name": "Design Goals Extraction",
        "description": "Extract design goals from user requirement",
        "version": "0.0.1",
        "variables": ["user_requirement"],
        "required_variables": ["user_requirement"],
        "content": "Extract the design goals from the following requirement:\n\n{user_requirement}"
    },
    "INITIAL_DESIGN": {
        "name": "Initial Design",
        "description": "Generate initial circuit design",
        "version": "0.0.1",
        "variables": ["design_goals"],
        "required_variables": ["design_goals"],
        "content": "Design a circuit based on these goals:\n\n{design_goals}"
    },
    "GENERAL_CONVERSATION": {
        "name": "General Conversation",
        "description": "Handle general conversation",
        "version": "0.0.1",
        "variables": ["user_message"],
        "required_variables": ["user_message"],
        "content": "Respond to the user:\n\n{user_message}"
    },
    "FREE_WORK_SYSTEM": {
        "name": "Free Work Mode",
        "description": "System prompt for free work mode",
        "version": "0.0.1",
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
    
    职责：
    - 统一管理所有 Prompt 模板的加载、校验、版本控制
    - 支持用户自定义模板覆盖
    - 提供模板变量填充功能
    
    模板加载优先级：
    1. 用户自定义模板（custom/user_prompts.json）
    2. 系统内置模板（system/task_prompts.json）
    3. 硬编码最小模板（回退保护）
    """
    
    def __init__(self):
        """初始化模板管理器"""
        self._logger = logging.getLogger(__name__)
        
        # 模板缓存
        self._task_templates: Dict[str, Template] = {}
        self._format_templates: Dict[str, Template] = {}
        
        # 版本信息
        self._version_info: Dict[str, Any] = {}
        
        # 初始化目录并加载模板
        self._ensure_directories()
        self._copy_builtin_templates()
        self.load_templates()
    
    # ============================================================
    # 目录和文件管理
    # ============================================================
    
    def _ensure_directories(self) -> None:
        """确保必要的目录存在"""
        try:
            SYSTEM_PROMPTS_DIR.mkdir(parents=True, exist_ok=True)
            CUSTOM_PROMPTS_DIR.mkdir(parents=True, exist_ok=True)
            self._logger.debug(f"Prompt directories ensured: {PROMPTS_DIR}")
        except Exception as e:
            self._logger.error(f"Failed to create prompt directories: {e}")
    
    def _copy_builtin_templates(self) -> None:
        """
        复制内置模板到系统目录
        
        仅在以下情况复制：
        - 系统目录中不存在模板文件
        - 内置模板版本更新
        """
        if not BUILTIN_PROMPTS_DIR.exists():
            self._logger.warning(f"Builtin prompts directory not found: {BUILTIN_PROMPTS_DIR}")
            return
        
        # 检查版本
        builtin_version = self._read_version_file(BUILTIN_PROMPTS_DIR / VERSION_FILE)
        system_version = self._read_version_file(SYSTEM_PROMPTS_DIR / VERSION_FILE)
        
        should_copy = False
        if not system_version:
            should_copy = True
            self._logger.info("System prompts not found, copying builtin templates")
        elif builtin_version and builtin_version.get("version", "0") > system_version.get("version", "0"):
            should_copy = True
            self._logger.info(
                f"Builtin templates updated: {system_version.get('version')} -> {builtin_version.get('version')}"
            )
        
        if should_copy:
            self._copy_template_files()
    
    def _copy_template_files(self) -> None:
        """复制模板文件到系统目录"""
        files_to_copy = [TASK_PROMPTS_FILE, OUTPUT_FORMAT_PROMPTS_FILE, VERSION_FILE]
        
        for filename in files_to_copy:
            src = BUILTIN_PROMPTS_DIR / filename
            dst = SYSTEM_PROMPTS_DIR / filename
            
            if src.exists():
                try:
                    shutil.copy2(src, dst)
                    self._logger.debug(f"Copied template file: {filename}")
                except Exception as e:
                    self._logger.error(f"Failed to copy {filename}: {e}")
    
    def _read_version_file(self, path: Path) -> Optional[Dict[str, Any]]:
        """读取版本文件"""
        if not path.exists():
            return None
        
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            self._logger.warning(f"Failed to read version file {path}: {e}")
            return None
    
    # ============================================================
    # 模板加载
    # ============================================================
    
    def load_templates(self) -> None:
        """
        加载所有模板文件到内存
        
        加载顺序：
        1. 系统内置模板
        2. 用户自定义模板（覆盖同名模板）
        3. 硬编码回退模板（填补缺失）
        """
        self._task_templates.clear()
        self._format_templates.clear()
        
        # 1. 加载系统模板
        self._load_system_templates()
        
        # 2. 加载用户自定义模板（覆盖）
        self._load_custom_templates()
        
        # 3. 填补硬编码回退模板
        self._load_fallback_templates()
        
        # 4. 加载版本信息
        self._version_info = self._read_version_file(SYSTEM_PROMPTS_DIR / VERSION_FILE) or {}
        
        self._logger.info(
            f"Templates loaded: {len(self._task_templates)} task, {len(self._format_templates)} format"
        )
    
    def _load_system_templates(self) -> None:
        """加载系统内置模板"""
        # 加载任务模板
        task_file = SYSTEM_PROMPTS_DIR / TASK_PROMPTS_FILE
        if task_file.exists():
            self._load_templates_from_file(task_file, self._task_templates, "system")
        
        # 加载输出格式模板
        format_file = SYSTEM_PROMPTS_DIR / OUTPUT_FORMAT_PROMPTS_FILE
        if format_file.exists():
            self._load_templates_from_file(format_file, self._format_templates, "system")
    
    def _load_custom_templates(self) -> None:
        """加载用户自定义模板"""
        custom_file = CUSTOM_PROMPTS_DIR / USER_PROMPTS_FILE
        if not custom_file.exists():
            return
        
        try:
            with open(custom_file, "r", encoding="utf-8") as f:
                custom_data = json.load(f)
            
            for key, template_data in custom_data.items():
                # 用户模板可以只提供 content，其他元数据继承自系统模板
                if key in self._task_templates:
                    base_template = self._task_templates[key]
                    merged_data = self._merge_template_data(base_template, template_data)
                    self._task_templates[key] = self._create_template(key, merged_data, "custom")
                    self._logger.debug(f"Custom template overrides: {key}")
                else:
                    # 全新的用户模板
                    self._task_templates[key] = self._create_template(key, template_data, "custom")
                    self._logger.debug(f"Custom template added: {key}")
                    
        except Exception as e:
            self._logger.warning(f"Failed to load custom templates: {e}")
    
    def _load_fallback_templates(self) -> None:
        """加载硬编码回退模板（填补缺失）"""
        for key, template_data in FALLBACK_TEMPLATES.items():
            if key not in self._task_templates:
                self._task_templates[key] = self._create_template(key, template_data, "fallback")
                self._logger.warning(f"Using fallback template: {key}")
    
    def _load_templates_from_file(
        self,
        file_path: Path,
        target_dict: Dict[str, Template],
        source: str
    ) -> None:
        """从文件加载模板"""
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            
            for key, template_data in data.items():
                target_dict[key] = self._create_template(key, template_data, source)
                
        except json.JSONDecodeError as e:
            self._logger.error(f"JSON parse error in {file_path}: {e}")
        except Exception as e:
            self._logger.error(f"Failed to load templates from {file_path}: {e}")
    
    def _create_template(
        self,
        key: str,
        data: Dict[str, Any],
        source: str
    ) -> Template:
        """创建模板对象"""
        metadata = TemplateMetadata(
            name=data.get("name", key),
            description=data.get("description", ""),
            version=data.get("version", "1.0.0"),
            variables=data.get("variables", []),
            required_variables=data.get("required_variables", []),
        )
        
        return Template(
            key=key,
            metadata=metadata,
            content=data.get("content", ""),
            source=source,
        )
    
    def _merge_template_data(
        self,
        base_template: Template,
        custom_data: Dict[str, Any]
    ) -> Dict[str, Any]:
        """合并用户自定义数据和系统模板"""
        return {
            "name": custom_data.get("name", base_template.metadata.name),
            "description": custom_data.get("description", base_template.metadata.description),
            "version": custom_data.get("version", base_template.metadata.version),
            "variables": custom_data.get("variables", base_template.metadata.variables),
            "required_variables": custom_data.get("required_variables", base_template.metadata.required_variables),
            "content": custom_data.get("content", base_template.content),
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
            variables: 变量字典，用于填充模板占位符
            include_format: 是否自动附加输出格式规范
            
        Returns:
            填充变量后的完整 Prompt 字符串
            
        Raises:
            ValueError: 缺少必需变量时抛出
        """
        variables = variables or {}
        
        # 获取模板
        template = self._task_templates.get(template_name)
        if not template:
            self._logger.error(f"Template not found: {template_name}")
            raise ValueError(f"Template not found: {template_name}")
        
        # 校验必需变量
        validation_result = self.validate_template(template_name, variables)
        if not validation_result["valid"]:
            missing = validation_result["missing_required"]
            self._logger.error(f"Missing required variables for {template_name}: {missing}")
            raise ValueError(f"Missing required variables: {missing}")
        
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
            template_name: 模板名称常量
            
        Returns:
            原始模板内容，不存在时返回 None
        """
        template = self._task_templates.get(template_name)
        return template.content if template else None
    
    def _fill_variables(self, content: str, variables: Dict[str, Any]) -> str:
        """
        填充模板变量
        
        支持的占位符格式：
        - {variable_name} - 简单变量
        - {object.field} - 嵌套变量（点号访问）
        
        Args:
            content: 模板内容
            variables: 变量字典
            
        Returns:
            填充后的内容
        """
        result = content
        
        # 查找所有占位符
        placeholders = re.findall(r'\{([^{}]+)\}', content)
        
        for placeholder in placeholders:
            value = self._get_variable_value(placeholder, variables)
            
            # 将值转换为字符串
            if value is None:
                str_value = ""
            elif isinstance(value, (dict, list)):
                str_value = json.dumps(value, ensure_ascii=False, indent=2)
            else:
                str_value = str(value)
            
            result = result.replace(f"{{{placeholder}}}", str_value)
        
        return result
    
    def _get_variable_value(
        self,
        placeholder: str,
        variables: Dict[str, Any]
    ) -> Any:
        """
        获取变量值，支持嵌套访问
        
        Args:
            placeholder: 占位符名称（可能包含点号）
            variables: 变量字典
            
        Returns:
            变量值，不存在时返回 None
        """
        parts = placeholder.split(".")
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
        """
        获取模板对应的输出格式规范
        
        Args:
            template_name: 任务模板名称
            
        Returns:
            输出格式规范内容，无对应格式时返回 None
        """
        format_name = TEMPLATE_FORMAT_MAPPING.get(template_name)
        if not format_name:
            return None
        
        format_template = self._format_templates.get(format_name)
        if not format_template:
            return None
        
        return format_template.content
    
    # ============================================================
    # 模板校验
    # ============================================================
    
    def validate_template(
        self,
        template_name: str,
        variables: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        校验模板变量完整性
        
        Args:
            template_name: 模板名称
            variables: 提供的变量字典
            
        Returns:
            校验结果字典：
            {
                "valid": bool,
                "missing_required": List[str],
                "missing_optional": List[str],
                "extra_variables": List[str]
            }
        """
        template = self._task_templates.get(template_name)
        if not template:
            return {
                "valid": False,
                "missing_required": [],
                "missing_optional": [],
                "extra_variables": [],
                "error": f"Template not found: {template_name}"
            }
        
        provided_vars = set(variables.keys())
        required_vars = set(template.metadata.required_variables)
        all_vars = set(template.metadata.variables)
        optional_vars = all_vars - required_vars
        
        missing_required = required_vars - provided_vars
        missing_optional = optional_vars - provided_vars
        extra_variables = provided_vars - all_vars
        
        return {
            "valid": len(missing_required) == 0,
            "missing_required": list(missing_required),
            "missing_optional": list(missing_optional),
            "extra_variables": list(extra_variables),
        }
    
    # ============================================================
    # 模板查询
    # ============================================================
    
    def list_templates(self) -> List[str]:
        """
        列出所有可用的任务模板名称
        
        Returns:
            模板名称列表
        """
        return list(self._task_templates.keys())
    
    def list_format_templates(self) -> List[str]:
        """
        列出所有可用的输出格式模板名称
        
        Returns:
            格式模板名称列表
        """
        return list(self._format_templates.keys())
    
    def get_template_metadata(self, template_name: str) -> Optional[TemplateMetadata]:
        """
        获取模板元数据
        
        Args:
            template_name: 模板名称
            
        Returns:
            模板元数据，不存在时返回 None
        """
        template = self._task_templates.get(template_name)
        return template.metadata if template else None
    
    def get_template_source(self, template_name: str) -> Optional[str]:
        """
        获取模板来源
        
        Args:
            template_name: 模板名称
            
        Returns:
            来源标识（"system", "custom", "fallback"），不存在时返回 None
        """
        template = self._task_templates.get(template_name)
        return template.source if template else None
    
    def get_version_info(self) -> Dict[str, Any]:
        """
        获取模板版本信息
        
        Returns:
            版本信息字典
        """
        return self._version_info.copy()

    
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
            metadata: 可选的元数据（name, description, variables 等）
            
        Returns:
            是否注册成功
        """
        try:
            # 构建模板数据
            template_data = metadata.copy() if metadata else {}
            template_data["content"] = content
            
            # 如果是覆盖现有模板，继承元数据
            if name in self._task_templates:
                base_template = self._task_templates[name]
                template_data = self._merge_template_data(base_template, template_data)
            
            # 创建模板对象
            self._task_templates[name] = self._create_template(name, template_data, "custom")
            
            # 保存到用户自定义文件
            self._save_custom_templates()
            
            self._logger.info(f"Custom template registered: {name}")
            return True
            
        except Exception as e:
            self._logger.error(f"Failed to register custom template {name}: {e}")
            return False
    
    def reset_to_default(self, template_name: str) -> bool:
        """
        重置模板为系统默认
        
        Args:
            template_name: 模板名称
            
        Returns:
            是否重置成功
        """
        try:
            # 从系统模板重新加载
            task_file = SYSTEM_PROMPTS_DIR / TASK_PROMPTS_FILE
            if task_file.exists():
                with open(task_file, "r", encoding="utf-8") as f:
                    system_data = json.load(f)
                
                if template_name in system_data:
                    self._task_templates[template_name] = self._create_template(
                        template_name,
                        system_data[template_name],
                        "system"
                    )
                    
                    # 从用户自定义文件中移除
                    self._remove_from_custom_file(template_name)
                    
                    self._logger.info(f"Template reset to default: {template_name}")
                    return True
            
            # 如果系统模板也不存在，使用回退模板
            if template_name in FALLBACK_TEMPLATES:
                self._task_templates[template_name] = self._create_template(
                    template_name,
                    FALLBACK_TEMPLATES[template_name],
                    "fallback"
                )
                self._remove_from_custom_file(template_name)
                self._logger.info(f"Template reset to fallback: {template_name}")
                return True
            
            self._logger.warning(f"No default template found for: {template_name}")
            return False
            
        except Exception as e:
            self._logger.error(f"Failed to reset template {template_name}: {e}")
            return False
    
    def _save_custom_templates(self) -> None:
        """保存用户自定义模板到文件"""
        custom_file = CUSTOM_PROMPTS_DIR / USER_PROMPTS_FILE
        
        # 收集所有自定义模板
        custom_data = {}
        for key, template in self._task_templates.items():
            if template.source == "custom":
                custom_data[key] = {
                    "name": template.metadata.name,
                    "description": template.metadata.description,
                    "version": template.metadata.version,
                    "variables": template.metadata.variables,
                    "required_variables": template.metadata.required_variables,
                    "content": template.content,
                }
        
        try:
            with open(custom_file, "w", encoding="utf-8") as f:
                json.dump(custom_data, f, ensure_ascii=False, indent=2)
            self._logger.debug(f"Custom templates saved: {len(custom_data)} templates")
        except Exception as e:
            self._logger.error(f"Failed to save custom templates: {e}")
    
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
                
                with open(custom_file, "w", encoding="utf-8") as f:
                    json.dump(custom_data, f, ensure_ascii=False, indent=2)
                    
        except Exception as e:
            self._logger.warning(f"Failed to remove template from custom file: {e}")
    
    # ============================================================
    # 热更新
    # ============================================================
    
    def reload_templates(self) -> None:
        """
        重新加载所有模板（支持热更新）
        
        在模板文件被外部修改后调用此方法刷新缓存
        """
        self._logger.info("Reloading templates...")
        self.load_templates()
    
    def check_for_updates(self) -> bool:
        """
        检查内置模板是否有更新
        
        Returns:
            是否有更新可用
        """
        builtin_version = self._read_version_file(BUILTIN_PROMPTS_DIR / VERSION_FILE)
        system_version = self._read_version_file(SYSTEM_PROMPTS_DIR / VERSION_FILE)
        
        if not builtin_version:
            return False
        
        if not system_version:
            return True
        
        return builtin_version.get("version", "0") > system_version.get("version", "0")
    
    def apply_updates(self) -> bool:
        """
        应用内置模板更新
        
        Returns:
            是否成功应用更新
        """
        if not self.check_for_updates():
            self._logger.info("No template updates available")
            return False
        
        try:
            self._copy_template_files()
            self.reload_templates()
            self._logger.info("Template updates applied successfully")
            return True
        except Exception as e:
            self._logger.error(f"Failed to apply template updates: {e}")
            return False


# ============================================================
# 模块导出
# ============================================================

__all__ = [
    "PromptTemplateManager",
    "Template",
    "TemplateMetadata",
    "PROMPTS_DIR",
    "SYSTEM_PROMPTS_DIR",
    "CUSTOM_PROMPTS_DIR",
]
