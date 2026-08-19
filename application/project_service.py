# Project Service - Project Management
"""
项目管理服务

职责：
- 管理工作文件夹的初始化和状态
- 确保项目环境就绪
- 管理最近打开的项目列表

初始化顺序：
- 阶段二启动时初始化
- 依赖 FileManager、SessionStateProjector、EventBus
- 注册到 ServiceLocator

当前状态边界：
- 本服务是打开/关闭项目路径与状态转换的权威入口
- FileManager/FileWatchTask 跟随项目路径
- SessionStateProjector 把项目状态写入 SessionState 供 UI 读取
- RAG、搜索和各 UI 面板通过项目生命周期事件维护各自状态

使用示例：
    from shared.service_locator import ServiceLocator
    from shared.service_names import SVC_PROJECT_SERVICE
    
    project_service = ServiceLocator.get(SVC_PROJECT_SERVICE)
    
    # 初始化项目
    result = project_service.initialize_project("/path/to/project")
    
    # 关闭项目
    project_service.close_project()
    
    # 切换项目
    project_service.switch_project("/path/to/new/project")
"""

import os
import shutil
import time
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from infrastructure.config.settings import (
    GLOBAL_CONFIG_DIR,
    WORK_FOLDER_HIDDEN_DIR,
)


# ============================================================
# 常量定义
# ============================================================

# 最近项目列表文件
RECENT_PROJECTS_FILE = "recent_projects.json"

# 最大最近项目数量
MAX_RECENT_PROJECTS = 10

# 最小磁盘空间要求（MB）
MIN_DISK_SPACE_MB = 100

# 项目隐藏目录结构
# 仿真结果已迁出 ``.circuit_ai/``，改由权威单树
# ``<project_root>/simulation_results/<stem>/<ts>/`` 承载；
# 这里不再为 ``sim_results`` 预建空目录。
HIDDEN_DIR_STRUCTURE = [
    "snapshots",      # 全量快照目录
    "conversations",  # 会话数据目录
    "bom_reports",    # BOM 报告目录
    "diffs",          # Diff 文件目录
    "datasheets",     # 元器件数据手册目录
]

# 初始化创建的 JSON 文件
INIT_JSON_FILES = {}


# ============================================================
# 项目状态枚举
# ============================================================

class ProjectStatus(Enum):
    """项目状态"""
    NOT_OPENED = "not_opened"       # 未打开项目
    INITIALIZING = "initializing"   # 正在初始化
    READY = "ready"                 # 就绪
    DEGRADED = "degraded"           # 降级模式（部分功能不可用）
    ERROR = "error"                 # 错误状态


# ============================================================
# 项目信息数据类
# ============================================================

@dataclass
class ProjectInfo:
    """项目信息"""
    path: str
    name: str
    status: ProjectStatus
    disk_space_mb: float
    is_degraded: bool
    degraded_reason: Optional[str]


# ============================================================
# 项目服务主类
# ============================================================

