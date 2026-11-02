#!/usr/bin/env python3
"""Generate small, reproducible PNG assets without external Python modules."""

from __future__ import annotations

import argparse
import binascii
import math
import pathlib
import struct
import zlib

RGBA = tuple[int, int, int, int]


def chunk(kind: bytes, data: bytes) -> bytes:
    return (
        struct.pack(">I", len(data))
        + kind
        + data
        + struct.pack(">I", binascii.crc32(kind + data) & 0xFFFFFFFF)
    )


def write_png(path: pathlib.Path, width: int, height: int, pixels) -> None:
    raw = bytearray()
    for y in range(height):
        raw.append(0)
        for x in range(width):
            raw.extend(bytes(max(0, min(255, int(v))) for v in pixels(x, y)))
    payload = (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(bytes(raw), 9))
        + chunk(b"IEND", b"")
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(payload)


def background_pixel(width: int, height: int):
    def pixel(x: int, y: int) -> RGBA:
        t = y / max(1, height - 1)
        value = 7 + 12 * t
        r = g = b = value

        # Soft graphite/silver glows without a colored accent.
        d1 = math.hypot((x - width * 0.25) / width, (y - height * 0.85) / height)
        d2 = math.hypot((x - width * 0.82) / width, (y - height * 0.18) / height)
        p = max(0.0, 1.0 - d1 * 3.2) ** 2
        c = max(0.0, 1.0 - d2 * 4.0) ** 2
        glow = 48 * p + 28 * c
        r += glow
        g += glow
        b += glow

        # Sparse deterministic stars; no random state means reproducible builds.
        h = (x * 73856093) ^ (y * 19349663)
        if (h & 0xFFFFF) < 85 and y < height * 0.78:
            glow = 105 + (h % 120)
            r = g = b = glow
        return int(r), int(g), int(b), 255

    return pixel


def rounded_rect(width: int, height: int, radius: int, color: RGBA):
    def pixel(x: int, y: int) -> RGBA:
        cx = min(max(x, radius), width - radius - 1)
        cy = min(max(y, radius), height - radius - 1)
        inside = (x - cx) ** 2 + (y - cy) ** 2 <= radius**2
        return color if inside else (0, 0, 0, 0)

    return pixel


def crop_pixel(source, offset_x: int, offset_y: int):
    return lambda x, y: source(x + offset_x, y + offset_y)


def write_nine_patch(directory: pathlib.Path, prefix: str, color: RGBA) -> None:
    tile = 24
    whole = tile * 3
    source = rounded_rect(whole, whole, 20, color)
    names = [
        ("nw", 0, 0),
        ("n", tile, 0),
        ("ne", tile * 2, 0),
        ("w", 0, tile),
        ("c", tile, tile),
        ("e", tile * 2, tile),
        ("sw", 0, tile * 2),
        ("s", tile, tile * 2),
        ("se", tile * 2, tile * 2),
    ]
    for suffix, ox, oy in names:
        write_png(directory / f"{prefix}_{suffix}.png", tile, tile, crop_pixel(source, ox, oy))


def logo_pixel(size: int):
    def pixel(x: int, y: int) -> RGBA:
        cx = cy = size / 2
        outer = math.hypot(x - cx, y - cy) <= size * 0.34
        cut = math.hypot(x - (cx + size * 0.14), y - (cy - size * 0.07)) <= size * 0.29
        if outer and not cut:
            t = y / size
            shade = int(222 - 76 * t)
            return shade, shade, shade, 255
        # A small silver star at the opening of the crescent.
        sx, sy = size * 0.65, size * 0.38
        if abs(x - sx) + abs(y - sy) < size * 0.055:
            return 210, 210, 210, 255
        return 0, 0, 0, 0

    return pixel


def welcome_pixel(width: int, height: int):
    bg = background_pixel(width, height)
    logo = logo_pixel(height)

    def pixel(x: int, y: int) -> RGBA:
        base = bg(x, y)
        lx = x - (width - height) // 2
        if 0 <= lx < height:
            mark = logo(lx, y)
            if mark[3]:
                return mark
        return base

    return pixel


def write_theme(theme_dir: pathlib.Path) -> None:
    write_png(theme_dir / "background.png", 1920, 1080, background_pixel(1920, 1080))
    write_nine_patch(theme_dir, "menu", (14, 14, 16, 224))
    write_nine_patch(theme_dir, "select", (92, 98, 108, 220))
    (theme_dir / "theme.txt").write_text(
        """# ShadowOS minimal GRUB theme
desktop-image: "background.png"
desktop-color: "#080808"
title-text: ""
message-font: "Unifont Regular 16"
message-color: "#A0A0A0"
message-bg-color: "#00000000"

+ label {
    top = 14%
    left = 0
    width = 100%
    align = "center"
    text = "SHADOWOS"
    color = "#F2F2F2"
    font = "Unifont Regular 32"
}

+ label {
    top = 20%
    left = 0
    width = 100%
    align = "center"
    text = "CachyOS gaming workstation"
    color = "#B9BEC7"
    font = "Unifont Regular 14"
}

+ boot_menu {
    left = 28%
    top = 31%
    width = 44%
    height = 36%
    menu_pixmap_style = "menu_*.png"
    item_font = "Unifont Regular 18"
    item_color = "#C8C8C8"
    selected_item_color = "#FFFFFF"
    selected_item_pixmap_style = "select_*.png"
    item_height = 48
    item_padding = 18
    item_spacing = 8
    icon_width = 0
    icon_height = 0
    scrollbar = false
}

+ progress_bar {
    id = "__timeout__"
    left = 38%
    top = 74%
    width = 24%
    height = 6
    show_text = false
    fg_color = "#A8AEB8"
    bg_color = "#303030"
    border_color = "#00000000"
}

+ label {
    top = 79%
    left = 0
    width = 100%
    align = "center"
    text = "UP / DOWN to select    ENTER to boot"
    color = "#8C8C8C"
    font = "Unifont Regular 13"
}
""",
        encoding="utf-8",
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--rootfs", type=pathlib.Path, required=True)
    parser.add_argument("--iso-grub", type=pathlib.Path, required=True)
    args = parser.parse_args()

    theme_dir = args.rootfs / "usr/share/grub/themes/shadowos"
    write_theme(theme_dir)
    branding = args.rootfs / "usr/share/calamares/branding/shadowos"
    write_png(branding / "icon.png", 256, 256, logo_pixel(256))
    write_png(branding / "logo.png", 256, 256, logo_pixel(256))
    write_png(branding / "welcome.png", 640, 240, welcome_pixel(640, 240))
    write_png(args.iso_grub / "splash.png", 1920, 1080, background_pixel(1920, 1080))


if __name__ == "__main__":
    main()
