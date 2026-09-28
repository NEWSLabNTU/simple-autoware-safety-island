# D8-C: Autoware (rmw_zenoh_cpp) and the S32K344 island (nano-ros) in one ROS domain over zenoh

Design brief for the RTSS@Work 2026 demo. Read-only research, 2026-09-28.
Repo HEAD e318253 (contract-params), nano-ros pin 91a9a1edc, host
ros-humble-rmw-zenoh-cpp 0.1.9 (zenoh-c 1.8.0 vendored), Autoware 1.5.0
(binaries in /opt/autoware/1.5.0, sources in ~/repos/autoware/1.5.0-ws/src).

Short version:

- The protocol layer is fine. The key-expression format, the liveliness tokens,
  the Humble type-hash literal and all 19 island message definitions match
  rmw_zenoh_cpp 0.1.9 and Autoware 1.5. The QEMU image showed it end to end:
  4 nodes and 23 topics in a host `ros2 node list` / `ros2 topic list` on
  domain 10.
- The link is not fine. At 115200 baud the UART is over capacity in BOTH
  directions, even with every stream cut to its contract rate. The main cost
  is Odometry, then the per-sample overhead. Autoware's vehicle_cmd_gate turns
  link starvation into an emergency stop: it needs an island heartbeat every
  0.5 s.
- Three semantic gaps show up only once the island shares a domain with the
  real Autoware graph:
  (1) `/api/operation_mode/state` is latched and publish-on-change. The
      island's volatile reader gets nothing on a late join, so the mode reads
      UNKNOWN and the island triggers MRM if the vehicle is driving.
  (2) `mrm_handler`'s two service clients start a graph-cache liveliness
      subscriber on `@ros2_lv/10/**`. That pulls the whole Autoware graph over
      the link.
  (3) The board image still cannot reach FirstSpin (the heap). That blocks
      everything.

Status legend used below: MEASURED (a run in this repo recorded it),
READ (read from source), ESTIMATE (arithmetic, to be measured).

---

## 1. How a nano-ros/zenoh-pico node and an rmw_zenoh_cpp node share a domain today

### 1.1 Topology primitive

zenoh-pico runs in CLIENT mode. nano-ros refuses peer mode (issue 0682), so a
router is mandatory. rmw_zenoh_cpp nodes run in PEER mode and connect to
`tcp/localhost:7447` by default
(`/opt/ros/humble/share/rmw_zenoh_cpp/config/DEFAULT_RMW_ZENOH_SESSION_CONFIG.json5`).
The island and Autoware meet only through a router: `rmw_zenohd`, or a chain of
routers. The router forwards to a client face only what that face declared
interest in. A unicast face is filtered; a multicast face is not (see 3c/CAN).

### 1.2 Data key expressions (READ, `nros-rmw-zenoh/src/keyexpr.rs`)

    <domain>/<topic without leading slash>/<pkg>::msg::dds_::<Type>_/TypeHashNotSupported

- The domain is the FIRST chunk. That is why a mismatch cannot be seen at the
  transport layer: the session opens, the router forwards, and nothing ever
  matches (experiments/serial-interop/README.md).
- Humble (the default build, no `ros-iron`/`ros-jazzy` feature) uses the
  literal `TypeHashNotSupported`. There is no RIHS01 prefix, in keys or tokens.
  Subscriptions and service clients use `*` for the hash chunk.
- Type names are DDS-mangled. `DdsTypeName` turns `pkg/msg/T` into
  `pkg::msg::dds_::T_`. An unmangled `/` would split the key (issue 0824).
- Services use the same shape. A queryable is declared at the service key,
  e.g. `10/mrm_handler/describe_parameters/rcl_interfaces::srv::dds_::DescribeParameters_/TypeHashNotSupported`
  (docs/boot-through.md, iteration 5).
- Every publication carries the rmw attachment: 33 B (int64 sequence number,
  int64 source timestamp, VLE length 16, then a 16-byte GID). With
  `safety-e2e` it is 37 B.

### 1.3 Liveliness tokens (READ, `nros-rmw-zenoh/src/shim/mod.rs:474-720`)

    node:   @ros2_lv/<d>/<zid>/0/0/NN/%/<ns%>/<node>
    entity: @ros2_lv/<d>/<zid>/0/<eid>/{MP|MS|SS|SC}/%/<ns%>/<node>/<%topic>/<Type_>/TypeHashNotSupported/<qos>
    qos:    <rel>:<dur>:<hist>,<depth>:,:,:,,     rel 1=RELIABLE 2=BEST_EFFORT; dur 1=TL 2=VOLATILE; hist 1=KEEP_LAST

- `/` becomes `%` in topic and namespace. The root namespace is `%`.
- The ZID is LSB-first hex. Since issue 0864 it is new on every boot, so a
  reset board is a NEW participant.
- All four island nodes share ONE zenoh session, so they share one zid, and
  every node uses node-id 0. Entity ids are unique per session (issue 0292).
  The QEMU run lists all four nodes correctly. Whether `ros2 node info` puts
  each entity under the right node is not verified (see Open Questions).
- The QoS in the token is the GRANTED profile (`shim/qos.rs`), not the one
  requested. Empty deadline/lifespan/liveliness fields read as defaults.
- `book/src/internals/rmw-zenoh-protocol.md` is stale on two points. It says
  tokens carry `RIHS01_`, and it shows entity ids pinned to `0/11`. The code
  and the W7 router logs (`@ros2_lv/10/.../3/MP/...`) are what is true.

### 1.4 Type-hash and type-identity requirements

- Humble uses no hash, so there is no check on either side. A structural
  mismatch between the island's generated types and Autoware's would be a
  SILENT CDR misparse.
