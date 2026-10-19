# CARLA + Autoware + the island on the board, with LEDs

Status: design, 2026-10-14. Built: the LED prototype (section 3,
`CONFIG_ISLAND_LED`, measured on the board), the scenario-declared ODD
(section 2.5), unit C1, the CARLA ego on the island's domain (section 5, G1
passed; runbook demo/carla/README.md), unit C2, acb's `allow_manual`
(MANUAL accepted and reported, a scripted driver holds the lane), unit C3,
the board attached to the CARLA ego, G2 passed (`run-board.sh --sim
carla`: encore, a and b PASS at RTF 1.000 with SSv2 junit PASS), unit C4,
each act triggered by its scenario at its place (encore, a, b back to back
on one boot; every ODD exit `segment` at x 239.8-240.0), unit C5, the booth
image with the LEDs (its record matches the trace within a tick), and unit
C8, the proof casts of acts b and a (`just carla-cast`), and unit C6, the
board's SW1/SW2 driving acts a and encore (`RB_TRIGGER=board`, section
3.4). The island keeps today's serial link
and gateway (1.1); a direct island-Autoware link is recorded as future work
(1.5), not chosen. Two repositories are named throughout:

- this repo (the island): paths without a prefix;
- carla-scenario-bridge, `NEWSLabNTU/carla-scenario-bridge` (CSB): paths
  prefixed `csb:`; its vehicle-side submodule autoware_carla_bridge is
  `acb:` (`csb:src/autoware_carla_bridge/...`).

The idea: a visitor watches a car drive a CARLA town under Autoware. The car
leaves its operating domain or its HPC dies, and the NXP board on the table
-- the safety island -- takes it to a stop, its LED showing the state the
whole time. Today's demo shows the same reactions on Autoware's planning
simulator (a 2-D ideal vehicle model in RViz); the island, its link and its
contract checks stay exactly as they are.

## 0. What was verified for this document

| item | result (2026-10-14, this host) |
|---|---|
| CSB build, `just build` (51 packages, Autoware 1.5.0, CARLA 0.9.16 feature) | exit 0 |
| CSB `just check` / `just test` | pass; 282 Rust + 151 Python tests |
| acb `just check` | **failed** (5 clippy errors); fixed, acb `0a02c2a` |
| acb `just test` | 218 passed |
| maps | the TUM pack, `~/nas/autoveh/dataset/CARLA-map-from-TUM/{Town01,02,03,05,10}` (sshfs); Town01 staged with `CSB_MAP_SOURCE=... just download-maps` |
| quick start: CARLA 0.9.16 offscreen, `just run`, `just ego-av`, `just scenario basic/town01_ego_drive.xosc` | `result.junit.xml` failures=0; ego stack `nodes 62/62, containers 18/18, composable 127/127` in 32 s; 2.0 GB GPU for CARLA |
| `just acceptance` (same stack) | FAIL on `pose_instability_detector` (a death the CSB user guide documents as harmless); fixed, acb `d9aef17`; then `1/1 runs passed`, 66.2 m, 0.007 m/s^2 longitudinal, 0.044 m cross-track |
| CSB gitlink bump | CSB `a84a019` (acb `d9aef17`) |
| LED prototype, encore on the board | `SUMMARY led-e3 encore: PASS; table 8/8 PASS; trace-check PASS`; LED record and pins below |
| ODD from the scenario (2.5): `odd_scenario.py` + `demo/carla/scenarios/town01_island_odd.xosc` | `python3 -m pytest demo/l3/takeover_demo/test`: 11 passed; odd_monitor under rclpy (Humble, `scenario_file:=` that file): pose (0,0) ignored before arming, armed at (315.0, -130.3), `ODD EXIT (segment (239.0, -130.3) outside the ODD polygon)` |
| Town01 road for the polygon | lanelets read from `/mnt/evo/aeon/carla-maps-stage/Town01/lanelet2_map.osm` (2.5) |
| direct-link board builds (1.5), configure only, not flashed | zenoh + `island-ethernet`: refused by Kconfig (`NROS_ZENOH_GRAPH_DISCOVERY ... is not directly user-configurable`); Cyclone: refused by nano-ros (`system.toml [image.zephyr] has rmw = "zenoh"`) |
| host Ethernet toward the board | none: no media converter for the board's 100BASE-T1 PHY; no spare host NIC (1.5) |
| C1, the ego on rmw_zenoh_cpp domain 10 with the island's overlay, no island (G1) | five starts: `Startup complete ... composable 125/125` each, no MRM node on the graph, availability 10.0 Hz from `availability_gate`, `town01_ego_drive` failures=0 errors=0 each (section 5, C1 row) |
| C2, acb `allow_manual` (acb `9ec6343`, CSB `3883f86`) | acb `just check` clean, `just test` 223 passed (5 new); on the board, act a reads control mode 4 (MANUAL) on `/vehicle/status/control_mode` and the scripted driver reaches the route's goal (junit failures=0 errors=0; c3-a5, c3-a7) |
| C3, the board on the CARLA ego (G2) | `SUMMARY c3-e2 encore: PASS ... table 8/8`, `c3-b5 b: PASS ... table 15/15`, `c3-a7 a: PASS ... table 6/6`; each `sim carla, RTF 1.000, SSv2 junit PASS` (section 5, C3 row) |
| C4, the scenario triggers the act | one boot: `c4-e3 encore: PASS ... 8/8 ... trigger hpc-loss at (285.1, -129.4)`, `c4-a2 a: PASS ... 6/6 ... trigger ODD EXIT segment (239.9, -129.4)`, `c4-b2 b: PASS ... 15/15`; each RTF 1.000, junit PASS; `vlimit 7.00 m/s asked, 4.17 selected` (section 5, C4) |
| C5, the booth image | `c5-e3`, `c5-a1`, `c5-b2` PASS; `led_vs_trace.py`: every edge within 0.7 ms of the trace (section 5, C5) |
| C6, the board's buttons | `c6-a2` a PASS 6/6 (`trigger board SW1`), `c6-e1` encore PASS 8/8 (`trigger board SW2`), each press injected through the firmware path; act b on the same image still to run (section 5, C6). The physical press is not verified (nobody at the board) |
| C8, the proof cast | /mnt/evo/aeon/casts/cast-b1.mp4 (act b: ODD exit -> takeover request -> island MRM -> stop) and cast-a1.mp4 (act a: MANUAL, no MRM), with stills (section 5, C8) |
| regression round (2026-10-18), nano-ros pin d4bf898409, play_launch 0.18.3 (rlm v0.1.65), phases 11 and 13 in the image | gate image: `rg-e3` encore PASS 8/8, `rg-b1` b PASS 16/16, `rg-a1` a PASS 8/8; booth image: `rg-be2` encore PASS 8/8 (`trigger board SW2`), `rg-bb1` b PASS 16/16, `rg-ba1` a PASS 8/8 (`trigger board SW1`); each RTF 0.998-1.000, SSv2 junit PASS, LED vs trace PASS on the booth image (section 5, regression round) |

## 1. Architecture

### 1.1 Today

```
 planning simulator (container, sai-l3-autoware:1.5.0-c8)       host                       board
 Autoware 1.5.0, rmw_zenoh_cpp, domain 10  --tcp-->  rmw_zenohd :7447  <-- gateway router --serial 921600--> island
 (demo/l3/container/bin/l3-autoware,                 (just l3-router)     (demo/l3/router/island-gateway.json5,      (3 MRM nodes,
  tier4_system_launch overlay)                                             just l3-peer, docs/serial-link.md)         nano-ros, Zephyr 4.4)
                         takeover_demo on the host: availability_gate (C++, SCHED_FIFO), odd_monitor,
                         takeover_hmi, driver_button, hazard_relay, graph_watcher (demo/l3/README.md)
```

### 1.2 With CARLA

```
 CARLA 0.9.16 (GPU, offscreen)
   ^ ticks (sync, dt 0.05)                ^ vehicle control / sensors / /clock
   |                                      |
 csb bridge + agent relay           ego stack (acb_launch carla_simulator.launch.xml):
 + SSv2 interpreter                  Autoware 1.5.0 + acb_bridge + acb_agent
 domain 9, CycloneDDS                rmw_zenoh_cpp, domain 10   --tcp-->  rmw_zenohd :7447 <-- gateway <--serial--> island
 (csb:justfile `run`, `scenario`)   + the island's tier4_system_launch overlay
        \______ agent relay (TCP 5560, not ROS) _____/         + takeover_demo nodes, unchanged
```

The planning simulator is replaced by the CSB **vehicle side**: Autoware with
CARLA sensors and vehicle interface (`acb:src/acb_launch/launch/carla_simulator.launch.xml`,
started by `csb:justfile` `ego-av`), driving the CARLA actor `hero`. The
**scenario side** (csb bridge, agent relay, SSv2) talks to the vehicle side
only through the agent relay, a TCP socket (csb roadmap 017), so the two
sides need not share a ROS domain or an RMW. That is what lets the ego move
to the island's domain without touching the scenario side:

| side | today in CSB | in this demo |
|---|---|---|
| scenario (csb, relay, SSv2) | domain 9, CycloneDDS (`csb:config/cyclonedds-localhost.xml`) | unchanged |
| vehicle (Autoware, acb_bridge, acb_agent) | domain 1, CycloneDDS | **domain 10, rmw_zenoh_cpp**, the stock router on 7447 |
| island + takeover_demo | domain 10, rmw_zenoh_cpp | unchanged |

acb_bridge and acb_agent are rclrs (rcl underneath), so they follow
`RMW_IMPLEMENTATION`; nothing in acb is Cyclone-specific except the
`CYCLONEDDS_URI` its recipes export, which zenoh ignores. Keeping the ego on
Cyclone domain 1 and bridging the island's topics across (a
zenoh-bridge-ros2dds or a relay node) was rejected: it adds a hop into
every measured path, and the island's graph and liveliness semantics
(`graph_watcher`, the contract's `on: omission`) are rmw_zenoh's.

### 1.3 The island attaches exactly as today

Nothing changes on the board or in the link: the same image, `just l3-router`,
`just l3-peer`, domain 10. On the host, the island's topics (docs/topic-contract.md)
must be produced and consumed by the CARLA ego the same way:

| interface | today | with CARLA | work |
|---|---|---|---|
| `/system/operation_mode/availability` | Autoware's converter publishes `.../availability_raw`; `availability_gate` republishes `autonomous &= !odd_exit` | same: pass `operation_mode_availability_topic:=/system/operation_mode/availability_raw` | the arg propagates from the top-level launch into the overlay's `system.launch.xml` (as `l3-autoware` passes it, demo/l3/container/bin/l3-autoware:58) |
| MRM nodes | the overlay `demo/host_ws/src/tier4_system_launch/launch/system.launch.xml` leaves out Autoware's mrm_handler and both operators | acb includes `$(find-pkg-share tier4_system_launch)/launch/system.launch.xml` (`acb:.../carla_simulator.launch.xml`, the `carla_system` group); with the island's overlay sourced between Autoware and acb, that find resolves to the overlay | source order: Autoware, `build/l3-host-ws/install` (via `demo/carla/ego-overlay.bash`, CSB's `EGO_OVERLAY`), acb install, csb install; `ros2 pkg prefix tier4_system_launch` stays the overlay's after all four. Verified in C1: `play_launch dump` resolves the overlay's file with both arguments (`converter_node` remapped to `.../availability_raw`, the aggregator's `graph_file` the merged graph) and no MRM node; G1's node lists |
| diagnostic graph | the overlay's `l3_diagnostic_graph_path` (phase9-C8, `config/diagnostics/autoware-l3.yaml`) | acb passes its own `acb:.../config/system/diagnostics/autoware-carla.yaml` (node names corrected for 1.5.0 + CARLA) | merged into `demo/host_ws/src/tier4_system_launch/config/diagnostics/autoware-carla-l3.yaml` (acb's graph, C8's 1.5 s timeouts where acb has none, `/autoware/map` without the pointcloud_map link, C1), passed as `l3_diagnostic_graph_path` |
| `/system/fail_safe/mrm_state`, `/system/emergency/*` | island -> vehicle_cmd_gate | same: vehicle_cmd_gate is Autoware's | none |
| `/vehicle/status/control_mode` | the simulator's | acb_bridge publishes it, always AUTONOMOUS | **acb must accept MANUAL** (section 2.2) |
| `/control/control_mode_request` | the simulator's server | acb serves it but refuses MANUAL (`acb:src/acb_bridge/src/vehicle_control.rs`, `control_mode_request_accepted`) | same change |
| `/localization/kinematic_state` | the simulator's ideal pose | Autoware's EKF on CARLA's GNSS/IMU/lidar | none; the island reads speed from it |
| hazard lights | `hazard_relay` -> `/system/hazard_lights_cmd` -> Autoware's selector -> simulator | the same chain ends in acb, which sets CARLA's blinkers (`vehicle_control.rs` `light_state`): the visitor sees them on the car | none; W9's stamp question remains (section 4) |
| comfortable stop velocity limit | `max_velocity_candidates` / `clear_velocity_limit` | Autoware's planner, unchanged | none |
| emergency/comfortable `operate` services | island-internal | island-internal | none |

`acb_launch` also starts its own copies of what the overlay replaces: an
`mrm_handler.param.yaml` (`carla_mrm_handler_path`) and the stock MRM
operator params. With the overlay they are dead arguments; the overlay
ignores them.

### 1.4 Native or container

The L3 container (`sai-l3-autoware:1.5.0-c8`, demo/l3/README.md "The
container") has Autoware 1.5.0 without `autoware-data`, a TensorRT stub, the
patched `librclcpp.so` (trap 2b) and the rmw_zenoh 0.1.10 hold. It has no
acb, no carla client library and no Rust toolchain.

Decision: **phase 1 native, phase 2 container.**

- Native first because it is CSB's tested path (`just ego-av`, section 0)
  and the GPU (CARLA) is on the host. Risk: the host's stock rclcpp 16.0.21
  under rmw_zenoh_cpp is not what demo/l3 measured (the container's
  patched 16.0.19, trap 2b: 63-64/68 composables in 3 of 5 starts on the
  unpatched image). Gate G1 below counts starts.
- Container second, `FROM sai-l3-autoware:1.5.0-c8`, adding a non-symlink
  `colcon build --merge-install` of CSB's acb packages (built on the host
  against the same Autoware debs) and `~/autoware_data` mounted read-only.
  The perception stack must not need TensorRT: acb's `clustering` lidar
  detector does not; the traffic-light classifier does, so the demo route
  avoids signalled junctions or runs `publish_ground_truth_objects:=true`
  with camera traffic lights off. This is also the shape W10 (the Orin)
  needs.

### 1.5 Direct link (future; not the chosen design)

Decision 2026-10-14: **the demo keeps the serial link and the gateway** (1.1).
This section records the options for a link with no bridge between the
island and Autoware, with the evidence gathered, so a later unit starts from
it. Nothing here was flashed.

What the "bridge" is today: the gateway is a second `rmw_zenohd` (the stock
binary) with a serial listen endpoint, connected to Autoware's router on
7447 (`demo/l3/router/island-gateway.json5`, a full copy of the stock config
with four deltas: `keep_alive 6`, serial-egress downsampling, a serial-egress
liveliness ACL, `queue.size.data 16`; docs/serial-link.md section 4). It is
a process and a hop, not a protocol translation: both ends speak zenoh.

| option | link | what goes away | evidence | verdict |
|---|---|---|---|---|
| D0 one router | serial, as today | the gateway process and its TCP hop | the gateway already is `rmw_zenohd`; its downsampling and ACL are already scoped `link_protocols: ["serial"]`, so they mean the same in Autoware's router | cheapest; config only. Deltas 1 and 4 then apply to every link of Autoware's router (keepalive every 10 s; a 16-batch queue on host links). Risk: a serial-face fault (the zenoh 1.8 stall, serial-link.md section 5) now lives in the router all of Autoware depends on |
| D1 zenoh-pico over Ethernet, client of Autoware's `rmw_zenohd` | 100BASE-T1 + TCP | the gateway and the serial line | `snippets/island-ethernet` exists (locator `tcp/192.168.10.77:7447`, static 192.168.10.20/24, domain 10, discovery off, lease 60 s); phase 3 measured the IP stack at +49 KB RAM / +136 KB flash against serial (phase-3 doc 4c); board-facts lists a 4-node zenoh-over-Ethernet image at RAM 273,072 / 327,680 (an older image). Today it does not configure: `error: NROS_ZENOH_GRAPH_DISCOVERY ... is assigned in a configuration file, but is not directly user-configurable` on pin 43fc1c2f7 (the symbol is now derived; the line has to go) | not a bridge: every rmw_zenoh_cpp system runs `rmw_zenohd`, the island becomes one more client. Blocked by hardware (below) and unmeasured: today's serial image is 276,056 B SRAM, so +49 KB would leave about 1.4 KB, an estimate that needs the net pools cut |
| D2 Cyclone DDS, native RTPS participant | 100BASE-T1 + UDP | the gateway and every router | nano-ros has `-S nros-cyclonedds`; board-facts: "CycloneDDS builds for the same board at RAM 174,364 (53.21%) -- static footprint only, at a 24 KiB malloc arena; it has never been run". Today the build is refused before Kconfig: "`-S nros-cyclonedds` selects CYCLONEDDS, but src/zephyr_entry/system.toml [image.zephyr] has rmw = "zenoh"" (needs a second image in system.toml) | no router at all, but the riskiest: SPDP/SEDP matching has no "discovery off", so the island holds proxy state for Autoware's whole graph (127 composables) in its heap, the failure class of G3 (zenoh's graph cache filled a 1 MiB QEMU heap in 2.5 s); Autoware, takeover_demo and acb all move from rmw_zenoh to Cyclone, undoing demo/l3's measured setup (graph_watcher, liveliness) |
| D3 zenoh peer modes, CAN | UDP multicast / CAN FD / ISO-TP | the router hop | nano-ros has `NROS_ZENOH_LINK_UDP_MULTICAST`, `NROS_ZENOH_LINK_CAN`, `NROS_ZENOH_LINK_ISOTP`, `NROS_ZENOH_RAWETH_TRANSPORT` (zephyr/Kconfig) | rmw_zenoh_cpp 0.1 still expects a router for discovery, and the host side of CAN is again a zenoh process: a bridge by another name. XRCE-DDS needs an agent: a bridge |

