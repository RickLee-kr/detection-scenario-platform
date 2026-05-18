#!/usr/bin/env bash
# VNC proxy (socat raw TCP) + noVNC/websockify web console helpers.
# Sourced by xdr-lab-vm-manager.sh (expects: log_structured, dry_run_active, die,
# require_cmd, vm_exists, LOGD, STATED, XDR_LAB_VNC_PROXY_DIR, XDR_RUNTIME_DIR).
# shellcheck shell=bash

: "${XDR_LAB_WEB_CONSOLE_DIR:=${XDR_RUNTIME_DIR}/web-console}"
: "${XDR_LAB_WEB_CONSOLE_PORT:=6080}"
: "${XDR_LAB_WEB_CONSOLE_BIND:=127.0.0.1}"
: "${XDR_LAB_WEB_CONSOLE_RETRY_SECS:=10}"
: "${XDR_LAB_WINDOWS_VICTIM_VNC_PORT:=5902}"
: "${XDR_LAB_WINDOWS_VICTIM_VNC_DISPLAY:=:2}"

xdr_primary_ipv4() {
  python3 - <<'PY' 2>/dev/null || true
import socket
for dst in ("203.0.113.1", "192.0.2.1", "198.51.100.1"):
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.settimeout(0.4)
        s.connect((dst, 80))
        ip = s.getsockname()[0]
        s.close()
        if ip and not str(ip).startswith("127."):
            print(ip)
            break
    except OSError:
        continue
PY
}

xdr_pid_alive() {
  local pid="$1"
  [[ -n "$pid" && "$pid" =~ ^[0-9]+$ ]] || return 1
  kill -0 "$pid" 2>/dev/null
}

xdr_tcp_open_local() {
  local host="$1" port="$2" timeout="${3:-1.0}"
  python3 - "$host" "$port" "$timeout" <<'PY' >/dev/null 2>&1
import socket, sys
host, port, timeout = sys.argv[1], int(sys.argv[2]), float(sys.argv[3])
try:
    with socket.create_connection((host, port), timeout=timeout):
        pass
except OSError:
    sys.exit(1)
PY
}

xdr_vnc_proxy_manifest_path() {
  local vm="${1:-windows-victim}"
  printf '%s/%s.json' "${XDR_LAB_VNC_PROXY_DIR}" "${vm}"
}

xdr_web_console_manifest_path() {
  local vm="${1:-windows-victim}"
  printf '%s/%s.json' "${XDR_LAB_WEB_CONSOLE_DIR}" "${vm}"
}

xdr_web_console_unit_name() {
  local vm="${1:-windows-victim}"
  printf 'xdr-lab-web-console@%s.service' "${vm}"
}

xdr_systemctl_available() {
  command -v systemctl >/dev/null 2>&1 && [[ -d /run/systemd/system ]]
}

xdr_web_console_unit_installed() {
  local unit="$1" template=""
  if [[ "$unit" == *@*.service ]]; then
    template="${unit%@*}@.service"
  fi
  if [[ -f "/etc/systemd/system/${unit}" || -f "/lib/systemd/system/${unit}" || -f "/usr/lib/systemd/system/${unit}" ]]; then
    return 0
  fi
  [[ -n "$template" ]] || return 1
  [[ -f "/etc/systemd/system/${template}" || -f "/lib/systemd/system/${template}" || -f "/usr/lib/systemd/system/${template}" ]]
}

xdr_web_console_systemd_state() {
  local unit="$1"
  if ! command -v systemctl >/dev/null 2>&1; then
    echo "systemctl unavailable"
    return 0
  fi
  local active enabled
  active="$(systemctl is-active "$unit" 2>/dev/null || true)"
  enabled="$(systemctl is-enabled "$unit" 2>/dev/null || true)"
  echo "active=${active:-unknown}, enabled=${enabled:-unknown}"
}

xdr_web_console_listen_socket() {
  local port="$1"
  if command -v ss >/dev/null 2>&1; then
    local socket
    socket="$(ss -H -ltn "sport = :${port}" 2>/dev/null | awk 'NF {print $4; exit}' || true)"
    if [[ -n "$socket" ]]; then
      echo "$socket"
      return 0
    fi
  fi
  echo "<none>"
}

xdr_vnc_manifest_read_field() {
  local path="$1" field="$2"
  [[ -f "$path" ]] || return 0
  python3 - "$path" "$field" <<'PY' 2>/dev/null || true
import json, sys
path, key = sys.argv[1], sys.argv[2]
try:
    with open(path, "r", encoding="utf-8") as f:
        d = json.load(f)
    v = d.get(key, "")
    if v is None:
        print("")
    elif isinstance(v, bool):
        print("true" if v else "false")
    else:
        print(v)
except Exception:
    print("")
PY
}

# virsh vncdisplay may print ":2", "127.0.0.1:2", or "localhost:2", often with trailing blank lines.
xdr_virsh_vncdisplay_raw() {
  local vm="$1"
  virsh vncdisplay "$vm" 2>&1 | tr -d '\r' | awk 'NF { line = $0 } END { if (line != "") print line }'
}

