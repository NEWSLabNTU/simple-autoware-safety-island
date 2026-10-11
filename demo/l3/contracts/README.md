# demo/l3/contracts - the takeover scenario as a checked contract

Phase 8, unit phase8-W6 (`docs/roadmap/phase-8-rtss-work-demo.md`, D6, G7,
G8). The four contract keys of ros-launch-manifest **v0.1.46** and the checker
rules of play_launch **phase 83**
(`docs/roadmap/phase-83-a-takeover-the-contract-can-state.md` there), applied
to the demo's takeover.

| file | what it is |
|---|---|
| `l3_takeover.launch.xml` | the three island nodes with their real parameter files (plus the handler's two takeover parameters, `takeover_request_timeout: 10.0`), and two HPC-side nodes, declared, not run: `availability_gate` (W16's C++ gate through `gate-rt`, as the container starts it) and `planning_hop` (a 300 ms PLACEHOLDER for Autoware's planning path) |
| `l3_takeover.contract.yaml` | both hazards, one ladder, the four keys; its header says where every number comes from |
| `l3_takeover_window20.*` | one-line variant: the window is 20 s (and the image runs 20.0, or `window-param` would refuse it first) |
| `l3_takeover_65kmh.*` | one-line variant: the ODD speed bound is 65 km/h (the anchor both hazards read) |

This directory does not touch the island's live contract
(`src/safety_island_bringup/launch/safety_island.contract.yaml`); unit W7
merges the keys into it.

## What the contract says

- `odd_exit` (ASIL_B, 30 s): a VALUE fault, `on: reported` +
  `when: { field: autonomous, equals: false }` on
  `/system/operation_mode/availability`. It removes `hpc_in_odd` only, so the
  ladder waits the 10 s takeover request out (`window:` bound to
  `mrm_handler.takeover_request_timeout`; the driver's MANUAL is the `exit:`),
  then takes the comfortable stop.
- `hpc_loss` (ASIL_D, 10 s): a SILENCE fault, `on: omission`. It removes both
  functions, so the checker skips the takeover request and the comfortable
  stop (they need the HPC) and charges neither: the floor is reached at once.
- `entry_speed` 8.33 m/s (30 km/h, decision 2) on both hazards. Every settle
  is DERIVED from the operator's own parameter file: emergency stop
  (`target_acceleration` -2.5, `target_jerk` -1.5) 4165.33 ms, comfortable
  stop (`min_acceleration` -1.0, `min_jerk` -0.3) 9996.67 ms.
- The comfortable stop's route crosses the operate service and the operator's
  callback, which publishes the velocity limit (brief D's F3: the walk does
  follow it), then the planner placeholder: 149 + 300 = 449 ms. The 149 ms
  is the handler's `call_mrm` on the S32K344 (phase9-W5): the tick 118 (100 +
  jitter) + in-tick work 31, each the maximum over the 13 W8 board runs plus
  20 % (the derivation is at `call_mrm` in the island contract;
  docs/takeover-trace.md section 10). The serial link in front of it, 81 ms,
  is the guard subscriber's `max_transport`, charged once on the reaction
  route (the takeover request's 230 ms) and not after the window's deadline.
  It was 206 ms with the link inside (phase8-W30), and 110 ms, the tick plus
  `timeout_call_mrm_behavior`, on native_sim before that.
- The availability gate is the 10 Hz timer it is (phase9-W6): W16's C++
  node, started through `gate-rt` as in
  `demo/l3/takeover_demo/launch/takeover.launch.xml`, republishing the latest
  raw sample with the ODD verdict folded in. Its timer's jitter, 6 ms, is
  measured (the largest publish gap under SCHED_FIFO, 104.53 ms,
  docs/takeover-trace.md section 7, x 1.2); its tick's 20 ms path is
  declared, not measured. `odd_exit` is detected within the gate's period
  plus that path, 120 ms.

**Why 10 s for `hpc_loss` and not the island's 3 s.** At 30 km/h the emergency
stop alone takes 4165.33 ms to standstill, so no island can meet 3 s; the
island's 3 s was chosen for the 3.0 m/s its contract assumed. 10 s is brief
D's figure; the floor fits it with 5065.33 ms to spare (5095.33 at
phase8-W30, 5191.33 before the board budget).

## Verdicts

| contract | odd_exit, comfortable stop | odd_exit, floor | hpc_loss, floor | exit |
|---|---|---|---|---|
| `l3_takeover` | 20795.67 / 30000 ms, fits | 14703.67 ms, fits | 4934.67 / 10000 ms, fits | 0 |
| `l3_takeover_window20` | 30795.67 ms, **ladder-rung-budget** | 24703.67 ms, fits | 4934.67 ms, fits | 1 |
| `l3_takeover_65kmh` | 30525.67 ms, **ladder-rung-budget** | 18595.67 ms, fits | 8826.67 ms, fits | 1 |

Each variant fails the comfortable-stop rung and nothing else. phase8-W30's
board budget (the handler's hop 110 -> 206 ms) moved every total by 96 or
192 ms and changed no verdict; before it the three rows read 20636.67,
30636.67 and 30366.67 for the comfortable stop. phase9-W5 (play_launch
0.14.0) split the hop: `call_mrm` 149 (tick + work), the serial link 81 as
the guard subscriber's `max_transport`, charged once on the reaction route
and not after the window's deadline, and the timers' release jitter (18 and
6 ms) charged where a tick is waited for. The comfortable-stop rows moved
by -33 (20828.67, 30828.67, 30558.67 before), the floors by -27, and
hpc_loss by +30 (4904.67 before); no verdict changed. phase9-W6 modelled
the gate as its 10 Hz timer and moved no number in the table: detection is
still the gate's period plus its declared 20 ms path. It cleared play_launch
0.14.0's `warning[scope-budget]` on island.tor (226 ms against a 250 ms
critical path once W5 moved the link into `max_transport`): island.tor is
now 356 ms, the gate's sampling wait 100 + its jitter 6 + its path 20 + the
link 81 + `call_mrm` 149, against the checker's 350 (it adds no jitter to a
sampling cost).

