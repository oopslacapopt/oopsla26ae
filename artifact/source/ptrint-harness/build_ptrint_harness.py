#!/usr/bin/env python3
"""
Build the ptrint-harness motivation cases for CHERI and non-CHERI targets
and show the differences between their assembly outputs.
"""

from __future__ import annotations

import argparse
import difflib
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple
from subprocess import CalledProcessError

REPO_ROOT = Path(__file__).resolve().parents[1]
HARNESS_ROOT = REPO_ROOT / "ptrint-harness"
SRC_ROOT = HARNESS_ROOT / "src"
BUILD_ROOT = HARNESS_ROOT / "build"
DIFF_ROOT = HARNESS_ROOT / "diffs"
CFI_IGNORELIST = HARNESS_ROOT / "cfi_ignorelist.txt"

C_EXTS = {".c"}
CXX_EXTS = {".cc", ".cxx", ".cpp", ".c++", ".C"}


def log(msg: str) -> None:
    print(msg, flush=True)


def run(cmd: List[str]) -> None:
    log("+ " + " ".join(cmd))
    subprocess.run(cmd, check=True)


@dataclass(frozen=True)
class Toolchain:
    name: str
    clang: Path
    clangxx: Path
    opt: Path
    common_flags: List[str]
    cheri_flags: List[str]
    baseline_flags: List[str]


def build_toolchain(isa: str) -> Toolchain:
    if isa == "morello":
        root = Path("/home/scxs/cheri/build/morello-llvm-project-build/bin")
        common = [
            "-target",
            "aarch64-unknown-freebsd13",
            "-mcpu=rainier",
            "-fuse-ld=lld",
            "-w",
            "--sysroot=/home/scxs/cheri/output/rootfs-morello-purecap",
        ]
        cheri = [
            "-march=morello",
            "-mabi=purecap",
            "-Xclang",
            "-morello-vararg=new",
            "-Xclang",
            "-morello-bounded-memargs=caller-only",
        ]
        baseline = [
            "-march=morello",
            "-mabi=aapcs",
        ]
    elif isa == "riscv":
        root = Path("/home/scxs/cheri/build/llvm-project-build/bin")
        common = [
            "-target",
            "riscv64-unknown-freebsd",
            "-mcmodel=medium",
            "-mno-relax",
            "-fuse-ld=lld",
            "-w",
            "--sysroot=/home/scxs/cheri/output/rootfs-riscv64-purecap",
        ]
        cheri = [
            "-march=rv64gcxcheri",
            "-mabi=l64pc128d",
        ]
        baseline = [
            "-march=rv64gc",
            "-mabi=lp64d",
        ]
    else:
        raise ValueError(f"Unsupported ISA '{isa}' (expected 'morello' or 'riscv').")

    return Toolchain(
        name=isa,
        clang=root / "clang",
        clangxx=root / "clang++",
        opt=root / "opt",
        common_flags=common,
        cheri_flags=cheri,
        baseline_flags=baseline,
    )


@dataclass(frozen=True)
class CaseSpec:
    name: str
    source: Path
    compile_flags: List[str]
    description: str
    mode_compile_flags: Dict[str, List[str]] = field(default_factory=dict)
    opt_pipelines: Dict[str, str] = field(default_factory=dict)
    skip: Dict[str, Dict[str, str]] = field(default_factory=dict)


