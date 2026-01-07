# Tuning Service - Quick Parameter Tuning Service
"""
快速调参服务

职责：
- 应用参数修改到电路文件
- 执行调参仿真
- 管理文件备份和恢复

设计说明：
- 参数提取功能由 parameter_extractor.py 实现
- 本服务专注于调参仿真的执行流程

工作流程：
1. 备份原始文件到 .circuit_ai/temp/{filename}.bak
2. 解析文件内容，定位参数所在行
3. 替换参数值，保持原有格式
4. 写入修改后的文件
5. 调用 SimulationService.run_simulation() 执行仿真
6. 可选：恢复原始文件

被调用方：
- TuningPanel（UI）
- SimulationService
"""

import logging
import re
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

from domain.simulation.service.parameter_extractor import (
    ParameterExtractor,
    ParameterType,
    TunableParameter,
    parameter_extractor,
)

_logger = logging.getLogger(__name__)


@dataclass
class TuningApplyResult:
    """
    参数应用结果
    
    Attributes:
        success: 是否成功
        modified_lines: 修改的行号列表
        backup_path: 备份文件路径
        error_message: 错误信息
        changes_applied: 实际应用的参数变更
    """
    success: bool = True
    modified_lines: List[int] = field(default_factory=list)
    backup_path: str = ""
    error_message: str = ""
    changes_applied: Dict[str, float] = field(default_factory=dict)



