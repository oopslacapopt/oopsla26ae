#!/usr/bin/env bash
# setup-qemu-image.sh — one-time, idempotent decompression of the packaged
# CheriBSD purecap guest disk inside the full-environment AE image.
set -euo pipefail

COMPRESSED="${CHERIBSD_IMAGE_ZST:-/opt/cheri/cheribsd-riscv64-purecap.img.zst}"
TARGET="${QEMU_CHERI_IMAGE:-/opt/cheri/cheribsd-riscv64-purecap.img}"

if [[ -f "$TARGET" ]]; then
    echo "guest image already present: $TARGET"
    exit 0
fi
if [[ ! -f "$COMPRESSED" ]]; then
    echo "no packaged guest image at $COMPRESSED" >&2
    echo "(this container is not the full-environment image; see README)" >&2
    exit 1
fi
echo "decompressing $COMPRESSED -> $TARGET (sparse)"
zstd -d -T0 --sparse "$COMPRESSED" -o "$TARGET"
ls -lh "$TARGET"
echo "done; QEMU_CHERI_IMAGE=$TARGET is ready"
