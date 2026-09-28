# Phase 8 - RTSS@Work 2026 demo: a takeover that keeps its contract, live

**Goal:** a booth demo in which Autoware (on an HPC) and the safety island
(four Autoware MRM nodes on an NXP S32K344) run in one ROS 2 domain over
zenoh; a Drive Pilot-style scenario (ODD exit -> takeover request with a
10 s window -> driver responds, or the island executes a minimal risk
manoeuvre) is triggered from a button; and a live timeline shows the
declared budgets from the launch contract with the traced events from the
MCU and the host overlaid, pass or fail. The contract is the selling point:
one file states the terms, the checker refuses what does not fit, the image
is sized from it, and the plot is read against it.

**Status (2026-09-28): design. Nothing here is implemented.** The four
investigation briefs this design rests on are filed under
`docs/design/rtss-work-2026/` (A container and localrepo, B silicon
feasibility with measurements, C the zenoh domain, D scenario vocabulary and
repository). Numbers below cite them; B's are measured on the board on
2026-09-28, the others are read from source or estimated and say so.

---

## 1. What the demo shows, in one paragraph

Ego drives autonomously in the planning simulator inside an operational
design domain (ODD: a speed bound, a road segment). The presenter pushes
"ODD exit". Autoware's availability turns `autonomous: false`; the island's
handler enters a takeover-request rung and the timeline starts a 10 s bar.
Branch A: the presenter pushes "driver takes over"; control mode goes
MANUAL, the rung exits, no MRM, the bar ends green. Branch B: nobody
responds; at 10 s the handler calls the comfortable-stop operator; hazard
lights on, in-lane deceleration to standstill; the settle bar fills against
the value the contract derived from the ODD speed bound. Encore: the
presenter pulls the HPC (the availability heartbeat stops); the island alone
detects it in 500 ms and executes the emergency stop, traced on the MCU.
Every bar's declared length comes from the contract; every observed edge
comes from a trace marker or a host event.

## 2. What is already true (measured, 2026-09-28, brief B)

With the parameter services off, a larger heap and one zenoh-pico feature
flag, the board did for the first time what the deck's slides could not
claim: all four nodes registered, the executor ran, and the complete
reaction (availability sample stops -> handler detects -> `operate` service
-> operator `OPERATING` -> braking command) ran on silicon and was traced.

| quantity | value | provenance |
|---|---|---|
| last availability sample -> braking command | 555 ms, 589 ms | two runs, cycle-counter time; contract composes 610 ms |
| operator `on_timer` | 245-397 us | N = 36-136 per run |
| handler `on_timer`, idle / with data | 10 us / 425 us | |
| handler reaction tick (`call_mrm`) | 28-38 ms | the service request leaves over the UART as a busy-wait per byte |
| trace marker cost | mean 3.07 us, max 5.96 us | DWT CYCCNT, 12,530 markers |
| board RAM, services off | 288,792 B (88 %); 317,472 B (97 %) with the 120 KiB heap | region report |
| heap peak, services off / on | 95,216 B / 190,216 B | QEMU; the board fails registration at the 94,208 B stated today |

Three of the four blockers the deck listed are therefore closed in
principle: registration passes, the executor spins, the reaction traces.
The fourth, and the one this phase turns on, is the link.

## 3. Decisions

### D1. The link is the UART at 921,600 baud through an island gateway router, with T1 Ethernet as the upgrade path

Measured (B): at 115200 baud the island's inputs need 2.4-3.8 times the
line at contract rates; even three host topics at 10 Hz stalled delivery
after the first spin and the island raised a false emergency stop 516 ms
later; the router expired the session about 21 s after opening in 3 of 3
runs with host traffic. Estimated (A, C, independently): inbound
~20 KB/s at contract rates against 11.5 KB/s, Odometry (718 B) alone 68 %
of the line at 10 Hz; outbound always-on publishers 98 % of the line.

Decision: raise the baud to 921,600 (exact on the S32K344 LPUART's 40 MHz
clock and on the FT232R; C's estimate at that rate: inbound 22 %, outbound
12 %), put every serial-specific setting on a second router (`board-peer`:
listens on the serial port, connects to Autoware's untouched stock router
on 7447, keep_alive 6, egress downsampling of the high-rate inputs on the
serial link), and keep the Ethernet snippet as the drop-in upgrade once the
100BASE-T1 media converter exists (`CONFIG_NROS_DOMAIN_ID=10` is missing
from that snippet today). CAN FD is not a demo road: both RFCs are drafts,
the apt router has no CAN link, this host has no adapter (B, C).