class TuningService:
    """
    快速调参服务
    
    提供调参仿真功能，支持参数修改、仿真执行和文件恢复。
    """
    
    # 备份目录（相对于项目根目录）
    BACKUP_DIR = ".circuit_ai/temp"
    
    # .param 语句替换模式
    PARAM_PATTERN = re.compile(
        r'^(\s*\.param\s+)(\w+)(\s*=\s*)([+-]?[\d.]+(?:[eE][+-]?\d+)?)(\s*\w*)',
        re.IGNORECASE
    )
    
    # 元件值替换模式（R/C/L/V/I）
    ELEMENT_PATTERN = re.compile(
        r'^(\s*[RCLVI]\w*\s+\S+\s+\S+\s+)([+-]?[\d.]+(?:[eE][+-]?\d+)?)(\s*\w*)',
        re.IGNORECASE
    )
    
    def __init__(
        self,
        extractor: Optional[ParameterExtractor] = None,
    ):
        """
        初始化调参服务
        
        Args:
            extractor: 参数提取器（可选，默认使用全局单例）
        """
        self._logger = _logger
        self._extractor = extractor or parameter_extractor
        self._event_bus = None
    
    def _get_event_bus(self):
        """获取事件总线"""
        if self._event_bus is None:
            try:
                from shared.service_locator import ServiceLocator
                from shared.service_names import SERVICE_EVENT_BUS
                self._event_bus = ServiceLocator.get(SERVICE_EVENT_BUS)
            except Exception:
                pass
        return self._event_bus
    
    def get_backup_path(self, file_path: str, project_root: str = "") -> Path:
        """
        获取备份文件路径
        
        Args:
            file_path: 原始文件路径
            project_root: 项目根目录（可选）
            
        Returns:
            Path: 备份文件路径
        """
        original = Path(file_path)
        
        if project_root:
            root = Path(project_root)
        else:
            root = original.parent
        
        backup_dir = root / self.BACKUP_DIR
        backup_name = f"{original.stem}.bak"
        return backup_dir / backup_name
    
    def apply_parameter_changes(
        self,
        file_path: str,
        changes: Dict[str, float],
        project_root: str = "",
    ) -> TuningApplyResult:
        """
        应用参数修改到电路文件
        
        Args:
            file_path: 电路文件路径
            changes: 参数变更字典 {param_name: new_value}
            project_root: 项目根目录（用于备份）
            
        Returns:
            TuningApplyResult: 应用结果
        """
        if not changes:
            return TuningApplyResult(
                success=True,
                error_message="无参数变更"
            )
        
        original_path = Path(file_path)
        
        if not original_path.exists():
            return TuningApplyResult(
                success=False,
                error_message=f"文件不存在: {file_path}"
            )
        
        try:
            # 1. 创建备份
            backup_path = self.get_backup_path(file_path, project_root)
            backup_path.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(original_path, backup_path)
            
            # 2. 读取文件内容
            content = original_path.read_text(encoding='utf-8', errors='ignore')
            lines = content.splitlines()
            
            # 3. 提取参数信息（用于定位）
            extraction_result = self._extractor.extract_from_content(content, file_path)
            param_map = {p.name: p for p in extraction_result.parameters}
            
            # 4. 应用修改
            modified_lines = []
            changes_applied = {}
            
            for param_name, new_value in changes.items():
                param_info = param_map.get(param_name)
                if param_info is None:
                    self._logger.warning(f"参数未找到: {param_name}")
                    continue
                
                line_idx = param_info.line_number - 1
                if line_idx < 0 or line_idx >= len(lines):
                    self._logger.warning(f"行号无效: {param_info.line_number}")
                    continue
                
                original_line = lines[line_idx]
                new_line = self._replace_value_in_line(
                    original_line,
                    param_info,
                    new_value
                )
                
                if new_line != original_line:
                    lines[line_idx] = new_line
                    modified_lines.append(param_info.line_number)
                    changes_applied[param_name] = new_value
                    self._logger.debug(
                        f"修改行 {param_info.line_number}: "
                        f"{original_line.strip()} -> {new_line.strip()}"
                    )
            
            # 5. 写入修改后的文件
            new_content = '\n'.join(lines)
            if content.endswith('\n'):
                new_content += '\n'
            original_path.write_text(new_content, encoding='utf-8')
            
            # 6. 发布事件
            self._publish_applied_event(
                file_path, changes_applied, modified_lines, str(backup_path)
            )
            
            self._logger.info(
                f"参数修改已应用: {len(changes_applied)} 个参数, "
                f"{len(modified_lines)} 行修改"
            )
            
            return TuningApplyResult(
                success=True,
                modified_lines=modified_lines,
                backup_path=str(backup_path),
                changes_applied=changes_applied
            )
            
        except Exception as e:
            self._logger.exception(f"应用参数修改失败: {e}")
            return TuningApplyResult(
                success=False,
                error_message=str(e)
            )
    
    def _replace_value_in_line(
        self,
        line: str,
        param_info: TunableParameter,
        new_value: float,
    ) -> str:
        """
        替换行中的参数值
        
        Args:
            line: 原始行内容
            param_info: 参数信息
            new_value: 新值
            
        Returns:
            str: 修改后的行内容
        """
        if param_info.param_type == ParameterType.PARAM:
            return self._replace_param_value(line, param_info.name, new_value)
        else:
            return self._replace_element_value(line, new_value)
    
    def _replace_param_value(
        self,
        line: str,
        param_name: str,
        new_value: float,
    ) -> str:
        """替换 .param 语句中的值"""
        def replacer(match):
            prefix = match.group(1)
            name = match.group(2)
            equals = match.group(3)
            suffix = match.group(5)
            
            if name.lower() == param_name.lower():
                formatted = self._format_value(new_value)
                return f"{prefix}{name}{equals}{formatted}{suffix}"
            return match.group(0)
        
        return self.PARAM_PATTERN.sub(replacer, line)
    
    def _replace_element_value(
        self,
        line: str,
        new_value: float,
    ) -> str:
        """替换元件值"""
        def replacer(match):
            prefix = match.group(1)
            suffix = match.group(3)
            formatted = self._format_value(new_value)
            return f"{prefix}{formatted}{suffix}"
        
        return self.ELEMENT_PATTERN.sub(replacer, line)
    
    def _format_value(self, value: float) -> str:
        """
        格式化数值
        
        保持合理的精度，避免科学计数法（除非必要）
        """
        abs_val = abs(value)
        
        if abs_val == 0:
            return "0"
        elif abs_val >= 1e9:
            return f"{value/1e9:.6g}G"
        elif abs_val >= 1e6:
            return f"{value/1e6:.6g}Meg"
        elif abs_val >= 1e3:
            return f"{value/1e3:.6g}k"
        elif abs_val >= 1:
            return f"{value:.6g}"
        elif abs_val >= 1e-3:
            return f"{value*1e3:.6g}m"
        elif abs_val >= 1e-6:
            return f"{value*1e6:.6g}u"
        elif abs_val >= 1e-9:
            return f"{value*1e9:.6g}n"
        elif abs_val >= 1e-12:
            return f"{value*1e12:.6g}p"
        else:
            return f"{value:.6e}"
    
    def restore_original(
        self,
        file_path: str,
        project_root: str = "",
    ) -> bool:
        """
        恢复原始文件
        
        Args:
            file_path: 电路文件路径
            project_root: 项目根目录
            
        Returns:
            bool: 是否恢复成功
        """
        backup_path = self.get_backup_path(file_path, project_root)
        original_path = Path(file_path)
        
        if not backup_path.exists():
            self._logger.warning(f"备份文件不存在: {backup_path}")
            return False
        
        try:
            shutil.copy2(backup_path, original_path)
            
            # 发布事件
            self._publish_restored_event(file_path, str(backup_path))
            
            self._logger.info(f"文件已恢复: {file_path}")
            return True
            
        except Exception as e:
            self._logger.exception(f"恢复文件失败: {e}")
            return False
    
    def run_tuning_simulation(
        self,
        file_path: str,
        changes: Dict[str, float],
        project_root: str,
        analysis_config: Optional[Dict[str, Any]] = None,
        *,
        version: int = 1,
        session_id: str = "",
        restore_after: bool = False,
    ):
        """
        执行调参仿真
        
        流程：
        1. 应用参数修改
        2. 执行仿真
        3. 可选：恢复原始文件
        
        Args:
            file_path: 电路文件路径
            changes: 参数变更字典
            project_root: 项目根目录
            analysis_config: 仿真配置
            version: 版本号
            session_id: 会话 ID
            restore_after: 仿真后是否恢复原始文件
            
        Returns:
            SimulationResult: 仿真结果
        """
        from domain.services.simulation_service import SimulationService
        from domain.simulation.models.simulation_result import create_error_result
        from domain.simulation.models.simulation_error import (
            SimulationError,
            SimulationErrorType,
            ErrorSeverity,
        )
        
        # 1. 应用参数修改
        apply_result = self.apply_parameter_changes(
            file_path, changes, project_root
        )
        
        if not apply_result.success:
            error = SimulationError(
                code="E020",
                type=SimulationErrorType.PARAMETER_INVALID,
                severity=ErrorSeverity.HIGH,
                message=f"参数应用失败: {apply_result.error_message}",
                file_path=file_path,
            )
            return create_error_result(
                executor="tuning",
                file_path=file_path,
                analysis_type=analysis_config.get("analysis_type", "ac") if analysis_config else "ac",
                error=error,
                version=version,
                session_id=session_id,
            )
        
        try:
            # 2. 执行仿真
            service = SimulationService()
            result = service.run_simulation(
                file_path=file_path,
                analysis_config=analysis_config,
                project_root=project_root,
                version=version,
                session_id=session_id,
            )
            
            return result
            
        finally:
            # 3. 可选：恢复原始文件
            if restore_after:
                self.restore_original(file_path, project_root)
    
    def _publish_applied_event(
        self,
        file_path: str,
        changes: Dict[str, float],
        modified_lines: List[int],
        backup_path: str,
    ) -> None:
        """发布参数应用事件"""
        bus = self._get_event_bus()
        if bus:
            from shared.event_types import EVENT_TUNING_APPLIED
            bus.publish(EVENT_TUNING_APPLIED, {
                "file_path": file_path,
                "changes": changes,
                "modified_lines": modified_lines,
                "backup_path": backup_path,
            })
    
    def _publish_restored_event(
        self,
        file_path: str,
        backup_path: str,
    ) -> None:
        """发布文件恢复事件"""
        bus = self._get_event_bus()
        if bus:
            from shared.event_types import EVENT_TUNING_RESTORED
            bus.publish(EVENT_TUNING_RESTORED, {
                "file_path": file_path,
                "backup_path": backup_path,
            })


# 模块级单例
tuning_service = TuningService()


__all__ = [
    "TuningService",
    "TuningApplyResult",
    "tuning_service",
]
