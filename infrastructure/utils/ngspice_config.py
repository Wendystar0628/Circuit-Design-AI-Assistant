"""
ngspice 运行时路径配置模块

⚠️ 关键约束：此模块必须在任何 PySpice 导入之前执行，否则 PySpice 会使用默认路径导致加载失败

职责：
- 检测运行环境（开发环境 vs PyInstaller 打包环境）
- 检测操作系统类型
- 配置 ngspice 共享库路径
- 设置必要的环境变量（PATH, SPICE_LIB_DIR, SPICE_SCRIPTS）
- 覆盖 PySpice 默认路径配置

调用时机：
- 在 main.py 的最开始调用，位于所有其他导入之前
- 确保在 Phase 0 基础设施初始化之前完成

使用示例：
    # main.py 顶部
    from infrastructure.utils.ngspice_config import configure_ngspice
    if not configure_ngspice():
        print("[WARNING] ngspice 配置失败，仿真功能可能不可用")
"""

import os
import sys
import platform
import shutil
from pathlib import Path
from typing import Optional


# ============================================================
# 平台常量定义
# ============================================================

PLATFORM_WINDOWS = "Windows"
PLATFORM_LINUX = "Linux"
PLATFORM_MACOS = "Darwin"

# 相对于项目根目录的 vendor 路径
VENDOR_NGSPICE_DIR = "vendor/ngspice"

# 各平台的子目录和库文件配置
PLATFORM_CONFIG = {
    PLATFORM_WINDOWS: {
        "subdir": "win64/Spice64_dll",      # 平台子目录
        "dll_dir": "dll-vs",                 # DLL 所在子目录
        "lib_name": "ngspice.dll",           # 共享库文件名
        "lib_dir": "lib/ngspice",            # 模型库目录
        "scripts_dir": "share/ngspice/scripts",  # 脚本目录
    },
    PLATFORM_LINUX: {
        "subdir": "linux64",
        "dll_dir": "",
        "lib_name": "libngspice.so",
        "lib_dir": "lib/ngspice",
        "scripts_dir": "share/ngspice/scripts",
    },
    PLATFORM_MACOS: {
        "subdir": "macos",
        "dll_dir": "",
        "lib_name": "libngspice.dylib",
        "lib_dir": "lib/ngspice",
        "scripts_dir": "share/ngspice/scripts",
    },
}


# ============================================================
# 模块级状态变量
# ============================================================

_ngspice_configured: bool = False       # 是否已执行配置
_ngspice_available: bool = False        # ngspice 是否可用
_ngspice_path: Optional[Path] = None    # ngspice 共享库路径
_configuration_error: Optional[str] = None  # 配置错误信息


# ============================================================
# 内部辅助函数
# ============================================================

def _is_packaged() -> bool:
    """
    检测是否为 PyInstaller 打包环境
    
    PyInstaller 打包后，会设置 sys._MEIPASS 指向临时解压目录
    
    Returns:
        bool: True 表示打包环境，False 表示开发环境
    """
    return getattr(sys, '_MEIPASS', None) is not None


def _get_base_path() -> Path:
    """
    获取基础路径（项目根目录或打包临时目录）
    
    开发环境：返回 circuit_design_ai/ 目录
    打包环境：返回 sys._MEIPASS 临时目录
    
    Returns:
        Path: 基础路径
    """
    if _is_packaged():
        # PyInstaller 打包环境
        return Path(sys._MEIPASS)
    else:
        # 开发环境：从当前文件向上三级到达 circuit_design_ai/
        # ngspice_config.py -> utils/ -> infrastructure/ -> circuit_design_ai/
        return Path(__file__).parent.parent.parent


def _get_platform() -> str:
    """
    获取当前平台标识
    
    Returns:
        str: 平台标识（Windows/Linux/Darwin）
    """
    return platform.system()


