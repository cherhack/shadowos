#!/usr/bin/env python3
"""Fail the CI build early when the generated live-root overlay is incomplete."""

from __future__ import annotations

import argparse
import json
import os
import pathlib

import yaml


def require(root: pathlib.Path, relative: str) -> pathlib.Path:
    path = root / relative
    if not path.exists():
        raise AssertionError(f"missing overlay path: {relative}")
    return path


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("airootfs", type=pathlib.Path)
    args = parser.parse_args()
    root = args.airootfs.resolve()

    settings_path = require(root, "usr/share/calamares/settings_online.conf")
    netinstall_path = require(root, "etc/calamares/modules/netinstall.yaml")
    partition_path = require(root, "etc/calamares/modules/partition.conf")
    branding_path = require(root, "usr/share/calamares/branding/shadowos/branding.desc")
    for path in (settings_path, netinstall_path, partition_path, branding_path):
        yaml.safe_load(path.read_text(encoding="utf-8"))

    settings = settings_path.read_text(encoding="utf-8")
    assert "shellprocess@shadowos-copy" in settings
    assert "shellprocess@shadowos-setup" in settings
    assert "branding: shadowos" in settings
    assert "packagechooser@desktop" not in settings

    netinstall = netinstall_path.read_text(encoding="utf-8")
    assert 'description: "ShadowOS desktop' in netinstall
    assert "linux-cachyos-lts" not in netinstall
    for package in ("hyprland", "quickshell", "steam", "wine", "gamemode", "zram-generator"):
        assert f"    - {package}\n" in netinstall, f"target package missing: {package}"

    partition = partition_path.read_text(encoding="utf-8")
    assert 'defaultFileSystemType:  "btrfs"' in partition
    assert "efiSystemPartitionSize: 1024M" in partition

    for relative in (
        "etc/calamares/modules/shellprocess_shadowos_copy.conf",
        "etc/calamares/modules/shellprocess_shadowos_setup.conf",
        "opt/shadowos/DarkShadowShell/install.sh",
        "opt/shadowos/payload/rootfs/usr/share/grub/themes/shadowos/theme.txt",
        "usr/share/grub/themes/shadowos/theme.txt",
        "usr/share/calamares/branding/shadowos/icon.png",
        "usr/share/calamares/branding/shadowos/welcome.png",
        "usr/local/lib/shadowos/shadow_ai.py",
        "usr/local/bin/shadowos-installer",
        "usr/local/bin/shadowos-exe",
    ):
        require(root, relative)

    for relative in (
        "usr/local/bin/shadow-ai",
        "usr/local/bin/shadowos-exe",
        "usr/local/bin/shadowos-gaming-mode",
        "usr/local/bin/shadowos-installer",
        "usr/local/lib/shadowos/deploy-user",
        "usr/local/lib/shadowos/install-target",
        "usr/local/lib/shadowos/live-prepare",
    ):
        path = require(root, relative)
        assert os.access(path, os.X_OK), f"not executable: {relative}"

    for relative in (
        "usr/share/shadowos/defaults/rice/desktop.json",
        "usr/share/shadowos/defaults/rice/effects.json",
        "usr/share/shadowos/defaults/waybar-ui.json",
    ):
        json.loads(require(root, relative).read_text(encoding="utf-8"))

    assert require(root, "opt/shadowos/CACHYOS_COMMIT").read_text().strip() == (
        "3215497d2e8c5fea90e185affcf973dfa2cf790b"
    )
    assert require(root, "opt/shadowos/DARKSHADOWSHELL_COMMIT").read_text().strip() == (
        "ba082f2e206ce798cd1b415cfed33d10363ff37a"
    )
    print("Generated ShadowOS overlay validation passed")


if __name__ == "__main__":
    main()