- Checked for this brief: all 19 island interface definitions (types and the
  OperateMrm service) are field-for-field identical (comments stripped) to
  `/opt/autoware/1.5.0/share/<pkg>/{msg,srv}`. The types are
  OperationModeState, MrmState, Control, Lateral, Longitudinal, VelocityLimit,
  VelocityLimitClearCommand, VelocityLimitConstraints,
  autoware_planning_msgs/RouteState, GearCommand, HazardLightsCommand,
  TurnIndicatorsCommand, ControlModeReport, SteeringReport, VelocityReport,
  OperationModeAvailability, MrmBehaviorStatus and EmergencyHoldingState.
- If nano-ros is ever built with `ros-jazzy`, every key changes to `RIHS01_...`
  and stops matching a Humble host. Keep the Humble default.

### 1.5 What W7 (and W8) already proved

| claim | evidence | status |
| --- | --- | --- |
| zenoh-pico 1.7.x talks to zenoh-c 1.8 over serial | Z_INIT/Z_OPEN both ways; router `New transport opened` | MEASURED (talker example, and the island image 6/6 boots) |
| host CLI sees a board node and data over serial | `/talker` in `ros2 node list`; `topic echo /chatter` streamed | MEASURED once, flaky 1-in-3 for the talker (README) |
| island image registers on the router over serial | router log shows `@ros2_lv/10/...` tokens from the board | MEASURED (W7) |
| the island's nodes stay up | NO. Registration failed at stop_mode_operator's 3rd TRANSIENT_LOCAL publisher (retention pool 2). Every entity was undeclared within 0.25 s; the router expired the link 10 s later. Nodes lived ~0.6 s per boot, too short for a CLI query. | MEASURED (W7, docs/board-facts.md "Z1b") |
| pool fix | TL pool now derived = 5, slot 105 B (nano-ros PR #1311, issue 1498) | MEASURED on QEMU (W8) |
| full graph visible to rmw_zenoh_cpp 0.1.9 | QEMU mps2-an385 over TCP: 4 nodes, 23 island topics, domain 10 | MEASURED (`build/emulation/qemu-20260925T211712.graph.txt`) |
| board reaches FirstSpin | NO. The heap needs about 190 KB at FirstSpin against 94 KB on the board. It is the parameter services (24 queryables). | MEASURED on QEMU; board links but is RAM-short (docs/boot-through.md) |

So the protocol compatibility of every island entity is proven, but on the
TCP road. On serial, only the handshake and the token registration are proven,
and only up to the retention-pool failure.

### 1.6 F6: the domain is baked from Kconfig

- The image's session domain is `CONFIG_NROS_DOMAIN_ID` (Kconfig default 0,
  `third-party/nano-ros/zephyr/Kconfig:1812`). `system.toml`'s
  `domain_id = 10` never reaches the image on this build road.
  The island entries use `nano_ros_add_executable`
  (`NanoRosEntry.cmake`). The agreement check that refuses a disagreement
  (`nros_system_check_domain_agreement`, phase-460 W4, issue 1423) runs only
  in `nros_system_generate`. RFC-0049 keeps Kconfig as the single writer on
  purpose.
- There is NO runtime override on Zephyr (no environment, no `--ros-args`).
  Changing the domain means rebuild and reflash.
- On the host side the domain exists only in the keys. `rmw_zenohd` has no
  domain handling at all: its binary contains no `ROS_DOMAIN_ID` string. One
  router can carry several domains, and they stay separated only by the key
  prefix. That is why a stranger's island on the same router is a hazard only
  when the domains are equal. Every rmw_zenoh_cpp process takes the domain
  from `ROS_DOMAIN_ID` through rcl.
- Current state: `CONFIG_NROS_DOMAIN_ID=10` is stated in `island-serial`,
  `qemu-serial` and `qemu-ethernet`, and is confirmed in `build-board`,
  `build-board-w8` and `build-qemu` `.config`. It is NOT stated in
  `src/zephyr_entry/snippets/island-ethernet/ethernet.conf`, so the Ethernet
  board image would join domain 0. The qemu-ethernet snippet's comment already
  says so.

How to make the domain match and check it:
1. Pick one domain for the whole demo: 10, as in `.envrc` and the bringup.
   Autoware, the scenario driver, RViz and every CLI need `ROS_DOMAIN_ID=10`.
   The router does not care.
2. Move `CONFIG_NROS_DOMAIN_ID=10` out of the transport snippets into
   `boards/mr_canhubk3_s32k344.conf`, or into prj.conf, so every transport
   inherits it. Or at least add it to island-ethernet.
3. Check at build time: `grep CONFIG_NROS_DOMAIN_ID build-board/zephyr/.config`.
4. Check on the wire: router with `RUST_LOG=zenoh=debug`, then
   `grep -oE '@ros2_lv/[0-9]+' board-peer-router.log | sort | uniq -c`.
   You should see only `/10`. Issue 0801 (a split across domains) was a real
   past failure.
5. Check at the endpoint: `RMW_IMPLEMENTATION=rmw_zenoh_cpp ROS_DOMAIN_ID=10 ros2 node list --no-daemon`.
   Use `--no-daemon` or restart the daemon: a daemon started under another RMW
   or domain answers for itself (nano-ros issue 1342).
6. Gap: the silicon provenance record (`src/safety_island_tracing/markers.json`,
   `island_trace_markers.h:114`) carries `NROS_CYCLONE_DOMAIN_ID` only. Add
   `NROS_DOMAIN_ID` so a trace read from the board states its domain.

---

## 2. QoS compatibility, topic by topic

What nros-rmw-zenoh admits (READ, `shim/qos.rs admit`):
- History: KEEP_LAST only. KEEP_ALL is refused.
- Reliability: always GRANTED RELIABLE, because zenoh-pico publishes with
  congestion-control BLOCK. A best-effort request is over-served, and that is
  logged at INFO.
- Durability: VOLATILE on every entity kind. TRANSIENT_LOCAL is served ONLY on
  a publisher, through query-on-match: it retains 1 sample
  (`TL_RETAIN_DEPTH`) and declares a queryable at
  `<topic key>/@adv/pub/<zid>/<eid>/_`, where rmw_zenoh_cpp 0.1.9's
  `ze_advanced_subscriber` sends its history query. A TRANSIENT_LOCAL
  SUBSCRIPTION is REFUSED: "a subscription cannot query a peer's cache on
  match yet" (issue 1341).