def _find_ngspice_path(base_path: Path, platform_id: str) -> Optional[Path]:
    """
    查找 ngspice 共享库路径
    
    Args:
        base_path: 基础路径（项目根目录或打包临时目录）
        platform_id: 平台标识
        
    Returns:
        Path: ngspice 基础目录路径（包含 dll-vs/, lib/, share/ 等），
              如果未找到则返回 None
    """
    if platform_id not in PLATFORM_CONFIG:
        return None
    
    config = PLATFORM_CONFIG[platform_id]
    
    # 构建 ngspice 基础目录路径
    ngspice_base = base_path / VENDOR_NGSPICE_DIR / config["subdir"]
    
    # 构建共享库完整路径
    if config["dll_dir"]:
        lib_path = ngspice_base / config["dll_dir"] / config["lib_name"]
    else:
        lib_path = ngspice_base / config["lib_name"]
    
    # 验证共享库文件是否存在
    if lib_path.exists():
        return ngspice_base
    
    return None


def _validate_ngspice_path(ngspice_base: Path, platform_id: str) -> bool:
    """
    验证 ngspice 路径的完整性
    
    检查必要的文件和目录是否存在
    
    Args:
        ngspice_base: ngspice 基础目录
        platform_id: 平台标识
        
    Returns:
        bool: 路径是否有效
    """
    if not ngspice_base or not ngspice_base.exists():
        return False
    
    config = PLATFORM_CONFIG.get(platform_id)
    if not config:
        return False
    
    # 检查共享库文件
    if config["dll_dir"]:
        lib_path = ngspice_base / config["dll_dir"] / config["lib_name"]
    else:
        lib_path = ngspice_base / config["lib_name"]
    
    if not lib_path.exists():
        return False
    
    # 模型库目录是可选的，但如果存在则更好
    lib_dir = ngspice_base / config["lib_dir"]
    if not lib_dir.exists():
        # 仅警告，不阻止
        pass
    
    return True


# ============================================================
# 公开接口
# ============================================================

def get_ngspice_path() -> Optional[Path]:
    """
    获取当前平台的 ngspice 基础目录路径（Spice64_dll 目录）
    
    注意：必须先调用 configure_ngspice() 才能获取有效路径
    
    Returns:
        Path: ngspice 基础目录路径，不可用时返回 None
    """
    return _ngspice_path


def get_ngspice_lib_path() -> Optional[Path]:
    """
    获取 lib/ngspice 目录路径（codemodel 和 OSDI 文件）
    
    此目录包含：
    - analog.cm, digital.cm 等 codemodel 文件
    - *.osdi OSDI 模型文件
    
    注意：必须先调用 configure_ngspice() 才能获取有效路径
    
    Returns:
        Path: lib/ngspice 目录路径，不可用时返回 None
    """
    if not _ngspice_path:
        return None
    
    platform_id = _get_platform()
    config = PLATFORM_CONFIG.get(platform_id)
    if not config:
        return None
    
    lib_path = _ngspice_path / config["lib_dir"]
    return lib_path if lib_path.exists() else None


def get_ngspice_models_path() -> Optional[Path]:
    """
    获取 share/ngspice/models 目录路径（cmp/sub/custom）
    
    此目录包含：
    - cmp/ - 基础器件模型参数（BJT、MOSFET、二极管等）
    - sub/ - 子电路定义（运放、稳压器等）
    - custom/ - 用户自定义模型
    
    注意：必须先调用 configure_ngspice() 才能获取有效路径
    
    Returns:
        Path: share/ngspice/models 目录路径，不可用时返回 None
    """
    if not _ngspice_path:
        return None
    
    models_path = _ngspice_path / "share" / "ngspice" / "models"
    return models_path if models_path.exists() else None


def get_ngspice_scripts_path() -> Optional[Path]:
    """
    获取 share/ngspice/scripts 目录路径（spinit 模板）
    
    此目录包含 spinit 初始化脚本模板
    
    注意：必须先调用 configure_ngspice() 才能获取有效路径
    
    Returns:
        Path: share/ngspice/scripts 目录路径，不可用时返回 None
    """
    if not _ngspice_path:
        return None
    
    platform_id = _get_platform()
    config = PLATFORM_CONFIG.get(platform_id)
    if not config:
        return None
    
    scripts_path = _ngspice_path / config["scripts_dir"]
    return scripts_path if scripts_path.exists() else None