**The window is a least time (phase8-W12, play_launch phase 84, rlm
v0.1.47).** The request lasts at least 10 s; WINDOWS charges it up to its
deadline, and the handler's late notice of the deadline (its 100 ms tick) is
the first hop of the route below, `/mrm_handler/call_mrm` (110 ms then, 206
ms on the board from phase8-W30, 149 since phase9-W5). The new rule
`window-expiry` checks that hop holds the tick; it passes on all three
files, `--explain` prints `window >=10000.00` and "ends within 10149.00ms"
(10206.00 at W30, 10110.00 at W12), and W12 moved no number in the table
above.

**Why the variants are 20 s and 65 km/h, not brief D's 12 s and +10 km/h.**
Brief D computed its variants at 16.7 m/s (60 km/h), where the comfortable
rung had 993 ms of slack. At the decided 30 km/h it has 9204.33 ms (9171.33
at phase8-W30, 9363.33 before the board budget), and the brief's two variants PASS. Run with the
same checker (scratch copies of this contract, one line changed each; the
12 s copy also runs `takeover_request_timeout` 12.0; phase9-W6, play_launch
0.15.1):

```
== window 12 s
odd_exit  comfortable_stop  rung     120.00  12230.00  449.00    9996.67 derived  22795.67  30000.00   7204.33
== entry_speed 11.11 m/s (40 km/h)
odd_exit  comfortable_stop  rung     120.00  10230.00  449.00   12776.67 derived  23575.67  30000.00   6424.33
```

The smallest breaks are a window above 19.20 s and a bound above 63.1 km/h
(17.53 m/s) (19.17 s and 63.0 km/h at phase8-W30, 19.36 s and 63.7 km/h
before the board budget); 20 s and 65 km/h are still the round values past
them, so neither variant needed a change.

## How to reproduce

```
source /opt/ros/humble/setup.bash
source /opt/autoware/1.5.0/setup.bash    # so `when-field-unknown` can read the .msg files
cd demo/l3/contracts
play_launch check <stem>.launch.xml --explain
```