Rejected: routing everything through one router (loses the ability to
restart the serial side alone); a container-internal router with UART
passthrough (packaging only, adds failure modes, fixes nothing).

The stall's root cause is undiagnosed (1 KiB receive ring at a 4-byte FIFO,
or the read task starved by the busy-wait transmit). Unit W2 owns it; the
soak test past 21 s is its gate.

### D2. Autoware runs on `rmw_zenoh_cpp` in one domain (10) with the island

The keys, liveliness tokens and (absent) type hashes already match on
Humble; all 19 island message and service types are field-identical to
Autoware's (C). Autoware 1.5.0 has never run on zenoh here (C, G1), and the
localrepo ships Cyclone only, so `rmw_zenoh_cpp` (0.1.9) comes from ROS apt
and the container must not source `autoware-env.bash`, which hard-sets
Cyclone (A). The domain reaches the image only through
`CONFIG_NROS_DOMAIN_ID`; the demo adds a doctor check that the image, the
snippet and `ROS_DOMAIN_ID` agree (C, G5).

Rejected: keeping Autoware on Cyclone with a byte-copying relay between the
RMWs (A, option B): a second moving part on stage that the contract does not
describe.

### D3. Autoware runs in a container built from the localrepo; the routers and the board link stay on the host

Base `ros:humble-ros-base-jammy`; the 1.85 GiB localrepo `.deb` unpacked
into its APT pool; `ros-humble-autoware-launch-1-5-0` plus config and theme,
no `autoware-data` (2 GB of models the planning simulator never loads), a
stub for the unversioned `libnvinfer10` dependency; `rmw_zenoh_cpp` from
apt, pinned; the `demo/host_ws` overlay that disables the stock MRM nodes;
the new `takeover_demo` package (section 4). autosdv's
`install-autoware-debian.sh` (parallel download, sha256) and its desktop
Dockerfile are the references; one stale path in autosdv skips the
prerequisites step on `-2` (A). Image estimate 5-8 GB. RViz runs on the host
over zenoh (software rendering in a container gives 2 fps with the
point-cloud map on). Estimated (A); nothing built.

User addition (2026-09-28): the autosdv desktop image is the reference for
the container's permission model as well, not only for the install steps:
a non-root user matching the host uid/gid, the `dialout` (serial), `video`
and `plugdev` groups, passwordless sudo inside the image, the serial device
passed by its `/dev/serial/by-id` path, and the X or VNC socket handling it
already does. Unit W3 copies that layout rather than inventing one.

### D4. The island image: parameter services off, `stop_mode_operator` out, local queryable on, heap 120 KiB

- `features = []` in `system.toml` turns the parameter services off and
  drops the queryables from 31 to 7 (B). Two nano-ros gaps come with it,
  both filed as units below: the generated entry still seeds the launch
  file's `<param from>` values through `nros_cpp_declare_param`, which does
  not link without the feature; and each component's `declare_parameter`
  then returns Unsupported and halts boot. The island loses `ros2 param` and
  the launch-file values; the 21 defaults in the source equal the yaml
  except `use_comfortable_stop` (false in yaml, true in source), which the
  demo wants true anyway.
- `stop_mode_operator` leaves the demo image: in 1.5.0 it is launched only
  with the control-command gate, nothing in the demo's `vehicle_cmd_gate`
  setup reads its outputs, and it owns three 30 Hz inbound topics and three
  of the five latched publishers (D).
- `Z_FEATURE_LOCAL_QUERYABLE=1`: the handler's `operate` request never
  reached the operator in the same image, because the router does not send
  a query back to the session it came from (B). This is the flag that made
  the reaction run on silicon; nano-ros should default it on when a client
  and a server share an image (unit W5).
- Heap 122,880 B and a 24 KiB trace buffer fit at 317,472 B of 327,680 (B).
  The heap is still a stated board fact, not a derived one; the honest line
  on the slide stays "the dynamic side is not derived".

### D5. The takeover request lives in `mrm_handler`, not in a fifth node

The handler already starts an MRM only in AUTONOMOUS (so the driver's switch
to MANUAL is the cancel), already reads `availability.autonomous == false`
(the ODD exit), already prefers comfortable stop and escalates to emergency
stop on timeout (D). The island change is about 40 lines: a takeover-request
wait of `takeover_request_timeout` (10 s) behind two parameters, entered on
the value fault and left on the driver's response or on expiry. A fifth node
would sit in the omission path uncounted and cost RAM the board does not
have.

