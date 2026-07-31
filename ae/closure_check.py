#!/usr/bin/env python3
"""Check that the default AE path is contained, complete, and unmodified."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path

REQUIRED = [
    "README.md",
    "LICENSE",
    "Dockerfile",
    "requirements.lock",
    "bin/capopt",
    "bin/start-notebook.sh",
    "bin/stop-notebook.sh",
    "ae/short_reproduction.py",
    "ae/recompute_claims.py",
    "ae/reproduce_small.py",
    "ae/tests/test_recompute_claims.py",
    "ae/tests/test_reproduce_small.py",
    "ae/inputs/small-campaign/README.md",
    "ae/inputs/small-campaign/riscv_cheri/p01/two_level/result.json",
    "ae/inputs/small-campaign/riscv_cheri/p11/baseline_o3/result.json",
    "ae/inputs/small-campaign/arm_morello/531.deepsjeng_r/two_level/result.json",
    "ae/inputs/small-campaign/arm_morello/llama.cpp/baseline_o3/result.json",
    "ae/inputs/pruning-p01/fxn.s",
    "ae/inputs/pruning-p01/main.s",
    "ae/inputs/pruning-p01/README.md",
    "ae/inputs/morello-p01/baseline_o3-p01",
    "ae/inputs/morello-p01/o3_asm-p01",
    "ae/inputs/morello-p01/manifest.json",
    "ae/inputs/morello-p01/README.md",
    "ae/morello/collect.py",
    "ae/morello/controller.py",
    "ae/morello/request.py",
    "ae/morello/report.py",
    "ae/morello/run.sh",
    "ae/morello/known_hosts",
    "artifact/SOURCE.json",
    "artifact/lib/README.md",
    "artifact/lib/capopt/__init__.pyc",
    "artifact/lib/capopt/core.pyc",
    "artifact/lib/capopt/cli.pyc",
    "artifact/lib/capopt/_native/__init__.pyc",
    "artifact/lib/capopt/_native/_fallback.pyc",
    "artifact/lib/superoptimization/__init__.pyc",
    "artifact/source/LICENSE",
    "artifact/source/superoptimization/pyproject.toml",
    "artifact/source/tests/test_soundness_regressions.py",
    "artifact/source/tests/test_capopt_smt_semantics.py",
    "artifact/source/results/optmix/a4_dev_host_harvest.json",
    "artifact/source/results/ablation_v3/summary.json",
    "artifact/source/results/souper_comparison/summary.json",
    "claims/manifest.json",
    "notebook/oopsla26-ae.ipynb",
    "SHA256SUMS",
    "VALIDATION.md",
]

FORBIDDEN_PARTS = {
    ".git",
    ".venv",
    "__pycache__",
    ".pytest_cache",
    "spec-cpu2017-1.1.0",
    # The optimizer's variant-store bundles default to a relative
    # "artifacts" directory; every scripted lane redirects them into
    # ae-output, so any packaged occurrence is accidental pollution.
    "artifacts",
}

LFS_PREFIX = b"version https://git-lfs.github.com/spec/v1"


def _under(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
        return True
    except ValueError:
        return False


def _read_sums(path: Path) -> list[tuple[str, str]]:
    entries: list[tuple[str, str]] = []
    pattern = re.compile(r"^([0-9a-f]{64})  (.+)$")
    for lineno, line in enumerate(path.read_text().splitlines(), 1):
        match = pattern.match(line)
        if not match:
            raise ValueError(f"{path.name}:{lineno}: malformed checksum line")
        entries.append((match.group(1), match.group(2)))
    return entries


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    args = parser.parse_args()
    root = args.root.resolve()
    failures: list[str] = []
    notes: list[str] = []

    for relative in REQUIRED:
        if not (root / relative).is_file():
            failures.append(f"missing required file: {relative}")

    source_metadata = root / "artifact/SOURCE.json"
    if source_metadata.is_file():
        try:
            source = json.loads(source_metadata.read_text())
            commit = source["git_commit"]
            if not re.fullmatch(r"[0-9a-f]{40}", commit):
                failures.append("artifact/SOURCE.json: git_commit is not a full SHA")
            if source.get("dirty"):
                # A dirty export is acceptable while the paper is under
                # revision, but it is a declared release blocker: the DOI
                # deposit must come from a clean, frozen commit.
                notes.append(
                    "WARNING: snapshot exported from a dirty working tree "
                    f"({len(source.get('dirty_tracked_paths', []))} modified "
                    "tracked paths; release blocker, dirty paths recorded "
                    "in artifact/SOURCE.json)"
                )
        except (OSError, json.JSONDecodeError, KeyError) as exc:
            failures.append(f"artifact/SOURCE.json: {exc}")

    # Layout invariant: artifact/lib is the prebuilt library (bytecode plus
    # the native extension, no Python or C++ source), and the open snapshot
    # must not carry a second copy of the core package.
    lib_root = root / "artifact/lib"
    if lib_root.is_dir():
        for leaked in sorted(lib_root.rglob("*")):
            if leaked.suffix in {".py", ".cpp", ".cc", ".h", ".hpp"}:
                failures.append(
                    f"source file inside the prebuilt library: "
                    f"{leaked.relative_to(root)}"
                )
    if (root / "artifact/source/superoptimization/capopt").exists():
        failures.append(
            "core capopt package present under artifact/source "
            "(it ships as the prebuilt library in artifact/lib)"
        )

    files = []
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        relative = path.relative_to(root)
        # Repository metadata and local generated state are not copied into
        # the image or release archive. Nested .git directories in the
        # vendored payload remain forbidden and are not skipped here.
        if relative.parts[0] == ".git":
            continue
        if any(part in {"ae-output", "__pycache__", ".pytest_cache"} for part in relative.parts):
            continue
        files.append(path)
    for path in files:
        relative = path.relative_to(root)
        if any(part in FORBIDDEN_PARTS for part in relative.parts):
            failures.append(f"forbidden packaged path: {relative}")
        if path.is_symlink() and not _under(path, root):
            failures.append(f"symlink escapes artifact: {relative} -> {path.resolve()}")
        try:
            if path.stat().st_size <= 1024 and path.read_bytes().startswith(LFS_PREFIX):
                failures.append(f"unresolved Git LFS pointer: {relative}")
        except OSError as exc:
            failures.append(f"cannot inspect {relative}: {exc}")

    sums_path = root / "SHA256SUMS"
    if sums_path.is_file():
        try:
            sums = _read_sums(sums_path)
            listed = set()
            for expected, relative_text in sums:
                relative = Path(relative_text)
                target = root / relative
                listed.add(relative_text)
                if relative.is_absolute() or ".." in relative.parts or not _under(target, root):
                    failures.append(f"unsafe checksum path: {relative_text}")
                    continue
                if not target.is_file():
                    failures.append(f"checksummed file missing: {relative_text}")
                    continue
                actual = hashlib.sha256(target.read_bytes()).hexdigest()
                if actual != expected:
                    failures.append(f"checksum mismatch: {relative_text}")
            notes.append(f"verified {len(sums)} SHA-256 entries")
        except (OSError, ValueError) as exc:
            failures.append(f"SHA256SUMS: {exc}")

    # The licensed benchmark must never enter the vendored source snapshot.
    if (root / "artifact/source/benchmarks/spec-cpu2017-1.1.0").exists():
        failures.append("licensed SPEC CPU2017 tree is present")

    for note in notes:
        label = "WARN" if note.startswith("WARNING") else "PASS"
        print(f"  {label:4}  {note}")
    for failure in failures:
        print(f"  FAIL  {failure}")
    print(f"CLOSURE: {'FAIL' if failures else 'PASS'}")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