# Extract QEMU display index (e.g. ":2" / "127.0.0.1:2" -> 2). Prints the number or nothing.
xdr_parse_qemu_vnc_display_num() {
  local raw="$1" num
  raw="${raw//$'\n'/}"
  raw="${raw//[[:space:]]/}"
  [[ -n "$raw" ]] || return 1
  if [[ "$raw" == :* ]]; then
    num="${raw#:}"
  elif [[ "$raw" == *:* ]]; then
    num="${raw##*:}"
  else
    num="${raw}"
  fi
  num="${num#:}"
  [[ "$num" =~ ^[0-9]+$ ]] || return 1
  printf '%s' "$num"
}

# Prints "<display_num>|<tcp_port>" (e.g. "2|5902") or nothing.
xdr_parse_qemu_vnc_display() {
  local raw="$1" num
  num="$(xdr_parse_qemu_vnc_display_num "$raw" 2>/dev/null || true)"
  [[ -n "$num" ]] || return 1
  printf '%s|%s' "$num" "$((5900 + num))"
}

xdr_ensure_windows_victim_vnc_xml() {
  local vm="${1:-windows-victim}"
  [[ "$vm" == "windows-victim" ]] || return 0
  require_cmd virsh

  local old_xml new_xml
  old_xml="$(mktemp)"
  new_xml="$(mktemp)"

  if ! virsh dumpxml --inactive "$vm" >"$old_xml" 2>/dev/null; then
    if ! virsh dumpxml "$vm" >"$old_xml" 2>/dev/null; then
      rm -f "$old_xml" "$new_xml"
      return 1
    fi
  fi

  if ! python3 - "$old_xml" "$new_xml" "${XDR_LAB_WINDOWS_VICTIM_VNC_PORT}" <<'PY'
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

src, dst, port = sys.argv[1:4]
tree = ET.parse(src)
root = tree.getroot()
devices = root.find("devices")
if devices is None:
    devices = ET.SubElement(root, "devices")

graphics = None
for node in devices.findall("graphics"):
    if node.get("type") == "vnc":
        graphics = node
        break
if graphics is None:
    graphics = ET.SubElement(devices, "graphics", {"type": "vnc"})

graphics.set("type", "vnc")
graphics.set("listen", "127.0.0.1")
graphics.set("port", str(port))
graphics.set("autoport", "no")

listen = None
for node in graphics.findall("listen"):
    if node.get("type", "address") == "address":
        listen = node
        break
if listen is None:
    listen = ET.SubElement(graphics, "listen", {"type": "address"})
listen.set("type", "address")
listen.set("address", "127.0.0.1")

ET.indent(tree, space="  ")
Path(dst).write_text(ET.tostring(root, encoding="unicode") + "\n", encoding="utf-8")
PY
  then
    rm -f "$old_xml" "$new_xml"
    return 1
  fi

  if cmp -s "$old_xml" "$new_xml"; then
    rm -f "$old_xml" "$new_xml"
    return 0
  fi
  if ! virsh define "$new_xml" >/dev/null; then
    rm -f "$old_xml" "$new_xml"
    return 1
  fi
  rm -f "$old_xml" "$new_xml"
  log_structured "INFO" "windows_vnc_xml_fixed vm=${vm} listen=127.0.0.1 port=${XDR_LAB_WINDOWS_VICTIM_VNC_PORT} autoport=no"
}

xdr_qemu_vnc_diagnostics() {
  local vm="$1"
  local raw disp num port
  raw="$(virsh vncdisplay "$vm" 2>&1 || true)"
  disp="$(xdr_virsh_vncdisplay_raw "$vm" 2>/dev/null || true)"
  num="$(xdr_parse_qemu_vnc_display_num "$disp" 2>/dev/null || true)"
  port=""
  if [[ -n "$num" ]]; then
    port=$((5900 + num))
  fi
  echo "VNC display diagnostics for ${vm}:" >&2
  echo "  virsh vncdisplay (raw):" >&2
  if [[ -n "$raw" ]]; then
    printf '%s\n' "$raw" | sed 's/^/    /' >&2
  else
    echo "    <empty>" >&2
  fi
  echo "  parsed display: ${num:-<failed>}" >&2
  echo "  resolved TCP port: ${port:-<failed>}" >&2
}

xdr_windows_vnc_listen_port() {
  local vm="$1"
  local disp parsed
  disp="$(xdr_virsh_vncdisplay_raw "$vm" 2>/dev/null || true)"
  parsed="$(xdr_parse_qemu_vnc_display "$disp" 2>/dev/null || true)"
  if [[ "$parsed" == *'|'* ]]; then
    echo "${parsed#*|}"
  else
    echo ""
  fi
}

xdr_web_console_target_port() {
  local vm="${1:-windows-victim}"
  if [[ "$vm" == "windows-victim" ]]; then
    echo "${XDR_LAB_WINDOWS_VICTIM_VNC_PORT}"
    return 0
  fi
  xdr_windows_vnc_listen_port "$vm"
}

