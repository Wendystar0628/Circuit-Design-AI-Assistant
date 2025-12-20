# JSON Repository - JSON File Storage Operations
"""
JSON存储操作

职责：
- 封装JSON文件的序列化/反序列化操作
- 提供类型安全的存取接口

初始化顺序：
- 无需显式初始化，作为工具类按需实例化
- 依赖 file_manager（底层文件操作）

使用场景：
- design_goals.json - 设计目标存储

说明：
- 对话历史由 Checkpointer 统一管理，不再使用独立的 JSON 文件
- 迭代历史从 SqliteSaver 查询，不再使用独立的 JSON 文件

使用示例：
    from infrastructure.persistence.json_repository import JsonRepository
    
    repo = JsonRepository()
    
    # 加载 JSON
    data = repo.load_json("config.json", default={})
    
    # 保存 JSON
    repo.save_json("config.json", {"key": "value"})
    
    # 部分更新
    repo.update_json("config.json", {"new_key": "new_value"})
    
    # 向数组追加
    repo.append_to_json_array("history.json", {"event": "new"})
"""

import json
from pathlib import Path
from typing import Any, Dict, List, Optional, Union


class JsonRepository:
    """
    JSON存储操作类
    
    封装JSON文件的读写操作，依赖 FileManager 进行底层文件操作
    """
    
    def __init__(self):
        """初始化 JSON 仓库"""
        self._file_manager = None
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
    def logger(self):
        """延迟获取日志器"""
        if self._logger is None:
            try:
                from infrastructure.utils.logger import get_logger
                self._logger = get_logger("json_repository")
            except Exception:
                pass
        return self._logger
    
    # ============================================================
    # 核心功能
    # ============================================================
    
    def load_json(
        self,
        path: Union[str, Path],
        default: Any = None,
        encoding: str = 'utf-8'
    ) -> Any:
        """
        加载JSON文件
        
        Args:
            path: JSON文件路径
            default: 解析失败或文件不存在时返回的默认值
            encoding: 文件编码
            
        Returns:
            解析后的数据，失败时返回默认值
        """
        try:
            # 使用 FileManager 读取文件
            if self.file_manager is not None:
                if not self.file_manager.file_exists(path):
                    if self.logger:
                        self.logger.debug(f"JSON文件不存在，返回默认值: {path}")
                    return default
                
                content = self.file_manager.read_file(path, encoding=encoding)
            else:
                # 降级：直接读取文件
                file_path = Path(path)
                if not file_path.exists():
                    return default
                content = file_path.read_text(encoding=encoding)
            
            # 解析 JSON
            data = json.loads(content)
            
            if self.logger:
                self.logger.debug(f"JSON文件加载成功: {path}")
            
            return data
            
        except json.JSONDecodeError as e:
            if self.logger:
                self.logger.warning(f"JSON解析失败: {path} - {e}")
            return default
        except Exception as e:
            if self.logger:
                self.logger.warning(f"JSON文件加载失败: {path} - {e}")
            return default
    
    def save_json(
        self,
        path: Union[str, Path],
        data: Any,
        indent: int = 2,
        ensure_ascii: bool = False,
        encoding: str = 'utf-8'
    ) -> bool:
        """
        保存数据为JSON文件
        
        Args:
            path: JSON文件路径
            data: 要保存的数据
            indent: 缩进空格数
            ensure_ascii: 是否转义非ASCII字符
            encoding: 文件编码
            
        Returns:
            bool: 是否成功
        """
        try:
            # 序列化为 JSON 字符串
            content = json.dumps(
                data,
                indent=indent,
                ensure_ascii=ensure_ascii,
                default=self._json_serializer
            )
            
            # 使用 FileManager 写入文件
            if self.file_manager is not None:
                self.file_manager.write_file(path, content, encoding=encoding)
            else:
                # 降级：直接写入文件
                file_path = Path(path)
                file_path.parent.mkdir(parents=True, exist_ok=True)
                file_path.write_text(content, encoding=encoding)
            
            if self.logger:
                self.logger.debug(f"JSON文件保存成功: {path}")
            
            return True
            
        except Exception as e:
            if self.logger:
                self.logger.error(f"JSON文件保存失败: {path} - {e}")
            return False
    
    def update_json(
        self,
        path: Union[str, Path],
        updates: Dict[str, Any],
        encoding: str = 'utf-8'
    ) -> bool:
        """
        部分更新JSON文件（合并字典）
        
        Args:
            path: JSON文件路径
            updates: 要更新的键值对
            encoding: 文件编码
            
        Returns:
            bool: 是否成功
        """
        try:
            # 加载现有数据
            data = self.load_json(path, default={}, encoding=encoding)
            
            if not isinstance(data, dict):
                if self.logger:
                    self.logger.warning(f"JSON文件不是字典类型，无法合并更新: {path}")
                return False
            
            # 合并更新
            data.update(updates)
            
            # 保存
            return self.save_json(path, data, encoding=encoding)
            
        except Exception as e:
            if self.logger:
                self.logger.error(f"JSON文件更新失败: {path} - {e}")
            return False
    
    def append_to_json_array(
        self,
        path: Union[str, Path],
        item: Any,
        encoding: str = 'utf-8'
    ) -> bool:
        """
        向JSON数组追加元素
        
        Args:
            path: JSON文件路径
            item: 要追加的元素
            encoding: 文件编码
            
        Returns:
            bool: 是否成功
        """
        try:
            # 加载现有数据
            data = self.load_json(path, default=[], encoding=encoding)
            
            if not isinstance(data, list):
                if self.logger:
                    self.logger.warning(f"JSON文件不是数组类型，无法追加: {path}")
                return False
            
            # 追加元素
            data.append(item)
            
            # 保存
            return self.save_json(path, data, encoding=encoding)
            
        except Exception as e:
            if self.logger:
                self.logger.error(f"JSON数组追加失败: {path} - {e}")
            return False
    
    def delete_from_json_array(
        self,
        path: Union[str, Path],
        index: int,
        encoding: str = 'utf-8'
    ) -> bool:
        """
        从JSON数组删除指定索引的元素
        
        Args:
            path: JSON文件路径
            index: 要删除的元素索引
            encoding: 文件编码
            
        Returns:
            bool: 是否成功
        """
        try:
            data = self.load_json(path, default=[], encoding=encoding)
            
            if not isinstance(data, list):
                if self.logger:
                    self.logger.warning(f"JSON文件不是数组类型: {path}")
                return False
            
            if index < 0 or index >= len(data):
                if self.logger:
                    self.logger.warning(f"索引越界: {index}, 数组长度: {len(data)}")
                return False
            
            del data[index]
            return self.save_json(path, data, encoding=encoding)
            
        except Exception as e:
            if self.logger:
                self.logger.error(f"JSON数组删除失败: {path} - {e}")
            return False
    
    def get_json_value(
        self,
        path: Union[str, Path],
        key: str,
        default: Any = None,
        encoding: str = 'utf-8'
    ) -> Any:
        """
        获取JSON文件中指定键的值
        
        支持点号分隔的嵌套键，如 "a.b.c"
        
        Args:
            path: JSON文件路径
            key: 键名（支持点号分隔的嵌套键）
            default: 键不存在时返回的默认值
            encoding: 文件编码
            
        Returns:
            键对应的值，不存在时返回默认值
        """
        try:
            data = self.load_json(path, default={}, encoding=encoding)
            
            # 处理嵌套键
            keys = key.split('.')
            value = data
            
            for k in keys:
                if isinstance(value, dict) and k in value:
                    value = value[k]
                else:
                    return default
            
            return value
            
        except Exception as e:
            if self.logger:
                self.logger.warning(f"获取JSON值失败: {path}[{key}] - {e}")
            return default
    
    def set_json_value(
        self,
        path: Union[str, Path],
        key: str,
        value: Any,
        encoding: str = 'utf-8'
    ) -> bool:
        """
        设置JSON文件中指定键的值
        
        支持点号分隔的嵌套键，如 "a.b.c"
        
        Args:
            path: JSON文件路径
            key: 键名（支持点号分隔的嵌套键）
            value: 要设置的值
            encoding: 文件编码
            
        Returns:
            bool: 是否成功
        """
        try:
            data = self.load_json(path, default={}, encoding=encoding)
            
            if not isinstance(data, dict):
                data = {}
            
            # 处理嵌套键
            keys = key.split('.')
            current = data
            
            for k in keys[:-1]:
                if k not in current or not isinstance(current[k], dict):
                    current[k] = {}
                current = current[k]
            
            current[keys[-1]] = value
            
            return self.save_json(path, data, encoding=encoding)
            
        except Exception as e:
            if self.logger:
                self.logger.error(f"设置JSON值失败: {path}[{key}] - {e}")
            return False
    
    # ============================================================
    # 辅助方法
    # ============================================================
    
    def _json_serializer(self, obj: Any) -> Any:
        """
        自定义JSON序列化器
        
        处理无法直接序列化的类型
        """
        from datetime import datetime, date
        from pathlib import Path
        
        if isinstance(obj, (datetime, date)):
            return obj.isoformat()
        elif isinstance(obj, Path):
            return str(obj)
        elif hasattr(obj, '__dict__'):
            return obj.__dict__
        else:
            raise TypeError(f"Object of type {type(obj)} is not JSON serializable")


# ============================================================
# 模块导出
# ============================================================

__all__ = [
    "JsonRepository",
]
