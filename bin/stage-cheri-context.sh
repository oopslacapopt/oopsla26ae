#!/usr/bin/env bash
# stage-cheri-context.sh — prepare the CHERI build context for the
# full-environment AE image (Dockerfile.full).
set -euo pipefail

STAGE_DEFAULT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)/cheri-stage"
if [[ $# -gt 0 && "$1" != --* ]]; then
    STAGE="$1"
    shift
else
    STAGE="$STAGE_DEFAULT"
fi

CHERI_OUTPUT="${HOME}/cheri/output"
WITH_MORELLO=0
while [[ $# -gt 0 ]]; do
    case "$1" in
        --cheri-output) CHERI_OUTPUT="$2"; shift 2 ;;
        --with-morello) WITH_MORELLO=1; shift ;;
        -h|--help) sed -n '2,18p' "$0"; exit 0 ;;
        *) echo "unknown flag: $1" >&2; exit 2 ;;
    esac
done

SDK="$CHERI_OUTPUT/sdk"
ROOTFS="$CHERI_OUTPUT/rootfs-riscv64-purecap"
DISK="$CHERI_OUTPUT/cheribsd-riscv64-purecap.img"
for path in "$SDK/bin/clang" "$SDK/bin/qemu-system-riscv64cheri" \
            "$SDK/bbl/riscv64-purecap/bbl" \
            "$SDK/sysroot-riscv64-purecap" \
            "$ROOTFS/boot/kernel/kernel" "$DISK"; do
    [[ -e "$path" ]] || { echo "missing: $path (build it with cheribuild first)" >&2; exit 1; }
done

echo "== staging CHERI context to $STAGE"
mkdir -p "$STAGE"

echo "-- sdk/ (CHERI-LLVM + sysroot + QEMU + bbl)"
rsync -a --delete "$SDK/" "$STAGE/sdk/"

echo "-- kernel/ (CheriBSD purecap boot kernel)"
rsync -a --delete "$ROOTFS/boot/kernel/" "$STAGE/kernel/"

echo "-- cheribsd-riscv64-purecap.img.zst (sparse-aware zstd)"
if [[ ! -f "$STAGE/cheribsd-riscv64-purecap.img.zst" ]] \
        || [[ "$DISK" -nt "$STAGE/cheribsd-riscv64-purecap.img.zst" ]]; then
    zstd -T0 -3 --sparse --force "$DISK" -o "$STAGE/cheribsd-riscv64-purecap.img.zst"
else
    echo "   up to date, skipping"
fi

if [[ "$WITH_MORELLO" -eq 1 ]]; then
    echo "-- morello-sdk/ (optional Morello cross toolchain)"
    rsync -a --delete "$CHERI_OUTPUT/morello-sdk/" "$STAGE/morello-sdk/"
fi

du -sh "$STAGE"/* | sed 's/^/   /'
echo "== stage complete: $STAGE"