- Depth: clamped to the ring. A subscription gets `ZPICO_SUBSCRIBER_RING_DEPTH`
  (4). A TL publisher gets 1. The clamp is advertised in the token.
- Deadline, lifespan and liveliness do not reach the token (empty fields).

rmw_zenoh_cpp does not block a match on RxO. Samples flow whatever the QoS
says. RxO is still worth stating for honesty in `ros2 topic info -v`.

### 2.1 Autoware -> island (island subscriptions, all `nros::QoS(1)`: RELIABLE, VOLATILE, KEEP_LAST 1)

| topic | Autoware publisher and QoS (READ, 1.5.0 source) | real source rate | contract | verdict |
| --- | --- | --- | --- | --- |
| /system/operation_mode/availability | diagnostic_graph_aggregator `converter` (`converter_node`), `QoS(1)`: R, V, KL1 | one per upstream availability msg (~10 Hz) | 10 Hz, 500 ms lease | OK |
| /localization/kinematic_state | planning sim: simple_planning_simulator `QoS{1}` R/V/KL1 (real car: ekf_localizer) | **40 Hz** (sim `timer_sampling_time_ms: 25`) | 10 Hz | OK on QoS. Bandwidth, see 3. |
| /vehicle/status/control_mode | simple_planning_simulator `QoS{1}` | **40 Hz** | 10 Hz | OK |
| /vehicle/status/steering_status | simple_planning_simulator `QoS{1}` | **40 Hz** | 30 Hz | OK |
| /vehicle/status/velocity_status | simple_planning_simulator `QoS{1}` | **40 Hz** | 30 Hz | OK |
| /control/command/control_cmd | vehicle_cmd_gate `durable_qos` = R, **TRANSIENT_LOCAL**, KL1 | ~33 Hz (controller `ctrl_period 0.03`) | 30 Hz | OK. A volatile reader of a TL writer is RxO-compatible, and the stream is periodic. |
| /control/command/gear_cmd | vehicle_cmd_gate `durable_qos` R/**TL**/KL1 | with each command, ~33 Hz while driving | 10 Hz | OK, same reasoning |
| /api/operation_mode/state | default_adapi `OperationModeNode`, adapi_specs: R, **TRANSIENT_LOCAL**, KL1 | **ON CHANGE ONLY**: `update_state()` publishes only when `prev_state_ != state` (5 Hz check timer) | **claims `min_rate_hz: 10`** | **MISMATCH**, see below |
| /planning/route_state | mission_planner, component_interface_specs RouteState: R, **TL**, KL1, type `autoware_planning_msgs/msg/RouteState` | on change | claims 30 Hz | same latch gap. Low impact. |

The `/api/operation_mode/state` mismatch is the one that matters. Upstream
mrm_handler subscribed TRANSIENT_LOCAL. The island changed it to VOLATILE
(F3, `mrm_handler_core.cpp:104-118`) because the shim refuses a TL
subscription. The justification in that comment is "the contract declares
10 Hz, so a late joiner has it within one period". That is false at the
source: default_adapi publishes only on a change. Consequence, read from the
island's code:
`getCurrentOperationMode()` returns UNKNOWN until the first message, so
`isAvailableCurrentOperationMode()` is false, so `isEmergency()` is true.
In state NORMAL with control mode AUTONOMOUS this is
`transitionTo(MRM_OPERATING)`. So:
- the island joining (or re-joining after a reset or link loss) while the
  vehicle drives autonomously triggers a spurious MRM at once;
- joining BEFORE engage works by luck: the engage transition publishes a new
  state and the island receives it live;
- the contract's `operation_mode_state: { min_rate_hz: 10 }` and
  `route_state: { min_rate_hz: 30 }` are false claims about the source.

The contract, the F3 comment and docs/topic-contract.md should be corrected
whatever transport is used. The native_sim/Cyclone image has the same volatile
reader, so it has the same late-join behaviour.

### 2.2 Island -> Autoware (island publishers)

| topic | island QoS (granted) | Autoware subscriber(s) and QoS (READ) | verdict |
| --- | --- | --- | --- |
| /system/fail_safe/mrm_state | default: R, V | vehicle_cmd_gate `input/mrm_state` depth 1 V. It is ALSO the gate's heartbeat: `system_emergency_heartbeat_timeout: 0.5` and `use_emergency_handling: true`. The gate sits in "waiting topics" until the first message, then emergency-stops if the gap exceeds 0.5 s. Also default_adapi fail_safe (component_interface_specs_universe MrmState R/V/KL1 -> `/api/fail_safe/mrm_state` TL) and the RViz state panel. | OK on QoS; **latency-critical** (see 3) |
| /system/emergency/control_cmd | R, V | gate `input/emergency/control_cmd` depth 1 V | OK |
| /system/emergency/{gear_cmd,hazard_lights_cmd,turn_indicators_cmd} | R, V | gate `InterProcessPollingSubscriber` default `QoS{1}` V | OK |
| /planning/scenario_planning/max_velocity_candidates | R, **TL** served, depth 1 | external_velocity_limit_selector `input/velocity_limit_from_internal` `QoS{10}.transient_local()` | RxO OK. The selector exists before the island, and nano-ros declares no `@adv` liveliness token, so it never queries the island's cache individually. It gets live samples only. They fire on MRM transitions only, and `use_comfortable_stop: false`, so the impact is low. |
| /planning/scenario_planning/clear_velocity_limit | R, TL, depth 1 | selector `QoS{10}.transient_local()` | same as above |
| /system/fail_safe/emergency_holding | R, V | **no subscriber**. Stock 1.5 mrm_handler publishes `/system/emergency_holding` (launch default), and hazard_status_converter listens there. | naming divergence; low |
| /system/stop_mode/{control,gear,hazard_lights,turn_indicators} | control R/V depth 5; others R/TL/1 | **no subscriber** in the stock 1.5 vehicle_cmd_gate configuration. Stock stop_mode_operator runs only with `use_control_command_gate=true` and publishes on `/control/control_command_gate/inputs/stop/*`. | unconsumed. zenoh-pico's write filter keeps them off the wire, until someone runs `ros2 topic echo/hz` on one (+11 KB/s, see 3). |

