#!/usr/bin/env bash
set -Eeuo pipefail

if [[ $# -ne 2 ]]; then
    echo "usage: smoke-test.sh IMAGE.iso SERIAL_LOG" >&2
    exit 2
fi

iso="$1"
log="$2"
rm -f "$log"

timeout 300 qemu-system-x86_64 \
    -machine accel=tcg,usb=off \
    -cpu max \
    -smp 2 \
    -m 3072 \
    -boot once=d \
    -cdrom "$iso" \
    -device virtio-vga \
    -nic user,model=virtio-net-pci \
    -display none \
    -serial "file:$log" \
    -no-reboot &
qemu_pid=$!

cleanup() {
    kill "$qemu_pid" 2>/dev/null || true
    wait "$qemu_pid" 2>/dev/null || true
}
trap cleanup EXIT

for _ in $(seq 1 150); do
    if grep -Eq 'Reached target (Graphical Interface|Multi-User System)|Started Simple Desktop Display Manager|ShadowOS login:' "$log" 2>/dev/null; then
        echo "QEMU smoke test reached the installed live system target."
        exit 0
    fi
    if ! kill -0 "$qemu_pid" 2>/dev/null; then
        break
    fi
    sleep 2
done

echo "QEMU did not reach the expected target. Last serial lines:" >&2
tail -n 120 "$log" >&2 || true
exit 1