Host side, a small `takeover_demo` package (A, D): `odd_monitor` (a speed
bound and a segment polygon, plus a manual inject service), `takeover_hmi`
(the countdown; a driver response requests MANUAL from the vehicle
interface), `availability_gate` (republishes Autoware's availability with
`autonomous &= !odd_exit`, which is what drives the handler; if it dies the
heartbeat stops and the island still stops the car), `driver_button`
(keyboard or a USB button), a `hazard_relay` into Autoware's
`hazard_lights_selector` for the comfortable-stop branch (D: `vehicle_cmd_gate`
applies the island's commands only in EMERGENCY_STOP; VERIFY), and a
`graph_watcher` that prints JOIN x4 when the island's tokens arrive.

### D6. The contract grows by four keys, proposed to rlm and play_launch, not by a new transition language

From D, each with its checker rules, runtime duty and how it reaches the
image; the full grammar and rules are in brief D section 1.3.

| key | meaning | why |
|---|---|---|
| `when: { field, op, value }` on a hazard or a function | a fault or a loss by VALUE, not only by silence | the ODD exit is `availability.autonomous == false`; the plot draws the bound; a function can be lost by value |
| `window: { duration, param }` on a ladder rung | a timed, transitional rung, bound to the parameter that enforces it | the 10 s takeover request; `ladder-rung-budget` becomes cumulative; a window on the floor is an error |
| `exit: { on: <function>, to: <mode> }` on a windowed rung | the driver's response ends the ladder successfully | `driver_took_over` is `control_mode == MANUAL`; the exit needs a path trigger so the island traces the take |
| `entry_speed` on a hazard, `settle: { decel, jerk }` by parameter name | the settle time derived from the braking profile and the ODD speed bound | fixes the phase-7 miss (3.0 m/s assumed, 4.23 observed); 3.0 gives 2,033 ms, 4.23 gives 2,525 ms by the same arithmetic |

nano-ros needs nothing new for any of the four: the window is a parameter,
the timer is the handler's tick, the predicate is application code the
contract describes, and pools and markers re-derive.

Two checker fixes found while drafting the demo contract (D): `ladder-rung-budget`
checks rungs the fault itself makes unavailable (a shared ladder for
`odd_exit` and `hpc_loss` would fail falsely), and the Linux observer records
a reaction only when a host process publishes the sink, so an island
reaction is seen only as `vehicle_cmd_gate`'s take (label it
`observed_at: take`). One item to verify: that the reaction walk continues
through a service callback that publishes (the comfortable-stop operator
does).

Expected verdicts, worked by hand with a 300 ms planner hop as placeholder
(D): ODD exit via comfortable stop 29,007 ms against a 30 s interval;
HPC loss via emergency stop 8,157 ms against 10 s. Two one-line variants
each fail only the comfortable-stop rung (a 12 s window; a speed bound
10 km/h higher), which is the "break a fact" act of the demo.

### D9. Graph discovery is off on the island; data and service traffic come first

User decision (2026-09-28). The island never asks who else is on the graph:
it does not need `ros2 node list` of its own, its service clients call a
fixed key, and the only thing discovery buys it is the ~1 MB liveliness
burst over the serial link (C, G3) into a 4 KiB cache it cannot hold.
Design, for nano-ros: a build-time switch (`CONFIG_NROS_ZENOH_GRAPH_DISCOVERY=n`,
derived to `n` by default when the transport is a serial or CAN link, `y`
on Ethernet unless stated) under which the backend

- still DECLARES the island's own liveliness tokens (nodes, publishers,
  subscribers, services), so the host's `ros2 node list` and the demo's
  `graph_watcher` see the island join and leave as today;
- declares no liveliness subscriber and keeps no graph cache; `rcl` graph
  queries on the island return Unsupported (the island's nodes make none);
- resolves a service call by its key expression alone, through the
  router's queryable matching (which is how it works anyway; the local
  queryable of D4 covers the in-image case);
- sends data and service traffic ahead of anything else on the link: the
  zenoh priority extension where zenoh-pico negotiates it (C, open
  question 5), otherwise the backend's own transmit order, with the
  availability subscription's samples first.

What it costs: nothing the demo uses. What it removes: the burst, the 4 KiB
cache, one subscriber and one thread. Gate for W4: with discovery off, a
socat tap on the serial line shows no `@ros2_lv` traffic toward the board
after the island's own declarations, and the host still lists the four
nodes.

