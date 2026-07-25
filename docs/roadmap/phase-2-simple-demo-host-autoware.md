# Phase 2 — the simple demo: host Autoware 1.5.0 + the island, vehicle stops on heartbeat loss

**Goal (today):** one filmable run — planning_simulator drives the sample map
autonomously, the availability heartbeat is cut, the ISLAND (not Autoware)
brings the vehicle to a stop.

**Status: DONE (2026-07-24) — VERDICT: PASS.** The full run: host Autoware
1.5.0 planning_simulator (stock MRM shadowed out via the host_ws overlay),
route set + engaged, vehicle drove at 3.9 m/s; the availability heartbeat was
cut (bridge SIGSTOP) → the ISLAND went MRM_OPERATING/EMERGENCY_STOP and the
vehicle stopped (3.90 → 0.00 m/s). `demo/scenario-drive-and-kill.sh` is the
one-shot reproduction (readiness-gated; init/goal poses baked from this run,
overridable via env).

**Zephyr-island variant:** verified PASS once (4.11 → 0.00 m/s) with the
single-bridge fault. **Known caveat (nano-ros #267):** the island's `Control`
msg corrupts through domain_bridge's serialized rebroadcast (direct typed
echo clean; MrmState crosses fine) — until fixed, the demo faults BOTH bridge
legs, the island's MRM decision is verified on domain 2, and the sim-side
stop is the gate's staleness reaction. The split forward/reverse bridge
recipes are already in place for the post-#267 airtight version.

**Late-session environment degradation (unresolved):** after many hours of
runs the domain-1 data plane stopped delivering to NEW participants
(discovery matches, latched samples never arrive; `netstat -su` showed 2e8
UDP receive-buffer errors; raw rclpy graph queries fine, ros2-CLI daemon
repeatedly wedged with `!rclpy.ok()`). The pure-rclpy
`demo/scenario_driver.py` replaces the CLI-based script to remove the daemon
dependency; the delivery wedge itself needs a fresh-boot investigation.

**play_launch adoption (2026-07-25): DONE.** The sim now launches via the
play_launch SOURCE build (`main`, v0.8.2): 40 s bring-up, 62/62 composables,
clean process-group teardown. The stall we hit earlier was pip 0.5.1 — an
old architecture (ListNodes-manager era) that gives up loading composables
into busy single-threaded containers; upstream main has rewritten it. Action
for play_launch: publish a fresh pip release (0.5.1 badly lags main).

**Engage-deadlock findings (both fixed here):**
- `/api/operation_mode/state` is transient_local at source, but the bridge
  republished it volatile and the island subscribed volatile — a late-joining
  island never learns the mode, stays "emergency", and (with the reverse
  bridge honest) its bridged MRM state makes Autoware refuse
  `change_to_autonomous`. Fixed: bridge-forward.yaml QoS override
  (transient_local) + the handler's opmode subscription is transient_local.
- Autoware's availability REQUIRES `/system/emergency/control_cmd` alive on
  domain 1 (topic_state_monitor) — dropping the corrupted bridge row (#267)
  blocked engage entirely. Fixed: `demo/control_relay.py`, a typed d2→d1
  relay (typed decode of the island's Control is clean; only domain_bridge's
  byte-level rebroadcast corrupts). The relay ALSO survives the bridge fault,
  so the island's decel commands genuinely reach the vehicle during MRM —
  the PASS is now attributable to the island's actuation, not gate staleness.

Operational notes learned the hard way: `ros2 launch` teardown MUST be
process-group kill (`just demo-sim-down`) — a plain kill strands every leaf
node and the duplicates flap availability + MRM; play_launch 0.5.1 replay
stalls loading composables into single-threaded containers (map never loads)
— stick to ros2 launch here until that's fixed.

## Environment switch (from phase-1's docker demo)

Autoware runs from the HOST install `/opt/autoware/1.5.0/setup.$shell`
(335 pkgs, 1.5.0 — exact version parity with the ported nodes, so the
velocity-limit topics return to the bridge set). The docker compose path
stays in `demo/` as the containerized alternative.

- Host tooling: source the env — the `tmp/host_msgs_ws` overlay is obsolete.
- `domain_bridge` is NOT in the install → built in `demo/host_ws` (colcon,
  from ros2/domain_bridge, humble).
- Stock MRM disable: `demo/host_ws` also shadows `tier4_system_launch` with
  a copy whose MRM operator/handler includes are removed (no disable args
  exist in 1.5.0; overlay-shadowing beats patching /opt).

## Vendored msg pkgs — keep (decision)

With the host env sourced, nano-ros codegen COULD consume the installed
autoware msg pkgs (AMENT_PREFIX_PATH rung) and the vendored subsets could go.
Kept anyway, for now:
1. The example is a copy-out repo — it must build on hosts WITHOUT an
   Autoware install.
2. nano-ros #258: full-pkg closures drag srv files whose IDL the embedded
   cyclone idlc rejects (`nav_msgs` proven; `autoware_adapi_v1_msgs` /
   `tier4_system_msgs` carry srvs too). Vendored msg-only subsets dodge it.
Revisit when #258 lands: `W-msgs` below.

## Work items

- **W1 — host_ws overlay**: colcon ws with domain_bridge (source) + shadowed
  tier4_system_launch (MRM includes removed). `just demo-host-ws`.
- **W2 — native demo recipes**: `just demo-sim` (planning_simulator from the
  host env + overlay, sample map), `just demo-bridge` (domain_bridge with
  demo/bridge/bridge-config.yaml incl. restored velocity-limit rows),
  `just run` unchanged (island, domain 2, lo).
- **W3 — scenario automation**: `demo/scenario-drive-and-kill.sh` — wait for
  sim readiness → publish /initialpose → goal pose → engage
  (`/api/operation_mode/change_to_autonomous`) → confirm velocity > 0 →
  cut availability (pause bridge OR stop the relay) → assert velocity → 0
  via the island's ramp. Exit code = demo verdict.
- **W4 — gate wiring check**: confirm the 1.5.0 `vehicle_cmd_gate` /
  `use_control_command_gate` arm consumes `/system/emergency/control_cmd` +
  `/system/fail_safe/mrm_state` from the bridge; add remap overrides to the
  shadowed launch if names drifted.
- **W5 — record**: bag + GIF of the stop; README quick-start rewrite around
  the host env.
- **W-msgs (optional, post-#258)**: island build against the installed msg
  pkgs (`AMENT_PREFIX_PATH` closure), vendored subsets deleted.

## Acceptance

`just demo-sim` + `just demo-bridge` + `just run` +
`demo/scenario-drive-and-kill.sh` → script prints DRIVING then STOPPED,
with the island's `/system/fail_safe/mrm_state` at MRM_OPERATING/
EMERGENCY_STOP and Autoware's own MRM nodes absent from `ros2 node list`.
