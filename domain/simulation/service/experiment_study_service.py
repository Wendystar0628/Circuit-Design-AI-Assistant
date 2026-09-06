"""Persistent corner/numerical studies scheduled by the shared job manager."""

from __future__ import annotations

import copy
import json
import math
import os
import re
import secrets
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from domain.simulation.data.simulation_run_archive import load_run_archive
from domain.simulation.models.experiment import ExperimentSpec
from domain.simulation.models.simulation_job import JobOrigin, SimulationJob
from domain.simulation.models.study import expand_corner_cases
from domain.simulation.spice.experiment_deck import compile_experiment_graph
from domain.simulation.spice.source_closure import capture_spice_source_snapshot, restore_spice_source_graph


_TERMINAL = {"completed", "failed", "cancelled"}
_STUDY_ID = re.compile(r"^study_[0-9a-f]{32}$")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class ExperimentStudyService:
    """Freeze once, validate every case, then submit independent bounded jobs.

    The manifest owns case identity and historical specifications. A terminal
    listener saves results without requiring an open browser or polling loop.
    Unknown active jobs on reload are marked interrupted, never re-executed.
    """

    def __init__(self, *, job_manager: Any, result_repository: Any) -> None:
        self._manager = job_manager
        self._repository = result_repository
        self._lock = threading.RLock()
        self._studies: dict[tuple[str, str], dict[str, Any]] = {}
        self._job_studies: dict[str, tuple[str, str]] = {}
        self._manager.add_terminal_listener(self._on_terminal)

    def create(
        self, *, project_root: str, circuit_file: str,
        experiment: ExperimentSpec | None = None, kind: str = "corner",
        axes: list[dict] | None = None, numerical: dict | None = None,
        origin: JobOrigin = JobOrigin.UI_EDITOR, session_id: str = "", version: int = 1,
    ) -> dict[str, Any]:
        root = self._project_root(project_root)
        circuit = Path(circuit_file).expanduser()
        circuit = (root / circuit).resolve() if not circuit.is_absolute() else circuit.resolve()
        if not circuit.is_relative_to(root) or not circuit.is_file():
            raise ValueError("circuit_file must be an existing file inside project_root")
        if not isinstance(origin, JobOrigin):
            raise ValueError("origin must be a JobOrigin")
        if not isinstance(session_id, str):
            raise ValueError("session_id must be a string")
        if isinstance(version, bool) or not isinstance(version, int) or version < 1:
            raise ValueError("version must be a positive integer")
        base = experiment or ExperimentSpec()
        if not isinstance(base, ExperimentSpec):
            raise ValueError("experiment must be an ExperimentSpec")
        base = ExperimentSpec.from_dict(base.to_dict())
        snapshot = capture_spice_source_snapshot(circuit)
        graph = restore_spice_source_graph(snapshot)
        numerical_config = None
        if kind == "corner":
            if numerical is not None:
                raise ValueError("corner studies must not include numerical controls")
            parsed_axes, cases = expand_corner_cases(base, axes)
            axis_payload = [axis.to_dict() for axis in parsed_axes]
        elif kind == "numerical":
            if axes:
                raise ValueError("numerical studies must not include corner axes")
            from domain.simulation.models.numerical_study import (
                NumericalStudySpec, build_numerical_experiments,
            )
            spec = NumericalStudySpec.from_dict(numerical or {})
            numerical_config = spec.to_dict()
            baseline, refined = build_numerical_experiments(base, graph, spec)
            cases = [{"case_id": label, "label": label, "coordinates": {}, "experiment": item.to_dict()}
                     for label, item in (("baseline", baseline), ("refined", refined))]
            axis_payload = []
        else:
            raise ValueError("study kind must be corner or numerical")
        # Reject unknown .param bindings or invalid analysis before any job runs.
        for case in cases:
            compile_experiment_graph(graph, ExperimentSpec.from_dict(case["experiment"]))
        study_id = f"study_{secrets.token_hex(16)}"
        manifest = {
            "schema_version": 1, "study_id": study_id, "kind": kind,
            "circuit_file": circuit.relative_to(root).as_posix(),
            "created_at": _now(), "updated_at": _now(), "status": "pending",
            "session_id": session_id, "version": version,
            "base_experiment": base.to_dict(), "axes": axis_payload,
            "numerical": numerical_config, "source_digest": graph.digest,
            "source_snapshot_path": f".circuit_ai/studies/{study_id}/source_snapshot.json",
            "cases": cases, "summary": {},
        }
        for case in cases:
            case.update({
                "job_id": None, "status": "pending", "cancel_requested": False,
                "result_path": None, "error": None, "result_error": None, "duration_seconds": None,
                "metrics": [], "acceptance": self._acceptance(None, case["experiment"]), "submitted_at": None,
                "started_at": None, "finished_at": None,
                "session_id": f"{session_id}:{study_id}:{case['case_id']}",
            })
        key = (str(root), study_id)
        with self._lock:
            directory = self._study_dir(root, study_id)
            directory.mkdir(parents=True, exist_ok=False)
            self._write_json(directory / "source_snapshot.json", snapshot)
            self._studies[key] = manifest
            self._save(root, manifest)
            for case in cases:
                try:
                    job = self._manager.submit(
                        circuit_file=str(circuit), project_root=str(root), origin=origin,
                        version=version, session_id=case["session_id"],
                        experiment=ExperimentSpec.from_dict(case["experiment"]),
                        source_snapshot=snapshot, study_id=study_id, case_id=case["case_id"],
                    )
                except Exception as exc:
                    case.update(status="failed", error=f"Submission failed: {exc}", finished_at=_now())
                else:
                    case["job_id"] = job.job_id
                    self._job_studies[job.job_id] = key
                    self._update_case(root, case, job)
                # A crash must not erase identities for already submitted cases.
                self._save(root, manifest)
            self._refresh(root, manifest)
            return copy.deepcopy(manifest)

    def get(self, project_root: str, study_id: str) -> dict[str, Any]:
        root = self._project_root(project_root)
        with self._lock:
            manifest = self._load(root, study_id)
            self._refresh(root, manifest)
            return copy.deepcopy(manifest)

    def list(self, project_root: str) -> list[dict[str, Any]]:
        root = self._project_root(project_root)
        directory = self._study_base(root)
        if not directory.exists():
            return []
        return sorted(
            [self.get(str(root), path.parent.name) for path in directory.glob("study_*/study.json")],
            key=lambda item: item["created_at"], reverse=True,
        )

    def cancel(self, project_root: str, study_id: str, case_id: str | None = None) -> dict[str, Any]:
        root = self._project_root(project_root)
        with self._lock:
            manifest = self._load(root, study_id)
            cases = [case for case in manifest["cases"] if case_id is None or case["case_id"] == case_id]
            if not cases:
                raise ValueError(f"Unknown study case: {case_id}")
            for case in cases:
                if case["status"] in _TERMINAL:
                    continue
                case["cancel_requested"] = True
                if case["job_id"]:
                    self._manager.request_cancel(case["job_id"])
                else:
                    case.update(status="cancelled", finished_at=_now())
            self._refresh(root, manifest)
            return copy.deepcopy(manifest)

    def close(self) -> None:
        """Detach this observer; lifecycle shutdown belongs to the job manager."""
        self._manager.remove_terminal_listener(self._on_terminal)

    def _on_terminal(self, job: SimulationJob) -> None:
        with self._lock:
            key = self._job_studies.get(job.job_id)
            if key is None:
                return
            manifest = self._studies[key]
            self._refresh(Path(key[0]), manifest)

    def _refresh(self, root: Path, manifest: dict) -> None:
        for case in manifest["cases"]:
            job = self._manager.query(case["job_id"]) if case["job_id"] else None
            if job is not None:
                self._update_case(root, case, job)
            elif case["status"] not in _TERMINAL:
                case.update(status="failed", error="Interrupted: job unavailable after application restart", finished_at=_now())
        statuses = [case["status"] for case in manifest["cases"]]
        if any(status not in _TERMINAL for status in statuses):
            manifest["status"] = "running" if "running" in statuses or any(status in _TERMINAL for status in statuses) else "pending"
        elif "failed" in statuses:
            manifest["status"] = "failed"
        elif "cancelled" in statuses:
            manifest["status"] = "cancelled"
        else:
            manifest["status"] = "completed"
        manifest["summary"] = self._summary(manifest)
        if manifest["kind"] == "numerical" and all(status in _TERMINAL for status in statuses):
            manifest["summary"]["numerical"] = self._numerical_summary(root, manifest)
        self._save(root, manifest)

    def _update_case(self, root: Path, case: dict, job: SimulationJob) -> None:
        already_loaded = bool(case.get("result_path")) and case["status"] in _TERMINAL
        case.update(
            status=job.status.value, cancel_requested=job.cancel_requested,
            result_path=job.result_path, error=job.error_message,
            submitted_at=job.submitted_at.isoformat(),
            started_at=job.started_at.isoformat() if job.started_at else None,
            finished_at=job.finished_at.isoformat() if job.finished_at else None,
        )
        # Once loaded, result.json's execution duration is the cost authority.
        # Job wall time also includes scheduling/service overhead and must not
        # replace the recorded cost on later polling or sibling completions.
        if not already_loaded and job.started_at and job.finished_at:
            case["duration_seconds"] = (job.finished_at - job.started_at).total_seconds()
        if case.get("result_error"):
            case.update(status="failed", error=case["result_error"])
        if not job.result_path or not job.is_terminal or already_loaded:
            return
        loaded = self._repository.load(str(root), job.result_path)
        if not loaded.success or loaded.data is None:
            error = loaded.error_message or "Persisted result unavailable"
            case.update(status="failed", error=error, result_error=error)
            return
        result = loaded.data
        case["duration_seconds"] = result.duration_seconds
        from domain.simulation.models.acceptance import resolve_native_measurement
        case["metrics"] = []
        for measure in result.measurements or []:
            value, unit, reason = resolve_native_measurement(result, measure.name)
            case["metrics"].append({
                "name": measure.name, "unit": unit, "value": value,
                "status": measure.status.value if value is not None or measure.status.value != "OK" else "NOT_MEASURED",
                "error": reason, "statement": measure.statement,
            })
        case["acceptance"] = self._acceptance(result, case["experiment"])
        # OP signals have no .measure rows; explicit acceptance targets supply
        # their signal identity and requested units for the corner summary.
        seen = {(row["name"].casefold(), row["unit"]) for row in case["metrics"]}
        for row in case["acceptance"]["rows"]:
            identity = (row["metric"].casefold(), row["unit"])
            if row["source"] != "op_signal" or identity in seen:
                continue
            seen.add(identity)
            case["metrics"].append({
                "name": row["metric"], "unit": row["unit"], "value": row["value"],
                "status": "OK" if row["value"] is not None else "NOT_MEASURED",
                "error": row["reason"] if row["value"] is None else "", "statement": "",
            })

    @staticmethod
    def _acceptance(result: Any, experiment: dict) -> Any:
        from domain.simulation.models.acceptance import evaluate_acceptance
        return evaluate_acceptance(result, experiment)

    @staticmethod
    def _summary(manifest: dict) -> dict:
        cases = manifest["cases"]
        counts = {name: sum(case["status"] == name for case in cases)
                  for name in ("pending", "running", "completed", "failed", "cancelled")}
        metrics: dict[tuple[str, str], list[tuple[str, float]]] = {}
        for case in cases:
            for row in case["metrics"]:
                key = (row["name"].casefold(), row["unit"])
                metrics.setdefault(key, [])
                if case["status"] == "completed" and row["unit"] and row["value"] is not None and row["status"] == "OK":
                    metrics[key].append((case["case_id"], row["value"]))
        rows = []
        for (name, unit), values in metrics.items():
            lower = min(values, key=lambda pair: pair[1]) if values else None
            upper = max(values, key=lambda pair: pair[1]) if values else None
            delta = upper[1] - lower[1] if lower and upper else None
            rows.append({
                "name": name, "unit": unit,
                "min": lower[1] if lower else None, "max": upper[1] if upper else None,
                "min_case_id": lower[0] if lower else None, "max_case_id": upper[0] if upper else None,
                "delta": delta if delta is None or math.isfinite(delta) else None,
                "measured_cases": len(values), "unmeasured_cases": len(cases) - len(values),
            })
        constraints: dict[str, dict] = {}
        acceptance_statuses = []
        for case in cases:
            acceptance_statuses.append(case["acceptance"]["status"])
            for row in case["acceptance"]["rows"]:
                item = constraints.setdefault(row["id"], {
                    "id": row["id"], "metric": row["metric"], "unit": row["unit"],
                    "lower": row["lower"], "upper": row["upper"],
                    "minimum_margin": None, "worst_case_id": None,
                    "counts": {"PASS": 0, "FAIL": 0, "NOT_MEASURED": 0},
                })
                item["counts"][row["status"]] += 1
                if row["margin"] is not None and (item["minimum_margin"] is None or row["margin"] < item["minimum_margin"]):
                    item.update(minimum_margin=row["margin"], worst_case_id=case["case_id"])
        acceptance_status = ("FAIL" if "FAIL" in acceptance_statuses else
                             "NOT_MEASURED" if "NOT_MEASURED" in acceptance_statuses else "PASS")
        return {"total_cases": len(cases), "counts": counts, "metrics": rows,
                "acceptance_status": acceptance_status, "worst_constraints": list(constraints.values()),
                "duration_seconds": sum(case["duration_seconds"] or 0 for case in cases)}

    def _numerical_summary(self, root: Path, manifest: dict) -> dict:
        from domain.simulation.models.numerical_study import NumericalStudySpec, compare_numerical_results

        def inconclusive(reason: str) -> dict:
            durations = [case["duration_seconds"] for case in manifest["cases"]]
            return {"status": "inconclusive", "stable": False, "metrics": [], "reason": reason,
                    "cost": {"baseline_seconds": durations[0], "refined_seconds": durations[1],
                             "total_seconds": sum(value or 0 for value in durations), "ratio": None}}

        results = []
        for case in manifest["cases"]:
            if case["status"] != "completed" or not case["result_path"]:
                return inconclusive("Both baseline and refined cases must complete successfully")
            loaded = self._repository.load(str(root), case["result_path"])
            if not loaded.success or loaded.data is None:
                return inconclusive("Result bundle unavailable")
            result = loaded.data
            try:
                result.provenance = load_run_archive(str(root), case["result_path"])
            except (OSError, ValueError):
                result.provenance = None
            results.append(result)
        comparable = all(result.provenance and result.provenance["original_source"]["digest"] == manifest["source_digest"] for result in results)
        return compare_numerical_results(
            results[0], results[1], NumericalStudySpec.from_dict(manifest["numerical"]), comparable=bool(comparable),
        )

    def _load(self, root: Path, study_id: str) -> dict:
        directory = self._study_dir(root, study_id)
        key = (str(root), study_id)
        if key in self._studies:
            return self._studies[key]
        path = directory / "study.json"
        if not path.is_file():
            raise FileNotFoundError(f"Unknown study: {study_id}")
        payload = json.loads(path.read_text(encoding="utf-8"))
        if payload.get("schema_version") != 1 or payload.get("study_id") != study_id or not payload.get("cases"):
            raise ValueError("Invalid study manifest")
        self._studies[key] = payload
        for case in payload["cases"]:
            if case["job_id"]:
                self._job_studies[case["job_id"]] = key
        return payload

    def _save(self, root: Path, manifest: dict) -> None:
        manifest["updated_at"] = _now()
        self._write_json(self._study_dir(root, manifest["study_id"]) / "study.json", manifest)

    @staticmethod
    def _write_json(path: Path, payload: dict) -> None:
        temporary = path.with_name(f".{path.name}.{secrets.token_hex(8)}.tmp")
        try:
            temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")
            os.replace(temporary, path)
        finally:
            temporary.unlink(missing_ok=True)

    @staticmethod
    def _project_root(project_root: str) -> Path:
        root = Path(project_root).expanduser()
        if not root.is_absolute() or not root.is_dir():
            raise ValueError("project_root must be an existing absolute directory")
        return root.resolve()

    @staticmethod
    def _study_base(root: Path) -> Path:
        base = root / ".circuit_ai" / "studies"
        if not base.resolve().is_relative_to(root):
            raise ValueError("Study directory must stay inside project_root")
        return base

    @classmethod
    def _study_dir(cls, root: Path, study_id: str) -> Path:
        if not isinstance(study_id, str) or not _STUDY_ID.fullmatch(study_id):
            raise ValueError("Invalid study_id")
        directory = cls._study_base(root) / study_id
        if directory.resolve().parent != cls._study_base(root).resolve():
            raise ValueError("Study directory must not redirect outside study storage")
        return directory


__all__ = ["ExperimentStudyService"]
