# switch-01 — Cisco SG350-10MP

## Identity

- Canonical pSquare name: `switch-01`
- Model: Cisco SG350-10MP
- Role: existing active wired network switch
- Vendor: Cisco
- Status: existing production switch; this identity is reserved for the Cisco device

## Naming rule

`switch-01` refers only to the Cisco SG350-10MP. The Juniper EX2300-C-12P is `switch-02` and must not reuse the `switch-01` hostname, inventory name, documentation name, or automation target.

## Management

The Cisco switch predates the Juniper onboarding and remains the existing `switch-01`. Its management address and configuration are intentionally not changed as part of the Juniper naming correction.

Before making management-plane or provisioning changes, positively identify the Cisco by model/MAC/serial and back up its current configuration.
