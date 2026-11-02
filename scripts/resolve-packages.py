#!/usr/bin/env python3
"""Resolve package manifests against the repositories configured for pacman."""

from __future__ import annotations

import argparse
import pathlib
import subprocess
import sys


def read_manifest(path: pathlib.Path) -> list[str]:
    result: list[str] = []
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.split("#", 1)[0].strip()
        if line and line not in result:
            result.append(line)
    return result


def available(name: str) -> bool:
    return subprocess.run(
        ["pacman", "-Si", name],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=False,
    ).returncode == 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--required", type=pathlib.Path, required=True)
    parser.add_argument("--optional", type=pathlib.Path, required=True)
    parser.add_argument("--output", type=pathlib.Path, required=True)
    args = parser.parse_args()

    required = read_manifest(args.required)
    optional = read_manifest(args.optional)
    missing_required = [name for name in required if not available(name)]
    if missing_required:
        print("Required packages missing from configured repositories:", file=sys.stderr)
        for name in missing_required:
            print(f"  - {name}", file=sys.stderr)
        return 1

    resolved_optional: list[str] = []
    for name in optional:
        if available(name):
            resolved_optional.append(name)
        else:
            print(f"Optional package unavailable, skipped: {name}")

    resolved = required + [name for name in resolved_optional if name not in required]
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text("".join(f"{name}\n" for name in resolved), encoding="utf-8")
    print(f"Resolved {len(required)} required and {len(resolved_optional)} optional packages.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
