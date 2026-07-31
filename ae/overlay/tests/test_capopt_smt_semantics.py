import pathlib
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from superoptimization.capopt.smt import CapabilitySMTVerifier, SMTGuidedEnumerator  # noqa: E402


@pytest.fixture(scope="module")
def solver() -> CapabilitySMTVerifier:
    # Keep the regression suite evaluator-safe: difficult FP128 queries may
    # otherwise run without a bound.  "unknown" remains a conservative
    # checked-but-not-proven result, which is exactly what negative tests
    # require.
    verifier = CapabilitySMTVerifier(enable=True, timeout_ms=5000)
    if not verifier.is_available():
        pytest.skip("Z3 solver not available")
    return verifier


def test_cseal_cunseal_round_trip(solver: CapabilitySMTVerifier) -> None:
    original = [
        "    cseal c5, c1, c2",
        "    cunseal c5, c5, c2",
    ]
    replacement = ["    cmove c5, c1"]
    result = solver.verify_candidate(original, replacement)
    assert result.checked and not result.proven


def test_cinvoke_rewrite_rejected(solver: CapabilitySMTVerifier) -> None:
    original = ["    cinvoke c1, c2, c3"]
    replacement = ["    cmove c1, c2"]
    result = solver.verify_candidate(original, replacement)
    assert result.checked and not result.proven


def test_grammar_enumerator_discovers_offset_fold(solver: CapabilitySMTVerifier) -> None:
    enumerator = SMTGuidedEnumerator(solver)
    lines = [
        "    cincoffset c3, c2, 4",
        "    cincoffset c3, c3, 8",
    ]
    candidates = enumerator.grammar_candidates(lines, max_window=2, max_depth=1, max_results=8)
    fold_candidates = enumerator.fold_cincoffsetimm_candidates(lines)
    all_candidates = candidates + fold_candidates
    # Now satisfied via the guarded (bucket-stable) candidate produced by
    # fold_cincoffsetimm_candidates — the unconditional fold is refused
    # after the A3 fix (see test_offset_fold_unconditional_is_refused).
    assert any(
        ("cincoffsetimm c3, c2, 12" in "\n".join(cand[2]))
        or ("cincoffset c3, c2, 12" in "\n".join(cand[2]))
        for cand in all_candidates
    )


def test_offset_fold_unconditional_is_refused(solver: CapabilitySMTVerifier) -> None:
    """The unconditional offset-fold is genuinely unsound (A3 fix); the
    verifier must keep refusing it when no precondition is supplied."""
    block = [
        "    cincoffset c3, c2, 4",
        "    cincoffset c3, c3, 8",
    ]
    result = solver.verify_candidate(block, ["    cincoffsetimm c3, c2, 12"])
    assert result.checked and not result.proven and result.precondition is None


def test_offset_fold_proven_under_bucket_stable_guard(
    solver: CapabilitySMTVerifier,
) -> None:
    """Under the encoding-aware bucket-stable precondition (cursor at
    each fastRepCheck site shares the source cap's B-aligned mantissa
    bucket), the offset-fold becomes provable -- but the result is
    reported as conditional (proven=False, precondition set)."""
    block = [
        "    cincoffset c3, c2, 4",
        "    cincoffset c3, c3, 8",
    ]
    result = solver.verify_candidate(
        block,
        ["    cincoffsetimm c3, c2, 12"],
        assume_bucket_stable=("c2", [0, 4]),
    )
    assert result.checked
    assert result.proven is False
    assert result.precondition is not None
    assert "bucket_stable" in result.precondition
    assert "c2" in result.precondition


def test_fold_cincoffsetimm_offset_fold_is_guarded(
    solver: CapabilitySMTVerifier,
) -> None:
    """fold_cincoffsetimm_candidates must recover the offset-fold as a
    GUARDED candidate: SolverResult.proven=False, precondition set, and
    metadata['precondition'] recorded."""
    enumerator = SMTGuidedEnumerator(solver)
    block = [
        "    cincoffset c3, c2, 4",
        "    cincoffset c3, c3, 8",
    ]
    fold_candidates = enumerator.fold_cincoffsetimm_candidates(block)
    matches = [
        cand
        for cand in fold_candidates
        if "cincoffsetimm c3, c2, 12" in "\n".join(cand[2])
    ]
    assert matches, "expected the offset-fold candidate to be recovered"
    _start, _end, _replacement, result, metadata = matches[0]
    assert result.proven is False
    assert result.precondition is not None
    assert metadata.get("precondition") is not None


def test_grammar_enumerator_handles_integer_ops(solver: CapabilitySMTVerifier) -> None:
    enumerator = SMTGuidedEnumerator(solver)
    lines = [
        "    add x5, x1, x2",
    ]
    candidates = enumerator.grammar_candidates(lines, max_window=1, max_depth=1, max_results=8)
    assert any("add x5, x2, x1" in "\n".join(cand[2]) for cand in candidates)