Host link today (`ip -br link`, `ethtool`, `lsusb`, 2026-10-14): `enp3s0`
is the lab subnet (192.168.10.77/24, 10 Gb/s, a switch with other hosts on
it; the address the Ethernet snippet already dials), `enp130s0` the uplink,
no USB NIC; USB has only the MCU-Link and the FT232R. The board's PHY is a
TJA1103, **100BASE-T1** (single pair), and the kit has no T1-to-100BASE-TX
media converter (board-facts "Ethernet is 100 Mbit"; phase-3 Z1 superseded).
So D1/D2 need, first, a converter (e.g. RDDRONE-T1ADAPT) and then either the
lab switch (no host change; the board at 192.168.10.20) or a dedicated USB
NIC with a static address on the board's subnet.

What D1 would change:

- Autoware launch: nothing; `rmw_zenohd` already listens on `tcp/[::]:7447`.
  `just l3-peer` goes away.
- Island image: `-S island-ethernet` instead of `island-serial` (fix the
  graph-discovery line first), net pools sized down, the DMA-reachable SRAM
  rule for descriptors (board-facts "TCM is not DMA-reachable").
- Contract: the link's `max_transport` (56 ms, measured on serial) is
  re-measured; it should fall (no 921,600-baud serialization, no FTDI
  latency timer), but TCP adds retransmission on loss (an RTO of hundreds of
  ms) where serial had none, and the lab switch is shared, so the bound is
  a measurement, not an assumption. The serial-only egress downsampling has
  no Ethernet counterpart and is not needed at 100 Mbit.
- Tracing: the gateway hop leaves the merge; the island's CTF RAM backend is
  unchanged (it never used the link).
- Domains in CARLA: unchanged under D0/D1 (zenoh domain 10, scenario side
  Cyclone domain 9). Under D2 the ego and the island would share Cyclone
  domain 10 and the scenario side stays on 9: separate RTPS port ranges
  (7400 + 250 x domain), still isolated, since the agent relay is TCP.
- Risk to the validated serial demo: none while it is a separate snippet
  and build dir; the serial image and `just l3-peer` stay the default.

Units, when this is picked up: L1 = D0 on the bench (Autoware's router with
the gateway's deltas and a serial listen endpoint; G: the soak of
serial-link.md and the encore table unchanged); L2 = a media converter and
the `island-ethernet` image re-fixed and sized (G: `ros2 node list` under
`env -i` with rmw_zenoh_cpp lists the three MRM nodes; RAM table); L3 = D1
acts with `max_transport` re-measured. D2 only after L2 has run, as a
separate measurement of whether Cyclone holds Autoware's graph at all.

## 2. Scenarios

### 2.1 The three acts in CARLA

The acts stay host-driven (tools/timeline/scenario.py), because their
measured edges are host events (`press`, `sigstop`, `gate_last`). SSv2
supplies the world: the route, the traffic, the place where things happen,
and its own verdict.

| act | today (planning simulator) | in CARLA |
|---|---|---|
| encore, HPC loss | `scenario hpc`: SIGSTOP the gate; the availability stream goes silent; the island's 500 ms detection -> EMERGENCY_STOP | same mechanism. Triggered at a place in the route by the scenario: an OpenSCENARIO `CustomCommandAction` with an unknown `type` is fork-exec'd by SSv2 (`csb:src/scenario_simulator_v2/openscenario/openscenario_interpreter/src/syntax/custom_command_action.cpp`, `ForkExecCommand`; it `waitpid`s, so the command must return at once) -> a one-line client that tells the act daemon "hpc-loss" |
| a, ODD exit + takeover | `/demo/odd/inject` or the 30 km/h bound in `odd_monitor`; the driver answers within 10 s (`driver_button`); control mode MANUAL | the ODD is declared by the scenario (2.5): a Town01 road polygon and the speed bound; the ego starts inside the polygon and drives out of it, `odd_monitor` detects it from the ego's pose. The visitor's takeover is a button (section 3.4); MANUAL needs acb support (2.2) |
| b, ODD exit unanswered | as a, no answer; COMFORTABLE_STOP after 10 s | as a; the comfortable stop's velocity limit is Autoware's planner braking in CARLA physics |

