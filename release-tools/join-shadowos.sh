#!/usr/bin/env bash
set -Eeuo pipefail

mapfile -t parts < <(find . -maxdepth 1 -type f -name '*.iso.part-*' -printf '%f\n' | sort)
if ((${#parts[@]} == 0)); then
    echo "No *.iso.part-* files found in the current directory." >&2
    exit 1
fi

output="${parts[0]%.part-*}"
echo "Joining ${#parts[@]} parts into $output ..."
cat "${parts[@]}" > "$output"

if [[ -f SHA256SUMS ]]; then
    sha256sum -c SHA256SUMS
else
    echo "SHA256SUMS is missing; calculate and compare the ISO checksum manually." >&2
fi

echo "Ready: $output"
