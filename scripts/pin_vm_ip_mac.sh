#!/usr/bin/env bash
# Give the IC618_rf VM a fixed address on VMware Fusion's NAT network (docs/134 §4c).  Run it yourself:
#   sudo scripts/pin_vm_ip_mac.sh
# Appends one host entry (VM MAC -> 172.16.218.100, outside the dynamic range .128-.254) after VMware's
# "DO NOT MODIFY" section of vmnet8/dhcpd.conf, keeps a timestamped backup, and restarts VMware networking.
# Afterwards reboot the VM (or renew DHCP inside it).  ssh keeps working either way, because ~/.ssh/config looks
# the address up with `vmrun getGuestIPAddress`.  Undo: restore the backup and rerun the vmnet-cli lines below.
set -euo pipefail
CONF="/Library/Preferences/VMware Fusion/vmnet8/dhcpd.conf"
VMNET="/Applications/VMware Fusion.app/Contents/Library/vmnet-cli"
MAC="00:0c:29:34:bb:40"          # ethernet0.generatedAddress in IC618_rf.vmx
IP="172.16.218.100"
[ "$(id -u)" = 0 ] || { echo "run with sudo" >&2; exit 1; }
grep -q "End of \"DO NOT MODIFY SECTION\"" "$CONF" || { echo "unexpected dhcpd.conf layout; not changed" >&2; exit 1; }
if grep -qi "$MAC" "$CONF"; then echo "a host entry for $MAC already exists; nothing to do"; exit 0; fi
cp -p "$CONF" "$CONF.bak-$(date +%Y%m%d%H%M%S)"
printf '\n# IC618_rf (Open-RFAmpDesigner-Cadence, docs/134 §4c): fixed address\nhost IC618_rf {\n\thardware ethernet %s;\n\tfixed-address %s;\n}\n' "$MAC" "$IP" >> "$CONF"
"$VMNET" --stop
"$VMNET" --start
echo "done: $MAC -> $IP. Reboot the VM (vmrun reset <vmx> soft) or renew DHCP inside it."