### D7. The live timeline is one JSON Lines event stream and one drawer

Inputs (D): the play_launch observer log (already flushed per line), a
contract-generated probe and logger on the host (takes of the topics named
in `when:`, the velocity at the first braking command), the scenario
controller's button presses, and the island's trace markers read over the
debug probe with the alignment W3 used. One event schema (`t_mono_ns`,
`source`, `kind`, `hazard`, `rung`, `marker`, `value`). pyqtgraph draws it
live; matplotlib renders the same file for the slides. Declared bars from
the checker's own arithmetic; observed edges from events; a rung turns red
the moment its observed dwell exceeds its declared window; the plot flags a
run whose entry speed exceeded the declared bound.

### D8. Repository: this one; merge `contract-params` first

`nano-ros-rt-eval` is an IROS poster workspace with synthetic nodes and no
contract, untouched since 2026-08-14; a new repository would duplicate the
port and cut the provenance trail the deck cites (D). Plan: merge
`contract-params` into `main` (51 commits ahead), then add `demo/l3/`
(container, takeover package, scenario scripts), `tools/timeline/`,
`just/l3-demo.just`, and a first CI that runs `play_launch check` on the
contracts and builds the QEMU image.

## 4. Gaps, ranked, with their owner

| # | gap | repo | design | unit |
|---|---|---|---|---|
| G0 | parameter store without services: seeds link without the feature; `declare_parameter` returns the compiled default instead of halting | nano-ros | phase-461 W6 as designed there, or the minimal form B used: no seeds, defaults on Unsupported | W1 |
| G1 | the serial stall at 115200 and the session expiry at ~21 s; 921,600 baud; FTDI latency timer; interrupt-driven receive at the higher rate | island, nano-ros (zenoh-pico Zephyr serial link) | diagnose with the socat tap; ring size; measure `uart_err_check` overruns | W2 |
| G2 | Autoware 1.5.0 on `rmw_zenoh_cpp`; container from the localrepo | island `demo/l3/` | D3 | W3 |
| G3 | the island's service clients start a liveliness subscriber on `@ros2_lv/10/**` and pull Autoware's whole graph (~1 MB, est.) over the link into a 4 KiB cache | nano-ros | discovery OFF on the island (D9): no liveliness subscriber, no graph cache; pub/sub and service traffic first | W4 |
| G4 | the subscriber half of transient-local: `/api/operation_mode/state` is latched and published on change only, so the volatile reader added in phase 7 reads UNKNOWN on a late join and can trigger a spurious MRM; the contract's `min_rate_hz: 10` on it is false | nano-ros, island contract | one history query on `<key>/@adv/**` at creation into the same ring; then revert the phase-7 change and fix the contract; until then the choreography joins before engaging | W4 |
| G5 | `Z_FEATURE_LOCAL_QUERYABLE` off by default; a client and server in one image cannot talk | nano-ros | derive it: on when the inventory has both a `cli` and a `srv` | W5 |
| G6 | domain plumbing: `CONFIG_NROS_DOMAIN_ID` vs `ROS_DOMAIN_ID` vs `system.toml`, unchecked on this build path; the Ethernet snippet does not set it | nano-ros, island | a doctor check and a provenance line in the boot record | W5 |
| G7 | the four grammar keys and the two checker fixes | rlm, play_launch | D6 | W6 |
| G8 | the observer cannot see an off-host reaction; no probe for `when:` | play_launch | D6, D7 | W6, W7 |
| G9 | the trace window: 16 KiB covers 3.4 s of spinning; the stop-mode publish markers are 34 % of the volume | island tracing | drop stop_mode; a start trigger on the first fault marker; stream markers over the link later | W8 |
| G10 | naming: the island publishes `/system/fail_safe/emergency_holding`, stock reads `/system/emergency_holding`; `/system/stop_mode/*` has no reader | island | rename or drop | W3 |

## 5. Units

Protocol as phase 6 and 7: `phase8-Wk`, disjoint files, real output only,
ASCII, one git writer per repository, nano-ros through PRs with auto-merge,
the others by fast-forward push once implementation starts.

- **W0 - merge and scaffold.** `contract-params` into `main`; `demo/l3/`,
  `tools/timeline/`, `just/l3-demo.just`; CI: `play_launch check` on every
  contract, QEMU build. Gate: green CI on main.