Island-internal: `/system/mrm/{comfortable,emergency}_stop/status` and the
two `operate` services. `Z_FEATURE_LOCAL_SUBSCRIBER=1` and `LOCAL_QUERYABLE=1`
(`nros-zpico-build/src/lib.rs:425-447`, forced on Zephyr), so they are
delivered on-board. But a local match turns the write filter OFF, so the two
status topics are ALSO sent to the router at 10 Hz and 30 Hz with no remote
reader.

Summary of mismatches:
- (M1) TL subscription refused in nros-rmw-zenoh. It matters for
  /api/operation_mode/state, which is latched and on-change at the source.
- (M2) The contract's rate claims on the two latched inputs are false.
- (M3) The TL publishers do not advertise the `@adv` liveliness token, so a
  pre-existing TL reader never queries them.
- (M4) Two outputs have no stock consumer (emergency_holding name,
  stop_mode_*).

---

## 3. Topology options

Common facts for every option:
- Router config: `ZENOH_ROUTER_CONFIG_URI` REPLACES rmw_zenoh's default and
  does not merge. `listen` must come from `ZENOH_CONFIG_OVERRIDE`, because
  rmw_zenoh computes its own. `ZENOH_CONFIG_OVERRIDE` is a `;`-separated list
  of `key=json5` pairs applied with `zc_config_insert_json5` (READ: strings in
  librmw_zenoh_cpp).
- Keepalive/lease: stock `lease 60000, keep_alive 2` means a router keepalive
  every 30 s. zenoh-pico drops the peer after 2 x its lease
  (`CONFIG_NROS_ZENOH_LEASE_MS=10000`, so 20 s) with nothing received.
  `router-serial.json5` sets keep_alive 6, a keepalive every 10 s, measured on
  the wire. In a shared Autoware domain inbound data flows all the time and
  resets the board's timer, so the issue is masked. It returns whenever
  Autoware is down or the router filters everything. Keep keep_alive 6.
  In the other direction the router expires the board after the board's
  declared lease: 10 s, which matches W7's "expired the link 10 s later".
- The board side has `CONFIG_NROS_ZENOH_AUTO_RECONNECT=y`. The island image
  retries the open about once a second while no peer answers (Z1a). The talker
  example gave up after ~11 s instead. Start the router first, then reset the
  board.
- rmw_zenoh_cpp CLI traps (README): `RMW_IMPLEMENTATION=rmw_zenoh_cpp` is not
  implied. `libzenohc.so` must be on `LD_LIBRARY_PATH` (use a fresh
  `env -i` shell, as `just board-peer` does). `ros2` daemon staleness.

### Bandwidth model (ESTIMATE; sizes READ from the derived bounds in `build-board/island_interfaces/*/nros_message_bounds.cmake`)

Payload sizes (CDR incl. header): Odometry ~718 B real (bound 836),
VelocityReport ~40 B, SteeringReport 16, ControlModeReport 13, Control 78,
GearCommand/Hazard/Turn 13, OperationModeAvailability 19, MrmState 16,
MrmBehaviorStatus 13, EmergencyHoldingState 13.

Per-sample overhead, about 65 B: attachment 33 + zenoh push/keyexpr-id/ext ~20
+ frame ~4 + serial framing ~9 (1 header + 2 length + 4 CRC32 + COBS + 0x00).
Add ~+90 B/sample if the router sends full keyexpr strings rather than ids.
Needs a wire measurement with the socat tap from the W7 keepalive work.

UART 115200 8N1 gives 11,520 B/s per direction (full duplex).

Inbound (host -> island), per direction:

| stream | size | source rate | B/s at source rate | contract rate | B/s at contract rate |
| --- | --- | --- | --- | --- | --- |
| kinematic_state (Odometry) | 718 | 40 | 31,320 | 10 | 7,830 |
| velocity_status | 40 | 40 | 4,200 | 30 | 3,150 |
| steering_status | 16 | 40 | 3,240 | 30 | 2,430 |
| control_mode | 13 | 40 | 3,120 | 10 | 780 |
| control_cmd | 78 | 33.3 | 4,767 | 30 | 4,290 |
| gear_cmd | 13 | 33.3 | 2,600 | 10 | 780 |
| availability | 19 | 10 | 840 | 10 | 840 |
| op-mode state, route_state | 19/13 | on change | ~0 | - | ~0 |
| **total** | | | **~50,100 (4.3x UART)** | | **~20,100 (1.75x UART)** |

Floor, with everything at 10 Hz: ~13,500 B/s, which is still 1.17x UART.
Odometry alone at 10 Hz is 68% of the link.

Outbound (island -> host) at contract rates. The write filter drops topics
with no remote reader, except topics with a local match:

| publisher set | samples/s | B/s |
| --- | --- | --- |
| mrm_handler: mrm_state, gear, hazard, turn, emergency_holding @10 | 50 | ~3,900 |
| emergency operator: control_cmd + status @30 | 60 | ~6,600 |
| comfortable operator: status @10 | 10 | ~780 |
| **subtotal (always on)** | 120 | **~11,300 (98% of UART)** |
| stop_mode_operator x4 @30 (only while a host reader exists) | 120 | +11,300 (2x UART) |

One-off bursts:
- Island declarations at session open: ~57-70 tokens x ~180 B plus ~30
  sub/queryable declarations. That is ~13-16 KB, about 1.2-1.4 s at 115200.
