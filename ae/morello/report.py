#!/usr/bin/env python3
"""Validate and summarize one collected Morello p01 hardware run."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import statistics
from pathlib import Path
from typing import Any

EXPECTED_SHA256 = "11f2f931a37dc6ae04eb6f6fe4ba4006b0feb3f9442878e9da6571f02b3c3b1a"
PAPER = {
    "baseline_o3_median_cycles": 8_509_341.5,
    "o3_asm_median_cycles": 8_494_868.5,
    "improvement_percent": 0.17008366628604576,
    "applied_rewrites": 0,
}


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _cv_percent(values: list[int]) -> float:
    mean = statistics.fmean(values)
    return 0.0 if mean == 0 else 100.0 * statistics.pstdev(values) / mean


def _canonical_result(
    variant: str, records: list[dict[str, Any]], median_cycles: float
) -> dict[str, Any]:
    instructions = [int(record["inst_retired"]) for record in records]
    cycles = [int(record["cpu_cycles"]) for record in records]
    return {
        "schema_version": 1,
        "arch": "arm_morello",
        "bench": "p01",
        "pipeline": variant,
        "n_runs": len(records),
        "instr_count": statistics.median(instructions),
        "extra": {
            "metric": "pmcstat",
            "cycles": median_cycles,
            "cycles_samples": cycles,
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[2])
    parser.add_argument("--run-dir", required=True)
    args = parser.parse_args()

    root = args.root.resolve()
    run_dir = (root / args.run_dir).resolve()
    allowed = (root / "ae-output" / "morello").resolve()
    try:
        run_dir.relative_to(allowed)
    except ValueError as exc:
        parser.error(f"--run-dir must be under {allowed.relative_to(root)}")

    provenance = json.loads((run_dir / "provenance.json").read_text())
    records = [
        json.loads(line)
        for line in (run_dir / "raw" / "samples.ndjson").read_text().splitlines()
        if line.strip()
    ]
    measured = [record for record in records if not record["warmup"]]
    groups = {
        variant: [record for record in measured if record["variant"] == variant]
        for variant in ("baseline_o3", "o3_asm")
    }
    expected_n = int(provenance["iterations"])
    local_inputs = root / "ae" / "inputs" / "morello-p01"
    hashes = {
        "baseline_o3": _sha256(local_inputs / "baseline_o3-p01"),
        "o3_asm": _sha256(local_inputs / "o3_asm-p01"),
    }

    medians = {
        variant: statistics.median(
            int(record["cpu_cycles"]) for record in variant_records
        )
        for variant, variant_records in groups.items()
    }
    cvs = {
        variant: _cv_percent(
            [int(record["cpu_cycles"]) for record in variant_records]
        )
        for variant, variant_records in groups.items()
    }
    improvement = 100.0 * (
        medians["baseline_o3"] - medians["o3_asm"]
    ) / medians["baseline_o3"]

    checks = {
        "pinned_payload_hashes": set(hashes.values()) == {EXPECTED_SHA256},
        "remote_payload_hashes": provenance["remote_payload_sha256"] == hashes,
        "byte_identical_variants": hashes["baseline_o3"] == hashes["o3_asm"],
        "sample_count": all(len(items) == expected_n for items in groups.values()),
        "all_exits_zero": all(int(record["exit_code"]) == 0 for record in records),
        "positive_counters": all(
            int(record["cpu_cycles"]) > 0 and int(record["inst_retired"]) > 0
            for record in records
        ),
        # The two payloads are identical. Their measured difference must be
        # interpreted as whole-process measurement noise, not a speedup.
        "near_zero_difference": abs(improvement) <= 2.0,
        "paper_cycle_scale": all(
            math.isclose(
                medians[variant],
                PAPER[f"{variant}_median_cycles"],
                rel_tol=0.15,
            )
            for variant in groups
        ),
    }
    passed = all(checks.values())

    canonical = run_dir / "results" / "arm_morello" / "p01"
    for variant in groups:
        destination = canonical / variant
        destination.mkdir(parents=True, exist_ok=True)
        result = _canonical_result(variant, groups[variant], medians[variant])
        (destination / "result.json").write_text(
            json.dumps(result, indent=2, sort_keys=True) + "\n"
        )

    report = {
        "schema_version": 1,
        "status": "PASS" if passed else "FAIL",
        "experiment": provenance["experiment"],
        "scope": provenance["scope"],
        "paper_expected": PAPER,
        "observed": {
            "baseline_o3_median_cycles": medians["baseline_o3"],
            "o3_asm_median_cycles": medians["o3_asm"],
            "improvement_percent": improvement,
            "cycle_cv_percent": cvs,
            "applied_rewrites": 0,
            "interpretation": (
                "The binaries are byte-identical; the observed delta is "
                "run-to-run noise and is consistent with the paper's p01 row."
            ),
        },
        "checks": checks,
    }
    (run_dir / "report.json").write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n"
    )

    print("Morello p01 hardware spot-check")
    print(
        f"  baseline median: {medians['baseline_o3']:,.1f} cycles "
        f"(CV {cvs['baseline_o3']:.2f}%)"
    )
    print(
        f"  -O3+CapOpt median: {medians['o3_asm']:,.1f} cycles "
        f"(CV {cvs['o3_asm']:.2f}%)"
    )
    print(f"  observed delta: {improvement:+.2f}% (byte-identical payloads)")
    for name, ok in checks.items():
        print(f"  {'PASS' if ok else 'FAIL'} {name}")
    print(f"  Report: {run_dir.relative_to(root)}/report.json")
    print(f"MORELLO P01: {'PASS' if passed else 'FAIL'}")
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