def test_grammar_enumerator_handles_fp_ops(solver: CapabilitySMTVerifier) -> None:
    enumerator = SMTGuidedEnumerator(solver)
    lines = [
        "    fsgnj.s f2, f3, f4",
    ]
    candidates = enumerator.grammar_candidates(lines, max_window=1, max_depth=1, max_results=8)
    assert isinstance(candidates, list)


def test_effect_kind_mismatch_is_reported(solver: CapabilitySMTVerifier) -> None:
    original = ["    lc cs1, 48(csp)"]
    replacement = ["    cincoffsetimm cs1, csp, 48"]
    result = solver.verify_candidate(original, replacement)
    assert result.checked and not result.proven
    # M3.4: the ordered memory-event trace check fires before the
    # effect-set comparison, so the mismatch surfaces with the more
    # precise reason.
    assert (
        "side_effect" in result.reason
        or "effect" in result.reason
        or result.reason == "memory_event_order_mismatch"
    )


def test_fmadd_requires_addend(solver: CapabilitySMTVerifier) -> None:
    original = ["    fmadd.d f3, f1, f2, f0"]
    replacement = ["    fmul.d f3, f1, f2"]
    result = solver.verify_candidate(original, replacement)
    assert result.checked and not result.proven


def test_fmin_not_equal_fmax(solver: CapabilitySMTVerifier) -> None:
    original = ["    fmin.s f5, f1, f2"]
    replacement = ["    fmax.s f5, f1, f2"]
    result = solver.verify_candidate(original, replacement)
    assert result.checked and not result.proven


def test_fsgnj_differs_from_fsgnjn(solver: CapabilitySMTVerifier) -> None:
    original = ["    fsgnj.s f2, f3, f4"]
    replacement = ["    fsgnjn.s f2, f3, f4"]
    result = solver.verify_candidate(original, replacement)
    assert result.checked and not result.proven


def test_fcvt_ws_not_equal_move(solver: CapabilitySMTVerifier) -> None:
    original = ["    fcvt.w.s x5, f1"]
    replacement = ["    fmv.x.w x5, f1"]
    result = solver.verify_candidate(original, replacement)
    assert result.checked and not result.proven


def test_fcsr_write_matches_component_writes(solver: CapabilitySMTVerifier) -> None:
    original = ["    csrrwi fcsr, zero, 0x20"]
    replacement = [
        "    csrrwi frm, zero, 1",
        "    csrrwi fflags, zero, 0",
    ]
    result = solver.verify_candidate(original, replacement)
    assert result.checked and result.proven


def test_fmin_sets_fflags_on_snan(solver: CapabilitySMTVerifier) -> None:
    original = [
        "    li x5, 0x7F000001",
        "    fmv.w.x f1, x5",
        "    fmin.s f2, f1, f1",
    ]
    replacement = [
        "    li x5, 0x7F000001",
        "    fmv.w.x f1, x5",
        "    fsgnj.s f2, f1, f1",
    ]
    result = solver.verify_candidate(original, replacement)
    assert result.checked and not result.proven


def test_fmv_hx_differs_from_fmv_wx(solver: CapabilitySMTVerifier) -> None:
    original = ["    fmv.h.x f1, x3"]
    replacement = ["    fmv.w.x f1, x3"]
    result = solver.verify_candidate(original, replacement)
    assert result.checked and not result.proven


def test_flh_store_cannot_be_dropped(solver: CapabilitySMTVerifier) -> None:
    original = [
        "    flh f1, 0(x2)",
        "    fsh f1, 0(x2)",
    ]
    replacement = [
        "    flh f1, 0(x2)",
    ]
    result = solver.verify_candidate(original, replacement)
    assert result.checked and not result.proven


def test_fadd_h_not_equal_fsub_h(solver: CapabilitySMTVerifier) -> None:
    original = ["    fadd.h f2, f0, f1"]
    replacement = ["    fsub.h f2, f0, f1"]
    result = solver.verify_candidate(original, replacement)
    assert result.checked and not result.proven


@pytest.mark.skip(
    reason=(
        "z3-solver 4.16 does not reliably honour its timeout for this "
        "FP128 division query; this negative sanity check is not a paper claim"
    )
)
def test_fdiv_q_not_equal_fmul_q(solver: CapabilitySMTVerifier) -> None:
    original = ["    fdiv.q f4, f2, f3"]
    replacement = ["    fmul.q f4, f2, f3"]
    result = solver.verify_candidate(original, replacement)
    assert result.checked and not result.proven


def test_fcvt_h_w_not_move(solver: CapabilitySMTVerifier) -> None:
    original = ["    fcvt.h.w f1, x5"]
    replacement = ["    fmv.h.x f1, x5"]
    result = solver.verify_candidate(original, replacement)
    assert result.checked and not result.proven


def test_fcvt_q_d_not_identity(solver: CapabilitySMTVerifier) -> None:
    original = ["    fcvt.q.d f3, f2"]
    replacement = ["    fsgnj.q f3, f2, f2"]
    result = solver.verify_candidate(original, replacement)
    assert result.checked and not result.proven