- The graph-cache history burst, host -> island. mrm_handler's clients start a
  liveliness subscriber on `@ros2_lv/10/**` with `history=true`
  (`shim/session.rs:1273` -> `zpico.c:4041-4075`). Every token in the Autoware
  graph is pushed. For a planning_simulator at ~150-200 nodes x ~20 tokens x
  ~200 B, that is ~0.6-1.0 MB (ESTIMATE, to be measured): 50-90 s of a
  saturated 115200 link. It would repeat in part on every Autoware node
  start/stop. The island's cache is 4 KiB, so almost all of it is dropped
  (counted) after being paid for.

The consequence is safety-relevant, not only a matter of performance. The
gate emergency-stops the car when mrm_state is late by more than 0.5 s. The
island triggers MRM when availability is late by more than 0.5 s. A saturated
link produces both. **UART at 115200 cannot carry this demo.** The link needs
at least 4x headroom over the contract-rate load: 460,800 baud minimum,
921,600 preferred (92 KB/s, so contract-rate inbound is ~22% and outbound
~12%), plus router-side downsampling of the 40 Hz sim streams.

### (a) One `rmw_zenohd` on the host, listening on serial + tcp; Autoware connects to it

What must be configured:
- Router:
  `ZENOH_ROUTER_CONFIG_URI=router-serial.json5` (keep_alive 6)
  `ZENOH_CONFIG_OVERRIDE='listen/endpoints=["serial//dev/serial/by-id/<ftdi>#baudrate=921600","tcp/[::]:7447"]'`.
  Port 7447 must be the port Autoware dials. `just board-peer` deliberately
  uses 7449 to keep strangers out, so the demo variant must change that, or
  use (a') below.
- Add to the router config:
  - a `downsampling` block with `link_protocols: ["serial"], flows: ["egress"],
    messages: ["put"]` and rules
    `10/localization/kinematic_state/** 10 Hz`,
    `10/vehicle/status/control_mode/** 10`,
    `10/vehicle/status/{steering,velocity}_status/** 30`,
    `10/control/command/gear_cmd/** 10`;
  - optionally a `qos/network` overwrite that raises `priority` for
    `10/system/operation_mode/availability/**` on serial egress. This helps
    only if zenoh-pico negotiates the QoS extension, which is open.
- Board: `CONFIG_NROS_ZENOH_LOCATOR="serial/uart@40330000#baudrate=921600"`,
  and `&lpuart2 { current-speed = <921600>; }` in `serial.overlay`. Keep
  `CONFIG_UART_INTERRUPT_DRIVEN=y` (already on). zenoh-pico's Zephyr
  `_z_open_serial_from_dev` passes the locator baud to `uart_configure`.
- Host serial: udev rule for a stable `/dev/serial/by-id` name.
  `ID_MM_DEVICE_IGNORE=1` so ModemManager does not grab the port. FTDI
  `latency_timer` = 1 ms; the default 16 ms adds up to 16 ms to every island
  -> host sample.
- Autoware: every process with `RMW_IMPLEMENTATION=rmw_zenoh_cpp
  ROS_DOMAIN_ID=10`. Stock session config (peer mode, connects to
  localhost:7447). Start the router first, or set
  `ZENOH_ROUTER_CHECK_ATTEMPTS`.
- Keepalive: as above. The same config serves the TCP clients, which cost only
  a keepalive every 10 s instead of 30 s.
- Bandwidth: see the model. Not viable at 115200. Viable at 921,600 with
  downsampling, IF the board's ISR RX keeps up. At 921,600 a byte arrives
  every 10.9 us. The LPUART FIFO is 4 bytes, so overrun comes after ~43 us of
  IRQ latency. The ring is 1 KiB (`_Z_ZEPHYR_SERIAL_RX_RING_BYTES`) and fills
  in ~11 ms if the reader thread stalls. ~92k IRQ/s is a real CPU load on a
  160 MHz M7. Unmeasured.
- Risk: a router restart (for example after an FTDI glitch) restarts discovery
  for the whole Autoware graph.

(a') Variant, recommended. Keep Autoware's stock router R1 on 7447, untouched.
Run a second "island gateway" router R2: `just board-peer` with
`connect/endpoints=["tcp/127.0.0.1:7447"]` added. Everything
serial-specific (keep_alive, downsampling, ACL) lives on R2 only, and R2 can be
restarted without touching Autoware. Routers mesh by linkstate; the cost is
one loopback hop. Untested here (see Open Questions).

### (b) Router inside the Autoware container, UART passed through

What must be configured, beyond (a):
- `docker run --device=/dev/serial/by-id/<ftdi>`, or
  `-v /dev:/dev --device-cgroup-rule='c 188:* rmw'` so an FTDI re-plug
  (a new ttyUSB minor) reaches a running container. `--group-add dialout`.
- `--network host`, or publish 7447, so host tools and RViz reach the router.
- The `fuser` holder check in `board-peer` cannot see HOST processes from
  inside the container. A host `cat /dev/ttyUSB0` or ModemManager would split
  the bytes, so the udev ignore rule and the latency_timer must be set on the
  HOST.
- Board reset (pyocd over MCU-Link) is a host-side USB action. Either pass
  that device in too or keep flashing and resetting on the host.
- Keepalive/lease: identical to (a). A container restart is a router restart:
  the board expires after <= 20 s and auto-reconnects. Same for Autoware
  nodes.
- Bandwidth: identical to (a). The container adds nothing on the wire.
- Verdict: packaging only. It is worth doing only if Autoware on the HPC is
  already containerised. It adds two failure modes (device visibility, host
  holders) and fixes none.

### (c1) Ethernet (100BASE-T1) instead of UART

- Board: `-S island-ethernet`. Static 192.168.10.20.
  `CONFIG_NROS_ZENOH_LOCATOR="tcp/<HPC>:7447"`. **Add
  `CONFIG_NROS_DOMAIN_ID=10`; it is missing today.** The GMAC descriptors must
  stay out of TCM (TCM is not DMA-reachable, board-facts).
- Host: a T1 <-> 100BASE-TX media converter, both sides 100 Mbit full duplex,
  and a host NIC on 192.168.10.0/24. Stock router, no serial config.
- Keepalive: the same pico lease rule applies (keep_alive 6, or rely on
  inbound traffic).
- Bandwidth: the line is 100 Mbit. The practical estimate is 10-30 Mbit/s
  (board-facts, unmeasured), i.e. >= 1.2 MB/s. Source-rate inbound (~50 KB/s)
  is ~4% of the LOW estimate, so no downsampling is needed. The graph-cache
  burst is ~1 s.
- Evidence: the QEMU image already ran this exact road (in-kernel IP stack,
  TCP) to FirstSpin with the full graph visible. It is the best-proven road.
- Cost: the media converter (not in the lab), and heap. The IP stack's pools
  and the 16/16/32/32 net_pkt/net_buf counts come on top of a heap that is
  already ~100 KB short. At stage 4 the serial and Ethernet heap peaks were
  close (55,792 vs 57,024 B); at FirstSpin they are unmeasured.

### (c2) CAN FD instead of UART

- zenoh-pico CAN link: RFC-0080, Draft. A multicast transport, proven only on
  vcan with 189-byte payloads. Endpoint
  `can/<dev>#bitrate=500000;dbitrate=2000000;id=0x100;match=0;mask=0`.
- Host half: RFC-0081, Draft. The apt `rmw_zenohd` (zenoh-c 1.8) has NO CAN
  link. It needs a custom zenoh 1.8 build carrying the link crate, and a CAN FD
  USB adapter on the HPC.
- Critical: a multicast face gets EVERY route the session forwards,
  unfiltered, and no interceptor (ACL, downsampling, qos overwrite) runs on a
  multicast face (RFC-0081 3.2, measured in phase-378 W6). The CAN endpoint
  must sit on a purpose-built peer session that publishes only the island
  inputs, never on the Autoware router.
- Bandwidth: ~1.41 Mbit/s usable (47.3 B per 63 B frame; 500k/2M), about
  176 KB/s. Contract-rate inbound is ~11%, source-rate ~28%. RFC-0080 measured
  37% with Odometry at 50 Hz and the rest at 20 Hz.
- Keepalive: a multicast transport has its own lease/join cadence. The
  router-serial.json5 fix does not apply.
- Verdict: the board is built for CAN, but this is a research track, not a
  demo road for RTSS@Work.

---

## 4. Discovery and liveliness, as `ros2` sees it

How it works (READ):
- Each rmw_zenoh_cpp context holds a liveliness subscriber with history on
  `@ros2_lv/<d>/**`, fed through the router. The island's tokens arrive as
  PUT and appear in the GraphCache. Undeclares, session close or lease expiry
  arrive as DELETE and disappear.
- `ros2 node list` then shows `/mrm_comfortable_stop_operator`,
  `/mrm_emergency_stop_operator`, `/mrm_handler` and `/stop_mode_operator`.
  They are in the ROOT namespace. Stock Autoware has them under `/system`,
  which is cosmetic but visible on stage.
- `ros2 topic info -v /system/fail_safe/mrm_state` shows publisher node
  `mrm_handler`, namespace `/`, and QoS RELIABLE / VOLATILE / KEEP_LAST with
  the granted depth. Deadline, lifespan and liveliness are defaults, because
  the token carries empty fields.
- Latched outputs show TRANSIENT_LOCAL, depth 1.
- The island's subscribers show depth 1, and RELIABLE even where BEST_EFFORT
  was requested.

Timing:
- Join. From board reset: session open in < 1 s (6/6 boots in W7), then
  registration.
  - At 115200 the island's ~15 KB of declarations take ~1.3 s to cross.
  - At 921,600 they take ~0.15 s.
  - On Ethernet, milliseconds.
  - Before any of this the board must reach FirstSpin. The graph-cache burst
    (section 3) competes with the declarations for the link unless it is fixed.
- Graceful leave: `undeclare` makes the entries vanish immediately. W7 saw
  every entity go within 0.25 s of the constructor failure.
- Unplug or crash: nothing until the router expires the board, which takes
  the board's lease, 10 s. Then all tokens are DELETEd together. Meanwhile
  vehicle_cmd_gate misses the mrm_state heartbeat after 0.5 s and publishes
  its own emergency stop ("system_emergency heartbeat is timeout"). That is
  Autoware watching the island, and it can be shown on stage.
- Rejoin within the 10 s window: a new zid means a second set of four nodes
  with the same names until the old session expires. rclcpp warns about
  duplicate node names. Either wait for the LEAVE, or shorten the board lease.
  With `CONFIG_NROS_ZENOH_LEASE_MS=3000` the router keepalive must be < 6 s,
  e.g. `keep_alive: 12` (60000/12 = 5 s).

How the demo can show the island joining live:
1. R1 and R2 up. Autoware (rmw_zenoh) up with stock MRM disabled (the
   demo/host_ws overlay). A graph watcher on screen: a long-lived rclpy node
   polling `get_node_names_and_namespaces()` and
   `count_publishers('/system/fail_safe/mrm_state')` every 100 ms and printing
   JOIN/LEAVE with timestamps. `watch ros2 node list` is too slow: each call
   creates a node and waits for the graph. The gate logs "waiting topics...".
2. `pyocd reset -t s32k344`. The watcher prints JOIN x4. `ros2 topic info -v`
   shows the island as publisher. The RViz AutowareStatePanel MRM row turns
   NORMAL. The gate becomes ready.
3. Engage. This must come AFTER the join until M1 is fixed; see 2.1.
4. SIGSTOP `converter_node`. The island's MRM fires within 0.5 s and the car
   stops. SIGCONT, the island recovers, and the car resumes (the existing
   scenario).
5. Optional: pull the UART. The gate's heartbeat emergency fires in 0.5 s, and
   the watcher prints LEAVE ~10 s later.

For a technical audience, the router log with `RUST_LOG=zenoh=debug` shows the
`@ros2_lv/10/<board zid>/...` tokens arriving.

---

## 5. Gaps to fix, ranked by necessity for the demo (design sketches; nothing implemented)

**G0. The board does not reach FirstSpin (prerequisite, outside D8-C but it
gates everything).** The heap peak is ~190 KB against 94 KB, and the cause is
the parameter services (24 queryables).
- Fix: nano-ros phase-461 W6, a store-only parameter capability (no
  queryables, no `ros2 param`). This is already named in `system.toml`.
- Side benefit for D8-C: 24 fewer SS tokens and queryable declarations on the
  link, and fewer cond/mutex slots.

**G1. Autoware itself on rmw_zenoh_cpp is unproven here.** The demo runs
Cyclone: `scenario_driver.py` hardcodes `rmw_cyclonedds_cpp`, `.envrc`
exports `CYCLONEDDS_URI`, and the runbook's discovery contract is
Cyclone-specific.
- Sketch: a `just autoware-zenoh` recipe (env -i, fresh ROS source,
  `RMW_IMPLEMENTATION=rmw_zenoh_cpp`, `ROS_DOMAIN_ID=10`, R1 started first).
  Parametrise the scenario driver's RMW. Run the existing native-island
  scenario unchanged over zenoh BEFORE any board work. That separates
  "Autoware on zenoh" from "island on zenoh".
- Measure: planning_simulator startup time, and the liveliness token count
  (needed for G3).

**G2. Link capacity.** 115200 is over capacity in both directions (section 3).
- Sketch, serial road:
  - 921,600 baud on both locators and the overlay;
  - FTDI latency_timer 1;
  - raise the zenoh-pico Zephyr RX ring from 1 KiB to 4 KiB;
  - measure overruns with `uart_err_check` (0852 instrumentation) at the new
    rate;
  - if ISR RX does not hold, use the LPUART eDMA async API
    (`CONFIG_UART_ASYNC_API`, mcux-lpuart + eDMA) behind the zenoh-pico
    Zephyr serial read. That is a zenoh-pico port change.
- Plus R2 egress downsampling of the 40 Hz sim streams to contract rates.
  Target <= 50% utilisation per direction at contract rates.
- Alternative: Ethernet (c1) as soon as a T1 media converter exists.
- Also check the FTDI part on the DCD-LZ cable, which bounds the baud rate
  (see Open Questions).

**G3. The graph-cache liveliness subscriber pulls the whole Autoware graph.**
`create_service_client` calls `ensure_graph_cache()` unconditionally
(`shim/session.rs:1273`). mrm_handler never calls `service_is_ready`
(grep of the island source), so the ~1 MB burst buys nothing.
- Sketch (nano-ros): start the cache lazily, on the first
  `service_is_ready` / `count_*` / graph call, not at client creation.
- And/or scope the subscription per client to
  `@ros2_lv/<d>/*/*/*/SS/%/*/*/<%service>/**`, one small subscriber per
  client, or one per distinct service name.
- Zero-code mitigation to try on R2: an ACL policy with
  `link_protocols: ["serial"]`, `flows: ["egress"]`,
  `messages: ["liveliness_token"]`, denying `@ros2_lv/10/**` except the island
  service names. Verify that zenoh 1.8 applies ACL to the liveliness history
  replay, and that the island still sees its own tokens locally.

**G4. Transient-local subscription (M1), and the false rate claims (M2).**
- Sketch (nano-ros, the "subscriber half" named in qos.rs and publisher.rs):
  - on a TL subscription, declare the subscriber as today;
  - then issue one `z_get` on `<topic key wildcard>/@adv/**`. That is the same
    global history query `ze_advanced_subscriber` issues (router log in
    publisher.rs:24-34). rmw_zenoh_cpp 0.1.9's advanced publisher cache
    answers with the latched sample, attachment included;
  - push the replies into the same ring, de-duplicated against live samples
    by (publisher GID, sequence number);
  - optionally declare a liveliness subscriber on `<key>/@adv/pub/**` for
    late publishers;
  - admit `TRANSIENT_LOCAL` for subscriptions in `admit`, with the granted
    depth advertised.
  Cost: one pending-get slot per TL subscription at start, and no persistent
  RAM.
- Then revert F3: mrm_handler goes back to `QoS(1).transient_local()`, and
  stop_mode_operator's route_state does the same.
- Interim, with zero code:
  - demo ordering, island joins before engage;
  - correct the contract (`operation_mode_state` and `route_state` are
    on-change, latched; drop the min_rate claims or mark them `state: true`);
  - correct the F3 comment.
- Do NOT "fix" it by treating UNKNOWN as non-emergency. That inverts
  upstream's fail-safe choice.

**G5. Domain plumbing (F6).**
- Move `CONFIG_NROS_DOMAIN_ID=10` into the board conf, or at least add it to
  island-ethernet.
- Add `NROS_DOMAIN_ID` to the trace provenance knobs.
- Add a `just doctor` line comparing `ROS_DOMAIN_ID` (.envrc) with each
  build's `.config`.
- Upstream: run `nros_system_check_domain_agreement` on the
  `nano_ros_add_executable` road as well (the gap F6 already names).

**G6. Router config hygiene.**
- `router-serial.json5` is a full copy of the default with one delta. It
  cannot shrink to just the serial-specific blocks (keep_alive, downsampling,
  ACL), because `ZENOH_ROUTER_CONFIG_URI` replaces the default rather than
  merging with it. Keep the full copy.
- Add a `just doctor` check that diffs it against the installed
  `DEFAULT_RMW_ZENOH_ROUTER_CONFIG.json5` and allows only the intended
  deltas.
- For keep_alive alone, `ZENOH_CONFIG_OVERRIDE='...;transport/link/tx/keep_alive=6'`
  on the stock file would avoid the copy. Verify that the override accepts a
  numeric leaf.
- Add `connect/endpoints` to R1 in `board-peer` for (a').

**G7. Write filter disabled by local match.** `/system/mrm/*/status` cross
the link (40 samples/s, ~3 KB/s) with no remote reader.
- Sketch (zenoh-pico/nano-ros): keep the remote interest state independent
  of the local match; deliver locally, and send to the network only when
  remote interest exists.
- Worth ~27% of a 115200 link; marginal at 921,600.

**G8. The `@adv` late-joiner liveliness token for TL publishers (M3).**
- Sketch: declare `<topic key>/@adv/pub/<zid>/<eid>` as a liveliness token
  beside the queryable. That is 5 more tokens.
- Low value for this demo, because the latched outputs fire live on MRM
  transitions.

**G9. Naming divergences (M4, cosmetic).**
- `/system/fail_safe/emergency_holding` should be `/system/emergency_holding`
  (stock 1.5 launch default, hazard_status_converter's input).
- The stop_mode outputs have no stock consumer. Decide whether they belong in
  the demo, and warn presenters that echoing them costs ~11 KB/s.
- Consider `/system` as the node namespace.
- docs/topic-contract.md is stale: it describes the domain 1/2 bridge and the
  adapi RouteState type.

**G10. Time base.** Island stamps and attachment timestamps are boot-relative;
Autoware's are wall-clock. The operators already clamp. Check that
vehicle_cmd_gate uses no source stamp from the island for freshness. From its
code it stamps the RECEIVE time, which is OK. Also check that nothing on the
host compares `source_timestamp`. Low priority.

---

## Recommended topology (one page)

    +---------------------------------- HPC (Humble, rmw_zenoh_cpp 0.1.9) ----------------------------------+
    |                                                                                                        |
    |  Autoware 1.5 planning_simulator            R1: stock rmw_zenohd            R2: island gateway         |
    |  (every process: RMW_IMPLEMENTATION=        tcp/[::]:7447                   rmw_zenohd (own name,      |
    |   rmw_zenoh_cpp, ROS_DOMAIN_ID=10,  <-----> stock config                    as board-peer)             |
    |   stock MRM disabled by host_ws)            (untouched)        <--tcp-->    connect tcp/127.0.0.1:7447 |
    |  RViz, scenario driver, graph watcher                                        listen serial/by-id/<ftdi>|
    |                                                                              #baudrate=921600          |
    |                                                                              (+ tcp 7449 diagnostics)  |
    |                                                                              config: keep_alive 6,     |
    |                                                                              egress downsampling on    |
    |                                                                              serial, (ACL on           |
    |                                                                              liveliness, if G3 open)   |
    +------------------------------------------------------------------------------------------|-------------+
                                                                                               | DCD-LZ UART
                                                                                               | (FTDI, latency_timer 1)
                                                        MR-CANHUBK344 / S32K344: 4 island nodes, one zenoh-pico
                                                        client session, CONFIG_NROS_DOMAIN_ID=10,
                                                        serial/uart@40330000#baudrate=921600, ISR RX,
                                                        auto-reconnect on, lease 10 s

- One domain (10) everywhere. The domain lives only in the keys, so the
  router chain is domain-agnostic.
- R1 is exactly what Autoware expects, so the Autoware side has no custom
  config. R2 carries every serial-specific setting and can be restarted
  alone. If router-to-router meshing misbehaves, fall back to (a): R2's
  listen set moved onto R1.
- Link budget at contract rates with 921,600 baud: inbound ~20 KB/s (22%),
  outbound ~11 KB/s (12%). This leaves headroom for the one-off declaration
  burst, and for the graph-cache burst while G3 is open (~1 MB, ~11 s: do it
  before the audience watches).
- Upgrade path, no redesign: swap the serial endpoint for T1 Ethernet
  (`-S island-ethernet` + `CONFIG_NROS_DOMAIN_ID=10`) and point the board at
  R2's TCP port. Downsampling becomes unnecessary.
- Order of work: G1 (Autoware on zenoh with the native island) and G0
  (board FirstSpin) in parallel, then G2, G3, G5, then the demo choreography
  in section 4. Until G4 lands, the choreography must join before engage.

## Open questions

1. Which FTDI part is on the DCD-LZ cable? What is its maximum baud, and does
   the S32K344 LPUART2 hit 921,600 (or 1,000,000) with an acceptable error at
   its clock?
2. Does ISR-driven RX (1 KiB ring, one IRQ per byte, 4-byte FIFO) sustain
   921,600 with zero `uart_err_check` overruns while the executor runs four
   nodes? The 0852 numbers are all at 115200.
3. How many liveliness tokens does the planning_simulator graph carry under
   rmw_zenoh_cpp, and what are the real bytes? This sizes the G3 burst.
4. What is the real per-sample overhead on the serial wire? Does the router
   send keyexpr ids or full strings to a zenoh-pico client face? Measure with
   the socat tap.
5. Does zenoh-pico negotiate the QoS/priority extension with the router? If
   not, per-priority queueing and a `qos/network` priority overwrite for
   availability cannot help on this link.
6. Does zenoh 1.8's ACL apply to the liveliness-history replay toward a
   client face, and to `link_protocols: ["serial"]` subjects? This decides
   the zero-code G3 mitigation.
7. Router chain (a'): do rmw_zenoh_cpp peers on R1 and the island client on
   R2 exchange liveliness and data with no extra config? Does gossip make
   Autoware peers dial R2's TCP port directly, and does it matter?
8. `ros2 node info` attribution with four nodes on one zid and node-id 0:
   correct in rmw_zenoh_cpp 0.1.9's GraphCache? The QEMU run proved only
   `node list` / `topic list`.
9. Does planning_simulator under rmw_zenoh_cpp start reliably at this graph
   size on the HPC, and does `vehicle_cmd_gate`'s 0.5 s heartbeat hold with a
   loopback router in the path?
10. Does the island image recover from an R2 restart mid-run
    (auto-reconnect = y) without redeclaring into a duplicate graph, and how
    long until its nodes reappear?
11. Should the demo keep the stop_mode_operator on the island at all, given
    that stock 1.5 with vehicle_cmd_gate never reads its outputs?
12. Is a 100BASE-T1 media converter obtainable before RTSS@Work? That turns
    G2 from a firmware project into a cable.