# Per-VM websockify listen port: XDR_LAB_WEB_CONSOLE_PORT_MAP="windows-build=6081,windows-victim=6082"
# Unknown VMs fall back to XDR_LAB_WEB_CONSOLE_PORT (default 6080).
xdr_web_console_listen_port() {
  local vm="${1:-windows-victim}"
  local map="${XDR_LAB_WEB_CONSOLE_PORT_MAP:-}"
  local entry k v
  if [[ -n "$map" ]]; then
    local IFS=,
    for entry in $map; do
      entry="${entry#"${entry%%[![:space:]]*}"}"
      entry="${entry%"${entry##*[![:space:]]}"}"
      [[ -n "$entry" ]] || continue
      if [[ "$entry" == *=* ]]; then
        k="${entry%%=*}"
        v="${entry#*=}"
      elif [[ "$entry" == *:* ]]; then
        k="${entry%%:*}"
        v="${entry#*:}"
      else
        continue
      fi
      k="${k#"${k%%[![:space:]]*}"}"
      k="${k%"${k##*[![:space:]]}"}"
      v="${v#"${v%%[![:space:]]*}"}"
      v="${v%"${v##*[![:space:]]}"}"
      if [[ "$k" == "$vm" && "$v" =~ ^[0-9]+$ ]]; then
        echo "$v"
        return 0
      fi
    done
  fi
  echo "${XDR_LAB_WEB_CONSOLE_PORT:-6080}"
}

xdr_find_novnc_webroot() {
  local d
  for d in /usr/share/novnc /usr/share/javascript/novnc; do
    if [[ -f "${d}/vnc.html" ]]; then
      printf '%s' "$d"
      return 0
    fi
  done
  return 1
}

# websockify --web serves index.html for "/"; distro novnc lacks it (directory listing only).
# Build a lab webroot: symlink packaged noVNC + index.html -> vnc.html (same pattern as vnc_auto.html).
xdr_prepare_web_console_webroot() {
  local src="${1:-}"
  local dst="${XDR_LAB_WEB_CONSOLE_DIR}/www"
  local name base target
  if [[ -z "$src" ]]; then
    src="$(xdr_find_novnc_webroot 2>/dev/null || true)"
  fi
  [[ -n "$src" && -f "${src}/vnc.html" ]] || return 1
  mkdir -p "$dst"
  for name in "${src}/"*; do
    [[ -e "$name" ]] || continue
    base="$(basename "$name")"
    target="${dst}/${base}"
    if [[ -L "$target" || ! -e "$target" ]]; then
      ln -sfn "$name" "$target"
    fi
  done
  ln -sfn vnc.html "${dst}/index.html"
  [[ -f "${dst}/vnc.html" || -L "${dst}/vnc.html" ]] || return 1
  [[ -L "${dst}/index.html" ]] || return 1
  printf '%s' "$dst"
}

xdr_websockify_cmd() {
  command -v websockify >/dev/null 2>&1 && printf '%s' "$(command -v websockify)" && return 0
  return 1
}

# --- socat emergency VNC (raw TCP; legacy VNC viewer) -------------------------

vnc_proxy_start() {
  local vm="${1:-windows-victim}"
  require_cmd virsh
  require_cmd socat
  if ! vm_exists "$vm"; then
    die "vnc-proxy start: domain not defined: ${vm}"
  fi
  local st
  st="$(virsh domstate "$vm" 2>/dev/null | tr -d '\r' || true)"
  if [[ "$st" != "running" ]]; then
    die "vnc-proxy start: VM ${vm} is not running (state=${st:-unknown})"
  fi
  local int_port ext_port mf bind
  int_port="$(xdr_windows_vnc_listen_port "$vm")"
  if [[ -z "$int_port" ]]; then
    xdr_qemu_vnc_diagnostics "$vm"
    die "vnc-proxy start: could not resolve QEMU VNC port for ${vm}"
  fi
  ext_port="${XDR_LAB_VNC_EXTERNAL_PORT}"
  bind="${XDR_LAB_VNC_PROXY_BIND}"
  mf="$(xdr_vnc_proxy_manifest_path "$vm")"
  mkdir -p "${XDR_LAB_VNC_PROXY_DIR}"

  local old_pid
  old_pid="$(xdr_vnc_manifest_read_field "$mf" socat_pid)"
  if [[ -n "$old_pid" ]] && xdr_pid_alive "$old_pid"; then
    log_structured "INFO" "vnc_proxy_start_idempotent vm=${vm} pid=${old_pid}"
    return 0
  fi

  if dry_run_active; then
    log_structured "INFO" "dry_run_skip vnc_proxy_start vm=${vm} internal_port=${int_port} external_port=${ext_port}"
    return 0
  fi

  socat TCP-LISTEN:"${ext_port}",bind="${bind}",fork,reuseaddr TCP:127.0.0.1:"${int_port}" \
    >>"${LOGD}/vnc-socat-${vm}.log" 2>&1 &
  local pid=$!
  disown "$pid" 2>/dev/null || true
  python3 - "$mf" "$pid" "$int_port" "$ext_port" <<'PY'
import json, sys, datetime
from pathlib import Path
path = Path(sys.argv[1])
pid = int(sys.argv[2])
internal = int(sys.argv[3])
external = int(sys.argv[4])
rec = {
    "vm": path.stem,
    "socat_pid": pid,
    "internal_port": internal,
    "external_port": external,
    "vnc_bind_mode": "localhost-proxy",
    "started_at": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
}
path.parent.mkdir(parents=True, exist_ok=True)
path.write_text(json.dumps(rec, indent=2) + "\n", encoding="utf-8")
PY
  log_structured "INFO" "vnc_proxy_started vm=${vm} socat_pid=${pid} internal_port=${int_port} external_port=${ext_port}"
}

vnc_proxy_stop() {
  local vm="${1:-windows-victim}"
  local mf pid
  mf="$(xdr_vnc_proxy_manifest_path "$vm")"
  pid="$(xdr_vnc_manifest_read_field "$mf" socat_pid)"
  if dry_run_active; then
    log_structured "INFO" "dry_run_skip vnc_proxy_stop vm=${vm} pid=${pid:-}"
    return 0
  fi
  if [[ -n "$pid" ]] && xdr_pid_alive "$pid"; then
    kill "$pid" 2>/dev/null || true
    log_structured "INFO" "vnc_proxy_stopped vm=${vm} pid=${pid}"
  else
    log_structured "INFO" "vnc_proxy_stop_noop vm=${vm}"
  fi
  rm -f "$mf" 2>/dev/null || true
}

vnc_proxy_status() {
  local vm="${1:-windows-victim}"
  local mf pid int_port ext_port
  mf="$(xdr_vnc_proxy_manifest_path "$vm")"
  pid="$(xdr_vnc_manifest_read_field "$mf" socat_pid)"
  int_port="$(xdr_vnc_manifest_read_field "$mf" internal_port)"
  ext_port="$(xdr_vnc_manifest_read_field "$mf" external_port)"
  echo "VNC raw proxy (socat) — ${vm}"
  echo "  manifest: ${mf}"
  echo "  socat_pid: ${pid:-<none>}"
  if [[ -n "$pid" ]] && xdr_pid_alive "$pid"; then
    echo "  process: running"
  else
    echo "  process: stopped"
  fi
  echo "  internal_port: ${int_port:-<unknown>}"
  echo "  external_port: ${ext_port:-${XDR_LAB_VNC_EXTERNAL_PORT}}"
}

vnc_proxy_verify() {
  local vm="${1:-windows-victim}"
  require_cmd virsh
  local mf pid int_port ext_port st
  st="$(virsh domstate "$vm" 2>/dev/null | tr -d '\r' || true)"
  mf="$(xdr_vnc_proxy_manifest_path "$vm")"
  pid="$(xdr_vnc_manifest_read_field "$mf" socat_pid)"
  int_port="$(xdr_vnc_manifest_read_field "$mf" internal_port)"
  ext_port="$(xdr_vnc_manifest_read_field "$mf" external_port)"
  local live_int
  live_int="$(xdr_windows_vnc_listen_port "$vm")"
  log_structured "INFO" "vnc_proxy_verify vm=${vm} domstate=${st:-unknown} live_internal_port=${live_int:-} manifest_internal=${int_port:-}"

  python3 - "$mf" "$pid" "$int_port" "$ext_port" "$live_int" "$st" <<'PY'
import json, socket, sys, os, datetime
from pathlib import Path

def tcp_open(host, port, timeout=2.0):
    try:
        with socket.create_connection((host, int(port)), timeout=timeout):
            return True
    except OSError:
        return False

mf, pid_s, int_s, ext_s, live_s, st = sys.argv[1:7]
pid = int(pid_s) if pid_s.strip().isdigit() else None
int_port = int(int_s) if int_s.strip().isdigit() else None
ext_port = int(ext_s) if ext_s.strip().isdigit() else int(os.environ.get("XDR_LAB_VNC_EXTERNAL_PORT", "15900"))
live_int = int(live_s) if live_s.strip().isdigit() else None

def primary_ip():
    for dst in ("203.0.113.1", "192.0.2.1", "198.51.100.1"):
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.settimeout(0.4)
            s.connect((dst, 80))
            ip = s.getsockname()[0]
            s.close()
            if ip and not str(ip).startswith("127."):
                return str(ip)
        except OSError:
            continue
    return None

def pid_running(p):
    if p is None or p <= 0:
        return False
    try:
        os.kill(p, 0)
    except OSError:
        return False
    return True

ok = True
reasons = []
if st != "running":
    ok = False
    reasons.append("vm_not_running")
if live_int is None:
    ok = False
    reasons.append("vnc_port_unknown")
elif int_port is not None and live_int != int_port:
    ok = False
    reasons.append("internal_port_mismatch")
if not tcp_open("127.0.0.1", live_int or int_port or 5900):
    ok = False
    reasons.append("internal_vnc_tcp_closed")
if not pid_running(pid):
    ok = False
    reasons.append("socat_not_running")
ip = primary_ip()
if ip and not tcp_open(ip, ext_port):
    ok = False
    reasons.append("external_listen_failed")

verified_at = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
rec = {}
if Path(mf).is_file():
    try:
        rec = json.loads(Path(mf).read_text(encoding="utf-8"))
    except Exception:
        rec = {}
rec["last_verified"] = verified_at
rec["verify_ok"] = ok
rec["verify_reasons"] = reasons
if os.environ.get("XDR_LAB_DRY_RUN") != "1":
    Path(mf).parent.mkdir(parents=True, exist_ok=True)
    Path(mf).write_text(json.dumps(rec, indent=2) + "\n", encoding="utf-8")
print("ok" if ok else "fail")
sys.exit(0 if ok else 1)
PY
}

vnc_proxy_dispatch() {
  local sub="${1:-}" vm="${2:-windows-victim}"
  case "${sub}" in
    start) vnc_proxy_start "$vm" ;;
    stop) vnc_proxy_stop "$vm" ;;
    status) vnc_proxy_status "$vm" ;;
    verify) vnc_proxy_verify "$vm" ;;
    *)
      echo "Usage: $(basename "$0") vnc-proxy <start|stop|status|verify> [vm]" >&2
      return 2
      ;;
  esac
}

