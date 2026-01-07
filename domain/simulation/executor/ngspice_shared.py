# NgSpice Shared Library Wrapper
"""
ngspice 共享库封装模块

使用 ctypes 直接调用 ngspice C API，不依赖 PySpice，避免版本兼容性问题。

设计原则：
- 直接使用 ctypes 调用 ngspice 共享库
- 提供 Python 友好的接口
- 线程安全（使用 Lock 保护所有 ngspice 调用）

ngspice C API 封装：
- ngSpice_Init() - 初始化 ngspice，设置回调函数
- ngSpice_Circ() - 加载网表（字符串数组形式）
- ngSpice_Command() - 执行 ngspice 命令
- ngSpice_CurPlot() - 获取当前 plot 名称
- ngSpice_AllVecs() - 获取当前 plot 的所有向量名称
- ngGet_Vec_Info() - 获取向量数据

使用示例：
    from domain.simulation.executor.ngspice_shared import NgSpiceWrapper
    from infrastructure.utils.ngspice_config import get_ngspice_dll_path
    
    dll_path = get_ngspice_dll_path()
    ngspice = NgSpiceWrapper(dll_path)
    
    # 加载网表
    ngspice.load_netlist_file("circuit.cir")
    
    # 执行仿真
    ngspice.run()
    
    # 获取结果
    freq = ngspice.get_vector_data("frequency")
    vout = ngspice.get_complex_vector_data("v(out)")
"""

import ctypes
import logging
import platform
import threading
from ctypes import (
    CFUNCTYPE, POINTER, Structure, c_bool, c_char_p, c_double, c_int,
    c_short, c_void_p, pointer, cast, byref
)
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

import numpy as np


# ============================================================
# 异常定义
# ============================================================

class NgSpiceError(Exception):
    """ngspice 相关错误的基类"""
    pass


class NgSpiceLoadError(NgSpiceError):
    """ngspice DLL 加载失败"""
    pass


class NgSpiceInitError(NgSpiceError):
    """ngspice 初始化失败"""
    pass


class NgSpiceCommandError(NgSpiceError):
    """ngspice 命令执行失败"""
    pass


# ============================================================
# 数据结构定义
# ============================================================

@dataclass
class VectorInfo:
    """向量信息"""
    name: str                           # 向量名称
    type: int                           # 向量类型（电压/电流/频率/时间）
    length: int                         # 数据点数
    data: np.ndarray                    # 实数数据
    cdata: Optional[np.ndarray] = None  # 复数数据（AC 分析）


# ============================================================
# ngspice C 结构体定义
# ============================================================

class NgComplex(Structure):
    """ngspice 复数结构体"""
    _fields_ = [
        ("cx_real", c_double),
        ("cx_imag", c_double),
    ]


class VectorInfoC(Structure):
    """ngspice 向量信息结构体 (vector_info)"""
    _fields_ = [
        ("v_name", c_char_p),           # 向量名称
        ("v_type", c_int),              # 向量类型
        ("v_flags", c_short),           # 标志位
        ("v_realdata", POINTER(c_double)),  # 实数数据指针
        ("v_compdata", POINTER(NgComplex)), # 复数数据指针
        ("v_length", c_int),            # 数据长度
    ]


class VecValuesC(Structure):
    """ngspice 向量值结构体 (vecvalues)"""
    _fields_ = [
        ("name", c_char_p),
        ("creal", c_double),
        ("cimag", c_double),
        ("is_scale", c_bool),
        ("is_complex", c_bool),
    ]


class VecValuesAllC(Structure):
    """ngspice 所有向量值结构体 (vecvaluesall)"""
    _fields_ = [
        ("veccount", c_int),
        ("vecindex", c_int),
        ("vecsa", POINTER(POINTER(VecValuesC))),
    ]


class VecInfoC(Structure):
    """ngspice 向量信息结构体 (vecinfoall)"""
    _fields_ = [
        ("name", c_char_p),
        ("title", c_char_p),
        ("date", c_char_p),
        ("type", c_char_p),
        ("veccount", c_int),
        ("vecs", POINTER(POINTER(VecValuesC))),
    ]


