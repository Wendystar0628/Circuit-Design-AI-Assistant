"""Run each native SPICE transaction in a disposable, supervised process.

The desktop API never owns the native solver session. A blocked native call or
DLL crash affects one worker only; cancellation and the total deadline are
enforced by the parent, including solver initialization and netlist loading.
"""

from __future__ import annotations

import json
import math
import os
from pathlib import Path
import platform
import subprocess
import sys
import tempfile
import time
from typing import TYPE_CHECKING, Any

from domain.simulation.executor.spice_executor import SUPPORTED_EXTENSIONS
from domain.simulation.models.simulation_error import (
    ErrorSeverity,
    SimulationError,
    SimulationErrorType,
)
from domain.simulation.models.simulation_result import SimulationResult, create_error_result

if TYPE_CHECKING:
    from domain.simulation.models.experiment import ExperimentSpec


WORKER_PROTOCOL_VERSION = 1
_POLL_SECONDS = 0.025
_STOP_SECONDS = 0.5


def _reject_json_constant(value: str) -> None:
    raise ValueError(f"Non-finite worker JSON constant: {value}")


class ProcessSpiceExecutor:
    """Supervise a fresh ngspice process for every submitted experiment."""

    def __init__(self, timeout_seconds: float = 300) -> None:
        if isinstance(timeout_seconds, bool):
            raise ValueError("timeout_seconds must be a positive finite number")
        timeout = float(timeout_seconds)
        if not math.isfinite(timeout) or timeout <= 0:
            raise ValueError("timeout_seconds must be a positive finite number")
        self._timeout_seconds = timeout

    def get_name(self) -> str:
        return "spice"

    def get_supported_extensions(self) -> list[str]:
        return list(SUPPORTED_EXTENSIONS)

    def can_handle(self, file_path: str) -> bool:
        return Path(file_path).suffix.casefold() in SUPPORTED_EXTENSIONS

    def execute(
        self,
        file_path: str,
        *,
        cancel_signal: Any = None,
        experiment: ExperimentSpec | None = None,
        source_snapshot: dict[str, Any] | None = None,
    ) -> SimulationResult:
        result = self._execute(
            file_path,
            cancel_signal=cancel_signal,
            experiment=experiment,
            source_snapshot=source_snapshot,
        )
        if not result.success and result.provenance is None and source_snapshot is not None:
            # A killed worker cannot attest to generated solver inputs. Preserve
            # the accepted source and request for replay without inventing them.
            result.provenance = {
                "schema_version": 1,
                "experiment": experiment.to_dict() if experiment is not None else {},
                "original_source": source_snapshot,
                "effective_source": None,
                "runtime": None,
                "omitted_measurements": [],
                "engine": {
                    "name": "ngspice", "version": None,
                    "platform": platform.platform(),
                    "execution_mode": "isolated_process",
                },
            }
        return result

    def _execute(
        self,
        file_path: str,
        *,
        cancel_signal: Any,
        experiment: ExperimentSpec | None,
        source_snapshot: dict[str, Any] | None,
    ) -> SimulationResult:
        started = time.monotonic()
        if cancel_signal is not None and not callable(
            getattr(cancel_signal, "is_set", None)
        ):
            return self._failure(
                file_path, SimulationErrorType.PARAMETER_INVALID,
                "内部取消信号无效", started,
            )
        if cancel_signal is not None and cancel_signal.is_set():
            return self._failure(
                file_path, SimulationErrorType.CANCELLED, "仿真已取消", started,
            )

        timeout = (
            experiment.timeout_seconds if experiment is not None
            else self._timeout_seconds
        )
        deadline = started + timeout
        process: subprocess.Popen[bytes] | None = None
        with tempfile.TemporaryDirectory(prefix="circuit-ai-spice-worker-") as directory:
            root = Path(directory)
            request_path = root / "request.json"
            response_path = root / "response.json"
            log_path = root / "worker.log"
            try:
                request_path.write_text(
                    json.dumps(
                        {
                            "protocol_version": WORKER_PROTOCOL_VERSION,
                            "file_path": str(Path(file_path).expanduser().resolve()),
                            "timeout_seconds": timeout,
                            "experiment": experiment.to_dict() if experiment else None,
                            "source_snapshot": source_snapshot,
                        },
                        ensure_ascii=False,
                        allow_nan=False,
                    ),
                    encoding="utf-8",
                )
                with log_path.open("wb") as log:
                    process = subprocess.Popen(
                        self._worker_command(request_path, response_path),
                        cwd=str(Path(__file__).resolve().parents[3]),
                        stdin=subprocess.DEVNULL,
                        stdout=log,
                        stderr=subprocess.STDOUT,
                        creationflags=(
                            subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
                        ),
                    )
                    while process.poll() is None:
                        if cancel_signal is not None and cancel_signal.is_set():
                            self._stop_worker(process)
                            return self._failure(
                                file_path, SimulationErrorType.CANCELLED,
                                "仿真已取消，求解器进程已退出", started,
                                raw_output=self._read_log(log_path),
                            )
                        remaining = deadline - time.monotonic()
                        if remaining <= 0:
                            self._stop_worker(process)
                            return self._failure(
                                file_path, SimulationErrorType.TIMEOUT,
                                f"仿真超过 {timeout:g} 秒总限制，求解器进程已退出",
                                started, raw_output=self._read_log(log_path),
                            )
                        try:
                            process.wait(timeout=min(_POLL_SECONDS, remaining))
                        except subprocess.TimeoutExpired:
                            pass

                if process.returncode != 0:
                    return self._failure(
                        file_path, SimulationErrorType.NGSPICE_CRASH,
                        f"求解器进程异常退出（退出码 {process.returncode}）", started,
                        raw_output=self._read_log(log_path),
                    )
                payload = json.loads(
                    response_path.read_text(encoding="utf-8"),
                    parse_constant=_reject_json_constant,
                )
                if not isinstance(payload, dict) or set(payload) != {
                    "protocol_version", "result", "provenance"
                }:
                    raise ValueError("Invalid simulation worker response envelope")
                if (
                    type(payload["protocol_version"]) is not int
                    or payload["protocol_version"] != WORKER_PROTOCOL_VERSION
                ):
                    raise ValueError("Unsupported simulation worker protocol version")
                if payload["provenance"] is not None and not isinstance(
                    payload["provenance"], dict
                ):
                    raise ValueError("Invalid simulation worker provenance")
                requested = Path(file_path).expanduser().resolve()
                result = self._decode_result(payload["result"], requested)
                result.provenance = payload["provenance"]
                result.duration_seconds = time.monotonic() - started
                return result
            except Exception as exc:
                return self._failure(
                    file_path, SimulationErrorType.NGSPICE_CRASH,
                    f"求解器进程未返回有效结果: {exc}", started,
                    raw_output=self._read_log(log_path),
                )
            finally:
                if process is not None and process.poll() is None:
                    self._stop_worker(process)

    @staticmethod
    def _decode_result(payload: Any, requested: Path) -> SimulationResult:
        """Validate the runtime identity, then round-trip the portable schema."""
        if not isinstance(payload, dict):
            raise ValueError("Simulation worker result must be an object")
        returned = Path(payload["file_path"])
        if not returned.is_absolute() or os.path.normcase(str(returned.resolve())) != (
            os.path.normcase(str(requested))
        ):
            raise ValueError("Simulation worker returned a different circuit")
        portable = {**payload, "file_path": requested.name}
        error_payload = payload.get("error")
        error_file = error_payload.get("file_path") if error_payload else None
        if error_file is not None:
            error_path = Path(error_file)
            if not error_path.is_absolute() or os.path.normcase(str(error_path.resolve())) != (
                os.path.normcase(str(requested))
            ):
                raise ValueError("Simulation worker error identifies a different circuit")
            portable["error"] = {**error_payload, "file_path": requested.name}
        result = SimulationResult.from_dict(portable)
        result.file_path = str(requested)
        if result.error is not None and error_file is not None:
            result.error.file_path = str(requested)
        return result

    @staticmethod
    def _worker_command(request_path: Path, response_path: Path) -> list[str]:
        if getattr(sys, "frozen", False):
            return [
                sys.executable, "--simulation-worker",
                str(request_path), str(response_path),
            ]
        return [
            sys.executable, "-m", "domain.simulation.executor.spice_worker",
            str(request_path), str(response_path),
        ]

    @staticmethod
    def _stop_worker(process: subprocess.Popen[bytes]) -> None:
        if process.poll() is not None:
            return
        try:
            process.terminate()
        except ProcessLookupError:
            pass
        try:
            process.wait(timeout=_STOP_SECONDS)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=_STOP_SECONDS)

    @staticmethod
    def _read_log(path: Path) -> str:
        try:
            with path.open("rb") as stream:
                stream.seek(0, os.SEEK_END)
                stream.seek(max(0, stream.tell() - 16_384))
                return stream.read().decode("utf-8", errors="replace")
        except OSError:
            return ""

    @staticmethod
    def _failure(
        file_path: str,
        error_type: SimulationErrorType,
        message: str,
        started: float,
        *,
        raw_output: str = "",
    ) -> SimulationResult:
        return create_error_result(
            executor="spice",
            file_path=file_path,
            analysis_type="unknown",
            error=SimulationError(
                type=error_type,
                severity=(
                    ErrorSeverity.LOW if error_type is SimulationErrorType.CANCELLED
                    else ErrorSeverity.HIGH
                ),
                message=message,
                file_path=file_path,
                recovery_suggestion=(
                    "修正输入或调整仿真设置后可直接重试；下次运行将使用新的求解器进程"
                    if error_type is SimulationErrorType.NGSPICE_CRASH else None
                ),
            ),
            raw_output=raw_output,
            duration_seconds=time.monotonic() - started,
        )


__all__ = ["ProcessSpiceExecutor"]
