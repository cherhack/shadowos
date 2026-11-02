# Reproducible build

The build pins these upstream revisions:

- CachyOS-Live-ISO: `3215497d2e8c5fea90e185affcf973dfa2cf790b`
- DarkShadowShell: `ba082f2e206ce798cd1b415cfed33d10363ff37a`

GitHub Actions runs an Arch Linux container in privileged mode, resolves every
package against the current signed repositories, builds with `mkarchiso`, checks
El Torito metadata and boots the image under QEMU until systemd reaches the live
system target.

To build manually, use an up-to-date Arch/CachyOS host with at least 30 GiB free:

```bash
sudo pacman -Syu --needed git archiso cachyos-keyring mkinitcpio-archiso \
  squashfs-tools grub xorriso qemu-desktop shellcheck python rsync zstd \
  cachyos-calamares-next
sudo pacman-key --populate archlinux cachyos
./scripts/apply-overlay.sh "$PWD" /var/tmp/shadowos-cachyos-live-iso
cd /var/tmp/shadowos-cachyos-live-iso
./buildiso.sh -p desktop -v -w
```

The workflow splits release images into files below GitHub's per-asset limit.
Use `join-shadowos.ps1` on Windows or `join-shadowos.sh` on Linux, then compare
the result with `SHA256SUMS`.
