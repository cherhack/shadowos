#!/usr/bin/env python3
"""Create a ShadowOS-specific Calamares configuration from the installed CachyOS one."""

from __future__ import annotations

import argparse
import pathlib
import re
import shutil


def package_block(packages: list[str]) -> str:
    package_lines = "".join(f"    - {name}\n" for name in packages)
    return (
        '- name: "Hyprland"\n'
        '  description: "ShadowOS desktop with Hyprland, DarkShadowShell and the gaming stack."\n'
        '  description[ru]: "Рабочий стол ShadowOS: Hyprland, DarkShadowShell и игровой набор программ."\n'
        '  platform: "desktop"\n'
        '  hidden: false\n'
        '  selected: true\n'
        '  expanded: true\n'
        '  critical: true\n'
        '  packages:\n'
        f"{package_lines}"
    )


def patch_settings(text: str) -> str:
    text = text.replace("branding: cachyos", "branding: shadowos")
    text = re.sub(r"(?m)^\s+- packagechooser@desktop\s*\n", "", text)
    if "id:       shadowos-copy" not in text:
        marker = "\nsequence:\n"
        instances = (
            "\n- id:       shadowos-copy\n"
            "  module:   shellprocess\n"
            "  config:   shellprocess_shadowos_copy.conf\n"
            "\n- id:       shadowos-setup\n"
            "  module:   shellprocess\n"
            "  config:   shellprocess_shadowos_setup.conf\n"
        )
        if marker not in text:
            raise RuntimeError("Could not locate Calamares sequence marker")
        text = text.replace(marker, instances + marker, 1)
    text = text.replace(
        "  - packages@online\n",
        "  - packages@online\n  - shellprocess@shadowos-copy\n",
        1,
    )
    text = text.replace(
        "  - shellprocess\n",
        "  - shellprocess\n  - shellprocess@shadowos-setup\n",
        1,
    )
    return text


def patch_branding(source: pathlib.Path, destination: pathlib.Path) -> None:
    shutil.copytree(source, destination, dirs_exist_ok=True)
    desc = destination / "branding.desc"
    text = desc.read_text(encoding="utf-8")
    replacements = {
        "componentName:  cachyos": "componentName:  shadowos",
        "productName:         CachyOS": "productName:         ShadowOS",
        "shortProductName:    CachyOS": "shortProductName:    ShadowOS",
        "versionedName:       CachyOS": "versionedName:       ShadowOS",
        "shortVersionedName:  CachyOS": "shortVersionedName:  ShadowOS",
        "bootloaderEntryName: CachyOS": "bootloaderEntryName: ShadowOS",
        'slideshow:               "show.qml"': 'slideshow: [ "welcome.png" ]',
        '"#292F34"': '"#202020"',
        '"#00CED1"': '"#A0A0A0"',
    }
    for old, new in replacements.items():
        text = text.replace(old, new)
    desc.write_text(text, encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--airootfs", type=pathlib.Path, required=True)
    parser.add_argument("--packages", type=pathlib.Path, required=True)
    parser.add_argument("--modules-source", type=pathlib.Path, default=pathlib.Path("/etc/calamares/modules"))
    parser.add_argument(
        "--settings-source",
        type=pathlib.Path,
        default=pathlib.Path("/usr/share/calamares/settings_online.conf"),
    )
    parser.add_argument(
        "--branding-source",
        type=pathlib.Path,
        default=pathlib.Path("/usr/share/calamares/branding/cachyos"),
    )
    args = parser.parse_args()

    modules_source = args.modules_source
    settings_source = args.settings_source
    branding_source = args.branding_source
    if not modules_source.is_dir() or not settings_source.is_file():
        raise RuntimeError("cachyos-calamares-next must be installed before patching")

    modules_destination = args.airootfs / "etc/calamares/modules"
    modules_destination.mkdir(parents=True, exist_ok=True)
    shutil.copytree(modules_source, modules_destination, dirs_exist_ok=True)

    packages = [
        line.strip()
        for line in args.packages.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    netinstall = modules_destination / "netinstall.yaml"
    text = netinstall.read_text(encoding="utf-8")
    # The personalized target uses one current CachyOS kernel. Keeping the LTS
    # kernel in the live image still provides a hardware fallback, while the
    # installed GRUB menu stays limited to ShadowOS and Windows.
    text = text.replace("     - linux-cachyos-lts\n", "")
    text = text.replace("     - linux-cachyos-lts-headers\n", "")
    pattern = re.compile(r'^- name: "Hyprland"\n.*?(?=^- name: |\Z)', re.M | re.S)
    text, count = pattern.subn(package_block(packages), text, count=1)
    if count != 1:
        raise RuntimeError("Could not replace the Hyprland netinstall package group")
    netinstall.write_text(text, encoding="utf-8")

    partition = modules_destination / "partition.conf"
    partition_text = partition.read_text(encoding="utf-8")
    partition_text = partition_text.replace("efiSystemPartitionSize:     2048M", "efiSystemPartitionSize:     1024M", 1)
    partition_text = partition_text.replace("efiSystemPartitionSize: 512M", "efiSystemPartitionSize: 1024M", 1)
    partition.write_text(partition_text, encoding="utf-8")

    (modules_destination / "packagechooser_desktop.conf").write_text(
        """---
mode: required
method: netinstall-select
labels:
    step: "ShadowOS Desktop"
    step[ru]: "Рабочий стол ShadowOS"
default: Hyprland
items:
    - id: Hyprland
      name: "ShadowOS Desktop"
      name[ru]: "Рабочий стол ShadowOS"
      description: "Hyprland with the original DarkShadowShell visual shell."
      description[ru]: "Hyprland с оригинальной визуальной оболочкой DarkShadowShell."
      screenshot: "/etc/calamares/images/hyprland.webp"
""",
        encoding="utf-8",
    )
    (modules_destination / "packagechooser_bootloader.conf").write_text(
        """---
mode: required
method: legacy
labels:
    step: "Bootloader"
    step[ru]: "Загрузчик"
default: grub
items:
    - id: grub
      name: "GRUB"
      platform: "desktop"
      description: "Standard GRUB boot manager with the minimal ShadowOS theme."
      description[ru]: "Стандартный GRUB с минималистичной темой ShadowOS."
      screenshot: "/etc/calamares/images/bootloaders/grub.jxl"
""",
        encoding="utf-8",
    )

    settings_destination = args.airootfs / "usr/share/calamares/settings_online.conf"
    settings_destination.parent.mkdir(parents=True, exist_ok=True)
    settings_destination.write_text(
        patch_settings(settings_source.read_text(encoding="utf-8")),
        encoding="utf-8",
    )
    patch_branding(
        branding_source,
        args.airootfs / "usr/share/calamares/branding/shadowos",
    )


if __name__ == "__main__":
    main()
