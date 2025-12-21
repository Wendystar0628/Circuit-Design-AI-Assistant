# Scan Configuration
"""
扫描配置

职责：
- 定义扫描参数（黑名单目录、最大递归深度等）
- 支持从配置文件加载
"""

from dataclasses import dataclass, field
from typing import List, Set


@dataclass
class ScanConfig:
    """
    扫描配置
    
    控制依赖扫描的行为参数
    """
    # 最大递归深度（防止循环引用导致无限递归）
    max_recursion_depth: int = 10
    
    # 目录黑名单（不扫描这些目录）
    blacklist_dirs: Set[str] = field(default_factory=lambda: {
        ".git",
        ".circuit_ai",
        "__pycache__",
        ".venv",
        "venv",
        "node_modules",
        ".idea",
        ".vscode",
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