against play_launch `bbf9c044` (phase 84, rlm v0.1.47; phase8-W12 re-ran all three, the verdicts did not move;
phase8-W14 regenerated them on the W8a mrm_handler, built from nano-ros da272e419's vendored
submodule with `cargo build --release -p play_launch`; W12 used
`/home/aeon/repos/play_launch/install/play_launch/lib/play_launch/play_launch`).
Against W12's outputs only the timestamps, the contract line numbers of the
`settle-derived` lines and three `derivable-min-rate` infos moved: W8a removed
the handler's gear, turn-indicator and emergency-holding publishers.
phase8-W30 regenerated all three with the pinned release, play_launch 0.13.0
from the package index (`build/l3-ci/play_launch-0.13.0`, as `just l3-check`
installs it), under `env -i` with /opt/ros/humble and /opt/autoware/1.5.0
sourced, after the board budget: the handler's hop 206 ms, `driver_exit`
149 ms, island.tor 226 ms. The path-exclusion note now names `call_mrm`,
which is island.tor's critical path, instead of `on_timer`.
phase9-W6 regenerated all three with play_launch 0.15.1 (the package
index; 0.14.0 prints the same diagnostics and table), under `env -i` with
/opt/ros/humble and /opt/autoware/1.5.0 sourced, after the gate became its
10 Hz timer and island.tor 356 ms: `warning[scope-budget]` is gone,
`derivable-min-rate` no longer prints (0.14.0 on), and
`declared-not-charged` notes the 143 ms `max_transport` on `control_mode`.
Without Autoware on `AMENT_PREFIX_PATH` the verdicts are the same and
`when-field-unknown` adds three warnings saying the fields are unchecked.

The outputs below are verbatim except that terminal colour codes are
stripped. Since play_launch 0.14.0 the tool's own text is ASCII (`--`,
`->`).

### `l3_takeover` (passes)