# ============================================================
# 回调函数类型定义
# ============================================================

# SendChar: int (*SendChar)(char* outputreturn, int ident, void* userdata)
SEND_CHAR_FUNC = CFUNCTYPE(c_int, c_char_p, c_int, c_void_p)

# SendStat: int (*SendStat)(char* outputreturn, int ident, void* userdata)
SEND_STAT_FUNC = CFUNCTYPE(c_int, c_char_p, c_int, c_void_p)

# ControlledExit: int (*ControlledExit)(int exitstatus, bool immediate, bool quitexit, int ident, void* userdata)
CONTROLLED_EXIT_FUNC = CFUNCTYPE(c_int, c_int, c_bool, c_bool, c_int, c_void_p)

# SendData: int (*SendData)(pvecvaluesall, int, int, void*)
SEND_DATA_FUNC = CFUNCTYPE(c_int, POINTER(VecValuesAllC), c_int, c_int, c_void_p)

# SendInitData: int (*SendInitData)(pvecinfoall, int, void*)
SEND_INIT_DATA_FUNC = CFUNCTYPE(c_int, POINTER(VecInfoC), c_int, c_void_p)

# BGThreadRunning: int (*BGThreadRunning)(bool, int, void*)
BG_THREAD_RUNNING_FUNC = CFUNCTYPE(c_int, c_bool, c_int, c_void_p)


# ============================================================
# 向量类型常量
# ============================================================

class VectorType:
    """ngspice 向量类型常量"""
    SV_NOTYPE = 0
    SV_TIME = 1
    SV_FREQUENCY = 2
    SV_VOLTAGE = 3
    SV_CURRENT = 4
    SV_OUTPUT_N_DENS = 5
    SV_OUTPUT_NOISE = 6
    SV_INPUT_N_DENS = 7
    SV_INPUT_NOISE = 8
    SV_POLE = 9
    SV_ZERO = 10
    SV_SPARAM = 11
    SV_TEMP = 12
    SV_RES = 13
    SV_IMPEDANCE = 14
    SV_ADMITTANCE = 15
    SV_POWER = 16
    SV_PHASE = 17
    SV_DB = 18
    SV_CAPACITANCE = 19
    SV_CHARGE = 20


# ============================================================
# NgSpiceWrapper 类
# ============================================================

