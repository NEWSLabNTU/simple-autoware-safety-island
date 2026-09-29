# demo/l3/contracts - the takeover scenario as a checked contract

Phase 8, unit phase8-W6 (`docs/roadmap/phase-8-rtss-work-demo.md`, D6, G7,
G8). The four contract keys of ros-launch-manifest **v0.1.46** and the checker
rules of play_launch **phase 83**
(`docs/roadmap/phase-83-a-takeover-the-contract-can-state.md` there), applied
to the demo's takeover.

| file | what it is |
|---|---|
| `l3_takeover.launch.xml` | the three island nodes with their real parameter files (plus the handler's two takeover parameters, `takeover_request_timeout: 10.0`), and two HPC-side stand-ins: `availability_gate` and `planning_hop` (a 300 ms PLACEHOLDER for Autoware's planning path) |
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
  follow it), then the planner placeholder: 110 + 300 = 410 ms.

**Why 10 s for `hpc_loss` and not the island's 3 s.** At 30 km/h the emergency
stop alone takes 4165.33 ms to standstill, so no island can meet 3 s; the
island's 3 s was chosen for the 3.0 m/s its contract assumed. 10 s is brief
D's figure; the floor fits it with 5191.33 ms to spare.

## Verdicts

| contract | odd_exit, comfortable stop | odd_exit, floor | hpc_loss, floor | exit |
|---|---|---|---|---|
| `l3_takeover` | 20636.67 / 30000 ms, fits | 14538.67 ms, fits | 4808.67 / 10000 ms, fits | 0 |
| `l3_takeover_window20` | 30636.67 ms, **ladder-rung-budget** | 24538.67 ms, fits | 4808.67 ms, fits | 1 |
| `l3_takeover_65kmh` | 30366.67 ms, **ladder-rung-budget** | 18430.67 ms, fits | 8700.67 ms, fits | 1 |

Each variant fails the comfortable-stop rung and nothing else.

**The window is a least time (phase8-W12, play_launch phase 84, rlm
v0.1.47).** The request lasts at least 10 s; WINDOWS charges it up to its
deadline, and the handler's late notice of the deadline (its 100 ms tick) is
the first hop of the route below, `/mrm_handler/call_mrm` 110 ms. The new
rule `window-expiry` checks that hop holds the tick; it passes on all three
files, `--explain` now prints `window >=10000.00` and "ends within
10110.00ms", and no number in the table above moved.

**Why the variants are 20 s and 65 km/h, not brief D's 12 s and +10 km/h.**
Brief D computed its variants at 16.7 m/s (60 km/h), where the comfortable
rung had 993 ms of slack. At the decided 30 km/h it has 9363.33 ms, and the
brief's two variants PASS. Run with the same checker (scratch copies of this
contract, one line changed each):

```
== window 12 s
odd_exit  comfortable_stop  rung     120.00  12110.00  410.00  9996.67 derived  22636.67  30000.00   7363.33
== entry_speed 11.11 m/s (40 km/h)
odd_exit  comfortable_stop  rung     120.00  10110.00  410.00  12776.67 derived  23416.67  30000.00   6583.33
```

The smallest breaks are a window above 19.36 s and a bound above 63.7 km/h
(17.69 m/s); 20 s and 65 km/h are the round values past them.

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
Without Autoware on `AMENT_PREFIX_PATH` the verdicts are the same and
`when-field-unknown` adds three warnings saying the fields are unchecked.

The outputs below are verbatim except that terminal colour codes are
stripped. **The tool's own text contains em dashes, box-drawing rules and a
unicode arrow**; they are left as the tool printed them.

### `l3_takeover` (passes)

