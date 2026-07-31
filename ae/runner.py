#!/usr/bin/env python3
"""Single command surface for the CapOpt OOPSLA 2026 artifact."""

from __future__ import annotations

import argparse
import json
import math
import os
import platform
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
LIB = ROOT / "artifact" / "lib"
SOURCE = ROOT / "artifact" / "source"
TESTS = SOURCE / "tests"
OUTPUT = ROOT / "ae-output"

# The vendored optimizer and parts of its test suite persist variant-store
# bundles under a relative "artifacts" directory by default. Point every
# scripted lane (and its subprocesses) at the excluded output tree so no
# reviewer command mutates the checksummed source snapshot; tests that pass
# their own artifact root are unaffected.
os.environ.setdefault("CAPOPT_ARTIFACT_ROOT", str(OUTPUT / "capopt-artifacts"))

# The core `capopt` package ships as the prebuilt library under artifact/lib
# (CPython 3.12 bytecode + optional native extension). Prefer it, then fall
# back to a source drop should a future release place the package under
# artifact/source/superoptimization. Export the same order through PYTHONPATH
# so every subprocess (pytest, claim commands, shipped scripts) resolves the
# identical package, whether run from this checkout or from the image.
_IMPORT_PATHS = [LIB, SOURCE, SOURCE / "superoptimization"]
for candidate in reversed(_IMPORT_PATHS):
    if str(candidate) not in sys.path:
        sys.path.insert(0, str(candidate))
os.environ["PYTHONPATH"] = os.pathsep.join(
    [str(path) for path in _IMPORT_PATHS]
    + ([os.environ["PYTHONPATH"]] if os.environ.get("PYTHONPATH") else [])
)


def _under_path(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root.resolve())
        return True
    except ValueError:
        return False


def _write_json(name: str, value: Any) -> None:
    try:
        OUTPUT.mkdir(parents=True, exist_ok=True)
        (OUTPUT / name).write_text(json.dumps(value, indent=2) + "\n")
    except OSError as exc:
        print(f"NOTE: could not write ae-output/{name}: {exc}", file=sys.stderr)


def _run(command: list[str], *, cwd: Path = ROOT) -> int:
    printable = " ".join(command)
    print(f"$ {printable}", flush=True)
    return subprocess.run(command, cwd=cwd, check=False).returncode


def check_environment() -> int:
    checks: list[tuple[str, bool, str]] = []
    checks.append(
        (
            "Python >= 3.11",
            sys.version_info >= (3, 11),
            platform.python_version(),
        )
    )
    virtual_env = os.environ.get("VIRTUAL_ENV")
    expected_prefix = Path(virtual_env).resolve() if virtual_env else None
    actual_prefix = Path(sys.prefix).resolve()
    checks.append(
        (
            "dedicated virtual environment",
            bool(virtual_env)
            and sys.prefix != sys.base_prefix
            and actual_prefix == expected_prefix,
            f"executable={sys.executable}; prefix={sys.prefix}",
        )
    )
    checks.append(("prebuilt core library", LIB.is_dir(), str(LIB.relative_to(ROOT))))
    checks.append(("vendored open source", SOURCE.is_dir(), str(SOURCE.relative_to(ROOT))))
    checks.append(("claim manifest", (ROOT / "claims/manifest.json").is_file(), "claims/manifest.json"))

    for module_name in ("z3", "numpy", "scipy", "networkx", "sympy", "pytest"):
        try:
            module = __import__(module_name)
            version = getattr(module, "__version__", "available")
            checks.append((module_name, True, str(version)))
        except Exception as exc:  # pragma: no cover - diagnostic path
            checks.append((module_name, False, str(exc)))

    try:
        import capopt
        from capopt import _native

        capopt_file = Path(capopt.__file__).resolve()
        checks.append(
            (
                "capopt import (prebuilt lib)",
                _under_path(capopt_file, LIB),
                f"{capopt_file} (HAVE_NATIVE={_native.HAVE_NATIVE})",
            )
        )
    except Exception as exc:  # pragma: no cover - diagnostic path
        checks.append(("capopt import (prebuilt lib)", False, str(exc)))

    print("Environment")
    for label, passed, detail in checks:
        print(f"  {'PASS' if passed else 'FAIL':4}  {label}: {detail}")
    failed = [label for label, passed, _ in checks if not passed]
    print(f"ENVIRONMENT: {'PASS' if not failed else 'FAIL'}")
    return 1 if failed else 0


