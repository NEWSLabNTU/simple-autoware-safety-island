# CARLA + Autoware + the island on the board, with LEDs

Status: design, 2026-10-14. Not built except the LED prototype (section 3,
`CONFIG_ISLAND_LED`, measured on the board), the scenario-declared ODD
(section 2.5: odd_monitor reads it from the `.xosc`, unit-tested; the
scenario itself not yet run with odd_monitor), unit C1, the CARLA ego on the
island's domain (section 5, G1 passed; runbook demo/carla/README.md), unit
C2, acb's `allow_manual` (MANUAL accepted and reported, a scripted driver
holds the lane) and unit C3, the board attached to the CARLA ego, G2
passed (`run-board.sh --sim carla`: encore, a and b PASS at RTF 1.000 with
SSv2 junit PASS). The island keeps today's serial link
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
  never fires for the CARLA ego, see below.)
- `town01_island_odd.xosc` (run in C3 as the world of acts b and encore):
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
would end the ODD. The scenario caps the ego with `Performance maxSpeed
7.0` (m/s, 25.2 km/h), which SSv2 hands to Autoware as its velocity limit
(to be confirmed in C4); that leaves 4.8 km/h of margin over EKF twist
noise. An act on the speed bound is the same file with the cap above 30 km/h.

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

SW1/SW2 as the visitor's buttons (the W1/W11 alternative to a screen UI):

- **SW1 = take over.** The takeover is the HPC side's (a MANUAL control mode
  from the vehicle), not the island's. The island would publish a new topic,
  `/demo/driver/response` (std_msgs/Empty), which `takeover_hmi` already
  consumes and turns into `/control/control_mode_request` MANUAL. Cost: one
  publisher on the island (no receive buffer), a contract entry, and the
  `gpio-keys` input subsystem or a polled read in the handler's tick (no
  ISR: poll SW1 at 10 Hz, debounce two ticks).
- **SW2 = HPC loss.** Pressing it must not make the island lie about its
  inputs. It publishes `/demo/fault/inject` (Empty); a host helper SIGSTOPs
  the gate, exactly the encore's mechanism. A local fault injection inside
  the island (ignore the availability) would demonstrate nothing the
  contract measures.

Both buttons are a demo affordance, not a safety function: they are outside
the island's contract's hazards and the trace marks them as injections like
today's `press` edge.

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
| C4 | the scenarios: `town01_island_encore.xosc` (CustomCommandAction -> act daemon), `town01_island_odd.xosc` (written; ODD declared, 2.5) with `scenario_file:=` the same path; confirm SSv2 applies `Performance maxSpeed` as Autoware's velocity limit | each act triggered by the scenario at its place, three times back to back without a reflash (W2's re-arm); act a/b's `ODD EXIT` reason is `segment`, between x 239 and 241 | |
| C5 | LEDs on by default for the booth image (`CONFIG_ISLAND_LED=y` in a booth conf, not the gate image) | the LED record shows the act's transitions with uptimes matching the trace's `mrm_operating` / `mrm_succeeded` edges within one tick | |
| C6 | buttons: SW1 take over, SW2 HPC loss (3.4) | a visitor runs acts a and encore from the board alone | |
| C7 | the container (phase 2, also W10) | C3's gate with Autoware + acb in the image | |
| C8 | proof cast: a screencast of one act run end to end. A new 1920x1080 TurboVNC display `:3` (`/opt/TurboVNC/bin/vncserver :3 -geometry 1920x1080`; `:1`/`:2` are the user's 1240x900 desktops and `:9` another user's: never touched), recorded with `ffmpeg -f x11grab` from `:3`. On screen and readable at 1080p: the CARLA chase view of the hero; a map panel with the ODD polygon (2.5), the ego pose and a marker where the ODD exit fired; the takeover request (`/system/operation_mode/availability`, the operation mode, `/system/takeover_request/state`); the island's MRM state with its LED colour mirrored on screen (section 3.2's mapping, from `/system/fail_safe/mrm_state`; the host has no webcam for the board itself); wall-clock and simulation timestamps | one cast in which ODD exit -> takeover request -> island MRM -> stop are visible in that order | design only |
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