def test_flq_store_cannot_be_dropped(solver: CapabilitySMTVerifier) -> None:
    original = [
        "    flq f1, 0(x2)",
        "    fsq f1, 0(x2)",
    ]
    replacement = [
        "    flq f1, 0(x2)",
    ]
    result = solver.verify_candidate(original, replacement)
    assert result.checked and not result.proven


def test_input_mismatch_is_reported(solver: CapabilitySMTVerifier) -> None:
    original = [
        "    add x1, x2, x3",
    ]
    replacement = [
        "    add x1, x2, x4",
    ]
    result = solver.verify_candidate(original, replacement)
    assert not result.checked
    assert result.reason.startswith("input_mismatch")


def test_store_versions_preserve_order(solver: CapabilitySMTVerifier) -> None:
    original = [
        "    sw x1, 0(x2)",
        "    sw x1, 0(x2)",
    ]
    replacement = [
        "    sw x1, 0(x2)",
    ]
    result = solver.verify_candidate(original, replacement)
    assert result.checked and not result.proven
    assert result.reason in ("distinct_side_effect_sets", "memory_event_order_mismatch")


def test_frm_snapshot_enforced(solver: CapabilitySMTVerifier) -> None:
    original = [
        "    csrrwi frm, zero, 1",
    ]
    replacement = [
        "    nop",
    ]
    result = solver.verify_candidate(original, replacement)
    assert result.checked and not result.proven
    assert result.reason in ("distinct_side_effect_sets", "memory_event_order_mismatch")


def test_quick_counterexample_generates_sandbox_trace(solver: CapabilitySMTVerifier) -> None:
    solver.collect_sandbox_replays()
    quick = getattr(solver, "_quick_tester", None)
    if quick is None:
        pytest.skip("Quick tester unavailable")
    quick._cached_vectors.clear()  # type: ignore[attr-defined]
    quick._cached_vectors.append({"x2": ("int", 3), "x3": ("int", 1)})  # type: ignore[attr-defined]
    original = ["    add x1, x2, x3"]
    replacement = ["    sub x1, x2, x3"]
    result = solver.verify_candidate(original, replacement)
    assert result.reason == "quick_counterexample"
    traces = solver.collect_sandbox_replays()
    assert traces, "sandbox replay should capture quick tester counterexample"
    trace = traces[-1]
    assert trace.reason == "quick_counterexample"
    assert "x1" in trace.register_differences


def test_unsupported_sequence_emits_sandbox_trace(solver: CapabilitySMTVerifier) -> None:
    solver.collect_sandbox_replays()
    original = ["    imaginary.mnemonic x1, x2, x3"]
    replacement = ["    add x1, x2, x3"]
    result = solver.verify_candidate(original, replacement)
    assert not result.checked
    assert result.reason == "unsupported_instructions"
    traces = solver.collect_sandbox_replays()
    assert traces
    assert traces[-1].reason == "unsupported_instructions"


def test_offset_fold_upgraded_to_proven_when_context_discharges(solver):
    """When the source cap's cursor is concretely known at csetbounds
    time (via a preceding ``csetaddr`` with a concrete immediate), the
    offset-fold's bucket-stable guard reduces to a closed Z3 expression
    and discharges, upgrading the candidate to ``proven=True``.

    See ``## Refinement: ConcreteAddrFact`` in
    ``docs/superpowers/specs/2026-05-23-context-fact-discharge-design.md``
    for why the symbolic-csetbounds variant is NOT discharge-able and
    requires the ``csetaddr`` first."""
    enumerator = SMTGuidedEnumerator(solver)
    lines = [
        "    csetaddr c2, c1, 0x1080",
        "    csetbounds c2, c2, 0x40",
        "    cincoffset c3, c2, 4",
        "    cincoffset c3, c3, 8",
    ]
    fold_candidates = enumerator.fold_cincoffsetimm_candidates(lines)
    matching = [c for c in fold_candidates
                if "cincoffsetimm c3, c2, 12" in "\n".join(c[2])]
    assert matching, "expected the fold candidate to be discovered"
    _, _, _, result, metadata = matching[0]
    assert result.proven is True, (
        f"context-fact analyzer should have discharged the bucket-stable guard "
        f"and upgraded the candidate to proven=True; got proven={result.proven}, "
        f"precondition={result.precondition}, reason={result.reason}"
    )
    # Soundness invariant: proven=True implies precondition=None.
    assert result.precondition is None
    assert "discharged" in metadata.get("precondition_status", "")