def default_cases() -> Dict[str, CaseSpec]:
    cases: List[CaseSpec] = [
        CaseSpec(
            name="combined_opts",
            source=SRC_ROOT / "combined_opts.cpp",
            compile_flags=[
                "-std=c++17",
                "-O3",
                "-fvisibility=hidden",
                "-fPIC",
            ],
            description="Combined devirtualization, lookup tables, and switch optimizations.",
            mode_compile_flags={
                "cheri": [
                    "-fno-lto",
                ],
                "baseline": [
                    "-flto=full",
                    "-fwhole-program-vtables",
                    "-fvirtual-function-elimination",
                    "-fvisibility=hidden",
                ],
            },
            opt_pipelines={
                "baseline": "wholeprogramdevirt,lowertypetests,rel-lookup-table-converter,simplifycfg",
            },
        ),
        CaseSpec(
            name="virtual_calls",
            source=SRC_ROOT / "virtual_calls.cpp",
            compile_flags=[
                "-std=c++17",
                "-O3",
                "-fvisibility=hidden",
            ],
            description="WholeProgramDevirt-style virtual dispatch optimisations.",
            mode_compile_flags={
                "cheri": [
                    "-fno-lto",
                ],
                "baseline": [
                    "-flto=full",
                    "-fwhole-program-vtables",
                    "-fvirtual-function-elimination",
                    "-fvisibility=hidden",
                ],
            },
            opt_pipelines={
                "baseline": "wholeprogramdevirt,lowertypetests",
            },
        ),
        CaseSpec(
            name="cfi_checks",
            source=SRC_ROOT / "cfi_checks.cpp",
            compile_flags=[
                "-std=c++17",
                "-O1",
                "-fvisibility=hidden",
            ],
            description="LowerTypeTests / type metadata lowering scenario.",
            mode_compile_flags={
                "baseline": [
                    "-flto=full",
                    "-fsanitize=cfi-vcall",
                    f"-fsanitize-ignorelist={CFI_IGNORELIST}",
                    f"-fsanitize-system-ignorelist={CFI_IGNORELIST}",
                    "-fvisibility=hidden",
                ],
            },
            opt_pipelines={
                "baseline": "lowertypetests",
            },
        ),
        CaseSpec(
            name="profiled_hotpath",
            source=SRC_ROOT / "profiled_hotpath.cpp",
            compile_flags=[
                "-std=c++17",
                "-O2",
            ],
            description="InstrProfiling counter updates.",
            mode_compile_flags={
                "baseline": [
                    "-fprofile-generate",
                ]
            },
        ),
        CaseSpec(
            name="asan_shadow",
            source=SRC_ROOT / "asan_shadow.c",
            compile_flags=[
                "-std=c17",
                "-O1",
            ],
            description="AddressSanitizer shadow instrumentation (baseline only).",
            mode_compile_flags={
                "baseline": [
                    "-fsanitize=address",
                ]
            },
        ),
        CaseSpec(
            name="lookup_table",
            source=SRC_ROOT / "lookup_table.cpp",
            compile_flags=[
                "-std=c++17",
                "-O2",
                "-fPIC",
            ],
            description="RelLookupTableConverter pointer table rewriting.",
            opt_pipelines={
                "baseline": "rel-lookup-table-converter",
            },
        ),
        CaseSpec(
            name="loop_iv",
            source=SRC_ROOT / "loop_iv.c",
            compile_flags=[
                "-std=c17",
                "-O1",
            ],
            description="ScalarEvolution / loop strength reduction case.",
            opt_pipelines={
                "baseline": "loop-reduce",
            },
        ),
        CaseSpec(
            name="ptr_roundtrip",
            source=SRC_ROOT / "ptr_roundtrip.c",
            compile_flags=[
                "-std=c17",
                "-O2",
            ],
            description="InstCombine pointer round-trip canonicalisation.",
            opt_pipelines={
                "baseline": "instcombine",
            },
        ),
        CaseSpec(
            name="instcombine_gep",
            source=SRC_ROOT / "instcombine_gep.c",
            compile_flags=[
                "-std=c17",
                "-O1",
            ],
            description="InstCombine folding of ptrtoint/inttoptr-derived GEPs.",
            opt_pipelines={
                "baseline": "instcombine",
            },
        ),
    ]
    return {case.name: case for case in cases}


def get_skip_reason(case: CaseSpec, isa: str, mode: str) -> Optional[str]:
    def lookup(key: str) -> Optional[str]:
        if key not in case.skip:
            return None
        per_mode = case.skip[key]
        return per_mode.get(mode) or per_mode.get("all")

    return lookup(isa) or lookup("all")


def compiler_for_source(toolchain: Toolchain, src: Path) -> Path:
    ext = src.suffix
    if ext in C_EXTS:
        return toolchain.clang
    if ext in CXX_EXTS:
        return toolchain.clangxx
    raise ValueError(f"Unsupported source extension '{ext}' for {src}")


def build_single_variant(
    case: CaseSpec,
    toolchain: Toolchain,
    mode: str,
    extra_flags: Iterable[str],
    build_dir: Path,
    keep_ir: bool,
) -> Path:
    compiler = compiler_for_source(toolchain, case.source)
    ir_path = build_dir / f"{case.name}.{mode}.bc"
    asm_path = build_dir / f"{case.name}.{mode}.s"
    intermediates = [ir_path]

    compile_cmd = [
        str(compiler),
        "-emit-llvm",
        "-c",
        "-o",
        str(ir_path),
        str(case.source),
    ]
    compile_cmd.extend(toolchain.common_flags)
    compile_cmd.extend(extra_flags)
    flags = list(case.compile_flags)
    flags.extend(case.mode_compile_flags.get(mode, []))
    compile_cmd.extend(flags)
    run(compile_cmd)

    codegen_input = ir_path
    pipeline = case.opt_pipelines.get(mode) or case.opt_pipelines.get("all")
    if pipeline:
        opt_out = build_dir / f"{case.name}.{mode}.opt.bc"
        opt_cmd = [
            str(toolchain.opt),
            f"-passes={pipeline}",
            str(codegen_input),
            "-o",
            str(opt_out),
        ]
        run(opt_cmd)
        codegen_input = opt_out
        intermediates.append(opt_out)

    # Codegen step: reuse clang to lower the bitcode to assembly for the target.
    codegen_cmd = [
        str(toolchain.clang),
        "-S",
        "-x",
        "ir",
        "-o",
        str(asm_path),
        str(codegen_input),
    ]
    codegen_cmd.extend(toolchain.common_flags)
    codegen_cmd.extend(extra_flags)
    run(codegen_cmd)

    if not keep_ir:
        for artifact in intermediates:
            try:
                artifact.unlink()
            except FileNotFoundError:
                pass
    return asm_path


