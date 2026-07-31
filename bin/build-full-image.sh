#!/usr/bin/env bash
# build-full-image.sh — build both AE image flavors:
#   capopt-oopsla26-ae:latest   closed image (Dockerfile, no CHERI SDK)
#   capopt-oopsla26-ae:full     complete CHERI environment (Dockerfile.full)
#
# Usage:
#   bin/build-full-image.sh [--stage DIR] [--cheri-output DIR]
#                           [--with-morello] [--skip-slim]
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
STAGE="$(cd "$ROOT/.." && pwd)/cheri-stage"
STAGE_ARGS=()
SKIP_SLIM=0
while [[ $# -gt 0 ]]; do
    case "$1" in
        --stage) STAGE="$2"; shift 2 ;;
        --cheri-output) STAGE_ARGS+=(--cheri-output "$2"); shift 2 ;;
        --with-morello) STAGE_ARGS+=(--with-morello); shift ;;
        --skip-slim) SKIP_SLIM=1; shift ;;
        -h|--help) sed -n '2,9p' "$0"; exit 0 ;;
        *) echo "unknown flag: $1" >&2; exit 2 ;;
    esac
done

if [[ "$SKIP_SLIM" -eq 0 ]]; then
    echo "== building closed image capopt-oopsla26-ae:latest"
    docker build --tag capopt-oopsla26-ae:latest "$ROOT"
fi

echo "== staging CHERI context"
"$ROOT/bin/stage-cheri-context.sh" "$STAGE" "${STAGE_ARGS[@]+"${STAGE_ARGS[@]}"}"

echo "== building full image capopt-oopsla26-ae:full"
docker build \
    --file "$ROOT/Dockerfile.full" \
    --build-context cheri-stage="$STAGE" \
    --tag capopt-oopsla26-ae:full \
    "$ROOT"

echo "== done"
docker image ls capopt-oopsla26-ae
echo
echo "Run the notebook against the full image with:"
echo "  CAPOPT_AE_IMAGE=capopt-oopsla26-ae:full ./bin/start-notebook.sh"
