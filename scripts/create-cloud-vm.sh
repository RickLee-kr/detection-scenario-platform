#!/bin/bash
# Create an Ubuntu 24.04 cloud VM with cloud-init seed and attach to ovs-net.
# Paths are sourced from config/paths.sh (overridable via env).

set -e

_SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=../config/paths.sh
. "${_SCRIPT_DIR}/../config/paths.sh"

VM_NAME="$1"
IP_ADDR="$2"

if [ -z "$VM_NAME" ] || [ -z "$IP_ADDR" ]; then
  echo "Usage: $0 <vm-name> <ip-address>"
  exit 1
fi

BASE_IMG="${UBUNTU_CLOUD_BASE_IMG}"
VM_DISK="${LIBVIRT_IMAGE_DIR}/${VM_NAME}.qcow2"
SEED_ISO="${LIBVIRT_IMAGE_DIR}/${VM_NAME}-seed.iso"
WORKDIR="${CLOUDINIT_DIR}/${VM_NAME}"

mkdir -p "$WORKDIR"

sudo qemu-img create -f qcow2 -F qcow2 -b "$BASE_IMG" "$VM_DISK" 20G

cat > "$WORKDIR/user-data" <<EOF2
#cloud-config
hostname: ${VM_NAME}
manage_etc_hosts: true

users:
  - name: lab
    sudo: ALL=(ALL) NOPASSWD:ALL
    shell: /bin/bash
    lock_passwd: false
    plain_text_passwd: lab1234

ssh_pwauth: true
disable_root: false

write_files:
  - path: /etc/netplan/50-cloud-init.yaml
    content: |
      network:
        version: 2
        ethernets:
          enp1s0:
            dhcp4: false
            addresses:
              - ${IP_ADDR}/24

runcmd:
  - netplan apply
  - systemctl enable --now ssh
EOF2

cat > "$WORKDIR/meta-data" <<EOF2
instance-id: ${VM_NAME}
local-hostname: ${VM_NAME}
EOF2

cloud-localds "$WORKDIR/seed.iso" "$WORKDIR/user-data" "$WORKDIR/meta-data"
sudo cp "$WORKDIR/seed.iso" "$SEED_ISO"

sudo virt-install \
  --connect qemu:///system \
  --name "$VM_NAME" \
  --memory 2048 \
  --vcpus 2 \
  --disk path="$VM_DISK",format=qcow2,bus=virtio \
  --disk path="$SEED_ISO",device=cdrom \
  --os-variant ubuntu24.04 \
  --network network="${LAB_OVS_NETWORK}",model=virtio \
  --graphics none \
  --console pty,target_type=serial \
  --import \
  --noautoconsole

echo "[OK] Created $VM_NAME with IP $IP_ADDR"
