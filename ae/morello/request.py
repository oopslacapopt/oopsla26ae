#!/usr/bin/env python3
"""Send one fixed request to the host-side Morello notebook controller."""

from __future__ import annotations

import argparse
import json
import socket
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_SOCKET = ROOT / "ae-output" / "morello-controller.sock"
MAX_RESPONSE_BYTES = 256 * 1024


def request(
    action: str,
    *,
    socket_path: Path = DEFAULT_SOCKET,
    board: str = "morello-1",
    iterations: int = 10,
    warmup: int = 1,
    timeout: float = 30 * 60,
) -> dict[str, Any]:
    message: dict[str, Any] = {"action": action}
    if action == "measure":
        message.update(
            {
                "board": board,
                "iterations": iterations,
                "warmup": warmup,
            }
        )
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
        client.settimeout(timeout)
        client.connect(str(socket_path))
        client.sendall((json.dumps(message) + "\n").encode())
        client.shutdown(socket.SHUT_WR)
        chunks: list[bytes] = []
        total = 0
        while True:
            chunk = client.recv(64 * 1024)
            if not chunk:
                break
            total += len(chunk)
            if total > MAX_RESPONSE_BYTES:
                raise RuntimeError("controller response exceeds 256 KiB")
            chunks.append(chunk)
    payload = b"".join(chunks)
    if not payload.endswith(b"\n") or payload.count(b"\n") != 1:
        raise RuntimeError("controller returned an invalid response frame")
    response = json.loads(payload)
    if not isinstance(response, dict):
        raise RuntimeError("controller returned a non-object response")
    return response


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("status", "measure", "shutdown"))
    parser.add_argument("--socket", type=Path, default=DEFAULT_SOCKET)
    parser.add_argument("--board", choices=("morello-1", "morello-2"), default="morello-1")
    parser.add_argument("--iterations", type=int, default=10)
    parser.add_argument("--warmup", type=int, default=1)
    args = parser.parse_args()
    try:
        response = request(
            args.action,
            socket_path=args.socket,
            board=args.board,
            iterations=args.iterations,
            warmup=args.warmup,
        )
    except (ConnectionError, OSError, RuntimeError, TimeoutError, ValueError) as exc:
        response = {"ok": False, "error": str(exc)}
    print(json.dumps(response, indent=2, sort_keys=True))
    return 0 if response.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