# --- Web console (websockify + noVNC static UI) ------------------------------

web_console_component_probe() {
  local ws_root
  if xdr_websockify_cmd >/dev/null; then
    echo "websockify: installed ($(xdr_websockify_cmd))"
  else
    echo "websockify: missing (install package, e.g. apt install websockify)"
  fi
  if ws_root="$(xdr_find_novnc_webroot 2>/dev/null)"; then
    echo "novnc: installed (webroot=${ws_root})"
  else
    echo "novnc: missing (install package, e.g. apt install novnc)"
  fi
}

web_console_start() {
  local vm="${1:-windows-victim}"
  require_cmd virsh
  if ! vm_exists "$vm"; then
    die "web-console start: domain not defined: ${vm}"
  fi
  if ! xdr_ensure_windows_victim_vnc_xml "$vm"; then
    die "web-console start: failed to enforce fixed VNC XML for ${vm}"
  fi
  local st
  st="$(virsh domstate "$vm" 2>/dev/null | tr -d '\r' || true)"
  if [[ "$st" != "running" ]]; then
    die "web-console start: VM ${vm} is not running (state=${st:-unknown})"
  fi

  local ws_bin novnc_src webroot vnc_port vnc_disp mf bind lport
  ws_bin="$(xdr_websockify_cmd 2>/dev/null || true)"
  novnc_src="$(xdr_find_novnc_webroot 2>/dev/null || true)"
  webroot="$(xdr_prepare_web_console_webroot "$novnc_src" 2>/dev/null || true)"
  vnc_disp="$(xdr_virsh_vncdisplay_raw "$vm" 2>/dev/null || true)"
  vnc_port="$(xdr_web_console_target_port "$vm")"
  if [[ -z "$vnc_port" ]]; then
    xdr_qemu_vnc_diagnostics "$vm"
    die "web-console start: could not resolve QEMU VNC port for ${vm}"
  fi
  if ! xdr_tcp_open_local 127.0.0.1 "$vnc_port" 1.0; then
    xdr_qemu_vnc_diagnostics "$vm"
    die "web-console start: fixed QEMU VNC target is not listening: 127.0.0.1:${vnc_port}"
  fi
  mf="$(xdr_web_console_manifest_path "$vm")"
  bind="${XDR_LAB_WEB_CONSOLE_BIND}"
  lport="$(xdr_web_console_listen_port "$vm")"
  mkdir -p "${XDR_LAB_WEB_CONSOLE_DIR}"

  if [[ -z "$ws_bin" ]]; then
    log_structured "ERROR" "web_console_start_failed vm=${vm} reason=websockify_missing"
    die "websockify not found (install websockify package)"
  fi
  if [[ -z "$webroot" ]]; then
    log_structured "ERROR" "web_console_start_failed vm=${vm} reason=novnc_missing"
    die "noVNC webroot not found (install novnc package; expected /usr/share/novnc/vnc.html)"
  fi

  local old_pid
  old_pid="$(xdr_vnc_manifest_read_field "$mf" websockify_pid)"
  if [[ -n "$old_pid" ]] && xdr_pid_alive "$old_pid"; then
    local old_target old_listen
    old_target="$(xdr_vnc_manifest_read_field "$mf" target_port)"
    old_listen="$(xdr_vnc_manifest_read_field "$mf" listen_port)"
    if [[ "$old_target" == "$vnc_port" && "$old_listen" == "$lport" ]]; then
      log_structured "INFO" "web_console_start_idempotent vm=${vm} pid=${old_pid}"
      return 0
    fi
    kill "$old_pid" 2>/dev/null || true
    log_structured "INFO" "web_console_restarting_stale vm=${vm} pid=${old_pid} old_target=${old_target:-} new_target=${vnc_port} old_listen=${old_listen:-} new_listen=${lport}"
  fi

  if dry_run_active; then
    log_structured "INFO" "dry_run_skip web_console_start vm=${vm} listen=${bind}:${lport} target=127.0.0.1:${vnc_port}"
    return 0
  fi

  "${ws_bin}" --web "${webroot}" "${bind}:${lport}" "127.0.0.1:${vnc_port}" \
    >>"${LOGD}/websockify-${vm}.log" 2>&1 &
  local pid=$!
  disown "$pid" 2>/dev/null || true
  python3 - "$vm" "$pid" "$bind" "$lport" "127.0.0.1" "$vnc_port" "$webroot" "$mf" "$vnc_disp" "$novnc_src" <<'PY'
import json, sys, datetime
from pathlib import Path
vm, pid, bind, lport, thost, tport, webroot, mf, vnc_disp, novnc_src = sys.argv[1:11]
rec = {
    "vm": vm,
    "websockify_pid": int(pid),
    "listen_bind": bind,
    "listen_port": int(lport),
    "target_host": thost,
    "target_port": int(tport),
    "vnc_display": vnc_disp,
    "webroot": webroot,
    "novnc_source": novnc_src,
    "started_at": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
}
Path(mf).parent.mkdir(parents=True, exist_ok=True)
Path(mf).write_text(json.dumps(rec, indent=2) + "\n", encoding="utf-8")
PY
  log_structured "INFO" "web_console_started vm=${vm} websockify_pid=${pid} listen=${bind}:${lport} target=127.0.0.1:${vnc_port}"
}

