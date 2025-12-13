# File Manager - Unified File Operations
"""
统一文件操作管理器

职责：
- 提供统一、安全的文件系统操作接口
- 所有文件操作必须通过此模块进行
- 实现原子性写入、文件锁定、安全校验

初始化顺序：
- Phase 3.2（延迟初始化），依赖 Logger、EventBus

设计原则：
- 所有模块（包括LLM工具调用）必须通过 file_manager 进行文件操作
- 禁止直接使用 open()、os.path 等底层API
- 文件变更自动触发 EVENT_FILE_CHANGED 事件

使用示例：
    from shared.service_locator import ServiceLocator
    from shared.service_names import SVC_FILE_MANAGER
    
    file_manager = ServiceLocator.get(SVC_FILE_MANAGER)
    
    # 读取文件
    content = file_manager.read_file("main.cir")
    
    # 创建新文件（幂等性检查）
    file_manager.create_file("new_file.cir", content)
    
    # 定位修改文件
    file_manager.patch_file("main.cir", "old_value", "new_value")
    
    # 整体替换文件
    file_manager.update_file("main.cir", new_content)
"""

import hashlib
import os
import shutil
import threading
import time
from datetime import datetime
from fnmatch import fnmatch
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union

# ============================================================
# 自定义异常类
# ============================================================


class FileManagerError(Exception):
    """文件管理器基础异常"""
    pass


class PathSecurityError(FileManagerError):
    """路径安全校验失败"""
    
    def __init__(self, path: str, reason: str):
        self.path = path
        self.reason = reason
        super().__init__(f"路径安全校验失败: {path} - {reason}")


class FileExistsError(FileManagerError):
    """文件已存在且内容不同"""
    
    def __init__(self, path: str):
        self.path = path
        super().__init__(
            f"文件已存在且内容不同: {path}\n"
            f"如需覆盖，请使用 update_file() 方法"
        )


class DirectoryCreationError(FileManagerError):
    """目录创建失败"""
    
    def __init__(self, path: str, reason: str):
        self.path = path
        self.reason = reason
        super().__init__(f"目录创建失败: {path} - {reason}")


class SearchNotFoundError(FileManagerError):
    """搜索内容未找到"""
    
    def __init__(self, path: str, search_preview: str):
        self.path = path
        self.search_preview = search_preview
        super().__init__(
            f"搜索内容未找到: {path}\n"
            f"搜索内容摘要: {search_preview[:100]}..."
        )


class MultipleMatchError(FileManagerError):
    """搜索内容匹配多处"""
    
    def __init__(self, path: str, match_count: int, positions: List[int]):
        self.path = path
        self.match_count = match_count
        self.positions = positions
        super().__init__(
            f"搜索内容匹配 {match_count} 处: {path}\n"
            f"匹配位置: {positions}\n"
            f"请指定 occurrence 参数或使用更精确的搜索内容"
        )


class FileLockTimeoutError(FileManagerError):
    """文件锁获取超时"""
    
    def __init__(self, path: str, timeout: float):
        self.path = path
        self.timeout = timeout
        super().__init__(f"文件锁获取超时 ({timeout}s): {path}")


class FileOperationError(FileManagerError):
    """文件操作失败"""
    
    def __init__(self, operation: str, path: str, reason: str):
        self.operation = operation
        self.path = path
        self.reason = reason
        super().__init__(f"文件操作失败 [{operation}]: {path} - {reason}")


# ============================================================
# 文件锁管理
# ============================================================


class FileLock:
    """
    文件锁 - 防止并发写入
    
    使用 threading.Lock 实现进程内锁定
    """
    
    def __init__(self, path: str, timeout: float = 5.0):
        self.path = path
        self.timeout = timeout
        self._lock = threading.Lock()
        self._acquired = False
    
    def acquire(self) -> bool:
        """
        获取文件锁
        
        Returns:
            bool: 是否成功获取
        """
        self._acquired = self._lock.acquire(timeout=self.timeout)
        return self._acquired
    
    def release(self) -> None:
        """释放文件锁"""
        if self._acquired:
            self._lock.release()
            self._acquired = False
    
    def __enter__(self):
        if not self.acquire():
            raise FileLockTimeoutError(self.path, self.timeout)
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        self.release()
        return False


