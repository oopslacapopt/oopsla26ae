#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
CONTAINER="${CAPOPT_AE_CONTAINER:-capopt-oopsla26-ae-runtime}"
BOARD="morello-1"
ITERATIONS=10
WARMUP=1

usage() {
    echo "Usage: $0 [--board morello-1|morello-2] [--iterations N] [--warmup N]"
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --board) BOARD="$2"; shift 2 ;;
        --iterations) ITERATIONS="$2"; shift 2 ;;
        --warmup) WARMUP="$2"; shift 2 ;;
        -h|--help) usage; exit 0 ;;
        *) echo "Unknown option: $1" >&2; usage >&2; exit 2 ;;
    esac
done

case "$BOARD" in
    morello-1|morello-2) ;;
    *) echo "Error: --board must be morello-1 or morello-2." >&2; exit 2 ;;
esac

if ! docker container inspect "$CONTAINER" >/dev/null 2>&1 \
    || [[ "$(docker container inspect "$CONTAINER" --format '{{.State.Running}}')" != "true" ]]; then
    echo "Error: AE runtime '$CONTAINER' is not running." >&2
    echo "Start it first with ./bin/start-notebook.sh" >&2
    exit 1
fi

run_id="p01-$(date -u +%Y%m%dT%H%M%SZ)-$$"
relative="ae-output/morello/$run_id"

echo "Collecting on $BOARD with host OpenSSH; credentials never enter Jupyter."
python3 "$ROOT/ae/morello/collect.py" \
    --board "$BOARD" \
    --iterations "$ITERATIONS" \
    --warmup "$WARMUP" \
    --run-dir "$relative"

echo
echo "Validating the credential-free result inside the AE container."
docker exec --workdir /artifact "$CONTAINER" \
    python3 ae/runner.py morello-report --run-dir "$relative"

echo
echo "Completed: $relative/report.json"