```
Parsing launch file: l3_takeover.launch.xml
Parsed: 1 scopes, 5 nodes, 0 containers, 0 composable nodes
2026-09-29T07:13:34.179341Z  INFO Loaded 1 manifest(s) [0 overlay, 1 provider] (0 scopes without manifests, 0 errors, 2 warnings)

── Cross-scope diagnostics ──
  info[path-exclusion]: scope path 'island.tor' (scope 0): the critical path assumes each node runs on arrival, but these traversals serialise with a sibling callback and may be delayed by it — /mrm_handler/on_timer may wait for [call_mrm, driver_exit] (up to 110.00ms). Declare `concurrency.exclusive` on the node if they can in fact run concurrently; absent that declaration every path of a node is assumed to serialise, matching rclcpp's default callback group
  info[derivable-min-rate]: publisher '/mrm_comfortable_stop_operator/status' promises min_rate_hz 10, which the graph already derives for '/system/mrm/comfortable_stop/status' from the timers that drive it. The declaration is redundant and can be deleted
  info[derivable-min-rate]: publisher '/mrm_emergency_stop_operator/emergency_control_cmd' promises min_rate_hz 30, which the graph already derives for '/system/emergency/control_cmd' from the timers that drive it. The declaration is redundant and can be deleted
  info[derivable-min-rate]: publisher '/mrm_emergency_stop_operator/status' promises min_rate_hz 30, which the graph already derives for '/system/mrm/emergency_stop/status' from the timers that drive it. The declaration is redundant and can be deleted
  info[derivable-min-rate]: publisher '/mrm_handler/hazard_lights_cmd' promises min_rate_hz 10, which the graph already derives for '/system/emergency/hazard_lights_cmd' from the timers that drive it. The declaration is redundant and can be deleted
  info[fault-reaction-budget]: l3_takeover.contract.yaml:101: hazard 'hpc_loss': detection 500.00ms (/mrm_handler/operation_mode_availability detects within 500.00ms) + reaction 4308.67ms (reaction route /mrm_handler/call_mrm → /mrm_emergency_stop_operator/on_timer (+33.33ms sampling) = 143.33ms + settle 4165.33ms) = 4808.67ms fits the fault-tolerant time interval 10000.00ms with 5191.33ms of slack
  warning[reaction-unguarded]: hazard 'hpc_loss' reaction 'l3_engaged' ends at /system/emergency/control_cmd and no subscriber there declares an `on_violation` — a stalled reaction would go unnoticed. Guard it with a second hazard whose guard is this output
  info[fault-reaction-budget]: l3_takeover.contract.yaml:99: hazard 'odd_exit': detection 120.00ms (/availability_gate/availability reports every 100.00ms + 20.00ms) + 'takeover_request' reaction 110.00ms + window 10000.00ms + reaction 4308.67ms (reaction route /mrm_handler/call_mrm → /mrm_emergency_stop_operator/on_timer (+33.33ms sampling) = 143.33ms + settle 4165.33ms) = 14538.67ms fits the fault-tolerant time interval 30000.00ms with 15461.33ms of slack
  warning[reaction-unguarded]: hazard 'odd_exit' reaction 'l3_engaged' ends at /system/emergency/control_cmd and no subscriber there declares an `on_violation` — a stalled reaction would go unnoticed. Guard it with a second hazard whose guard is this output
  info[settle-derived]: l3_takeover.contract.yaml:247: hazard 'odd_exit', rung 'comfortable_stop': settle from /mrm_comfortable_stop_operator's braking profile, a = |min_acceleration| = 1 m/s^2, j = |min_jerk| = 0.3 m/s^3, v0 = entry_speed 8.33 m/s: v_r = a^2/(2j) = 1^2/(2*0.3) = 1.6667 m/s; v0 = 8.33 > v_r, so t = a/j + (v0 - v_r)/a = 1/0.3 + (8.33 - 1.6667)/1 = 3333.33 + 6663.33 = 9996.67ms
  info[settle-derived]: l3_takeover.contract.yaml:269: hazard 'hpc_loss', rung 'emergency_stop': settle from /mrm_emergency_stop_operator's braking profile, a = |target_acceleration| = 2.5 m/s^2, j = |target_jerk| = 1.5 m/s^3, v0 = entry_speed 8.33 m/s: v_r = a^2/(2j) = 2.5^2/(2*1.5) = 2.0833 m/s; v0 = 8.33 > v_r, so t = a/j + (v0 - v_r)/a = 2.5/1.5 + (8.33 - 2.0833)/2.5 = 1666.67 + 2498.67 = 4165.33ms
  info[settle-derived]: l3_takeover.contract.yaml:269: hazard 'odd_exit', rung 'emergency_stop': settle from /mrm_emergency_stop_operator's braking profile, a = |target_acceleration| = 2.5 m/s^2, j = |target_jerk| = 1.5 m/s^3, v0 = entry_speed 8.33 m/s: v_r = a^2/(2j) = 2.5^2/(2*1.5) = 2.0833 m/s; v0 = 8.33 > v_r, so t = a/j + (v0 - v_r)/a = 2.5/1.5 + (8.33 - 2.0833)/2.5 = 1666.67 + 2498.67 = 4165.33ms

-- Fault-reaction budgets (--explain, ms) --
HAZARD    RUNG              ROLE     DETECT   WINDOWS   ROUTE             SETTLE     TOTAL      FTTI     SLACK
hpc_loss  takeover_request  skipped       -         -       -                  -         -  10000.00         -
hpc_loss  comfortable_stop  skipped       -         -       -                  -         -  10000.00         -
hpc_loss  emergency_stop    floor    500.00      0.00  143.33    4165.33 derived   4808.67  10000.00   5191.33
odd_exit  takeover_request  window   120.00      0.00  110.00  window >=10000.00         -  30000.00         -
odd_exit  comfortable_stop  rung     120.00  10110.00  410.00    9996.67 derived  20636.67  30000.00   9363.33
odd_exit  emergency_stop    floor    120.00  10110.00  143.33    4165.33 derived  14538.67  30000.00  15461.33
  TOTAL = DETECT + WINDOWS + ROUTE + SETTLE; WINDOWS is the route and window of every windowed rung passed on the way, up to its deadline.
  A window is a least time (`window >=`); noticing its deadline is the first hop of the ROUTE below it (`window-expiry`), never a second charge.
  hpc_loss/takeover_request: requires hpc_alive, which this fault removes
  hpc_loss/comfortable_stop: requires hpc_alive, which this fault removes
  odd_exit/takeover_request: lasts at least 10000.00ms once on, and ends within 10110.00ms: /mrm_handler reads the deadline on its 100.00ms timer ('on_timer'), charged inside /mrm_handler/call_mrm 110.00ms, the first hop of the route below

1 manifest(s) checked: 1 clean, 0 with errors (0 errors, 2 warnings)
1 contract(s): 0 overlay, 1 provider
exit code: 0
```