def test_offset_fold_stays_guarded_when_context_is_ambiguous(solver):
    """When the source cap is not tracked (no construction site in window),
    the fold stays guarded — proven=False, precondition set."""
    enumerator = SMTGuidedEnumerator(solver)
    lines = [
        "    cincoffset c3, c2, 4",
        "    cincoffset c3, c3, 8",
    ]
    fold_candidates = enumerator.fold_cincoffsetimm_candidates(lines)
    matching = [c for c in fold_candidates
                if "cincoffsetimm c3, c2, 12" in "\n".join(c[2])]
    assert matching, "expected the fold candidate to be discovered (guarded)"
    _, _, _, result, _ = matching[0]
    assert result.proven is False
    assert result.precondition is not None


def test_offset_fold_stays_guarded_when_csetbounds_src_addr_is_symbolic(solver):
    """Documented v1 limitation: ``csetbounds`` without a preceding
    concrete ``csetaddr`` leaves the source cursor symbolic, the
    bucket-stable predicate has counterexamples near 0x800 boundaries,
    and the discharge correctly returns ``discharged=False``."""
    enumerator = SMTGuidedEnumerator(solver)
    lines = [
        "    csetbounds c2, c1, 0x40",
        "    cincoffset c3, c2, 4",
        "    cincoffset c3, c3, 8",
    ]
    fold_candidates = enumerator.fold_cincoffsetimm_candidates(lines)
    matching = [c for c in fold_candidates
                if "cincoffsetimm c3, c2, 12" in "\n".join(c[2])]
    assert matching, "expected the fold candidate to be discovered (guarded)"
    _, _, _, result, metadata = matching[0]
    assert result.proven is False, (
        "symbolic-csetbounds discharge is a known v1 limitation; the "
        f"candidate must stay guarded. got proven=True, reason={result.reason}"
    )
    assert result.precondition is not None
    status = metadata.get("precondition_status", "")
    assert "guarded_undischarged" in status or "guard_query_" in status


def test_offset_fold_stays_guarded_when_csetbounds_appears_after_chain(solver):
    """Post-chain csetaddr+csetbounds writes to the source register MUST NOT
    install facts visible to the chain's discharge attempt. Without this guard
    the analyzer would unsoundly upgrade a candidate whose source cap was
    actually unknown at chain execution time."""
    enumerator = SMTGuidedEnumerator(solver)
    lines = [
        "    cincoffset c3, c2, 4",          # chain: c2 provenance unknown
        "    cincoffset c3, c3, 8",
        "    csetaddr c2, c0, 0x1080",        # post-chain write — must NOT leak
        "    csetbounds c2, c2, 0x40",        # into the fact store at chain time
    ]
    fold_candidates = enumerator.fold_cincoffsetimm_candidates(lines)
    matching = [c for c in fold_candidates
                if "cincoffsetimm c3, c2, 12" in "\n".join(c[2])]
    assert matching, "expected the fold candidate to be discovered"
    _, _, _, result, _ = matching[0]
    assert result.proven is False, (
        "post-chain csetbounds for c2 leaked into the discharge — "
        "the candidate was unsoundly upgraded to proven=True"
    )
    assert result.precondition is not None