web_console_serve() {
  local vm="${1:-windows-victim}"
  require_cmd virsh
  local retry="${XDR_LAB_WEB_CONSOLE_RETRY_SECS}"
  while true; do
    if ! vm_exists "$vm"; then
      log_structured "WARN" "web_console_service_wait vm=${vm} reason=domain_missing retry=${retry}"
      echo "web-console service: domain not defined: ${vm}; retrying in ${retry}s" >&2
      sleep "$retry"
      continue
    fi
    if ! xdr_ensure_windows_victim_vnc_xml "$vm"; then
      log_structured "WARN" "web_console_service_wait vm=${vm} reason=vnc_xml_fix_failed retry=${retry}"
      echo "web-console service: failed to enforce fixed VNC XML for ${vm}; retrying in ${retry}s" >&2
      sleep "$retry"
      continue
    fi

    local st
    st="$(virsh domstate "$vm" 2>/dev/null | tr -d '\r' || true)"
    if [[ "$st" != "running" ]]; then
      log_structured "INFO" "web_console_service_wait vm=${vm} state=${st:-unknown} retry=${retry}"
      echo "web-console service: VM ${vm} is not running (state=${st:-unknown}); retrying in ${retry}s" >&2
      sleep "$retry"
      continue
    fi

    local ws_bin novnc_src webroot vnc_port vnc_disp mf bind lport old_pid
    ws_bin="$(xdr_websockify_cmd 2>/dev/null || true)"
    novnc_src="$(xdr_find_novnc_webroot 2>/dev/null || true)"
    webroot="$(xdr_prepare_web_console_webroot "$novnc_src" 2>/dev/null || true)"
    vnc_disp="$(xdr_virsh_vncdisplay_raw "$vm" 2>/dev/null || true)"
    vnc_port="$(xdr_web_console_target_port "$vm")"
    mf="$(xdr_web_console_manifest_path "$vm")"
    bind="${XDR_LAB_WEB_CONSOLE_BIND}"
    lport="$(xdr_web_console_listen_port "$vm")"
    mkdir -p "${XDR_LAB_WEB_CONSOLE_DIR}"

    if [[ -z "$ws_bin" ]]; then
      log_structured "ERROR" "web_console_service_failed vm=${vm} reason=websockify_missing"
      echo "web-console service: websockify not found" >&2
      return 1
    fi
    if [[ -z "$webroot" ]]; then
      log_structured "ERROR" "web_console_service_failed vm=${vm} reason=novnc_missing"
      echo "web-console service: noVNC webroot not found" >&2
      return 1
    fi
    if [[ -z "$vnc_port" ]]; then
      xdr_qemu_vnc_diagnostics "$vm"
      log_structured "WARN" "web_console_service_wait vm=${vm} reason=vnc_port_unknown retry=${retry}"
      sleep "$retry"
      continue
    fi
    if ! xdr_tcp_open_local 127.0.0.1 "$vnc_port" 1.0; then
      log_structured "WARN" "web_console_service_wait vm=${vm} reason=vnc_target_closed target=127.0.0.1:${vnc_port} retry=${retry}"
      echo "web-console service: QEMU VNC target 127.0.0.1:${vnc_port} is not listening; retrying in ${retry}s" >&2
      sleep "$retry"
      continue
    fi

    old_pid="$(xdr_vnc_manifest_read_field "$mf" websockify_pid)"
    if [[ -n "$old_pid" && "$old_pid" != "$$" ]] && xdr_pid_alive "$old_pid"; then
      kill "$old_pid" 2>/dev/null || true
      log_structured "INFO" "web_console_service_replaced_old_pid vm=${vm} pid=${old_pid}"
    fi

    python3 - "$vm" "$$" "$bind" "$lport" "127.0.0.1" "$vnc_port" "$webroot" "$mf" "$vnc_disp" "$novnc_src" <<'PY'
import json, sys, datetime
from pathlib import Path
vm, pid, bind, lport, thost, tport, webroot, mf, vnc_disp, novnc_src = sys.argv[1:11]
rec = {
    "vm": vm,
    "websockify_pid": int(pid),
    "listen_bind": bind,
    "listen_port": int(lport),
    "target_host": thost,
    "target_port": int(tport),
    "vnc_display": vnc_disp,
    "webroot": webroot,
    "novnc_source": novnc_src,
    "started_at": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    "systemd_service": True,
}
Path(mf).parent.mkdir(parents=True, exist_ok=True)
Path(mf).write_text(json.dumps(rec, indent=2) + "\n", encoding="utf-8")
PY
    log_structured "INFO" "web_console_service_exec vm=${vm} listen=${bind}:${lport} target=127.0.0.1:${vnc_port}"
    exec "${ws_bin}" --web "${webroot}" "${bind}:${lport}" "127.0.0.1:${vnc_port}"
  done
}