def ensure_dirs(*paths: Path) -> None:
    for path in paths:
        path.mkdir(parents=True, exist_ok=True)


def ensure_system_ignorelist(toolchain: Toolchain) -> None:
    if not CFI_IGNORELIST.exists():
        CFI_IGNORELIST.write_text("# ptrint harness ignorelist\n", encoding="utf-8")
    try:
        resource_dir = subprocess.check_output(
            [str(toolchain.clang), "-print-resource-dir"],
            text=True,
        ).strip()
    except subprocess.CalledProcessError as exc:
        raise SystemExit(f"Failed to query resource dir from {toolchain.clang}: {exc}") from exc
    target = Path(resource_dir) / "share" / "cfi_ignorelist.txt"
    if target.exists():
        return
    target.parent.mkdir(parents=True, exist_ok=True)
    try:
        target.symlink_to(CFI_IGNORELIST)
    except FileExistsError:
        pass


def verify_toolchain(toolchain: Toolchain) -> None:
    missing = [binary for binary in (toolchain.clang, toolchain.clangxx, toolchain.opt) if not binary.exists()]
    if missing:
        formatted = ", ".join(str(p) for p in missing)
        raise SystemExit(f"Toolchain binaries not found: {formatted}")


def write_diff(case: CaseSpec, cheri_path: Path, baseline_path: Path) -> Path:
    cheri_text = cheri_path.read_text(encoding="utf-8", errors="ignore").splitlines()
    base_text = baseline_path.read_text(encoding="utf-8", errors="ignore").splitlines()
    diff = difflib.unified_diff(
        base_text,
        cheri_text,
        fromfile=f"{case.name}-baseline",
        tofile=f"{case.name}-cheri",
        lineterm="",
    )
    diff_lines = list(diff)
    diff_path = DIFF_ROOT / f"{case.name}.diff"
    DIFF_ROOT.mkdir(parents=True, exist_ok=True)
    diff_path.write_text("\n".join(diff_lines) + ("\n" if diff_lines else ""), encoding="utf-8")
    return diff_path


def parse_args() -> argparse.Namespace:
    cases = default_cases()
    parser = argparse.ArgumentParser(
        description="Build ptrint-harness cases for CHERI vs non-CHERI and diff their assembly output.",
    )
    parser.add_argument(
        "--isa",
        choices=["morello", "riscv"],
        default="morello",
        help="Instruction set to target (default: morello).",
    )
    parser.add_argument(
        "--cases",
        nargs="+",
        choices=sorted(cases.keys()),
        help="Restrict to a subset of cases.",
    )
    parser.add_argument(
        "--keep-intermediates",
        action="store_true",
        help="Do not delete intermediate bitcode files (useful for debugging).",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    cases = default_cases()
    selected = args.cases or sorted(cases.keys())

    missing_sources = [name for name in selected if not cases[name].source.exists()]
    if missing_sources:
        raise SystemExit(f"Missing source files: {', '.join(missing_sources)}. Did you create ptrint-harness/src?")

    toolchain = build_toolchain(args.isa)
    verify_toolchain(toolchain)
    ensure_system_ignorelist(toolchain)
    ensure_dirs(BUILD_ROOT, DIFF_ROOT)

    report = []
    for case_name in selected:
        case = cases[case_name]
        log(f"==> Building case '{case.name}': {case.description}")
        case_build_dir = BUILD_ROOT / toolchain.name / case.name
        ensure_dirs(case_build_dir)
        results: Dict[str, Tuple[str, Optional[Path], Optional[str]]] = {}

        for mode, flags in (("cheri", toolchain.cheri_flags), ("baseline", toolchain.baseline_flags)):
            skip = get_skip_reason(case, toolchain.name, mode)
            if skip:
                log(f"    - skipping {mode}: {skip}")
                results[mode] = ("skipped", None, skip)
                continue
            try:
                path = build_single_variant(
                    case,
                    toolchain,
                    mode=mode,
                    extra_flags=flags,
                    build_dir=case_build_dir,
                    keep_ir=args.keep_intermediates,
                )
                results[mode] = ("ok", path, None)
            except CalledProcessError as exc:
                log(f"    - {mode} build failed (exit {exc.returncode})")
                results[mode] = ("failed", None, str(exc))

        cheri_result = results.get("cheri")
        base_result = results.get("baseline")
        if cheri_result and base_result and cheri_result[0] == base_result[0] == "ok":
            diff_path = write_diff(case, cheri_result[1], base_result[1])
            status = "differs" if diff_path.stat().st_size > 0 else "identical"
            report.append((case.name, status, diff_path))
        else:
            report.append((case.name, "skipped/failed", None))

    log("\nSummary:")
    for name, status, path in report:
        if path:
            log(f"  - {name}: {status} (see {path})")
        else:
            log(f"  - {name}: {status}")


if __name__ == "__main__":
    main()
