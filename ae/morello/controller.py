#!/usr/bin/env python3
"""Host-side fixed-command bridge for notebook-triggered Morello runs.

The Jupyter container sees only this Unix socket through the existing
``ae-output`` bind mount.  SSH and its credentials stay in this host process.
No request field is ever interpreted as a shell command.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import signal
import socketserver
import subprocess
import sys
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
COLLECTOR = ROOT / "ae" / "morello" / "collect.py"
OUTPUT = ROOT / "ae-output" / "morello"
MAX_REQUEST_BYTES = 4096
MEASUREMENT_LOCK = threading.Lock()
MEASUREMENT_PARAMETERS: tuple[str, int, int] | None = None
MEASUREMENT_RESPONSE: dict[str, Any] | None = None


def _response(ok: bool, **values: Any) -> bytes:
    return (json.dumps({"ok": ok, **values}, sort_keys=True) + "\n").encode()


def _validate_measure_request(request: dict[str, Any]) -> tuple[str, int, int]:
    board = request.get("board", "morello-1")
    iterations = request.get("iterations", 10)
    warmup = request.get("warmup", 1)
    if board not in {"morello-1", "morello-2"}:
        raise ValueError("board must be morello-1 or morello-2")
    if type(iterations) is not int or iterations != 10:
        raise ValueError("the notebook bridge accepts exactly 10 measured pairs")
    if type(warmup) is not int or warmup != 1:
        raise ValueError("the notebook bridge accepts exactly one warmup pair")
    return board, iterations, warmup


def _json_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    """Reject duplicate fields instead of accepting the final value."""
    value: dict[str, Any] = {}
    for key, item in pairs:
        if key in value:
            raise ValueError(f"duplicate request field: {key}")
        value[key] = item
    return value


def _reject_unknown(request: dict[str, Any], allowed: set[str]) -> None:
    unknown = sorted(set(request) - allowed)
    if unknown:
        raise ValueError("unsupported request field(s): " + ", ".join(unknown))


class Controller(socketserver.ThreadingUnixStreamServer):
    daemon_threads = True
    allow_reuse_address = False

    def __init__(self, socket_path: str, pid_file: Path):
        self.pid_file = pid_file
        super().__init__(socket_path, RequestHandler)


class RequestHandler(socketserver.StreamRequestHandler):
    def handle(self) -> None:
        global MEASUREMENT_PARAMETERS, MEASUREMENT_RESPONSE
        self.connection.settimeout(5)
        try:
            raw = self.rfile.readline(MAX_REQUEST_BYTES + 1)
            if not raw:
                return
            if len(raw) > MAX_REQUEST_BYTES or not raw.endswith(b"\n"):
                raise ValueError(
                    "request must be one newline-terminated JSON frame "
                    "of at most 4096 bytes"
                )
            if self.rfile.read(1):
                raise ValueError("only one request frame is accepted per connection")
            request = json.loads(raw, object_pairs_hook=_json_object)
            if not isinstance(request, dict):
                raise ValueError("request must be a JSON object")
            action = request.get("action")
            if action == "status":
                _reject_unknown(request, {"action"})
                self.wfile.write(
                    _response(
                        True,
                        status="ready",
                        measurement_active=MEASUREMENT_LOCK.locked(),
                        measurement_complete=MEASUREMENT_RESPONSE is not None,
                    )
                )
                return
            if action == "shutdown":
                _reject_unknown(request, {"action"})
                self.wfile.write(_response(True, status="stopping"))
                threading.Thread(
                    target=self.server.shutdown,
                    name="controller-shutdown",
                    daemon=True,
                ).start()
                return
            if action != "measure":
                raise ValueError("action must be status, measure, or shutdown")

            _reject_unknown(
                request, {"action", "board", "iterations", "warmup"}
            )
            board, iterations, warmup = _validate_measure_request(request)
            parameters = (board, iterations, warmup)
            if MEASUREMENT_RESPONSE is not None:
                if MEASUREMENT_PARAMETERS != parameters:
                    self.wfile.write(
                        _response(
                            False,
                            error=(
                                "this controller session already completed a "
                                "different measurement; restart it to change boards"
                            ),
                        )
                    )
                else:
                    self.wfile.write(_response(True, **MEASUREMENT_RESPONSE))
                return
            if not MEASUREMENT_LOCK.acquire(blocking=False):
                self.wfile.write(
                    _response(False, error="another Morello measurement is active")
                )
                return
            try:
                stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
                run_id = f"p01-notebook-{stamp}-{os.getpid()}-{threading.get_ident()}"
                if not re.fullmatch(r"[A-Za-z0-9._-]+", run_id):
                    raise RuntimeError("internal run-id validation failed")
                relative = f"ae-output/morello/{run_id}"
                command = [
                    sys.executable,
                    str(COLLECTOR),
                    "--board",
                    board,
                    "--iterations",
                    str(iterations),
                    "--warmup",
                    str(warmup),
                    "--run-dir",
                    relative,
                ]
                completed = subprocess.run(
                    command,
                    cwd=ROOT,
                    text=True,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    timeout=30 * 60,
                    check=False,
                )
                if completed.returncode:
                    self.wfile.write(
                        _response(
                            False,
                            error="Morello collection failed",
                            returncode=completed.returncode,
                            output=completed.stdout[-4000:],
                        )
                    )
                    return
                MEASUREMENT_PARAMETERS = parameters
                MEASUREMENT_RESPONSE = {
                    "status": "collected",
                    "board": board,
                    "iterations": iterations,
                    "warmup": warmup,
                    "run_dir": relative,
                    "output": completed.stdout[-16_000:],
                }
                self.wfile.write(_response(True, **MEASUREMENT_RESPONSE))
            finally:
                MEASUREMENT_LOCK.release()
        except (
            json.JSONDecodeError,
            OSError,
            subprocess.SubprocessError,
            TypeError,
            UnicodeDecodeError,
            ValueError,
        ) as exc:
            self.wfile.write(_response(False, error=str(exc)))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--socket", type=Path, required=True)
    parser.add_argument("--pid-file", type=Path, required=True)
    args = parser.parse_args()

    expected_parent = ROOT / "ae-output"
    if expected_parent.is_symlink():
        parser.error("ae-output must not be a symbolic link")
    try:
        output_stat = expected_parent.stat()
    except OSError as exc:
        parser.error(f"cannot inspect ae-output: {exc}")
    if not expected_parent.is_dir() or output_stat.st_uid != os.getuid():
        parser.error("ae-output must be a directory owned by this user")

    socket_path = Path(os.path.abspath(args.socket))
    expected_parent = Path(os.path.abspath(expected_parent))
    if socket_path.parent != expected_parent:
        parser.error("socket must be directly under ae-output")
    if socket_path.is_symlink():
        parser.error("controller socket path must not be a symbolic link")

    pid_file = Path(os.path.abspath(args.pid_file))
    if pid_file.is_symlink():
        parser.error("PID file must not be a symbolic link")
    state_dir = pid_file.parent
    try:
        state_stat = state_dir.stat()
    except OSError as exc:
        parser.error(f"cannot inspect host-only state directory: {exc}")
    if state_stat.st_uid != os.getuid() or state_stat.st_mode & 0o077:
        parser.error("host-only state directory must be owned by this user and mode 0700")

    os.umask(0o077)
    if socket_path.exists() and not socket_path.is_socket():
        parser.error("controller socket path exists and is not a socket")
    if socket_path.is_socket():
        socket_path.unlink()
    if pid_file.exists():
        parser.error("PID file already exists")

    server = Controller(str(socket_path), pid_file)
    socket_path.chmod(0o600)
    pid_file.write_text(f"{os.getpid()}\n")

    def stop(_signum: int, _frame: object) -> None:
        threading.Thread(target=server.shutdown, daemon=True).start()

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    try:
        print(f"Morello notebook controller ready: {socket_path}", flush=True)
        server.serve_forever(poll_interval=0.2)
    finally:
        server.server_close()
        socket_path.unlink(missing_ok=True)
        pid_file.unlink(missing_ok=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
