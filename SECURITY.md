# Security model

## Installer

The live launcher runs `os-prober`, identifies physical disks that contain a
Windows installation and marks those disks read-only for the current live
session. This is an additional guard, not a substitute for checking the disk
model, serial number and size in Calamares. Disconnecting the Windows disk is
still the strongest protection.

The installer never automatically chooses or erases a target disk. Destructive
partitioning remains an explicit Calamares action confirmed by the user.

## Shadow AI

The API model has no shell and no root access. It can return only a small JSON
action schema. The local client validates every field, shows the plan and asks
for confirmation. Package operations additionally require polkit.

Supported changes are limited to DarkShadowShell visual profiles, diagnostics,
package installation, Flatpak installation and system updates. Arbitrary shell
commands and package removal are deliberately unsupported.

API credentials are created after installation and stored in
`~/.config/shadow-ai/config.json` with mode `0600`. They are never included in
the ISO. Only HTTPS endpoints are accepted, except localhost development APIs.

## Windows executables

Opening an EXE or MSI shows its SHA-256 hash and asks for confirmation the first
time that exact file is seen. Each application is launched in a separate Wine
prefix. Wine is not a security sandbox; untrusted Windows programs should not be
run at all.