### `l3_takeover_window20` (fails the comfortable-stop rung)

```
Parsing launch file: l3_takeover_window20.launch.xml
Parsed: 1 scopes, 5 nodes, 0 containers, 0 composable nodes
2026-09-29T07:13:34.430926Z  WARN [cross-scope] [ladder-rung-budget] error: l3_takeover_window20.contract.yaml:123: hazard 'odd_exit': fallback rung 'comfortable_stop' cannot make the fault-tolerant time interval — detection 120.00ms + 'takeover_request' reaction 110.00ms + window 20000.00ms + reaction 410.00ms + settle 9996.67ms = 30636.67ms against 30000.00ms. A graded reaction is a promise in its own right, not only a step on the way to the floor (at hazards.odd_exit.reaction)
2026-09-29T07:13:34.430939Z  INFO Loaded 1 manifest(s) [0 overlay, 1 provider] (0 scopes without manifests, 1 errors, 2 warnings)

── Cross-scope diagnostics ──
  info[path-exclusion]: scope path 'island.tor' (scope 0): the critical path assumes each node runs on arrival, but these traversals serialise with a sibling callback and may be delayed by it — /mrm_handler/on_timer may wait for [call_mrm, driver_exit] (up to 110.00ms). Declare `concurrency.exclusive` on the node if they can in fact run concurrently; absent that declaration every path of a node is assumed to serialise, matching rclcpp's default callback group
  info[derivable-min-rate]: publisher '/mrm_comfortable_stop_operator/status' promises min_rate_hz 10, which the graph already derives for '/system/mrm/comfortable_stop/status' from the timers that drive it. The declaration is redundant and can be deleted
  info[derivable-min-rate]: publisher '/mrm_emergency_stop_operator/emergency_control_cmd' promises min_rate_hz 30, which the graph already derives for '/system/emergency/control_cmd' from the timers that drive it. The declaration is redundant and can be deleted
  info[derivable-min-rate]: publisher '/mrm_emergency_stop_operator/status' promises min_rate_hz 30, which the graph already derives for '/system/mrm/emergency_stop/status' from the timers that drive it. The declaration is redundant and can be deleted
  info[derivable-min-rate]: publisher '/mrm_handler/hazard_lights_cmd' promises min_rate_hz 10, which the graph already derives for '/system/emergency/hazard_lights_cmd' from the timers that drive it. The declaration is redundant and can be deleted
  info[fault-reaction-budget]: l3_takeover_window20.contract.yaml:101: hazard 'hpc_loss': detection 500.00ms (/mrm_handler/operation_mode_availability detects within 500.00ms) + reaction 4308.67ms (reaction route /mrm_handler/call_mrm → /mrm_emergency_stop_operator/on_timer (+33.33ms sampling) = 143.33ms + settle 4165.33ms) = 4808.67ms fits the fault-tolerant time interval 10000.00ms with 5191.33ms of slack
  warning[reaction-unguarded]: hazard 'hpc_loss' reaction 'l3_engaged' ends at /system/emergency/control_cmd and no subscriber there declares an `on_violation` — a stalled reaction would go unnoticed. Guard it with a second hazard whose guard is this output
  info[fault-reaction-budget]: l3_takeover_window20.contract.yaml:99: hazard 'odd_exit': detection 120.00ms (/availability_gate/availability reports every 100.00ms + 20.00ms) + 'takeover_request' reaction 110.00ms + window 20000.00ms + reaction 4308.67ms (reaction route /mrm_handler/call_mrm → /mrm_emergency_stop_operator/on_timer (+33.33ms sampling) = 143.33ms + settle 4165.33ms) = 24538.67ms fits the fault-tolerant time interval 30000.00ms with 5461.33ms of slack
  error[ladder-rung-budget]: l3_takeover_window20.contract.yaml:123: hazard 'odd_exit': fallback rung 'comfortable_stop' cannot make the fault-tolerant time interval — detection 120.00ms + 'takeover_request' reaction 110.00ms + window 20000.00ms + reaction 410.00ms + settle 9996.67ms = 30636.67ms against 30000.00ms. A graded reaction is a promise in its own right, not only a step on the way to the floor
  warning[reaction-unguarded]: hazard 'odd_exit' reaction 'l3_engaged' ends at /system/emergency/control_cmd and no subscriber there declares an `on_violation` — a stalled reaction would go unnoticed. Guard it with a second hazard whose guard is this output
  info[settle-derived]: l3_takeover_window20.contract.yaml:247: hazard 'odd_exit', rung 'comfortable_stop': settle from /mrm_comfortable_stop_operator's braking profile, a = |min_acceleration| = 1 m/s^2, j = |min_jerk| = 0.3 m/s^3, v0 = entry_speed 8.33 m/s: v_r = a^2/(2j) = 1^2/(2*0.3) = 1.6667 m/s; v0 = 8.33 > v_r, so t = a/j + (v0 - v_r)/a = 1/0.3 + (8.33 - 1.6667)/1 = 3333.33 + 6663.33 = 9996.67ms
  info[settle-derived]: l3_takeover_window20.contract.yaml:269: hazard 'hpc_loss', rung 'emergency_stop': settle from /mrm_emergency_stop_operator's braking profile, a = |target_acceleration| = 2.5 m/s^2, j = |target_jerk| = 1.5 m/s^3, v0 = entry_speed 8.33 m/s: v_r = a^2/(2j) = 2.5^2/(2*1.5) = 2.0833 m/s; v0 = 8.33 > v_r, so t = a/j + (v0 - v_r)/a = 2.5/1.5 + (8.33 - 2.0833)/2.5 = 1666.67 + 2498.67 = 4165.33ms
  info[settle-derived]: l3_takeover_window20.contract.yaml:269: hazard 'odd_exit', rung 'emergency_stop': settle from /mrm_emergency_stop_operator's braking profile, a = |target_acceleration| = 2.5 m/s^2, j = |target_jerk| = 1.5 m/s^3, v0 = entry_speed 8.33 m/s: v_r = a^2/(2j) = 2.5^2/(2*1.5) = 2.0833 m/s; v0 = 8.33 > v_r, so t = a/j + (v0 - v_r)/a = 2.5/1.5 + (8.33 - 2.0833)/2.5 = 1666.67 + 2498.67 = 4165.33ms

-- Fault-reaction budgets (--explain, ms) --
HAZARD    RUNG              ROLE     DETECT   WINDOWS   ROUTE             SETTLE     TOTAL      FTTI    SLACK
hpc_loss  takeover_request  skipped       -         -       -                  -         -  10000.00        -
hpc_loss  comfortable_stop  skipped       -         -       -                  -         -  10000.00        -
hpc_loss  emergency_stop    floor    500.00      0.00  143.33    4165.33 derived   4808.67  10000.00  5191.33
odd_exit  takeover_request  window   120.00      0.00  110.00  window >=20000.00         -  30000.00        -
odd_exit  comfortable_stop  rung     120.00  20110.00  410.00    9996.67 derived  30636.67  30000.00  -636.67
odd_exit  emergency_stop    floor    120.00  20110.00  143.33    4165.33 derived  24538.67  30000.00  5461.33
  TOTAL = DETECT + WINDOWS + ROUTE + SETTLE; WINDOWS is the route and window of every windowed rung passed on the way, up to its deadline.
  A window is a least time (`window >=`); noticing its deadline is the first hop of the ROUTE below it (`window-expiry`), never a second charge.
  hpc_loss/takeover_request: requires hpc_alive, which this fault removes
  hpc_loss/comfortable_stop: requires hpc_alive, which this fault removes
  odd_exit/takeover_request: lasts at least 20000.00ms once on, and ends within 20110.00ms: /mrm_handler reads the deadline on its 100.00ms timer ('on_timer'), charged inside /mrm_handler/call_mrm 110.00ms, the first hop of the route below

1 manifest(s) checked: 1 clean, 0 with errors (1 errors, 2 warnings)
1 contract(s): 0 overlay, 1 provider
exit code: 1
```

