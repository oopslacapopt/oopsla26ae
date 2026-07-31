#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CONTAINER="${CAPOPT_AE_CONTAINER:-capopt-oopsla26-ae-runtime}"
CONTROLLER_SOCKET="$ROOT/ae-output/morello-controller.sock"
CONTROLLER_STATE_ROOT="${XDG_RUNTIME_DIR:-/tmp}"
CONTROLLER_STATE_DIR="$CONTROLLER_STATE_ROOT/capopt-oopsla26-ae-$(id -u)"
CONTROLLER_PID="$CONTROLLER_STATE_DIR/controller.pid"

if ! command -v docker >/dev/null 2>&1; then
    echo "Error: Docker is not installed or is not on PATH." >&2
    exit 1
fi

# Stop Jupyter first so it cannot submit a new hardware request during
# controller shutdown.
if docker container inspect "$CONTAINER" >/dev/null 2>&1; then
    echo "Stopping CapOpt AE runtime '$CONTAINER'..."
    docker stop "$CONTAINER" >/dev/null
    echo "Container stopped."
else
    echo "CapOpt AE runtime '$CONTAINER' is not running."
fi

if [[ -S "$CONTROLLER_SOCKET" ]]; then
    python3 "$ROOT/ae/morello/request.py" shutdown \
        --socket "$CONTROLLER_SOCKET" >/dev/null 2>&1 || true
    for _ in $(seq 1 30); do
        [[ ! -S "$CONTROLLER_SOCKET" ]] && break
        sleep 0.1
    done
fi

# PID state is host-only, never mounted into the notebook container. Validate
# the process command before using it as a fallback to a failed socket stop.
if [[ -f "$CONTROLLER_PID" && ! -L "$CONTROLLER_PID" ]]; then
    controller_pid="$(tr -cd '0-9' < "$CONTROLLER_PID")"
    if [[ -n "$controller_pid" ]] && kill -0 "$controller_pid" 2>/dev/null; then
        controller_args="$(ps -p "$controller_pid" -o args= 2>/dev/null || true)"
        if [[ "$controller_args" == *"$ROOT/ae/morello/controller.py"* ]]; then
            kill "$controller_pid"
        fi
    fi
fi

rm -f "$CONTROLLER_SOCKET"
if [[ -d "$CONTROLLER_STATE_DIR" && ! -L "$CONTROLLER_STATE_DIR" ]]; then
    rm -f "$CONTROLLER_PID"
fi
echo "Morello bridge stopped."
