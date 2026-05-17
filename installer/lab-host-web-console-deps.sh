#!/usr/bin/env bash
# Optional lab-host packages for Windows VM browser console (noVNC + websockify).
# QEMU/KVM keeps VNC on 127.0.0.1; xdr-lab-vm-manager.sh web-console runs websockify.
#
# Usage (root): installer/lab-host-web-console-deps.sh
# shellcheck shell=bash
set -euo pipefail

if [[ "${EUID}" -ne 0 ]]; then
  echo "Run as root (apt/dnf need elevated privileges)." >&2
  exit 1
fi

if command -v apt-get >/dev/null 2>&1; then
  export DEBIAN_FRONTEND=noninteractive
  apt-get update -y
  apt-get install -y novnc websockify socat
elif command -v dnf >/dev/null 2>&1; then
  dnf install -y novnc python3-websockify socat || dnf install -y novnc websockify socat
elif command -v yum >/dev/null 2>&1; then
  yum install -y novnc python3-websockify socat || yum install -y novnc websockify socat
else
  echo "No supported package manager (apt-get, dnf, yum)." >&2
  exit 1
fi

echo "Installed noVNC + websockify (+ socat for legacy VNC proxy)."
