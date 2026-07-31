"""Fresh-recomputation lane: each C4–C7 claim command must launch the real
analysis script (or fresh aggregation) over shipped raw evidence, write a
report under ae-output/recompute/, and exit zero only when the fresh values
match the shipped summaries and paper-expected numbers."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
REPORTS = ROOT / "ae-output" / "recompute"


def _recompute(claim: str) -> dict:
    result = subprocess.run(
        [sys.executable, str(ROOT / "ae" / "recompute_claims.py"), claim],
        cwd=ROOT,
        text=True,
        capture_output=True,
    )
    assert result.returncode == 0, (
        f"recompute {claim} failed\nstdout:\n{result.stdout}\nstderr:\n{result.stderr}"
    )
    report_path = REPORTS / f"{claim.lower()}.json"
    assert report_path.is_file(), f"missing report {report_path}"
    report = json.loads(report_path.read_text())
    assert report["claim_id"].startswith(claim), report["claim_id"]
    assert report["passed"] is True, json.dumps(report, indent=2)[:4000]
    return report


def test_c4_reruns_classifier_on_frozen_raw_counts() -> None:
    report = _recompute("C4")
    assert report["observed"]["total_accepted_rewrites"] == 782
    assert "classify_rewrites.py" in " ".join(report["command"])


def test_c5_reruns_gen_pruning_stats_per_config() -> None:
    report = _recompute("C5")
    configs = report["configs"]
    assert set(configs) == {"full", "no-alias-prune", "no-pattern-library"}
    for name, config in configs.items():
        assert config["fresh"]["filtered_before_smt_percent"] == 25.1, name
        assert "gen_pruning_stats.py" in " ".join(config["command"]), name
    assert configs["no-alias-prune"]["fresh_sidecars_byte_identical_to_full"] is True
    assert configs["no-pattern-library"]["fresh_sidecars_byte_identical_to_full"] is True


def test_c6_reruns_souper_summarize_from_raw() -> None:
    report = _recompute("C6")
    assert "souper_comparison.py" in " ".join(report["command"])
    verdict = report["fresh"]["verdict"]
    assert verdict["geomean_within_2pp"] is True
    assert verdict["all_kernels_within_2pp"] is True
    assert verdict["kernels_compared"] == 25
    # The per-TU Souper solver counters need the non-vendored build tree and
    # must be reported as excluded, never silently compared.
    assert "souper_smt_queries" in report["fields_excluded_from_comparison"]


def test_c7_recomputes_measurements_and_audits_recorded_fields() -> None:
    report = _recompute("C7")
    assert report["fresh"]["kernels"] == 25
    assert report["fresh"]["geomean_improvement_pct"] == report["expected"][
        "geomean_improvement_pct"
    ]
    audit = report["recorded_evidence_audit"]
    assert audit["kernels_with_applied_rewrites"] == 0
    assert audit["kernels_text_differing"] == 0
    assert audit["suite_smt_proven"] == 0