```
Parsing launch file: l3_takeover.launch.xml
Parsed: 1 scopes, 5 nodes, 0 containers, 0 composable nodes
2026-10-11T01:58:01.044422Z  INFO Loaded 1 manifest(s) [0 overlay, 1 provider] (0 scopes without manifests, 0 errors, 2 warnings)

-- Cross-scope diagnostics --
  info[path-exclusion]: scope path 'island.tor' (scope 0): the critical path assumes each node runs on arrival, but these traversals serialise with a sibling callback and may be delayed by it -- /mrm_handler/call_mrm may wait for [driver_exit, on_timer] (up to 149.00ms). Declare `concurrency.exclusive` on the node if they can in fact run concurrently; absent that declaration every path of a node is assumed to serialise, matching rclcpp's default callback group
  info[fault-reaction-budget]: l3_takeover.contract.yaml:119: hazard 'hpc_loss': detection 500.00ms (/mrm_handler/operation_mode_availability detects within 500.00ms) + reaction 4434.67ms (reaction route link 81.00ms into /mrm_handler/operation_mode_availability + /mrm_handler/call_mrm -> /mrm_emergency_stop_operator/on_timer (+33.33ms sampling + 6.00ms jitter) = 269.33ms + settle 4165.33ms) = 4934.67ms fits the fault-tolerant time interval 10000.00ms with 5065.33ms of slack
  warning[reaction-unguarded]: hazard 'hpc_loss' reaction 'l3_engaged' ends at /system/emergency/control_cmd and no subscriber there declares an `on_violation` -- a stalled reaction would go unnoticed. Guard it with a second hazard whose guard is this output
  info[fault-reaction-budget]: l3_takeover.contract.yaml:117: hazard 'odd_exit': detection 120.00ms (/availability_gate/availability reports every 100.00ms + 20.00ms) + 'takeover_request' reaction 230.00ms + window 10000.00ms + reaction 4353.67ms (reaction route /mrm_handler/call_mrm -> /mrm_emergency_stop_operator/on_timer (+33.33ms sampling + 6.00ms jitter) = 188.33ms + settle 4165.33ms) = 14703.67ms fits the fault-tolerant time interval 30000.00ms with 15296.33ms of slack
  warning[reaction-unguarded]: hazard 'odd_exit' reaction 'l3_engaged' ends at /system/emergency/control_cmd and no subscriber there declares an `on_violation` -- a stalled reaction would go unnoticed. Guard it with a second hazard whose guard is this output
  info[settle-derived]: l3_takeover.contract.yaml:296: hazard 'odd_exit', rung 'comfortable_stop': settle from /mrm_comfortable_stop_operator's braking profile, a = |min_acceleration| = 1 m/s^2, j = |min_jerk| = 0.3 m/s^3, v0 = entry_speed 8.33 m/s: v_r = a^2/(2j) = 1^2/(2*0.3) = 1.6667 m/s; v0 = 8.33 > v_r, so t = a/j + (v0 - v_r)/a = 1/0.3 + (8.33 - 1.6667)/1 = 3333.33 + 6663.33 = 9996.67ms
  info[settle-derived]: l3_takeover.contract.yaml:318: hazard 'hpc_loss', rung 'emergency_stop': settle from /mrm_emergency_stop_operator's braking profile, a = |target_acceleration| = 2.5 m/s^2, j = |target_jerk| = 1.5 m/s^3, v0 = entry_speed 8.33 m/s: v_r = a^2/(2j) = 2.5^2/(2*1.5) = 2.0833 m/s; v0 = 8.33 > v_r, so t = a/j + (v0 - v_r)/a = 2.5/1.5 + (8.33 - 2.0833)/2.5 = 1666.67 + 2498.67 = 4165.33ms
  info[settle-derived]: l3_takeover.contract.yaml:318: hazard 'odd_exit', rung 'emergency_stop': settle from /mrm_emergency_stop_operator's braking profile, a = |target_acceleration| = 2.5 m/s^2, j = |target_jerk| = 1.5 m/s^3, v0 = entry_speed 8.33 m/s: v_r = a^2/(2j) = 2.5^2/(2*1.5) = 2.0833 m/s; v0 = 8.33 > v_r, so t = a/j + (v0 - v_r)/a = 2.5/1.5 + (8.33 - 2.0833)/2.5 = 1666.67 + 2498.67 = 4165.33ms
  info[declared-not-charged]: l3_takeover.contract.yaml:265: `nodes.mrm_handler.sub.control_mode.max_transport: 143ms` on '/mrm_handler/control_mode' is not charged by the fault-reaction arithmetic: no hazard's reaction route enters through it (a route is charged `max_transport` on its guard edge only, the hop into the subscriber that detects the fault), so hazard detection and reaction routes (the `--explain` budgets) do not include it; path and chain latencies do

-- Fault-reaction budgets (--explain, ms) --
HAZARD    RUNG              ROLE     DETECT   WINDOWS   ROUTE             SETTLE     TOTAL      FTTI     SLACK
hpc_loss  takeover_request  skipped       -         -       -                  -         -  10000.00         -
hpc_loss  comfortable_stop  skipped       -         -       -                  -         -  10000.00         -
hpc_loss  emergency_stop    floor    500.00      0.00  269.33    4165.33 derived   4934.67  10000.00   5065.33
odd_exit  takeover_request  window   120.00      0.00  230.00  window >=10000.00         -  30000.00         -
odd_exit  comfortable_stop  rung     120.00  10230.00  449.00    9996.67 derived  20795.67  30000.00   9204.33
odd_exit  emergency_stop    floor    120.00  10230.00  188.33    4165.33 derived  14703.67  30000.00  15296.33
  TOTAL = DETECT + WINDOWS + ROUTE + SETTLE; WINDOWS is the route and window of every windowed rung passed on the way, up to its deadline.
  A window is a least time (`window >=`); noticing its deadline is the first hop of the ROUTE below it (`window-expiry`), never a second charge.
  ROUTE includes the guard edge's link (`max_transport` into the detecting subscriber), except after a window's deadline.
  hpc_loss/takeover_request: requires hpc_alive, which this fault removes
  hpc_loss/comfortable_stop: requires hpc_alive, which this fault removes
  hpc_loss/emergency_stop: route = link 81.00ms (max_transport into '/mrm_handler/operation_mode_availability', sub-level) + path 188.33ms
  odd_exit/takeover_request: lasts at least 10000.00ms once on, and ends within 10149.00ms: /mrm_handler reads the deadline on its 100.00ms timer ('on_timer') released up to 18.00ms late, charged inside /mrm_handler/call_mrm 149.00ms, the first hop of the route below
  odd_exit/takeover_request: route = link 81.00ms (max_transport into '/mrm_handler/operation_mode_availability', sub-level) + path 149.00ms
  odd_exit/comfortable_stop: route = path 449.00ms; the guard edge's link (81.00ms into '/mrm_handler/operation_mode_availability') is not charged after a window's deadline, which its owner reads on its own clock
  odd_exit/emergency_stop: route = path 188.33ms; the guard edge's link (81.00ms into '/mrm_handler/operation_mode_availability') is not charged after a window's deadline, which its owner reads on its own clock

1 manifest(s) checked: 1 clean, 0 with errors (0 errors, 2 warnings)
1 contract(s): 0 overlay, 1 provider
exit code: 0
```