- **W1 - parameter store without services (nano-ros).** Gate: the island
  image links and boots with `features = []` and no local patch; QEMU first
  spin at the conf stack; the board region report.
- **W2 - the link.** Root cause of the stall; 921,600 baud on both ends; the
  gateway router config; downsampling of Odometry and the two 30 Hz
  status topics on the serial egress; a 10-minute soak with the contract's
  inputs at contract rates and zero false emergencies. Gate: the soak log.
- **W3 - Autoware on zenoh in a container.** The image; the planning
  simulator on `rmw_zenoh_cpp`; the `takeover_demo` package; `graph_watcher`
  shows the island joining; `ros2 node list` shows all four island nodes
  beside Autoware's. Gate: an engaged drive with the island in the loop,
  MRM disabled on the host, on the sample map.
- **W4 - zenoh gaps in nano-ros.** G3 as D9 (discovery off on the island,
  data first) and G4 (transient-local subscriber); revert the phase-7
  volatile change and fix the contract's rate claim. Gate: a late-joining
  island reads the current operation mode; the serial tap shows no graph
  traffic toward the board; the host still lists the four nodes.
- **W5 - image hygiene in nano-ros.** G5 (local queryable derived), G6
  (domain doctor). Gate: `just board-doctor` reports the domain from the
  image, the snippet and the shell.
- **W6 - the four grammar keys and the checker fixes (rlm, play_launch).**
  Gate: the demo contract parses, the two expected verdicts print, the two
  one-line variants fail the comfortable-stop rung only, `settle-derived`
  prints the arithmetic that reproduces 2,033 / 2,525 ms.
- **W7 - the takeover in the handler, the probe, the timeline.** The 40-line
  handler change with its two parameters; the contract-generated probe and
  logger; the JSONL schema; the pyqtgraph drawer and the matplotlib
  renderer. Gate: branch A and branch B on native_sim with the timeline,
  every bar from the contract.
- **W8 - silicon rehearsal.** W1 + W2 + W5 on the board; the trace window
  (G9); the encore (HPC loss) traced on the MCU with the live plot; ten
  consecutive scripted runs. Gate: the ten runs, every one green or
  explained.
- **W9 - the booth.** Poster, the two-minute script, the fallback
  (native_sim with the identical plot), a recorded run.

Order: W0 first; W1, W2, W3, W6 in parallel; W4 and W5 after W1; W7 after
W6; W8 after W2, W4, W5, W7; W9 last. Rough effort 6-7 weeks on the core
path (D); the board path 1-1.5 weeks once W1 and W2 land (B); the link is
the schedule risk.

## 6. Risks

1. The link. A demo on a saturated link shows a reaction the link causes,
   not the fault (B measured exactly that). W2's soak is the gate for every
   silicon act; the native_sim fallback carries the identical plot.
2. Autoware 1.5.0 has never run on `rmw_zenoh_cpp` here (C, G1); the
   planning simulator's graph size and `vehicle_cmd_gate`'s 0.5 s heartbeat
   over a loopback router are untested.
3. The comfortable-stop branch has never been exercised on this island
   (`use_comfortable_stop: false` everywhere so far); hazard lights in that
   branch need a relay (VERIFY).
4. The map: 60 km/h needs about 400 m of straight lane; the sample map lacks
   it (D). A lower ODD bound (30 km/h) is the fallback and changes only the
   derived settle.
5. Time base: the board stamps in cycle-counter time from boot; alignment
   is by host receive times and anchors, as in phase 7, never by
   subtracting stamps.
6. Grammar scope creep: four keys, no transition language; anything more is
   a working-group proposal, not a demo item.

## 7. Open questions for the user

1. Link: raise the baud on the existing DCD-LZ cable, or buy the T1 media
   converter now and make Ethernet the primary road (then the UART is the
   fallback and downsampling disappears)?
2. ODD speed bound for the demo: 60 km/h (needs a longer straight than the
   sample map has) or 30 km/h on the sample map?
3. The takeover window: 10 s as Drive Pilot, and is the 30 s interval for
   the ODD-exit hazard an acceptable declared judgement, or should the
   demo state it differently?
4. Whether W6's four keys go to rlm as one PR with the checker rules, or as
   a proposal to the working group first (they are the same vocabulary the
   deck's `bounded_by:` note asks the group to judge).
5. Parameter store: wait for nano-ros phase-461 W6 as designed, or land the
   minimal form now (defaults on Unsupported, no seeds) and replace it
   later?
