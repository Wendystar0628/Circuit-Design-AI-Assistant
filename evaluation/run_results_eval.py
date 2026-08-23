from __future__ import annotations

import argparse
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from evaluation.results_eval_utils import write_json
from evaluation.simulation_results_summary import summarize_simulation_results
from evaluation.testcircuit_batch_eval import run_batch as run_testcircuit_batch
from evaluation.transcription_batch_eval import run_batch as run_transcription_batch

logger = logging.getLogger("evaluation.run_results_eval")


def run_all(
    test_root: str,
    results_root: str,
    asc_root: str,
    report_dir: str,
) -> Dict[str, Any]:
    output_root = Path(report_dir).expanduser().resolve()
    output_root.mkdir(parents=True, exist_ok=True)

    logger.info("Running TestCircuit batch evaluation...")
    testcircuit_payload = run_testcircuit_batch(
        test_root=test_root,
        output_json=str(output_root / "testcircuit_batch_eval.json"),
        output_csv=str(output_root / "testcircuit_batch_eval.csv"),
    )

    logger.info("Summarizing simulation_results bundles...")
    simulation_results_payload = summarize_simulation_results(
        results_root=results_root,
        output_json=str(output_root / "simulation_results_summary.json"),
        output_csv=str(output_root / "simulation_results_summary.csv"),
    )

    logger.info("Running transcription batch evaluation...")
    transcription_payload = run_transcription_batch(
        asc_root=asc_root,
        output_json=str(output_root / "transcription_batch_eval.json"),
        output_csv=str(output_root / "transcription_batch_eval.csv"),
    )

    combined = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "report_dir": str(output_root),
        "thesis_metrics": {
            "testcircuit_total": testcircuit_payload["summary"]["total_circuits"],
            "testcircuit_success_rate_pct": testcircuit_payload["summary"]["success_rate_pct"],
            "testcircuit_result_valid_rate_pct": testcircuit_payload["summary"]["result_valid_rate_pct"],
            "testcircuit_metric_capture_rate_pct": testcircuit_payload["summary"]["metric_capture_rate_pct"],
            "testcircuit_mean_duration_ms": (testcircuit_payload["summary"].get("duration_ms") or {}).get("mean"),
            "testcircuit_p95_duration_ms": (testcircuit_payload["summary"].get("duration_ms") or {}).get("p95"),
            "historical_bundle_count": simulation_results_payload["summary"]["total_bundles"],
            "historical_unique_circuits": simulation_results_payload["summary"]["unique_circuits"],
            "historical_success_rate_pct": simulation_results_payload["summary"]["success_rate_pct"],
            "historical_error_free_rate_pct": simulation_results_payload["summary"]["error_free_rate_pct"],
            "transcription_total_files": transcription_payload["summary"]["total_files"],
            "transcription_syntax_pass_rate_pct": transcription_payload["summary"]["syntax_pass_rate_pct"],
            "transcription_mean_cpr_pct": transcription_payload["summary"]["mean_cpr_pct"],
        },
        "testcircuit": testcircuit_payload,
        "simulation_results": simulation_results_payload,
        "transcription": transcription_payload,
    }

    write_json(output_root / "results_eval_suite.json", combined)
    return combined


def main() -> None:
    parser = argparse.ArgumentParser(description="Run thesis-oriented batch evaluation for TestCircuit and simulation_results")
    parser.add_argument("--test_root", default=str(_PROJECT_ROOT / "TestCircuit"))
    parser.add_argument("--results_root", default=str(_PROJECT_ROOT / "TestCircuit" / "simulation_results"))
    parser.add_argument("--asc_root", default=str(_PROJECT_ROOT / "circuit_geo_data"))
    parser.add_argument("--report_dir", default=str(_PROJECT_ROOT / "evaluation" / "reports"))
    parser.add_argument("--log_level", default="INFO")
    args = parser.parse_args()

    logging.basicConfig(level=getattr(logging, str(args.log_level).upper(), logging.INFO), format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
    combined = run_all(
        test_root=args.test_root,
        results_root=args.results_root,
        asc_root=args.asc_root,
        report_dir=args.report_dir,
    )

    metrics = combined["thesis_metrics"]
    print("=" * 60)
    print("RESULTS EVAL SUITE")
    print("=" * 60)
    print(f"TestCircuit success rate:      {metrics['testcircuit_success_rate_pct']:.2f}%")
    print(f"Historical bundle count:      {metrics['historical_bundle_count']}")
    print(f"Historical success rate:      {metrics['historical_success_rate_pct']:.2f}%")
    print(f"Transcription syntax pass:    {metrics['transcription_syntax_pass_rate_pct']:.2f}%")
    mean_cpr = metrics.get("transcription_mean_cpr_pct")
    if mean_cpr is not None:
        print(f"Transcription mean CPR:       {mean_cpr:.2f}%")
    print("=" * 60)


if __name__ == "__main__":
    main()
