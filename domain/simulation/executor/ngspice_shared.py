"""Per-worker binding for the ngspice shared-library API.

ngspice keeps callbacks, the active circuit, plots and its background worker
in process-global C state. Loading the same DLL into several Python objects
does not create independent simulators. This module therefore owns exactly
one :class:`NgSpiceWrapper` per process.

Only the operations needed by ``SpiceExecutor`` are exposed. ``bg_run`` supports
cooperative cancellation inside the worker. ``ProcessSpiceExecutor`` enforces
the hard deadline outside the DLL, including native calls that never return.
Native vectors are copied before their plots can be destroyed.
"""

from __future__ import annotations

import ctypes
import logging
import math
import os
import platform
import re
import threading
import time
from ctypes import (
    CFUNCTYPE,
    POINTER,
    Structure,
    c_bool,
    c_char_p,
    c_double,
    c_int,
    c_short,
    c_void_p,
)
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Protocol

import numpy as np

from domain.simulation.spice.directive_tokenizer import is_spice_end_directive


class NgSpiceError(Exception):
    """Base class for failures at the shared-library boundary."""


class NgSpiceLoadError(NgSpiceError):
    """The ngspice shared library could not be loaded."""


class NgSpiceInitError(NgSpiceError):
    """The loaded shared library could not be initialized."""


class NgSpiceCommandError(NgSpiceError):
    """ngspice rejected a command or entered a broken state."""


class NgSpiceTimeoutError(NgSpiceCommandError):
    """A background simulation exceeded its deadline."""


class NgSpiceCancelledError(NgSpiceCommandError):
    """A background simulation was stopped by its owning job."""


class _CancellationSignal(Protocol):
    def is_set(self) -> bool: ...

    def wait(self, timeout: Optional[float] = None) -> bool: ...


@dataclass(frozen=True)
class VectorInfo:
    """A detached copy of one native ngspice vector."""

    name: str
    type: int
    length: int
    data: np.ndarray
    cdata: Optional[np.ndarray] = None


class NgComplex(Structure):
    _fields_ = [("cx_real", c_double), ("cx_imag", c_double)]


class VectorInfoC(Structure):
    _fields_ = [
        ("v_name", c_char_p),
        ("v_type", c_int),
        ("v_flags", c_short),
        ("v_realdata", POINTER(c_double)),
        ("v_compdata", POINTER(NgComplex)),
        ("v_length", c_int),
    ]


class VecValuesC(Structure):
    _fields_ = [
        ("name", c_char_p),
        ("creal", c_double),
        ("cimag", c_double),
        ("is_scale", c_bool),
        ("is_complex", c_bool),
    ]


class VecValuesAllC(Structure):
    _fields_ = [
        ("veccount", c_int),
        ("vecindex", c_int),
        ("vecsa", POINTER(POINTER(VecValuesC))),
    ]


class VecInfoDetailC(Structure):
    _fields_ = [
        ("number", c_int),
        ("vecname", c_char_p),
        ("is_real", c_bool),
        ("pdvec", c_void_p),
        ("pdvecscale", c_void_p),
    ]


class VecInfoAllC(Structure):
    _fields_ = [
        ("name", c_char_p),
        ("title", c_char_p),
        ("date", c_char_p),
        ("type", c_char_p),
        ("veccount", c_int),
        ("vecs", POINTER(POINTER(VecInfoDetailC))),
    ]


SEND_CHAR_FUNC = CFUNCTYPE(c_int, c_char_p, c_int, c_void_p)
SEND_STAT_FUNC = CFUNCTYPE(c_int, c_char_p, c_int, c_void_p)
CONTROLLED_EXIT_FUNC = CFUNCTYPE(c_int, c_int, c_bool, c_bool, c_int, c_void_p)
SEND_DATA_FUNC = CFUNCTYPE(c_int, POINTER(VecValuesAllC), c_int, c_int, c_void_p)
SEND_INIT_DATA_FUNC = CFUNCTYPE(c_int, POINTER(VecInfoAllC), c_int, c_void_p)
BG_THREAD_RUNNING_FUNC = CFUNCTYPE(c_int, c_bool, c_int, c_void_p)