Weather as an ODD exit (not part of 2.5's declared ODD; the contract's `odd_exit` names "speed bound or
weather"): SSv2's `EnvironmentAction` is a parse-only no-op and the protocol
has no weather slot (`csb:docs/design/ssv2-feature-completeness.md`, row 15);
csb serves `/carla/set_weather` in the scenario domain (9, Cyclone). So the
weather change is staged, not sensed: the same CustomCommandAction that
injects the ODD exit also calls `/carla/set_weather` (fog), and the
`odd_monitor` is told by `/demo/odd/inject`. Sensing it for real (a weather
reader in domain 9 relaying to domain 10) is a later unit; it would make
"weather" a monitored ODD condition rather than a stage effect.

New scenario files (in this repo, `demo/carla/scenarios/`, `$(env
CARLA_MAPS)/Town01` like CSB's):

- `town01_island_encore.xosc`: CSB's `basic/town01_ego_drive.xosc` route,
  one `ReachPositionCondition` at a straight -> CustomCommandAction
  `hpc-loss`; success = ego standstill (`StandStillCondition`) within 15 s
  of the trigger, no collision; failure = timeout. (C3: StandStillCondition
  never fires for the CARLA ego, see below. Built in C4: the trigger at
  x 285 on the odd scenario's straight, its success the odd scenario's.)
- `town01_island_odd.xosc` (act b; in C3 also the encore's world):
  its own route on the long Town01 straight, the ODD declared in its
  ParameterDeclarations (2.5); success = 60 s (simulation) after the ego
  was below 0.1 m/s having moved 5 m. SSv2's StandStillCondition counts
  only a speed of exactly 0, which the stopped CARLA ego never reported
  (c3-b1), and the 60 s keep the world running past the act's readout:
  the scenario's end pauses the world, and the island then raises an HPC
  loss that belongs to no act.
- `town01_island_takeover.xosc` (C3, act a): the same road and route;
  success = the ego at the route's goal, which only a car still driven
  after the takeover reaches; failure = below 0.1 m/s once moved, or the
  timeout. MANUAL itself is read by the act daemon (SSv2 cannot see
  domain 10).

### 2.2 Driver takeover in CARLA (acb change)

acb answers MANUAL with failure and always reports AUTONOMOUS, like SSv2's
stock ego (`vehicle_control.rs`, the comment on `control_mode_request_accepted`).
The island's `driver_exit` path reads MANUAL on `/vehicle/status/control_mode`,
so act a cannot pass without:

- acb accepts MANUAL behind a launch flag (`allow_manual:=true`, default
  false so CSB's scenarios are unchanged), reports MANUAL, and stops
  applying Autoware's commands;
- while MANUAL, the car is driven by a scripted driver: hold the lane at the
  current speed with CARLA's own controller (`set_autopilot` on the hero,
  or acb's `carla_manual_control` for a person at the booth).

Built in C2 (acb `9ec6343`): `allow_manual:=true` as planned, but the
scripted driver is acb's own (`VehicleControlBridge::drive_manual`: pure
pursuit on CARLA's lane waypoints, a proportional speed hold through the
pedal maps), not `set_autopilot`. In synchronous mode LibCarla ticks the
Traffic Manager only inside the process that calls `world.tick()`
(`Simulator::SynchronizeFrame` -> `TrafficManager::Tick()`), which is csb,
and csb creates its Traffic Manager only for a `simulator_autopilot`
entity; acb registering the hero would create an unticked one in its own
process. `carla_manual_control` for a person at the booth is unchanged and
untried with it.

### 2.3 The verdicts combined

| verdict | from | covers |
|---|---|---|
| contract table, `trace-check`, `VERDICT` | run-board.sh SUMMARY (tools/timeline/run-board.sh steps 8-10) | the island's terms: detect, route, settle, FTTI, rung, entry speed |
| SSv2 `result.junit.xml` | the scenario | the world: the ego reached standstill, no collision, within the scenario's timeout |
| acceptance-style checks | `acb:scripts/acceptance.py` | no node died, localization against ground truth, tracking |

run-board.sh gains `--sim carla` (Autoware from the CARLA ego stack instead
of the container; the scenario started at step 7 alongside the act) and a
row `scenario (SSv2 junit)` in the SUMMARY. An act passes only when both
agree.

### 2.4 What changes in the numbers

- **Settle.** Today the settle is the planning simulator's ideal model
  following the emergency operator's ramp. In CARLA, acb applies
  `/control/command/emergency_cmd` as **full brake** (`vehicle_control.rs`:
  `throttle 0, brake 1.0`, handbrake below 0.1 m/s), not the operator's
  `min_acceleration`/`min_jerk` profile. The measured settle will be
  shorter than the derived one: the FTTI row still passes, but the row
  stops validating the declared braking profile. For the contract to mean
  the same thing, acb needs an option to follow the control command's
  acceleration in an emergency (`emergency_full_brake:=false`) through its
  pedal maps; then CARLA physics (tyres, load transfer, the brake map)
  makes the settle a real measurement with an error against the derived
  value, which is a better demo than the ideal model.
  Found in C2: that option already exists and is the default. acb acts on
  `emergency_cmd` only with `honor_emergency_cmd:=true` (default false,
  acb docs/issues/021: the flag was set in 29% of driving samples while
  Autoware commanded acceleration), so in an MRM the vehicle follows the
  control command, i.e. the MRM operator's ramp through vehicle_cmd_gate,
  through the pedal maps. C2 exposed it as a launch argument (still
  false) instead of adding `emergency_full_brake`. Measured in C3: encore
  settle 2350 ms against 4165 derived (entry 2.30 m/s, c3-e2); b settle
  5641-7319 ms against 9997.
- **Entry speed.** Measured from CARLA, through the EKF: localization was
  0.95 m median from GNSS in section 0's run, so a speed derived from pose
  has noise the planning simulator never had; the table reads the
  kinematic state's twist, which is the EKF's.
- **Takeover window.** 10 s on the island's clock (`takeover_request_timeout`,
  src/autoware_mrm_handler/config/mrm_handler.param.yaml). While it runs
  the car keeps driving in CARLA; at the scenario's 7 m/s cap (2.5) the
  route needs 10 s x 7 m/s = 70 m of road after the ODD boundary, about
  7 m for detection and routing, and the comfortable stop's 24.5 m (7 m/s
  at the operator's -1.0 m/s^2): 101.5 m. The polygon in 2.5 puts the stop
  near x 138 on a straight whose junction is at x 101.4.
- **FTTI.** The FTTI argument (`hpc_loss` 10 s, `odd_exit` 30 s,
  demo/l3/contracts/l3_takeover.contract.yaml) is in wall time, because
  the island's detection and the gate are wall clock. It survives only if
  CARLA runs at real time: section 4.

### 2.5 The ODD from the scenario (option b)

The scenario declares the ODD as data; the host's `odd_monitor` detects the
exit from the ego's pose and speed; the gate and the island do the rest
exactly as today. No new node, no new topic, nothing on the island.

**Declaration.** Two OpenSCENARIO `ParameterDeclaration`s at the top of the
`.xosc` (`demo/carla/scenarios/town01_island_odd.xosc`):

| name | `parameterType` | unit, frame | Town01 value |
|---|---|---|---|
| `IslandOddPolygon` | `string` | `"x,y;x,y;..."`, metres, the Autoware map frame | `330.0,-138.0;240.0,-138.0;240.0,-126.0;330.0,-126.0` |
| `IslandOddMaxSpeed` | `double` | km/h | `30.0` (the contract's `entry_speed` 8.33 m/s) |

Either may be left out; a file with neither is refused. A value that is a
`$reference` is refused rather than evaluated: the ODD must read as written.
SSv2 ignores parameters nothing references.

**Frame.** The map frame of the TUM Town01 Lanelet2 map is the frame of
every `WorldPosition` in a CSB scenario: CARLA's world with y flipped and
headings negated (`csb:docs/tutorials/02-prepare-a-scenario.md`; the
projector is `local`, origin 0,0, `map_projector_info.yaml`). The lanelets
store `local_x`/`local_y` in that frame, so the polygon is drawn straight
from the `.osm` and `carla_poses` prints in it too. odd_monitor compares it
with `/localization/kinematic_state`'s position, which is in `map`.

**The polygon.** The straight between the junctions at x 101.4 and x 325.6
(lanelets 6583 westbound, y -132.4..-128.3, and 5230 eastbound,
y -136.4..-132.3; one lanelet each, so no junction between): both lanes plus
1.6 m / 2.3 m of margin for the EKF's lateral noise (0.95 m median in
section 0's run), from x 330 to x 240. The ego is teleported to (315.0,
-130.3) heading west, routed to (120.0, -129.8) (C3: the mission planner
refused (110.0, -130.3) with "Goal's footprint exceeds lane!"; this is CSB's
town01_ego_drive goal), and leaves the ODD at
x 240, 75 m after the start. West of the boundary the 101.5 m budget of 2.4
puts the comfortable stop near x 138, 37 m before the junction.

**The speed bound vs the speed cap.** The lanelets carry no `speed_limit`,
so Autoware would cruise above 30 km/h and the speed bound, not the polygon,
would end the ODD. The scenario caps the ego at 7.0 m/s (25.2 km/h),
leaving 4.8 km/h of margin over EKF twist noise. C4 found that SSv2 hands
Autoware the Controller's `Property maxSpeed`, not `Performance maxSpeed`
(which it sent as DBL_MAX); the scenarios now declare the property, and
Autoware's own `max_vel` (4.17 m/s) caps the cruise lower still (section
5, C4). An act on the speed bound is the same file with the cap above 30
km/h and Autoware's `max_vel` raised.

**How the values reach odd_monitor.** `odd_monitor` takes `scenario_file`
(launch arg of `takeover.launch.xml`) and reads the two declarations itself
(`takeover_demo/odd_scenario.py`, stdlib XML). A declared value replaces the
`max_speed_kmh` / `segment_polygon` parameter; a scenario polygon together
with `segment_polygon` is refused (two sources for one bound). The node logs
the source: `ODD: |v| <= 30.0 km/h, inside a 4-point segment (from <file>)`.
The act daemon (run-board.sh `--sim carla`, C3) passes the same path to SSv2
and to the takeover launch. Chosen over:

- a `CustomCommandAction` at scenario start: it runs in the scenario
  process, fork-exec'd and `waitpid`ed (2.1), so it would need its own IPC
  to a node in another domain, and it arrives after odd_monitor has already
  started judging poses: a race the file read does not have;
- the act daemon parsing the `.xosc` into launch arguments: the same parser
  in a shell-side tool, with the polygon string through two layers of
  quoting; reading in the node keeps one parser, the one the unit test
  covers.

**Arming.** The segment check arms on the first pose inside the polygon. A
pose before localization settles or before the teleport (the EKF's first
output, or a previous scenario's position) would otherwise latch an exit
before the act; the pose `(0, 0)` is ignored until then (section 0). The
speed bound is not armed: a start above 30 km/h is a real exit.

**The evidence chain** (each link already measured in the planning-simulator
acts; nothing new on the island):

```
 ego pose (map, EKF) --> odd_monitor: inside(polygon)? armed?  --> /demo/odd/exit true, /demo/odd/reason "segment (x, y) outside ..."
                                                                     (10 Hz, latched; log line ODD EXIT ... wall= mono=)
   --> availability_gate: autonomous &= !odd_exit (10 Hz timer)  --> /system/operation_mode/availability autonomous=false
   --> island mrm_handler: takeover request (detect row, odd_exit)  --> /system/takeover_request/state, LED amber blinking
   --> driver answers (MANUAL, act a) | 10 s window expires -> COMFORTABLE_STOP (act b)
```

The SUMMARY's odd_exit rows (detect, `island.tor`, window, settle) stay as
they are; the act's start edge becomes odd_monitor's `ODD EXIT` stamp
instead of the `/demo/odd/inject` press.

## 3. LEDs

### 3.1 The board

MR-CANHUBK344 (Zephyr `boards/nxp/mr_canhubk3`, `mr_canhubk3_common.dtsi`,
`doc/index.rst`):

| LED | DT | pin | note |
|---|---|---|---|
| user RGB, red | `led0` = `user_led1_red` | PTE14 | gpio-leds, active low; PGPDO(E low) 0x40291712 bit 1 |
| user RGB, green | `led1` = `user_led1_green` | PTA27 | PGPDO(A high) 0x40291700 bit 4 |
| user RGB, blue | `led2` = `user_led1_blue` | PTE12 | PGPDO(E low) bit 3 |
| CAN LED0..5, red | `can_led0..5` | PTC18, PTE5, PTD20, PTB24, PTB26, PTD31 | one beside each CAN connector |
| SW1, SW2 | `sw0`, `sw1` (gpio-keys) | PTD15, PTA25 | active high |

The `pwm-leds` node drives the same RGB LED through eMIOS and cannot be used
with gpio-leds; the island enables no eMIOS PWM, so there is no conflict.
LPUART2 (the serial link) is pinctrl-muxed on its own pins; none of the LED
or button pins is in the island's pinctrl or the `island-serial` snippet
(src/zephyr_entry/snippets/island-serial/serial.overlay). The GPIO driver
(`CONFIG_GPIO_NXP_SIUL2`) is already in the image.

Visibility: these are small SMD LEDs on a board the size of a palm. At a
booth they read from about a metre. For a crowd, either a camera close-up on
the screen, or the same three signals wired from the header to a stack light
through a driver (a later unit; the state mapping below does not change).

### 3.2 State -> LED

| island state | RGB LED | reads as |
|---|---|---|
| boot, before the handler's first tick | blue steady | starting |
| INIT (waiting for Autoware's inputs) | blue blinking 1 Hz | waiting for the car |
| NORMAL | green steady | the car drives itself, the island watches |
| NORMAL + takeover requested | amber (R+G) blinking 2.5 Hz | driver, take over |
| MRM_OPERATING, COMFORTABLE_STOP | amber steady | stopping gently |
| MRM_OPERATING, EMERGENCY_STOP | red blinking 2.5 Hz | emergency stop |
| MRM_SUCCEEDED | red steady | stopped, safe |
| MRM_FAILED | magenta (R+B) blinking | stop failed |
| CAN LED0 | toggles every 5 handler ticks (1 Hz) | the island is alive; frozen = handler stuck |

The heartbeat is driven by the handler's own tick, so it freezes with the
handler: the visitor-readable form of "the island is not running".

### 3.3 Where it is driven (the prototype)

`CONFIG_ISLAND_LED` (src/zephyr_entry/Kconfig, default n), `src/zephyr_entry/src/island_led.c`,
two calls in `MrmHandler::onTimer()` (src/autoware_mrm_handler/src/mrm_handler/mrm_handler_core.cpp):
one in the INIT branch, one after `publishHazardCmd()`. Chosen over the two
alternatives:

- a separate LED node subscribing to `/system/fail_safe/mrm_state` on the
  island: another subscription, another arena slot and receive buffer
  (about 1.5 KB of the derived sizing), a contract entry, and the LED would
  lag the state by a publish/take;
- a Zephyr timer or thread: an ISR or stack the timing analysis has to
  carry, and the heartbeat would then not prove the handler runs.

No thread, timer or ISR is added; the work is a few register writes on the
spin thread when a pin changes.

The trap found on the board: **Zephyr 4.4's CTF backend traces every GPIO
API call** (`subsys/tracing/ctf/ctf_top.c` defines the gpio hooks whatever
`CONFIG_TRACING_GPIO` says, and it is `n`). With `gpio_pin_set_dt()` on
every tick the first run (`led-e2`) wrote 2,781 gpio set/clear events in
34 s and filled the 52 KiB RAM trace buffer before the act:
`trace-check: FAIL ... it filled at 53246 of 53248 B`, merge.py found no
anchor, and the composed `detect + route` row failed (794 ms against 744;
752 in the first run, `led-e1`) while the image without LEDs passed it. Not
investigated further: after the fix below the row passed (8/8). The image without LEDs used 20,752 B for the same
act. The prototype therefore calls the driver's `port_set_bits_raw` /
`port_clear_bits_raw` directly and only on a level change; the act after
the change used 20,949 B (+197 B).

`island_led_record` (88 B, DTCM .bss) holds the selected pattern, the tick
count and the last 8 transitions with their uptime;
`tools/timeline/led_readout.py` reads it and the four pins' PGPDO bits over
SWD (attach, no halt).

On the board, two acts with the LED image (`ISLAND_BOARD_KCONFIG="CONFIG_ISLAND_LED=y"
just BOARD_BUILD_DIR=build-board-led board-build`, then
`tools/timeline/run-board.sh --elf build-board-led/zephyr/zephyr.elf`):

```
SUMMARY led-e3 encore: PASS; load 13.51 at act; table 8/8 PASS, total 3540.99 of 4909.67 ms; trace-check PASS; ...
edges (ms from the button): ... detect_tick 582.14, ... mrm_operating 582.60, ... mrm_succeeded 3690.89
led_readout (after the act):
pins lit=R   hb=0  record: magic=ok pattern=R blink ticks=553 transitions=7 gpio_errors=0
  #0       0.119 s  NORMAL/NONE                          -> B blink
  #1       3.120 s  MRM_OPERATING/EMERGENCY_STOP         -> R blink    (init_timeout: no Autoware yet)
  #2       6.320 s  NORMAL/NONE                          -> G
  #3      40.120 s  MRM_OPERATING/EMERGENCY_STOP         -> R blink    (the act)
  #4      43.220 s  MRM_SUCCEEDED/EMERGENCY_STOP         -> R          (3.10 s later; trace: 3690.89 - 582.60 = 3108 ms)
  #5      44.420 s  NORMAL/NONE                          -> G          (hpc-restore)
  #6      45.620 s  MRM_OPERATING/EMERGENCY_STOP         -> R blink    (teardown stops the gate)
02:07:22 pins lit=off hb=1 pattern=R blink   (--watch: the pins blink)
02:07:23 pins lit=R   hb=1 pattern=R blink

SUMMARY led-a1 a: PASS; load 24.22 at act; table 6/6 PASS; trace-check PASS; ...
  #3       8.721 s  NORMAL/NONE                          -> G
  #4      47.821 s  NORMAL/NONE +takeover                -> RG blink   (ODD exit, takeover request)
  #5      51.021 s  NORMAL/NONE                          -> G          (the driver's MANUAL)
```

A read during the encore's drive (attach, no halt, while the act ran) gave
`pattern=R blink` one second after the press, `lit=off` in the blink's dark
half. "lit" is read from the pads' output registers, so it is what the LED
shows, independent of the record. The baseline image on the same host and
setup: `SUMMARY base-e1 encore: PASS; table 8/8 PASS, total 3529.22 of
4909.67 ms; trace-check PASS`.

Cost against the gate image (main `5057528`, `just board-build`):

| region | without | with `CONFIG_ISLAND_LED=y` | delta |
|---|---|---|---|
| FLASH | 581,868 | 582,612 | +744 |
| RAM (SRAM) | 276,056 | 276,056 | 0 |
| DTCM | 117,536 | 117,624 | +88 (13,448 B left; the 8 KiB guard holds) |
| ITCM | 12,996 | 13,028 | +32 |

### 3.4 Buttons

SW1/SW2 as the visitor's buttons (the W1/W11 alternative to a screen UI),
built in unit C6 (`CONFIG_ISLAND_BUTTONS`, on in the booth image only):

- **SW1 = take over.** The takeover is the HPC side's (a MANUAL control mode
  from the vehicle), not the island's. A press the island accepts makes the
  act on the host send `/control/control_mode_request` MANUAL, the request
  the act's own takeover button sent before (acb `allow_manual`, C2). The
  island accepts SW1 only while its takeover request is on; any other press
  is recorded as ignored and does nothing.
- **SW2 = HPC loss.** Pressing it must not make the island lie about its
  inputs. A press the island accepts (MRM state NORMAL) makes the act
  SIGSTOP the availability gate, exactly the encore's mechanism: the stream
  stops and the island detects the silence itself. A local fault injection
  inside the island (ignore the availability) would demonstrate nothing the
  contract measures.

Both buttons are a demo affordance, not a safety function: they are outside
the island's contract's hazards, and the island does not act on a press.
The host's act records each press as an injection like today's `press`
edge.

**How a press leaves the board: SWD, not a topic.** The island records the
press; the act reads the record over the debug probe. Decided in C6:

- *Read.* Once per MRM handler tick (`MrmHandler::onTimer`, 10 Hz, beside
  the LED update), through the GPIO driver's `port_get_raw` (the SIUL2
  PGPDI register), not `gpio_pin_get_dt()`. Zephyr 4.4's CTF backend
  traces every GPIO API call (3.3): a poll through the API would add 2
  records of 28 B per tick, 560 B/s, about as much as the whole act's
  window rate (c5-b2 673 B/s). The direct read adds no trace record. An
  interrupt was not chosen: an ISR and a debounce timer the timing analysis
  would carry, for a button whose meaning is decided at the handler's tick
  anyway.
- *Debounce.* A level counts once two consecutive ticks read it. Contacts
  bounce for milliseconds and ticks are 100 ms apart, so a press is seen
  100-200 ms after it starts and has to last about 200 ms (hold it for
  half a second).
- *Record.* `island_button_record` (112 B, DTCM .bss): the sampled and
  debounced levels, counts, and the last 8 presses with their uptime, the
  button, accepted or why ignored, and the MRM state at that tick.
- *To the host.* In `RB_TRIGGER=board` the trace window's re-arm helper
  (`readout.py --rearm-only --buttons`) stays attached after the re-arm and
  polls the record every 25 ms (`tools/timeline/board_buttons.py`): one
  pyocd session holds the probe for the whole act. The act turns an
  accepted press into the MANUAL request (SW1) or the SIGSTOP (SW2).
- *Rejected: publishing `/demo/driver/response` and `/demo/fault/inject`
  from the island* (this section's first plan). Two publishers are two
  contract entries, and the contract is shared by every image: the gate
  image's derived pools and its trace-marker table (whose digest each trace
  carries) would change for a demo affordance, or the booth image would need
  a contract of its own. With the record over SWD the booth image's ROS
  interface, contract and marker table are the gate image's. The cost: the
  booth needs the probe attached (it is, for the flash, the trace and the
  LED readout), and a press reaches the host 25 ms after the tick at worst.
- *Injection* (nobody at the board): a debugger writes N into the record's
  `inject` word for a button; for the next N ticks the button reads pressed
  (OR'ed with the pin) and the firmware counts the word down. The debounce,
  the edge, the state check and the record are the path a real press takes;
  only the pad itself is bypassed.

What the operator still starts: `run-board.sh --sim carla` with
`RB_TRIGGER=board` (the flash or `--keep-boot`, the router and the link,
CARLA, the scenario side, the ego, the gate and the probe, and the SSv2
scenario that poses, routes and engages the ego). The visitor drives the
act from the board: in a, the ego leaves the scenario's ODD by itself, the
LED blinks amber, and SW1 hands the car to the driver (no press: the window
expires and the island stops the car, act b); in the encore, SW2 is the HPC
loss and the island stops the car (red). On site, `just board-buttons`
checks both buttons without a reflash.

## 4. Measurements and risks

### 4.1 What stays a measurement

| today | with CARLA |
|---|---|
| detect (last sample -> reaction tick), route, `call_mrm`, takeover window dwell | unchanged, on the island's clock; contract-checked |
| settle (braking command -> standstill), the planning simulator's model | CARLA physics through acb's pedal maps following the MRM operator's command (`honor_emergency_cmd:=false`, the default; 2.4), so a measurement against the derived profile (C3: shorter, inside the bound) |
| entry speed | EKF twist on CARLA sensors; measured, noisier |
| hazard lights reach the vehicle (W9) | visible as CARLA blinkers; the `hazard_lights_on` row stays `-` until W9's stamp is fixed (it read `-` in `led-e3` too) |
| the car is safe | new: SSv2 verdict (standstill, no collision) |
| LED state | new, qualitative for visitors; the LED record makes it checkable (3.3) |

### 4.2 Risks

1. **Simulation time vs the island's wall clock (the main one).** CSB runs
   CARLA synchronous and csb is the only ticker; between scenarios the
   world and `/clock` are paused (`csb:docs/design/time-and-ticking.md`,
   "One ticker"). Autoware runs on `/clock` (`use_sim_time:=true`). The
   island and the availability gate run on wall time: the island's 500 ms
   availability timeout and the gate's 1 s freshness are wall-clock. So
   - a paused world between scenarios silences the availability stream
     (Autoware's converter timer is sim time) and the island takes an
     EMERGENCY_STOP: correct, and red on the LED, but it must not be
     counted as an act. The act daemon arms only while SSv2 runs;
   - at a real-time factor below 1, sim-time periodic topics arrive slower
     on the wall clock: at RTF 0.5 the availability's 10 Hz becomes 5 Hz,
     still inside 500 ms, but the FTTI is wall time and the settle is sim
     time, so `total = detect (wall) + route (wall) + settle (sim / RTF)`.
     The contract's sum is only meaningful at RTF ~1;
   - the island stamps its messages with its own clock; vehicle_cmd_gate
     and acb see sim-time stamps from everything else. W3/W9 already
     showed one stamp the host rejects (hazard lights).
   Gate G2: RTF measured over every act (`/clock` against wall), and an act
   with RTF below 0.95 is marked invalid in the SUMMARY rather than judged.
   SSv2 runs at `global_real_time_factor` 1.0 (`csb:src/csb_launch/launch/scenario.launch.xml`),
   so RTF below 1 only comes from a host that cannot keep up.
2. **Host load.** Section 0's ego stack is 127 composables plus CARLA; the
   1-min load was 21 before the start and spiked to 141 during it (other
   users' jobs were also running). run-board.sh refuses an act above 35
   (`RB_LOAD_MAX`); the island's serial path measured clean at load 12-14
   today. The CARLA stack must be started and settled before the act's load
   check, and CARLA quality stays `Low` offscreen.
3. **GPU.** CARLA offscreen used 2.0 GB of the 24 GB; acb's default
   perception (`clustering`) needs no GPU; centerpoint would add TensorRT
   engines. No conflict expected; measured per start in G1.
4. **rclcpp under zenoh, native** (1.4): a start flake would look like an
   island fault (the availability never establishes, INIT -> emergency). G1
   counts it.
5. **Emergency brake in acb is full brake** (2.4): an act passes while the
   contract's settle row no longer tests what it says. Closed in C2: full
   brake is only with `honor_emergency_cmd:=true`, which defaults to false.
6. **The stock MRM nodes come back** if the overlay is not first on the
   path for `tier4_system_launch`: the same shadowing trap as demo-runbook
   section 0, inverted. G1 checks the node list (`/system/mrm_handler`
   must be absent on the host graph; section 0's stock CSB run shows it
   present).

## 5. Plan

Each unit ends in a gate that is a run, not a review.

| unit | what | gate | status |
|---|---|---|---|
| C1 | the ego on zenoh: `just ego-av` with `RMW_IMPLEMENTATION=rmw_zenoh_cpp`, `ROS_DOMAIN_ID=10`, the stock router, the island's overlay sourced between Autoware and acb, `operation_mode_availability_topic:=.../availability_raw`, a merged `autoware-carla-l3.yaml` graph | G1: five starts, each `Startup complete` with every composable; `/system/mrm_handler` not on the host graph; `town01_ego_drive` passes with no island attached (availability flows through the gate) | **[x] done 2026-10-14** (below) |
| C2 | acb options: `allow_manual` (MANUAL accepted, reported, Autoware's commands not applied, CARLA autopilot holds the lane) and `emergency_full_brake:=false` | acb unit tests; act a in CARLA reports MANUAL on `/vehicle/status/control_mode` | **[x] done 2026-10-14** (below) |
| C3 | the island attached: run-board.sh `--sim carla` (CARLA + scenario + ego instead of the container), RTF recorded per act | G2: encore, a, b each PASS with SUMMARY rows unchanged in meaning, RTF >= 0.95, SSv2 junit PASS | **[x] done 2026-10-14** (below) |
| C4 | the scenarios: `town01_island_encore.xosc` (CustomCommandAction -> act daemon), `town01_island_odd.xosc` (written; ODD declared, 2.5) with `scenario_file:=` the same path; confirm SSv2 applies `Performance maxSpeed` as Autoware's velocity limit | each act triggered by the scenario at its place, three times back to back without a reflash (W2's re-arm); act a/b's `ODD EXIT` reason is `segment`, between x 239 and 241 | **[x] done 2026-10-14** (below) |
| C5 | LEDs on by default for the booth image (`CONFIG_ISLAND_LED=y` in a booth conf, not the gate image) | the LED record shows the act's transitions with uptimes matching the trace's `mrm_operating` / `mrm_succeeded` edges within one tick | **[x] done 2026-10-14** (below) |
| C6 | buttons: SW1 take over, SW2 HPC loss (3.4) | a visitor runs acts a and encore from the board alone | **[x] done** (gate passed 2026-10-15 for a and encore; act b on the booth image with the buttons on, rg-bb1, regression round 2026-10-18, below; the press injected, the physical buttons not pressed) |
| C7 | the container (phase 2, also W10) | C3's gate with Autoware + acb in the image | |
| C8 | proof cast: a screencast of one act run end to end. A new 1920x1080 TurboVNC display `:3` (`/opt/TurboVNC/bin/vncserver :3 -geometry 1920x1080`; `:1`/`:2` are the user's 1240x900 desktops and `:9` another user's: never touched), recorded with `ffmpeg -f x11grab` from `:3`. On screen and readable at 1080p: the CARLA chase view of the hero; a map panel with the ODD polygon (2.5), the ego pose and a marker where the ODD exit fired; the takeover request (`/system/operation_mode/availability`, the operation mode, `/system/takeover_request/state`); the island's MRM state with its LED colour mirrored on screen (section 3.2's mapping, from `/system/fail_safe/mrm_state`; the host has no webcam for the board itself); wall-clock and simulation timestamps | one cast in which ODD exit -> takeover request -> island MRM -> stop are visible in that order | **[x] done 2026-10-14** (below) |
| L1-L3 | direct link, future (1.5): D0 one router on serial, then D1 Ethernet after a media converter | 1.5's gates | |

**C1 status (2026-10-14, evidence).** Glue: `just/carla.just` (`carla-server`,
`carla-sim`, `carla-ego`, `carla-takeover`, `carla-standin`,
`carla-scenario`, `carla-rclcpp`), `demo/carla/ego-overlay.bash`,
`demo/carla/play_launch.yaml`, `demo/carla/island_standin.py`, the merged
graph above; CSB `e77f0b0`, `971c184`, `c060ddc` (opt-in `just ego-av`
knobs `EGO_RMW_IMPLEMENTATION`, `EGO_OVERLAY`, `EGO_LAUNCH_ARGS`,
`EGO_PLAY_LAUNCH_ARGS`, `EGO_CONTAINER_MODE`; acb unchanged). G1, five
starts back to back, each from a cold CARLA (`/mnt/evo/aeon/scratch-csb/c1/start1..5`):

| start | 1-min load | Startup complete (play_launch, parse to complete) | MRM nodes on the domain-10 graph | `/system/operation_mode/availability` | `town01_ego_drive` |
|---|---|---|---|---|---|
| 1 | 23.7 | 7.7 s, nodes 62/62, containers 16/16, composable 125/125 | none (238 nodes) | 10.000 Hz, one publisher `availability_gate` | failures=0 errors=0 |
| 2 | 28.5 | 9.3 s, 125/125 | none (238) | 9.999 Hz, `availability_gate` | failures=0 errors=0 |
| 3 | 19.5 | 8.3 s, 125/125 | none (238) | 10.000 Hz, `availability_gate` | failures=0 errors=0 |
| 4 | 18.8 | 37.9 s, 125/125 (16 slow constructors, none stalled) | none (238) | 10.000 Hz, `availability_gate` | failures=0 errors=0 |
| 5 | 34.2 | 37.0 s, 125/125 (16 slow, none stalled) | none (238) | 10.000 Hz, `availability_gate` | failures=0 errors=0 |

"MRM nodes": `ros2 node list` (rmw_zenoh_cpp, domain 10, `just l3-nodes`)
has no `/mrm_handler`, `/mrm_emergency_stop_operator`,
`/mrm_comfortable_stop_operator` (only the ADAPI's `/adapi/node/mrm_request`);
the stock CSB run of section 0 had them. The rate is `ros2 topic hz` over
15 s; the gate's own counters over each run: largest publish gap 104-112 ms,
0 gaps over 150 ms, largest gap of the raw converter stream (sim-time
timer) 142-661 ms. No ODD exit fired (odd_monitor: 30 km/h, no polygon).
What it took, beyond the plan's list (demo/carla/README.md, traps):

- **a stand-in for the island's always-on outputs** (`carla-standin`:
  mrm_state NORMAL, the emergency operator's idle pass-through). Without them
  `/autoware/system` (its `emergency_control_command` topic check) is ERROR,
  autonomous never available, the agent stays in PLANNING and SSv2 errors
  out ("waited for ... WAITING_FOR_ENGAGE ... state is PLANNING"). "No
  island attached" in G1 therefore means no island and this stand-in; it
  answers no MRM.
- **the L3 image's rclcpp patch (trap 2b), on the host**: `just
  carla-rclcpp` builds it over the host's 16.0.21, the ego alone loads it.
  Without it behavior_path_planner went silent on the first route.
- **`ZENOH_RUNTIME` 8 workers (trap 2c) and observable container mode.**
  In CSB's isolated mode (~200 zenoh peers, gossip-meshed) the starts were
  not clean even with 8 workers: one composable wedged in its constructor
  (twice, once without `ZENOH_RUNTIME`), one run where behavior_path_planner
  never received `/planning/scenario_planning/scenario`, one drive that did
  not arrive within 180 s, and `/map/pointcloud_map` (62 MB, latched) missed
  by its monitor in 3 of 8 starts. Observable (one process per container):
  6 of 6 clean (a trial plus G1).
- `/autoware/map` without the pointcloud_map link in the merged graph
  (NDT loads the map through a service; the unit stays visible).

Not verified in C1: the island attached (C3); the patched rclcpp over many
re-routes on CARLA (one route per scenario here); container mode
`observable` against CSB's reason for isolated (reloading one crashed
behavior_path_planner, autoware_universe#12460), which no G1 run hit.

**C2 status (2026-10-14, evidence).** acb `9ec6343` (CSB gitlink
`3883f86`): `allow_manual` (default false) on acb_bridge, its launch file
and `carla_simulator.launch.xml`. With it, `/control/control_mode_request`
accepts MANUAL (AUTONOMOUS still, everything else refused), the mode is
shared with the per-session bridge, `/vehicle/status/control_mode` reports
it, the control-command callback returns before applying anything while
MANUAL, and `drive_manual` (called once per frame by the main loop) holds
the lane at the speed it had at the takeover. A new vehicle session starts
AUTONOMOUS. `honor_emergency_cmd` became a launch argument (default false)
in place of `emergency_full_brake` (2.4). `just carla-ego` is started with
`allow_manual:=true` by run-board.sh (`CARLA_EGO_ARGS`).

| check | result |
|---|---|
| acb `just check` (fmt, clippy `-D warnings`) | clean |
| acb `just test` | 223 passed (218 before; new: `allow_manual_accepts_manual_only`, `control_mode_reports_what_was_accepted`, `pursuit_steers_toward_the_target`, `lookahead_and_speed_hold`, `heading_difference_wraps`) |
| the ego's acb_bridge parameters (play_log) | `allow_manual: true`, `honor_emergency_cmd: false` |
| act a on the board, c3-a5 and c3-a7 | the takeover button's MANUAL request answered; scenario.py reads control mode 4 (MANUAL) on `/vehicle/status/control_mode` with the TOR cleared and mrm NORMAL; the scripted driver takes the car on to the route's goal 195 m from the start (`town01_island_takeover` junit failures=0 errors=0) |

Not verified in C2: the scripted driver through a junction (c3-a6, with
the goal delayed 15 s, drove past the goal and fell below 0.1 m/s 227 m
from the start; not investigated); its lateral error (no ground-truth
trace kept); `carla_manual_control` beside `allow_manual`.

**C3 status (2026-10-14, evidence).** `tools/timeline/run-board.sh --sim
carla` (island `613c17f`, `36506e2`): steps 1-4 as today (flash, router,
gateway, the island joins), step 5 starts CARLA, csb and the CARLA ego
(each its own process group, SIGINT first at teardown), step 7 starts the
SSv2 scenario beside the act, scenario.py (`SCENARIO_SIM=carla`) waits for
the ego to drive, re-arms the trace window, injects the fault and writes
an `rtf` event; after the readout the probe stops, the run waits for the
scenario and keeps its junit; run_summary.py adds `sim carla, RTF, SSv2
junit`, reads INVALID below RTF 0.95 and FAIL when the junit disagrees
with a PASS. Image: the gate image, `CONFIG_ISLAND_LED` off (built
2026-10-14 01:11 in the island-led worktree,
`/mnt/evo/aeon/worktrees/island-led/build-board/zephyr/zephyr.elf`, the default image the LED
commit `f0c8adf` leaves size-identical to `5057528`). G2, the last
run of each act with the final tooling (`build/timeline/c3-*`):

| act | run | SUMMARY | table | RTF (fault -> verdict) | SSv2 junit | load at act |
|---|---|---|---|---|---|---|
| encore | c3-e2 | PASS | 8/8, total 2910.37 of 4909.67 ms (detect + route 559.92 of 744.33; settle 2350.45 of 4165.33; entry 2.30 m/s) | 1.000 (4.10 sim s / 4.10 wall s) | PASS | 34.38 |
| b | c3-b5 | PASS | 15/15, total 15903.77 of 20450.67 ms (window dwell 10100 ms; rung COMFORTABLE_STOP) | 1.000 (17.00 / 17.00) | PASS | 33.50 |
| a | c3-a7 | PASS | 6/6 (driver answered 3014 ms; exit route 98.87 of 149 ms; no MRM) | 1.000 (14.00 / 13.99) | PASS | 21.55 |

Rows: the same terms and declared bounds as the planning-simulator acts
(base-e1 encore 8/8, led-a1 a 6/6, w21-b1 b 15/15), each `trace-check PASS (window 2 of
the boot)` and `stored 1 (silence-runtime x1)`, which the planning
simulator's runs store too (the availability's silence right after the
island arms). Also PASS with earlier tooling: c3-a5 (a, 6/6) and c3-e1
(encore, 8/8).

The availability upstream of the island (C1 saw raw gaps up to 661 ms):
over the nine runs that drove, the gate's largest raw gap was 125-364 ms,
its largest publish gap 104-140 ms, never a publish gap over 150 ms, and
the probe's longest availability gap in an act (the a/b tables' `HPC
alive` row) 103-135 ms, except c3-b1
(1427 ms): there every stream the probe records (availability,
control_cmd, kinematic_state, the island's emergency control_cmd) paused
together for 1.4 s while the island's own take record shows availability
every 110 ms or less over the whole act; the probe process stalled, not
the stream. One run went past both: c3-a4, at load 234 and 68% I/O wait
from other jobs, never localized, and its gate saw a raw gap of 1845 ms and
a publish gap of 996 ms before any act. Serial: 1 overrun and 1 bad frame
in the act window of c3-a2, c3-a5, c3-b3 and c3-b5, 0/0 in the others.

What it took (failed runs, in order):

| run | what failed | fix |
|---|---|---|
| c3-a1 | refused: the main checkout's SystemModel stale; then no patched librclcpp in the checkout; then the 1-min load (230 after the ego's start, 108 after 180 s) | `just sync`; build/l3-host-rclcpp and build/l3-host-ws are now links to builds under /mnt/evo; RB_LOAD_WAIT 900 s with `--sim carla` |
| c3-a1 | acb's agent: `/api/localization/initialize: no response in 8.0 s` five times (NDT align 9.4 s on a loaded host) | acb `b463171`: 30 s |
| c3-a2, c3-a3 | `set_route_points` refused 5 times, "Goal's footprint exceeds lane!" for (110.0, -130.3) and (120.0, -130.3) | goal (120.0, -129.8), town01_ego_drive's |
| c3-a4 | localization never reached the teleported pose (load 234, 68% I/O wait from other jobs) | none; rerun at a lower load |
| c3-b1 | junit timeout: StandStillCondition never true (SSv2 needs a speed of exactly 0); the trace window, opened at arming, full 15 s before the act's end | speed < 0.1 m/s once moved 5 m, read 60 s back with `delay`; scenario.py re-arms the window when the ego drives |
| c3-b2 | the island never answered the join check: a ros2 daemon left by an earlier run, sent SIGTERM by hand, was wedged | SIGKILL; the daemon each run's ros2 CLI starts is left running between runs and killed at the end |
| c3-b3, c3-b4 | rung EMERGENCY_STOP: the scenario's end paused the world, the availability went silent, the island raised an HPC loss after the act, and the probe (still running while the run waited for SSv2) recorded it | the probe stops before the wait; b/encore succeed 60 s after the stop |
| c3-a6 | junit failure: with the goal delayed 15 s the scripted driver went past it and slowed below 0.1 m/s | act a's goal not delayed |

Teardown: `orphans: 0` after every run (ps, reparented component
containers, play_launch, acb, csb, CARLA, SSv2), GPU back to 349 MiB / 0 %.

Not verified in C3: three back-to-back acts on one boot (C4's
`--keep-boot`); act a/b triggered by odd_monitor from the scenario's ODD
(C4; here the act daemon's button, as on the planning simulator); RTF
below 1 (every act ran at 0.999-1.001; the INVALID path is unit-tested on
a fixture, not on a run); the LED image under CARLA (C5); the container
(C7). The host load stayed above RB_LOAD_MAX for long stretches from other
users' jobs; runs waited for it, and "load at act" is the load before
the scenario started: the 1-min load over a whole run peaked at 23-177
(load.log; 177 in c3-e2).

**C4 status (2026-10-14, evidence).** Island `6d1f7ed`, `42ae329` (the
SUMMARY names the trigger mode): the scenario
triggers each act at its place (demo/carla/README.md, "C4"). The encore's
`town01_island_encore.xosc` runs a CustomCommandAction at x 285 whose type
is `$(env SAI_ACT_TRIGGER true) hpc-loss`; run-board.sh sets the variable
to `demo/carla/act_trigger.py` and the run's socket, the script sends one
datagram and exits (SSv2 `waitpid()`s it), and the act presses hpc-loss on
it. Acts a and b get no press: run-board.sh starts `odd_monitor` with
`scenario_file:=` the act's own `.xosc`, and the ego leaving the declared
polygon is the ODD exit. Chain 2, three acts back to back on one boot
(`--keep-link`, `--keep-boot`, the gate image, no reflash; build/timeline/c4-*):

| act | run | SUMMARY | table | trigger | RTF | SSv2 junit | load at act |
|---|---|---|---|---|---|---|---|
| encore | c4-e3 | PASS | 8/8, total 3022.51 of 4909.67 ms (detect + route 582.50 of 744.33; settle 2440.02 of 4165.33; entry 4.08 m/s) | the scenario's datagram with the ego at (285.1, -129.4) | 1.000 | PASS | 31.62 |
| a | c4-a2 | PASS | 6/6 (detect 70.66 of 100; driver answered 3035.96; exit route 98.51 of 149; no MRM) | `ODD EXIT (segment (239.9, -129.4) outside the ODD polygon)`, odd_monitor -> gate 1.41 ms | 1.000 | PASS | 34.77 |
| b | c4-b2 | PASS | 15/15, total 14738.55 of 20450.67 ms (detect 86.16 of 100; window dwell 10100.49; settle 4411.48 of 9996.67; rung COMFORTABLE_STOP) | `ODD EXIT (segment (239.9, -129.4) ...)`, 3.24 ms | 1.000 | PASS | 33.79 |

Chain 1 on its own boot: c4-e1 (encore) had no verdict (below), c4-e2
encore PASS 8/8 (trigger at (287.3, -129.4), RTF 1.003), c4-a1 a PASS 6/6
(`ODD EXIT (segment (239.9, -129.4) ...)`, 0.33 ms), c4-b1 b no verdict
(below). Also on the booth image (C5, C8): c5-a1, c5-b2, cast-a1, cast-b1. Every
ODD exit's reason was `segment`, at x 239.8-240.0, with the ego at about
4.15 m/s. Each run `trace-check PASS (window <n> of the boot)`,
`orphans: 0`.

- **The start edge of a and b** is the gate's receipt of
  `/demo/odd/exit` (its `odd` event in gate.jsonl), not odd_monitor's
  `ODD EXIT` stamp as 2.5 planned: the contract's odd_exit detection
  (126 ms) is the gate's timer and starts where the gate learns the
  verdict, as it started at SIGUSR1 before. odd_monitor's stamp, reason
  and hop to the gate (0.33-3.24 ms) are in the act's `trigger` event and
  the SUMMARY (`trigger ODD EXIT ..., odd_monitor -> gate <ms>`).
  odd_monitor now publishes the moment an exit fires as well as on its
  10 Hz timer, so the hop is a transport, not up to a period.
- **The velocity limit.** SSv2 does not send `Performance maxSpeed`: the
  limit it sets through `/api/autoware/set/velocity_limit` is the
  Controller's `Property maxSpeed` (`simulator_core.hpp`
  `applyAssignControllerAction`), DBL_MAX when absent, which C3's
  scenarios sent. The scenarios now declare `maxSpeed` 7.0 on the
  controller. The act reads it back (`vlimit 7.00 m/s asked, 4.17
  selected` in every C4 SUMMARY): `max_velocity_default` 7.0, the
  selector's `max_velocity` 4.17, which is Autoware's own `max_vel`
  (autoware_launch common.param.yaml). So the ego cruises at about 4.1
  m/s whatever the scenario asks above that, the 30 km/h speed bound is
  never near, and 2.4's 7 m/s budget is an upper bound: the ODD exit at
  x 240 leaves 55 m to the comfortable stop at 4.17 m/s.

What it took:

| run | what failed | fix |
|---|---|---|
| c4-e1 | no verdict: the act's re-arm (`readout.py --rearm-only`) re-armed the window and never exited (1-min load 54); `subprocess.run`'s 30 s timeout killed the shell, not pyocd, the act died, and the readout after it failed `USBError: [Errno 16] Resource busy` | the re-arm runs in its own session, killed whole after 60 s; `--keep-boot`'s re-arm bounded at 90 s |
| c4-b1 | no verdict: `FATAL: odd_exit seen on /demo/odd/exit but no odd event in gate.jsonl`: the act took the topic sample 1 ms before the gate logged its receipt, and the act looked for a flip before its own | the act takes the gate's first flip of the run |

Not verified in C4: the encore's place against the planning simulator
(only CARLA); a scenario with the cap above 30 km/h (the speed bound as
the exit; 2.5), which needs Autoware's `max_vel` raised too; each act
three times on one boot (the chain ran each act once per boot, as W2's
chain; scenario-triggered passes across C4, C5 and C8: encore 3 (c4-e2,
c4-e3, c5-e3), a 4 (c4-a1, c4-a2, c5-a1, cast-a1), b 3 (c4-b2, c5-b2,
cast-b1)).

**C5 status (2026-10-14, evidence).** Island `cde2f40`: the booth image is
the gate image plus the snippet `island-booth`
(`src/zephyr_entry/snippets/island-booth/booth.conf`: `CONFIG_ISLAND_LED=y`),
built by `just board-build-booth` into build-board-booth; `just
board-build` (the gate image) is unchanged (its `.config`: `#
CONFIG_ISLAND_LED is not set`). The booth build (2026-10-14, island-led
worktree at main + the snippet) is the size of 3.3's LED build: FLASH
582,612, RAM 276,056, DTCM 117,624, ITCM 13,028. `tools/timeline/led_vs_trace.py`
matches each `mrm_state` and takeover-request edge of an act's trace
(island clock) with a transition of the LED record (`led_readout.py`, read
right after the act; island uptime) and passes when each is within one
handler tick (100 ms). The C3/C4 acts on the booth image, scenario-triggered:

| act | run | SUMMARY | table | RTF | junit | LED vs trace (LED - trace) | trace window used |
|---|---|---|---|---|---|---|---|
| encore | c5-e3 | PASS | 8/8, total 3025.25 of 4909.67 ms | 1.006 | PASS | mrm_operating +0.1 ms, mrm_succeeded +0.6, normal +0.2; operating -> succeeded LED 2600 ms, trace 2599.5, host probe 2607.8 | 11,884 B over 20.0 s |
| a | c5-a1 | PASS | 6/6 (driver answered 3039.68 ms; no MRM) | 1.000 | PASS | tor_on -0.3 ms (RG blink), tor_off -0.3 (G) | 28,908 B over 45.6 s |
| b | c5-b2 | PASS | 15/15, total 14730.23 of 20450.67 ms (settle 4444.42) | 1.000 | PASS | tor_on +0.4 (RG blink), mrm_operating +0.7 (RG), tor_off +0.4, mrm_succeeded +0.5 (R); LED 4499 ms, trace 4499.1, host 4540.3 | 50,410 B over 74.9 s |
| a (cast) | cast-a1 | PASS | 6/6 | 1.000 | PASS | tor_on +0.4, tor_off +0.4 | - |
| b (cast) | cast-b1 | PASS | 15/15, total 14757.06 | 1.000 | PASS | tor_on +0.4, mrm_operating +0.2, tor_off -0.1, mrm_succeeded -0.0; LED 4699 ms, trace 4699.2, host 4685.7 | - |

Every edge lands in the same tick on both records (|LED - trace| <= 0.7
ms; the LED is set in the tick that publishes the state). Each run
`trace-check PASS`, `orphans: 0`.

The trace margin: the LED driver writes a pin only on a level change (3.3),
and the window fills at the gate image's rate (c5-b2 673 B/s, c4-b2 680
B/s). Until this note, b's window opened when the ego first drove (C3's
re-arm) and ran past the stop to the readout, 47-75 s: c5-b2 used 50,410
of the buffer's 53,248 B (2,838 B left) over 74.9 s, and a readout about 4
s later would have filled it.

**Re-armed at the ODD exit (acts a and b).** scenario.py now re-arms a/b's
window a fixed lead before the exit instead of at the first drive:

- **Where.** The ego, held at its speed and heading, is
  `SCENARIO_REARM_LEAD_S` (4.0 s) from the edge of the scenario's own ODD
  polygon (the `.xosc` odd_monitor watches, `SCENARIO_ODD_FILE`): a ray
  from the pose along the heading to the nearest polygon edge, over the
  speed. On Town01 that is x 256.5, 16.5 m east of the boundary at 4.15
  m/s. A deterministic place on the road, not a time after an event.
- **The lead.** No table row needs island events from before the start
  edge: the a/b edges are all taken from 50 ms before it (analysis.py,
  `island_take`, `tor_on`), the clock alignment's anchors are after it
  (merge.py), and the `HPC alive` row is the host probe's, not the trace.
  The timeline plot starts 2 s before the edge, and the window keeps 1.5 s
  of history before its trigger; 4 s covers both with 2 s to spare.
- **The re-arm cost.** pyocd's start-up is the slow part (the ELF's
  symbols, the probe, the session): 0.4-0.7 s warm, 5.1 s cold at a 1-min
  load of 13, and tm-b1 (the first try, the helper started when the ego
  drove, load 50 from the run itself) had not attached 22 s later, so its
  exit came first. The re-arm is therefore split: `readout.py --rearm-only
  --wait-go` starts with the act (minutes before the exit, while SSv2
  poses and engages), attaches, prints `re-arm ready` and writes the word
  only when the act sends `go`. Go -> acknowledged (the island clears the
  word in its next heartbeat tick) measured 56-57 ms on the bench and
  65.3 ms (tm-b2) and 108.4 ms (tm-a2) in the acts; the attach took 444
  and 429 ms after the act started.
- **It cannot miss silently.** The act requires the acknowledgement
  before the start edge (the gate's receipt of `/demo/odd/exit`); without
  a go, a failed helper, or an acknowledgement after the edge, the act
  ends FATAL (no verdict) rather than a table without its start, as tm-b1
  did. The `scenario` `rearm` event keeps the latencies, the lead and the
  pose; the SUMMARY's trace-check field reads `trace <used> of <buffer> B
  over <s> s, re-armed <s> s before the ODD exit (go -> ack <ms> ms)`.
- **The encore keeps the first drive.** Its fault is the scenario's
  datagram, the edge itself, about 11 s after the first drive (x 285), so
  a re-arm at the trigger would land after the edge; its table also needs
  the island's last availability take before the SIGSTOP and the gate's
  last sample (up to 2 s before). Its window is short already: c5-e3
  11,884 B over 20.0 s.
- led_vs_trace.py: the window's first NORMAL mrm_state and first
  request-off are the level at the re-arm, not edges (with the window 4 s
  before the exit, merge.py's 5 s now includes them); the C5/C8 runs read
  the same with the change.

| act | run | SUMMARY | table | trace window used | re-armed before the start edge | RTF | junit | LED vs trace (LED - trace) |
|---|---|---|---|---|---|---|---|---|
| b | tm-b2 | PASS | 15/15, total 14595.77 of 20450.67 ms (settle 4484.22; rung COMFORTABLE_STOP) | 21,256 of 53,248 B over 29.5 s (was 50,410 over 74.9 s in c5-b2) | 4.06 s, go -> ack 65.3 ms | 0.966 | PASS | tor_on +0.4 ms, mrm_operating +0.1, tor_off -0.1, mrm_succeeded +0.6; LED 4600 ms, trace 4599.5, host 4592.9 |
| a | tm-a2 | PASS | 6/6 (driver answered 3056.24 ms; exit route 51.11 of 149; no MRM) | 19,936 of 53,248 B over 27.8 s (was 28,908 over 45.6 s in c5-a1) | 4.00 s, go -> ack 108.4 ms | 1.000 | PASS | tor_on +0.4, tor_off +0.4 |

The encore through the refactored first-drive path: tm-e1 PASS, 8/8,
total 3002.38 of 4909.67 ms, 11,860 B over 20.0 s, RTF 1.004, junit PASS,
LED vs trace PASS (operating -> succeeded LED 2500 ms, trace 2499.6).
All three on the booth image, `trace-check PASS (window 2 of the boot)`,
`stored 1 (silence-runtime x1)`, `orphans: 0`. The rows are the same terms
and bounds as before. tm-b2's `route, island clock` read 1.12 ms where
c5-b2 read 101.60: the window's expiry fell in the same handler tick as
its deadline rather than the next (dwell 10000.48 against 10100.96; the
sum, `windows + route`, 10064.53 against 10196.19); not the re-arm. The
remaining window is the act plus the readout: from the exit, about 25 s to
the act's end (the stop, 1 s, the 5 s hold, 3 s) and the readout's start.
A b act now has about 32 KB (44 s at 720 B/s) of headroom.

What it took:

| run | what failed | fix |
|---|---|---|
| c5-e1 (first try) | REFUSED: `pyocd list` took over 30 s (heavy I/O wait) | `RB_PYOCD_TIMEOUT=90` (trap 11) |
| c5-e1 | INVALID (RTF 0.098): the host stalled 44 s (load.log has no sample from 13:45:34 to 13:46:18; 60% I/O wait, other jobs); the island's verdict said PASS, run_summary said INVALID, as 4.2 asks | none; the INVALID path, unit-tested in C3, read right on a real run |
| c5-b1 | no verdict: Autoware never left INITIALIZING (SSv2: "waited for the Autoware state to transition to WAITING_FOR_ROUTE, but time is up") at a 1-min load of 220-290 (another session's cargo builds); the ego never drove, so the ODD exit could not fire | rerun (c5-b2) when the load fell |
| c5-e2 | no verdict: SSv2 "The simulator reported a failed frame" after its main loop was unresponsive for 30 s (load 105 falling); the ego never drove | rerun (c5-e3) |
| c5-b2 | PASS, but odd_monitor -> gate read 571.54 ms: odd_monitor published after its `ODD EXIT` log line, whose write blocked on the loaded disk | odd_monitor publishes before it logs (the table's start edge, the gate's receipt, was not affected) |
| tm-b1 | no verdict (FATAL, by design): the re-arm helper, started when the ego drove at a 1-min load of 50, printed nothing in the 22 s to the exit; the act refused to go on without the window | the helper starts with the act and attaches while SSv2 engages (tm-b2: 444 ms); why the first attach stalled is not known |
| tm-a1 | REFUSED: 1-min load 72 after 900 s (other sessions' rustc and clippy) | rerun (tm-a2) at a load under 25 |

Not verified in C5: the LED seen by a person (the record and the pads'
output registers are read, not the light); the booth image under the
planning simulator since this commit (3.3's led-e3/led-a1 were); a b act
whose trace window overflows (now 32 KB away); why tm-b1's re-arm helper
had not attached after 22 s (no line from it; the bench and every later
act attached in 0.4-0.7 s); the re-arm at the exit with
`RB_TRIGGER=button` (it keeps the first-drive re-arm) or with an ODD exit
other than the polygon (the speed bound: the act would end FATAL, not
re-armed, unless the polygon's lead came first).

**C6 status (2026-10-15, evidence; act b on the booth image still to run).** Island `ec2b96c`, `ef312f6`,
`dcf8425`: the booth image records SW1/SW2 (`CONFIG_ISLAND_BUTTONS`,
`src/zephyr_entry/src/island_buttons.c`, section 3.4) and
`run-board.sh --sim carla` takes `RB_TRIGGER=board` for a and the encore
(demo/carla/README.md, "C6"). What a visitor does and what the operator
starts:

| | the operator | the visitor, at the board |
|---|---|---|
| a | `RB_TRIGGER=board run-board.sh --sim carla --elf <booth> a <id>` (flash or `--keep-boot`, the link, CARLA, the scenario side, the ego, the gate, the probe, the SSv2 scenario) | waits for the amber blink (the ODD exit, the scenario's), presses SW1 within the 10 s window: MANUAL |
| encore | the same with `encore` | presses SW2 while the car drives (green): the HPC is lost, the island stops the car |

The semantics, decided here (section 3.4 has the read, the debounce and
why SWD rather than a topic):

- **SW1** is accepted only while the island's takeover request is on;
  the act then sends the MANUAL request its takeover button sent (the
  `inject` event the a table measures from, as before) and records a
  `button` event. A press outside the request is recorded as ignored
  (`no takeover request`) and does nothing. No accepted SW1 within the
  window: the island's ladder runs as in act b, and act a reads FAIL.
- **SW2** is accepted only while the MRM state is NORMAL; the act then
  SIGSTOPs the availability gate (the encore's hpc-loss, the table's
  start edge, as before) and records the press as its `trigger` event. The
  island learns of the loss only from the silence, as in every encore.
- b has no button: `RB_TRIGGER=board` refuses it.

The gate, with nobody at the board: `RB_BUTTON_INJECT=1`. The act writes
the button's `inject` word through the bridge (the button reads pressed
for 3 handler ticks, OR'ed with the pin), SW1 `RESPOND_AFTER` (3) s into
the takeover request, SW2 when the encore scenario's datagram arrives
(x 285, C4's place). The debounce, the edge, the state check, the record,
the bridge and the act's reaction are the path a real press takes. Acts on
the booth image (FLASH 583,356, RAM 276,056, DTCM 117,744 (13,328 B free;
the 8 KiB guard holds), ITCM 13,068; against C5's booth image +744, 0,
+120, +40; the gate image, rebuilt, unchanged at 581,868 / 276,056 /
117,536 / 12,996, `# CONFIG_ISLAND_BUTTONS is not set`); build/timeline in
the island-led worktree:

| act | run | SUMMARY | table | trigger (SUMMARY) | trace window | RTF | junit | LED vs trace (LED - trace) |
|---|---|---|---|---|---|---|---|---|
| a | c6-a2 | PASS | 6/6 (detect 28.44 of 100; driver answered 3233.51; exit route 81.58 of 149; no MRM) | `board SW1 (injected, island uptime 204873 ms, inject -> seen 189.0 ms, seen -> MANUAL request 3.06 ms) after ODD EXIT segment (240.0, -129.4) ..., odd_monitor -> gate 0.28 ms` | 20,540 of 53,248 B over 28.6 s, re-armed 4.00 s before the exit (go -> ack 53.5 ms) | 1.000 | PASS | tor_on -0.3 ms, tor_off +0.4 |
| encore | c6-e1 | PASS | 8/8, total 3003.63 of 4909.67 ms (detect + route 553.49 of 744.33; settle 2450.14 of 4165.33; entry 4.08 m/s) | `board SW2 (injected, island uptime 209777 ms, inject -> seen 132.9 ms, seen -> SIGSTOP 8.22 ms) at (286.6, -129.4)` | 9,768 B over 15.6 s, re-armed when the ego drove | 1.000 | PASS | mrm_operating +0.2, mrm_succeeded +0.6, normal +0.2; operating -> succeeded LED 2600 ms, trace 2599.6 |

Each `trace-check PASS (window 2 of the boot)`, `stored 1
(silence-runtime x1)`, serial 0/0 in the act, `orphans: 0`. The button
record read after each act (`board_buttons.py show`): c6-a2 one press, SW1
accepted at 204.873 s; c6-e1 one press, SW2 accepted at 209.777 s;
`gpio_errors 0`. The rows are the same terms and bounds as C5's runs
(tm-a2, tm-e1): the button only moves who starts the edge.

Trace cost of the buttons: none measurable. The pins are read by the
driver's port read, which the CTF backend does not see, and the bridge's
SWD reads are not traced. The window filled at 718 B/s in c6-a2 (tm-a2
717 B/s) and 626 B/s in c6-e1 (tm-e1 593 B/s over a window 4.4 s longer). Through `gpio_pin_get_dt()` the poll would have added 2
records of 28 B per tick, 560 B/s (3.3).

Latencies (host side): inject written -> the bridge's line 133-189 ms (the
debounce's 2 ticks, 100-200 ms, plus the 25 ms poll); the bridge's line ->
the MANUAL request or the SIGSTOP 3-8 ms. With a finger the first is the
same less the tick phase, from the moment the contact closes.

What it took:

| run | what failed | fix |
|---|---|---|
| bench | `just l3-peer` refused: `fuser` on the gateway tty ran over 10 min. A `find /` left running (orphaned) had walked into the sshfs NAS and held about 1,900 directory fds there; fuser stat()s every open file | `scripts/tty-holders.sh` (readlink of /proc/<pid>/fd, 0.03 s with that walk running) in l3-peer, board-peer and run-board's preflight (demo/carla/README.md trap 19) |
| c6-a1 | FAIL with no reason, though the table was 6/6, MANUAL reached and the junit PASS: the board branch of act a skipped the verdict | the MANUAL check runs after either branch (`dcf8425`); c6-a1's SUMMARY otherwise as c6-a2 (`board SW1 (injected, ..., inject -> seen 160.2 ms, seen -> MANUAL request 7.32 ms)`, trace 14,042 B over 19.8 s) |
| c6-b1 | no verdict: Autoware never left INITIALIZING (load 33 at the act, trap 16) | rerun; c6-b2 was stopped at step 5 (SIGINT, teardown, orphans 0) when the board was handed to the paper's experiments |

c6-a1 also stored 3 `timer-overrun-runtime timer` violations (measured 29,
9, 9 periods) outside its trace window (none in the window; the island
armed at 172 s, the window opened at 250.5 s), where no earlier CARLA run
stored any; c6-a2 and c6-e1 stored none. The bridge was not
attached before the window (it starts at the re-arm), so it is not the
cause; the cause is not known.

Not verified in C6: **act b on the booth image with the buttons on** (the no-regression run; c6-b1 never drove, c6-b2 stopped before CARLA came up); **a physical press** (nobody was at the board; the pad
is the one part of the path the injection bypasses; `just board-buttons`
is the on-site check, README "On site"); a person's reaction time against
the 10 s window and the 200 ms hold the debounce needs; presses on a
`--keep-boot` chain (each act here ran on its own boot); the booth image
under the planning simulator; the cause of c6-a1's timer overruns.

**C8 status (2026-10-14, evidence).** `just carla-cast [run-board options]
a|b|encore <id>` (`demo/carla/cast.sh`, `demo/carla/cast_dashboard.py`;
demo/carla/README.md, "C8") runs one act with run-board.sh `--sim carla`,
starts the dashboard on the TurboVNC display `:3` (1920x1080, no desktop:
`just carla-cast-display`) at run-board's step 6, records it with ffmpeg
x11grab (h264_nvenc, 30 fps) from step 7 (the scenario starts) to 8 s
after step 8 (the readout), and cuts a still at each transition the act is
about. The dashboard, one window, one clock (the host's wall clock and
`/clock` in the banner and on every event line): the state in a banner
(AUTONOMOUS / TAKEOVER REQUESTED with the window's countdown / ISLAND MRM:
COMFORTABLE STOP / STOPPED SAFELY / DRIVER IN CONTROL), the CARLA chase view
(an RGB camera the dashboard attaches to the hero, 1066x600), the ODD panel
(odd_monitor's verdict and reason, speed, x), the takeover request
(`/system/operation_mode/availability` autonomous, `/api/operation_mode/state`,
`/vehicle/status/control_mode`, `/system/takeover_request/state`), the
island (`/system/fail_safe/mrm_state`, the LED mirrored with 3.2's
mapping), the map (the Town01 straight from the Lanelet2 map, the
scenario's polygon, the track, the ego, a cross where the ODD exit fired,
a square where it stopped) and the last four transitions. Casts, booth
image, in /mnt/evo/aeon/casts:

| take | act | file | length | in order on screen (wall clock) | the act |
|---|---|---|---|---|---|
| cast-b1 | b | cast-b1.mp4 (H.264, 1920x1080, 30 fps) | 141.7 s | ODD EXIT segment (239.8, -129.4) 15:07:14.420 -> autonomous available NO .458 -> TAKEOVER REQUESTED .512 -> request off and island MRM_OPERATING / COMFORTABLE_STOP 15:07:24.613 -> STANDSTILL at x 187.0 15:07:29.175 -> MRM_SUCCEEDED / COMFORTABLE_STOP 15:07:29.304 | PASS, 15/15, RTF 1.000, junit PASS, LED vs trace PASS |
| cast-b5 | b | cast-b5.mp4 (H.264, 1920x1080, 30 fps) | 157.8 s | ODD EXIT segment (239.9, -129.4) 20:21:39.746 -> autonomous available NO .748 -> TAKEOVER REQUESTED .844 -> request off and island MRM_OPERATING / COMFORTABLE_STOP 20:21:49.958 -> STANDSTILL at x 187.1 20:21:54.449 -> MRM_SUCCEEDED / COMFORTABLE_STOP 20:21:54.539 | PASS, 15/15, total 14704.67 ms, RTF 1.000, junit PASS, LED vs trace PASS (tor_on +0.3 ms, mrm_operating +0.0, tor_off -0.2, mrm_succeeded -0.3), trace 21,696 B over 30.0 s, re-armed 4.00 s before the exit |
| cast-a1 | a | cast-a1.mp4 | 140.3 s | ODD EXIT segment (240.0, -129.4) 15:11:55.398 -> autonomous NO .494 -> TAKEOVER REQUESTED .515 -> control mode MANUAL 15:11:58.601 -> request off .715; mrm NORMAL throughout | PASS, 6/6, no MRM, RTF 1.000, junit PASS, LED vs trace PASS |

Stills (each viewed, legible at 1080p): cast-b1-01-odd-exit.png,
-02-takeover-request.png, -03-mrm-operating.png, -04-standstill.png,
-05-mrm-succeeded.png; cast-a1-01-odd-exit.png, -02-takeover-request.png,
-03-manual.png. The dashboard's camera is one more CARLA client and sensor
on the hero during the act: the acts it recorded kept RTF 1.000 and passed
their tables.

cast-b5 is the b take with the fixed dashboard (stills
cast-b5-01-odd-exit.png ... -05-mrm-succeeded.png, each viewed: no text
cut off, no label over another). Two changes for it: during the island's
MRM the takeover panel adds one line, "island MRM overrides control;
Autoware's modes stay AUTONOMOUS" (the operation mode and control mode
rows read AUTONOMOUS while the island brakes, which a viewer could take
for Autoware driving on), and the ODD-exit label sits west of its cross,
clear of the polygon's outline. cast-a1's frames (no MRM, MANUAL) were
re-rendered offscreen with the new code, not re-recorded; the note does
not appear there. cast-b4 was refused at a 1-min load of 217 and its
files deleted; cast-b1 is kept.

Three cosmetic flaws of cast-b1, fixed in the dashboard after it was
recorded (cast-a1 has the fixes): the banner's last words cut off
("STOPPED - ISLAND MRM SUCCEEDED (COMFOR"; now "STOPPED SAFELY - ISLAND
MRM SUCCEEDED"), the mirrored LED's words cut off ("driver, take ov"), and
the ODD-exit label over the polygon's label on the map. A re-take of b
(cast-b2) never drove: Autoware stayed INITIALIZING at a 1-min load of 220
from other jobs; the next (cast-b3) was refused at load 47 after 900 s.

Not verified in C8: the encore on cast (not asked; the recipe takes it);
the physical LED on camera (no camera on the host; the LED on screen is
mirrored from the topic, and led_vs_trace shows the board's LED changed in
the same tick); a person's takeover at the booth (the act's scripted
button presses MANUAL); the cast on a display other than TurboVNC.

**Regression round (2026-10-18, evidence).** Main at `bac35cd` (phase 11's
supervised budgets and emergency response, phase 13's derived priorities,
nano-ros pin `d4bf898409`) with play_launch 0.18.3 (rlm v0.1.65), CSB
`3883f86` (acb `9ec6343` era, unchanged since C6), on CARLA through
`run-board.sh --sim carla`, each act on its own boot. Branch
`carla-regression` (worktree under /mnt/mx500, its own `just setup-cli`,
`just doctor` OK, host overlay built from the same tree). Images: the gate
image (`just board-build`, sha256 `404524a32c664b24...`, FLASH 575,884,
RAM 280,672, DTCM 117,584, ITCM 14,832, `# CONFIG_ISLAND_LED is not set`)
and the booth image (`just board-build-booth`, `d4cf6c1aac543c56...`,
FLASH 577,372, DTCM 117,792, ITCM 14,904, `CONFIG_ISLAND_LED=y`,
`CONFIG_ISLAND_BUTTONS=y`); both `priority-check [ok]` (transport [4, 4],
pool.app [5, 14], mrm 3, supervisor 2). Nothing in the contract or the
run tooling needed a change for play_launch 0.18.3; the model check,
`play_launch check --explain` and the SUMMARY read as on the planning
simulator.

| image | act | run | SUMMARY | table | trigger | trace window | RTF | junit | LED vs trace | load at act |
|---|---|---|---|---|---|---|---|---|---|---|
| gate | encore | rg-e3 | PASS | 8/8 (+1 n/a), total 3012.57 of 5228.67 ms; hazard_lights_on 545.49 ms | hpc-loss at (287.2, -129.4) | 11,900 B over 19.6 s, at the first drive | 1.000 | PASS | - | 12.04 |
| gate | b | rg-b1 | PASS | 16/16 (+1 n/a), total 16052.68 of 21393.67 ms; hazard_lights_on 173.49 | ODD EXIT segment (239.9, -129.4) | 22,128 B over 30.6 s, re-armed 4.00 s before the exit (go -> ack 57.5 ms) | 1.000 | PASS | - | 10.82 |
| gate | a | rg-a1 | PASS | 8/8; hazard_lights_on 295.63 | ODD EXIT segment (239.9, -129.4) | 19,874 B over 27.7 s, 4.00 s (52.7 ms) | 1.000 | PASS | - | 7.30 |
| booth | encore | rg-be2 | PASS | 8/8 (+1 n/a), total 3025.13 of 5228.67 ms; hazard_lights_on 635.43 | board SW2 (injected, inject -> seen 186.5 ms, seen -> SIGSTOP 1.72 ms) at (286.6, -129.4) | 12,124 B over 19.9 s, at the first drive | 0.998 | PASS | PASS (mrm_operating +0.1 ms, mrm_succeeded -0.1, normal +0.1) | 18.62 |
| booth | b | rg-bb1 | PASS | 16/16 (+1 n/a), total 14598.14 of 21393.67 ms; hazard_lights_on 243.93 | ODD EXIT segment (239.9, -129.4) | 21,066 B over 29.1 s, 4.00 s (105.9 ms) | 1.000 | PASS | PASS (operating -> succeeded LED 4498 ms, trace 4498.0) | 12.73 |
| booth | a | rg-ba1 | PASS | 8/8; hazard_lights_on 291.69 | board SW1 (injected, inject -> seen 213.5 ms, seen -> MANUAL request 38.31 ms) after ODD EXIT segment (239.9, -129.4) | 19,824 B over 27.6 s, 4.00 s (54.2 ms) | 1.000 | PASS | PASS (tor_off +0.3 ms) | 14.11 |

SUMMARY lines:

    SUMMARY rg-e3 encore: PASS; load 12.04 at act; table 8/8 PASS (+1 n/a), total 3012.57 of 5228.67 ms; trace-check PASS (window 2 of the boot), trace 11,900 of 53,248 B over 19.6 s, re-armed when the ego drove; stored 1 (silence-runtime x1); serial in act 1/1 (overruns/bad frames); heap peak 66216 of 107008 B; supervisor not driven, SWT0 fires 0, spin gap max 12.708 ms, priorities spin 3 / reaction 2 AGREE with the plan; sim carla, RTF 1.000, SSv2 junit PASS, trigger hpc-loss at (287.2, -129.4), vlimit 7.00 m/s asked, 4.17 selected
    SUMMARY rg-b1 b: PASS; load 10.82 at act; table 16/16 PASS (+1 n/a), total 16052.68 of 21393.67 ms; trace-check PASS (window 2 of the boot), trace 22,128 of 53,248 B over 30.6 s, re-armed 4.00 s before the ODD exit (go -> ack 57.5 ms); stored 1 (silence-runtime x1); serial in act 0/0 (overruns/bad frames); heap peak 66264 of 107008 B; supervisor not driven, SWT0 fires 0, spin gap max 13.226 ms, priorities spin 3 / reaction 2 AGREE with the plan; sim carla, RTF 1.000, SSv2 junit PASS, trigger ODD EXIT segment (239.9, -129.4) outside the ODD polygon, odd_monitor -> gate -0.24 ms, vlimit 7.00 m/s asked, 4.17 selected
    SUMMARY rg-a1 a: PASS; load 7.30 at act; table 8/8 PASS; trace-check PASS (window 2 of the boot), trace 19,874 of 53,248 B over 27.7 s, re-armed 4.00 s before the ODD exit (go -> ack 52.7 ms); stored 1 (silence-runtime x1); serial in act 0/0 (overruns/bad frames); heap peak 65992 of 107008 B; supervisor not driven, SWT0 fires 0, spin gap max 12.703 ms, priorities spin 3 / reaction 2 AGREE with the plan; sim carla, RTF 1.000, SSv2 junit PASS, trigger ODD EXIT segment (239.9, -129.4) outside the ODD polygon, odd_monitor -> gate 0.88 ms, vlimit 7.00 m/s asked, 4.17 selected
    SUMMARY rg-be2 encore: PASS; load 18.62 at act; table 8/8 PASS (+1 n/a), total 3025.13 of 5228.67 ms; trace-check PASS (window 2 of the boot), trace 12,124 of 53,248 B over 19.9 s, re-armed when the ego drove; stored 1 (silence-runtime x1); serial in act 0/0 (overruns/bad frames); heap peak 66216 of 107008 B; supervisor not driven, SWT0 fires 0, spin gap max 12.707 ms, priorities spin 3 / reaction 2 AGREE with the plan; sim carla, RTF 0.998, SSv2 junit PASS, trigger board SW2 (injected, island uptime 142568 ms, inject -> seen 186.5 ms, seen -> SIGSTOP 1.72 ms) at (286.6, -129.4), vlimit 7.00 m/s asked, 4.17 selected
    SUMMARY rg-bb1 b: PASS; load 12.73 at act; table 16/16 PASS (+1 n/a), total 14598.14 of 21393.67 ms; trace-check PASS (window 2 of the boot), trace 21,066 of 53,248 B over 29.1 s, re-armed 4.00 s before the ODD exit (go -> ack 105.9 ms); stored 1 (silence-runtime x1); serial in act 0/0 (overruns/bad frames); heap peak 66264 of 107008 B; supervisor not driven, SWT0 fires 0, spin gap max 12.727 ms, priorities spin 3 / reaction 2 AGREE with the plan; sim carla, RTF 1.000, SSv2 junit PASS, trigger ODD EXIT segment (239.9, -129.4) outside the ODD polygon, odd_monitor -> gate -0.23 ms, vlimit 7.00 m/s asked, 4.17 selected
    SUMMARY rg-ba1 a: PASS; load 14.11 at act; table 8/8 PASS; trace-check PASS (window 2 of the boot), trace 19,824 of 53,248 B over 27.6 s, re-armed 4.00 s before the ODD exit (go -> ack 54.2 ms); stored 1 (silence-runtime x1); serial in act 0/0 (overruns/bad frames); heap peak 65992 of 107008 B; supervisor not driven, SWT0 fires 0, spin gap max 12.727 ms, priorities spin 3 / reaction 2 AGREE with the plan; sim carla, RTF 1.000, SSv2 junit PASS, trigger board SW1 (injected, island uptime 127114 ms, inject -> seen 213.5 ms, seen -> MANUAL request 38.31 ms) after ODD EXIT segment (239.9, -129.4) outside the ODD polygon, odd_monitor -> gate 1.11 ms, vlimit 7.00 m/s asked, 4.17 selected

The rows are the planning simulator's current terms: the a table has 8 rows
and b 16 (phase 11 added the supervised route and the settle judged as one
sum), and the encore and b budgets are the phase 11/13 derivations (5228.67
and 21393.67 ms); every observed value is inside them with the margins of
C3-C6. Phases 11 and 13 hold on CARLA: the supervisor record reads not
driven and SWT0 fires 0 in every act (no route deadline missed), the
longest feed-to-feed gap is 12.70-13.23 ms, and the kernel's thread
priorities at the first spin agree with the derived plan in all six. Button
records after the booth acts (`board_buttons.py show`): rg-be2 one press,
SW2 accepted (NORMAL); rg-ba1 one press, SW1 accepted; rg-bb1 none;
`gpio_errors 0`. `orphans: 0` after each.

The open C6 item is closed: act b on the booth image with the buttons on
(rg-bb1) passes with the same table and LED record as the gate image's b.
`hazard_lights_on` read a value in all six acts (encore 545-635 ms, b
174-244 ms, a 292-296 ms), each act on a fresh boot and a fresh ego.

What it took:

| run | what failed | fix |
|---|---|---|
| rg-e1, rg-e2 | flash failed: `Memory transfer fault (FAULT ACK) @ 0x20002c00` (the flash algorithm's RAM), then on the retry `@ 0x00423000` while erasing (the half-programmed sector); the booth image's first flash did the same (`@ 0x20004800`, then `@ 0x0041c800`) | `pyocd erase --sector` of that one 8 KiB sector, then the flash passed; run-board now does it (up to 3 tries; a RAM fault is retried, a fault inside the image's flash range erases that sector first). w9c-e1 exercised it: `flash try 1: FAULT ACK in RAM at 0x20004800`, `flash try 2: ... at 0x0041c400; erasing the sector 0x0041c000`, then programmed |
| rg-be1 | no verdict: run-board.sh was edited while the run executed it (bash reads a script as it runs) and died with a syntax error at step 5, leaving its CARLA, csb, ego, router and gateway process groups running | those groups stopped by pgid (SIGINT, then SIGKILL), ports and GPU checked free; rerun (rg-be2). Never edit run-board.sh while an act runs |

The three bugs carried from C5/C6:

- **c6-a1's timer overruns** (3 `timer-overrun-runtime timer`, 29, 9 and 9
  dropped activations, after arming and before the window): not
  recurred, 0 in all six acts. nano-ros checks every timer's overrun
  counter on each spin and stores the delta, so 29 is one spin gap of
  about 29 periods (about 1 s on the 33 ms emergency operator, 2.9 s on a
  100 ms timer). Two candidate causes were tested and ruled out on the
  bench (router and gateway up, the island joined, no Autoware): a pyocd
  attach (`readout.py --serial-only`, the act start's read and the re-arm
  helper's attach): 20 attaches in 18 s left the longest feed-to-feed gap
  at 11.6 ms and the serial counters at 0 overruns, 0 bad frames; and the
  button bridge (it attaches only at the re-arm, after c6-a1's overruns).
  One mechanism that does stall the spin was found: with the gateway gone,
  about 90 s later (the 60 s lease, then the session lost), the spin
  stalls about 12.3 s at a time (gaps 12263 and 12275 ms on the bench) and
  SWT0 latches the safe-state output at the first timeout (uptime
  180597 ms), as designed; the same 12.3 s gap was in the supervisor record
  after rg-b1's teardown. It needs a lost session, which no act had. The
  cause of c6-a1's overruns is not known; the supervisor record that the
  C6 image lacked (longest gap with its end uptime) now dates any
  recurrence.
- **tm-b1's silent re-arm helper** (nothing in 22 s, act FATAL): the
  helper is `python3 tools/timeline/readout.py`, whose imports (pyocd and
  pyelftools, from ~/.local on /home, the spinning disk) block on that
  disk under other jobs' I/O. Measured on 2026-10-18: `import
  pyocd.core.helpers, elftools.elf.elffile` took 38 s, and an `import
  pyocd` over 6 min at an I/O pressure of 87 % (`/proc/pressure/io` some
  avg60), the process in D state in `read_extent_buffer_pages`; the probe
  and the session take 0.1 s. tm-b1 ran from the main checkout on /home
  too. The helper now prints a stamped line per phase (`re-arm helper
  up`, `symbols read`, `pyocd imported`, `probe chosen`, `session open`,
  each `at +<s> s` of its own start), the act keeps them in its `rearm`
  event and prints them in the FATAL line, and pyocd's probe choice no
  longer waits forever for a probe. In this round: up +0.01 s, symbols
  +0.15, pyocd imported +0.33, probe +0.34, session +0.40 (rg-b1).
- **In-run bad frames with no UART error** (docs/serial-link.md 10, 11.4,
  11.5): 0 in this round. Over the six acts (15,762 frames received by the
  island, 2,137-3,161 per act, read at each readout since boot): one bad
  frame, in rg-e3, with one UART overrun in the same act window, so a byte
  lost in the RX FIFO, not the case that is open; no ring overflow, no
  framing, noise or parity error anywhere. The data does not allow a
  cause for the open case (none occurred, and the gate image carries no
  frame capture); the bench rules out the SWD attach as a source of
  overruns.

Not verified in the regression round: the physical presses (injected, as
C6); `--keep-boot` chains; the encore and acts under the planning
simulator with this image (phase 13's own rounds); the overrun in rg-e3
(its instant is not recorded: the counters are read twice per act).

**Found in the round: a supervisor latch while driving (fixed).** w9c-b2
(the W9 gate below, gate image of this round) ended with no verdict: the
ego stopped at x 251.9, 12 m before the ODD exit, because the island had
latched its safe-state output and its direct path commanded the emergency
stop. The supervisor record: `safe-state output LATCHED by route deadline
at uptime 279001.045 ms`; route 1 (the executor's supervised route,
mrm_handler/call_mrm, `mechanism: timer`) `deadline verdicts=1 ... first
verdict at 279001.028 ms for the due at 279000 ms (+1.028 ms)`, one in
27,299 arms; the executor stored no `route-deadline-runtime` or
`route-latency-runtime` verdict and never called the reaction hook (`hook
calls=0`), so on its own clock the route was answered in time; the
longest feed-to-feed gap was 12.35 ms and no timer overran. Cause: the
supervisor armed route 1 at `k_uptime_get() + ceil(us / 1000)`, and with
a 1 ms kernel tick `k_uptime_get()` is the floor of now, so the armed due
fell up to 1 ms before the executor's (take + route_deadline_ms on its
microsecond clock) whenever now's sub-millisecond part exceeded the
rest's. A route answered in its last millisecond was a verdict there and
on time for the executor. island_supervisor.c now computes the due from
the cycle counter in microseconds (the executor's clock), rounded up, so
the k_timer is at or after the executor's due and at most 1 ms later.
The supervised path still catches an overrun on that image: rg-ov2, the encore on CARLA with a
300 ms fault-tick overrun (`RB_OVERRUN=300 RB_TRIGGER=button`), PASS,
table 9/9 (+5 n/a), supervised 7/7 PASS, route 0's verdict 0.03 ms after
its due, the safe-state output 0.04 ms, the direct braking command
0.58 ms, total 3562.44 of 5379.67 ms.

    SUMMARY rg-ov2 encore: PASS; load 13.78 at act; table 9/9 PASS (+5 n/a), supervised 7/7 PASS; trace-check PASS (window 3 of the boot), trace 11,264 of 53,248 B over 16.6 s, re-armed when the ego drove; stored 8 (max-latency-runtime x3, release-jitter-runtime x1, silence-runtime x1, timer-overrun-runtime x3); serial in act 2/3 (overruns/bad frames); heap peak 66256 of 107008 B; supervisor latched (route deadline), SWT0 fires 0, spin gap max 308.056 ms, priorities spin 3 / reaction 2 AGREE with the plan; sim carla, RTF 0.999, SSv2 junit PASS, trigger button

(Its 3 timer overruns, 754 ring overflows and 2 UART overruns are the
injected 300 ms stall's.) rg-ov1, the same with the scenario's trigger,
took the overrun about 500 ms into the MRM, on a later call_mrm tick:
scenario.py armed it only after the scenario's trigger had fired, and
SWT0 caught the stall instead (still PASS). run-board now refuses
`RB_OVERRUN` with `--sim carla` unless `RB_TRIGGER=button`.

**Found after it: the late notice of an answered route (fixed).** Route
1's k_timer was armed after every spin from the executor's earliest pending
due (`island_supervisor_spin_after`, called by the `nros_cpp_spin_once`
wrapper in spin_hook.c after the real spin returns), and nothing else
cleared it. The executor answers a route earlier: `route_judge` clears the
row's `ROUTE_PENDING` (an atomic in its monitor cell) at the end of the
dispatch that publishes the output, on its microsecond clock. A route
answered before its due by a spin that then ran past the due (other
callbacks, transport work; spin gaps up to ~13 ms) found route 1 still
armed at the expiry, so the supervisor latched and the direct path
commanded the emergency stop while the executor judged the route on time
and recorded nothing. Routes 0 and 2 do not share it: the handler clears
route 0 itself at call_mrm's EXIT inside the tick (`island_supervisor_done`),
and route 2 is judged at its due from the speed the kinematic_state take
noted, also inside its callback; neither waits for a spin to return.

Fix: nano-ros phase-503 W7 (PR #2379, `RouteWatch`;
`nros_cpp_executor_route_watch` / `nros_cpp_route_watch_next_due_us`) reads
the executor's route cells from any thread without touching the executor.
The supervisor fills the watch once on the spin thread and asks it at route
1's expiry: a take still unanswered at or after its deadline is the miss,
judged at the same instant as before; an answered route is not a miss
(`answered_at_expiry` in the record); a later take re-arms the timer to its
own due. An answer between the executor's due and the timer's (the at most
1 ms rounding) reads as answered there, and the executor judged it overdue
at completion and called the reaction hook, which latches. Memory: the
record grows 20 B and the watch 13 B (DTCM). The image needs nano-ros PR
#2381 too: since issue 1299 the Zephyr module forwarded the zenoh locator
as a compile definition, which CMake drops when it contains `#` (every
serial locator), so a serial image opened no session (issue 1955; bisected
on the board to 2ccf662c0d).

The late notice is injectable: `violations.py late-return N`
(`island_debug_late_return_ms`, CONFIG_ISLAND_DEBUG_SPIN_STALL), or
`RB_LATE_RETURN=<ms>` on run-board.sh, holds the spin that answered route 1
until N ms past its due before the supervisor hears of it. Board runs
(2026-10-18, planning simulator unless noted):

| run | image | case | result |
| --- | --- | --- | --- |
| sl-before-a2 | main's supervisor + the knob (pin d4bf898409) | a, `RB_LATE_RETURN=5` | FAIL: latched by route 1 at its due +0.031 ms, executor no `route-deadline-runtime`, hook calls 0 (the round's finding, reproduced) |
| sl-late-a1 | fixed | a, `RB_LATE_RETURN=5` | PASS 8/8; not driven; the expiry read the route answered 0.027 ms after its due |
| sl-miss-a2 | fixed | a, the handler's tick overruns 200 ms after its publishes (`violations.py overrun 200`): route 1 answered late | latched by route 1 at its due +0.035 ms, output +0.051 ms; executor `route-deadline-runtime` and the hook at completion (the act stops by design) |
| sl-e1, sl-a1, sl-b1 | fixed | encore, a, b | PASS 8/8, 8/8, 16/16; not driven |
| sl-ov2 | fixed, CARLA | encore, `RB_OVERRUN=300 RB_TRIGGER=button` | PASS, supervised 7/7; route 0 verdict 0.04 ms after its due, output 0.06 ms, direct braking 0.82 ms |
| sl-ce1 | fixed, CARLA | encore | PASS 8/8; not driven |

    SUMMARY sl-late-a1 a: PASS; load 10.26 at act; table 8/8 PASS; trace-check PASS, trace 29,544 of 53,248 B over 52.8 s; stored 7 (hazard-detected x2, hazard-recovered x2, release-jitter-runtime x1, silence-runtime x1, timer-overrun-runtime x1); serial in act 0/0 (overruns/bad frames); heap peak 66144 of 107008 B; supervisor not driven, SWT0 fires 0, spin gap max 115.856 ms, route 1 answered by its expiry 1, priorities spin 3 / reaction 2 AGREE with the plan
    SUMMARY sl-ov2 encore: PASS; load 8.28 at act; table 9/9 PASS (+5 n/a), supervised 7/7 PASS; trace-check PASS (window 3 of the boot), trace 11,326 of 53,248 B over 16.7 s, re-armed when the ego drove; stored 12 (hazard-detected x1, max-latency-runtime x3, release-jitter-runtime x1, timer-overrun-runtime x3); serial in act 0/1 (overruns/bad frames); heap peak 66352 of 107008 B; supervisor latched (route deadline), SWT0 fires 0, spin gap max 312.139 ms, priorities spin 3 / reaction 2 AGREE with the plan; sim carla, RTF 1.000, SSv2 junit PASS, trigger button

(sl-late-a1's release-jitter and timer-overrun verdicts and its 115.9 ms
gap are the injected hold's.)

Merged main `f8a3867` (pin ebf7140191), the gate image rebuilt and flashed:
the island joins over the serial link and both acts pass, the supervisor
not driven.

    SUMMARY sl-main-e1 encore: PASS; load 7.32 at act; table 8/8 PASS (+1 n/a), total 3466.21 of 5228.67 ms; trace-check PASS, trace 19,278 of 53,248 B over 38.1 s; stored 5 (hazard-detected x2, hazard-recovered x2, silence-runtime x1); serial in act 0/0 (overruns/bad frames); heap peak 66312 of 107008 B; supervisor not driven, SWT0 fires 0, spin gap max 12.545 ms, priorities spin 3 / reaction 2 AGREE with the plan
    SUMMARY sl-main-a1 a: PASS; load 16.78 at act; table 8/8 PASS; trace-check PASS, trace 28,636 of 53,248 B over 51.2 s; stored 5 (hazard-detected x2, hazard-recovered x2, silence-runtime x1); serial in act 0/0 (overruns/bad frames); heap peak 66144 of 107008 B; supervisor not driven, SWT0 fires 0, spin gap max 13.035 ms, priorities spin 3 / reaction 2 AGREE with the plan

**The W9 gate on the board (2026-10-18).** Branch `w9-hazard-stamp`
`73c6e59` (the island's hazard command restamped on the host for
vehicle_cmd_gate, island_restamp; hazard_relay the one publisher of
`/system/hazard_lights_cmd`, W18's topic_tools relay removed), host only;
the board image unchanged in what it publishes (this round's gate image;
w9c-b3 and the planning-simulator runs on the image with the supervisor
fix). CARLA: the W9 host overlay (`just l3-host-ws` from that branch) in
place of build/l3-host-ws; planning simulator: `L3_IMAGE=
sai-l3-autoware:1.5.0-w9` (built from the branch) and `RB_HOST_WS` the W9
overlay. `hazard_lights_on` is from the hazard event to the vehicle's
hazard report ENABLE (the probe):

| sim | act | run | RB_HAZARD_RELAY | SUMMARY | hazard_lights_on (ms) | RTF / junit | load at act |
|---|---|---|---|---|---|---|---|
| CARLA | encore | w9c-e1 | - | PASS 8/8 (+1 n/a), total 2991.04 | 560.89 | 1.005 / PASS | 19.14 |
| CARLA | a | w9c-a1 | - | PASS 8/8 | **-** | 1.000 / PASS | 17.75 |
| CARLA | b | w9c-b1 | - | PASS 16/16 (+1 n/a) | **25810.85** (the vehicle lit after the act) | 1.000 / PASS | 22.39 |
| CARLA | a | w9c-a2 | 1 | PASS 8/8 | 341.93 | 0.999 / PASS | 17.09 |
| CARLA | b | w9c-b2 | 1 | no verdict (the supervisor latch above) | - | - / PASS | 32.36 |
| CARLA | encore | w9c-e2 | 1 | PASS 8/8 (+1 n/a), total 3014.07 | 572.07 | 1.004 / PASS | 10.82 |
| CARLA | b | w9c-b3 | 1 | PASS 16/16 (+1 n/a), total 14642.80 | 368.04 | 1.000 / PASS | 6.24 |
| planning | encore | w9p-e1 | 1 | PASS 8/8 (+1 n/a), total 3519.83 | 599.78 | - | 10.04 |
| planning | a | w9p-a1 | 1 | PASS 8/8 | 299.64 | - | 10.65 |
| planning | b | w9p-b1 | 1 | PASS 16/16 (+1 n/a), total 15668.37 | 442.42 | - | 31.94 |

- **hazard_relay must run.** No run-board run started takeover_demo's
  hazard_relay (the container starts Autoware only; `--sim carla` starts
  the gate, the probe and odd_monitor). With W18's relay gone,
  `ros2 topic info /system/hazard_lights_cmd` during w9c-e1 read
  `Publisher count: 0` (one subscriber, the selector), and outside an
  EMERGENCY_STOP the island's ENABLE never reached the vehicle: w9c-a1
  `-`, w9c-b1 25.8 s. `RB_HAZARD_RELAY=1` (carla-regression) starts it at
  step 6; with it every act reads a value and its log has `system hazard
  lights -> ENABLE` at each takeover request. The variable is off by
  default because with W18's relay still in the overlay the two race; it
  should default on when W9 merges.
- **The emergency path**: the restamp's log line per change (`hazard
  lights 2: island stamp 111.772625687, host stamp 0.000000000` ... on
  CARLA, sim-time host stamps; on the planning simulator `island stamp
  3.473045418, host stamp 1792297565.516803475`), and no `HazardLightsCommand
  is not received yet` line in any container log of the three planning
  acts.
- **Against the expectations**: encore 561-600 ms and a 300-342 ms are in
  range; b 368 ms on CARLA, 442 ms on the planning simulator (expected
  100-400). Before W9, this round's own CARLA acts read encore 545-635 ms,
  b 174-244 ms, a 292-296 ms (W18's relay forwarding the island's
  command).
- **A hazard ENABLE before the act on CARLA**: in w9c-e1, w9c-a1 and
  w9c-b1 the island raised its init-timeout EMERGENCY_STOP before the act
  (the availability's first raw sample 28.0-34.8 s after the probe
  started, the braking stream at 24.2-26.0 s; in the six acts before W9
  both came together at 18.2-24.7 s and the island stayed NORMAL), and
  the vehicle's hazards then read ENABLE for 20-49 s after the island
  went back to NO_COMMAND (w9c-a1: 27.94-76.95 s), cleared before the
  act's fault each time. w9c-a2, w9c-e2 and w9c-b3 had no such
  emergency and no ENABLE before the act. Not established: why the
  availability started late in those three runs, and whether the hold is
  the gate's stamp rule on a paused `/clock`.

**acb's MANUAL driver through the junction (c3-a6, 2026-10-18).** acb
`d59ba64` (branch fix/manual-driver-junction: the driver commits to its
lane, 4 m lookahead, a speed limit for curves and lane ends; it brings
acb main 5f9c54c..7bd709c along, carla 0.15.1 and a command watchdog that
disarms in MANUAL), checked out detached in the CSB checkout's
src/autoware_carla_bridge and built with CSB's `just build` (51
packages). Act a with c3-a6's case, the route's goal delayed 25 s (a
temporary copy of `town01_island_takeover.xosc` with `delay="25"` on
`reach_goal`, not committed), then the stock acts, each on the gate image
with the supervisor fix:

| run | act | SUMMARY | junit | `CARLA collision` in csb.log | newest ~/.ros/csb/contacts/*.json | hazard_lights_on (ms) |
|---|---|---|---|---|---|---|
| acb-a1 | a, goal delayed 25 s | PASS 8/8, RTF 1.000 | failures=0 errors=0 | 0 | `"contacts": []` | 360.79 |
| acb-ra | a | PASS 8/8, RTF 1.000 | failures=0 errors=0 | 0 | `[]` | 262.83 |
| acb-rencore | encore | PASS 8/8 (+1 n/a), total 3065.30 of 5228.67 ms, RTF 1.013 | failures=0 errors=0 | 0 | `[]` | 660.74 |
| acb-rb | b | PASS 16/16 (+1 n/a), total 14750.43 of 21393.67 ms, RTF 1.000 | failures=0 errors=0 | 0 | `[]` | 392.09 |

The goal-delayed act a, where c3-a6's driver ran wide in the T-junction
past the goal and hit a pole, now ends at the goal with no contact. The
CSB checkout's acb is back on `b463171` (its main, the CSB gitlink) and
rebuilt; d59ba64 stays on its branch.

**Serial over the whole day** (21 acts with a verdict or not, the injected
stall of rg-ov2 left out): 64,571 frames received by the island; 8 bad
frames, each in an act with one UART overrun (rg-e3, w9c-e1, w9c-a1,
w9c-e2, w9c-b3, w9p-e1, acb-ra, acb-rencore), no ring overflow, no
framing, noise or parity error. The open case of docs/serial-link.md (a
bad frame with no error at all) did not occur. The overruns themselves
are not rare on this image: one in 5 of the 7 encores, 2 of 7 a and 1 of
7 b acts; each loses one frame. When in the act they fall is not
recorded (two counter reads per act).

**nano-ros 54a1146d67 and CSB 0b80299 (2026-10-19).** The gate image on
nano-ros pin 54a1146d67 (DTCM 112,464 B; plan transport 4, mrm 5 in
pool.app, supervisor 3: the mrm tier names no `above = "transport"`,
nano-ros #1967), the CSB checkout at 0b80299 with acb 7d1b1ce (its
gitlink; acb's `max_velocity` stays at Autoware's 4.17 m/s; CSB's
Autoware fix overlay of roadmap 042 is not built, so the ego runs stock
Autoware 1.5.0), built with CSB's `just build` (51 packages). One fresh
boot per act, `tools/timeline/run-board.sh --sim planning|carla`:

| sim | act | run | SUMMARY | junit | hazard_lights_on (ms) |
|---|---|---|---|---|---|
| planning | encore | fn-pe | PASS 8/8 (+1 n/a), total 3481.62 of 5228.67 ms; spin gap max 13.239 ms; serial 0/0 | - | 4726.18 |
| planning | a | fn-pa | PASS 8/8; spin gap max 13.423 ms; serial 0/0 | - | 249.97 |
| planning | b | fn-pb | PASS 16/16 (+1 n/a), total 15800.75 of 21393.67 ms; spin gap max 12.717 ms; serial 0/0 | - | 275.28 |
| CARLA | encore | fn-ce | PASS 8/8 (+1 n/a), total 3102.72 of 5228.67 ms; RTF 1.004; spin gap max 13.244 ms; serial 0/0 | failures=0 errors=0 | 658.03 |
| CARLA | a | fn-ca | PASS 8/8; RTF 1.000; spin gap max 13.084 ms; serial 1/1 | failures=0 errors=0 | 363.26 |
| CARLA | b | fn-cb | PASS 16/16 (+1 n/a), total 14650.42 of 21393.67 ms; RTF 1.000; spin gap max 12.726 ms; serial 0/0 | failures=0 errors=0 | 292.15 |

Every act: supervisor not driven, SWT0 fires 0, priorities spin 5 /
reaction 3 AGREE with the plan, heap peak 66,320-66,536 of 107,008 B.
Serial is overruns/bad frames in the act; fn-ca's one overrun lost one
frame, with no ring overflow.

- **The planning encore's hazard lights are late or absent**: fn-pe's
  vehicle status reads ENABLE 4726.18 ms after the stop, near standstill.
  Over the day's seven other plain planning encores on this host side (pin
  628675932, with and without #2398's tier change: mrm above or below the
  transport), two read 4624-4721 ms and five `-`: the island's ENABLE on
  `/system/emergency/hazard_lights_cmd` and hazard_relay's `system hazard
  lights -> ENABLE` happen in every one, but the simulator's
  `/vehicle/status/hazard_lights_status` stays DISABLE until about
  standstill or through the act. The CARLA encore and the planning a and
  b read 250-365 ms. Not established: which stage between the selector
  and the simulator holds it while the gate is stopped.
- **nano-ros 941132a82c does not boot on the board**: phase-397 W2 put the
  executor's `WakeCtx` (`repr(align(64))`) in an `Arc`, and the platform
  global allocator answered `align > 8` with null. The island panicked at
  boot (`memory allocation of 128 bytes failed`, boot record stuck at
  ExecutorReady, no arena allocation) and never joined. nano-ros #2400
  (in 628675932 and later) carves over-aligned blocks out of the platform
  heap.

**nano-ros fbd27da76d (2026-10-19).** The gate image on nano-ros pin
fbd27da76d (main after #2414: rlm v0.1.67 with the tier key `above =
"transport"`, play_launch d109f2ec, the derived spin period #2399, probe
sizing #2401, per-tier executor sizing #2404): DTCM 112,464 B, the same as
54a1146d67. The plan is unchanged: transport 4, mrm 5 in pool.app,
supervisor 3 (`[tiers.mrm]` names no `above`). The build notes the authored
`spin_period = "10ms"` as an override of the derived 33,333 us (the tier's
fastest release, the 30 Hz operator). `just sync` exits 0 with no
`ExecutorFull` and writes the four components' source metadata
(mrm_handler.json among them). Planning simulator, one fresh boot per act,
`tools/timeline/run-board.sh --sim planning`:

| act | run | SUMMARY | hazard_lights_on (ms) |
|---|---|---|---|
| encore | p4-pe1 | PASS 8/8 (+1 n/a), total 3490.93 of 5228.67 ms; spin gap max 12.535 ms; serial 0/0 | - |
| a | p4-pa | PASS 8/8; spin gap max 13.712 ms; serial 0/0 | 299.66 |
| b | p4-pb | PASS 16/16 (+1 n/a), total 15375.02 of 21393.67 ms; spin gap max 12.811 ms; serial 0/0 | 275.48 |

Every act: supervisor not driven, SWT0 fires 0, priorities spin 5 /
reaction 3 AGREE with the plan, heap peak 66,488-66,536 of 107,008 B. The
planning encore's hazard lights read `-`, the case above.

**nano-ros 77e4175e77 (2026-10-19).** The gate image on nano-ros pin
77e4175e77, main after RFC-0107 steps 1-3 (#2421 the arena floor only where
demand is unknown, #2423 launch remaps one const table in flash with no
runtime remap table on bare metal, #2424 extra sessions sized from the
backend count): DTCM 103,224 B (FLASH 598,512, RAM 280,680, ITCM 14,824).
The plan is unchanged: transport 4, mrm 5 in pool.app, supervisor 3.
Planning simulator, one fresh boot per act, `tools/timeline/run-board.sh
--sim planning`:

| act | run | SUMMARY | hazard_lights_on (ms) |
|---|---|---|---|
| encore | r7-pe | PASS 8/8 (+1 n/a), total 3448.50 of 5228.67 ms; spin gap max 12.871 ms; serial 0/0 | 4650.83 |
| a | r7-pa | PASS 8/8; spin gap max 13.249 ms; serial 0/0 | 249.26 |
| b | r7-pb | PASS 16/16 (+1 n/a), total 15050.16 of 21393.67 ms; spin gap max 12.475 ms; serial 0/0 | 149.47 |

Every act: supervisor not driven, SWT0 fires 0, priorities spin 5 /
reaction 3 AGREE with the plan, heap peak 66,320-66,536 of 107,008 B. The
planning encore's hazard lights are late, the case above.

**The derived spin period (2026-10-20, island issue 8).** The same pin
(77e4175e77) with `spin_period = "10ms"` removed from `[tiers.mrm]`: the
build prints `tier mrm spin period 33333 us, derived from member
mrm_emergency_stop_operator's release period` and no override note. DTCM
103,224 B (FLASH 598,728, RAM 280,680, ITCM 14,824). The spin period only
bounds an idle park: the executor parks on min(the period, the next timer,
the session's next event, a supervised route's due), and a subscription or
service arrival signals the wake object the park waits on, so arrivals do
not wait for it. Route 1 is re-armed after every spin from the executor's
own due and judged at its expiry from the executor's route cells, not from
the gap between spins, so a longer park cannot latch it. The longest
feed-to-feed gap is now ~34 ms (the 33.3 ms park plus the spin), still
about a ninth of SWT0's 300 ms. Planning simulator, one fresh boot per act,
`tools/timeline/run-board.sh --sim planning`, two rounds:

| act | run | SUMMARY | hazard_lights_on (ms) |
|---|---|---|---|
| encore | s1-pe | PASS 8/8 (+1 n/a), total 3427.84 of 5228.67 ms; spin gap max 34.425 ms; serial 0/0 | 4675.04 |
| a | s1-pa | PASS 8/8; spin gap max 34.583 ms; serial 0/0 | 125.74 |
| b | s1-pb | PASS 16/16 (+1 n/a), total 15700.10 of 21393.67 ms; spin gap max 34.341 ms; serial 0/0 | 200.04 |
| encore | s1-pe2 | PASS 8/8 (+1 n/a), total 3465.05 of 5228.67 ms; spin gap max 34.016 ms; serial 0/0 | 4675.11 |
| a | s1-pa2 | PASS 8/8; spin gap max 34.163 ms; serial 0/0 | 175.02 |
| b | s1-pb2 | PASS 16/16 (+1 n/a), total 15900.09 of 21393.67 ms; spin gap max 33.812 ms; serial 0/0 | 173.81 |

Every act: supervisor not driven (reaction thread wakes 0, timer expiries
0, deadline verdicts 0), SWT0 fires 0, priorities spin 5 / reaction 3 AGREE
with the plan, heap peak 66,488-66,680 of 107,008 B. The island spins about
28 % less (6,077-8,732 spins an act against 8,548-11,333 for r7). The
island's take - stamp medians (control_cmd 7.3-12.0 ms, kinematic_state
13.4-18.6 ms) sit inside the range of the planning runs at 10 ms; a park
that arrivals did not break would add about half a period (~17 ms) to
them. The b totals (15,700 and 15,900 ms against r7's 15,050) follow the
entry speed (3.04-3.06 m/s against 2.61) and the 10 Hz handler tick's phase
at the deadline (route 2.18 or ~101 ms, both seen at 10 ms). The planning
encore's hazard lights are late, the case above.