def run_demo() -> int:
    """Exercise matching plus the real Z3 gate on a CHERI rewrite."""
    from capopt.capability_model import CapabilityModel
    from capopt.cost_model import CostModel, CostWeights
    from capopt.ir_superoptimizer import IRSuperoptimizer

    optimizer = IRSuperoptimizer(
        CostModel(CostWeights()),
        CapabilityModel(),
        random_seed=0,
    )
    if optimizer.llvm_smt_verifier is None or not optimizer.llvm_smt_verifier.is_available():
        print("DEMO: FAIL (Z3 verifier unavailable)")
        return 1

    source = [
        "define void @f(i8 addrspace(200)* %cap, i64 %mask) {",
        "entry:",
        "  %perms = call i64 @llvm.cheri.cap.perms.get(i8 addrspace(200)* %cap)",
        "  %masked = and i64 %perms, %mask",
        "  %cap2 = call i8 addrspace(200)* @llvm.cheri.cap.perms.set(i8 addrspace(200)* %cap, i64 %masked)",
        "  ret void",
        "}",
    ]
    optimized, applied = optimizer._apply_textual_rewrites(source)
    incidents = [str(item) for item in optimizer.textual_rewrite_incidents]
    proven = (
        "perms_and_rewrite" in applied
        and any("@llvm.cheri.cap.perms.and" in line for line in optimized)
        and not incidents
    )
    report = {
        "demo": "permission restriction fusion",
        "source": source,
        "optimized": optimized,
        "applied": applied,
        "incidents": incidents,
        "smt_proven": proven,
    }
    _write_json("demo-report.json", report)
    print(json.dumps(report, indent=2))
    print(f"SMT DEMO: {'PASS' if proven else 'FAIL'}")
    return 0 if proven else 1


def reproduce_short() -> int:
    """Run fresh code plus exact short paper-result recomputation."""
    return _run([sys.executable, str(ROOT / "ae" / "short_reproduction.py")])


def recompute(claim: str) -> int:
    """Freshly recompute C4–C7 evidence from shipped raw data."""
    return _run(
        [sys.executable, str(ROOT / "ae" / "recompute_claims.py"), claim]
    )


def reproduce_small(claim: str) -> int:
    """Run the C1/C2/C3/C8/C9 pipeline on the bundled small dataset."""
    return _run(
        [
            sys.executable,
            str(ROOT / "ae" / "reproduce_small.py"),
            "--claim",
            claim,
        ]
    )


def morello_report(run_dir: str) -> int:
    """Validate a credential-free result collected by the host SSH helper."""
    return _run(
        [
            sys.executable,
            str(ROOT / "ae" / "morello" / "report.py"),
            "--root",
            str(ROOT),
            "--run-dir",
            run_dir,
        ]
    )


AE_TESTS = ROOT / "ae" / "tests"

QUICK_TESTS = [
    TESTS / "test_textual_rewrite_verification.py",
    TESTS / "test_smt_llvmir.py",
    TESTS / "test_classify_rewrites.py",
    TESTS / "test_check_paper_claims.py",
    AE_TESTS / "test_recompute_claims.py",
]


def run_tests(full: bool) -> int:
    paths = (
        [str(TESTS), str(AE_TESTS)]
        if full
        else [str(path) for path in QUICK_TESTS]
    )
    started = time.monotonic()
    rc = _run([sys.executable, "-m", "pytest", "-q", *paths], cwd=SOURCE)
    elapsed = time.monotonic() - started
    print(f"{'FULL' if full else 'QUICK'} TESTS: {'PASS' if rc == 0 else 'FAIL'} ({elapsed:.1f}s)")
    return rc