def _setup_environment(ngspice_base: Path, platform_id: str) -> None:
    """
    设置 ngspice 相关的环境变量
    
    注意：这些环境变量必须在 ngspice 共享库加载之前设置
    
    Args:
        ngspice_base: ngspice 基础目录
        platform_id: 平台标识
    """
    config = PLATFORM_CONFIG[platform_id]
    
    # 1. 将 DLL 目录添加到 PATH（主要用于 Windows）
    if platform_id == PLATFORM_WINDOWS and config["dll_dir"]:
        dll_dir = ngspice_base / config["dll_dir"]
        if dll_dir.exists():
            current_path = os.environ.get("PATH", "")
            dll_dir_str = str(dll_dir)
            # 避免重复添加
            if dll_dir_str not in current_path:
                os.environ["PATH"] = dll_dir_str + os.pathsep + current_path
    
    # 2. 设置 SPICE_LIB_DIR（模型库目录 - .cm 文件）
    lib_dir = ngspice_base / config["lib_dir"]
    if lib_dir.exists():
        # 使用正斜杠路径，ngspice 在 Windows 上也使用正斜杠
        os.environ["SPICE_LIB_DIR"] = str(lib_dir).replace("\\", "/")
    
    # 3. 设置 SPICE_SCRIPTS（脚本目录，可选）
    scripts_dir = ngspice_base / config["scripts_dir"]
    if scripts_dir.exists():
        os.environ["SPICE_SCRIPTS"] = str(scripts_dir).replace("\\", "/")
    
    # 4. 设置 NGSPICE_LIBRARY_PATH（某些版本的 ngspice 使用此变量）
    if config["dll_dir"]:
        dll_path = ngspice_base / config["dll_dir"] / config["lib_name"]
    else:
        dll_path = ngspice_base / config["lib_name"]
    if dll_path.exists():
        os.environ["NGSPICE_LIBRARY_PATH"] = str(dll_path).replace("\\", "/")


def _configure_pyspice(ngspice_base: Path, platform_id: str) -> bool:
    """
    覆盖 PySpice 的默认 ngspice 路径配置
    
    注意：这必须在 PySpice 首次使用 NgSpiceShared 之前执行
    
    Args:
        ngspice_base: ngspice 基础目录
        platform_id: 平台标识
        
    Returns:
        bool: 配置是否成功
    """
    try:
        # 延迟导入，避免在配置前触发 PySpice 的路径检测
        from PySpice.Spice.NgSpice.Shared import NgSpiceShared
        
        config = PLATFORM_CONFIG[platform_id]
        
        # 构建共享库完整路径
        if config["dll_dir"]:
            lib_path = ngspice_base / config["dll_dir"] / config["lib_name"]
        else:
            lib_path = ngspice_base / config["lib_name"]
        
        # 设置 PySpice 的库路径
        # NgSpiceShared 会使用这个路径加载共享库
        NgSpiceShared.LIBRARY_PATH = str(lib_path)
        
        return True
        
    except ImportError:
        # PySpice 未安装，跳过配置
        return True  # 不算失败，只是 PySpice 不可用
    except Exception as e:
        # 其他错误
        global _configuration_error
        _configuration_error = f"PySpice 配置失败: {e}"
        return False


def configure_ngspice() -> bool:
    """
    配置 ngspice 路径，必须在导入 PySpice 之前调用
    
    此函数执行以下步骤：
    1. 检测运行环境和平台
    2. 查找内嵌的 ngspice 共享库
    3. 设置环境变量
    4. 配置 PySpice 路径
    5. 如果内嵌版本不可用，尝试系统版本
    
    Returns:
        bool: 配置是否成功
    """
    global _ngspice_configured, _ngspice_available, _ngspice_path, _configuration_error
    
    # 避免重复配置
    if _ngspice_configured:
        return _ngspice_available
    
    _ngspice_configured = True
    _configuration_error = None
    
    # 获取平台信息
    platform_id = _get_platform()
    if platform_id not in PLATFORM_CONFIG:
        _configuration_error = f"不支持的平台: {platform_id}"
        return False
    
    # 获取基础路径
    base_path = _get_base_path()
    
    # 查找内嵌的 ngspice
    ngspice_base = _find_ngspice_path(base_path, platform_id)
    
    if ngspice_base and _validate_ngspice_path(ngspice_base, platform_id):
        # 找到内嵌版本
        _ngspice_path = ngspice_base
        
        # 设置环境变量
        _setup_environment(ngspice_base, platform_id)
        
        # 配置 PySpice
        if _configure_pyspice(ngspice_base, platform_id):
            _ngspice_available = True
            return True
    
    # 内嵌版本不可用，尝试系统版本
    system_path = _try_system_ngspice(platform_id)
    if system_path:
        _ngspice_path = system_path
        _ngspice_available = True
        return True
    
    # 所有尝试都失败
    if not _configuration_error:
        _configuration_error = "未找到可用的 ngspice 共享库"
    
    return False


