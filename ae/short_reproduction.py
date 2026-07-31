#!/usr/bin/env python3
"""Run the short, host-independent paper-result reproduction.

This lane deliberately targets paper Section 6.3 rather than the hardware
performance table. It runs production CapOpt code and Z3 on the seven small
workloads used by the frozen rewrite-mix harvest, then reclassifies the
harvest's raw per-rule counts to reproduce the published table exactly.
"""

from __future__ import annotations

import json
import logging
import os
import sys
import time
from collections import Counter
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "artifact" / "source"
OUTPUT = ROOT / "ae-output"
P01_INPUTS = ROOT / "ae" / "inputs" / "pruning-p01"

# OptimizationConfig reads several campaign defaults at import time, so set
# the exact archived p01 environment before importing CapOpt.
os.environ.update(
    {
        "CAPOPT_STORE_VARIANTS": "0",
        "CAPOPT_STRATUM_ESCALATION": "on_failure",
        "CAPOPT_CORRESPONDENCE_CHECK": "strict",
        "CAPOPT_W_BND_WIDTH": "0.25",
        "CAPOPT_W_PERM_BITS": "0.25",
        "CAPOPT_PATTERN_LIBRARY": str(
            SOURCE / "configs" / "pattern_store.morello-cheri.json"
        ),
        # The frozen p01 counters were captured with the assembler-parse gate
        # disabled; pin that explicitly so the lane reproduces identically in
        # both image flavors (the full image has llvm-mc on PATH).
        "CAPOPT_LLVM_MC": "off",
    }
)

# The core capopt package resolves from the prebuilt library first
# (artifact/lib); artifact/source keeps the open scripts on the path and
# remains a fallback should a future release place the package there.
LIB = ROOT / "artifact" / "lib"
for candidate in (SOURCE / "superoptimization", SOURCE / "scripts", SOURCE, LIB):
    if str(candidate) not in sys.path:
        sys.path.insert(0, str(candidate))

from capopt import OptimizationConfig  # noqa: E402
from capopt.capability_model import CapabilityModel  # noqa: E402
from capopt.cost_model import CostModel, CostWeights  # noqa: E402
from capopt.core import create_optimizer  # noqa: E402
from capopt.ir_superoptimizer import IRSuperoptimizer  # noqa: E402
from capopt.pgss import PGSSAlgorithm  # noqa: E402
from classify_rewrites import classify  # noqa: E402


WORKLOADS = {
    "foo": {
        "category": "capability_walk_or_cincoffset_folding",
        "required_pattern": "cincoffset_from_get_set",
        "ir": """define void @foo(i8 addrspace(200)* %cap) {
entry:
  %fresh = call i8 addrspace(200)* @llvm.cheri.cap.bounds.set(i8 addrspace(200)* %cap, i64 32)
  %addr = call i64 @llvm.cheri.cap.address.get(i8 addrspace(200)* %fresh)
  %tmp = add i64 %addr, 16
  %newcap = call i8 addrspace(200)* @llvm.cheri.cap.address.set(i8 addrspace(200)* %fresh, i64 %tmp)
  ret void
}""",
    },
    "tighten": {
        "category": "permission_or_bounds_restriction",
        "required_pattern": "ir_perms_and_fusion",
        "ir": """define void @tighten(i8 addrspace(200)* %cap, i64 %mask) {
entry:
  %perms = call i64 @llvm.cheri.cap.perms.get(i8 addrspace(200)* %cap)
  %masked = and i64 %perms, %mask
  %cap2 = call i8 addrspace(200)* @llvm.cheri.cap.perms.set(i8 addrspace(200)* %cap, i64 %masked)
  ret void
}""",
    },
    "bump": {
        "category": "capability_walk_or_cincoffset_folding",
        "required_pattern": "",
        "ir": """define ptr addrspace(200) @bump(ptr addrspace(200) %p) {
entry:
  %inc = getelementptr inbounds i32, ptr addrspace(200) %p, i64 1
  ret ptr addrspace(200) %inc
}""",
    },
    "neg_add": {
        "category": "arithmetic_normalisation",
        "required_pattern": "ir_add_neg_const_to_sub",
        "ir": """define i32 @neg_add(i32 %x) {
entry:
  %inc = add nsw i32 %x, -1
  ret i32 %inc
}""",
    },
    "neg_sub": {
        "category": "arithmetic_normalisation",
        "required_pattern": "ir_sub_neg_const_to_add",
        "ir": """define i32 @neg_sub(i32 %x) {
entry:
  %dec = sub nsw i32 %x, -5
  ret i32 %dec
}""",
    },
    "cond_true": {
        "category": "boolean_compare_simplification",
        "required_pattern": "ir_machine_bool_compare",
        "ir": """define i1 @cond_true(i1 %cond) {
entry:
  %cmp = icmp eq i1 %cond, true
  ret i1 %cmp
}""",
    },
    "self_compare": {
        "category": "generic_enumerative_or_other",
        "required_pattern": "ir_optimizer",
        "ir": """define i1 @self_compare(i32 %x) {
entry:
  %cmp = icmp eq i32 %x, %x
  ret i1 %cmp
}""",
    },
}