def _select(value: Any, selector: str | list[str]) -> Any:
    current = value
    components = selector if isinstance(selector, list) else selector.split(".")
    for component in components:
        if isinstance(current, list):
            current = current[int(component)]
        elif isinstance(current, dict):
            current = current[component]
        else:
            raise KeyError(f"{selector}: {component!r} is not selectable")
    return current


def _compare(actual: Any, check: dict[str, Any]) -> tuple[bool, str]:
    op = check.get("op", "eq")
    expected = check.get("expected")
    if op == "eq":
        passed = actual == expected
    elif op == "approx":
        passed = math.isclose(
            float(actual),
            float(expected),
            rel_tol=float(check.get("relative_tolerance", 0.0)),
            abs_tol=float(check.get("absolute_tolerance", 0.0)),
        )
    elif op == "lte":
        passed = float(actual) <= float(expected)
    elif op == "gte":
        passed = float(actual) >= float(expected)
    elif op == "truthy":
        passed = bool(actual)
        expected = True
    else:
        raise ValueError(f"unsupported comparison {op!r}")
    return passed, f"actual={actual!r}, expected {op} {expected!r}"


def _evaluate_data_claim(claim: dict[str, Any]) -> tuple[str, list[dict[str, Any]]]:
    observations: list[dict[str, Any]] = []
    passed = True
    for check in claim.get("checks", []):
        path = ROOT / check["path"]
        try:
            document = json.loads(path.read_text())
            actual = _select(document, check["selector"])
            ok, detail = _compare(actual, check)
        except (OSError, json.JSONDecodeError, KeyError, ValueError, TypeError) as exc:
            ok, actual, detail = False, None, str(exc)
        observations.append(
            {
                "path": check["path"],
                "selector": check["selector"],
                "actual": actual,
                "passed": ok,
                "detail": detail,
            }
        )
        passed &= ok
    return ("PASS" if passed else "FAIL"), observations


def _evaluate_command_claim(claim: dict[str, Any]) -> tuple[str, list[dict[str, Any]]]:
    command = [
        part.replace("{python}", sys.executable).replace("{root}", str(ROOT))
        for part in claim["command"]
    ]
    rc = _run(command, cwd=SOURCE)
    return (
        "PASS" if rc == 0 else "FAIL",
        [{"command": command, "returncode": rc, "passed": rc == 0}],
    )


def verify_claims(strict: bool = False) -> int:
    manifest_path = ROOT / "claims" / "manifest.json"
    manifest = json.loads(manifest_path.read_text())
    records: list[dict[str, Any]] = []

    for claim in manifest["claims"]:
        state = claim.get("state", "ready")
        observations: list[dict[str, Any]] = []
        if state == "pending":
            status = "PENDING"
        elif state == "blocked":
            status = "BLOCKED"
            for check in claim.get("checks", []):
                _, observed = _evaluate_data_claim({"checks": [check]})
                observations.extend(observed)
        elif claim.get("kind", "data") == "command":
            status, observations = _evaluate_command_claim(claim)
        else:
            status, observations = _evaluate_data_claim(claim)

        record = {
            "id": claim["id"],
            "paper": claim["paper"],
            "status": status,
            "summary": claim["summary"],
            "reason": claim.get("reason"),
            "observations": observations,
        }
        records.append(record)
        suffix = f" — {claim.get('reason')}" if claim.get("reason") else ""
        print(f"{status:7} {claim['id']}: {claim['summary']}{suffix}")
        for observation in observations:
            if "detail" in observation:
                print(f"          {observation['selector']}: {observation['detail']}")

    counts = {
        status: sum(record["status"] == status for record in records)
        for status in ("PASS", "FAIL", "PENDING", "BLOCKED")
    }
    report = {
        "schema_version": 1,
        "manifest": str(manifest_path.relative_to(ROOT)),
        "counts": counts,
        "claims": records,
    }
    _write_json("claims-report.json", report)
    print(
        "CLAIMS: "
        + " / ".join(f"{counts[key]} {key}" for key in ("PASS", "FAIL", "PENDING", "BLOCKED"))
    )

    unacceptable = counts["FAIL"] or (strict and (counts["PENDING"] or counts["BLOCKED"]))
    return 1 if unacceptable else 0


