#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
IMAGE="${CAPOPT_AE_IMAGE:-capopt-oopsla26-ae:latest}"
CONTAINER="${CAPOPT_AE_CONTAINER:-capopt-oopsla26-ae-runtime}"
PORT="${CAPOPT_AE_PORT:-8888}"
CONTROLLER_SOCKET="$ROOT/ae-output/morello-controller.sock"
CONTROLLER_STATE_ROOT="${XDG_RUNTIME_DIR:-/tmp}"
CONTROLLER_STATE_DIR="$CONTROLLER_STATE_ROOT/capopt-oopsla26-ae-$(id -u)"
CONTROLLER_PID="$CONTROLLER_STATE_DIR/controller.pid"
CONTROLLER_LOG="$CONTROLLER_STATE_DIR/controller.log"
NOTEBOOK_TEMPLATE_CONTAINER="/artifact/notebook/oopsla26-ae.ipynb"
NOTEBOOK_WORK_RELATIVE="ae-output/notebook/oopsla26-ae.ipynb"
NOTEBOOK_WORK_DIR_HOST="$ROOT/ae-output/notebook"
NOTEBOOK_WORK_HOST="$ROOT/$NOTEBOOK_WORK_RELATIVE"

if ! command -v docker >/dev/null 2>&1; then
    echo "Error: Docker is not installed or is not on PATH." >&2
    exit 1
fi

if ! docker info >/dev/null 2>&1; then
    echo "Error: the Docker daemon is not available." >&2
    exit 1
fi

if [[ "${CAPOPT_AE_REBUILD:-0}" == "1" ]] \
    || ! docker image inspect "$IMAGE" >/dev/null 2>&1; then
    echo "Building local AE image '$IMAGE'..."
    docker build --tag "$IMAGE" "$ROOT"
fi

mkdir -p "$ROOT/ae-output"
bridge_status="disabled (host Python 3 and OpenSSH are optional requirements)"

# The ordinary closed/offline lane needs only Docker. When host Python and
# OpenSSH are present, start a capability-limited bridge so a notebook cell
# can request the fixed Morello p01 experiment without receiving credentials.
if command -v python3 >/dev/null 2>&1 \
    && command -v ssh >/dev/null 2>&1 \
    && command -v scp >/dev/null 2>&1; then
    if [[ -L "$CONTROLLER_STATE_DIR" ]]; then
        echo "Warning: refusing symlinked controller state path." >&2
    else
        mkdir -p "$CONTROLLER_STATE_DIR"
        chmod 700 "$CONTROLLER_STATE_DIR"
        if [[ "$(stat -c %u "$CONTROLLER_STATE_DIR")" != "$(id -u)" ]]; then
            echo "Warning: controller state directory has the wrong owner." >&2
        else
            if ! python3 "$ROOT/ae/morello/request.py" status \
                --socket "$CONTROLLER_SOCKET" >/dev/null 2>&1; then
                if [[ -f "$CONTROLLER_PID" && ! -L "$CONTROLLER_PID" ]]; then
                    stale_pid="$(tr -cd '0-9' < "$CONTROLLER_PID")"
                    if [[ -n "$stale_pid" ]] && kill -0 "$stale_pid" 2>/dev/null; then
                        stale_args="$(ps -p "$stale_pid" -o args= 2>/dev/null || true)"
                        if [[ "$stale_args" == *"$ROOT/ae/morello/controller.py"* ]]; then
                            kill "$stale_pid"
                        fi
                    fi
                fi
                rm -f "$CONTROLLER_SOCKET" "$CONTROLLER_PID"
                echo "Starting host-side Morello notebook bridge..."
                nohup python3 "$ROOT/ae/morello/controller.py" \
                    --socket "$CONTROLLER_SOCKET" \
                    --pid-file "$CONTROLLER_PID" \
                    >"$CONTROLLER_LOG" 2>&1 &
                for _ in $(seq 1 50); do
                    if python3 "$ROOT/ae/morello/request.py" status \
                        --socket "$CONTROLLER_SOCKET" >/dev/null 2>&1; then
                        bridge_status="ready"
                        break
                    fi
                    sleep 0.1
                done
            else
                bridge_status="ready"
            fi
            if [[ "$bridge_status" != "ready" ]]; then
                echo "Warning: Morello bridge is unavailable; core notebook remains usable." >&2
                tail -20 "$CONTROLLER_LOG" >&2 2>/dev/null || true
            fi
        fi
    fi
