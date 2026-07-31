#!/usr/bin/env python3
"""Freshly recompute the C4–C7 claim evidence from shipped raw data.

Each claim command launches the repository's own analysis script (C4/C5/C6)
or performs a fresh aggregation (C7 measurements) over the raw evidence
vendored in artifact/source/results, then compares the fresh values against
the shipped summaries and the paper-expected numbers. Nothing under
artifact/source is modified; staging and reports live in ae-output/recompute.

C7's build-derived fields (applied rewrites, .text digests, suite search
totals) come from build sidecars and llvm-objcopy digests that are not
vendored; they are audited from the recorded run, never recomputed here.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import shutil
import statistics
import subprocess
import sys
from pathlib import Path
from typing import Any, Callable

ROOT = Path(__file__).resolve().parents[1]
LIB = ROOT / "artifact" / "lib"
SOURCE = ROOT / "artifact" / "source"
SCRIPTS = SOURCE / "scripts"
RESULTS = SOURCE / "results"
OUTPUT = ROOT / "ae-output" / "recompute"
KERNELS = [f"p{i:02d}" for i in range(1, 26)]

PAPER_C4 = {
    "total_accepted_rewrites": 782,
    "category_breakdown_count": {
        "capability_walk_or_cincoffset_folding": 250,
        "permission_or_bounds_restriction": 171,
        "arithmetic_normalisation": 38,
        "boolean_compare_simplification": 19,
        "generic_enumerative_or_other": 304,
    },
    "category_breakdown_percent": {
        "capability_walk_or_cincoffset_folding": 32.0,
        "permission_or_bounds_restriction": 21.9,
        "arithmetic_normalisation": 4.9,
        "boolean_compare_simplification": 2.4,
        "generic_enumerative_or_other": 38.9,
    },
    "library_attributed_count": 478,
    "library_attributed_percent": 61.1,
}


def _printable(command: list[str]) -> list[str]:
    prefix = str(ROOT) + os.sep
    return [
        part[len(prefix):] if part.startswith(prefix) else part
        for part in command
    ]


def _launch(
    command: list[str],
    *,
    cwd: Path,
    env: dict[str, str] | None = None,
    capture: bool = False,
) -> None:
    print("$", " ".join(_printable(command)), flush=True)
    result = subprocess.run(
        command,
        cwd=cwd,
        env=env,
        text=True,
        capture_output=capture,
        check=False,
    )
    if result.returncode:
        if capture:
            print(result.stdout)
            print(result.stderr, file=sys.stderr)
        raise RuntimeError(
            f"{_printable(command)[1]} exited with {result.returncode}"
        )


def _mismatches(fresh: dict[str, Any], expected: dict[str, Any]) -> dict[str, Any]:
    return {
        key: {"fresh": fresh[key], "expected": expected[key]}
        for key in expected
        if fresh.get(key) != expected[key]
    }


def recompute_c4() -> dict[str, Any]:
    """Launch scripts/classify_rewrites.py over the frozen per-rule counts."""
    evidence = RESULTS / "optmix" / "a4_dev_host_harvest.json"
    json_out = OUTPUT / "c4_classification.json"
    command = [
        sys.executable,
        str(SCRIPTS / "classify_rewrites.py"),
        "--from-raw",
        str(evidence),
        "--json-out",
        str(json_out),
    ]
    _launch(command, cwd=SOURCE, capture=True)
    classified = json.loads(json_out.read_text())
    observed = {key: classified[key] for key in PAPER_C4}
    mismatches = _mismatches(observed, PAPER_C4)
    print(
        f"  fresh classification: {observed['total_accepted_rewrites']} accepted; "
        f"counts={list(observed['category_breakdown_count'].values())}; "
        f"library-attributed={observed['library_attributed_percent']}%"
    )
    return {
        "claim_id": "C4-rewrite-diversity",
        "paper": "Section 6.3, rewrite classification table",
        "method": (
            "Launch the repository's scripts/classify_rewrites.py --from-raw "
            "over the frozen per-rule harvest counts and compare its fresh "
            "output with the published table."
        ),
        "command": _printable(command),
        "evidence": str(evidence.relative_to(ROOT)),
        "fresh_output": str(json_out.relative_to(ROOT)),
        "observed": observed,
        "expected": PAPER_C4,
        "mismatches": mismatches,
        "passed": not mismatches,
    }


def recompute_c5() -> dict[str, Any]:
    """Launch scripts/gen_pruning_stats.py per config over shipped sidecars."""
    shipped = json.loads((RESULTS / "ablation_v3" / "summary.json").read_text())[
        "configs"
    ]
    full_raw = RESULTS / "ablation_v3" / "full" / "raw"
    configs: dict[str, Any] = {}
    passed = True
    for cfg in ("full", "no-alias-prune", "no-pattern-library"):
        raw = RESULTS / "ablation_v3" / cfg / "raw"
        stage = OUTPUT / "c5-stage" / cfg
        if stage.exists():
            shutil.rmtree(stage)
        for kernel in KERNELS:
            sidecar = json.loads((raw / f"{kernel}.search_stats.json").read_text())
            kernel_dir = stage / kernel
            kernel_dir.mkdir(parents=True)
            (kernel_dir / "result.json").write_text(
                json.dumps({"search_stats": sidecar})
            )
        json_out = OUTPUT / f"c5_{cfg}.json"
        command = [
            sys.executable,
            str(SCRIPTS / "gen_pruning_stats.py"),
            "--root",
            str(stage),
            "--json-out",
            str(json_out),
        ]
        _launch(command, cwd=SOURCE, capture=True)
        stats = json.loads(json_out.read_text())
        fresh = {
            "files_all_rounds_accounting": stats["files_all_rounds_accounting"],
            "enumerated_total": stats["enumerated_total"],
            "smt_queried": stats["smt_queried"],
            "cached_verdicts": stats["cached_verdicts"],
            "reached_verification": stats["reached_verification"],
            "filtered_before_smt_percent": stats["filtered_before_smt_percent"],
        }
        expected = {
            "files_all_rounds_accounting": shipped[cfg]["kernels_ok"],
            "enumerated_total": shipped[cfg]["enumerated"],
            "smt_queried": shipped[cfg]["smt_queried"],
            "cached_verdicts": shipped[cfg]["cached_verdicts"],
            "reached_verification": shipped[cfg]["reached_verification"],
            "filtered_before_smt_percent": shipped[cfg]["filtered_before_smt_pct"],
        }
        mismatches = _mismatches(fresh, expected)

        applied_asm = applied_ir = 0
        for kernel in KERNELS:
            functions = json.loads(
                (raw / f"{kernel}.functions.json").read_text()
            ).get("functions") or {}
            for record in functions.values():
                if not isinstance(record, dict) or "error" in record:
                    continue
                applied_asm += len(record.get("applied_assembly") or [])
                applied_ir += len(record.get("applied_ir") or [])
        applied_total = applied_asm + applied_ir
        entry: dict[str, Any] = {
            "command": _printable(command),
            "fresh_output": str(json_out.relative_to(ROOT)),
            "fresh": fresh,
            "expected_from_shipped_summary": expected,
            "mismatches": mismatches,
            "fresh_applied_rewrites_total": applied_total,
            "expected_applied_rewrites_total": shipped[cfg][
                "applied_rewrites_total"
            ],
        }
        config_ok = (
            not mismatches
            and applied_total == shipped[cfg]["applied_rewrites_total"]
        )
        if cfg != "full":
            identical = all(
                (raw / f"{kernel}.search_stats.json").read_bytes()
                == (full_raw / f"{kernel}.search_stats.json").read_bytes()
                for kernel in KERNELS
            )
            entry["fresh_sidecars_byte_identical_to_full"] = identical
            entry["expected_sidecars_byte_identical_to_full"] = shipped[cfg][
                "sidecars_byte_identical_to_full"
            ]
            config_ok &= identical == shipped[cfg][
                "sidecars_byte_identical_to_full"
            ]
        entry["passed"] = config_ok
        passed &= config_ok
        configs[cfg] = entry
        identical_note = (
            f", sidecars byte-identical to full={entry['fresh_sidecars_byte_identical_to_full']}"
            if cfg != "full"
            else ""
        )
        print(
            f"  {cfg}: fresh filtered-before-SMT="
            f"{fresh['filtered_before_smt_percent']}% "
            f"({fresh['smt_queried']} queried of {fresh['enumerated_total']} "
            f"enumerated), applied rewrites={applied_total}{identical_note}"
        )
    return {
        "claim_id": "C5-pre-smt-pruning",
        "paper": "Section 6.3, pre-SMT filtering ablation",
        "method": (
            "Stage the 25 shipped per-kernel search-stat sidecars of each "
            "ablation config and launch the repository's "
            "scripts/gen_pruning_stats.py on them, then compare the fresh "
            "aggregate with the shipped summary. Applied-rewrite totals are "
            "freshly re-counted from the functions.json sidecars, and the "
            "no-op configs are freshly re-checked byte-for-byte."
        ),
        "configs": configs,
        "paper_alignment": (
            "This lane verifies the reproducibility of the recorded "
            "ablation_v3 evidence (pre-screening pipeline, 25.1% filtered, "
            "alias-prune / pattern-library A/B). The paper's ~98.7% "
            "pre-SMT-filtering claim itself is carried by the "
            "results/pruning_v4 evidence (98.7% with concrete-input "
            "screening; see C5-pre-smt-pruning in claims/manifest.json and "
            "the reproduce-short lane's read-only reaggregation)."
        ),
        "passed": passed,
    }


def recompute_c6() -> dict[str, Any]:
    """Launch scripts/souper_comparison.py summarize over the shipped raw tree."""
    stage = OUTPUT / "c6-stage"
    if stage.exists():
        shutil.rmtree(stage)
    (stage / "scripts").mkdir(parents=True)
    (stage / "benchmarks" / "scripts").mkdir(parents=True)
    shutil.copy2(
        SCRIPTS / "souper_comparison.py", stage / "scripts" / "souper_comparison.py"
    )
    shutil.copy2(
        SOURCE / "benchmarks" / "scripts" / "build_hacker_benchmarks.py",
        stage / "benchmarks" / "scripts" / "build_hacker_benchmarks.py",
    )
    shutil.copytree(
        RESULTS / "souper_comparison" / "raw",
        stage / "results" / "souper_comparison" / "raw",
    )
    command = [
        sys.executable,
        str(stage / "scripts" / "souper_comparison.py"),
        "summarize",
        "--iter-arg",
        "10000000",
    ]
    for kernel in KERNELS:
        command += ["--bench", kernel]
    env = dict(os.environ)
    env["PYTHONPATH"] = os.pathsep.join(
        [str(LIB), str(SOURCE), str(SOURCE / "superoptimization")]
    )
    _launch(command, cwd=stage, env=env)
    fresh_summary = json.loads(
        (stage / "results" / "souper_comparison" / "summary.json").read_text()
    )
    shipped_summary = json.loads(
        (RESULTS / "souper_comparison" / "summary.json").read_text()
    )

    # Per-TU tool counters (solver queries, changed-TU / applied-rewrite
    # counts) live in the non-vendored build tree; they are excluded from the
    # comparison and reported as such, never silently compared.
    excluded = [
        "souper_smt_queries",
        "souper_ir_changed_tus",
        "capopt_asm_rewrites",
        "capopt_ir_changed_tus",
    ]
    comparable = json.loads(json.dumps(shipped_summary))
    for row in comparable["rows"]:
        for key in excluded:
            row.pop(key, None)
    leaked = sorted(
        {key for row in fresh_summary["rows"] for key in excluded if key in row}
    )

    section_mismatches: dict[str, Any] = {}
    for section in (
        "experiment",
        "drift_probe",
        "config",
        "rows",
        "geomean",
        "verdict",
        "failures",
    ):
        if fresh_summary.get(section) == comparable.get(section):
            continue
        if section == "rows":
            details = []
            for fresh_row, shipped_row in zip(
                fresh_summary["rows"], comparable["rows"]
            ):
                keys = sorted(
                    key
                    for key in set(fresh_row) | set(shipped_row)
                    if fresh_row.get(key) != shipped_row.get(key)
                )
                if keys:
                    details.append({"bench": shipped_row["bench"], "keys": keys})
            section_mismatches[section] = details
        else:
            section_mismatches[section] = {
                "fresh": fresh_summary.get(section),
                "expected": comparable.get(section),
            }
    passed = not section_mismatches and not leaked

    verdict = fresh_summary["verdict"]
    print(
        f"  fresh geomean diff={verdict['geomean_abs_diff_pp']:.3f}pp "
        f"(within 2pp: {verdict['geomean_within_2pp']}); max per-kernel "
        f"diff={verdict['max_per_kernel_abs_diff_pp']:.3f}pp (all within 2pp: "
        f"{verdict['all_kernels_within_2pp']}); failures={fresh_summary['failures']}"
    )
    return {
        "claim_id": "C6-souper-comparison",
        "paper": "Section 6.4, comparison with Souper",
        "method": (
            "Copy the shipped raw measurement tree into a staging area and "
            "launch the repository's scripts/souper_comparison.py summarize "
            "on it, then compare the freshly generated summary with the "
            "shipped one section by section."
        ),
        "command": _printable(command),
        "stage": str(stage.relative_to(ROOT)),
        "fresh": {
            "rows": len(fresh_summary["rows"]),
            "geomean": fresh_summary["geomean"],
            "verdict": verdict,
            "failures": fresh_summary["failures"],
        },
        "fields_excluded_from_comparison": excluded,
        "exclusion_reason": (
            "Per-TU Souper solver counters come from build-tree sidecars "
            "(benchmarks/build/hacker/riscv-noncheri) that are not vendored; "
            "every measurement-derived field is compared."
        ),
        "excluded_fields_present_in_fresh_rows": leaked,
        "section_mismatches": section_mismatches,
        "paper_alignment": (
            "The fresh geomean gap is within 2 points but the maximum "
            "per-kernel gap is not; the paper's per-kernel wording is still "
            "pending correction, so the claim stays BLOCKED in "
            "claims/manifest.json."
        ),
        "passed": passed,
    }


def recompute_c7() -> dict[str, Any]:
    """Freshly re-aggregate the -O3-start measurements; audit recorded fields."""
    run_dir = RESULTS / "runs" / "2026-07-16_o3-start-hd-morello"
    shipped = json.loads((run_dir / "o3start_analysis.json").read_text())
    shipped_rows = {row["bench"]: row for row in shipped["rows"]}
    measure_keys = (
        "base_cycles",
        "o3asm_cycles",
        "ratio",
        "improvement_pct",
        "base_spread_pct",
        "o3asm_spread_pct",
        "n_base",
        "n_o3asm",
    )

    rows: list[dict[str, Any]] = []
    mismatches: dict[str, Any] = {}
    median_check_failures: list[str] = []
    for bench in KERNELS:
        sides: dict[str, dict[str, Any]] = {}
        for pipe in ("baseline_o3", "o3_asm"):
            data = json.loads(
                (run_dir / "arm_morello" / bench / pipe / "result.json").read_text()
            )
            extra = data.get("extra") or {}
            samples = extra.get("cycles_samples") or []
            recorded_median = float(extra.get("cycles"))
            if float(statistics.median(samples)) != recorded_median:
                median_check_failures.append(f"{bench}/{pipe}")
            sides[pipe] = {
                "median": recorded_median,
                "samples": samples,
                "n": data.get("n_runs"),
            }
        base, o3asm = sides["baseline_o3"], sides["o3_asm"]
        b, o = base["median"], o3asm["median"]
        fresh_row = {
            "bench": bench,
            "base_cycles": b,
            "o3asm_cycles": o,
            "ratio": o / b,
            "improvement_pct": (b - o) / b * 100.0,
            "base_spread_pct": (max(base["samples"]) - min(base["samples"]))
            / b
            * 100.0,
            "o3asm_spread_pct": (max(o3asm["samples"]) - min(o3asm["samples"]))
            / o
            * 100.0,
            "n_base": base["n"],
            "n_o3asm": o3asm["n"],
        }
        rows.append(fresh_row)
        expected_row = {key: shipped_rows[bench][key] for key in measure_keys}
        row_mismatches = _mismatches(fresh_row, expected_row)
        if row_mismatches:
            mismatches[bench] = row_mismatches

    ratios = [row["ratio"] for row in rows]
    gm_ratio = math.exp(sum(math.log(value) for value in ratios) / len(ratios))
    fresh = {
        "kernels": len(rows),
        "geomean_ratio_o3asm_over_o3": gm_ratio,
        "geomean_improvement_pct": (1.0 - gm_ratio) * 100.0,
    }
    expected = {
        "kernels": len(shipped["rows"]),
        "geomean_ratio_o3asm_over_o3": shipped["geomean_ratio_o3asm_over_o3"],
        "geomean_improvement_pct": shipped["geomean_improvement_pct"],
    }
    geomean_mismatches = _mismatches(fresh, expected)

    zero_rows = all(
        (row.get("applied_rewrites") or 0) == 0
        and not row.get("applied_list")
        and row.get("text_identical") is True
        for row in shipped["rows"]
    )
    audit = {
        "kernels_with_applied_rewrites": shipped["kernels_with_applied_rewrites"],
        "kernels_text_differing": shipped["kernels_text_differing"],
        "suite_smt_proven": shipped["search_stats_suite_totals"][
            "verification.smt_proven"
        ],
        "all_rows_zero_applied_and_text_identical": zero_rows,
        "provenance": (
            "Recorded by the dated campaign from build sidecars and "
            "llvm-objcopy .text digests; the build tree and Morello SDK are "
            "not vendored, so these fields are audited, not recomputed. "
            "Fresh complements: the kick-the-tires p01 assembly search and "
            "the optional Section 5 Morello p01 execution."
        ),
    }
    audit_ok = (
        audit["kernels_with_applied_rewrites"] == 0
        and audit["kernels_text_differing"] == 0
        and audit["suite_smt_proven"] == 0
        and zero_rows
    )
    passed = (
        not mismatches
        and not median_check_failures
        and not geomean_mismatches
        and audit_ok
    )
    print(
        f"  fresh measurement aggregate: {fresh['kernels']} kernels, geomean "
        f"improvement={fresh['geomean_improvement_pct']:.3f}% (measurement "
        f"noise); per-kernel mismatches={len(mismatches)}"
    )
    print(
        f"  recorded-evidence audit: applied-rewrite kernels="
        f"{audit['kernels_with_applied_rewrites']}, text-differing kernels="
        f"{audit['kernels_text_differing']}, suite smt_proven="
        f"{audit['suite_smt_proven']}"
    )
    return {
        "claim_id": "C7-o3-start",
        "paper": "Section 6.4, starting from -O3",
        "method": (
            "Freshly re-derive every per-kernel median, ratio, improvement, "
            "spread, and the suite geomean from the 50 shipped raw Morello "
            "result.json files (re-checking each recorded median against its "
            "samples), compare with the shipped analysis, and audit the "
            "recorded build-derived zero-rewrite evidence."
        ),
        "raw_inputs": str(
            (run_dir / "arm_morello").relative_to(ROOT)
        )
        + "/<bench>/{baseline_o3,o3_asm}/result.json",
        "fresh": fresh,
        "expected": expected,
        "geomean_mismatches": geomean_mismatches,
        "per_kernel_mismatches": mismatches,
        "median_check_failures": median_check_failures,
        "recorded_evidence_audit": audit,
        "passed": passed,
    }


CLAIMS: dict[str, Callable[[], dict[str, Any]]] = {
    "C4": recompute_c4,
    "C5": recompute_c5,
    "C6": recompute_c6,
    "C7": recompute_c7,
}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "claim",
        choices=[*CLAIMS, "all"],
        help="claim to freshly recompute from shipped raw evidence",
    )
    args = parser.parse_args(argv)
    names = list(CLAIMS) if args.claim == "all" else [args.claim]
    OUTPUT.mkdir(parents=True, exist_ok=True)
    failed: list[str] = []
    for name in names:
        report = CLAIMS[name]()
        (OUTPUT / f"{name.lower()}.json").write_text(
            json.dumps(report, indent=2) + "\n"
        )
        print(f"{name} RECOMPUTE: {'PASS' if report['passed'] else 'FAIL'}")
        if not report["passed"]:
            failed.append(name)
    print(f"RECOMPUTE({args.claim}): {'FAIL' if failed else 'PASS'}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