### `l3_takeover_window20` (fails the comfortable-stop rung)

```
Parsing launch file: l3_takeover_window20.launch.xml
Parsed: 1 scopes, 5 nodes, 0 containers, 0 composable nodes
2026-10-11T01:58:01.360814Z  INFO Loaded 1 manifest(s) [0 overlay, 1 provider] (0 scopes without manifests, 1 errors, 2 warnings)

-- Cross-scope diagnostics --
  info[path-exclusion]: scope path 'island.tor' (scope 0): the critical path assumes each node runs on arrival, but these traversals serialise with a sibling callback and may be delayed by it -- /mrm_handler/call_mrm may wait for [driver_exit, on_timer] (up to 149.00ms). Declare `concurrency.exclusive` on the node if they can in fact run concurrently; absent that declaration every path of a node is assumed to serialise, matching rclcpp's default callback group
  info[fault-reaction-budget]: l3_takeover_window20.contract.yaml:119: hazard 'hpc_loss': detection 500.00ms (/mrm_handler/operation_mode_availability detects within 500.00ms) + reaction 4434.67ms (reaction route link 81.00ms into /mrm_handler/operation_mode_availability + /mrm_handler/call_mrm -> /mrm_emergency_stop_operator/on_timer (+33.33ms sampling + 6.00ms jitter) = 269.33ms + settle 4165.33ms) = 4934.67ms fits the fault-tolerant time interval 10000.00ms with 5065.33ms of slack
  warning[reaction-unguarded]: hazard 'hpc_loss' reaction 'l3_engaged' ends at /system/emergency/control_cmd and no subscriber there declares an `on_violation` -- a stalled reaction would go unnoticed. Guard it with a second hazard whose guard is this output
  info[fault-reaction-budget]: l3_takeover_window20.contract.yaml:117: hazard 'odd_exit': detection 120.00ms (/availability_gate/availability reports every 100.00ms + 20.00ms) + 'takeover_request' reaction 230.00ms + window 20000.00ms + reaction 4353.67ms (reaction route /mrm_handler/call_mrm -> /mrm_emergency_stop_operator/on_timer (+33.33ms sampling + 6.00ms jitter) = 188.33ms + settle 4165.33ms) = 24703.67ms fits the fault-tolerant time interval 30000.00ms with 5296.33ms of slack
  error[ladder-rung-budget]: l3_takeover_window20.contract.yaml:141: hazard 'odd_exit': fallback rung 'comfortable_stop' cannot make the fault-tolerant time interval -- detection 120.00ms + 'takeover_request' reaction 230.00ms + window 20000.00ms + reaction 449.00ms + settle 9996.67ms = 30795.67ms against 30000.00ms. A graded reaction is a promise in its own right, not only a step on the way to the floor
  warning[reaction-unguarded]: hazard 'odd_exit' reaction 'l3_engaged' ends at /system/emergency/control_cmd and no subscriber there declares an `on_violation` -- a stalled reaction would go unnoticed. Guard it with a second hazard whose guard is this output
  info[settle-derived]: l3_takeover_window20.contract.yaml:296: hazard 'odd_exit', rung 'comfortable_stop': settle from /mrm_comfortable_stop_operator's braking profile, a = |min_acceleration| = 1 m/s^2, j = |min_jerk| = 0.3 m/s^3, v0 = entry_speed 8.33 m/s: v_r = a^2/(2j) = 1^2/(2*0.3) = 1.6667 m/s; v0 = 8.33 > v_r, so t = a/j + (v0 - v_r)/a = 1/0.3 + (8.33 - 1.6667)/1 = 3333.33 + 6663.33 = 9996.67ms
  info[settle-derived]: l3_takeover_window20.contract.yaml:318: hazard 'hpc_loss', rung 'emergency_stop': settle from /mrm_emergency_stop_operator's braking profile, a = |target_acceleration| = 2.5 m/s^2, j = |target_jerk| = 1.5 m/s^3, v0 = entry_speed 8.33 m/s: v_r = a^2/(2j) = 2.5^2/(2*1.5) = 2.0833 m/s; v0 = 8.33 > v_r, so t = a/j + (v0 - v_r)/a = 2.5/1.5 + (8.33 - 2.0833)/2.5 = 1666.67 + 2498.67 = 4165.33ms
  info[settle-derived]: l3_takeover_window20.contract.yaml:318: hazard 'odd_exit', rung 'emergency_stop': settle from /mrm_emergency_stop_operator's braking profile, a = |target_acceleration| = 2.5 m/s^2, j = |target_jerk| = 1.5 m/s^3, v0 = entry_speed 8.33 m/s: v_r = a^2/(2j) = 2.5^2/(2*1.5) = 2.0833 m/s; v0 = 8.33 > v_r, so t = a/j + (v0 - v_r)/a = 2.5/1.5 + (8.33 - 2.0833)/2.5 = 1666.67 + 2498.67 = 4165.33ms
  info[declared-not-charged]: l3_takeover_window20.contract.yaml:265: `nodes.mrm_handler.sub.control_mode.max_transport: 143ms` on '/mrm_handler/control_mode' is not charged by the fault-reaction arithmetic: no hazard's reaction route enters through it (a route is charged `max_transport` on its guard edge only, the hop into the subscriber that detects the fault), so hazard detection and reaction routes (the `--explain` budgets) do not include it; path and chain latencies do

-- Fault-reaction budgets (--explain, ms) --
HAZARD    RUNG              ROLE     DETECT   WINDOWS   ROUTE             SETTLE     TOTAL      FTTI    SLACK
hpc_loss  takeover_request  skipped       -         -       -                  -         -  10000.00        -
hpc_loss  comfortable_stop  skipped       -         -       -                  -         -  10000.00        -
hpc_loss  emergency_stop    floor    500.00      0.00  269.33    4165.33 derived   4934.67  10000.00  5065.33
odd_exit  takeover_request  window   120.00      0.00  230.00  window >=20000.00         -  30000.00        -
odd_exit  comfortable_stop  rung     120.00  20230.00  449.00    9996.67 derived  30795.67  30000.00  -795.67
odd_exit  emergency_stop    floor    120.00  20230.00  188.33    4165.33 derived  24703.67  30000.00  5296.33
  TOTAL = DETECT + WINDOWS + ROUTE + SETTLE; WINDOWS is the route and window of every windowed rung passed on the way, up to its deadline.
  A window is a least time (`window >=`); noticing its deadline is the first hop of the ROUTE below it (`window-expiry`), never a second charge.
  ROUTE includes the guard edge's link (`max_transport` into the detecting subscriber), except after a window's deadline.
  hpc_loss/takeover_request: requires hpc_alive, which this fault removes
  hpc_loss/comfortable_stop: requires hpc_alive, which this fault removes
  hpc_loss/emergency_stop: route = link 81.00ms (max_transport into '/mrm_handler/operation_mode_availability', sub-level) + path 188.33ms
  odd_exit/takeover_request: lasts at least 20000.00ms once on, and ends within 20149.00ms: /mrm_handler reads the deadline on its 100.00ms timer ('on_timer') released up to 18.00ms late, charged inside /mrm_handler/call_mrm 149.00ms, the first hop of the route below
  odd_exit/takeover_request: route = link 81.00ms (max_transport into '/mrm_handler/operation_mode_availability', sub-level) + path 149.00ms
  odd_exit/comfortable_stop: route = path 449.00ms; the guard edge's link (81.00ms into '/mrm_handler/operation_mode_availability') is not charged after a window's deadline, which its owner reads on its own clock
  odd_exit/emergency_stop: route = path 188.33ms; the guard edge's link (81.00ms into '/mrm_handler/operation_mode_availability') is not charged after a window's deadline, which its owner reads on its own clock

1 manifest(s) checked: 0 clean, 1 with errors (1 errors, 2 warnings)
1 contract(s): 0 overlay, 1 provider
exit code: 1
```

