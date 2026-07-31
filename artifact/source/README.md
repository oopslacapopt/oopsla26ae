# CapOpt — A Capability-Aware Superoptimizer for CHERI

CapOpt is a two-level (LLVM IR + assembly) superoptimizer for CHERI-enabled architectures (Arm Morello and CHERI-RISC-V). It discovers rewrites that recover performance lost to CHERI's pointer-as-capability semantics, and accepts a rewrite only when a Z3 SMT verifier proves it capability-aware equivalent: functionally equal, never wider in authority (bounds, permissions, otype), and tag/provenance preserving.

## How it works

- **Two-level pipeline** (`capopt/core.py`, `CapOptOptimizer`): an IR phase
(textual LLVM IR with `@llvm.cheri.cap.*` intrinsics, verified by the
Alive2-style refinement checker in `capopt/smt_llvmir.py`) followed by an
assembly phase (assembly-text rewriting verified by the per-ISA CHERI
verifiers), run to a greedy fixpoint.
- **PGSS search** (`capopt/pgss.py` — Provenance-Guided Stratified
Synthesis): candidates are organized into five semantic strata S0–S4,
drawn from a verified pattern library, SMT-guided enumeration, and MCMC
stochastic search, and pruned by a provenance alias DAG
(`capopt/alias_dag.py`) before any solver query. The paper's
escalate-on-failure stratum discipline is the default
(`CAPOPT_STRATUM_ESCALATION=explore_all` restores the pre-v4 one-pool
search for A/B comparison).
- **Pre-SMT concrete screening** (`capopt/assembly_optimizer.py` +
`screen_candidate` in the ISA verifiers): every assembly candidate is
first executed against the original on shared concrete input vectors
(remembered SMT counterexamples, corner cases, PRNG samples — evaluated
by substitution/constant-folding, no solver instance); any observable
divergence rejects the candidate before Z3 is consulted.  Reject-only:
survivors still require the full SMT proof.  Knobs:
`CAPOPT_CONCRETE_SCREEN=off|on` (default on; also
`OptimizationConfig.enable_concrete_screen`) and
`CAPOPT_CONCRETE_SCREEN_VECTORS=<n>` random vectors (default 16).
- **Verification**: capability-aware equivalence discharged by Z3 with a
normalization-keyed verdict cache; the hand-written CHERI-RISC-V
semantics are cross-validated against the official CHERI Sail model via
Isla (47 mnemonics mechanically proven equivalent; gaps honestly
cataloged); an optional Alive2 cross-check covers capability-free IR
rewrites. All verification is fail-closed.
- **Cost model** (`capopt/cost_model.py`): security-aware static cost
(latency + bounds + permissions + tag terms) with optional dynamic
re-ranking from median-of-runs measurements (QEMU retired-instruction
counts for CHERI-RISC-V; `pmcstat`/perf cycle counts on Morello).
- **Implementation**: a Python package with an optional pybind11 C++
backend (`capopt/_native/`) for hot cost/parsing kernels, with a
pure-Python fallback.

See `[docs/capopt-design.md](docs/capopt-design.md)` for the full
architecture and `[docs/verifier-soundness.md](docs/verifier-soundness.md)`
for the soundness model and audit history.

## Repository layout

```
cheri-superoptimization/
├── superoptimization/
│   ├── capopt/                  # the Python package (see capopt/README.md)
│   │   └── _native/             # optional pybind11 C++ backend
│   └── pyproject.toml           # package metadata; entry point: capopt
├── scripts/                     # experiment drivers, campaign + claim tooling
├── benchmarks/
│   ├── hacker/                  # 25 Hacker's Delight kernels (p01..p25)
│   ├── spec-cpu2017-1.1.0/      # SPEC CPU2017 sources (12-benchmark paper set)
│   ├── llama.cpp/               # ML inference benchmark
│   └── scripts/                 # build_*_benchmarks.py (see its README)
├── configs/                     # toolchain pins, paper_claims.json, pattern stores
├── docs/                        # documentation (index below)
├── tests/                       # pytest suite
├── ptrint-harness/              # pointer-vs-integer motivation harness
└── results*/                    # measurement campaigns (dated runs)
```



## Prerequisites

- **Python 3.11+**; the package pulls in `z3-solver`, NumPy, NetworkX, etc.
- Optional **C++ backend**: a C++17 compiler plus pybind11
(`pip install -e .[native]`), then
`python3 superoptimization/capopt/_native/build_native.py`. Without it
the pure-Python fallback is used transparently.
- For experiments: **CHERI-LLVM** (pinned to 17.0.0 @ `9e82d2969a6`, see
`configs/toolchain.env`), **QEMU-CHERI** (full-system CheriBSD purecap
image) for CHERI-RISC-V, and ssh access to an **Arm Morello board** for
the hardware column. Toolchains build via
`[cheribuild](https://github.com/CTSRD-CHERI/cheribuild)`:

```bash
LIBOMP_USE_QUAD_PRECISION=OFF ./cheribuild.py --include-dependencies run-riscv64-purecap -d
```



## Quick start

```bash
cd superoptimization
pip install -e .                 # registers the `capopt` console script
# optional C++ backend:
pip install -e .[native] && python3 capopt/_native/build_native.py

cd ..
python3 -m pytest tests/ -q      # full suite should pass

capopt --input path/to/program.ll --function foo \
       --arch riscv64-cheri --evaluate --report report.json
```



## Benchmarks

The paper evaluates three suites:

- **25 Hacker's Delight kernels** (`benchmarks/hacker/p01`–`p25`).
- **12 SPEC CPU2017 benchmarks**: 510.parest_r, 519.lbm_r, 520.omnetpp_r,
523.xalancbmk_r, 531.deepsjeng_r, 541.leela_r, 544.nab_r, 557.xz_r,
620.omnetpp_s, 623.xalancbmk_s, 631.deepsjeng_s, 641.leela_s.
- **LLaMA.cpp** inference.

Baselines are −O0 and −O3 purecap builds; the measurement protocol is 10  
runs, median. Build entry points are in `benchmarks/scripts/` (see  
`[benchmarks/scripts/README.md](benchmarks/scripts/README.md)`).