def _try_system_ngspice(platform_id: str) -> Optional[Path]:
    """
    尝试使用系统安装的 ngspice（回退机制）
    
    Args:
        platform_id: 平台标识
        
    Returns:
        Path: 系统 ngspice 路径，未找到返回 None
    """
    config = PLATFORM_CONFIG.get(platform_id)
    if not config:
        return None
    
    lib_name = config["lib_name"]
    
    if platform_id == PLATFORM_WINDOWS:
        # Windows: 检查 PATH 中是否有 ngspice.dll
        # 或者检查常见安装位置
        common_paths = [
            Path("C:/Spice64/bin-dll"),
            Path("C:/Program Files/Spice64/bin-dll"),
            Path("C:/Program Files (x86)/Spice64/bin-dll"),
        ]
        for path in common_paths:
            lib_path = path / lib_name
            if lib_path.exists():
                return path.parent
        
        # 尝试使用 shutil.which 查找
        ngspice_exe = shutil.which("ngspice")
        if ngspice_exe:
            ngspice_dir = Path(ngspice_exe).parent
            lib_path = ngspice_dir / lib_name
            if lib_path.exists():
                return ngspice_dir.parent
    
    elif platform_id == PLATFORM_LINUX:
        # Linux: 检查常见库路径
        common_paths = [
            Path("/usr/lib"),
            Path("/usr/lib64"),
            Path("/usr/local/lib"),
            Path("/usr/lib/x86_64-linux-gnu"),
        ]
        for path in common_paths:
            lib_path = path / lib_name
            if lib_path.exists():
                return path
    
    elif platform_id == PLATFORM_MACOS:
        # macOS: 检查 Homebrew 和常见路径
        common_paths = [
            Path("/usr/local/lib"),
            Path("/opt/homebrew/lib"),
            Path("/usr/lib"),
        ]
        for path in common_paths:
            lib_path = path / lib_name
            if lib_path.exists():
                return path
    
    return None


def is_ngspice_available() -> bool:
    """
    检查 ngspice 是否可用
    
    注意：必须先调用 configure_ngspice() 才能获取准确结果
    
    Returns:
        bool: ngspice 是否已正确配置且可用
    """
    return _ngspice_available


def get_configuration_error() -> Optional[str]:
    """
    获取配置错误信息（如果有）
    
    Returns:
        str: 错误信息，无错误时返回 None
    """
    return _configuration_error


def get_ngspice_info() -> dict:
    """
    获取 ngspice 配置的详细信息
    
    用于调试和诊断
    
    Returns:
        dict: 包含配置状态的字典
    """
    lib_path = get_ngspice_lib_path()
    models_path = get_ngspice_models_path()
    scripts_path = get_ngspice_scripts_path()
    
    return {
        "configured": _ngspice_configured,
        "available": _ngspice_available,
        "path": str(_ngspice_path) if _ngspice_path else None,
        "lib_path": str(lib_path) if lib_path else None,
        "models_path": str(models_path) if models_path else None,
        "scripts_path": str(scripts_path) if scripts_path else None,
        "error": _configuration_error,
        "platform": _get_platform(),
        "packaged": _is_packaged(),
        "base_path": str(_get_base_path()),
    }


# ============================================================
# 模块导出
# ============================================================

__all__ = [
    "configure_ngspice",
    "get_ngspice_path",
    "get_ngspice_lib_path",
    "get_ngspice_models_path",
    "get_ngspice_scripts_path",
    "is_ngspice_available",
    "get_configuration_error",
    "get_ngspice_info",
]
