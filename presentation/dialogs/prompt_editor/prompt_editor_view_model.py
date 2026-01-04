# Prompt Editor ViewModel
"""
Prompt 编辑器 ViewModel - 管理编辑状态和业务逻辑

职责：
- 管理编辑状态（dirty 标记）
- 暂存修改内容（内存中）
- 协调保存/重置操作
- 与 PromptTemplateManager 交互

设计原则：
- 采用"编辑时暂存，确认时持久化"策略
- 所有模板修改先存入内存，用户确认后才写入文件
"""

import logging
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set

from PyQt6.QtCore import QObject, pyqtSignal


@dataclass
class TemplateEditState:
    """单个模板的编辑状态"""
    key: str
    original_content: str
    current_content: str
    name: str
    description: str
    variables: List[str] = field(default_factory=list)
    required_variables: List[str] = field(default_factory=list)
    source: str = "builtin"  # builtin, custom, fallback
    
    @property
    def is_dirty(self) -> bool:
        """是否有未保存的修改"""
        return self.current_content != self.original_content


class PromptEditorViewModel(QObject):
    """
    Prompt 编辑器 ViewModel
    
    Signals:
        template_list_changed: 模板列表变化
        template_selected(str): 选中模板变化
        dirty_state_changed(str, bool): 模板脏状态变化 (key, is_dirty)
        save_completed(bool, str): 保存完成 (success, message)
        reset_completed(str): 重置完成 (template_key)
    """
    
    template_list_changed = pyqtSignal()
    template_selected = pyqtSignal(str)
    dirty_state_changed = pyqtSignal(str, bool)
    save_completed = pyqtSignal(bool, str)
    reset_completed = pyqtSignal(str)
    
    def __init__(self, parent: Optional[QObject] = None):
        super().__init__(parent)
        self._logger = logging.getLogger(__name__)
        
        # 模板管理器引用
        self._template_manager = None
        
        # 编辑状态缓存
        self._edit_states: Dict[str, TemplateEditState] = {}
        
        # 当前选中的模板
        self._current_key: Optional[str] = None
        
        # 已修改的模板集合
        self._dirty_keys: Set[str] = set()
    
    def initialize(self) -> bool:
        """
        初始化 ViewModel，加载模板数据
        
        Returns:
            是否初始化成功
        """
        try:
            from shared.service_locator import ServiceLocator
            from shared.service_names import SVC_PROMPT_TEMPLATE_MANAGER
            
            self._template_manager = ServiceLocator.get_optional(SVC_PROMPT_TEMPLATE_MANAGER)
            if not self._template_manager:
                # 直接创建实例
                from domain.llm.prompt_template_manager import PromptTemplateManager
                self._template_manager = PromptTemplateManager()
            
            self._load_templates()
            return True
        except Exception as e:
            self._logger.error(f"初始化 ViewModel 失败: {e}")
            return False
    
    def _load_templates(self) -> None:
        """从 PromptTemplateManager 加载所有模板"""
        self._edit_states.clear()
        self._dirty_keys.clear()
        
        if not self._template_manager:
            return
        
        all_templates = self._template_manager.get_all_templates()
        for key, template in all_templates.items():
            self._edit_states[key] = TemplateEditState(
                key=key,
                original_content=template.content,
                current_content=template.content,
                name=template.metadata.name,
                description=template.metadata.description,
                variables=list(template.metadata.variables),
                required_variables=list(template.metadata.required_variables),
                source=template.source,
            )
        
        self.template_list_changed.emit()
    
    # ============================================================
    # 模板列表操作
    # ============================================================
    
    def get_template_list(self) -> List[Dict[str, str]]:
        """
        获取模板列表（用于 UI 显示）
        
        Returns:
            模板信息列表，每项包含 key, name, source, is_dirty
        """
        result = []
        for key, state in self._edit_states.items():
            result.append({
                "key": key,
                "name": state.name,
                "source": state.source,
                "is_dirty": state.is_dirty,
            })
        # 按名称排序
        result.sort(key=lambda x: x["name"])
        return result
    
    def select_template(self, key: str) -> bool:
        """
        选中模板
        
        Args:
            key: 模板键名
            
        Returns:
            是否选中成功
        """
        if key not in self._edit_states:
            return False
        
        self._current_key = key
        self.template_selected.emit(key)
        return True
    
    def get_current_template(self) -> Optional[TemplateEditState]:
        """获取当前选中的模板状态"""
        if self._current_key:
            return self._edit_states.get(self._current_key)
        return None
    
    def get_template_state(self, key: str) -> Optional[TemplateEditState]:
        """获取指定模板的状态"""
        return self._edit_states.get(key)
    
    # ============================================================
    # 编辑操作
    # ============================================================
    
    def update_content(self, key: str, content: str) -> None:
        """
        更新模板内容（暂存到内存）
        
        Args:
            key: 模板键名
            content: 新内容
        """
        state = self._edit_states.get(key)
        if not state:
            return
        
        old_dirty = state.is_dirty
        state.current_content = content
        new_dirty = state.is_dirty
        
        # 更新脏状态集合
        if new_dirty:
            self._dirty_keys.add(key)
        else:
            self._dirty_keys.discard(key)
        
        # 通知脏状态变化
        if old_dirty != new_dirty:
            self.dirty_state_changed.emit(key, new_dirty)
    
    def has_unsaved_changes(self) -> bool:
        """是否有未保存的修改"""
        return len(self._dirty_keys) > 0
    
    def get_dirty_templates(self) -> List[str]:
        """获取所有有修改的模板键名"""
        return list(self._dirty_keys)
    
    # ============================================================
    # 保存/重置操作
    # ============================================================
    
    def save_template(self, key: str) -> bool:
        """
        保存单个模板
        
        Args:
            key: 模板键名
            
        Returns:
            是否保存成功
        """
        state = self._edit_states.get(key)
        if not state or not self._template_manager:
            return False
        
        if not state.is_dirty:
            return True  # 无需保存
        
        try:
            success = self._template_manager.register_custom_template(
                name=key,
                content=state.current_content,
                metadata={
                    "name": state.name,
                    "description": state.description,
                    "variables": state.variables,
                    "required_variables": state.required_variables,
                }
            )
            
            if success:
                state.original_content = state.current_content
                state.source = "custom"
                self._dirty_keys.discard(key)
                self.dirty_state_changed.emit(key, False)
                self.save_completed.emit(True, key)
                self._logger.info(f"模板已保存: {key}")
            
            return success
        except Exception as e:
            self._logger.error(f"保存模板失败 {key}: {e}")
            self.save_completed.emit(False, str(e))
            return False
    
    def save_all(self) -> bool:
        """
        保存所有修改的模板
        
        Returns:
            是否全部保存成功
        """
        if not self._dirty_keys:
            return True
        
        all_success = True
        for key in list(self._dirty_keys):
            if not self.save_template(key):
                all_success = False
        
        return all_success
    
    def reset_template(self, key: str) -> bool:
        """
        重置模板为内置默认
        
        Args:
            key: 模板键名
            
        Returns:
            是否重置成功
        """
        if not self._template_manager:
            return False
        
        try:
            success = self._template_manager.reset_to_default(key)
            if success:
                # 重新加载该模板
                template = self._template_manager.get_all_templates().get(key)
                if template:
                    self._edit_states[key] = TemplateEditState(
                        key=key,
                        original_content=template.content,
                        current_content=template.content,
                        name=template.metadata.name,
                        description=template.metadata.description,
                        variables=list(template.metadata.variables),
                        required_variables=list(template.metadata.required_variables),
                        source=template.source,
                    )
                    self._dirty_keys.discard(key)
                    self.dirty_state_changed.emit(key, False)
                    self.reset_completed.emit(key)
                    self._logger.info(f"模板已重置: {key}")
            
            return success
        except Exception as e:
            self._logger.error(f"重置模板失败 {key}: {e}")
            return False
    
    def discard_changes(self, key: str) -> None:
        """
        放弃对模板的修改
        
        Args:
            key: 模板键名
        """
        state = self._edit_states.get(key)
        if state:
            state.current_content = state.original_content
            self._dirty_keys.discard(key)
            self.dirty_state_changed.emit(key, False)
    
    def discard_all_changes(self) -> None:
        """放弃所有修改"""
        for key in list(self._dirty_keys):
            self.discard_changes(key)
    
    # ============================================================
    # 变量操作
    # ============================================================
    
    def get_template_variables(self, key: str) -> List[str]:
        """获取模板的变量列表"""
        state = self._edit_states.get(key)
        return state.variables if state else []
    
    def get_required_variables(self, key: str) -> List[str]:
        """获取模板的必需变量列表"""
        state = self._edit_states.get(key)
        return state.required_variables if state else []


__all__ = [
    "PromptEditorViewModel",
    "TemplateEditState",
]