class NgSpiceWrapper:
    """
    ngspice 共享库封装类
    
    使用 ctypes 直接调用 ngspice C API，提供 Python 友好的接口。
    
    特性：
    - 线程安全：使用 Lock 保护所有 ngspice 调用
    - 回调收集：自动收集 ngspice 的 stdout/stderr 输出
    - 错误处理：命令执行失败时返回 False 并记录日志
    
    注意：
    - ngspice 共享库不是线程安全的，同一时间只能有一个仿真在执行
    - 实例化时会自动初始化 ngspice
    """
    
    # 类级别的实例计数器（用于 ngspice_id）
    _instance_counter = 0
    _instance_lock = threading.Lock()
    
    def __init__(self, dll_path: Optional[Path] = None):
        """
        初始化 NgSpiceWrapper
        
        Args:
            dll_path: ngspice 共享库路径，如果为 None 则自动从 ngspice_config 获取
            
        Raises:
            NgSpiceLoadError: DLL 加载失败
            NgSpiceInitError: ngspice 初始化失败
        """
        self._logger = logging.getLogger(__name__)
        self._lock = threading.Lock()
        
        # 输出收集
        self._stdout_lines: List[str] = []
        self._stderr_lines: List[str] = []
        self._status_lines: List[str] = []
        
        # ngspice 状态
        self._initialized = False
        self._ngspice_id = self._get_next_id()
        
        # 加载 DLL
        self._dll_path = dll_path or self._get_default_dll_path()
        self._ngspice = self._load_dll(self._dll_path)
        
        # 设置函数签名
        self._setup_function_signatures()
        
        # 创建回调函数（必须保持引用，否则会被垃圾回收）
        self._callbacks = self._create_callbacks()
        
        # 初始化 ngspice
        self._initialize()
    
    @classmethod
    def _get_next_id(cls) -> int:
        """获取下一个实例 ID"""
        with cls._instance_lock:
            cls._instance_counter += 1
            return cls._instance_counter
    
    def _get_default_dll_path(self) -> Path:
        """从 ngspice_config 获取默认 DLL 路径"""
        from infrastructure.utils.ngspice_config import get_ngspice_dll_path
        dll_path = get_ngspice_dll_path()
        if not dll_path:
            raise NgSpiceLoadError("无法获取 ngspice DLL 路径，请确保已调用 configure_ngspice()")
        return dll_path
    
    def _load_dll(self, dll_path: Path) -> ctypes.CDLL:
        """加载 ngspice 共享库"""
        if not dll_path.exists():
            raise NgSpiceLoadError(f"ngspice DLL 不存在: {dll_path}")
        
        try:
            # Windows 需要添加 DLL 目录到搜索路径
            if platform.system() == "Windows":
                dll_dir = dll_path.parent
                # 添加 DLL 目录到搜索路径
                import os
                os.add_dll_directory(str(dll_dir))
            
            ngspice = ctypes.CDLL(str(dll_path))
            self._logger.debug(f"ngspice DLL 加载成功: {dll_path}")
            return ngspice
            
        except OSError as e:
            raise NgSpiceLoadError(f"加载 ngspice DLL 失败: {e}")

    def _setup_function_signatures(self):
        """设置 ngspice 函数签名"""
        # ngSpice_Init
        self._ngspice.ngSpice_Init.argtypes = [
            SEND_CHAR_FUNC,         # SendChar
            SEND_STAT_FUNC,         # SendStat
            CONTROLLED_EXIT_FUNC,   # ControlledExit
            SEND_DATA_FUNC,         # SendData
            SEND_INIT_DATA_FUNC,    # SendInitData
            BG_THREAD_RUNNING_FUNC, # BGThreadRunning
            c_void_p,               # userdata
        ]
        self._ngspice.ngSpice_Init.restype = c_int
        
        # ngSpice_Init_Sync (同步模式初始化)
        try:
            self._ngspice.ngSpice_Init_Sync.argtypes = [
                SEND_CHAR_FUNC,
                SEND_STAT_FUNC,
                CONTROLLED_EXIT_FUNC,
                SEND_DATA_FUNC,
                SEND_INIT_DATA_FUNC,
                BG_THREAD_RUNNING_FUNC,
                c_void_p,
            ]
            self._ngspice.ngSpice_Init_Sync.restype = c_int
        except AttributeError:
            pass  # 旧版本可能没有这个函数
        
        # ngSpice_Command
        self._ngspice.ngSpice_Command.argtypes = [c_char_p]
        self._ngspice.ngSpice_Command.restype = c_int
        
        # ngSpice_Circ
        self._ngspice.ngSpice_Circ.argtypes = [POINTER(c_char_p)]
        self._ngspice.ngSpice_Circ.restype = c_int
        
        # ngSpice_CurPlot
        self._ngspice.ngSpice_CurPlot.argtypes = []
        self._ngspice.ngSpice_CurPlot.restype = c_char_p
        
        # ngSpice_AllPlots
        self._ngspice.ngSpice_AllPlots.argtypes = []
        self._ngspice.ngSpice_AllPlots.restype = POINTER(c_char_p)
        
        # ngSpice_AllVecs
        self._ngspice.ngSpice_AllVecs.argtypes = [c_char_p]
        self._ngspice.ngSpice_AllVecs.restype = POINTER(c_char_p)
        
        # ngGet_Vec_Info
        self._ngspice.ngGet_Vec_Info.argtypes = [c_char_p]
        self._ngspice.ngGet_Vec_Info.restype = POINTER(VectorInfoC)
        
        # ngSpice_running (检查是否正在运行)
        try:
            self._ngspice.ngSpice_running.argtypes = []
            self._ngspice.ngSpice_running.restype = c_bool
        except AttributeError:
            pass
    
    def _create_callbacks(self) -> Dict[str, Any]:
        """创建回调函数"""
        callbacks = {}
        
        # SendChar 回调 - 接收 ngspice 文本输出
        def send_char(output: bytes, ident: int, userdata: c_void_p) -> int:
            if output:
                try:
                    msg = output.decode('utf-8', errors='replace')
                    self._stdout_lines.append(msg)
                    # 检查是否是错误输出
                    if msg.startswith('stderr'):
                        self._stderr_lines.append(msg)
                except Exception:
                    pass
            return 0
        
        callbacks['send_char'] = SEND_CHAR_FUNC(send_char)
        
        # SendStat 回调 - 接收仿真状态
        def send_stat(status: bytes, ident: int, userdata: c_void_p) -> int:
            if status:
                try:
                    msg = status.decode('utf-8', errors='replace')
                    self._status_lines.append(msg)
                except Exception:
                    pass
            return 0
        
        callbacks['send_stat'] = SEND_STAT_FUNC(send_stat)
        
        # ControlledExit 回调 - 处理退出请求
        def controlled_exit(exitstatus: int, immediate: bool, quitexit: bool, 
                           ident: int, userdata: c_void_p) -> int:
            self._logger.debug(f"ngspice 请求退出: status={exitstatus}, immediate={immediate}")
            return exitstatus
        
        callbacks['controlled_exit'] = CONTROLLED_EXIT_FUNC(controlled_exit)
        
        # SendData 回调 - 接收仿真数据（可选）
        def send_data(vecvaluesall: POINTER(VecValuesAllC), count: int, 
                     ident: int, userdata: c_void_p) -> int:
            return 0
        
        callbacks['send_data'] = SEND_DATA_FUNC(send_data)
        
        # SendInitData 回调 - 接收初始化数据（可选）
        def send_init_data(vecinfoall: POINTER(VecInfoC), ident: int, 
                          userdata: c_void_p) -> int:
            return 0
        
        callbacks['send_init_data'] = SEND_INIT_DATA_FUNC(send_init_data)
        
        # BGThreadRunning 回调 - 后台线程状态
        def bg_thread_running(running: bool, ident: int, userdata: c_void_p) -> int:
            return 0
        
        callbacks['bg_thread_running'] = BG_THREAD_RUNNING_FUNC(bg_thread_running)
        
        return callbacks
    
    def _initialize(self):
        """初始化 ngspice"""
        with self._lock:
            try:
                result = self._ngspice.ngSpice_Init(
                    self._callbacks['send_char'],
                    self._callbacks['send_stat'],
                    self._callbacks['controlled_exit'],
                    self._callbacks['send_data'],
                    self._callbacks['send_init_data'],
                    self._callbacks['bg_thread_running'],
                    None,  # userdata
                )
                
                if result != 0:
                    raise NgSpiceInitError(f"ngSpice_Init 返回错误码: {result}")
                
                self._initialized = True
                self._logger.debug("ngspice 初始化成功")
                
            except Exception as e:
                raise NgSpiceInitError(f"ngspice 初始化失败: {e}")
    
    # ============================================================
    # 公开方法
    # ============================================================
    
    def load_netlist(self, netlist_lines: List[str]) -> bool:
        """
        加载网表
        
        Args:
            netlist_lines: 网表行列表（每行一个字符串）
            
        Returns:
            bool: 是否成功
        """
        with self._lock:
            try:
                # 清空之前的输出
                self._clear_output()
                
                # 转换为 C 字符串数组
                # ngSpice_Circ 需要以 NULL 结尾的字符串数组
                c_lines = [line.encode('utf-8') for line in netlist_lines]
                c_lines.append(None)  # NULL 结尾
                
                c_array = (c_char_p * len(c_lines))(*c_lines)
                
                result = self._ngspice.ngSpice_Circ(c_array)
                
                if result != 0:
                    self._logger.error(f"ngSpice_Circ 返回错误码: {result}")
                    return False
                
                return True
                
            except Exception as e:
                self._logger.exception(f"加载网表失败: {e}")
                return False
    
    def load_netlist_file(self, file_path: Path) -> bool:
        """
        从文件加载网表
        
        Args:
            file_path: 网表文件路径
            
        Returns:
            bool: 是否成功
        """
        try:
            path = Path(file_path)
            content = path.read_text(encoding='utf-8', errors='ignore')
            lines = content.splitlines()
            return self.load_netlist(lines)
        except Exception as e:
            self._logger.exception(f"读取网表文件失败: {e}")
            return False
    
    def run(self) -> bool:
        """
        执行仿真（执行 'run' 命令）
        
        Returns:
            bool: 是否成功
        """
        return self.execute_command("run")
    
    def execute_command(self, command: str) -> bool:
        """
        执行 ngspice 命令
        
        Args:
            command: ngspice 命令字符串
            
        Returns:
            bool: 是否成功
        """
        with self._lock:
            try:
                result = self._ngspice.ngSpice_Command(command.encode('utf-8'))
                
                if result != 0:
                    self._logger.error(f"ngSpice_Command '{command}' 返回错误码: {result}")
                    return False
                
                return True
                
            except Exception as e:
                self._logger.exception(f"执行命令失败: {command}, 错误: {e}")
                return False

    def get_current_plot(self) -> Optional[str]:
        """
        获取当前 plot 名称
        
        Returns:
            str: plot 名称，失败返回 None
        """
        with self._lock:
            try:
                result = self._ngspice.ngSpice_CurPlot()
                if result:
                    return result.decode('utf-8')
                return None
            except Exception as e:
                self._logger.exception(f"获取当前 plot 失败: {e}")
                return None
    
    def get_all_plots(self) -> List[str]:
        """
        获取所有 plot 名称
        
        Returns:
            List[str]: plot 名称列表
        """
        with self._lock:
            try:
                result = self._ngspice.ngSpice_AllPlots()
                plots = []
                if result:
                    i = 0
                    while result[i]:
                        plots.append(result[i].decode('utf-8'))
                        i += 1
                return plots
            except Exception as e:
                self._logger.exception(f"获取所有 plots 失败: {e}")
                return []
    
    def get_all_vectors(self, plot_name: Optional[str] = None) -> List[str]:
        """
        获取指定 plot 的所有向量名称
        
        Args:
            plot_name: plot 名称，如果为 None 则使用当前 plot
            
        Returns:
            List[str]: 向量名称列表
        """
        # 如果没有指定 plot_name，先在锁外获取当前 plot
        if plot_name is None:
            plot_name = self.get_current_plot()
            if not plot_name:
                return []
        
        with self._lock:
            try:
                result = self._ngspice.ngSpice_AllVecs(plot_name.encode('utf-8'))
                vectors = []
                if result:
                    i = 0
                    while result[i]:
                        vectors.append(result[i].decode('utf-8'))
                        i += 1
                return vectors
            except Exception as e:
                self._logger.exception(f"获取向量列表失败: {e}")
                return []
    
    def get_vector_info(self, vec_name: str) -> Optional[VectorInfo]:
        """
        获取向量完整信息
        
        Args:
            vec_name: 向量名称（如 "frequency"、"v(out)"）
            
        Returns:
            VectorInfo: 向量信息，失败返回 None
        """
        with self._lock:
            try:
                vec_ptr = self._ngspice.ngGet_Vec_Info(vec_name.encode('utf-8'))
                
                if not vec_ptr:
                    self._logger.warning(f"向量不存在: {vec_name}")
                    return None
                
                vec = vec_ptr.contents
                length = vec.v_length
                
                if length <= 0:
                    return None
                
                # 提取数据
                data = None
                cdata = None
                
                if vec.v_realdata:
                    # 实数数据
                    data = np.array([vec.v_realdata[i] for i in range(length)])
                
                if vec.v_compdata:
                    # 复数数据
                    cdata = np.array([
                        complex(vec.v_compdata[i].cx_real, vec.v_compdata[i].cx_imag)
                        for i in range(length)
                    ])
                
                return VectorInfo(
                    name=vec.v_name.decode('utf-8') if vec.v_name else vec_name,
                    type=vec.v_type,
                    length=length,
                    data=data if data is not None else np.array([]),
                    cdata=cdata,
                )
                
            except Exception as e:
                self._logger.exception(f"获取向量信息失败: {vec_name}, 错误: {e}")
                return None
    
    def get_vector_data(self, vec_name: str) -> Optional[np.ndarray]:
        """
        获取向量实数数据
        
        Args:
            vec_name: 向量名称
            
        Returns:
            np.ndarray: 实数数据数组，失败返回 None
        """
        info = self.get_vector_info(vec_name)
        if info and info.data is not None and len(info.data) > 0:
            return info.data
        return None
    
    def get_complex_vector_data(self, vec_name: str) -> Optional[np.ndarray]:
        """
        获取向量复数数据（用于 AC 分析）
        
        Args:
            vec_name: 向量名称
            
        Returns:
            np.ndarray: 复数数据数组，失败返回 None
        """
        info = self.get_vector_info(vec_name)
        if info and info.cdata is not None and len(info.cdata) > 0:
            return info.cdata
        return None
    
    def get_stdout(self) -> str:
        """
        获取 ngspice 输出日志
        
        Returns:
            str: 输出日志文本
        """
        return '\n'.join(self._stdout_lines)
    
    def get_stderr(self) -> str:
        """
        获取 ngspice 错误输出
        
        Returns:
            str: 错误输出文本
        """
        return '\n'.join(self._stderr_lines)
    
    def get_status(self) -> str:
        """
        获取 ngspice 状态输出
        
        Returns:
            str: 状态输出文本
        """
        return '\n'.join(self._status_lines)
    
    def halt(self) -> bool:
        """
        停止当前仿真
        
        Returns:
            bool: 是否成功
        """
        return self.execute_command("bg_halt")
    
    def reset(self) -> bool:
        """
        重置 ngspice 状态
        
        Returns:
            bool: 是否成功
        """
        # 清空输出
        self._clear_output()
        # 执行 reset 命令
        return self.execute_command("reset")
    
    def destroy(self) -> bool:
        """
        销毁当前电路
        
        Returns:
            bool: 是否成功
        """
        self._clear_output()
        return self.execute_command("destroy all")
    
    def is_running(self) -> bool:
        """
        检查是否正在运行仿真
        
        Returns:
            bool: 是否正在运行
        """
        try:
            return self._ngspice.ngSpice_running()
        except AttributeError:
            return False
    
    def _clear_output(self):
        """清空输出缓冲区"""
        self._stdout_lines.clear()
        self._stderr_lines.clear()
        self._status_lines.clear()
    
    @property
    def initialized(self) -> bool:
        """是否已初始化"""
        return self._initialized
    
    @property
    def dll_path(self) -> Path:
        """DLL 路径"""
        return self._dll_path


# ============================================================
# 模块级单例（可选）
# ============================================================

_default_wrapper: Optional[NgSpiceWrapper] = None
_wrapper_lock = threading.Lock()


def get_default_wrapper() -> NgSpiceWrapper:
    """
    获取默认的 NgSpiceWrapper 实例（单例模式）
    
    Returns:
        NgSpiceWrapper: 默认实例
    """
    global _default_wrapper
    with _wrapper_lock:
        if _default_wrapper is None:
            _default_wrapper = NgSpiceWrapper()
        return _default_wrapper


def reset_default_wrapper():
    """重置默认实例"""
    global _default_wrapper
    with _wrapper_lock:
        _default_wrapper = None


# ============================================================
# 模块导出
# ============================================================

__all__ = [
    "NgSpiceWrapper",
    "NgSpiceError",
    "NgSpiceLoadError",
    "NgSpiceInitError",
    "NgSpiceCommandError",
    "VectorInfo",
    "VectorType",
    "get_default_wrapper",
    "reset_default_wrapper",
]