# ======================================================================
# A1 — _heuristic_certificate must not bypass SMT verification
#
# Phase A — post-publication soundness audit (audit doc § A1).
# Before the fix, ``AssemblyOptimizer._heuristic_certificate`` returned
# ``proven=True`` for candidates whose ``metadata['pattern']`` was one of
# {asm_candperm_fusion, asm_csetboundsimm, asm_csetboundsimm_fusion,
#  asm_cincoffsetimm, asm_cincoffsetimm_fusion} — no liveness check on the
# ``tmp`` register that the pgss fusion matchers DROP from the rewrite.
# If ``tmp`` is read after the original sequence, dropping its definition
# is genuinely unsound; the certificate would silently claim proof.
#
# The fix removes the certificate; ALL candidates must now go through real
# SMT verification. This test pins that contract by constructing a candidate
# whose pattern is in the allowlist AND whose rewrite drops a tmp that is
# read later — and asserts the optimizer no longer reports proven=True.
# ======================================================================
def test_heuristic_certificate_does_not_bypass_smt_for_unsound_rewrite():
    """Constructing a candidate with the certified pattern label whose
    rewrite drops a ``tmp = imm`` definition that is read by a subsequent
    line MUST NOT be silently certified as proven. Before the fix the
    heuristic returned proven=True regardless of liveness; after the fix
    every candidate is required to obtain a real SMT proof.

    The pinned post-condition is the absence of the bypass: the candidate
    is not selected (because the SMT verifier — correctly — refuses to
    prove an unsound rewrite), so the optimizer's ``solver_verified``
    flag is false for the resulting (empty) optimisation.
    """
    from types import SimpleNamespace
    from superoptimization.capopt.assembly_optimizer import AssemblyOptimizer
    from superoptimization.capopt.candidates import SynthesisCandidate, SynthesisLevel

    config = SimpleNamespace(
        enable_smt_synthesis=True,
        require_solver_proof=True,
        solver_timeout_ms=5000,
        target_arch="riscv64-cheri",
        weight_latency=1.0,
        weight_bounds=1.0,
        weight_permissions=1.0,
        weight_tag=0.5,
        enable_normalization_cache=False,
    )
    optimizer = AssemblyOptimizer(config)

    # Original sequence: addi defines tmp register (x5), csetbounds reads it,
    # and a subsequent instruction (sw) reads x5 too. Dropping the addi makes
    # the second use see whatever x5 held BEFORE the original sequence — a
    # genuine soundness violation.
    original = [
        "    addi x5, zero, 16",
        "    csetbounds c2, c1, x5",
        "    sw x5, 0(x6)",
    ]
    # Replacement drops the addi (only fuses the first two; x5 is not redefined).
    replacement = [
        "    csetboundsimm c2, c1, 16",
        "    sw x5, 0(x6)",
    ]
    candidate = SynthesisCandidate(
        code="\n".join(replacement),
        level=SynthesisLevel.ASSEMBLY,
        provenance_trace=[],
        capability_changes={},
        estimated_cost=1.0,
        confidence=0.9,
        metadata={
            "pattern": "asm_csetboundsimm_fusion",
            "original_lines": original[:2],  # the fusion only matches the first 2 lines
            "match_range": (0, 2),
            "replacement_blocks": [[replacement[0]]],
        },
    )
    original_cost = optimizer.cost_model.assembly_cost("\n".join(original))
    best, solver_result = optimizer._select_candidate(original, [candidate], original_cost)

    # Pinned post-condition: the candidate is NOT certified as proven via
    # the heuristic-certificate bypass. With the bypass removed, the SMT
    # verifier either rejects the rewrite or returns checked=False; either
    # way the result must NOT be (checked=True, proven=True) backed by
    # "capopt-heuristic" / reason "pattern_certified".
    if solver_result is not None:
        assert not (
            solver_result.proven
            and solver_result.backend == "capopt-heuristic"
            and solver_result.reason == "pattern_certified"
        ), (
            "heuristic-certificate bypass still active: the optimizer "
            "accepted the allowlisted pattern without an SMT proof, "
            f"got {solver_result.to_dict()}"
        )
    # And with require_solver_proof=True, the candidate without a real proof
    # must not be selected at all.
    assert best is None, (
        "candidate selected without a real SMT proof — the heuristic "
        "bypass is still active"
    )


# ======================================================================
# Phase D — search-space improvements (D1, D2, D3)
# Documented in cheri-superoptimization Phase D plan; the items here are
# search-engine widenings (NOT semantic changes), and the tests pin the
# observable contract change at the verifier/matcher boundary.
# ======================================================================


def test_d1_mcmc_attaches_original_lines_and_replacement_blocks():
    """D1 — MCMC ``_to_candidate`` MUST attach ``original_lines`` and
    ``replacement_blocks`` so that ``AssemblyOptimizer._run_solver`` can
    dispatch the SMT verifier on MCMC-produced candidates. Before D1 the
    solver returned ``reason="original_snippet_missing"`` and the
    candidate was silently dropped under ``require_solver_proof=True``."""
    from superoptimization.capopt.candidates import SynthesisLevel
    from superoptimization.capopt.cost_model import CostModel
    from superoptimization.capopt.capability_model import CapabilityModel
    from superoptimization.capopt.mcmc import MCMCConfig, MCMCRunner

    cost = CostModel()
    cap = CapabilityModel()
    runner = MCMCRunner(
        SynthesisLevel.ASSEMBLY,
        "riscv64-cheri",
        cost,
        cap,
        MCMCConfig(max_steps=4, restarts=1, seed=0),
    )
    baseline = "cincoffset c1, c1, 16"
    baseline_state = runner._evaluate(baseline, cost.assembly_cost(baseline))
    better_state = runner._evaluate("cincoffsetimm c1, c1, 16")
    cand = runner._to_candidate(better_state, baseline_state, 0)

    assert "original_lines" in cand.metadata, (
        "D1 contract: MCMC candidate must carry original_lines so the "
        "AssemblyOptimizer solver path can dispatch the SMT verifier"
    )
    assert "replacement_blocks" in cand.metadata
    assert cand.metadata["original_lines"] == ["cincoffset c1, c1, 16"]
    assert cand.metadata["replacement_blocks"] == [["cincoffsetimm c1, c1, 16"]]