TEXTUAL_APPLICATIONS = {
    "foo": {
        "expected_rewrite": "cap_offset_increment",
        "expected_output": "@llvm.cheri.cap.offset.increment",
    },
    "tighten": {
        "expected_rewrite": "perms_and_rewrite",
        "expected_output": "@llvm.cheri.cap.perms.and",
    },
    "bump": {
        "expected_rewrite": "gep_offset_increment",
        "expected_output": "@llvm.cheri.cap.offset.increment",
    },
}


PAPER_EXPECTED = {
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


def _candidate_label(candidate: Any) -> str:
    metadata = candidate.metadata
    return str(metadata.get("pattern") or metadata.get("origin") or "unknown")


def _run_fresh_code() -> dict[str, Any]:
    capability_model = CapabilityModel()
    records: list[dict[str, Any]] = []

    for name, workload in WORKLOADS.items():
        config = OptimizationConfig(
            max_candidates=24,
            detailed_logging=False,
            enable_ir_stochastic_search=False,
            enable_ir_enumerative_search=False,
            enable_mcmc_candidates=False,
            enable_beam_candidates=False,
            enable_pattern_smt_gate=True,
        )
        pgss = PGSSAlgorithm(config)
        started = time.monotonic()
        candidates = pgss.generate_llvm_candidates(
            workload["ir"],
            name,
            capability_model.analyze_llvm_ir(workload["ir"]),
        )
        patterns = sorted({_candidate_label(item) for item in candidates})
        required_present = (not workload["required_pattern"]) or workload["required_pattern"] in patterns
        all_smt_proven = bool(candidates) and all(
            item.metadata.get("pattern_smt_proven") is True
            for item in candidates
        )
        records.append(
            {
                "workload": name,
                "paper_category": workload["category"],
                "required_pattern": workload["required_pattern"],
                "generated_patterns": patterns,
                "candidate_count": len(candidates),
                "all_candidates_apply_time_smt_proven": all_smt_proven,
                "elapsed_seconds": round(time.monotonic() - started, 4),
                "passed": required_present and all_smt_proven,
            }
        )

    cost_model = CostModel(CostWeights())
    applications: list[dict[str, Any]] = []
    for name, expected in TEXTUAL_APPLICATIONS.items():
        optimizer = IRSuperoptimizer(
            cost_model,
            capability_model,
            random_seed=0,
        )
        output_lines, applied = optimizer._apply_textual_rewrites(
            WORKLOADS[name]["ir"].splitlines()
        )
        output = "\n".join(output_lines)
        incidents = [str(item) for item in optimizer.textual_rewrite_incidents]
        passed = (
            expected["expected_rewrite"] in applied
            and expected["expected_output"] in output
            and not incidents
        )
        applications.append(
            {
                "workload": name,
                "expected_rewrite": expected["expected_rewrite"],
                "applied_rewrites": applied,
                "expected_output_marker": expected["expected_output"],
                "verification_incidents": incidents,
                "passed": passed,
            }
        )

    return {
        "scope": (
            "Fresh deterministic production-code replay of the seven small "
            "Section 6.3 workloads; no target hardware or recorded result "
            "values are used by this stage."
        ),
        "candidate_generation_and_apply_time_smt": records,
        "applied_cheri_rewrites": applications,
        "passed": (
            all(record["passed"] for record in records)
            and all(record["passed"] for record in applications)
        ),
    }



def _total(runs: list[tuple[dict[str, Any], dict[str, Any]]], section: str, key: str) -> int:
    return sum(int(stats[section].get(key, 0)) for _, stats in runs)


def _run_p01_assembly_search() -> dict[str, Any]:
    """Freshly rerun the archived Morello p01 assembly-search stage."""

    runs: list[tuple[dict[str, Any], dict[str, Any]]] = []
    started = time.monotonic()
    for filename in ("fxn.s", "main.s"):
        optimizer = create_optimizer(
            {"target_arch": "aarch64-morello", "detailed_logging": False}
        )
        result = optimizer.optimize_assembly_text((P01_INPUTS / filename).read_text())
        function_stats = result["search_stats"]
        if len(function_stats) != 1:
            raise RuntimeError(
                f"{filename}: expected one function, found {list(function_stats)}"
            )
        stats = next(iter(function_stats.values()))
        if stats.get("enumeration_accounting") != "all_rounds":
            raise RuntimeError(f"{filename}: incompatible enumeration accounting")
        if result.get("solver_verified") is not True:
            raise RuntimeError(f"{filename}: applied rewrite was not solver verified")
        runs.append((result, stats))

    enumerated = _total(runs, "enumeration", "generated_by_generators") + _total(
        runs, "enumeration", "generated_by_explorer"
    )
    queried = _total(runs, "verification", "smt_queried")
    cached = _total(runs, "verification", "cached_verdicts")
    reached = queried + cached
    fresh = {
        "kernel": "p01",
        "enumerated": enumerated,
        "generated_by_generators": _total(
            runs, "enumeration", "generated_by_generators"
        ),
        "generated_by_explorer": _total(
            runs, "enumeration", "generated_by_explorer"
        ),
        "emitted_after_dedup": _total(
            runs, "enumeration", "emitted_after_dedup"
        ),
        "candidates_considered": _total(
            runs, "verification", "candidates_considered"
        ),
        "smt_queried": queried,
        "cached_verdicts": cached,
        "reached_verification": reached,
        "filtered_before_smt_pct": round(
            100.0 * (1.0 - reached / enumerated), 1
        ),
        "smt_proven": _total(runs, "verification", "smt_proven"),
        "smt_refuted": _total(
            runs, "verification", "smt_refuted_counterexample"
        )
        + _total(runs, "verification", "smt_refuted_structural"),
        "abstained_unchecked": _total(
            runs, "verification", "abstained_unchecked"
        ),
        "quick_ce_rejects": _total(
            runs, "verification", "quick_ce_rejects"
        ),
        "assembler_rejects": _total(
            runs, "verification", "assembler_rejects"
        ),
        "solver_unavailable": _total(
            runs, "verification", "solver_unavailable"
        ),
        "dropped_provenance_prune": _total(
            runs, "enumeration", "dropped_provenance_prune"
        ),
        "dropped_stratum_gate": _total(
            runs, "enumeration", "dropped_stratum_gate"
        ),
        "dropped_stratum_cap": _total(
            runs, "enumeration", "dropped_stratum_cap"
        ),
        "applied_assembly_rewrites": sum(
            len(result["applied_optimizations"]) for result, _ in runs
        ),
    }
    frozen = json.loads(
        (P01_INPUTS / "expected_counters.json").read_text()
    )
    expected = {key: frozen["expected"][key] for key in fresh}
    mismatches = {
        key: {"fresh": value, "expected": expected[key]}
        for key, value in fresh.items()
        if value != expected[key]
    }
    return {
        "scope": (
            "Fresh assembly-search rerun from two shipped Morello p01 assembly "
            "translation units; no archived counters are inputs to the run. "
            "The frozen expectation snapshot was captured from the current "
            "CapOpt core (concrete-input screening enabled)."
        ),
        "inputs": [
            str((P01_INPUTS / name).relative_to(ROOT))
            for name in ("fxn.s", "main.s")
        ],
        "fresh": fresh,
        "expected_from_archived_p01_row": expected,
        "mismatches": mismatches,
        "elapsed_seconds": round(time.monotonic() - started, 4),
        "passed": not mismatches,
    }


def _reaggregate_c5() -> dict[str, Any]:
    """Read-only recomputation of the 25-kernel pre-SMT pruning headline.

    Reaggregates the shipped results/pruning_v4 per-kernel sidecars and
    compares the recomputed totals against the shipped summary headline
    (paper Section 6.3 claims ~98.7% filtered before SMT; the shipped
    evidence measures 98.7% with concrete-input screening enabled).
    """

    raw = SOURCE / "results" / "pruning_v4" / "riscv_cheri"
    paths = sorted(raw.glob("p*/capopt/result.json"))
    documents = [
        json.loads(path.read_text())["search_stats"] for path in paths
    ]
    compatible = len(documents) == 25

    def total(section: str, key: str) -> int:
        return sum(int(item.get(section, {}).get(key, 0)) for item in documents)

    enumerated = total("enumeration", "generated_by_generators") + total(
        "enumeration", "generated_by_explorer"
    )
    queried = total("verification", "smt_queried")
    cached = total("verification", "cached_verdicts")
    reached = queried + cached
    actual = {
        "kernels_ok": len(documents),
        "enumerated_total": enumerated,
        "fresh_smt_queries": queried,
        "cached_verdicts_consumed": cached,
        "reached_verification": reached,
        "filtered_before_smt_percent": round(
            100.0 * (1.0 - reached / enumerated), 1
        ),
        "smt_proven": total("verification", "smt_proven"),
    }
    headline = json.loads(
        (SOURCE / "results" / "pruning_v4" / "summary.json").read_text()
    )["headline"]
    expected = {
        key: headline[key] for key in actual if key in headline
    }
    expected["kernels_ok"] = 25
    mismatches = {
        key: {"observed": value, "expected": expected[key]}
        for key, value in actual.items()
        if value != expected[key]
    }
    meets_paper = (
        actual["filtered_before_smt_percent"]
        >= float(headline["paper_claim_percent"])
    )
    return {
        "claim_id": "C5-pre-smt-pruning",
        "paper": "Section 6.3 pre-SMT filtering",
        "method": (
            "Read-only reaggregation of the 25 shipped pruning_v4 per-kernel "
            "search-stat sidecars, compared against the shipped summary "
            "headline."
        ),
        "observed": actual,
        "expected": expected,
        "mismatches": mismatches,
        "paper_alignment": (
            f"Recomputed filtering rate "
            f"{actual['filtered_before_smt_percent']}% meets the paper's "
            f"~{headline['paper_claim_percent']}% claim."
        ),
        "passed": compatible and not mismatches and meets_paper,
    }

def _reproduce_c4() -> dict[str, Any]:
    evidence_path = SOURCE / "results" / "optmix" / "a4_dev_host_harvest.json"
    evidence = json.loads(evidence_path.read_text())
    observed_full = classify(Counter(evidence["raw_category_count"]))
    observed = {key: observed_full[key] for key in PAPER_EXPECTED}
    return {
        "claim_id": "C4-rewrite-diversity",
        "paper": "Section 6.3 rewrite-classification table",
        "method": (
            "Re-run scripts/classify_rewrites.py over the frozen raw "
            "per-rule counts; this is exact result recomputation, not a "
            "fresh performance measurement."
        ),
        "evidence": str(evidence_path.relative_to(ROOT)),
        "expected": PAPER_EXPECTED,
        "observed": observed,
        "passed": observed == PAPER_EXPECTED,
    }


def main() -> int:
    started = time.monotonic()
    # The implementation is intentionally chatty at INFO. The report
    # captures the useful experimental observations directly.
    logging.disable(logging.CRITICAL)
    fresh = _run_fresh_code()
    p01 = _run_p01_assembly_search()
    c4 = _reproduce_c4()
    c5 = _reaggregate_c5()
    elapsed = time.monotonic() - started

    report = {
        "schema_version": 1,
        "experiment": "short host-independent paper-result reproduction",
        "fresh_code_experiment": fresh,
        "fresh_p01_assembly_search": p01,
        "paper_result_reproduction": {"C4": c4, "C5": c5},
        "limitations": [
            "This lane freshly reruns the p01 search, reproduces C4, and "
            "reaggregates the corrected C5 value.",
            "It does not remeasure Table 2 performance, which requires the "
            "pinned CHERI toolchain plus QEMU-CHERI or Morello hardware.",
            "SPEC CPU2017 inputs are not redistributed.",
        ],
        "elapsed_seconds": round(elapsed, 4),
        "passed": (
            fresh["passed"] and p01["passed"] and c4["passed"] and c5["passed"]
        ),
    }

    OUTPUT.mkdir(parents=True, exist_ok=True)
    report_path = OUTPUT / "short-reproduction.json"
    report_path.write_text(json.dumps(report, indent=2) + "\n")

    print("Short host-independent reproduction")
    print("  Fresh production-code workloads:")
    for record in fresh["candidate_generation_and_apply_time_smt"]:
        print(
            f"    {'PASS' if record['passed'] else 'FAIL'} "
            f"{record['workload']}: {record['required_pattern']} "
            f"({record['candidate_count']} candidates, apply-time SMT proven)"
        )
    print("  Fresh applied CHERI rewrites:")
    for record in fresh["applied_cheri_rewrites"]:
        print(
            f"    {'PASS' if record['passed'] else 'FAIL'} "
            f"{record['workload']}: {record['expected_rewrite']}"
        )
    print("  Fresh p01 assembly search:")
    print(
        f"    {'PASS' if p01['passed'] else 'FAIL'} "
        f"enumerated={p01['fresh']['enumerated']}, "
        f"SMT-queried={p01['fresh']['smt_queried']}, "
        f"filtered={p01['fresh']['filtered_before_smt_pct']}%"
    )
    observed = c4["observed"]
    print("  Paper Section 6.3 recorded-evidence recomputation:")
    print(
        f"    {'PASS' if c4['passed'] else 'FAIL'} "
        f"{observed['total_accepted_rewrites']} accepted rewrites; "
        f"counts={list(observed['category_breakdown_count'].values())}; "
        f"library-attributed={observed['library_attributed_percent']}%"
    )
    print(
        f"    {'PASS' if c5['passed'] else 'FAIL'} "
        f"C5 full-suite filtered-before-SMT="
        f"{c5['observed']['filtered_before_smt_percent']}%"
    )
    print(f"  Report: {report_path.relative_to(ROOT)}")
    print(
        f"SHORT REPRODUCTION: {'PASS' if report['passed'] else 'FAIL'} "
        f"({elapsed:.2f}s)"
    )
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
