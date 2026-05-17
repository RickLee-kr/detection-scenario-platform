# shellcheck shell=bash
# xdr-lab-appliance — Centralized path/environment definitions.
#
# Source this file from any repository script to obtain stable paths and
# environment variables. Do NOT execute directly.
#
#   . "$(cd "$(dirname "${BASH_SOURCE[0]}")"/../config && pwd)/paths.sh"
#
# All variables are overridable from the caller's environment (export
# before sourcing). PROJECT_ROOT may be overridden when developing
# against a non-canonical checkout location.

# --- Project root (override via XDR_LAB_PROJECT_ROOT if needed) -------
: "${XDR_LAB_PROJECT_ROOT:=/home/aella/xdr-lab-appliance}"
PROJECT_ROOT="${XDR_LAB_PROJECT_ROOT}"

# --- Repository sub-directories --------------------------------------
CONFIG_DIR="${PROJECT_ROOT}/config"
IMAGE_DIR="${PROJECT_ROOT}/images"
SCRIPT_DIR="${PROJECT_ROOT}/scripts"
SCENARIO_DIR="${PROJECT_ROOT}/scenarios"
LOG_DIR="${PROJECT_ROOT}/logs"
CLOUDINIT_DIR="${PROJECT_ROOT}/cloud-init"
TEMPLATE_DIR="${PROJECT_ROOT}/templates"
INSTALLER_DIR="${PROJECT_ROOT}/installer"
APPLIANCE_DIR="${PROJECT_ROOT}/appliance"
DOCS_DIR="${PROJECT_ROOT}/docs"
TESTS_DIR="${PROJECT_ROOT}/tests"
BACKUPS_DIR="${PROJECT_ROOT}/backups"

# --- Runtime install target (cli-installer.sh / xdr-lab-vm-manager.sh)
# These mirror the production layout under /opt/xdr-lab. They are NOT
# the repo paths; they are the target paths after `cli-installer.sh`
# has installed assets. Override via XDR_BASE / XDR_ROOT to relocate
# (e.g. for rootless lab environments).
: "${XDR_BASE:=/opt/xdr-lab}"
: "${XDR_ROOT:=${XDR_BASE}}"

# --- Installed lab tree (mirrors cli-installer.sh layout) ------------
: "${XDR_LAB_VMS_JSON:=${XDR_ROOT}/config/lab-vms.json}"
: "${XDR_IMAGES_DIR:=${XDR_ROOT}/images}"
: "${XDR_RUNTIME_DIR:=${XDR_ROOT}/runtime}"
: "${XDR_RUNTIME_STATE_DIR:=${XDR_RUNTIME_DIR}/state}"
: "${XDR_LOGS_DIR:=${XDR_ROOT}/logs}"
: "${XDR_SCRIPTS_DIR:=${XDR_ROOT}/scripts}"

# --- Libvirt artefact locations --------------------------------------
: "${LIBVIRT_IMAGE_DIR:=/var/lib/libvirt/images}"

# --- Cloud base image (used by create-cloud-vm.sh) -------------------
: "${UBUNTU_CLOUD_BASE_IMG:=${LIBVIRT_IMAGE_DIR}/ubuntu-24.04-cloud.img}"

# --- Networking defaults (mirrors config/lab-vms.json) ---------------
: "${LAB_BRIDGE:=br0}"
: "${LAB_OVS_NETWORK:=ovs-net}"
: "${LAB_SUBNET_CIDR:=10.10.10.0/24}"
: "${LAB_GATEWAY:=10.10.10.1}"
: "${LAB_DNS:=10.10.10.1}"
# Optional override for MASQUERADE egress (-o). Empty = auto-detect default route dev.
: "${LAB_UPLINK_IFACE:=}"

# --- OVS mirror orchestration (state-aware, runtime-driven) ----------
# Authoritative mirror identity: the bridge above + this name. Names are
# the OVS handle we own; we never touch mirrors with other names.
: "${XDR_LAB_MIRROR_NAME:=mirror-to-sensor}"
# Sensor VM whose libvirt vNIC (vnetX) is auto-discovered as output-port.
# Never hard-code vnetN — interface number changes across reboots.
: "${XDR_LAB_SENSOR_VM:=sensor-vm}"
# Mirror runtime state file (single source of truth for OVS mirror facts).
: "${XDR_LAB_MIRROR_STATE_JSON:=${XDR_RUNTIME_STATE_DIR}/mirror.json}"
# Traffic-validation probe target inside the lab subnet (gateway by default).
: "${XDR_LAB_MIRROR_PROBE_TARGET:=${LAB_GATEWAY}}"