web_console_stop() {
  local vm="${1:-windows-victim}"
  local mf pid
  mf="$(xdr_web_console_manifest_path "$vm")"
  pid="$(xdr_vnc_manifest_read_field "$mf" websockify_pid)"
  if dry_run_active; then
    log_structured "INFO" "dry_run_skip web_console_stop vm=${vm} pid=${pid:-}"
    return 0
  fi
  if [[ -n "$pid" ]] && xdr_pid_alive "$pid"; then
    kill "$pid" 2>/dev/null || true
    log_structured "INFO" "web_console_stopped vm=${vm} pid=${pid}"
  else
    log_structured "INFO" "web_console_stop_noop vm=${vm}"
  fi
  rm -f "$mf" 2>/dev/null || true
}

web_console_status() {
  local vm="${1:-windows-victim}"
  local mf pid lport webroot vnc_disp vnc_port live_vnc_port bind unit vm_state listen_socket
  mf="$(xdr_web_console_manifest_path "$vm")"
  pid="$(xdr_vnc_manifest_read_field "$mf" websockify_pid)"
  lport="$(xdr_web_console_listen_port "$vm")"
  bind="${XDR_LAB_WEB_CONSOLE_BIND}"
  unit="$(xdr_web_console_unit_name "$vm")"
  vm_state="$(virsh domstate "$vm" 2>/dev/null | tr -d '\r' || true)"
  vnc_disp="$(xdr_virsh_vncdisplay_raw "$vm" 2>/dev/null || true)"
  live_vnc_port="$(xdr_windows_vnc_listen_port "$vm")"
  vnc_port="$(xdr_web_console_target_port "$vm")"
  listen_socket="$(xdr_web_console_listen_socket "$lport")"
  echo "Windows web console (noVNC/websockify) — ${vm}"
  web_console_component_probe
  echo "  VM name: ${vm}"
  echo "  VM state: ${vm_state:-unknown}"
  echo "  VNC display: ${vnc_disp:-<unknown>}"
  echo "  live QEMU VNC port: ${live_vnc_port:-<unknown>}"
  echo "  QEMU VNC target: 127.0.0.1:${vnc_port:-<unknown>}"
  echo "  Web console URL: http://127.0.0.1:${lport}/vnc.html"
  echo "  systemd unit: ${unit}"
  echo "  systemd unit state: $(xdr_web_console_systemd_state "$unit")"
  echo "  manifest: ${mf}"
  echo "  websockify PID: ${pid:-<none>}"
  if [[ -n "$pid" ]] && xdr_pid_alive "$pid"; then
    echo "  websockify process: running"
  else
    echo "  websockify process: stopped"
  fi
  echo "  listen socket: ${listen_socket}"
  echo "  listen: ${bind}:${lport} -> 127.0.0.1:${vnc_port:-<qemu-vnc>}"
  if webroot="$(xdr_find_novnc_webroot 2>/dev/null)"; then
    echo "  novnc vnc.html: present (${webroot})"
  else
    echo "  novnc vnc.html: missing"
  fi
}

