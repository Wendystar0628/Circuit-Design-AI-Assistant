# Async File Operations - Application Layer Interface
"""
异步文件操作门面 - 应用层接口

职责：
- 为应用层提供非阻塞的异步文件操作接口
- 所有方法都是 async def，通过 asyncio.to_thread() 包装同步操作
- 确保事件循环不被阻塞，UI 保持响应

设计原则：
- 这是应用层的唯一文件操作入口
- UI 层、LangGraph 节点、LLM 工具调用必须使用本模块
- 禁止 UI 线程直接调用 FileManager 的同步方法

初始化顺序：
- Phase 3.3，依赖 FileManager，注册到 ServiceLocator

使用示例：
    from infrastructure.persistence.async_file_ops import AsyncFileOps
    
    async_ops = AsyncFileOps()
    
    # 单文件读取
    content = await async_ops.read_file_async("main.cir")
    
    # 并发读取多个文件
    results = await async_ops.read_multiple_files_async([
        "main.cir", "subcircuits/opamp.cir", "parameters/values.json"
    ])
"""

import asyncio
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union

from .file_manager import FileManager


class AsyncFileOps:
    """
    异步文件操作门面类
    
    通过 asyncio.to_thread() 将 FileManager 的同步方法卸载到线程池，
    确保主线程（事件循环）不被阻塞。
    
    线程安全说明：
    - FileManager 使用 FileLock 进行文件锁定
    - 锁的获取和释放在工作线程内闭环完成
    - 主线程不直接持有锁，避免跨线程锁竞争
    """
    
    # 默认并发读取文件数
    DEFAULT_MAX_WORKERS = 10
    
    def __init__(self, file_manager: Optional[FileManager] = None):
        """
        初始化异步文件操作门面
        
        Args:
            file_manager: FileManager 实例，若不提供则延迟获取
        """
        self._file_manager = file_manager
    
    @property
    def file_manager(self) -> FileManager:
        """延迟获取 FileManager 实例"""
        if self._file_manager is None:
            try:
                from shared.service_locator import ServiceLocator
                from shared.service_names import SVC_FILE_MANAGER
                self._file_manager = ServiceLocator.get(SVC_FILE_MANAGER)
            except Exception:
                # 如果无法从 ServiceLocator 获取，创建新实例
                self._file_manager = FileManager()
        return self._file_manager
    
    # ============================================================
    # 异步文件读取
    # ============================================================
    
    async def read_file_async(
        self,
        path: Union[str, Path],
        binary: bool = False,
        encoding: str = 'utf-8'
    ) -> Union[str, bytes]:
        """
        异步读取文件内容
        
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
        return await asyncio.to_thread(
            self.file_manager.read_file,
            path,
            binary=binary,
            encoding=encoding
        )
    
    async def read_multiple_files_async(
        self,
        paths: List[Union[str, Path]],
        binary: bool = False,
        encoding: str = 'utf-8',
        max_workers: int = DEFAULT_MAX_WORKERS
    ) -> Dict[str, Union[str, bytes, Exception]]:
        """
        并发读取多个文件
        
        使用 asyncio.gather() 并发调度多个 to_thread 任务，
        适用于上下文检索、批量文件分析等场景。
        
        Args:
            paths: 文件路径列表
            binary: 是否以二进制模式读取
            encoding: 文本编码
            max_workers: 最大并发数（默认 10）
            
        Returns:
            Dict[str, Union[str, bytes, Exception]]: 
                键为文件路径，值为文件内容或异常对象
        """
        # 限制并发数
        semaphore = asyncio.Semaphore(max_workers)
        
        async def read_with_semaphore(path: Union[str, Path]) -> Tuple[str, Union[str, bytes, Exception]]:
            async with semaphore:
                try:
                    content = await self.read_file_async(path, binary=binary, encoding=encoding)
                    return (str(path), content)
                except Exception as e:
                    return (str(path), e)
        
        # 并发执行所有读取任务
        tasks = [read_with_semaphore(p) for p in paths]
        results = await asyncio.gather(*tasks)
        
        return dict(results)
    
    # ============================================================
    # 异步文件写入
    # ============================================================
    
    async def write_file_async(
        self,
        path: Union[str, Path],
        content: Union[str, bytes],
        encoding: str = 'utf-8'
    ) -> bool:
        """
        异步写入文件（原子性写入）
        
        Args:
            path: 文件路径
            content: 文件内容
            encoding: 文本编码
            
        Returns:
            bool: 是否成功
        """
        return await asyncio.to_thread(
            self.file_manager.write_file,
            path,
            content,
            encoding=encoding
        )
    
    async def create_file_async(
        self,
        path: Union[str, Path],
        content: Union[str, bytes],
        encoding: str = 'utf-8'
    ) -> bool:
        """
        异步创建新文件（幂等性检查）
        
        Args:
            path: 文件路径
            content: 文件内容
            encoding: 文本编码
            
        Returns:
            bool: 是否成功
        """
        return await asyncio.to_thread(
            self.file_manager.create_file,
            path,
            content,
            encoding=encoding
        )

    
    async def patch_file_async(
        self,
        path: Union[str, Path],
        search: str,
        replace: str,
        occurrence: int = 1,
        fuzzy: bool = False,
        encoding: str = 'utf-8'
    ) -> Union[int, Tuple[int, str]]:
        """
        异步定位修改文件内容
        
        Args:
            path: 文件路径
            search: 搜索内容
            replace: 替换内容
            occurrence: 匹配第几处（默认1，0表示全部）
            fuzzy: 是否启用模糊匹配
            encoding: 文本编码
            
        Returns:
            int: 替换次数（fuzzy=False 时）
            Tuple[int, str]: (替换次数, 实际匹配到的原始内容)（fuzzy=True 时）
        """
        return await asyncio.to_thread(
            self.file_manager.patch_file,
            path,
            search,
            replace,
            occurrence=occurrence,
            fuzzy=fuzzy,
            encoding=encoding
        )
    
    async def patch_file_by_line_async(
        self,
        path: Union[str, Path],
        start_line: int,
        end_line: int,
        new_content: str,
        encoding: str = 'utf-8'
    ) -> str:
        """
        异步按行号范围修改文件内容
        
        Args:
            path: 文件路径
            start_line: 起始行号（从 1 开始）
            end_line: 结束行号（包含该行）
            new_content: 替换内容
            encoding: 文本编码
            
        Returns:
            str: 被替换的原始内容
        """
        return await asyncio.to_thread(
            self.file_manager.patch_file_by_line,
            path,
            start_line,
            end_line,
            new_content,
            encoding=encoding
        )
    
    async def rewrite_file_async(
        self,
        path: Union[str, Path],
        content: Union[str, bytes],
        encoding: str = 'utf-8'
    ) -> bool:
        """
        异步重写文件（小文件整体重写）
        
        Args:
            path: 文件路径
            content: 完整的新文件内容
            encoding: 文本编码
            
        Returns:
            bool: 是否成功
        """
        return await asyncio.to_thread(
            self.file_manager.rewrite_file,
            path,
            content,
            encoding=encoding
        )
    
    async def update_file_async(
        self,
        path: Union[str, Path],
        content: Union[str, bytes],
        encoding: str = 'utf-8'
    ) -> bool:
        """
        异步更新文件（整体替换）
        
        Args:
            path: 文件路径
            content: 完整的新文件内容
            encoding: 文本编码
            
        Returns:
            bool: 是否成功
        """
        return await asyncio.to_thread(
            self.file_manager.update_file,
            path,
            content,
            encoding=encoding
        )
    
    async def delete_file_async(
        self,
        path: Union[str, Path]
    ) -> bool:
        """
        异步删除文件
        
        Args:
            path: 文件路径
            
        Returns:
            bool: 是否成功
        """
        return await asyncio.to_thread(
            self.file_manager.delete_file,
            path
        )
    
    # ============================================================
    # 异步文件信息查询
    # ============================================================
    
    async def file_exists_async(
        self,
        path: Union[str, Path]
    ) -> bool:
        """
        异步检查文件是否存在
        
        Args:
            path: 文件路径
            
        Returns:
            bool: 文件是否存在
        """
        return await asyncio.to_thread(
            self.file_manager.file_exists,
            path
        )
    
    async def list_directory_async(
        self,
        path: Union[str, Path],
        pattern: Optional[str] = None,
        recursive: bool = False
    ) -> List[str]:
        """
        异步列出目录内容
        
        Args:
            path: 目录路径
            pattern: glob 模式（可选）
            recursive: 是否递归
            
        Returns:
            List[str]: 文件路径列表
        """
        return await asyncio.to_thread(
            self.file_manager.list_directory,
            path,
            pattern=pattern,
            recursive=recursive
        )
    
    async def get_file_info_async(
        self,
        path: Union[str, Path]
    ) -> Dict[str, Any]:
        """
        异步获取文件元信息
        
        Args:
            path: 文件路径
            
        Returns:
            Dict: 文件信息（大小、修改时间等）
        """
        return await asyncio.to_thread(
            self.file_manager.get_file_info,
            path
        )


# ============================================================
# 模块导出
# ============================================================

__all__ = [
    "AsyncFileOps",
]
