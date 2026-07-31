#!/usr/bin/env python3
"""Collect the bounded p01 AE measurement from a fixed Morello board.

This script is deliberately host-only.  SSH credentials remain with the
reviewer's OpenSSH client and are never mounted into the unauthenticated
Jupyter container.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
INPUTS = ROOT / "ae" / "inputs" / "morello-p01"
KNOWN_HOSTS = Path(__file__).with_name("known_hosts")
OUTPUT = ROOT / "ae-output" / "morello"

BOARDS = {
    "morello-1": "192.168.10.101",
    "morello-2": "192.168.10.102",
}
VARIANTS = {
    "baseline_o3": INPUTS / "baseline_o3-p01",
    "o3_asm": INPUTS / "o3_asm-p01",
}
EXPECTED_SHA256 = "11f2f931a37dc6ae04eb6f6fe4ba4006b0feb3f9442878e9da6571f02b3c3b1a"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _host_key_fingerprint(host: str) -> str:
    for line in KNOWN_HOSTS.read_text().splitlines():
        fields = line.split()
        if len(fields) == 3 and host in fields[0].split(","):
            key = base64.b64decode(fields[2])
            value = base64.b64encode(hashlib.sha256(key).digest()).decode().rstrip("=")
            return f"SHA256:{value}"
    raise RuntimeError(f"no pinned host key for {host}")


def _ssh_options() -> list[str]:
    return [
        "-F",
        "/dev/null",
        "-o",
        "BatchMode=yes",
        "-o",
        "PasswordAuthentication=no",
        "-o",
        "KbdInteractiveAuthentication=no",
        "-o",
        "ForwardAgent=no",
        "-o",
        "ClearAllForwardings=yes",
        "-o",
        "RequestTTY=no",
        "-o",
        "PermitLocalCommand=no",
        "-o",
        "ConnectTimeout=10",
        "-o",
        "StrictHostKeyChecking=yes",
        "-o",
        f"UserKnownHostsFile={KNOWN_HOSTS}",
        "-o",
        "LogLevel=ERROR",
    ]


def _ssh(target: str, *remote: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["ssh", *_ssh_options(), target, "--", *remote],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=check,
    )


def _scp(local: Path, target: str, remote: str) -> None:
    subprocess.run(
        ["scp", "-q", *_ssh_options(), str(local), f"{target}:{remote}"],
        check=True,
    )


def _parse_pmc(text: str) -> tuple[int, int]:
    saw_header = False
    for line in text.splitlines():
        if "p/inst_retired" in line and "p/cpu_cycles" in line:
            saw_header = True
            continue
        if saw_header:
            match = re.fullmatch(r"\s*(\d+)\s+(\d+)\s*", line)
            if match:
                return int(match.group(1)), int(match.group(2))
    raise RuntimeError(f"could not parse pmcstat counters from {text!r}")


def _safe_run_dir(relative: str) -> tuple[Path, str]:
    relative_path = Path(relative)
    if (
        relative_path.is_absolute()
        or len(relative_path.parts) != 3
        or relative_path.parts[:2] != ("ae-output", "morello")
        or not re.fullmatch(r"[A-Za-z0-9._-]+", relative_path.name)
    ):
        raise ValueError("run directory must be one safe child of ae-output/morello")

    shared_root = ROOT / "ae-output"
    for directory, label in ((shared_root, "ae-output"), (OUTPUT, "Morello output")):
        if directory.is_symlink():
            raise ValueError(f"{label} directory must not be a symbolic link")
        if not directory.exists():
            directory.mkdir(mode=0o700)
        directory_stat = directory.stat()
        if not directory.is_dir() or directory_stat.st_uid != os.getuid():
            raise ValueError(f"{label} directory must be owned by this user")

    path = OUTPUT / relative_path.name
    if path.exists() or path.is_symlink():
        raise ValueError("run directory already exists")
    return path, str(path.relative_to(ROOT))


def _probe(target: str) -> dict[str, Any]:
    # Keep every remote operation a fixed argv command. In particular, do not
    # pass a compound string to ``sh -c``: OpenSSH concatenates remote argv and
    # a lost quoting boundary can expose the remote shell environment.
    required = (
        ("test", "-x", "/libexec/ld-elf.so.1"),
        ("command", "-v", "cpuset"),
        ("command", "-v", "pmcstat"),
        ("command", "-v", "lockf"),
        ("command", "-v", "sha256"),
    )
    for command in required:
        _ssh(target, *command)
    values: dict[str, Any] = {
        "arch": _ssh(target, "uname", "-m").stdout.strip(),
        "abi": _ssh(target, "uname", "-K").stdout.strip(),
        "release": _ssh(target, "sysctl", "-n", "kern.osrelease").stdout.strip(),
        "model": _ssh(target, "sysctl", "-n", "hw.model").stdout.strip(),
        "purecap_loader": True,
    }
    if values["arch"] != "arm64" or "Morello" not in values["model"]:
        raise RuntimeError(f"remote system is not the expected Morello board: {values}")
    return values


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--board", choices=sorted(BOARDS), default="morello-1")
    parser.add_argument("--iterations", type=int, default=10)
    parser.add_argument("--warmup", type=int, default=1)
    parser.add_argument("--cpu", type=int, default=1)
    parser.add_argument("--run-dir", required=True)
    args = parser.parse_args()

    if not 1 <= args.iterations <= 100:
        parser.error("--iterations must be between 1 and 100")
    if not 0 <= args.warmup <= 10:
        parser.error("--warmup must be between 0 and 10")
    if not 0 <= args.cpu <= 3:
        parser.error("--cpu must be between 0 and 3")

    user = os.environ.get("CAPOPT_MORELLO_USER", "root")
    if not re.fullmatch(r"[a-z_][a-z0-9_-]*", user):
        parser.error("CAPOPT_MORELLO_USER is not a valid account name")

    run_dir, relative_run_dir = _safe_run_dir(args.run_dir)
    raw_dir = run_dir / "raw"
    raw_dir.mkdir(parents=True, exist_ok=False)
    raw_path = raw_dir / "samples.ndjson"

    local_hashes = {name: _sha256(path) for name, path in VARIANTS.items()}
    if set(local_hashes.values()) != {EXPECTED_SHA256}:
        raise RuntimeError(f"p01 input digest mismatch: {local_hashes}")

    host = BOARDS[args.board]
    target = f"{user}@{host}"
    probe = _probe(target)
    scratch_result = _ssh(target, "mktemp", "-d", "/tmp/capopt-ae-p01.XXXXXX")
    scratch = scratch_result.stdout.strip()
    if not re.fullmatch(r"/tmp/capopt-ae-p01\.[A-Za-z0-9]+", scratch):
        raise RuntimeError(f"unsafe remote scratch path returned: {scratch!r}")

    started = datetime.now(timezone.utc)
    remote_hashes: dict[str, str] = {}
    records: list[dict[str, Any]] = []
    try:
        for variant, path in VARIANTS.items():
            remote = f"{scratch}/{variant}"
            _scp(path, target, remote)
            _ssh(target, "chmod", "700", remote)
            remote_hashes[variant] = _ssh(target, "sha256", "-q", remote).stdout.strip()
        if remote_hashes != local_hashes:
            raise RuntimeError(f"remote payload digest mismatch: {remote_hashes}")

        # ABI/load sanity check before collecting counters.
        dry = _ssh(target, f"{scratch}/baseline_o3")
        if dry.returncode != 0:
            raise RuntimeError("p01 dry execution failed")

        sequence = 0
        schedule: list[tuple[str, bool]] = []
        for _ in range(args.warmup):
            schedule.extend((variant, True) for variant in ("baseline_o3", "o3_asm"))
        for iteration in range(args.iterations):
            order = ("baseline_o3", "o3_asm")
            if iteration % 2:
                order = tuple(reversed(order))
            schedule.extend((variant, False) for variant in order)

        with raw_path.open("w") as raw:
            for variant, warmup in schedule:
                remote = f"{scratch}/{variant}"
                result = _ssh(
                    target,
                    "lockf",
                    "-t",
                    "30",
                    f"/tmp/capopt-ae-cpu{args.cpu}.lock",
                    "cpuset",
                    "-l",
                    str(args.cpu),
                    "pmcstat",
                    "-p",
                    "inst_retired",
                    "-p",
                    "cpu_cycles",
                    "--",
                    remote,
                )
                instructions, cycles = _parse_pmc(result.stdout + "\n" + result.stderr)
                record = {
                    "sequence": sequence,
                    "variant": variant,
                    "warmup": warmup,
                    "exit_code": result.returncode,
                    "inst_retired": instructions,
                    "cpu_cycles": cycles,
                }
                records.append(record)
                raw.write(json.dumps(record, sort_keys=True) + "\n")
                raw.flush()
                label = "warmup" if warmup else "sample"
                print(
                    f"{label:6} {sequence:02d} {variant:11} "
                    f"instructions={instructions} cycles={cycles}",
                    flush=True,
                )
                sequence += 1
    finally:
        cleanup = _ssh(target, "rm", "-rf", "--", scratch, check=False)
        if cleanup.returncode:
            print(
                f"WARNING: could not remove isolated remote scratch {scratch}",
                file=sys.stderr,
            )

    provenance = {
        "schema_version": 1,
        "experiment": "paper Section 6.4 p01 -O3-start Morello spot-check",
        "scope": (
            "Fresh execution of two frozen, byte-identical p01 binaries on one "
            "Morello board; this checks the paper's near-zero/no-rewrite row, "
            "not the Table 2 suite geomean."
        ),
        "board_alias": args.board,
        "pinned_host_key_fingerprint": _host_key_fingerprint(host),
        "probe": probe,
        "cpu": args.cpu,
        "iterations": args.iterations,
        "warmup": args.warmup,
        "started_utc": started.isoformat(),
        "finished_utc": datetime.now(timezone.utc).isoformat(),
        "payload_sha256": local_hashes,
        "remote_payload_sha256": remote_hashes,
    }
    (run_dir / "provenance.json").write_text(
        json.dumps(provenance, indent=2, sort_keys=True) + "\n"
    )
    print(f"Collected {len(records)} executions in {relative_run_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