def test_d1_assembly_optimizer_runs_solver_on_mcmc_candidate():
    """D1 contract end-to-end: with the D1 metadata attached,
    ``AssemblyOptimizer._run_solver`` MUST NOT return
    ``reason="original_snippet_missing"`` for an MCMC candidate. The
    actual SMT verdict is irrelevant — the test only pins that the
    solver was *dispatchable* (i.e. D1 removed the dead-code blocker)."""
    from types import SimpleNamespace
    from superoptimization.capopt.assembly_optimizer import AssemblyOptimizer
    from superoptimization.capopt.candidates import SynthesisLevel
    from superoptimization.capopt.cost_model import CostModel
    from superoptimization.capopt.capability_model import CapabilityModel
    from superoptimization.capopt.mcmc import MCMCConfig, MCMCRunner

    cost = CostModel()
    cap = CapabilityModel()
    runner = MCMCRunner(
        SynthesisLevel.ASSEMBLY,
        "riscv64-cheri",
        cost,
        cap,
        MCMCConfig(max_steps=4, restarts=1, seed=0),
    )
    baseline = "cincoffset c1, c1, 16"
    baseline_state = runner._evaluate(baseline, cost.assembly_cost(baseline))
    better_state = runner._evaluate("cincoffsetimm c1, c1, 16")
    cand = runner._to_candidate(better_state, baseline_state, 0)

    opt_config = SimpleNamespace(
        target_arch="riscv64-cheri",
        enable_smt_synthesis=True,
        require_solver_proof=True,
        solver_timeout_ms=5000,
        weight_latency=1.0,
        weight_bounds=1.0,
        weight_permissions=1.0,
        weight_tag=0.5,
        enable_normalization_cache=False,
    )
    opt = AssemblyOptimizer(opt_config)
    if not opt._solver.is_available():
        pytest.skip("SMT verifier unavailable")
    result = opt._run_solver(cand, baseline.splitlines())
    assert result is not None
    assert result.reason != "original_snippet_missing", (
        "D1 contract violated: _run_solver still returns "
        "original_snippet_missing after MCMC attached the metadata"
    )


def test_d2_integer_store_then_load_forwards_through_symbol_pool(solver):
    """D2 regression: integer store-then-load at the same address MUST
    forward the stored value through the shared symbol pool so the
    subsequent same-key load returns the stored value rather than an
    opaque fresh symbol. This was already working for RV64I stores
    (``_handle_rv64i_store`` writes ``symbols[mem_key]``); D2 mirrors
    the axiom for the CHERI store dispatch path."""
    seq = solver._evaluate_sequence([
        "    sd x1, 0(x2)",
        "    ld x3, 0(x2)",
    ])
    assert seq.supported
    mem_symbol = seq.symbols.get("mem[x2+0]")
    assert mem_symbol is not None, (
        "D2 regression: integer store must record the stored value into "
        "the symbol pool (mem[x2+0]) so the subsequent load forwards it"
    )
    # The symbol pool entry must reflect the STORED value (derived from
    # x1), not a fresh ``mem[x2+0]`` opaque symbol.
    assert "x1" in str(mem_symbol.expr), (
        "D2 regression: stored value must be derived from the source "
        "operand (x1), not a fresh opaque memory symbol"
    )


def test_d3_ir_matcher_tolerates_blank_lines():
    """D3 — IR matchers skip blank lines while scanning for the next
    expected pattern op. The rewrite preserves the blank line at its
    original position."""
    from superoptimization.capopt.pgss import PGSSAlgorithm, CapabilityAliasGraph

    pm = PGSSAlgorithm.__new__(PGSSAlgorithm)
    graph = CapabilityAliasGraph()
    lines = [
        "%t1 = call i64 @llvm.cheri.cap.address.get(i8 addrspace(200)* %c)",
        "",
        "%t2 = add i64 %t1, 16",
        "%c2 = call i8 addrspace(200)* @llvm.cheri.cap.address.set(i8 addrspace(200)* %c, i64 %t2)",
    ]
    matches = list(pm._match_ir_cinc_offset(lines, graph))
    assert len(matches) == 1, (
        "D3 contract: a blank line between pattern ops must not block "
        "the match"
    )
    # Replacement preserves the blank line.
    assert "" in matches[0].replacement
    assert any("offset.increment" in line for line in matches[0].replacement)


def test_d3_ir_matcher_tolerates_non_target_label():
    """D3 — IR matchers skip label-only lines whose label is NOT a
    branch target. The label is preserved in the rewrite so a later
    branch cannot accidentally bypass the fused op."""
    from superoptimization.capopt.pgss import PGSSAlgorithm, CapabilityAliasGraph

    pm = PGSSAlgorithm.__new__(PGSSAlgorithm)
    graph = CapabilityAliasGraph()
    lines = [
        "%t1 = call i64 @llvm.cheri.cap.address.get(i8 addrspace(200)* %c)",
        "label1:",
        "%t2 = add i64 %t1, 16",
        "%c2 = call i8 addrspace(200)* @llvm.cheri.cap.address.set(i8 addrspace(200)* %c, i64 %t2)",
    ]
    matches = list(pm._match_ir_cinc_offset(lines, graph))
    assert len(matches) == 1, (
        "D3 contract: a non-target label between pattern ops must not "
        "block the match"
    )
    assert "label1:" in matches[0].replacement