fi

desired_image="$(docker image inspect "$IMAGE" --format '{{.Id}}')"
container_created=0
if docker container inspect "$CONTAINER" >/dev/null 2>&1; then
    running="$(docker container inspect "$CONTAINER" --format '{{.State.Running}}')"
    current_image="$(docker container inspect "$CONTAINER" --format '{{.Image}}')"
    if [[ "$running" == "true" && "$current_image" == "$desired_image" ]]; then
        echo "CapOpt AE runtime '$CONTAINER' is already running."
    elif [[ "$running" == "true" ]]; then
        echo "Error: runtime '$CONTAINER' uses an older image." >&2
        echo "Run ./stop-notebook.sh and then retry." >&2
        exit 1
    else
        docker rm "$CONTAINER" >/dev/null
    fi
fi

if ! docker container inspect "$CONTAINER" >/dev/null 2>&1; then
    echo "Starting named CapOpt AE runtime '$CONTAINER'..."
    docker run --detach --rm \
        --name "$CONTAINER" \
        --init \
        --pull=never \
        -p "127.0.0.1:${PORT}:8888" \
        -v "$ROOT/ae-output:/artifact/ae-output" \
        "$IMAGE" \
        python3 -m jupyter lab \
            --ip=0.0.0.0 \
            --port=8888 \
            --no-browser \
            --allow-root \
            --ServerApp.root_dir=/artifact \
            --IdentityProvider.token= \
            --PasswordIdentityProvider.hashed_password= >/dev/null
    container_created=1
fi

# Jupyter autosaves execution counts, outputs, and kernel metadata. Open a
# generated notebook under the excluded ae-output mount so those normal edits
# never change the checksummed template inside the image. Preserve the previous
# working notebook whenever a new container session is created.
if [[ -L "$NOTEBOOK_WORK_DIR_HOST" || -L "$NOTEBOOK_WORK_HOST" ]]; then
    echo "Error: refusing a symlinked notebook working path." >&2
    exit 1
fi
mkdir -p "$NOTEBOOK_WORK_DIR_HOST"
if [[ "$container_created" == "1" && -f "$NOTEBOOK_WORK_HOST" ]]; then
    notebook_history="$ROOT/ae-output/notebook-history"
    mkdir -p "$notebook_history"
    notebook_archive="$notebook_history/oopsla26-ae-$(date -u +%Y%m%dT%H%M%SZ)-$$.ipynb"
    mv "$NOTEBOOK_WORK_HOST" "$notebook_archive"
    echo "Archived previous notebook session: ${notebook_archive#$ROOT/}"
fi
if [[ ! -f "$NOTEBOOK_WORK_HOST" ]]; then
    notebook_seed="$NOTEBOOK_WORK_HOST.new-$$"
    docker cp "$CONTAINER:$NOTEBOOK_TEMPLATE_CONTAINER" "$notebook_seed"
    mv "$notebook_seed" "$NOTEBOOK_WORK_HOST"
fi

ready=0
for _ in $(seq 1 30); do
    if docker exec "$CONTAINER" python3 -c \
        "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8888/lab', timeout=1)" \
        >/dev/null 2>&1; then
        ready=1
        break
    fi
    sleep 1
done

if [[ "$ready" != "1" ]]; then
    echo "Error: Jupyter did not become ready; recent logs:" >&2
    docker logs --tail 40 "$CONTAINER" >&2
    exit 1
fi

if [[ "$bridge_status" == "ready" ]] \
    && ! docker exec "$CONTAINER" python3 ae/morello/request.py status \
        >/dev/null 2>&1; then
    bridge_status="unavailable inside this Docker filesystem"
fi

echo "CapOpt AE notebook (writable session copy):"
echo "  http://127.0.0.1:${PORT}/lab/tree/${NOTEBOOK_WORK_RELATIVE}"
echo "Checksummed template: notebook/oopsla26-ae.ipynb"
echo "Python environment: /opt/capopt-venv"
echo "Authentication: disabled (localhost only)"
echo "Runtime container: $CONTAINER"
echo "Morello bridge: $bridge_status"
echo
echo "Open the notebook and run its cells; no experiment command is required in another terminal."
echo
echo "Stop the runtime:"
echo "  ./stop-notebook.sh"
