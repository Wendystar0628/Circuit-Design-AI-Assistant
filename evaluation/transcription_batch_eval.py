from __future__ import annotations

import argparse
import logging
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from domain.simulation.executor.spice_executor import SpiceExecutor
from domain.simulation.spice.ltspice_asc_to_cir_transcriber import LtspiceAscToCirTranscriber
from infrastructure.utils.ngspice_config import configure_ngspice
from evaluation.results_eval_utils import (
    count_components_in_cir_text,
    count_symbols_in_asc_text,
    describe_numeric,
    iter_asc_files,
    normalize_for_csv,
    write_csv,
    write_json,
)

logger = logging.getLogger("evaluation.transcription_batch")


def _evaluate_one(
    transcriber: LtspiceAscToCirTranscriber,
    spice_executor: SpiceExecutor,
    asc_path: Path,
) -> Dict[str, Any]:
    asc_text = asc_path.read_text(encoding="utf-8", errors="ignore")
    expected_component_count = count_symbols_in_asc_text(asc_text)

    with tempfile.TemporaryDirectory(prefix="cai_transcription_") as tmp_dir:
        transcribed = transcriber.transcribe_file(str(asc_path), output_dir=tmp_dir)
        cir_text = transcribed.netlist_text
        cir_path = Path(tmp_dir) / f"{asc_path.stem}.cir"
        cir_path.write_text(cir_text, encoding="utf-8")
        sim_result = spice_executor.execute(str(cir_path))
        syntax_pass = bool(sim_result.success)
        error_message = None if syntax_pass else str(sim_result.error)

    transcribed_component_count = count_components_in_cir_text(cir_text)
    cpr = (
        min(transcribed_component_count, expected_component_count) / expected_component_count
        if expected_component_count > 0 else 0.0
    )

    return {
        "name": asc_path.stem,
        "asc_path": asc_path.as_posix(),
        "expected_component_count": expected_component_count,
        "transcribed_component_count": transcribed_component_count,
        "cpr_pct": cpr * 100.0,
        "syntax_pass": bool(syntax_pass),
        "warning_count": len(transcribed.warnings),
        "validation_error_count": len(transcribed.validation_errors),
        "degraded": bool(transcribed.degraded),
        "error_message": error_message,
    }


def run_batch(asc_root: str, output_json: str, output_csv: str) -> Dict[str, Any]:
    root = Path(asc_root).expanduser().resolve()
    asc_files = iter_asc_files(root)
    transcriber = LtspiceAscToCirTranscriber()
    configure_ngspice()
    spice_executor = SpiceExecutor()
    if not spice_executor.is_available():
        init_error = getattr(spice_executor, "_init_error", None) or "SpiceExecutor is not available"
        raise RuntimeError(init_error)

    records: List[Dict[str, Any]] = []
    for index, asc_path in enumerate(asc_files, start=1):
        logger.info("[%d/%d] Transcribing %s", index, len(asc_files), asc_path.relative_to(root).as_posix())
        records.append(_evaluate_one(transcriber, spice_executor, asc_path))

    syntax_passes = [r for r in records if r["syntax_pass"]]
    validation_clean = [r for r in records if r["validation_error_count"] == 0]
    non_degraded = [r for r in records if not r["degraded"]]

    payload = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "asc_root": str(root),
        "summary": {
            "total_files": len(records),
            "syntax_pass_count": len(syntax_passes),
            "syntax_pass_rate_pct": (len(syntax_passes) / len(records) * 100.0) if records else 0.0,
            "mean_cpr_pct": describe_numeric([r["cpr_pct"] for r in records]).get("mean"),
            "validation_clean_rate_pct": (len(validation_clean) / len(records) * 100.0) if records else 0.0,
            "non_degraded_rate_pct": (len(non_degraded) / len(records) * 100.0) if records else 0.0,
            "warning_count": describe_numeric([r["warning_count"] for r in records]),
            "validation_error_count": describe_numeric([r["validation_error_count"] for r in records]),
        },
        "records": records,
    }

    write_json(output_json, payload)
    write_csv(output_csv, [{k: normalize_for_csv(v) for k, v in row.items()} for row in records])
    return payload


def main() -> None:
    parser = argparse.ArgumentParser(description="Batch evaluate LTspice ASC transcription quality")
    parser.add_argument("--asc_root", default=str(_PROJECT_ROOT / "circuit_geo_data"))
    parser.add_argument("--output_json", default=str(_PROJECT_ROOT / "evaluation" / "reports" / "transcription_batch_eval.json"))
    parser.add_argument("--output_csv", default=str(_PROJECT_ROOT / "evaluation" / "reports" / "transcription_batch_eval.csv"))
    parser.add_argument("--log_level", default="INFO")
    args = parser.parse_args()

    logging.basicConfig(level=getattr(logging, str(args.log_level).upper(), logging.INFO), format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
    payload = run_batch(args.asc_root, args.output_json, args.output_csv)
    summary = payload["summary"]
    print("=" * 60)
    print("TRANSCRIPTION BATCH EVAL")
    print("=" * 60)
    print(f"Total ASC files:       {summary['total_files']}")
    print(f"Syntax pass rate:      {summary['syntax_pass_rate_pct']:.2f}%")
    mean_cpr = summary.get("mean_cpr_pct")
    if mean_cpr is not None:
        print(f"Mean CPR:              {mean_cpr:.2f}%")
    print(f"Validation clean rate: {summary['validation_clean_rate_pct']:.2f}%")
    print(f"Non-degraded rate:     {summary['non_degraded_rate_pct']:.2f}%")
    print("=" * 60)


if __name__ == "__main__":
    main()
