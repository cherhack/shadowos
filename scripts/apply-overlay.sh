#!/usr/bin/env bash
set -Eeuo pipefail

if [[ $# -ne 2 ]]; then
    echo "usage: apply-overlay.sh PROJECT_ROOT CACHYOS_DESTINATION" >&2
    exit 2
fi

project_root="$(realpath "$1")"
destination="$(realpath -m "$2")"
cachyos_commit="3215497d2e8c5fea90e185affcf973dfa2cf790b"
darkshadow_commit="ba082f2e206ce798cd1b415cfed33d10363ff37a"

if [[ -e "$destination" ]]; then
    echo "Refusing to overwrite existing destination: $destination" >&2
    exit 1
fi

git clone --filter=blob:none https://github.com/CachyOS/CachyOS-Live-ISO.git "$destination"
git -C "$destination" checkout --detach "$cachyos_commit"

airootfs="$destination/archiso/airootfs"
darkshadow="$airootfs/opt/shadowos/DarkShadowShell"
mkdir -p "$(dirname "$darkshadow")"
git clone --filter=blob:none https://github.com/shadowww-dev/DarkShadowShell.git "$darkshadow"
git -C "$darkshadow" checkout --detach "$darkshadow_commit"
rm -rf "$darkshadow/.git"

resolved="$destination/shadowos-target-packages.x86_64"
python "$project_root/scripts/resolve-packages.py" \
    --required "$project_root/config/packages-required.txt" \
    --optional "$project_root/config/packages-optional.txt" \
    --output "$resolved"

live_resolved="$destination/shadowos-live-packages.x86_64"
python "$project_root/scripts/resolve-packages.py" \
    --required "$project_root/config/packages-live.txt" \
    --optional "$project_root/config/packages-live-optional.txt" \
    --output "$live_resolved"

package_list="$destination/archiso/packages_desktop.x86_64"
grep -vxFf "$project_root/config/packages-remove-live.txt" "$package_list" > "$package_list.tmp"
cat "$live_resolved" >> "$package_list.tmp"
LC_ALL=C sort -u "$package_list.tmp" > "$package_list"
rm "$package_list.tmp"

python "$project_root/scripts/patch-calamares.py" --airootfs "$airootfs" --packages "$resolved"

cp -a "$project_root/payload/rootfs/." "$airootfs/"
cp -a "$project_root/live-rootfs/." "$airootfs/"
mkdir -p "$airootfs/opt/shadowos/payload/rootfs"
cp -a "$project_root/payload/rootfs/." "$airootfs/opt/shadowos/payload/rootfs/"
cp -a "$project_root/LICENSES/." "$airootfs/opt/shadowos/licenses/"

python "$project_root/scripts/make-assets.py" \
    --rootfs "$airootfs" \
    --iso-grub "$destination/archiso/grub"

# Generated boot assets are needed in the installed system as well as in the
# live filesystem. They are generated after the static payload is copied.
mkdir -p "$airootfs/opt/shadowos/payload/rootfs/usr/share/grub/themes"
cp -a "$airootfs/usr/share/grub/themes/shadowos" \
    "$airootfs/opt/shadowos/payload/rootfs/usr/share/grub/themes/"
install -Dm0644 "$airootfs/usr/share/calamares/branding/shadowos/icon.png" \
    "$airootfs/opt/shadowos/payload/rootfs/usr/share/pixmaps/shadowos.png"

# Keep an immutable copy of the installer configuration. The launcher restores
# it immediately before Calamares starts, so a keyring refresh cannot replace it.
mkdir -p "$airootfs/opt/shadowos/calamares/etc" "$airootfs/opt/shadowos/calamares/usr-share"
cp -a "$airootfs/etc/calamares/." "$airootfs/opt/shadowos/calamares/etc/"
cp -a "$airootfs/usr/share/calamares/settings_online.conf" \
    "$airootfs/opt/shadowos/calamares/usr-share/settings_online.conf"
cp -a "$airootfs/usr/share/calamares/branding/shadowos" \
    "$airootfs/opt/shadowos/calamares/usr-share/"

# Enable the live preparation service and SDDM while preserving real symlinks.
mkdir -p "$airootfs/etc/systemd/system/graphical.target.wants"
ln -sfn /usr/lib/systemd/system/shadowos-live-prepare.service \
    "$airootfs/etc/systemd/system/graphical.target.wants/shadowos-live-prepare.service"
ln -sfn /usr/lib/systemd/system/sddm.service \
    "$airootfs/etc/systemd/system/display-manager.service"

chmod +x \
    "$airootfs/usr/local/bin/shadow-ai" \
    "$airootfs/usr/local/bin/shadowos-exe" \
    "$airootfs/usr/local/bin/shadowos-gaming-mode" \
    "$airootfs/usr/local/bin/shadowos-installer" \
    "$airootfs/usr/local/lib/shadowos/deploy-user" \
    "$airootfs/usr/local/lib/shadowos/firstboot" \
    "$airootfs/usr/local/lib/shadowos/install-target" \
    "$airootfs/usr/local/lib/shadowos/live-prepare"

# Brand the build without pretending to be an official CachyOS image.
sed -i \
    -e 's/^iso_name=.*/iso_name="shadowos"/' \
    -e 's/^iso_label=.*/iso_label="SHADOW_$(date --date="@${SOURCE_DATE_EPOCH:-$(date +%s)}" +%Y%m)"/' \
    -e 's|^iso_publisher=.*|iso_publisher="ShadowOS community build (based on CachyOS)"|' \
    -e 's|^iso_application=.*|iso_application="ShadowOS Live/Installer"|' \
    "$destination/archiso/profiledef.sh"

sed -i \
    -e 's/Welcome to CachyOS/Welcome to ShadowOS/' \
    -e 's/menuentry "CachyOS"/menuentry "ShadowOS Live"/' \
    -e 's/menuentry "CachyOS LTS Kernel"/menuentry "ShadowOS Live (LTS kernel)"/' \
    -e 's/CachyOS Legacy Hardware/ShadowOS fallback graphics/' \
    -e 's/timeout=10/timeout=5/' \
    -e 's/ nvme_load=yes/ nvme_load=yes console=tty0 console=ttyS0,115200/' \
    "$destination/archiso/grub/grub.cfg"

sed -i \
    -e 's/CachyOS/ShadowOS/g' \
    -e 's/ nvme_load=yes/ nvme_load=yes console=tty0 console=ttyS0,115200/' \
    "$destination/archiso/syslinux/archiso_sys-linux.cfg"

# Add a simple image to the live GRUB menu. Installed systems use the full theme.
python - "$destination/archiso/grub/grub.cfg" <<'PY'
from pathlib import Path
import sys

p = Path(sys.argv[1])
s = p.read_text()
needle = "# Enable serial console\n"
block = (
    "# ShadowOS live background\n"
    "insmod png\n"
    "if background_image \"${prefix}/splash.png\"; then\n"
    "    set color_normal=white/black\n"
    "    set color_highlight=white/magenta\n"
    "fi\n\n"
)
if block not in s:
    s = s.replace(needle, block + needle, 1)
p.write_text(s)
PY

printf '%s\n' "$cachyos_commit" > "$airootfs/opt/shadowos/CACHYOS_COMMIT"
printf '%s\n' "$darkshadow_commit" > "$airootfs/opt/shadowos/DARKSHADOWSHELL_COMMIT"
cp "$resolved" "$airootfs/opt/shadowos/INSTALLED_PACKAGES"
cp "$live_resolved" "$airootfs/opt/shadowos/LIVE_PACKAGES"

echo "ShadowOS overlay prepared in $destination"
