#!/usr/bin/env python3
"""Run the C1/C2/C3/C8/C9 analysis pipeline end to end on the bundled
small dataset (ae/inputs/small-campaign).

The final multi-day campaigns need CHERI hardware, a CHERI SDK, and QEMU,
none of which ship in the container. This lane instead demonstrates —
hardware-independently, on real recorded measurements — that every script
in those claims' pipelines runs correctly and that the claimed
relationships hold on the bundled suite:

  1. aggregate the mini result tree with capopt.reporting.aggregate_summary
     (imported from the prebuilt library in artifact/lib);
  2. launch scripts/gen_table.py on the aggregate (the Table 2 generator
     behind C1/C2/C3, including the geomean machinery);
  3. launch docs/figures/optimization_time.py on the aggregate (the C8
     figure);
  4. launch scripts/apply_validation_gate.py per architecture on a COPY of
     the tree (the C9 gate; the pristine checksummed inputs are never
     modified);
  5. assert the per-claim semantic properties on the outputs and write a
     machine-readable report to ae-output/small-campaign/report.json.

Full-campaign snapshots refresh the C1/C2/C3/C8/C9 evidence at freeze; this
lane keeps the pipeline itself verifiable until then.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
LIB = ROOT / "artifact" / "lib"
SOURCE = ROOT / "artifact" / "source"
SCRIPTS = SOURCE / "scripts"
FIGURES = SOURCE / "docs" / "figures"
INPUTS = ROOT / "ae" / "inputs" / "small-campaign"
OUTPUT = ROOT / "ae-output" / "small-campaign"

# The prebuilt capopt library resolves first, exactly as in ae/runner.py, so
# this script also works when launched directly with a bare interpreter.
_IMPORT_PATHS = [LIB, SOURCE, SOURCE / "superoptimization"]
for _candidate in reversed(_IMPORT_PATHS):
    if str(_candidate) not in sys.path:
        sys.path.insert(0, str(_candidate))

BASELINE = "baseline_o3"
OPTIMIZED = ["two_level", "ir_only", "asm_only"]
HD_ARCH = "riscv_cheri"
REALWORLD_ARCH = "arm_morello"
SPEC_BENCH = "531.deepsjeng_r"

CLAIMS = {
    "C1": "C1-two-level-ablation",
    "C2": "C2-hd-speedup",
    "C3": "C3-spec-llama-speedup",
    "C8": "C8-optimization-time",
    "C9": "C9-no-regression",
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
    cwd: Path = SOURCE,
    display: str | None = None,
    quiet: bool = False,
) -> list[str]:
    """Run one pipeline stage.

    ``display`` replaces the echoed command line (used to keep the notebook
    output focused on results rather than on internal artifact paths), and
    ``quiet`` captures the stage's own output, printing it only on failure.
    The full command is always recorded in report.json.
    """
    printable = _printable(command)
    print("$", display if display else " ".join(printable), flush=True)
    env = dict(os.environ)
    env["PYTHONPATH"] = os.pathsep.join(str(path) for path in _IMPORT_PATHS)
    result = subprocess.run(
        command, cwd=cwd, env=env, check=False,
        capture_output=quiet, text=quiet,
    )
    if result.returncode:
        if quiet:
            sys.stdout.write(result.stdout or "")
            sys.stderr.write(result.stderr or "")
        raise RuntimeError(f"{printable[1]} exited with {result.returncode}")
    return printable


def _load_script(name: str, path: Path) -> Any:
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _observe(
    observations: list[dict[str, Any]], check: str, passed: bool, detail: str
) -> bool:
    observations.append({"check": check, "passed": passed, "detail": detail})
    return passed


def _pct(value: Any) -> str:
    """Readable improvement value for observation details."""
    return "n/a" if value is None else f"{value:+.2f}%"


def run_pipeline() -> dict[str, Any]:
    """Execute every stage once; claim evaluators read the artifacts."""
    from capopt.reporting import aggregate_summary

    if OUTPUT.exists():
        shutil.rmtree(OUTPUT)
    OUTPUT.mkdir(parents=True)
    commands: list[list[str]] = []

    # Stage 1: aggregate the pristine mini tree (read-only) into ae-output.
    summary_path = OUTPUT / "summary.json"
    summary = aggregate_summary(INPUTS, summary_path)
    print(
        f"aggregate_summary: {summary['n_runs']} recorded runs aggregated "
        f"from the bundled small campaign"
    )

    # Stage 2: the per-benchmark improvement / geomean machinery (C1/C2/C3).
    # The generated table file stays in ae-output as a silent artifact; the
    # measured improvements themselves are printed by the claim checks below.
    table_path = OUTPUT / "tab_two_level.tex"
    commands.append(
        _launch(
            [
                sys.executable, str(SCRIPTS / "gen_table.py"),
                "--results", str(summary_path),
                "--out", str(table_path),
            ],
            display=(
                "scripts/gen_table.py  "
                "(recomputes per-benchmark improvements and geomeans)"
            ),
            quiet=True,
        )
    )

    # Stage 3: the optimization-time distribution (C8 machinery).
    figure_path = OUTPUT / "fig_opt_time.pdf"
    commands.append(
        _launch(
            [
                sys.executable, str(FIGURES / "optimization_time.py"),
                "--results", str(summary_path),
                "--out", str(figure_path),
                "--arch", HD_ARCH,
            ],
            display=(
                "docs/figures/optimization_time.py  "
                "(recomputes the optimization-time distribution)"
            ),
            quiet=True,
        )
    )

    # Stage 4: the validation gate (C9) on a copy; the gate annotates and,
    # for retained_original decisions, clamps result.json files in place.
    tree = OUTPUT / "tree"
    shutil.copytree(INPUTS, tree)
    gate_paths: dict[str, Path] = {}
    for arch_dir in sorted(p for p in tree.iterdir() if p.is_dir()):
        gate_path = OUTPUT / f"gate_{arch_dir.name}.json"
        gate_paths[arch_dir.name] = gate_path
        commands.append(
            _launch(
                [
                    sys.executable, str(SCRIPTS / "apply_validation_gate.py"),
                    "--root", str(arch_dir),
                    "--json-out", str(gate_path),
                ],
                display=(
                    f"scripts/apply_validation_gate.py  "
                    f"(re-runs the empirical no-regression gate, "
                    f"{arch_dir.name})"
                ),
                quiet=True,
            )
        )
        gate = json.loads(gate_path.read_text())
        print(
            f"  {arch_dir.name}: {gate['gated']} gated -> "
            f"{gate['kept_optimized']} kept_optimized, "
            f"{gate['retained_original']} retained_original, "
            f"{gate['not_comparable']} not_comparable"
        )

    # Stage 5: re-aggregate the gated copy for the shipped-artefact check.
    post_gate_path = OUTPUT / "summary_post_gate.json"
    aggregate_summary(tree, post_gate_path)

    return {
        "commands": commands,
        "summary": summary_path,
        "table": table_path,
        "figure": figure_path,
        "tree": tree,
        "gates": gate_paths,
        "post_gate_summary": post_gate_path,
    }


def _table_rows(gen_table: Any, summary_path: Path) -> dict[str, Any]:
    runs = gen_table.load_runs(summary_path)
    idx = gen_table.index(runs)
    return {
        "idx": idx,
        "hd": gen_table.hackers_delight_row(idx),
        "llama": gen_table.llama_row(idx),
        "spec": gen_table.spec_rows(idx)[0],
    }


def check_c1(pipeline: dict[str, Any], gen_table: Any) -> dict[str, Any]:
    """Two-level beats each single level on the bundled small HD suite."""
    observations: list[dict[str, Any]] = []
    hd = _table_rows(gen_table, pipeline["summary"])["hd"]
    per_pipeline = {
        name: hd[(HD_ARCH, name)]
        for name in ("two_level", "ir_only", "asm_only")
    }
    passed = _observe(
        observations,
        f"per-pipeline HD geomean improvements computed ({HD_ARCH})",
        all(value is not None for value in per_pipeline.values()),
        ", ".join(f"{k}={_pct(v)}" for k, v in per_pipeline.items()),
    )
    two_level = hd[(HD_ARCH, "two_level")]
    for single in ("ir_only", "asm_only"):
        value = hd[(HD_ARCH, single)]
        ok = (
            two_level is not None
            and value is not None
            and two_level >= value
        )
        passed &= _observe(
            observations,
            f"HD geomean improvement: two_level >= {single} ({HD_ARCH})",
            ok,
            f"two_level={_pct(two_level)}, {single}={_pct(value)}",
        )
    return {
        "claim_id": CLAIMS["C1"],
        "checked": (
            "Table 2 generation (gen_table.py geomean machinery) on the "
            "bundled small suite; two-level >= each single level there"
        ),
        "observations": observations,
        "passed": bool(passed),
    }


def check_c2(pipeline: dict[str, Any], gen_table: Any) -> dict[str, Any]:
    """The bundled HD geomean improvement is positive."""
    observations: list[dict[str, Any]] = []
    hd = _table_rows(gen_table, pipeline["summary"])["hd"]
    two_level = hd[(HD_ARCH, "two_level")]
    passed = _observe(
        observations,
        f"HD geomean improvement of two_level > 0 ({HD_ARCH})",
        two_level is not None and two_level > 0,
        f"two_level={_pct(two_level)}",
    )
    return {
        "claim_id": CLAIMS["C2"],
        "checked": (
            "The Hacker's Delight geomean pipeline on the bundled small "
            "suite reports a positive two-level improvement"
        ),
        "observations": observations,
        "passed": bool(passed),
    }


def check_c3(pipeline: dict[str, Any], gen_table: Any) -> dict[str, Any]:
    """SPEC and LLaMA.cpp rows regenerate from recorded measurements."""
    observations: list[dict[str, Any]] = []
    rows = _table_rows(gen_table, pipeline["summary"])
    spec = dict(rows["spec"])
    spec_cell = spec.get(SPEC_BENCH, {}).get((REALWORLD_ARCH, "two_level"))
    passed = _observe(
        observations,
        f"SPEC row {SPEC_BENCH} ({REALWORLD_ARCH}): two_level improvement > 0",
        spec_cell is not None and spec_cell > 0,
        f"two_level={_pct(spec_cell)}",
    )
    llama_cell = rows["llama"][(REALWORLD_ARCH, "two_level")]
    passed &= _observe(
        observations,
        f"LLaMA.cpp row ({REALWORLD_ARCH}) computed from recorded cycles",
        llama_cell is not None,
        f"two_level={_pct(llama_cell)}",
    )
    hd = rows["hd"]
    two_level = hd[(HD_ARCH, "two_level")]
    passed &= _observe(
        observations,
        "functional stand-in: bundled HD geomean improvement > 0",
        two_level is not None and two_level > 0,
        f"two_level={_pct(two_level)}",
    )
    return {
        "claim_id": CLAIMS["C3"],
        "checked": (
            "The SPEC/LLaMA table rows regenerate through the same pipeline "
            "from bundled recorded real-workload measurements"
        ),
        "observations": observations,
        "passed": bool(passed),
    }


def check_c8(pipeline: dict[str, Any]) -> dict[str, Any]:
    """The optimization-time figure regenerates from compile_time_s."""
    observations: list[dict[str, Any]] = []
    figure: Path = pipeline["figure"]
    header = figure.read_bytes()[:5] if figure.is_file() else b""
    passed = _observe(
        observations,
        "the optimization-time distribution regenerated as a non-empty PDF",
        figure.is_file() and figure.stat().st_size > 0 and header == b"%PDF-",
        f"{figure.stat().st_size if figure.is_file() else 0} bytes",
    )
    summary = json.loads(pipeline["summary"].read_text())
    records = [
        run for run in summary["runs"]
        if run["arch"] == HD_ARCH
        and run["pipeline"] == "two_level"
        and run.get("compile_time_s") is not None
    ]
    passed &= _observe(
        observations,
        f"every bundled {HD_ARCH} two_level run carries compile_time_s",
        len(records) == sum(
            1 for run in summary["runs"]
            if run["arch"] == HD_ARCH and run["pipeline"] == "two_level"
        )
        and len(records) > 0,
        f"{len(records)} compile-time records plotted",
    )
    return {
        "claim_id": CLAIMS["C8"],
        "checked": (
            "The Section 6.5 figure script regenerates the optimization-"
            "time distribution from the bundled compile_time_s fields"
        ),
        "observations": observations,
        "passed": bool(passed),
    }


def check_c9(pipeline: dict[str, Any], gen_table: Any) -> dict[str, Any]:
    """Every bench gets a gate decision; nothing ships slower than baseline."""
    observations: list[dict[str, Any]] = []
    tree: Path = pipeline["tree"]

    expected: set[tuple[str, str, str]] = set()
    for arch_dir in sorted(p for p in tree.iterdir() if p.is_dir()):
        for bench_dir in sorted(p for p in arch_dir.iterdir() if p.is_dir()):
            if not (bench_dir / BASELINE / "result.json").is_file():
                continue
            for pipeline_name in OPTIMIZED:
                if (bench_dir / pipeline_name / "result.json").is_file():
                    expected.add((arch_dir.name, bench_dir.name, pipeline_name))

    decisions: dict[tuple[str, str, str], str] = {}
    for arch, gate_path in pipeline["gates"].items():
        gate = json.loads(gate_path.read_text())
        for record in gate["decisions"]:
            decisions[(arch, record["bench"], record["pipeline"])] = (
                record["decision"]
            )
    passed = _observe(
        observations,
        "the gate reports one decision per measured (bench, pipeline)",
        set(decisions) == expected and len(expected) > 0,
        f"{len(decisions)} decisions for {len(expected)} expected pairs",
    )
    kinds = set(decisions.values())
    passed &= _observe(
        observations,
        "every decision is kept_optimized or retained_original, and both "
        "branches of the gate are exercised",
        kinds == {"kept_optimized", "retained_original"},
        f"decision kinds: {sorted(kinds)}",
    )

    post = json.loads(pipeline["post_gate_summary"].read_text())
    index = {
        (run["arch"], run["bench"], run["pipeline"]): run
        for run in post["runs"]
    }
    slower: list[str] = []
    for arch, bench, pipeline_name in sorted(expected):
        base = gen_table._metric_value(index[(arch, bench, BASELINE)])
        opt = gen_table._metric_value(index[(arch, bench, pipeline_name)])
        if base is None or opt is None or opt > base:
            slower.append(f"{arch}/{bench}/{pipeline_name} ({opt} vs {base})")
    passed &= _observe(
        observations,
        "after gating, no shipped candidate is slower than its baseline",
        not slower,
        "no regressions" if not slower else "; ".join(slower),
    )
    return {
        "claim_id": CLAIMS["C9"],
        "checked": (
            "apply_validation_gate.py re-runs on a copy of the bundled "
            "tree; each bench receives a decision and retained_original "
            "candidates are clamped to their baseline"
        ),
        "observations": observations,
        "passed": bool(passed),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--claim",
        choices=[*CLAIMS, "all"],
        default="all",
        help="exit nonzero only if this claim's checks fail (default: all)",
    )
    args = parser.parse_args(argv)

    pipeline = run_pipeline()
    gen_table = _load_script("ae_gen_table", SCRIPTS / "gen_table.py")
    reports = {
        "C1": check_c1(pipeline, gen_table),
        "C2": check_c2(pipeline, gen_table),
        "C3": check_c3(pipeline, gen_table),
        "C8": check_c8(pipeline),
        "C9": check_c9(pipeline, gen_table),
    }

    report = {
        "schema_version": 1,
        "inputs": str(INPUTS.relative_to(ROOT)),
        "scope": (
            "pipeline verification on the bundled small recorded dataset; "
            "full-campaign snapshots refresh this evidence at freeze"
        ),
        "commands": pipeline["commands"],
        "artifacts": {
            name: str(pipeline[name].relative_to(ROOT))
            for name in ("summary", "table", "figure", "post_gate_summary")
        },
        "claims": [reports[name] for name in CLAIMS],
        "passed": all(entry["passed"] for entry in reports.values()),
    }
    (OUTPUT / "report.json").write_text(json.dumps(report, indent=2) + "\n")

    for name, entry in reports.items():
        print(f"{'PASS' if entry['passed'] else 'FAIL':4}  {name}: {entry['checked']}")
        for observation in entry["observations"]:
            print(f"        {observation['check']}: {observation['detail']}")

    selected = list(CLAIMS) if args.claim == "all" else [args.claim]
    failed = [name for name in selected if not reports[name]["passed"]]
    print(
        f"REPRODUCE-SMALL({args.claim}): {'FAIL' if failed else 'PASS'}"
    )
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