def test_d3_ir_matcher_refuses_to_match_across_jump_target_label():
    """D3 conservative safety: when a label between pattern ops is the
    target of a branch elsewhere in the window, the rewrite MUST refuse
    to match — anything could jump in between the source-cap defs and
    the fused op. This is the soundness guard for the relaxation."""
    from superoptimization.capopt.pgss import PGSSAlgorithm, CapabilityAliasGraph

    pm = PGSSAlgorithm.__new__(PGSSAlgorithm)
    graph = CapabilityAliasGraph()
    lines = [
        "br label %label1",
        "%t1 = call i64 @llvm.cheri.cap.address.get(i8 addrspace(200)* %c)",
        "label1:",
        "%t2 = add i64 %t1, 16",
        "%c2 = call i8 addrspace(200)* @llvm.cheri.cap.address.set(i8 addrspace(200)* %c, i64 %t2)",
    ]
    matches = list(pm._match_ir_cinc_offset(lines, graph))
    assert matches == [], (
        "D3 soundness: a label that's the target of a branch elsewhere "
        "in the window must block the match"
    )


# ======================================================================
# Phase D / D4 — MCMC insert/delete moves
#
# STOKE-style length-changing moves expand the MCMC search beyond the
# original three (imm/opcode/swap), all of which preserve chain length.
# The DELETE move can discover length-reducing optima the existing
# moves cannot. The INSERT move is bounded to the stratum already
# present in the baseline so we don't, e.g., introduce S4 memory ops
# into a pure S0 inspection block (verifier cost explosion).
# ======================================================================


def test_d4_delete_move_discovers_canonical_redundant_op():
    """D4 — MCMC with ``p_delete > 0`` MUST discover the canonical
    length-reducing optimum: a baseline ``cmove c1, c2; cmove c1, c2``
    has a redundant second copy that pure imm/opcode/swap moves cannot
    eliminate. The delete move enables length reduction.

    Pinned post-condition: at least one candidate is strictly shorter
    than the baseline (proves the delete axis is reachable AND
    accepted by the cost model)."""
    from superoptimization.capopt.candidates import SynthesisLevel
    from superoptimization.capopt.cost_model import CostModel
    from superoptimization.capopt.capability_model import CapabilityModel
    from superoptimization.capopt.mcmc import MCMCConfig, MCMCRunner

    cost = CostModel()
    cap = CapabilityModel()
    baseline = "cmove c1, c2\ncmove c1, c2"
    config = MCMCConfig(
        max_steps=200, restarts=4, seed=42, p_delete=2.0, p_insert=0.5
    )
    runner = MCMCRunner(SynthesisLevel.ASSEMBLY, "riscv64-cheri", cost, cap, config)
    cands = runner.generate(baseline, cost.assembly_cost(baseline))
    shorter = [c for c in cands if c.code.count("\n") < baseline.count("\n")]
    assert shorter, (
        "D4 contract: MCMC with p_delete > 0 must discover at least one "
        "length-reducing rewrite of the canonical cmove/cmove baseline"
    )


def test_d4_insert_move_respects_stratum_bound():
    """D4 — the INSERT move samples from a stratum-bounded opcode pool,
    so an S0 baseline never gets an S4 memory op spliced in."""
    from superoptimization.capopt.candidates import SynthesisLevel
    from superoptimization.capopt.cost_model import CostModel
    from superoptimization.capopt.capability_model import CapabilityModel
    from superoptimization.capopt.mcmc import MCMCConfig, MCMCRunner

    cost = CostModel()
    cap = CapabilityModel()
    runner = MCMCRunner(
        SynthesisLevel.ASSEMBLY,
        "riscv64-cheri",
        cost,
        cap,
        MCMCConfig(seed=0, p_insert=1.0),
    )
    # Build a pure S0 baseline and gather insert sites.
    s0_lines = ["    cmove c1, c2"]
    sites = runner._collect_asm_insert_sites(s0_lines)
    assert sites, "expected at least one insert site for non-empty baseline"
    # Synthesise an insertion at site 0 and confirm it doesn't contain a
    # memory mnemonic (S4).
    for _ in range(16):
        inserted = runner._build_insertion(s0_lines, sites[0])
        if inserted is None:
            continue
        # Confirm no S4 memory op leaked into the insertion.
        s4_ops = {"clc", "csc", "cld", "csd", "clw", "csw"}
        body = inserted.strip().split(None, 1)[0].lower()
        assert body not in s4_ops, (
            f"D4 stratum-bound violated: S4 op {body!r} inserted into S0 baseline"
        )


def test_d4_insert_pool_omits_reserved_abi_caps():
    """D4 — synthesised insertions must not target reserved ABI cap
    registers (cra/csp/cgp/etc.). Reserved regs would corrupt linkage
    and explode the verifier's call-graph reasoning."""
    from superoptimization.capopt.candidates import SynthesisLevel
    from superoptimization.capopt.cost_model import CostModel
    from superoptimization.capopt.capability_model import CapabilityModel
    from superoptimization.capopt.mcmc import MCMCConfig, MCMCRunner

    cost = CostModel()
    cap = CapabilityModel()
    runner = MCMCRunner(
        SynthesisLevel.ASSEMBLY,
        "riscv64-cheri",
        cost,
        cap,
        MCMCConfig(seed=0, p_insert=1.0),
    )
    # Include reserved regs in the baseline; they MUST NOT enter the
    # in-scope cap pool.
    lines = ["    cmove c1, c5", "    cmove c1, csp", "    cmove c1, cra"]
    sites = runner._collect_asm_insert_sites(lines)
    assert sites
    in_scope = set(sites[0]["in_scope_caps"])
    forbidden = {"csp", "cra", "cgp", "ctp"} & in_scope
    assert not forbidden, (
        f"D4 reserved-cap contract: insertions must not target {forbidden}; "
        f"in-scope cap pool was {in_scope}"
    )