class ProjectService:
    """
    项目管理服务
    
    管理工作文件夹的初始化、关闭和切换
    """
    
    def __init__(self):
        """初始化项目服务"""
        # 当前项目路径
        self._current_project_path: Optional[Path] = None
        
        # 项目状态
        self._status: ProjectStatus = ProjectStatus.NOT_OPENED
        
        # 降级原因
        self._degraded_reason: Optional[str] = None
        
        # 延迟获取的服务
        self._file_manager = None
        self._session_state_projector = None
        self._event_bus = None
        self._file_watcher = None
        self._session_state_manager = None
        self._logger = None
    
    # ============================================================
    # 延迟获取服务（避免循环依赖）
    # ============================================================
    
    @property
    def file_manager(self):
        """延迟获取文件管理器"""
        if self._file_manager is None:
            try:
                from shared.service_locator import ServiceLocator
                from shared.service_names import SVC_FILE_MANAGER
                self._file_manager = ServiceLocator.get_optional(SVC_FILE_MANAGER)
            except Exception:
                pass
        return self._file_manager
    
    @property
    def session_state_projector(self):
        """延迟获取项目/RAG 状态投影器"""
        if self._session_state_projector is None:
            try:
                from shared.service_locator import ServiceLocator
                from shared.service_names import SVC_SESSION_STATE_PROJECTOR
                self._session_state_projector = ServiceLocator.get_optional(
                    SVC_SESSION_STATE_PROJECTOR
                )
            except Exception:
                pass
        return self._session_state_projector
    
    @property
    def event_bus(self):
        """延迟获取事件总线"""
        if self._event_bus is None:
            try:
                from shared.service_locator import ServiceLocator
                from shared.service_names import SVC_EVENT_BUS
                self._event_bus = ServiceLocator.get_optional(SVC_EVENT_BUS)
            except Exception:
                pass
        return self._event_bus
    
    @property
    def file_watcher(self):
        """延迟获取文件监听服务"""
        if self._file_watcher is None:
            try:
                from shared.service_locator import ServiceLocator
                from shared.service_names import SVC_FILE_WATCHER
                self._file_watcher = ServiceLocator.get_optional(SVC_FILE_WATCHER)
            except Exception:
                pass
        return self._file_watcher

    @property
    def session_state_manager(self):
        """Return the authoritative conversation-session coordinator."""
        if self._session_state_manager is None:
            try:
                from shared.service_locator import ServiceLocator
                from shared.service_names import SVC_SESSION_STATE_MANAGER

                self._session_state_manager = ServiceLocator.get_optional(
                    SVC_SESSION_STATE_MANAGER
                )
            except Exception:
                pass
        return self._session_state_manager
    
    @property
    def logger(self):
        """延迟获取日志器"""
        if self._logger is None:
            try:
                from infrastructure.utils.logger import get_logger
                self._logger = get_logger("project_service")
            except Exception:
                pass
        return self._logger


    # ============================================================
    # 核心功能
    # ============================================================
    
    def initialize_project(self, folder_path: str) -> Tuple[bool, str]:
        """
        初始化工作文件夹
        
        项目状态隔离原则：
        - 每个工作文件夹拥有独立的状态存储（.circuit_ai/ 目录）
        - 切换项目时，旧项目的所有状态不会带入新项目
        - 每个工作文件夹使用独立的 .circuit_ai 数据目录
        
        执行流程：
        1. 校验文件夹有效性与权限
        2. 检查磁盘空间
        3. 创建或验证 .circuit_ai/ 目录结构
        4. 幂等初始化项目 JSON 文件
        5. 设置 FileManager 工作目录并启动文件监听
        6. 通过 SessionStateProjector 更新 SessionState
        7. 发布 EVENT_STATE_PROJECT_OPENED 事件
        8. 各项目级服务和 UI 面板订阅事件后刷新
        
        Args:
            folder_path: 工作文件夹路径
            
        Returns:
            Tuple[bool, str]: (是否成功, 消息)
        """
        self._status = ProjectStatus.INITIALIZING
        self._degraded_reason = None
        
        try:
            path = Path(folder_path).resolve()
            
            # 1. 校验文件夹有效性
            valid, msg = self.validate_folder(str(path))
            if not valid:
                self._status = ProjectStatus.ERROR
                return False, msg
            
            # 2. 检查磁盘空间
            has_space, space_msg = self.check_disk_space(MIN_DISK_SPACE_MB, str(path))
            if not has_space:
                self._status = ProjectStatus.ERROR
                return False, space_msg
            
            # 3. 创建隐藏目录结构
            success, create_msg = self.create_hidden_structure(str(path))
            if not success:
                # 降级模式：继续运行但记录警告
                self._degraded_reason = create_msg
                if self.logger:
                    self.logger.warning(f"项目初始化降级: {create_msg}")
            
            if self.logger:
                self.logger.info(f"打开项目: {path}")
            
            # 初始化缺失的 JSON 文件；已存在的文件不会被覆盖。
            self._init_json_files(path)
            
            # 8. 设置 FileManager 工作目录
            if self.file_manager:
                self.file_manager.set_work_dir(path)
            
            # 8.1 启动文件监听
            if self.file_watcher:
                self.file_watcher.start_watching(str(path))
            
            # 9. 将项目状态投影到 SessionState
            if self.session_state_projector:
                self.session_state_projector.update_project_state(str(path))
            
            # 更新当前项目路径
            self._current_project_path = path
            
            # 添加到最近打开列表
            self.add_to_recent(str(path))
            
            # 设置状态
            if self._degraded_reason:
                self._status = ProjectStatus.DEGRADED
            else:
                self._status = ProjectStatus.READY
            
            # 12. 发布项目打开事件（携带完整的项目状态信息）
            if self.event_bus:
                from shared.event_types import EVENT_STATE_PROJECT_OPENED
                self.event_bus.publish(EVENT_STATE_PROJECT_OPENED, {
                    "path": str(path),
                    "name": path.name,
                    "status": self._status.value,
                    "degraded": self._degraded_reason is not None,
                })
            
            if self.logger:
                self.logger.info(f"项目初始化完成: {path}")
            
            status_msg = "项目初始化成功"
            if self._degraded_reason:
                status_msg += f"（降级模式: {self._degraded_reason}）"
            
            return True, status_msg
            
        except Exception as e:
            self._status = ProjectStatus.ERROR
            error_msg = f"项目初始化失败: {e}"
            if self.logger:
                self.logger.error(error_msg)
            return False, error_msg
    
    def close_project(self) -> Tuple[bool, str]:
        """
        关闭当前项目并清理状态
        
        项目状态隔离原则：
        - 关闭项目时，所有项目相关状态必须完全清理
        - 确保下一个项目不会继承任何旧状态
        
        执行流程：
        1. 停止文件监听
        2. 通过 SessionStateProjector 清空 SessionState 中的项目相关字段
        3. 清空各面板显示内容（文件浏览器、代码编辑器、对话面板、仿真结果面板）
           - 通过发布 EVENT_STATE_PROJECT_CLOSED 事件，各面板订阅后自行清理
        4. 发布 EVENT_STATE_PROJECT_CLOSED 事件
        5. 更新状态栏显示"未打开项目"
        
        Returns:
            Tuple[bool, str]: (是否成功, 消息)
        """
        if self._status == ProjectStatus.NOT_OPENED:
            return True, "没有打开的项目"
        
        try:
            old_path = self._current_project_path

            # Conversation persistence is the first, authoritative preflight.
            # Nothing below this point is reversible as one unit (watcher stop,
            # graph clear, work-dir reset and close-event publication), so a
            # failed save must leave the whole project lifecycle untouched.
            session_manager = self.session_state_manager
            if session_manager is None:
                return False, "关闭项目失败: 会话状态管理器不可用"
            try:
                persisted = session_manager.ensure_current_session_persisted(
                    str(old_path) if old_path else None
                )
            except Exception as exc:
                return False, f"关闭项目失败: 当前会话保存失败: {exc}"
            if not persisted:
                return False, "关闭项目失败: 当前会话未能保存"
            
            # 1. 停止文件监听
            if self.file_watcher:
                self.file_watcher.stop_watching()
                if self.logger:
                    self.logger.debug("已停止文件监听")
            
            # 2. 清空投影状态
            if self.session_state_projector:
                self.session_state_projector.clear_project_state()
            
            # 3. 重置 FileManager 工作目录
            if self.file_manager:
                self.file_manager.set_work_dir(None)
            
            # 4. 发布项目关闭事件
            # 各 UI 面板订阅此事件后清空显示内容：
            # - 文件浏览器：清空文件树
            # - 代码编辑器：关闭所有打开的文件
            # - 对话面板：清空对话历史
            # - 仿真结果面板：清空图表和数据
            if self.event_bus:
                from shared.event_types import EVENT_STATE_PROJECT_CLOSED
                self.event_bus.publish(EVENT_STATE_PROJECT_CLOSED, {
                    "path": str(old_path) if old_path else None,
                })
            
            # 5. 重置内部状态
            self._current_project_path = None
            self._status = ProjectStatus.NOT_OPENED
            self._degraded_reason = None
            
            if self.logger:
                self.logger.info(f"项目已关闭: {old_path}")
            
            return True, "项目已关闭"
            
        except Exception as e:
            error_msg = f"关闭项目失败: {e}"
            if self.logger:
                self.logger.error(error_msg)
            return False, error_msg
    
    def switch_project(self, new_folder_path: str) -> Tuple[bool, str]:
        """
        切换到新的工作文件夹
        
        执行流程：
        1. 调用 close_project() 清理当前状态
        2. 调用 initialize_project() 初始化新项目
        3. 若新项目初始化失败，保持"未打开项目"状态
        
        Args:
            new_folder_path: 新的工作文件夹路径
            
        Returns:
            Tuple[bool, str]: (是否成功, 消息)
        """
        # 1. 关闭当前项目
        close_success, close_msg = self.close_project()
        if not close_success:
            if self.logger:
                self.logger.warning(f"关闭当前项目失败，取消切换: {close_msg}")
            # Closing the old project is the commit boundary for a switch.
            # Never initialise the new project over partially-cleared state.
            return False, f"切换项目失败: {close_msg}"
        
        # 2. 初始化新项目
        init_success, init_msg = self.initialize_project(new_folder_path)
        
        if not init_success:
            # 保持"未打开项目"状态
            self._status = ProjectStatus.NOT_OPENED
            return False, f"切换项目失败: {init_msg}"
        
        return True, f"已切换到项目: {new_folder_path}"


    # ============================================================
    # 校验与检查
    # ============================================================
    
    def validate_folder(self, folder_path: str) -> Tuple[bool, str]:
        """
        校验文件夹有效性与权限
        
        Args:
            folder_path: 文件夹路径
            
        Returns:
            Tuple[bool, str]: (是否有效, 消息)
        """
        try:
            path = Path(folder_path).resolve()
            
            # 检查路径是否存在
            if not path.exists():
                # 尝试创建目录
                try:
                    path.mkdir(parents=True, exist_ok=True)
                    if self.logger:
                        self.logger.info(f"创建工作目录: {path}")
                except Exception as e:
                    return False, f"无法创建目录: {e}"
            
            # 检查是否为目录
            if not path.is_dir():
                return False, f"路径不是目录: {path}"
            
            # 检查读权限
            if not os.access(path, os.R_OK):
                return False, f"没有读取权限: {path}"
            
            # 检查写权限
            if not os.access(path, os.W_OK):
                return False, f"没有写入权限: {path}"
            
            # 尝试创建测试文件验证写入能力
            test_file = path / ".write_test"
            try:
                test_file.write_text("test")
                test_file.unlink()
            except Exception as e:
                return False, f"无法写入文件: {e}"
            
            return True, "文件夹有效"
            
        except Exception as e:
            return False, f"校验失败: {e}"
    
    def check_disk_space(
        self,
        required_mb: float,
        folder_path: str = None
    ) -> Tuple[bool, str]:
        """
        检查磁盘空间
        
        Args:
            required_mb: 需要的空间（MB）
            folder_path: 检查的路径，默认使用当前项目路径
            
        Returns:
            Tuple[bool, str]: (是否足够, 消息)
        """
        try:
            if folder_path:
                path = Path(folder_path)
            elif self._current_project_path:
                path = self._current_project_path
            else:
                return True, "未指定路径，跳过检查"
            
            # 获取磁盘使用情况
            usage = shutil.disk_usage(path)
            free_mb = usage.free / (1024 * 1024)
            
            if free_mb < required_mb:
                return False, f"磁盘空间不足: 需要 {required_mb}MB，可用 {free_mb:.1f}MB"
            
            return True, f"磁盘空间充足: {free_mb:.1f}MB 可用"
            
        except Exception as e:
            # 无法检查时不阻塞
            if self.logger:
                self.logger.warning(f"无法检查磁盘空间: {e}")
            return True, f"无法检查磁盘空间: {e}"
    
    def create_hidden_structure(self, folder_path: str) -> Tuple[bool, str]:
        """
        创建 .circuit_ai/ 目录结构
        
        Args:
            folder_path: 工作文件夹路径
            
        Returns:
            Tuple[bool, str]: (是否成功, 消息)
        """
        try:
            path = Path(folder_path)
            hidden_dir = path / WORK_FOLDER_HIDDEN_DIR
            
            # 创建隐藏目录
            hidden_dir.mkdir(parents=True, exist_ok=True)
            
            # 创建子目录
            for subdir in HIDDEN_DIR_STRUCTURE:
                (hidden_dir / subdir).mkdir(parents=True, exist_ok=True)
            
            # Windows: 设置隐藏属性
            if os.name == 'nt':
                try:
                    import ctypes
                    FILE_ATTRIBUTE_HIDDEN = 0x02
                    ctypes.windll.kernel32.SetFileAttributesW(
                        str(hidden_dir), FILE_ATTRIBUTE_HIDDEN
                    )
                except Exception:
                    pass  # 设置隐藏属性失败不影响功能
            
            if self.logger:
                self.logger.debug(f"创建隐藏目录结构: {hidden_dir}")
            
            return True, "隐藏目录结构创建成功"
            
        except Exception as e:
            return False, f"创建隐藏目录失败: {e}"
    
    def _init_json_files(self, project_path: Path) -> None:
        """初始化 JSON 文件"""
        from infrastructure.utils.json_utils import safe_json_dump_file
        
        hidden_dir = project_path / WORK_FOLDER_HIDDEN_DIR
        
        for filename, default_content in INIT_JSON_FILES.items():
            file_path = hidden_dir / filename
            if not file_path.exists():
                try:
                    safe_json_dump_file(default_content, file_path)
                except Exception as e:
                    if self.logger:
                        self.logger.warning(f"初始化 JSON 文件失败: {filename} - {e}")

    # ============================================================
    # 项目状态查询
    # ============================================================
    
    def get_project_status(self) -> ProjectInfo:
        """
        获取项目状态信息
        
        Returns:
            ProjectInfo: 项目信息
        """
        if self._current_project_path is None:
            return ProjectInfo(
                path="",
                name="",
                status=ProjectStatus.NOT_OPENED,
                disk_space_mb=0,
                is_degraded=False,
                degraded_reason=None,
            )
        
        path = self._current_project_path
        # 获取磁盘空间
        try:
            usage = shutil.disk_usage(path)
            disk_space_mb = usage.free / (1024 * 1024)
        except Exception:
            disk_space_mb = 0
        
        return ProjectInfo(
            path=str(path),
            name=path.name,
            status=self._status,
            disk_space_mb=disk_space_mb,
            is_degraded=self._degraded_reason is not None,
            degraded_reason=self._degraded_reason,
        )
    
    def get_current_project_path(self) -> Optional[str]:
        """获取当前项目路径"""
        if self._current_project_path:
            return str(self._current_project_path)
        return None
    
    def get_hidden_dir_path(self) -> Optional[Path]:
        """获取隐藏目录路径"""
        if self._current_project_path:
            return self._current_project_path / WORK_FOLDER_HIDDEN_DIR
        return None
    
    def is_project_open(self) -> bool:
        """检查是否有打开的项目"""
        return self._status in (ProjectStatus.READY, ProjectStatus.DEGRADED)


    # ============================================================
    # 最近打开列表
    # ============================================================
    
    def add_to_recent(self, folder_path: str) -> None:
        """
        添加到最近打开列表
        
        Args:
            folder_path: 项目路径
        """
        from infrastructure.utils.json_utils import safe_json_load_file, safe_json_dump_file
        
        try:
            recent_file = GLOBAL_CONFIG_DIR / RECENT_PROJECTS_FILE
            
            # 确保配置目录存在
            GLOBAL_CONFIG_DIR.mkdir(parents=True, exist_ok=True)
            
            # 加载现有列表
            recent_list = safe_json_load_file(recent_file, default=[])
            
            # 规范化路径
            normalized_path = str(Path(folder_path).resolve())
            
            # 移除已存在的相同路径
            recent_list = [p for p in recent_list if p != normalized_path]
            
            # 添加到列表顶部
            recent_list.insert(0, normalized_path)
            
            # 限制数量
            recent_list = recent_list[:MAX_RECENT_PROJECTS]
            
            # 保存
            safe_json_dump_file(recent_list, recent_file)
            
        except Exception as e:
            if self.logger:
                self.logger.warning(f"添加到最近打开列表失败: {e}")
    
    def get_recent_projects(self, filter_invalid: bool = True) -> List[Dict[str, Any]]:
        """
        获取最近打开的项目列表
        
        Args:
            filter_invalid: 是否过滤无效路径
            
        Returns:
            List[Dict]: 项目列表，每项包含 path, name, exists
        """
        from infrastructure.utils.json_utils import safe_json_load_file
        
        try:
            recent_file = GLOBAL_CONFIG_DIR / RECENT_PROJECTS_FILE
            
            # 加载列表
            recent_list = safe_json_load_file(recent_file, default=[])
            
            result = []
            for path_str in recent_list:
                path = Path(path_str)
                exists = path.exists() and path.is_dir()
                
                if filter_invalid and not exists:
                    continue
                
                result.append({
                    "path": path_str,
                    "name": path.name,
                    "exists": exists,
                })
            
            return result
            
        except Exception as e:
            if self.logger:
                self.logger.warning(f"获取最近打开列表失败: {e}")
            return []
    
    def clear_recent_projects(self) -> bool:
        """
        清空最近打开列表
        
        Returns:
            bool: 是否成功
        """
        from infrastructure.utils.json_utils import safe_json_dump_file
        
        try:
            recent_file = GLOBAL_CONFIG_DIR / RECENT_PROJECTS_FILE
            safe_json_dump_file([], recent_file)
            return True
            
        except Exception as e:
            if self.logger:
                self.logger.warning(f"清空最近打开列表失败: {e}")
            return False
    
    def remove_from_recent(self, folder_path: str) -> bool:
        """
        从最近打开列表中移除指定项目
        
        Args:
            folder_path: 项目路径
            
        Returns:
            bool: 是否成功
        """
        from infrastructure.utils.json_utils import safe_json_load_file, safe_json_dump_file
        
        try:
            recent_file = GLOBAL_CONFIG_DIR / RECENT_PROJECTS_FILE
            
            # 加载列表
            recent_list = safe_json_load_file(recent_file, default=[])
            
            # 规范化路径
            normalized_path = str(Path(folder_path).resolve())
            
            # 移除
            recent_list = [p for p in recent_list if p != normalized_path]
            
            # 保存
            safe_json_dump_file(recent_list, recent_file)
            
            return True
            
        except Exception as e:
            if self.logger:
                self.logger.warning(f"从最近打开列表移除失败: {e}")
            return False


# ============================================================
# 模块导出
# ============================================================

__all__ = [
    "ProjectService",
    "ProjectStatus",
    "ProjectInfo",
]
