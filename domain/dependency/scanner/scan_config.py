# Scan Configuration
"""
扫描配置

职责：
- 定义扫描参数（黑名单目录、最大递归深度等）
- 支持从配置文件加载
"""

from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Set


@dataclass
class ScanConfig:
    """
    扫描配置
    
    控制依赖扫描的行为参数
    """
    # 最大递归深度（防止循环引用导致无限递归）
    max_recursion_depth: int = 10
    
    # 目录名黑名单（不扫描这些目录）
    blacklist_dirs: Set[str] = field(default_factory=lambda: {
        ".git",
        ".circuit_ai",
        "__pycache__",
        "node_modules",
        ".idea",
        ".vscode",
    })
    
    # Python 虚拟环境特征文件（用于检测任意命名的虚拟环境）
    venv_marker_files: Set[str] = field(default_factory=lambda: {
        "pyvenv.cfg",  # Python 3.3+ venv 标志文件
    })
    
    # 支持的电路文件扩展名
    circuit_extensions: Set[str] = field(default_factory=lambda: {
        ".cir",
        ".sp",
        ".spice",
        ".net",
        ".ckt",
        ".lib",
        ".sub",
        ".mod",
    })
    
    # 是否启用增量扫描（基于文件修改时间）
    enable_incremental: bool = True
    
    # 扫描超时时间（秒）
    scan_timeout_seconds: int = 60
    
    # 单个文件最大大小（字节），超过则跳过
    max_file_size_bytes: int = 10 * 1024 * 1024  # 10MB
    
    # 是否解析嵌套引用（.include 文件中的 .include）
    parse_nested_includes: bool = True
    
    def is_blacklisted(self, dir_name: str) -> bool:
        """检查目录是否在黑名单中"""
        return dir_name in self.blacklist_dirs
    
    def is_venv_directory(self, dir_path: Path) -> bool:
        """
        检测目录是否为 Python 虚拟环境
        
        通过特征文件检测，而非目录名，可识别任意命名的虚拟环境
        """
        for marker in self.venv_marker_files:
            if (dir_path / marker).exists():
                return True
        # 备选检测：检查是否存在典型的虚拟环境结构
        if (dir_path / "bin" / "python").exists() or (dir_path / "Scripts" / "python.exe").exists():
            return True
        return False
    
    def is_circuit_file(self, filename: str) -> bool:
        """检查是否为电路文件"""
        return any(filename.lower().endswith(ext) for ext in self.circuit_extensions)
    
    def to_dict(self) -> dict:
        """序列化为字典"""
        return {
            "max_recursion_depth": self.max_recursion_depth,
            "blacklist_dirs": list(self.blacklist_dirs),
            "circuit_extensions": list(self.circuit_extensions),
            "enable_incremental": self.enable_incremental,
            "scan_timeout_seconds": self.scan_timeout_seconds,
            "max_file_size_bytes": self.max_file_size_bytes,
            "parse_nested_includes": self.parse_nested_includes,
        }
    
    @classmethod
    def from_dict(cls, data: dict) -> "ScanConfig":
        """从字典反序列化"""
        config = cls()
        if "max_recursion_depth" in data:
            config.max_recursion_depth = data["max_recursion_depth"]
        if "blacklist_dirs" in data:
            config.blacklist_dirs = set(data["blacklist_dirs"])
        if "circuit_extensions" in data:
            config.circuit_extensions = set(data["circuit_extensions"])
        if "enable_incremental" in data:
            config.enable_incremental = data["enable_incremental"]
        if "scan_timeout_seconds" in data:
            config.scan_timeout_seconds = data["scan_timeout_seconds"]
        if "max_file_size_bytes" in data:
            config.max_file_size_bytes = data["max_file_size_bytes"]
        if "parse_nested_includes" in data:
            config.parse_nested_includes = data["parse_nested_includes"]
        return config


__all__ = ["ScanConfig"]