# --- Reverse-NAT validation (read-only against the Golden Image) -----
# nat_state.py never mutates iptables. The authoritative DNAT/MASQUERADE
# mapping is baked into nat_state.py because the KVM Host Golden Image is
# the single source of truth for these rules — drift in lab-vms.json
# cannot silently break the operator-facing port contract.
: "${XDR_LAB_NAT_STATE_JSON:=${XDR_RUNTIME_STATE_DIR}/nat.json}"
# VM whose web-console manifest is cross-referenced in nat.json (observability).
# Per-VM websockify ports use XDR_LAB_WEB_CONSOLE_PORT_MAP (see docs/web-console.md).
: "${XDR_LAB_NAT_WEB_CONSOLE_VM:=windows-victim}"

# --- Windows golden qcow2 (canonical image cache + runtime layout) -----
# Images live under ${XDR_IMAGES_DIR}/windows/ (never mutated in place).
# Per-VM runtime: ${XDR_RUNTIME_DIR}/<vm>/root.qcow2 + nvram/.
: "${XDR_LAB_WINDOWS_IMAGES_DIR:=${XDR_IMAGES_DIR}/windows}"
# 1 = delete and recreate NVRAM from template on each deploy; 0 = reuse if present.
: "${XDR_LAB_WINDOWS_RECREATE_NVRAM:=0}"
# If non-empty, state refresh probes SSH (OpenSSH) as this user on the guest.
: "${XDR_LAB_WINDOWS_SSH_USER:=lab}"

# --- Windows emergency VNC (localhost QEMU + host socat TCP forward) -----
# Default external listen port avoids collision with typical :0 -> 5900 on 127.0.0.1.
: "${XDR_LAB_VNC_PROXY_DIR:=${XDR_RUNTIME_DIR}/vnc-proxy}"
: "${XDR_LAB_VNC_EXTERNAL_PORT:=15900}"
: "${XDR_LAB_VNC_PROXY_BIND:=0.0.0.0}"

# --- Windows VM web console (noVNC + websockify; QEMU VNC stays 127.0.0.1) ---
: "${XDR_LAB_WEB_CONSOLE_DIR:=${XDR_RUNTIME_DIR}/web-console}"
: "${XDR_LAB_WEB_CONSOLE_PORT:=6080}"
: "${XDR_LAB_WEB_CONSOLE_BIND:=0.0.0.0}"
# Recommended: "windows-build=6081,windows-victim=6082" (see docs/web-console.md).
# Unlisted VMs use XDR_LAB_WEB_CONSOLE_PORT (6080).
: "${XDR_LAB_WEB_CONSOLE_PORT_MAP:=}"

export PROJECT_ROOT CONFIG_DIR IMAGE_DIR SCRIPT_DIR SCENARIO_DIR LOG_DIR \
       CLOUDINIT_DIR TEMPLATE_DIR INSTALLER_DIR APPLIANCE_DIR DOCS_DIR \
       TESTS_DIR BACKUPS_DIR XDR_BASE XDR_ROOT XDR_LAB_VMS_JSON \
       XDR_IMAGES_DIR XDR_RUNTIME_DIR XDR_RUNTIME_STATE_DIR XDR_LOGS_DIR \
       XDR_SCRIPTS_DIR LIBVIRT_IMAGE_DIR UBUNTU_CLOUD_BASE_IMG LAB_BRIDGE \
       LAB_OVS_NETWORK LAB_SUBNET_CIDR LAB_GATEWAY LAB_DNS LAB_UPLINK_IFACE \
       XDR_LAB_MIRROR_NAME XDR_LAB_SENSOR_VM XDR_LAB_MIRROR_STATE_JSON \
       XDR_LAB_MIRROR_PROBE_TARGET XDR_LAB_NAT_STATE_JSON \
       XDR_LAB_NAT_WEB_CONSOLE_VM XDR_LAB_WINDOWS_IMAGES_DIR \
       XDR_LAB_WINDOWS_RECREATE_NVRAM XDR_LAB_WINDOWS_SSH_USER \
       XDR_LAB_VNC_PROXY_DIR XDR_LAB_VNC_EXTERNAL_PORT XDR_LAB_VNC_PROXY_BIND \
       XDR_LAB_WEB_CONSOLE_DIR XDR_LAB_WEB_CONSOLE_PORT XDR_LAB_WEB_CONSOLE_BIND \
       XDR_LAB_WEB_CONSOLE_PORT_MAP
