# CapOpt OOPSLA 2026 Artifact

[DOI](https://doi.org/10.5281/zenodo.21715188)

This repository is the Artifact Evaluation (AE) package for **CapOpt:**  
**Capability-Aware Superoptimization for Secure and Provably Faster Code**.  
The archival deposit is published on Zenodo:  
[doi:10.5281/zenodo.21715188](https://doi.org/10.5281/zenodo.21715188). It contains the pinned CapOpt optimizer (see below), the redistributable benchmark inputs, recorded experimental evidence, and an interactive Jupyter notebook.



## Kick the tires

Requirements: Docker 24 or newer, an x86-64 or Arm64 Linux host, 4 GB RAM,
and approximately 5 GB of free disk space. No CHERI hardware, CHERI SDK, or
SPEC license is needed for this lane.

```bash
docker build -t capopt-oopsla26-ae .
docker run --rm capopt-oopsla26-ae
```

Expected result: the environment and closure checks, an SMT-proven
permission-restriction rewrite, the bounded p01 search/paper-data recomputation,
and the fast regression tests all finish with
`KICK-THE-TIRES: PASS`. This lane is designed to finish in under ten minutes
on a laptop.

## Interactive notebook

The notebook is the primary reviewer interface. Run:

```bash
./start-notebook.sh
```

If `capopt-oopsla26-ae:latest` is not present locally, the launcher builds it
from this directory before starting Jupyter. Set `CAPOPT_AE_REBUILD=1` to
force a rebuild after changing the artifact, or `CAPOPT_AE_IMAGE` to use a
different local image tag.

Open the URL printed by the launcher (normally  
`http://127.0.0.1:8888/lab/tree/ae-output/notebook/oopsla26-ae.ipynb`), then run the cells from top to bottom. If optional Morello access is unavailable, that cell reports a skip and the Docker-only results continue. The launcher binds the published port to host loopback (`127.0.0.1`) only.

## Non-interactive evaluation

All notebook actions have command-line equivalents:

```bash
# Fast functionality check (under 10 minutes)
docker run --rm capopt-oopsla26-ae

# Run the bounded fresh p01/search and recorded-evidence reproduction
docker run --rm capopt-oopsla26-ae \
  python3 ae/runner.py reproduce-short

# Inspect every paper claim against shipped evidence
docker run --rm capopt-oopsla26-ae \
  python3 ae/runner.py claims

# Freshly recompute the C4–C7 evidence by launching the repository's own
# analysis scripts on the shipped raw data (all claims, or one of C4..C7)
docker run --rm capopt-oopsla26-ae \
  python3 ae/runner.py recompute --claim all

# Run the longer hardware-independent regression lane
docker run --rm capopt-oopsla26-ae \
  python3 ae/runner.py tests --full

# Release gate: fails on failed, blocked, or pending claims
docker run --rm capopt-oopsla26-ae \
  python3 ae/runner.py release-check
```

The claims report is also written to `ae-output/claims-report.json` when that
directory is writable. A `PASS` means the value was recomputed from shipped
raw or structured data. `PENDING` means the final campaign data have not yet
been imported. 

The `recompute` command stages the shipped raw evidence under
`ae-output/recompute/` and launches `scripts/classify_rewrites.py` (C4),
`scripts/gen_pruning_stats.py` per ablation config (C5), and
`scripts/souper_comparison.py summarize` (C6) on it, and freshly re-derives
the C7 measurement aggregate from the 50 raw Morello result files. Each fresh
result is compared field by field with the shipped summary and written to
`ae-output/recompute/c{4,5,6,7}.json`. C7's zero-rewrite fields come from
build sidecars that are not vendored, so they are audited from the recorded
run and labeled as such rather than recomputed.


## Licenses and availability

The AE wrapper is distributed under the
[Unlicense](LICENSE). The vendored CapOpt code — both the open source under
`artifact/source` and the compiled core under `artifact/lib` — retains its
[MIT license](artifact/source/LICENSE), and third-party components retain
their own licenses. SPEC CPU2017 is not redistributed. 
