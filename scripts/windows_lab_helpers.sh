#!/usr/bin/env bash
# Shared helpers for Windows golden-qcow2 + UEFI orchestration (sourced by xdr-lab-vm-manager.sh).
# shellcheck shell=bash

# Discover edk2 OVMF CODE (4M) — first match wins.
xdr_find_ovmf_code() {
  local c
  for c in \
    "/usr/share/OVMF/OVMF_CODE_4M.fd" \
    "/usr/share/OVMF/OVMF_CODE_4M.ms.fd" \
    "/usr/share/qemu/OVMF_CODE_4M.fd" \
    "/usr/share/edk2/ovmf/OVMF_CODE.fd"; do
    if [[ -f "$c" ]]; then
      printf '%s' "$c"
      return 0
    fi
  done
  return 1
}

# Writable NVRAM template (copied per-VM into runtime).
xdr_find_ovmf_vars_template() {
  local v
  for v in \
    "/usr/share/OVMF/OVMF_VARS_4M.fd" \
    "/usr/share/OVMF/OVMF_VARS_4M.ms.fd" \
    "/usr/share/qemu/OVMF_VARS_4M.fd" \
    "/usr/share/edk2/ovmf/OVMF_VARS.fd"; do
    if [[ -f "$v" ]]; then
      printf '%s' "$v"
      return 0
    fi
  done
  return 1
}

# TCP probe using bash /dev/tcp (no nc dependency).
# Usage: xdr_tcp_open <host> <port> <timeout_seconds>
xdr_tcp_open() {
  local host="$1" port="$2" timeout="${3:-2}"
  [[ -n "$host" && -n "$port" ]] || return 1
  if timeout "${timeout}" bash -c "echo >/dev/tcp/${host}/${port}" 2>/dev/null; then
    return 0
  fi
  return 1
}
