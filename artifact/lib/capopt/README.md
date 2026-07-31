# capopt — package overview

CapOpt's implementation: a two-level (LLVM IR + assembly) capability-aware
superoptimizer for CHERI targets. Architecture documentation lives in
[`docs/capopt-design.md`](../../docs/capopt-design.md); this README is a
module map.

## Quick start

```bash
cd superoptimization
uv sync                       # or: pip install -e .
uv run pytest ../tests/ -q    # run the test suite
```

Optional C++ backend (`capopt._native._kernels` — hot kernels for assembly
parsing/canonicalization/instruction counting, used by `cost_model.py` and
`dynamic_cost.py`; pure-Python fallback in `_native/_fallback.py`):

```bash
pip install -e .[native]      # provides pybind11
python3 capopt/_native/build_native.py
```

Parity between the backend and the fallback is enforced by
`tests/test_native_backend.py`.

## Module map

| Module | Purpose |
|--------|---------|
| `core.py` | `CapOptOptimizer` + `OptimizationConfig` — two-level orchestration, fixpoint loop, splice-back |
| `pgss.py` | PGSS search engine: strata S0–S4, pattern dispatch, candidate merging |
| `llvm_optimizer.py` / `ir_superoptimizer.py` | IR phase: window extraction and Souper-style IR rewriting |
| `assembly_optimizer.py` | assembly phase: candidate selection, solver dispatch, assembler-parse gate |
| `stoke_integration.py` | `DualPhaseOptimizer` — SMT enumeration + MCMC combination, dynamic re-ranking |
| `smt_llvmir.py` | IR-level Z3 verifier (`LLVMSMTVerifier`): refinement encoding, CHERI intrinsics, memory events |
| `smt_cheri.py` | `CheriContext` — hand-written CHERI-RISC-V semantics (CHERI Concentrate B/T/E model) |
| `smt_isa_cheri_riscv.py` | asm-level verifier (`CapabilitySMTVerifier`) + `SMTGuidedEnumerator`; RV64I/M/A/F/D/Q/H, CSRs |
| `smt_isa_cheri_arm.py` | Morello/CHERI-AArch64 asm verifier |
| `smt_isa_riscv.py` / `smt_isa_arm.py` | non-CHERI baseline verifiers |
| `capability_model.py` | capability-equivalence predicates (bounds/perms/provenance) |
| `correspondence.py` | derivation-aware correspondence mapping 𝓜 (off/warn/strict) |
| `alias_dag.py` | provenance alias DAG + `ProvenanceAliasPruner` |
| `cost_model.py` | security-aware static cost (`CostVector`, `CostWeights`, per-ISA latency tables) |
| `dynamic_cost.py` | dynamic measurement backends (QEMU icount, Morello pmcstat/ssh), SQLite cache |
| `cache.py` | `NormalizationService` — cost caches + normalization-keyed solver verdict cache |
| `pattern_library.py` | builtin + learned rewrite patterns (`scripts/capopt_learn.py` writes stores) |
| `mcmc.py` / `beam.py` / `sketch.py` | stochastic and enumerative candidate generators |
| `alive2_crosscheck.py` | optional Alive2 differential cross-check (off by default) |
| `sail/` | Sail/Isla cross-validation harness + opcode catalog |
| `_native/` | optional pybind11 C++ backend |
| `cli.py` / `reporting.py` / `evaluation.py` | CLI entry point, results schema, measurement protocol |

## Capability-aware equivalence

A rewrite R of original S is accepted only when all three conditions are
SMT-proven (fail-closed; `require_solver_proof=True` by default):

1. **Functional equivalence** — identical observable outputs and memory
   events for all inputs (Alive2-style refinement at the IR level).
2. **Capability-metadata restriction** — `bounds(R) ⊆ bounds(S)`,
   `perms(R) ⊆ perms(S)`, equal otype/seal state.
3. **Tag/provenance validity** — `tag(S) == tag(R)` plus
   derivation-consistent output pairing.

Soundness model, flag defaults, and the audit history are in
[`docs/verifier-soundness.md`](../../docs/verifier-soundness.md).