def closure() -> int:
    return _run(
        [sys.executable, str(ROOT / "ae" / "closure_check.py"), "--root", str(ROOT)]
    )


def kick_the_tires() -> int:
    started = time.monotonic()
    results = [
        ("environment", check_environment()),
        ("closure", closure()),
        ("SMT demo", run_demo()),
        ("short paper reproduction", reproduce_short()),
        ("quick tests", run_tests(full=False)),
    ]
    elapsed = time.monotonic() - started
    failed = [name for name, rc in results if rc]
    print(f"KICK-THE-TIRES: {'FAIL' if failed else 'PASS'} ({elapsed:.1f}s)")
    if failed:
        print("Failed stages: " + ", ".join(failed))
    return 1 if failed else 0


def release_check() -> int:
    """Strict pre-DOI gate; fails while any claim is pending or blocked."""
    stages = [
        ("environment", check_environment()),
        ("closure", closure()),
        ("all claims", verify_claims(strict=True)),
        ("full tests", run_tests(full=True)),
    ]
    failed = [name for name, rc in stages if rc]
    print(f"RELEASE CHECK: {'FAIL' if failed else 'PASS'}")
    if failed:
        print("Failed stages: " + ", ".join(failed))
    return 1 if failed else 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("env", help="check the packaged Python environment")
    subparsers.add_parser("demo", help="run one end-to-end SMT-gated rewrite")
    subparsers.add_parser(
        "reproduce-short",
        help="run fresh short experiments and reproduce paper claims C4/C5",
    )
    recompute_parser = subparsers.add_parser(
        "recompute",
        help="freshly recompute C4–C7 claim evidence from shipped raw data",
    )
    recompute_parser.add_argument(
        "--claim",
        choices=["C4", "C5", "C6", "C7", "all"],
        default="all",
        help="claim to recompute (default: all)",
    )
    reproduce_small_parser = subparsers.add_parser(
        "reproduce-small",
        help="run the C1/C2/C3/C8/C9 analysis pipeline on the bundled "
        "small recorded dataset",
    )
    reproduce_small_parser.add_argument(
        "--claim",
        choices=["C1", "C2", "C3", "C8", "C9", "all"],
        default="all",
        help="claim whose checks decide the exit code (default: all)",
    )
    morello_parser = subparsers.add_parser(
        "morello-report",
        help="validate a p01 hardware run collected by ae/morello/run.sh",
    )
    morello_parser.add_argument(
        "--run-dir",
        required=True,
        help="credential-free result directory below ae-output/morello",
    )
    test_parser = subparsers.add_parser("tests", help="run regression tests")
    test_parser.add_argument("--full", action="store_true")
    claim_parser = subparsers.add_parser("claims", help="verify shipped claim evidence")
    claim_parser.add_argument("--strict", action="store_true")
    subparsers.add_parser("closure", help="validate artifact containment and hashes")
    subparsers.add_parser("kick-the-tires", help="run the fast reviewer lane")
    subparsers.add_parser("release-check", help="run the strict pre-release gate")
    args = parser.parse_args()

    commands = {
        "env": check_environment,
        "demo": run_demo,
        "reproduce-short": reproduce_short,
        "closure": closure,
        "kick-the-tires": kick_the_tires,
        "release-check": release_check,
    }
    if args.command == "tests":
        return run_tests(args.full)
    if args.command == "claims":
        return verify_claims(args.strict)
    if args.command == "recompute":
        return recompute(args.claim)
    if args.command == "reproduce-small":
        return reproduce_small(args.claim)
    if args.command == "morello-report":
        return morello_report(args.run_dir)
    return commands[args.command]()


if __name__ == "__main__":
    raise SystemExit(main())