### `l3_takeover_65kmh` (fails the comfortable-stop rung)

```
Parsing launch file: l3_takeover_65kmh.launch.xml
Parsed: 1 scopes, 5 nodes, 0 containers, 0 composable nodes
2026-10-11T01:58:01.685273Z  INFO Loaded 1 manifest(s) [0 overlay, 1 provider] (0 scopes without manifests, 1 errors, 2 warnings)

-- Cross-scope diagnostics --
  info[path-exclusion]: scope path 'island.tor' (scope 0): the critical path assumes each node runs on arrival, but these traversals serialise with a sibling callback and may be delayed by it -- /mrm_handler/call_mrm may wait for [driver_exit, on_timer] (up to 149.00ms). Declare `concurrency.exclusive` on the node if they can in fact run concurrently; absent that declaration every path of a node is assumed to serialise, matching rclcpp's default callback group
  info[fault-reaction-budget]: l3_takeover_65kmh.contract.yaml:119: hazard 'hpc_loss': detection 500.00ms (/mrm_handler/operation_mode_availability detects within 500.00ms) + reaction 8326.67ms (reaction route link 81.00ms into /mrm_handler/operation_mode_availability + /mrm_handler/call_mrm -> /mrm_emergency_stop_operator/on_timer (+33.33ms sampling + 6.00ms jitter) = 269.33ms + settle 8057.33ms) = 8826.67ms fits the fault-tolerant time interval 10000.00ms with 1173.33ms of slack
  warning[reaction-unguarded]: hazard 'hpc_loss' reaction 'l3_engaged' ends at /system/emergency/control_cmd and no subscriber there declares an `on_violation` -- a stalled reaction would go unnoticed. Guard it with a second hazard whose guard is this output
  info[fault-reaction-budget]: l3_takeover_65kmh.contract.yaml:117: hazard 'odd_exit': detection 120.00ms (/availability_gate/availability reports every 100.00ms + 20.00ms) + 'takeover_request' reaction 230.00ms + window 10000.00ms + reaction 8245.67ms (reaction route /mrm_handler/call_mrm -> /mrm_emergency_stop_operator/on_timer (+33.33ms sampling + 6.00ms jitter) = 188.33ms + settle 8057.33ms) = 18595.67ms fits the fault-tolerant time interval 30000.00ms with 11404.33ms of slack
  error[ladder-rung-budget]: l3_takeover_65kmh.contract.yaml:141: hazard 'odd_exit': fallback rung 'comfortable_stop' cannot make the fault-tolerant time interval -- detection 120.00ms + 'takeover_request' reaction 230.00ms + window 10000.00ms + reaction 449.00ms + settle 19726.67ms = 30525.67ms against 30000.00ms. A graded reaction is a promise in its own right, not only a step on the way to the floor
  warning[reaction-unguarded]: hazard 'odd_exit' reaction 'l3_engaged' ends at /system/emergency/control_cmd and no subscriber there declares an `on_violation` -- a stalled reaction would go unnoticed. Guard it with a second hazard whose guard is this output
  info[settle-derived]: l3_takeover_65kmh.contract.yaml:296: hazard 'odd_exit', rung 'comfortable_stop': settle from /mrm_comfortable_stop_operator's braking profile, a = |min_acceleration| = 1 m/s^2, j = |min_jerk| = 0.3 m/s^3, v0 = entry_speed 18.06 m/s: v_r = a^2/(2j) = 1^2/(2*0.3) = 1.6667 m/s; v0 = 18.06 > v_r, so t = a/j + (v0 - v_r)/a = 1/0.3 + (18.06 - 1.6667)/1 = 3333.33 + 16393.33 = 19726.67ms
  info[settle-derived]: l3_takeover_65kmh.contract.yaml:318: hazard 'hpc_loss', rung 'emergency_stop': settle from /mrm_emergency_stop_operator's braking profile, a = |target_acceleration| = 2.5 m/s^2, j = |target_jerk| = 1.5 m/s^3, v0 = entry_speed 18.06 m/s: v_r = a^2/(2j) = 2.5^2/(2*1.5) = 2.0833 m/s; v0 = 18.06 > v_r, so t = a/j + (v0 - v_r)/a = 2.5/1.5 + (18.06 - 2.0833)/2.5 = 1666.67 + 6390.67 = 8057.33ms
  info[settle-derived]: l3_takeover_65kmh.contract.yaml:318: hazard 'odd_exit', rung 'emergency_stop': settle from /mrm_emergency_stop_operator's braking profile, a = |target_acceleration| = 2.5 m/s^2, j = |target_jerk| = 1.5 m/s^3, v0 = entry_speed 18.06 m/s: v_r = a^2/(2j) = 2.5^2/(2*1.5) = 2.0833 m/s; v0 = 18.06 > v_r, so t = a/j + (v0 - v_r)/a = 2.5/1.5 + (18.06 - 2.0833)/2.5 = 1666.67 + 6390.67 = 8057.33ms
  info[declared-not-charged]: l3_takeover_65kmh.contract.yaml:265: `nodes.mrm_handler.sub.control_mode.max_transport: 143ms` on '/mrm_handler/control_mode' is not charged by the fault-reaction arithmetic: no hazard's reaction route enters through it (a route is charged `max_transport` on its guard edge only, the hop into the subscriber that detects the fault), so hazard detection and reaction routes (the `--explain` budgets) do not include it; path and chain latencies do

-- Fault-reaction budgets (--explain, ms) --
HAZARD    RUNG              ROLE     DETECT   WINDOWS   ROUTE             SETTLE     TOTAL      FTTI     SLACK
hpc_loss  takeover_request  skipped       -         -       -                  -         -  10000.00         -
hpc_loss  comfortable_stop  skipped       -         -       -                  -         -  10000.00         -
hpc_loss  emergency_stop    floor    500.00      0.00  269.33    8057.33 derived   8826.67  10000.00   1173.33
odd_exit  takeover_request  window   120.00      0.00  230.00  window >=10000.00         -  30000.00         -
odd_exit  comfortable_stop  rung     120.00  10230.00  449.00   19726.67 derived  30525.67  30000.00   -525.67
odd_exit  emergency_stop    floor    120.00  10230.00  188.33    8057.33 derived  18595.67  30000.00  11404.33
  TOTAL = DETECT + WINDOWS + ROUTE + SETTLE; WINDOWS is the route and window of every windowed rung passed on the way, up to its deadline.
  A window is a least time (`window >=`); noticing its deadline is the first hop of the ROUTE below it (`window-expiry`), never a second charge.
  ROUTE includes the guard edge's link (`max_transport` into the detecting subscriber), except after a window's deadline.
  hpc_loss/takeover_request: requires hpc_alive, which this fault removes
  hpc_loss/comfortable_stop: requires hpc_alive, which this fault removes
  hpc_loss/emergency_stop: route = link 81.00ms (max_transport into '/mrm_handler/operation_mode_availability', sub-level) + path 188.33ms
  odd_exit/takeover_request: lasts at least 10000.00ms once on, and ends within 10149.00ms: /mrm_handler reads the deadline on its 100.00ms timer ('on_timer') released up to 18.00ms late, charged inside /mrm_handler/call_mrm 149.00ms, the first hop of the route below
  odd_exit/takeover_request: route = link 81.00ms (max_transport into '/mrm_handler/operation_mode_availability', sub-level) + path 149.00ms
  odd_exit/comfortable_stop: route = path 449.00ms; the guard edge's link (81.00ms into '/mrm_handler/operation_mode_availability') is not charged after a window's deadline, which its owner reads on its own clock
  odd_exit/emergency_stop: route = path 188.33ms; the guard edge's link (81.00ms into '/mrm_handler/operation_mode_availability') is not charged after a window's deadline, which its owner reads on its own clock

1 manifest(s) checked: 0 clean, 1 with errors (1 errors, 2 warnings)
1 contract(s): 0 overlay, 1 provider
exit code: 1
```

## Placeholders and open items

- `planning_hop`'s 300 ms is a placeholder until the planner hop is measured
  on the planning simulator; the comfortable-stop verdict depends on it.
- `availability_gate`'s tick path, 20 ms, is declared, not measured (its
  timer jitter, 6 ms, is). The checker charges the gate's period and path in
  `odd_exit`'s detection but not its jitter, so the detection is 6 ms short
  of the measured worst; no verdict is within 6 ms of its interval.
- The declared comfortable settle is the operator's REQUEST; the velocity
  smoother's profile is what the vehicle does (brief D section 2). Measure the
  difference before the number goes on a slide.
- Both `reaction-unguarded` warnings are true: nothing on the host watches the
  island's braking command with an `on_violation`.