# ======================================================================
# Phase D / D5 — register-rename axis (alpha-equivalence in
# verify_candidate)
#
# Before D5 the verifier required the original and the replacement to
# write to the EXACT same set of output registers. D5 adds an
# alpha-rename layer: pass a partial ``rename_map`` of {repl_reg ->
# orig_reg} and the comparison treats the two sequences as equivalent
# under the renaming.
#
# The grammar_candidates dest-axis extension (varying dest over an
# ABI-safe register set) is SCOPED OUT in this commit — surface as
# DONE_WITH_CONCERNS in the status report. The ABI-safe register set
# is computed in CapabilitySMTVerifier.abi_safe_destinations() so the
# downstream extension is one-line away.
# ======================================================================


def test_d5_default_no_rename_map_preserves_legacy_behaviour(solver):
    """D5 — calling ``verify_candidate`` WITHOUT a ``rename_map`` (the
    default) MUST be byte-for-byte identical to the pre-D5 behaviour.
    The two-sequences-with-different-dests case must still be rejected
    as ``distinct_output_sets``."""
    result = solver.verify_candidate(
        ["    cmove c5, c10"],
        ["    cmove c6, c10"],
    )
    assert not result.proven
    assert result.reason == "distinct_output_sets"


def test_d5_alpha_rename_accepts_only_dest_difference(solver):
    """D5 — with a ``rename_map`` the verifier MUST accept two
    sequences that differ only by an output-register renaming."""
    result = solver.verify_candidate(
        ["    cmove c5, c10"],
        ["    cmove c6, c10"],
        rename_map={"c6": "c5"},
    )
    assert result.proven, (
        "D5 alpha-rename contract: cmove c5,c10 vs cmove c6,c10 with "
        f"rename {{'c6': 'c5'}} must prove; got reason={result.reason}"
    )


def test_d5_alpha_rename_rejects_non_injective_map(solver):
    """D5 — a non-injective rename map (two distinct repl regs mapping
    onto the same orig reg) MUST be rejected with a specific reason
    code, not silently miscoerced."""
    # The replacement writes to c6 AND c7; both map to c5 (non-injective).
    result = solver.verify_candidate(
        ["    cmove c5, c10", "    cmove c8, c10"],
        ["    cmove c6, c10", "    cmove c7, c10"],
        rename_map={"c6": "c5", "c7": "c5"},
    )
    assert not result.proven
    assert result.reason == "rename_map_not_injective", (
        f"D5 injectivity: expected reason='rename_map_not_injective', got "
        f"{result.reason}"
    )


def test_d5_infer_rename_map_no_change_returns_empty():
    """D5 — ``infer_rename_map`` returns ``{}`` when the two sequences
    write to the same destinations (no rename is needed; the empty map
    reduces to the legacy code path)."""
    from superoptimization.capopt.smt_isa_cheri_riscv import CapabilitySMTVerifier
    m = CapabilitySMTVerifier.infer_rename_map(
        ["    cmove c5, c10"],
        ["    cmove c5, c10"],
    )
    assert m == {}


def test_d5_infer_rename_map_one_to_one_renaming():
    """D5 — ``infer_rename_map`` pairs the i-th distinct dest in the
    replacement with the i-th distinct dest in the original (textual
    order). For a single-instruction difference this collapses to a
    one-entry map."""
    from superoptimization.capopt.smt_isa_cheri_riscv import CapabilitySMTVerifier
    m = CapabilitySMTVerifier.infer_rename_map(
        ["    cmove c5, c10"],
        ["    cmove c6, c10"],
    )
    assert m == {"c6": "c5"}


def test_d5_abi_safe_destinations_excludes_calling_convention_regs():
    """D5 — the published ABI-safe register set MUST NOT contain
    ``cra``/``csp``/``cgp``/``ctp`` or any of the callee-saved
    ``cs0``..``cs11``. (cs0 / cfp are the frame pointer; csp the stack
    pointer; cra the return address; cgp the global pointer; ctp the
    thread pointer.)"""
    from superoptimization.capopt.smt_isa_cheri_riscv import CapabilitySMTVerifier
    safe = CapabilitySMTVerifier.abi_safe_destinations()
    for reserved in ("cra", "csp", "cgp", "ctp", "cfp", "cs0"):
        assert reserved not in safe, (
            f"D5 ABI contract: {reserved} must not be in the renamable set"
        )