### `l3_takeover_65kmh` (fails the comfortable-stop rung)

```
Parsing launch file: l3_takeover_65kmh.launch.xml
Parsed: 1 scopes, 5 nodes, 0 containers, 0 composable nodes
2026-09-29T07:13:34.681219Z  WARN [cross-scope] [ladder-rung-budget] error: l3_takeover_65kmh.contract.yaml:123: hazard 'odd_exit': fallback rung 'comfortable_stop' cannot make the fault-tolerant time interval — detection 120.00ms + 'takeover_request' reaction 110.00ms + window 10000.00ms + reaction 410.00ms + settle 19726.67ms = 30366.67ms against 30000.00ms. A graded reaction is a promise in its own right, not only a step on the way to the floor (at hazards.odd_exit.reaction)
2026-09-29T07:13:34.681228Z  INFO Loaded 1 manifest(s) [0 overlay, 1 provider] (0 scopes without manifests, 1 errors, 2 warnings)

── Cross-scope diagnostics ──
  info[path-exclusion]: scope path 'island.tor' (scope 0): the critical path assumes each node runs on arrival, but these traversals serialise with a sibling callback and may be delayed by it — /mrm_handler/on_timer may wait for [call_mrm, driver_exit] (up to 110.00ms). Declare `concurrency.exclusive` on the node if they can in fact run concurrently; absent that declaration every path of a node is assumed to serialise, matching rclcpp's default callback group
  info[derivable-min-rate]: publisher '/mrm_comfortable_stop_operator/status' promises min_rate_hz 10, which the graph already derives for '/system/mrm/comfortable_stop/status' from the timers that drive it. The declaration is redundant and can be deleted
  info[derivable-min-rate]: publisher '/mrm_emergency_stop_operator/emergency_control_cmd' promises min_rate_hz 30, which the graph already derives for '/system/emergency/control_cmd' from the timers that drive it. The declaration is redundant and can be deleted
  info[derivable-min-rate]: publisher '/mrm_emergency_stop_operator/status' promises min_rate_hz 30, which the graph already derives for '/system/mrm/emergency_stop/status' from the timers that drive it. The declaration is redundant and can be deleted
  info[derivable-min-rate]: publisher '/mrm_handler/hazard_lights_cmd' promises min_rate_hz 10, which the graph already derives for '/system/emergency/hazard_lights_cmd' from the timers that drive it. The declaration is redundant and can be deleted
  info[fault-reaction-budget]: l3_takeover_65kmh.contract.yaml:101: hazard 'hpc_loss': detection 500.00ms (/mrm_handler/operation_mode_availability detects within 500.00ms) + reaction 8200.67ms (reaction route /mrm_handler/call_mrm → /mrm_emergency_stop_operator/on_timer (+33.33ms sampling) = 143.33ms + settle 8057.33ms) = 8700.67ms fits the fault-tolerant time interval 10000.00ms with 1299.33ms of slack
  warning[reaction-unguarded]: hazard 'hpc_loss' reaction 'l3_engaged' ends at /system/emergency/control_cmd and no subscriber there declares an `on_violation` — a stalled reaction would go unnoticed. Guard it with a second hazard whose guard is this output
  info[fault-reaction-budget]: l3_takeover_65kmh.contract.yaml:99: hazard 'odd_exit': detection 120.00ms (/availability_gate/availability reports every 100.00ms + 20.00ms) + 'takeover_request' reaction 110.00ms + window 10000.00ms + reaction 8200.67ms (reaction route /mrm_handler/call_mrm → /mrm_emergency_stop_operator/on_timer (+33.33ms sampling) = 143.33ms + settle 8057.33ms) = 18430.67ms fits the fault-tolerant time interval 30000.00ms with 11569.33ms of slack
  error[ladder-rung-budget]: l3_takeover_65kmh.contract.yaml:123: hazard 'odd_exit': fallback rung 'comfortable_stop' cannot make the fault-tolerant time interval — detection 120.00ms + 'takeover_request' reaction 110.00ms + window 10000.00ms + reaction 410.00ms + settle 19726.67ms = 30366.67ms against 30000.00ms. A graded reaction is a promise in its own right, not only a step on the way to the floor
  warning[reaction-unguarded]: hazard 'odd_exit' reaction 'l3_engaged' ends at /system/emergency/control_cmd and no subscriber there declares an `on_violation` — a stalled reaction would go unnoticed. Guard it with a second hazard whose guard is this output
  info[settle-derived]: l3_takeover_65kmh.contract.yaml:247: hazard 'odd_exit', rung 'comfortable_stop': settle from /mrm_comfortable_stop_operator's braking profile, a = |min_acceleration| = 1 m/s^2, j = |min_jerk| = 0.3 m/s^3, v0 = entry_speed 18.06 m/s: v_r = a^2/(2j) = 1^2/(2*0.3) = 1.6667 m/s; v0 = 18.06 > v_r, so t = a/j + (v0 - v_r)/a = 1/0.3 + (18.06 - 1.6667)/1 = 3333.33 + 16393.33 = 19726.67ms
  info[settle-derived]: l3_takeover_65kmh.contract.yaml:269: hazard 'hpc_loss', rung 'emergency_stop': settle from /mrm_emergency_stop_operator's braking profile, a = |target_acceleration| = 2.5 m/s^2, j = |target_jerk| = 1.5 m/s^3, v0 = entry_speed 18.06 m/s: v_r = a^2/(2j) = 2.5^2/(2*1.5) = 2.0833 m/s; v0 = 18.06 > v_r, so t = a/j + (v0 - v_r)/a = 2.5/1.5 + (18.06 - 2.0833)/2.5 = 1666.67 + 6390.67 = 8057.33ms
  info[settle-derived]: l3_takeover_65kmh.contract.yaml:269: hazard 'odd_exit', rung 'emergency_stop': settle from /mrm_emergency_stop_operator's braking profile, a = |target_acceleration| = 2.5 m/s^2, j = |target_jerk| = 1.5 m/s^3, v0 = entry_speed 18.06 m/s: v_r = a^2/(2j) = 2.5^2/(2*1.5) = 2.0833 m/s; v0 = 18.06 > v_r, so t = a/j + (v0 - v_r)/a = 2.5/1.5 + (18.06 - 2.0833)/2.5 = 1666.67 + 6390.67 = 8057.33ms

-- Fault-reaction budgets (--explain, ms) --
HAZARD    RUNG              ROLE     DETECT   WINDOWS   ROUTE             SETTLE     TOTAL      FTTI     SLACK
hpc_loss  takeover_request  skipped       -         -       -                  -         -  10000.00         -
hpc_loss  comfortable_stop  skipped       -         -       -                  -         -  10000.00         -
hpc_loss  emergency_stop    floor    500.00      0.00  143.33    8057.33 derived   8700.67  10000.00   1299.33
odd_exit  takeover_request  window   120.00      0.00  110.00  window >=10000.00         -  30000.00         -
odd_exit  comfortable_stop  rung     120.00  10110.00  410.00   19726.67 derived  30366.67  30000.00   -366.67
odd_exit  emergency_stop    floor    120.00  10110.00  143.33    8057.33 derived  18430.67  30000.00  11569.33
  TOTAL = DETECT + WINDOWS + ROUTE + SETTLE; WINDOWS is the route and window of every windowed rung passed on the way, up to its deadline.
  A window is a least time (`window >=`); noticing its deadline is the first hop of the ROUTE below it (`window-expiry`), never a second charge.
  hpc_loss/takeover_request: requires hpc_alive, which this fault removes
  hpc_loss/comfortable_stop: requires hpc_alive, which this fault removes
  odd_exit/takeover_request: lasts at least 10000.00ms once on, and ends within 10110.00ms: /mrm_handler reads the deadline on its 100.00ms timer ('on_timer'), charged inside /mrm_handler/call_mrm 110.00ms, the first hop of the route below

1 manifest(s) checked: 1 clean, 0 with errors (1 errors, 2 warnings)
1 contract(s): 0 overlay, 1 provider
exit code: 1
```

## Placeholders and open items

- `planning_hop`'s 300 ms is a placeholder until the planner hop is measured
  on the planning simulator; the comfortable-stop verdict depends on it.
- `availability_gate`'s 20 ms is declared, not measured.
- The declared comfortable settle is the operator's REQUEST; the velocity
  smoother's profile is what the vehicle does (brief D section 2). Measure the
  difference before the number goes on a slide.
- Both `reaction-unguarded` warnings are true: nothing on the host watches the
  island's braking command with an `on_violation`.