# ============================================================
# 文件管理器主类
# ============================================================


class FileManager:
    """
    统一文件操作管理器
    
    提供安全、原子性的文件操作接口
    用户可选择电脑上任意目录作为工作目录（类似 VSCode）
    """
    
    # 临时文件目录名
    TEMP_DIR_NAME = ".circuit_ai/temp"
    
    # 临时文件过期时间（秒）
    TEMP_FILE_MAX_AGE = 24 * 60 * 60  # 24小时
    
    # 默认文件锁超时（秒）
    DEFAULT_LOCK_TIMEOUT = 5.0
    
    def __init__(self):
        """初始化文件管理器"""
        # 工作目录（延迟设置）
        self._work_dir: Optional[Path] = None
        
        # 文件锁注册表
        self._locks: Dict[str, FileLock] = {}
        self._locks_mutex = threading.Lock()
        
        # 延迟获取的服务
        self._logger = None
        self._event_bus = None
    
    # ============================================================
    # 延迟获取服务（避免循环依赖）
    # ============================================================
    
    @property
    def logger(self):
        """延迟获取日志器"""
        if self._logger is None:
            try:
                from infrastructure.utils.logger import get_logger
                self._logger = get_logger("file_manager")
            except Exception:
                pass
        return self._logger
    
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

    # ============================================================
    # 工作目录管理
    # ============================================================
    
    def set_work_dir(self, path: Union[str, Path]) -> None:
        """
        设置工作目录
        
        Args:
            path: 工作目录路径
        """
        self._work_dir = Path(path).resolve()
        if self.logger:
            self.logger.info(f"工作目录设置为: {self._work_dir}")
    
    def get_work_dir(self) -> Optional[Path]:
        """
        获取当前工作目录
        
        Returns:
            Path: 工作目录路径，未设置时返回 None
        """
        return self._work_dir
    
    def _resolve_path(self, path: Union[str, Path]) -> Path:
        """
        解析路径为绝对路径
        
        相对路径基于工作目录解析，绝对路径直接使用
        
        Args:
            path: 文件路径
            
        Returns:
            Path: 解析后的绝对路径
        """
        path = Path(path)
        if path.is_absolute():
            return path.resolve()
        
        if self._work_dir is None:
            # 未设置工作目录时，基于当前目录
            return Path.cwd().joinpath(path).resolve()
        
        return self._work_dir.joinpath(path).resolve()
    
    # ============================================================
    # 安全校验
    # ============================================================
    
    def _validate_path_security(self, path: Path) -> None:
        """
        校验路径安全性
        
        用户可选择电脑上任意目录作为工作目录（类似 VSCode）
        安全校验仅拒绝操作系统关键目录和 Git 内部目录
        
        Args:
            path: 要校验的路径
            
        Raises:
            PathSecurityError: 路径安全校验失败
        """
        resolved = path.resolve()
        path_str = str(resolved)
        
        # 检查危险路径模式（系统关键目录）
        dangerous_patterns = [
            # Linux/macOS 系统目录
            "/etc/*", "/usr/*", "/bin/*", "/sbin/*",
            "/boot/*", "/lib/*", "/lib64/*",
            # Windows 系统目录
            "C:\\Windows\\*", "C:\\Program Files\\*", "C:\\Program Files (x86)\\*",
            # Git 内部目录（防止破坏版本控制）
            "*/.git/objects/*", "*/.git/hooks/*"
        ]
        
        for pattern in dangerous_patterns:
            if fnmatch(path_str, pattern):
                raise PathSecurityError(
                    str(path),
                    f"拒绝操作系统关键目录: {pattern}"
                )
        
        # 检查符号链接指向的目标
        if path.is_symlink():
            link_target = path.resolve()
            link_target_str = str(link_target)
            for pattern in dangerous_patterns:
                if fnmatch(link_target_str, pattern):
                    raise PathSecurityError(
                        str(path),
                        f"符号链接指向系统关键目录: {pattern}"
                    )
    
    # ============================================================
    # 文件锁管理
    # ============================================================
    
    def _get_lock(self, path: str) -> FileLock:
        """获取或创建文件锁"""
        with self._locks_mutex:
            if path not in self._locks:
                self._locks[path] = FileLock(path, self.DEFAULT_LOCK_TIMEOUT)
            return self._locks[path]
    
    def acquire_lock(self, path: Union[str, Path], timeout: float = None) -> bool:
        """
        获取文件锁
        
        Args:
            path: 文件路径
            timeout: 超时时间（秒），默认使用 DEFAULT_LOCK_TIMEOUT
            
        Returns:
            bool: 是否成功获取
        """
        resolved = self._resolve_path(path)
        lock = self._get_lock(str(resolved))
        if timeout is not None:
            lock.timeout = timeout
        return lock.acquire()
    
    def release_lock(self, path: Union[str, Path]) -> None:
        """
        释放文件锁
        
        Args:
            path: 文件路径
        """
        resolved = self._resolve_path(path)
        lock_key = str(resolved)
        with self._locks_mutex:
            if lock_key in self._locks:
                self._locks[lock_key].release()
    
    # ============================================================
    # 事件发布
    # ============================================================
    
    def _publish_file_changed(
        self,
        path: Path,
        operation: str,
        char_count: Optional[int] = None
    ) -> None:
        """
        发布文件变更事件
        
        Args:
            path: 文件路径
            operation: 操作类型（create/update/delete）
            char_count: 字符数（可选）
        """
        if self.event_bus is None:
            return
        
        try:
            from shared.event_types import EVENT_FILE_CHANGED
            self.event_bus.publish(
                EVENT_FILE_CHANGED,
                {
                    "path": str(path),
                    "operation": operation,
                    "char_count": char_count,
                    "timestamp": time.time()
                }
            )
        except Exception as e:
            if self.logger:
                self.logger.warning(f"发布文件变更事件失败: {e}")
    
    # ============================================================
    # 哈希计算
    # ============================================================
    
    def _compute_hash(self, content: Union[str, bytes]) -> str:
        """
        计算内容哈希值
        
        Args:
            content: 文件内容
            
        Returns:
            str: SHA256 哈希值
        """
        if isinstance(content, str):
            content = content.encode('utf-8')
        return hashlib.sha256(content).hexdigest()

    # ============================================================
    # 核心文件操作
    # ============================================================
    
    def read_file(
        self,
        path: Union[str, Path],
        binary: bool = False,
        encoding: str = 'utf-8'
    ) -> Union[str, bytes]:
        """
        读取文件内容
        
        Args:
            path: 文件路径
            binary: 是否以二进制模式读取
            encoding: 文本编码（binary=False 时使用）
            
        Returns:
            文件内容（str 或 bytes）
            
        Raises:
            FileNotFoundError: 文件不存在
            PathSecurityError: 路径安全校验失败
            FileOperationError: 读取失败
        """
        resolved = self._resolve_path(path)
        self._validate_path_security(resolved)
        
        if not resolved.exists():
            raise FileNotFoundError(f"文件不存在: {resolved}")
        
        try:
            if binary:
                content = resolved.read_bytes()
            else:
                content = resolved.read_text(encoding=encoding)
            
            # 记录日志
            if self.logger:
                from infrastructure.utils.logger import log_file_operation
                char_count = len(content) if isinstance(content, str) else len(content)
                log_file_operation("read", str(resolved), char_count, success=True)
            
            return content
            
        except Exception as e:
            if self.logger:
                from infrastructure.utils.logger import log_file_operation
                log_file_operation("read", str(resolved), success=False)
            raise FileOperationError("read", str(resolved), str(e))
    
    def write_file(
        self,
        path: Union[str, Path],
        content: Union[str, bytes],
        encoding: str = 'utf-8'
    ) -> bool:
        """
        写入文件（原子性写入）
        
        先写入临时文件，再重命名为目标文件，确保原子性
        
        Args:
            path: 文件路径
            content: 文件内容
            encoding: 文本编码
            
        Returns:
            bool: 是否成功
            
        Raises:
            PathSecurityError: 路径安全校验失败
            FileLockTimeoutError: 文件锁获取超时
            FileOperationError: 写入失败
        """
        resolved = self._resolve_path(path)
        self._validate_path_security(resolved)
        
        # 确保父目录存在
        resolved.parent.mkdir(parents=True, exist_ok=True)
        
        # 获取文件锁
        lock = self._get_lock(str(resolved))
        
        try:
            with lock:
                # 原子性写入：先写临时文件
                temp_path = resolved.with_suffix(resolved.suffix + '.tmp')
                
                if isinstance(content, str):
                    temp_path.write_text(content, encoding=encoding)
                else:
                    temp_path.write_bytes(content)
                
                # 重命名为目标文件
                os.replace(str(temp_path), str(resolved))
                
                # 记录日志
                if self.logger:
                    from infrastructure.utils.logger import log_file_operation
                    char_count = len(content) if isinstance(content, str) else len(content)
                    log_file_operation("write", str(resolved), char_count, success=True)
                
                # 发布事件
                self._publish_file_changed(resolved, "update", len(content))
                
                return True
                
        except FileLockTimeoutError:
            raise
        except Exception as e:
            # 清理临时文件
            temp_path = resolved.with_suffix(resolved.suffix + '.tmp')
            if temp_path.exists():
                try:
                    temp_path.unlink()
                except Exception:
                    pass
            
            if self.logger:
                from infrastructure.utils.logger import log_file_operation
                log_file_operation("write", str(resolved), success=False)
            raise FileOperationError("write", str(resolved), str(e))
    
    def create_file(
        self,
        path: Union[str, Path],
        content: Union[str, bytes],
        encoding: str = 'utf-8'
    ) -> bool:
        """
        创建新文件（幂等性检查）
        
        若文件已存在且内容相同，返回成功；
        若文件已存在但内容不同，抛出 FileExistsError
        
        Args:
            path: 文件路径
            content: 文件内容
            encoding: 文本编码
            
        Returns:
            bool: 是否成功
            
        Raises:
            FileExistsError: 文件已存在且内容不同
            PathSecurityError: 路径安全校验失败
            DirectoryCreationError: 父目录创建失败
        """
        resolved = self._resolve_path(path)
        self._validate_path_security(resolved)
        
        # 检查文件是否已存在
        if resolved.exists():
            # 执行幂等性检查
            try:
                existing_content = self.read_file(resolved, binary=isinstance(content, bytes))
                existing_hash = self._compute_hash(existing_content)
                target_hash = self._compute_hash(content)
                
                if existing_hash == target_hash:
                    # 内容相同，返回成功
                    if self.logger:
                        self.logger.debug(f"文件已存在且内容一致，跳过创建: {resolved}")
                    return True
                else:
                    # 内容不同，抛出异常
                    raise FileExistsError(str(resolved))
                    
            except FileExistsError:
                raise
            except Exception as e:
                raise FileOperationError("create", str(resolved), f"幂等性检查失败: {e}")
        
        # 确保父目录存在
        try:
            resolved.parent.mkdir(parents=True, exist_ok=True)
        except Exception as e:
            raise DirectoryCreationError(str(resolved.parent), str(e))
        
        # 创建文件
        try:
            result = self.write_file(resolved, content, encoding)
            
            # 发布创建事件
            self._publish_file_changed(resolved, "create", len(content))
            
            return result
            
        except Exception as e:
            if self.logger:
                from infrastructure.utils.logger import log_file_operation
                log_file_operation("create", str(resolved), success=False)
            raise FileOperationError("create", str(resolved), str(e))

    def patch_file(
        self,
        path: Union[str, Path],
        search: str,
        replace: str,
        occurrence: int = 1,
        encoding: str = 'utf-8'
    ) -> int:
        """
        定位修改文件内容
        
        在文件中查找指定内容并替换为新内容
        
        Args:
            path: 文件路径
            search: 搜索内容
            replace: 替换内容
            occurrence: 匹配第几处（默认1，0表示全部）
            encoding: 文本编码
            
        Returns:
            int: 替换次数
            
        Raises:
            FileNotFoundError: 文件不存在
            SearchNotFoundError: 搜索内容不存在且替换内容也不存在
            MultipleMatchError: 匹配多处但未指定 occurrence
            PathSecurityError: 路径安全校验失败
            FileLockTimeoutError: 文件锁获取超时
        """
        resolved = self._resolve_path(path)
        self._validate_path_security(resolved)
        
        if not resolved.exists():
            raise FileNotFoundError(f"文件不存在: {resolved}")
        
        # 获取文件锁
        lock = self._get_lock(str(resolved))
        
        try:
            with lock:
                # 读取文件内容
                content = resolved.read_text(encoding=encoding)
                
                # 幂等性检查
                if search not in content:
                    # 检查 replace 是否已存在
                    if replace in content:
                        # 内容已是目标状态
                        if self.logger:
                            self.logger.debug(f"文件已是目标状态，跳过修改: {resolved}")
                        return 0
                    else:
                        # search 和 replace 都不存在
                        raise SearchNotFoundError(str(resolved), search)
                
                # 查找所有匹配位置
                positions = []
                start = 0
                while True:
                    pos = content.find(search, start)
                    if pos == -1:
                        break
                    positions.append(pos)
                    start = pos + 1
                
                match_count = len(positions)
                
                # 检查匹配数量
                if match_count > 1 and occurrence == 1:
                    # 默认 occurrence=1 时，如果有多处匹配，抛出异常
                    raise MultipleMatchError(str(resolved), match_count, positions)
                
                # 执行替换
                if occurrence == 0:
                    # 替换所有
                    new_content = content.replace(search, replace)
                    replace_count = match_count
                else:
                    # 替换指定位置
                    if occurrence > match_count:
                        raise SearchNotFoundError(
                            str(resolved),
                            f"指定 occurrence={occurrence}，但只找到 {match_count} 处匹配"
                        )
                    
                    # 找到第 occurrence 处的位置
                    target_pos = positions[occurrence - 1]
                    new_content = (
                        content[:target_pos] +
                        replace +
                        content[target_pos + len(search):]
                    )
                    replace_count = 1
                
                # 原子性写入
                temp_path = resolved.with_suffix(resolved.suffix + '.tmp')
                temp_path.write_text(new_content, encoding=encoding)
                os.replace(str(temp_path), str(resolved))
                
                # 记录日志
                if self.logger:
                    from infrastructure.utils.logger import log_file_operation
                    log_file_operation("patch", str(resolved), len(new_content), success=True)
                
                # 发布事件
                self._publish_file_changed(resolved, "update", len(new_content))
                
                return replace_count
                
        except (SearchNotFoundError, MultipleMatchError, FileLockTimeoutError):
            raise
        except Exception as e:
            # 清理临时文件
            temp_path = resolved.with_suffix(resolved.suffix + '.tmp')
            if temp_path.exists():
                try:
                    temp_path.unlink()
                except Exception:
                    pass
            
            if self.logger:
                from infrastructure.utils.logger import log_file_operation
                log_file_operation("patch", str(resolved), success=False)
            raise FileOperationError("patch", str(resolved), str(e))
    
    def update_file(
        self,
        path: Union[str, Path],
        content: Union[str, bytes],
        encoding: str = 'utf-8'
    ) -> bool:
        """
        整体替换文件内容（幂等性检查）
        
        用新内容完全替换整个文件。
        作为 patch_file 失败时的降级方案。
        
        Args:
            path: 文件路径
            content: 完整的新文件内容
            encoding: 文本编码
            
        Returns:
            bool: 是否成功
            
        Raises:
            FileNotFoundError: 文件不存在
            PathSecurityError: 路径安全校验失败
            FileLockTimeoutError: 文件锁获取超时
        """
        resolved = self._resolve_path(path)
        self._validate_path_security(resolved)
        
        if not resolved.exists():
            raise FileNotFoundError(f"文件不存在: {resolved}")
        
        # 获取文件锁
        lock = self._get_lock(str(resolved))
        
        try:
            with lock:
                # 幂等性检查
                existing_content = self.read_file(resolved, binary=isinstance(content, bytes))
                existing_hash = self._compute_hash(existing_content)
                target_hash = self._compute_hash(content)
                
                if existing_hash == target_hash:
                    # 内容相同，跳过写入
                    if self.logger:
                        self.logger.debug(f"文件内容未变化，跳过更新: {resolved}")
                    return True
                
                # 原子性写入
                temp_path = resolved.with_suffix(resolved.suffix + '.tmp')
                
                if isinstance(content, str):
                    temp_path.write_text(content, encoding=encoding)
                else:
                    temp_path.write_bytes(content)
                
                os.replace(str(temp_path), str(resolved))
                
                # 记录日志
                if self.logger:
                    from infrastructure.utils.logger import log_file_operation
                    char_count = len(content) if isinstance(content, str) else len(content)
                    log_file_operation("update", str(resolved), char_count, success=True)
                
                # 发布事件
                self._publish_file_changed(resolved, "update", len(content))
                
                return True
                
        except FileLockTimeoutError:
            raise
        except Exception as e:
            # 清理临时文件
            temp_path = resolved.with_suffix(resolved.suffix + '.tmp')
            if temp_path.exists():
                try:
                    temp_path.unlink()
                except Exception:
                    pass
            
            if self.logger:
                from infrastructure.utils.logger import log_file_operation
                log_file_operation("update", str(resolved), success=False)
            raise FileOperationError("update", str(resolved), str(e))

    def delete_file(self, path: Union[str, Path]) -> bool:
        """
        删除文件
        
        Args:
            path: 文件路径
            
        Returns:
            bool: 是否成功
            
        Raises:
            FileNotFoundError: 文件不存在
            PathSecurityError: 路径安全校验失败
        """
        resolved = self._resolve_path(path)
        self._validate_path_security(resolved)
        
        if not resolved.exists():
            raise FileNotFoundError(f"文件不存在: {resolved}")
        
        try:
            resolved.unlink()
            
            # 记录日志
            if self.logger:
                from infrastructure.utils.logger import log_file_operation
                log_file_operation("delete", str(resolved), success=True)
            
            # 发布事件
            self._publish_file_changed(resolved, "delete")
            
            return True
            
        except Exception as e:
            if self.logger:
                from infrastructure.utils.logger import log_file_operation
                log_file_operation("delete", str(resolved), success=False)
            raise FileOperationError("delete", str(resolved), str(e))
    
    # ============================================================
    # 目录操作
    # ============================================================
    
    def ensure_directory(self, path: Union[str, Path]) -> bool:
        """
        确保目录存在
        
        如果目录不存在则创建（包括父目录）
        
        Args:
            path: 目录路径
            
        Returns:
            bool: 是否成功
            
        Raises:
            PathSecurityError: 路径安全校验失败
            DirectoryCreationError: 目录创建失败
        """
        resolved = self._resolve_path(path)
        self._validate_path_security(resolved)
        
        try:
            resolved.mkdir(parents=True, exist_ok=True)
            return True
        except Exception as e:
            raise DirectoryCreationError(str(resolved), str(e))
    
    def list_directory(
        self,
        path: Union[str, Path],
        pattern: str = "*",
        recursive: bool = False
    ) -> List[Dict[str, Any]]:
        """
        列出目录内容
        
        Args:
            path: 目录路径
            pattern: glob 模式（默认 "*"）
            recursive: 是否递归（默认 False）
            
        Returns:
            List[Dict]: 文件信息列表，每项包含：
                - name: 文件名
                - path: 完整路径
                - is_dir: 是否为目录
                - size: 文件大小（字节）
                - modified: 修改时间（时间戳）
                
        Raises:
            FileNotFoundError: 目录不存在
            PathSecurityError: 路径安全校验失败
        """
        resolved = self._resolve_path(path)
        self._validate_path_security(resolved)
        
        if not resolved.exists():
            raise FileNotFoundError(f"目录不存在: {resolved}")
        
        if not resolved.is_dir():
            raise FileOperationError("list", str(resolved), "路径不是目录")
        
        results = []
        
        try:
            if recursive:
                items = resolved.rglob(pattern)
            else:
                items = resolved.glob(pattern)
            
            for item in items:
                try:
                    stat = item.stat()
                    results.append({
                        "name": item.name,
                        "path": str(item),
                        "is_dir": item.is_dir(),
                        "size": stat.st_size,
                        "modified": stat.st_mtime
                    })
                except Exception:
                    # 跳过无法访问的文件
                    continue
            
            return results
            
        except Exception as e:
            raise FileOperationError("list", str(resolved), str(e))
    
    # ============================================================
    # 文件信息查询
    # ============================================================
    
    def file_exists(self, path: Union[str, Path]) -> bool:
        """
        检查文件是否存在
        
        Args:
            path: 文件路径
            
        Returns:
            bool: 文件是否存在
        """
        resolved = self._resolve_path(path)
        return resolved.exists()
    
    def get_file_info(self, path: Union[str, Path]) -> Dict[str, Any]:
        """
        获取文件元信息
        
        Args:
            path: 文件路径
            
        Returns:
            Dict: 文件信息，包含：
                - name: 文件名
                - path: 完整路径
                - size: 文件大小（字节）
                - modified: 修改时间（时间戳）
                - created: 创建时间（时间戳）
                - is_dir: 是否为目录
                - extension: 文件扩展名
                
        Raises:
            FileNotFoundError: 文件不存在
            PathSecurityError: 路径安全校验失败
        """
        resolved = self._resolve_path(path)
        self._validate_path_security(resolved)
        
        if not resolved.exists():
            raise FileNotFoundError(f"文件不存在: {resolved}")
        
        try:
            stat = resolved.stat()
            return {
                "name": resolved.name,
                "path": str(resolved),
                "size": stat.st_size,
                "modified": stat.st_mtime,
                "created": stat.st_ctime,
                "is_dir": resolved.is_dir(),
                "extension": resolved.suffix
            }
        except Exception as e:
            raise FileOperationError("get_info", str(resolved), str(e))

    # ============================================================
    # 临时文件管理
    # ============================================================
    
    def _get_temp_dir(self) -> Path:
        """
        获取临时文件目录
        
        Returns:
            Path: 临时文件目录路径
        """
        if self._work_dir is None:
            return Path.cwd() / self.TEMP_DIR_NAME
        return self._work_dir / self.TEMP_DIR_NAME
    
    def cleanup_temp_files(self, max_age_seconds: int = None) -> int:
        """
        清理临时文件
        
        删除超过指定时间的临时文件
        
        Args:
            max_age_seconds: 最大保留时间（秒），默认 24 小时
            
        Returns:
            int: 删除的文件数量
        """
        if max_age_seconds is None:
            max_age_seconds = self.TEMP_FILE_MAX_AGE
        
        temp_dir = self._get_temp_dir()
        
        if not temp_dir.exists():
            return 0
        
        deleted_count = 0
        cutoff_time = time.time() - max_age_seconds
        
        try:
            for item in temp_dir.iterdir():
                try:
                    if item.stat().st_mtime < cutoff_time:
                        if item.is_file():
                            item.unlink()
                        elif item.is_dir():
                            shutil.rmtree(item)
                        deleted_count += 1
                except Exception as e:
                    if self.logger:
                        self.logger.warning(f"清理临时文件失败: {item} - {e}")
            
            if deleted_count > 0 and self.logger:
                self.logger.info(f"清理了 {deleted_count} 个过期临时文件")
            
            return deleted_count
            
        except Exception as e:
            if self.logger:
                self.logger.warning(f"清理临时文件目录失败: {e}")
            return deleted_count
    
    def create_temp_file(
        self,
        content: Union[str, bytes],
        prefix: str = "temp_",
        suffix: str = "",
        encoding: str = 'utf-8'
    ) -> Path:
        """
        创建临时文件
        
        Args:
            content: 文件内容
            prefix: 文件名前缀
            suffix: 文件名后缀
            encoding: 文本编码
            
        Returns:
            Path: 临时文件路径
        """
        temp_dir = self._get_temp_dir()
        temp_dir.mkdir(parents=True, exist_ok=True)
        
        # 生成唯一文件名
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        filename = f"{prefix}{timestamp}{suffix}"
        temp_path = temp_dir / filename
        
        # 写入内容
        if isinstance(content, str):
            temp_path.write_text(content, encoding=encoding)
        else:
            temp_path.write_bytes(content)
        
        return temp_path
    
    # ============================================================
    # 便捷方法
    # ============================================================
    
    def copy_file(
        self,
        src: Union[str, Path],
        dst: Union[str, Path]
    ) -> bool:
        """
        复制文件
        
        Args:
            src: 源文件路径
            dst: 目标文件路径
            
        Returns:
            bool: 是否成功
        """
        src_resolved = self._resolve_path(src)
        dst_resolved = self._resolve_path(dst)
        
        self._validate_path_security(src_resolved)
        self._validate_path_security(dst_resolved)
        
        if not src_resolved.exists():
            raise FileNotFoundError(f"源文件不存在: {src_resolved}")
        
        try:
            # 确保目标目录存在
            dst_resolved.parent.mkdir(parents=True, exist_ok=True)
            
            shutil.copy2(str(src_resolved), str(dst_resolved))
            
            # 发布事件
            self._publish_file_changed(dst_resolved, "create")
            
            return True
            
        except Exception as e:
            raise FileOperationError("copy", str(src_resolved), str(e))
    
    def move_file(
        self,
        src: Union[str, Path],
        dst: Union[str, Path]
    ) -> bool:
        """
        移动文件
        
        Args:
            src: 源文件路径
            dst: 目标文件路径
            
        Returns:
            bool: 是否成功
        """
        src_resolved = self._resolve_path(src)
        dst_resolved = self._resolve_path(dst)
        
        self._validate_path_security(src_resolved)
        self._validate_path_security(dst_resolved)
        
        if not src_resolved.exists():
            raise FileNotFoundError(f"源文件不存在: {src_resolved}")
        
        try:
            # 确保目标目录存在
            dst_resolved.parent.mkdir(parents=True, exist_ok=True)
            
            shutil.move(str(src_resolved), str(dst_resolved))
            
            # 发布事件
            self._publish_file_changed(src_resolved, "delete")
            self._publish_file_changed(dst_resolved, "create")
            
            return True
            
        except Exception as e:
            raise FileOperationError("move", str(src_resolved), str(e))
    
    def get_relative_path(
        self,
        path: Union[str, Path],
        base: Union[str, Path] = None
    ) -> str:
        """
        获取相对路径
        
        Args:
            path: 文件路径
            base: 基准路径（默认使用工作目录）
            
        Returns:
            str: 相对路径
        """
        resolved = self._resolve_path(path)
        
        if base is None:
            base = self._work_dir or Path.cwd()
        else:
            base = Path(base).resolve()
        
        try:
            return str(resolved.relative_to(base))
        except ValueError:
            return str(resolved)


# ============================================================
# 模块导出
# ============================================================

__all__ = [
    # 主类
    "FileManager",
    "FileLock",
    # 异常类
    "FileManagerError",
    "PathSecurityError",
    "FileExistsError",
    "DirectoryCreationError",
    "SearchNotFoundError",
    "MultipleMatchError",
    "FileLockTimeoutError",
    "FileOperationError",
]