class VectorType:
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


class NgSpiceWrapper:
    """The single native ngspice session owned by this process."""

    _singleton: Optional["NgSpiceWrapper"] = None
    _singleton_lock = threading.RLock()

    def __new__(cls, dll_path: Optional[Path] = None) -> "NgSpiceWrapper":
        with cls._singleton_lock:
            if cls._singleton is None:
                cls._singleton = super().__new__(cls)
            return cls._singleton

    def __init__(self, dll_path: Optional[Path] = None) -> None:
        cls = type(self)
        with cls._singleton_lock:
            if getattr(self, "_construction_complete", False):
                if dll_path is not None and Path(dll_path).resolve() != self._dll_path:
                    raise NgSpiceLoadError(
                        "ngspice 已从其他路径加载；同一进程不能切换原生库"
                    )
                return

            self._logger = logging.getLogger(__name__)
            self._call_lock = threading.RLock()
            self._output_lock = threading.Lock()
            self._state_lock = threading.Lock()
            self._stdout_lines: List[str] = []
            self._callback_plot_lock = threading.Lock()
            self._active_callback_plot: Optional[str] = None
            self._plot_scale_names: Dict[str, str] = {}
            self._fatal_error_message: Optional[str] = None
            self._initialized = False
            self._engine_version: Optional[str] = None
            self._run_started = threading.Event()
            self._run_finished = threading.Event()
            self._run_finished.set()
            self._dll_directory_handle: Any = None

            try:
                self._dll_path = Path(dll_path or self._get_default_dll_path()).resolve()
                self._ngspice = self._load_dll(self._dll_path)
                self._setup_function_signatures()
                self._callbacks = self._create_callbacks()
                self._initialize()
                self._construction_complete = True
            except BaseException:
                cls._singleton = None
                raise

    def _get_default_dll_path(self) -> Path:
        from infrastructure.utils.ngspice_config import get_ngspice_dll_path

        dll_path = get_ngspice_dll_path()
        if dll_path is None:
            raise NgSpiceLoadError("ngspice 共享库路径未配置")
        return Path(dll_path)

    def _load_dll(self, dll_path: Path) -> ctypes.CDLL:
        if not dll_path.is_file():
            raise NgSpiceLoadError(f"ngspice 共享库不存在: {dll_path}")
        try:
            if platform.system() == "Windows":
                # Closing this handle removes the dependency search directory.
                self._dll_directory_handle = os.add_dll_directory(str(dll_path.parent))
            return ctypes.CDLL(str(dll_path))
        except OSError as exc:
            raise NgSpiceLoadError(f"加载 ngspice 共享库失败: {exc}") from exc

    def _setup_function_signatures(self) -> None:
        lib = self._ngspice
        lib.ngSpice_Init.argtypes = [
            SEND_CHAR_FUNC,
            SEND_STAT_FUNC,
            CONTROLLED_EXIT_FUNC,
            SEND_DATA_FUNC,
            SEND_INIT_DATA_FUNC,
            BG_THREAD_RUNNING_FUNC,
            c_void_p,
        ]
        lib.ngSpice_Init.restype = c_int
        lib.ngSpice_Command.argtypes = [c_char_p]
        lib.ngSpice_Command.restype = c_int
        lib.ngSpice_Circ.argtypes = [POINTER(c_char_p)]
        lib.ngSpice_Circ.restype = c_int
        lib.ngSpice_AllPlots.argtypes = []
        lib.ngSpice_AllPlots.restype = POINTER(c_char_p)
        lib.ngSpice_AllVecs.argtypes = [c_char_p]
        lib.ngSpice_AllVecs.restype = POINTER(c_char_p)
        lib.ngGet_Vec_Info.argtypes = [c_char_p]
        lib.ngGet_Vec_Info.restype = POINTER(VectorInfoC)
        try:
            lib.ngSpice_running.argtypes = []
            lib.ngSpice_running.restype = c_bool
        except AttributeError as exc:
            raise NgSpiceLoadError(
                "当前 ngspice 库不支持后台运行/取消 API"
            ) from exc
        try:
            lib.ngCM_Input_Path.argtypes = [c_char_p]
            lib.ngCM_Input_Path.restype = c_char_p
        except AttributeError:
            pass

    def _create_callbacks(self) -> Dict[str, Any]:
        callbacks: Dict[str, Any] = {}

        def send_char(output: bytes, _ident: int, _userdata: c_void_p) -> int:
            if output:
                message = output.decode("utf-8", errors="replace")
                with self._output_lock:
                    self._stdout_lines.append(message)
            return 0

        def send_stat(_status: bytes, _ident: int, _userdata: c_void_p) -> int:
            return 0

        def controlled_exit(
            exit_status: int,
            immediate: bool,
            quit_exit: bool,
            _ident: int,
            _userdata: c_void_p,
        ) -> int:
            self._run_finished.set()
            if not quit_exit:
                self._mark_fatal_error(
                    "ngspice 请求受控退出 "
                    f"(status={exit_status}, immediate={bool(immediate)})"
                )
            return 0

        def send_data(
            values: POINTER(VecValuesAllC),
            _count: int,
            _ident: int,
            _userdata: c_void_p,
        ) -> int:
            if not values:
                return 0
            with self._callback_plot_lock:
                plot_name = self._active_callback_plot
                if not plot_name or plot_name in self._plot_scale_names:
                    return 0
            native = values.contents
            scale_names: List[str] = []
            for index in range(min(int(native.veccount), int(_count))):
                value_pointer = native.vecsa[index]
                if not value_pointer or not value_pointer.contents.is_scale:
                    continue
                raw_name = value_pointer.contents.name
                if raw_name:
                    scale_names.append(raw_name.decode("utf-8", errors="replace"))
            if len(scale_names) == 1:
                with self._callback_plot_lock:
                    if self._active_callback_plot == plot_name:
                        self._plot_scale_names[plot_name] = scale_names[0]
            return 0

        def send_init_data(
            info: POINTER(VecInfoAllC),
            _ident: int,
            _userdata: c_void_p,
        ) -> int:
            if not info:
                return 0
            native = info.contents
            plot_name = (
                native.name.decode("utf-8", errors="replace")
                if native.name
                else ""
            )
            details = [
                native.vecs[index].contents
                for index in range(int(native.veccount))
                if native.vecs[index]
            ]
            scale_pointers = {
                int(detail.pdvecscale)
                for detail in details
                if detail.pdvecscale
            }
            scale_names = [
                detail.vecname.decode("utf-8", errors="replace")
                for detail in details
                if detail.pdvec
                and int(detail.pdvec) in scale_pointers
                and detail.vecname
            ]
            with self._callback_plot_lock:
                self._active_callback_plot = plot_name or None
                if plot_name:
                    self._plot_scale_names.pop(plot_name, None)
                    if len(scale_names) == 1:
                        self._plot_scale_names[plot_name] = scale_names[0]
            return 0

        def background_running(
            exited: bool,
            _ident: int,
            _userdata: c_void_p,
        ) -> int:
            # Despite the public header's ``bool noruns``/running-oriented
            # wording, ngspice 42's sharedspice.c passes its ``fl_exited``
            # flag: false immediately before the worker runs and true after
            # it exits.  Treating this as ``running`` makes short analyses
            # return before their plot exists.
            if exited:
                self._run_finished.set()
            else:
                self._run_finished.clear()
                self._run_started.set()
            return 0

        callbacks["send_char"] = SEND_CHAR_FUNC(send_char)
        callbacks["send_stat"] = SEND_STAT_FUNC(send_stat)
        callbacks["controlled_exit"] = CONTROLLED_EXIT_FUNC(controlled_exit)
        callbacks["send_data"] = SEND_DATA_FUNC(send_data)
        callbacks["send_init_data"] = SEND_INIT_DATA_FUNC(send_init_data)
        callbacks["background_running"] = BG_THREAD_RUNNING_FUNC(background_running)
        return callbacks

    def _initialize(self) -> None:
        with self._call_lock:
            result = self._ngspice.ngSpice_Init(
                self._callbacks["send_char"],
                self._callbacks["send_stat"],
                self._callbacks["controlled_exit"],
                self._callbacks["send_data"],
                self._callbacks["send_init_data"],
                self._callbacks["background_running"],
                None,
            )
        if result != 0:
            raise NgSpiceInitError(f"ngSpice_Init 返回错误码: {result}")
        self._initialized = True
        banner = re.search(
            r"(?m)^stdout \*\* ngspice-(\S+) shared library\b",
            self.get_stdout(),
        )
        self._engine_version = banner.group(1) if banner else None

    def set_input_path(self, directory: Path) -> None:
        """Set XSPICE's input path without changing the process ``cwd``."""

        function = getattr(self._ngspice, "ngCM_Input_Path", None)
        if function is None:
            return
        with self._call_lock:
            function(Path(directory).resolve().as_posix().encode("utf-8"))

    def load_netlist(self, netlist_lines: List[str]) -> bool:
        if self.has_fatal_error:
            return False
        if not netlist_lines or not any(
            is_spice_end_directive(str(line)) for line in netlist_lines
        ):
            self._logger.error("ngspice 网表必须以 .end 结束")
            return False
        if any("\x00" in str(line) for line in netlist_lines):
            self._logger.error("ngspice 网表不允许 NUL 字符")
            return False

        self._clear_output()
        encoded = [str(line).encode("utf-8") for line in netlist_lines]
        c_array = (c_char_p * (len(encoded) + 1))(*encoded, None)
        try:
            with self._call_lock:
                result = self._ngspice.ngSpice_Circ(c_array)
        except OSError as exc:
            self._mark_fatal_error(f"加载网表时的原生异常: {exc}")
            return False
        except Exception:
            self._logger.exception("加载 ngspice 网表失败")
            return False
        return result == 0 and not self.has_fatal_error

    def execute_command(self, command: str) -> bool:
        if self.has_fatal_error:
            return False
        if not isinstance(command, str) or not command.strip():
            raise ValueError("ngspice command must be a non-empty string")
        try:
            with self._call_lock:
                result = self._ngspice.ngSpice_Command(command.encode("utf-8"))
        except OSError as exc:
            self._mark_fatal_error(f"执行原生命令 {command!r} 失败: {exc}")
            return False
        except Exception:
            self._logger.exception("ngspice 命令异常: %s", command)
            return False
        return result == 0 and not self.has_fatal_error

    def run(
        self,
        *,
        timeout_seconds: float,
        cancel_signal: Optional[_CancellationSignal] = None,
    ) -> None:
        """Run in ngspice's background thread with a caller deadline."""

        try:
            timeout = float(timeout_seconds)
        except (TypeError, ValueError) as exc:
            raise ValueError("timeout_seconds must be a positive number") from exc
        if not math.isfinite(timeout) or timeout <= 0:
            raise ValueError("timeout_seconds must be a positive finite number")

        deadline = time.monotonic() + timeout
        # Stopping a shared-library background worker is part of the caller's
        # budget.  Begin timeout cleanup before the external deadline instead
        # of adding a hidden multi-second grace period after it expires.
        stop_reserve = min(0.25, timeout * 0.8)
        run_deadline = deadline - stop_reserve
        self._run_started.clear()
        self._run_finished.clear()
        if not self.execute_command("bg_run"):
            self._run_finished.set()
            raise NgSpiceCommandError("ngspice 拒绝 bg_run 命令")

        while True:
            if self.has_fatal_error:
                raise NgSpiceCommandError(self.fatal_error_message)
            if cancel_signal is not None and cancel_signal.is_set():
                self._stop_background(
                    deadline=min(deadline, time.monotonic() + 0.25)
                )
                raise NgSpiceCancelledError("仿真已取消")
            if self._run_finished.is_set():
                return

            remaining = run_deadline - time.monotonic()
            if remaining <= 0:
                self._stop_background(deadline=deadline)
                raise NgSpiceTimeoutError(f"仿真超过 {timeout:g} 秒限制")
            wait_for = min(0.05, remaining)
            if cancel_signal is not None:
                cancel_signal.wait(wait_for)
            else:
                self._run_finished.wait(wait_for)

    def _stop_background(self, *, deadline: float) -> None:
        """Halt the accepted worker without exceeding an absolute deadline."""

        if self._run_finished.is_set():
            return
        try:
            stop_deadline = float(deadline)
        except (TypeError, ValueError) as exc:
            raise ValueError("deadline must be a finite monotonic timestamp") from exc
        if not math.isfinite(stop_deadline):
            raise ValueError("deadline must be a finite monotonic timestamp")
        # ``bg_run`` returns before its worker necessarily flips the native
        # running flag.  A cancellation in that window must not conclude that
        # there is nothing to stop and leave a worker running into the next
        # circuit. Give the start/finish callback a bounded fraction of the
        # remaining budget, then halt the accepted command regardless.
        now = time.monotonic()
        start_deadline = min(stop_deadline, now + (stop_deadline - now) * 0.25)
        while (
            not self._run_started.is_set()
            and not self._run_finished.is_set()
            and time.monotonic() < start_deadline
        ):
            if self.is_running():
                break
            remaining = start_deadline - time.monotonic()
            if remaining <= 0:
                break
            self._run_finished.wait(timeout=min(0.005, remaining))
        if self._run_finished.is_set():
            return

        # Always make the non-blocking halt request, even if Python scheduling
        # consumed the final fraction of a very small budget.  No grace wait is
        # added: a worker that is still live after the absolute deadline marks
        # the singleton untrusted immediately.
        halted = self.execute_command("bg_halt")
        while True:
            if self.has_fatal_error:
                raise NgSpiceCommandError(self.fatal_error_message)
            if self._run_finished.is_set():
                return
            still_running = self.is_running()
            if not still_running and halted:
                self._run_finished.set()
                return
            remaining = stop_deadline - time.monotonic()
            if remaining <= 0:
                self._mark_fatal_error("ngspice 后台仿真无法在总超时预算内停止")
                raise NgSpiceCommandError(self.fatal_error_message)
            self._run_finished.wait(timeout=min(0.005, remaining))

    def destroy(self, *, deadline: float) -> bool:
        """Remove all plots and the current circuit before the next job."""

        if self.has_fatal_error:
            return False
        try:
            cleanup_deadline = float(deadline)
        except (TypeError, ValueError) as exc:
            raise ValueError("deadline must be a finite monotonic timestamp") from exc
        if not math.isfinite(cleanup_deadline):
            raise ValueError("deadline must be a finite monotonic timestamp")
        if time.monotonic() >= cleanup_deadline:
            raise NgSpiceTimeoutError("清理上一 ngspice 会话时总超时预算已耗尽")
        if self.is_running():
            try:
                self._stop_background(deadline=cleanup_deadline)
            except NgSpiceError:
                return False
        if time.monotonic() >= cleanup_deadline:
            raise NgSpiceTimeoutError("停止上一 ngspice 会话时总超时预算已耗尽")
        plots_ok = self.execute_command("destroy all")
        if time.monotonic() >= cleanup_deadline:
            raise NgSpiceTimeoutError("销毁 ngspice plots 时总超时预算已耗尽")
        circuit_ok = self.execute_command("remcirc")
        with self._callback_plot_lock:
            self._active_callback_plot = None
            self._plot_scale_names.clear()
        # The official API defines a NULL command as command-history cleanup.
        try:
            with self._call_lock:
                self._ngspice.ngSpice_Command(None)
        except Exception:
            self._logger.debug("ngspice command-history cleanup failed", exc_info=True)
        self._clear_output()
        return plots_ok and circuit_ok and not self.has_fatal_error

    def get_all_plots(self) -> List[str]:
        with self._call_lock:
            return self._copy_string_array(self._ngspice.ngSpice_AllPlots())

    def get_all_vectors(self, plot_name: str) -> List[str]:
        if not isinstance(plot_name, str) or not plot_name.strip():
            raise ValueError("plot_name must be a non-empty string")
        with self._call_lock:
            values = self._ngspice.ngSpice_AllVecs(plot_name.encode("utf-8"))
            return self._copy_string_array(values)

    def get_plot_scale_name(self, plot_name: str) -> Optional[str]:
        """Return ngspice's callback-declared scale vector for one plot.

        ngspice 42 passes the human plot title (for example ``DC transfer
        characteristic``) in ``VecInfoAll.name`` while the query API exposes
        the canonical plot name (for example ``dc1``).  A source-owned run has
        one DC analysis plot, so a single callback-declared scale is still an
        unambiguous native identity even when those two names differ.
        """

        with self._callback_plot_lock:
            direct = self._plot_scale_names.get(str(plot_name))
            if direct:
                return direct
            declared = set(self._plot_scale_names.values())
            return next(iter(declared)) if len(declared) == 1 else None

    @staticmethod
    def _copy_string_array(values: POINTER(c_char_p)) -> List[str]:
        copied: List[str] = []
        if not values:
            return copied
        index = 0
        while values[index]:
            copied.append(values[index].decode("utf-8", errors="replace"))
            index += 1
        return copied

    def get_vector_info(
        self,
        vec_name: str,
        *,
        plot_name: Optional[str] = None,
    ) -> Optional[VectorInfo]:
        query_name = str(vec_name)
        if plot_name and not query_name.lower().startswith(f"{plot_name.lower()}."):
            query_name = f"{plot_name}.{query_name}"
        try:
            with self._call_lock:
                pointer = self._ngspice.ngGet_Vec_Info(query_name.encode("utf-8"))
                if not pointer:
                    return None
                native = pointer.contents
                length = int(native.v_length)
                if length <= 0:
                    return None
                real_data = (
                    np.ctypeslib.as_array(native.v_realdata, shape=(length,)).copy()
                    if native.v_realdata
                    else np.array([], dtype=float)
                )
                complex_data = None
                if native.v_compdata:
                    complex_data = np.fromiter(
                        (
                            complex(
                                native.v_compdata[index].cx_real,
                                native.v_compdata[index].cx_imag,
                            )
                            for index in range(length)
                        ),
                        dtype=np.complex128,
                        count=length,
                    )
                name = (
                    native.v_name.decode("utf-8", errors="replace")
                    if native.v_name
                    else str(vec_name)
                )
                return VectorInfo(
                    name=name,
                    type=int(native.v_type),
                    length=length,
                    data=real_data,
                    cdata=complex_data,
                )
        except Exception:
            self._logger.exception("读取 ngspice 向量失败: %s", query_name)
            return None

    def get_stdout(self) -> str:
        with self._output_lock:
            return "\n".join(self._stdout_lines)

    def is_running(self) -> bool:
        try:
            with self._call_lock:
                return bool(self._ngspice.ngSpice_running())
        except Exception as exc:
            self._logger.exception("读取 ngspice 后台状态失败")
            self._mark_fatal_error(f"无法读取 ngspice 后台状态: {exc}")
            return False

    def _clear_output(self) -> None:
        with self._output_lock:
            self._stdout_lines.clear()

    def _mark_fatal_error(self, message: str) -> None:
        with self._state_lock:
            self._fatal_error_message = str(message or "ngspice 原生状态已损坏")
            self._initialized = False
        self._run_finished.set()

    @property
    def engine_version(self) -> Optional[str]:
        """Version reported by the loaded library's initialization banner."""
        return self._engine_version

    @property
    def initialized(self) -> bool:
        return self._initialized and not self.has_fatal_error

    @property
    def has_fatal_error(self) -> bool:
        with self._state_lock:
            return bool(self._fatal_error_message)

    @property
    def fatal_error_message(self) -> str:
        with self._state_lock:
            return str(self._fatal_error_message or "")

__all__ = [
    "NgSpiceWrapper",
    "NgSpiceError",
    "NgSpiceLoadError",
    "NgSpiceInitError",
    "NgSpiceCommandError",
    "NgSpiceTimeoutError",
    "NgSpiceCancelledError",
    "VectorInfo",
    "VectorType",
]