web_console_verify() {
  local vm="${1:-windows-victim}"
  require_cmd virsh
  local mf pid st live_int lport ext_ip bind
  st="$(virsh domstate "$vm" 2>/dev/null | tr -d '\r' || true)"
  mf="$(xdr_web_console_manifest_path "$vm")"
  pid="$(xdr_vnc_manifest_read_field "$mf" websockify_pid)"
  live_int="$(xdr_web_console_target_port "$vm")"
  lport="$(xdr_web_console_listen_port "$vm")"
  ext_ip="$(xdr_primary_ipv4 2>/dev/null || true)"
  bind="${XDR_LAB_WEB_CONSOLE_BIND}"
  log_structured "INFO" "web_console_verify vm=${vm} domstate=${st:-unknown} internal_vnc_port=${live_int:-} websockify_pid=${pid:-}"

  python3 - "$mf" "$pid" "$live_int" "$lport" "$st" "$ext_ip" "$bind" <<'PY'
import json, socket, sys, os, datetime
from pathlib import Path

def which(name):
    paths = os.environ.get("PATH", os.defpath).split(os.pathsep)
    for p in paths:
        fp = Path(p) / name
        if fp.is_file() and os.access(fp, os.X_OK):
            return str(fp)
    return None

def find_novnc():
    for root in ("/usr/share/novnc", "/usr/share/javascript/novnc"):
        if (Path(root) / "vnc.html").is_file():
            return str(Path(root).resolve())
    return None

def tcp_open(host, port, timeout=2.0):
    try:
        with socket.create_connection((host, int(port)), timeout=timeout):
            return True
    except OSError:
        return False

def primary_ip():
    for dst in ("203.0.113.1", "192.0.2.1", "198.51.100.1"):
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.settimeout(0.4)
            s.connect((dst, 80))
            ip = s.getsockname()[0]
            s.close()
            if ip and not str(ip).startswith("127."):
                return str(ip)
        except OSError:
            continue
    return None

def pid_running(p):
    if p is None or p <= 0:
        return False
    try:
        os.kill(p, 0)
    except OSError:
        return False
    return True

mf, pid_s, live_s, lport_s, st, ext_arg, bind = sys.argv[1:8]
pid = int(pid_s) if str(pid_s).strip().isdigit() else None
live_int = int(live_s) if str(live_s).strip().isdigit() else None
lport = int(lport_s)
ext_ip = ext_arg.strip() or primary_ip()

ok = True
reasons = []
if which("websockify") is None:
    ok = False
    reasons.append("websockify_missing")
if find_novnc() is None:
    ok = False
    reasons.append("novnc_missing")
if st != "running":
    ok = False
    reasons.append("vm_not_running")
if live_int is None:
    ok = False
    reasons.append("vnc_port_unknown")
elif not tcp_open("127.0.0.1", live_int):
    ok = False
    reasons.append("internal_vnc_tcp_closed")
mf_int = None
if Path(mf).is_file():
    try:
        rec = json.loads(Path(mf).read_text(encoding="utf-8"))
        mf_int = int(rec["target_port"]) if str(rec.get("target_port", "")).strip().isdigit() else None
    except Exception:
        rec = {}
else:
    rec = {}
if live_int is not None and mf_int is not None and mf_int != live_int:
    ok = False
    reasons.append("manifest_target_port_stale")
if not pid_running(pid):
    ok = False
    reasons.append("websockify_not_running")
else:
    if not tcp_open("127.0.0.1", lport):
        ok = False
        reasons.append("listen_tcp_closed")
    exposes_off_host = bind in ("0.0.0.0", "::", "[::]")
    if exposes_off_host and ext_ip and not tcp_open(ext_ip, lport):
        ok = False
        reasons.append("external_web_console_tcp_closed")

verified_at = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
if Path(mf).is_file():
    try:
        rec = json.loads(Path(mf).read_text(encoding="utf-8"))
    except Exception:
        rec = {}
else:
    rec = {}
rec["last_verified"] = verified_at
rec["verify_ok"] = ok
rec["verify_reasons"] = reasons
if os.environ.get("XDR_LAB_DRY_RUN") != "1":
    Path(mf).parent.mkdir(parents=True, exist_ok=True)
    Path(mf).write_text(json.dumps(rec, indent=2) + "\n", encoding="utf-8")
print("ok" if ok else "fail")
sys.exit(0 if ok else 1)
PY
}

