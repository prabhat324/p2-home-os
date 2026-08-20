# switch-01 — Juniper EX2300-C-12P

## Identity

- Hostname: `switch-01`
- Model: Juniper EX2300-C-12P
- Management interface: `vme.0` (dedicated MGMT port)
- Current management IP: `192.168.0.65/24` via DHCP
- Management MAC: `d0:81:c5:e1:82:5c`
- Admin account: `psquare`
- Root SSH: disabled after bootstrap
- SSH: enabled
- NETCONF: enabled for Ansible management
- ZTP `chassis auto-image-upgrade`: disabled
- Juniper phone-home: disabled

## Control plane

The switch is managed from the `p2-home-os` Ansible control plane on core-01. The self-hosted runner key is `/home/p2runner/.ssh/id_ed25519_p2homeos`; only the public key is installed on the Juniper `psquare` account.

Ansible inventory group: `network_switches`.

## Notes

Keep the dedicated MGMT port connected to the management LAN. Regular `ge-0/0/x` and `xe-0/1/x` interfaces should be used for switching rather than switch administration. Before disruptive changes, back up the committed configuration through Ansible.
