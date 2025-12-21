# FileReferenceValidator - File Reference Validation
"""
文件引用校验器

职责：
- 提供文件路径有效性校验的统一入口
- 供 UI 层和工作流层调用
- 检测 GraphState 中的悬空指针

设计原则：
- 纯函数式：无状态，仅做路径存在性检查
- 不修改 GraphState：仅返回校验结果，由调用方决定后续处理

使用示例：
    from shared.file_reference_validator import FileReferenceValidator
    
    validator = FileReferenceValidator()
    
    # 校验单个路径
    if not validator.validate_sim_result_path(project_root, sim_result_path):
        # 显示文件缺失占位图
        pass
    
    # 批量校验 GraphState 中的所有路径
    invalid_paths = validator.get_invalid_references(project_root, state)
"""

from pathlib import Path
from typing import Any, Dict, List, Optional, Protocol


class GraphStateLike(Protocol):
    """GraphState 协议，用于类型提示"""
    circuit_file_path: str
    sim_result_path: str
    design_goals_path: str
    project_root: str


class FileReferenceValidator:
    """
    文件引用校验器
    
    提供文件路径有效性校验的统一入口。
    """
    
    def validate_path(self, project_root: str, relative_path: str) -> bool:
        """
        校验单个路径是否有效
        
        Args:
            project_root: 项目根目录路径
            relative_path: 相对路径
            
        Returns:
            bool: 路径是否有效（文件存在）
        """
        if not relative_path:
            return False
        
        if not project_root:
            return False
        
        full_path = Path(project_root) / relative_path
        return full_path.exists()
    
    def validate_sim_result_path(
        self,
        project_root: str,
        sim_result_path: str
    ) -> bool:
        """
        校验仿真结果路径
        
        Args:
            project_root: 项目根目录路径
            sim_result_path: 仿真结果文件相对路径
            
        Returns:
            bool: 路径是否有效
        """
        return self.validate_path(project_root, sim_result_path)
    
    def validate_design_goals_path(
        self,
        project_root: str,
        design_goals_path: str
    ) -> bool:
        """
        校验设计目标路径
        
        Args:
            project_root: 项目根目录路径
            design_goals_path: 设计目标文件相对路径
            
        Returns:
            bool: 路径是否有效
        """
        return self.validate_path(project_root, design_goals_path)
    
    def validate_circuit_file_path(
        self,
        project_root: str,
        circuit_file_path: str
    ) -> bool:
        """
        校验电路文件路径
        
        Args:
            project_root: 项目根目录路径
            circuit_file_path: 电路文件相对路径
            
        Returns:
            bool: 路径是否有效
        """
        return self.validate_path(project_root, circuit_file_path)
    
    def get_invalid_references(
        self,
        project_root: str,
        state: GraphStateLike
    ) -> List[str]:
        """
        批量校验 GraphState 中的所有路径，返回无效路径列表
        
        Args:
            project_root: 项目根目录路径
            state: GraphState 对象
            
        Returns:
            List[str]: 无效路径列表（字段名）
        """
        invalid_fields: List[str] = []
        
        # 校验仿真结果路径（仅当路径非空时校验）
        if state.sim_result_path:
            if not self.validate_sim_result_path(project_root, state.sim_result_path):
                invalid_fields.append("sim_result_path")
        
        # 校验设计目标路径（仅当路径非空时校验）
        if state.design_goals_path:
            if not self.validate_design_goals_path(project_root, state.design_goals_path):
                invalid_fields.append("design_goals_path")
        
        # 校验电路文件路径（仅当路径非空时校验）
        if state.circuit_file_path:
            if not self.validate_circuit_file_path(project_root, state.circuit_file_path):
                invalid_fields.append("circuit_file_path")
        
        return invalid_fields
    
    def get_invalid_references_from_dict(
        self,
        project_root: str,
        state_dict: Dict[str, Any]
    ) -> List[str]:
        """
        从字典格式的状态中批量校验路径
        
        Args:
            project_root: 项目根目录路径
            state_dict: GraphState 字典
            
        Returns:
            List[str]: 无效路径列表（字段名）
        """
        invalid_fields: List[str] = []
        
        sim_result_path = state_dict.get("sim_result_path", "")
        if sim_result_path and not self.validate_sim_result_path(project_root, sim_result_path):
            invalid_fields.append("sim_result_path")
        
        design_goals_path = state_dict.get("design_goals_path", "")
        if design_goals_path and not self.validate_design_goals_path(project_root, design_goals_path):
            invalid_fields.append("design_goals_path")
        
        circuit_file_path = state_dict.get("circuit_file_path", "")
        if circuit_file_path and not self.validate_circuit_file_path(project_root, circuit_file_path):
            invalid_fields.append("circuit_file_path")
        
        return invalid_fields


# 模块级单例，便于直接导入使用
file_reference_validator = FileReferenceValidator()


# ============================================================
# 模块导出
# ============================================================

__all__ = [
    "FileReferenceValidator",
    "file_reference_validator",
]
