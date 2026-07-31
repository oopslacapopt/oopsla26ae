#!/usr/bin/env bash
# publish-notebook.sh — project a locally running AE notebook session onto a
# rented machine with a public IP, via an SSH reverse tunnel.
#
#   1. Start the session locally WITH a token (public exposure without
#      authentication is refused):
#        CAPOPT_AE_TOKEN=$(python3 -c 'import secrets;print(secrets.token_urlsafe(24))') \
#            ./bin/start-notebook.sh
#   2. Publish it:
#        ./bin/publish-notebook.sh USER@PUBLIC_HOST [PUBLIC_PORT]
#
# The tunnel runs in the foreground (Ctrl-C to unpublish). PUBLIC_PORT
# defaults to 8888. For the public host to accept connections on all
# interfaces, its sshd must have `GatewayPorts yes` (or `clientspecified`)
# in /etc/ssh/sshd_config; otherwise the forward binds to the remote
# loopback only and this script tells you.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PORT="${CAPOPT_AE_PORT:-8888}"
CONTROLLER_STATE_ROOT="${XDG_RUNTIME_DIR:-/tmp}"
CONTROLLER_STATE_DIR="$CONTROLLER_STATE_ROOT/capopt-oopsla26-ae-$(id -u)"
TOKEN_FILE="$CONTROLLER_STATE_DIR/jupyter.token"

if [[ $# -lt 1 || $# -gt 2 ]]; then
    sed -n '2,17p' "$0" >&2
    exit 2
fi
TARGET="$1"
PUBLIC_PORT="${2:-8888}"

if ! command -v ssh >/dev/null 2>&1; then
    echo "Error: OpenSSH client is required." >&2
    exit 1
fi

# The local session must be up.
if ! python3 - "$PORT" <<'PYEOF'
import sys, urllib.request
try:
    urllib.request.urlopen(f"http://127.0.0.1:{sys.argv[1]}/lab", timeout=3)
except Exception:
    raise SystemExit(1)
PYEOF
then
    echo "Error: no notebook session on 127.0.0.1:$PORT." >&2
    echo "Start one first: ./bin/start-notebook.sh" >&2
    exit 1
fi

# Refuse to publish an unauthenticated session: the tunnel would expose an
# arbitrary-code-execution Jupyter to the whole internet.
TOKEN=""
[[ -f "$TOKEN_FILE" && ! -L "$TOKEN_FILE" ]] && TOKEN="$(cat "$TOKEN_FILE")"
if [[ -z "$TOKEN" ]]; then
    echo "Error: the running session has no authentication token." >&2
    echo "Restart it with a token before publishing:" >&2
    echo "  ./bin/stop-notebook.sh" >&2
    echo "  CAPOPT_AE_TOKEN=\$(python3 -c 'import secrets;print(secrets.token_urlsafe(24))') \\" >&2
    echo "      ./bin/start-notebook.sh" >&2
    exit 1
fi

PUBLIC_HOST="${TARGET##*@}"
echo "Publishing local notebook (127.0.0.1:$PORT) to $PUBLIC_HOST:$PUBLIC_PORT ..."
echo
echo "Reviewer URL:"
echo "  http://${PUBLIC_HOST}:${PUBLIC_PORT}/lab/tree/oopsla26-ae.ipynb?token=${TOKEN}"
echo
echo "If the URL is unreachable from outside, set 'GatewayPorts yes' in the"
echo "public host's /etc/ssh/sshd_config, restart sshd, and rerun this script."
echo "The tunnel stays in the foreground; press Ctrl-C to unpublish."
echo

exec ssh -N \
    -o ExitOnForwardFailure=yes \
    -o ServerAliveInterval=30 \
    -o ServerAliveCountMax=3 \
    -R "0.0.0.0:${PUBLIC_PORT}:127.0.0.1:${PORT}" \
    "$TARGET"