web_console_service_action() {
  local action="$1" vm="${2:-windows-victim}" unit rc
  unit="$(xdr_web_console_unit_name "$vm")"
  if ! xdr_systemctl_available; then
    die "systemd is not available; cannot ${action} ${unit}"
  fi
  case "$action" in
    start) systemctl start "$unit" ;;
    stop)
      systemctl stop "$unit"
      rc=$?
      rm -f "$(xdr_web_console_manifest_path "$vm")" 2>/dev/null || true
      return "$rc"
      ;;
    enable) systemctl enable "$unit" ;;
    disable) systemctl disable "$unit" ;;
    *) return 2 ;;
  esac
}

web_console_dispatch() {
  local sub="${1:-}" vm="${2:-windows-victim}"
  case "${sub}" in
    start)
      local unit
      unit="$(xdr_web_console_unit_name "$vm")"
      if xdr_systemctl_available && xdr_web_console_unit_installed "$unit"; then
        web_console_service_action start "$vm"
      else
        web_console_start "$vm"
      fi
      ;;
    stop)
      local unit
      unit="$(xdr_web_console_unit_name "$vm")"
      if xdr_systemctl_available && xdr_web_console_unit_installed "$unit"; then
        web_console_service_action stop "$vm"
      else
        web_console_stop "$vm"
      fi
      ;;
    status) web_console_status "$vm" ;;
    verify) web_console_verify "$vm" ;;
    enable) web_console_service_action enable "$vm" ;;
    disable) web_console_service_action disable "$vm" ;;
    serve) web_console_serve "$vm" ;;
    *)
      echo "Usage: $(basename "$0") web-console <start|stop|status|enable|disable|verify> [vm]" >&2
      return 2
      ;;
  esac
}
