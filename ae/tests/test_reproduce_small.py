"""Small-dataset pipeline lane: `reproduce-small` must launch the real
analysis scripts (aggregation, gen_table.py, optimization_time.py,
apply_validation_gate.py) over the bundled recorded dataset, leave the
pristine inputs untouched, write ae-output/small-campaign/report.json, and
exit zero only when every C1/C2/C3/C8/C9 semantic check holds."""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
INPUTS = ROOT / "ae" / "inputs" / "small-campaign"
OUTPUT = ROOT / "ae-output" / "small-campaign"
CLAIM_IDS = {
    "C1-two-level-ablation",
    "C2-hd-speedup",
    "C3-spec-llama-speedup",
    "C8-optimization-time",
    "C9-no-regression",
}


def _input_digest() -> str:
    digest = hashlib.sha256()
    for path in sorted(INPUTS.rglob("*")):
        if path.is_file():
            digest.update(str(path.relative_to(INPUTS)).encode())
            digest.update(path.read_bytes())
    return digest.hexdigest()


@pytest.fixture(scope="module")
def report() -> dict:
    before = _input_digest()
    result = subprocess.run(
        [sys.executable, str(ROOT / "ae" / "reproduce_small.py")],
        cwd=ROOT,
        text=True,
        capture_output=True,
    )
    assert result.returncode == 0, (
        f"reproduce-small failed\nstdout:\n{result.stdout}"
        f"\nstderr:\n{result.stderr}"
    )
    assert _input_digest() == before, "pristine bundled inputs were modified"
    report_path = OUTPUT / "report.json"
    assert report_path.is_file(), f"missing report {report_path}"
    return json.loads(report_path.read_text())


def test_every_claim_passes_with_observations(report: dict) -> None:
    assert {entry["claim_id"] for entry in report["claims"]} == CLAIM_IDS
    for entry in report["claims"]:
        assert entry["passed"] is True, json.dumps(entry, indent=2)
        assert entry["observations"], entry["claim_id"]
        assert all(obs["passed"] for obs in entry["observations"])
    assert report["passed"] is True


def test_pipeline_launched_the_real_scripts(report: dict) -> None:
    launched = " ".join(" ".join(command) for command in report["commands"])
    assert "gen_table.py" in launched
    assert "optimization_time.py" in launched
    assert "apply_validation_gate.py" in launched


def test_artifacts_exist_and_figure_is_a_pdf(report: dict) -> None:
    for relative in report["artifacts"].values():
        assert (ROOT / relative).is_file(), relative
    figure = ROOT / report["artifacts"]["figure"]
    assert figure.stat().st_size > 0
    assert figure.read_bytes()[:5] == b"%PDF-"


def test_single_claim_gate_returns_zero() -> None:
    result = subprocess.run(
        [
            sys.executable,
            str(ROOT / "ae" / "runner.py"),
            "reproduce-small",
            "--claim",
            "C9",
        ],
        cwd=ROOT,
        text=True,
        capture_output=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "REPRODUCE-SMALL(C9): PASS" in result.stdout
