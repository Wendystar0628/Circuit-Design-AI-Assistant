"""Discover and configure the ngspice *shared library* used by ctypes.

The command-line ``ngspice`` executable is not a substitute for
``ngspice.dll``/``libngspice``. Configuration therefore records one exact
discovered library candidate rather than reconstructing a path later from an
ambiguous installation directory. ABI loading is verified by ``NgSpiceWrapper``.
"""

from __future__ import annotations

import os
import platform
import shutil
import sys
import threading
from pathlib import Path
from typing import Iterable, Optional, Tuple


PLATFORM_WINDOWS = "Windows"
PLATFORM_LINUX = "Linux"
PLATFORM_MACOS = "Darwin"
VENDOR_NGSPICE_DIR = Path("vendor/ngspice")

_BUNDLED_LAYOUT = {
    PLATFORM_WINDOWS: (
        Path("win64/Spice64_dll"),
        Path("dll-vs/ngspice.dll"),
    ),
    PLATFORM_LINUX: (Path("linux64"), Path("libngspice.so")),
    PLATFORM_MACOS: (Path("macos"), Path("libngspice.dylib")),
}

_configuration_lock = threading.RLock()
_ngspice_configured = False
_ngspice_available = False
_ngspice_library_path: Optional[Path] = None
_configuration_error: Optional[str] = None


def _get_base_path() -> Path:
    packaged_root = getattr(sys, "_MEIPASS", None)
    if packaged_root is not None:
        return Path(packaged_root).resolve()
    return Path(__file__).resolve().parents[2]


def _get_platform() -> str:
    return platform.system()


def _discover_bundled(
    base_path: Path,
    platform_id: str,
) -> Optional[Tuple[Path, Path]]:
    layout = _BUNDLED_LAYOUT.get(platform_id)
    if layout is None:
        return None
    root_relative, library_relative = layout
    root = (Path(base_path) / VENDOR_NGSPICE_DIR / root_relative).resolve()
    library = (root / library_relative).resolve()
    if library.is_file():
        return library, root
    return None


def _system_library_candidates(platform_id: str) -> Iterable[Path]:
    if platform_id == PLATFORM_WINDOWS:
        for directory in (
            Path("C:/Spice64/bin-dll"),
            Path("C:/Program Files/Spice64/bin-dll"),
            Path("C:/Program Files (x86)/Spice64/bin-dll"),
        ):
            yield directory / "ngspice.dll"

        executable = shutil.which("ngspice") or shutil.which("ngspice_con")
        if executable:
            executable_dir = Path(executable).resolve().parent
            yield executable_dir / "ngspice.dll"
            yield executable_dir.parent / "bin-dll" / "ngspice.dll"
        return

    if platform_id == PLATFORM_LINUX:
        for directory in (
            Path("/usr/lib"),
            Path("/usr/lib64"),
            Path("/usr/local/lib"),
            Path("/usr/lib/x86_64-linux-gnu"),
            Path("/usr/lib/aarch64-linux-gnu"),
        ):
            yield directory / "libngspice.so"
            yield directory / "libngspice.so.0"
        return

    if platform_id == PLATFORM_MACOS:
        for directory in (
            Path("/opt/homebrew/lib"),
            Path("/usr/local/lib"),
            Path("/usr/lib"),
        ):
            yield directory / "libngspice.dylib"


def _infer_install_root(library: Path, platform_id: str) -> Path:
    parent = library.parent
    if platform_id == PLATFORM_WINDOWS and parent.name.lower() in {
        "bin-dll",
        "dll-vs",
    }:
        return parent.parent
    if platform_id in {PLATFORM_LINUX, PLATFORM_MACOS}:
        # /usr/lib*, /usr/local/lib and Homebrew's /opt/homebrew/lib all map
        # cleanly to a prefix whose share/ngspice directory can be inspected.
        return parent.parent
    return parent


def _discover_system(platform_id: str) -> Optional[Tuple[Path, Path]]:
    for candidate in _system_library_candidates(platform_id):
        if candidate.is_file():
            library = candidate.resolve()
            return library, _infer_install_root(library, platform_id)
    return None


def _prepend_path_entry(directory: Path) -> None:
    directory_text = str(directory.resolve())
    current = os.environ.get("PATH", "")
    entries = [entry for entry in current.split(os.pathsep) if entry]
    normalized = os.path.normcase(os.path.abspath(directory_text))
    if any(
        os.path.normcase(os.path.abspath(entry)) == normalized
        for entry in entries
    ):
        return
    os.environ["PATH"] = os.pathsep.join([directory_text, *entries])


def _setup_environment(library: Path, root: Path, platform_id: str) -> None:
    if platform_id == PLATFORM_WINDOWS:
        _prepend_path_entry(library.parent)

    model_library = root / "lib" / "ngspice"
    if model_library.is_dir():
        os.environ["SPICE_LIB_DIR"] = model_library.as_posix()

    scripts = root / "share" / "ngspice" / "scripts"
    if scripts.is_dir():
        os.environ["SPICE_SCRIPTS"] = scripts.as_posix()


def configure_ngspice() -> bool:
    """Resolve one concrete shared library and configure its resource paths."""

    global _ngspice_configured
    global _ngspice_available
    global _ngspice_library_path
    global _configuration_error

    with _configuration_lock:
        if _ngspice_configured:
            return _ngspice_available

        _ngspice_configured = True
        _ngspice_available = False
        _ngspice_library_path = None
        _configuration_error = None

        platform_id = _get_platform()
        if platform_id not in _BUNDLED_LAYOUT:
            _configuration_error = f"不支持的平台: {platform_id}"
            return False

        discovered = _discover_bundled(_get_base_path(), platform_id)
        if discovered is None:
            discovered = _discover_system(platform_id)
        if discovered is None:
            _configuration_error = "未找到可用的 ngspice 共享库"
            return False

        library, root = discovered
        _setup_environment(library, root, platform_id)
        _ngspice_library_path = library
        _ngspice_available = True
        return True


def get_ngspice_dll_path() -> Optional[Path]:
    """Return the exact discovered shared-library candidate used by ctypes."""

    with _configuration_lock:
        library = _ngspice_library_path
        return library if library is not None and library.is_file() else None


def is_ngspice_available() -> bool:
    with _configuration_lock:
        return _ngspice_available


def get_configuration_error() -> Optional[str]:
    with _configuration_lock:
        return _configuration_error


__all__ = [
    "configure_ngspice",
    "get_ngspice_dll_path",
    "is_ngspice_available",
    "get_configuration_error",
]
