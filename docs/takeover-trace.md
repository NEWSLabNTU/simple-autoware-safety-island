# The takeover trace

phase8-W7, 2026-09-28. The takeover scenario of phase 8
(`docs/roadmap/phase-8-rtss-work-demo.md`, D5-D7), run end to end on
`native_sim` with Autoware's planning simulator, and set against the terms
the live contract declares: branch A (ODD exit, the driver takes over),
branch B (ODD exit, nobody answers, comfortable stop), and the encore (HPC
loss, emergency stop). Every declared bar is a row of
`play_launch check --explain` on
`src/safety_island_bringup/launch/safety_island.contract.yaml`; every
observed edge is an event (tools/timeline/README.md has the schema).

**The rung is native_sim. Island durations are SIMULATED time.** As in
docs/reaction-trace.md (phase7-W3): native_sim runs code in zero simulated
time, so an interval inside one island callback reads 0 or a few
microseconds and is never an execution time. What the island markers do
measure is the waits between callbacks: the handler's 100 ms tick, the
10 s window counted on that tick, the 500 ms staleness window, the
operator's 30 Hz tick. Rows that cross to the host (the probe's receipt of
a topic, the planner's braking, the vehicle's standstill) are host
CLOCK_MONOTONIC and carry loopback transport and host scheduling. "route
0.01 ms" (window over -> velocity limit) is such a zero-time artefact: the
handler's call and the operator's publish run in one executor turn.

## 1. What was run

- Image: `build-zephyr/zephyr/zephyr.exe`, sha256 `4efe2f09...543ab143`
  (native_sim, tracing on, 2026-09-28 21:53), with the handler change below
  and `use_comfortable_stop: true`.
- Contract: the live contract with the takeover vocabulary (the hazards
  `odd_exit` and `hpc_loss`, `entry_speed` 8.33 m/s, the functions with
  `when:`, the `takeover_request` window of 10 s bound to
  `mrm_handler.takeover_request_timeout`, the exit on `driver_took_over`,
  settle by the operators' parameters). Resolved by nano-ros's vendored
  play_launch 92043c82 / rlm v0.1.46 (nano-ros PR 1394); `just sync` and
  `just trace-gen` accept it.
- Host: Autoware 1.5.0 `planning_simulator` on CycloneDDS, launched with
  `operation_mode_availability_topic:=/system/operation_mode/availability_raw`;
  the availability gate (`tools/timeline/scenario.py gate`) republishes it on
  `/system/operation_mode/availability` at 10 Hz with
  `autonomous &= !odd_exit`.
- Acts (`tools/timeline/scenario.py run a|b|encore`): initial pose, goal,
  engage, drive 3 s past 1 m/s, then
  - A: ODD exit (SIGUSR1 to the gate), wait 3 s, ask the vehicle for MANUAL
    (`/control/control_mode_request`), observe past the would-be expiry;
  - B: ODD exit, nobody answers, observe to MRM_SUCCEEDED;
  - encore: SIGSTOP the gate, observe to MRM_SUCCEEDED, SIGCONT.
- One run: `tools/timeline/run-native.sh <act> <id>` (GNU parallel
  supervisor as experiments/reaction-trace/run.sh). Island markers are put
  on the host clock by `merge.py`: offset from the minimum over the
  publish/receipt pairs (each change of `/system/takeover_request/state` and
  `/system/fail_safe/mrm_state`, and the velocity limit, that the probe also
  received), checked against two anchors (the TOR state
  going OPERATING, the first availability sample with autonomous=false; for
  the encore, MRM_OPERATING and the last sample before the stop). The anchors
  agreed within 0.02-0.93 ms in every aligned run.
- Load: the host is shared; 1-min load average at start 23-56 (per run below).

The checker's table for this contract (play_launch 92043c82, verbatim):

```
-- Fault-reaction budgets (--explain, ms) --
HAZARD    RUNG              ROLE     DETECT   WINDOWS   ROUTE           SETTLE     TOTAL      FTTI     SLACK
hpc_loss  takeover_request  skipped       -         -       -                -         -  10000.00         -
hpc_loss  comfortable_stop  skipped       -         -       -                -         -  10000.00         -
hpc_loss  emergency_stop    floor    500.00      0.00  143.33  4165.33 derived   4808.67  10000.00   5191.33
odd_exit  takeover_request  window   100.00      0.00  110.00  window 10000.00         -  30000.00         -
odd_exit  comfortable_stop  rung     100.00  10110.00  110.00  9996.67 derived  20316.67  30000.00   9683.33
odd_exit  emergency_stop    floor    100.00  10110.00  143.33  4165.33 derived  14518.67  30000.00  15481.33
  TOTAL = DETECT + WINDOWS + ROUTE + SETTLE; WINDOWS is the route and window of every windowed rung passed on the way.
  hpc_loss/takeover_request: requires hpc_alive, which this fault removes
  hpc_loss/comfortable_stop: requires hpc_alive, which this fault removes
  odd_exit/takeover_request: transitional: charged to every rung below it
```

## 2. The verdicts

The act's own verdict line, verbatim (from each run's `scenario.jsonl`):

```
a1 VERDICT: PASS a: v at the fault 3.88 m/s; TOR on True, TOR now 1, control mode 4, mrm (1, 1)
a2 VERDICT: PASS a: v at the fault 3.89 m/s; TOR on True, TOR now 1, control mode 4, mrm (1, 1)
a3 VERDICT: PASS a: v at the fault 3.90 m/s; TOR on True, TOR now 1, control mode 4, mrm (1, 1)
b3 VERDICT: FAIL b: v at the fault 3.86 m/s; TOR on True, mrm (3, 2) (3 = COMFORTABLE_STOP), v 0.000
b4 VERDICT: FAIL b: v at the fault 3.56 m/s; TOR on True, mrm (3, 2) (3 = COMFORTABLE_STOP), v 0.000
b5 VERDICT: PASS b: v at the fault 3.86 m/s; TOR on True, mrm (3, 3) (3 = COMFORTABLE_STOP), v 0.000
b6 VERDICT: PASS b: v at the fault 3.91 m/s; TOR on True, mrm (3, 3) (3 = COMFORTABLE_STOP), v 0.000
b7 VERDICT: PASS b: v at the fault 3.90 m/s; TOR on True, mrm (3, 3) (3 = COMFORTABLE_STOP), v 0.000
b8 VERDICT: PASS b: v at the fault 3.90 m/s; TOR on True, mrm (3, 3) (3 = COMFORTABLE_STOP), v 0.000
e1 VERDICT: PASS encore: v at the fault 3.92 m/s; mrm (3, 2) (2 = EMERGENCY_STOP), v 0.000, after restore mrm (1, 1)
e2 VERDICT: PASS encore: v at the fault 3.83 m/s; mrm (3, 2) (2 = EMERGENCY_STOP), v 0.000, after restore mrm (1, 1)
e3 VERDICT: PASS encore: v at the fault 3.91 m/s; mrm (3, 2) (2 = EMERGENCY_STOP), v 0.000, after restore mrm (1, 1)
```

`mrm (state, behavior)`: state 1 NORMAL, 3 MRM_SUCCEEDED; behavior 1 NONE,
2 EMERGENCY_STOP, 3 COMFORTABLE_STOP. `TOR` is the takeover request state
(1 idle, 2 on); control mode 4 is MANUAL.

Runs b1 and b2 were made on earlier images (before the fix that asks the
driver only while the operation mode is AUTONOMOUS, section 4) and are not
counted.

## 3. Declared against observed, per run

ms unless marked; "FAIL" marks an observed value outside its declared one.
Produced by `tools/timeline/render.py <run> --table`.

### Branch A: ODD exit, the driver takes over

| term | declared | a1 | a2 | a3 |
|---|---|---|---|---|
| detect (button -> verdict on the wire) | 100.00 | 22.40 | 86.16 | 92.93 |
| takeover route (verdict -> request on) | 110.00 | 65.09 | 0.49 | 88.25 |
| driver answered inside the window | 10000.00 | 3036.72 | 3037.65 | 3043.87 |
| exit route (MANUAL taken -> request off) | 100.00 | 62.97 | 62.01 | 56.99 |
| no MRM | none | none | none | none |
| HPC alive: longest availability gap (host) | 500.00 | 103.66 | 156.65 | 104.75 |

Load at start 23.3 / 53.6 / 27.9. The button to MANUAL on the host took
17.26 / 16.50 / 22.46 ms. The exit route is the handler's tick phase: the
MANUAL report is taken at once, the request goes off on the next 100 ms tick.

### Branch B: ODD exit, nobody answers

| term | declared | b3 | b4 | b5 | b6 | b7 | b8 |
|---|---|---|---|---|---|---|---|
| detect (button -> verdict on the wire) | 100.00 | 18.26 | 305.15 FAIL | 19.24 | 71.22 | 90.55 | 45.94 |
| takeover route (verdict -> request on) | 110.00 | 8.88 | 100.13 | 33.29 | 99.88 | 75.21 | 41.22 |
| window dwell (request on -> off) | 10000.00 | 10000.00 | 600.00 FAIL | 10000.00 | 10087.22 | 10000.00 | 10099.00 |
| windows (verdict -> window over) | 10110.00 | 10008.88 | 700.13 | 10033.29 | 10187.09 FAIL | 10075.21 | 10140.21 FAIL |
| route (window over -> velocity limit) | 110.00 | 0.01 | - | 0.01 | 2.87 | 0.01 | 0.01 |
| settle (velocity limit -> standstill) | 9996.67 | 4523.03 | - | 6072.25 | 7888.91 | 1109.18 | 4969.18 |
| total (button -> standstill) | 20316.67 | 14550.17 | 4079.51 | 16124.79 | 18150.09 | 11274.95 | 15155.34 |
| within the FTTI | 30000.00 | 14550.17 | 4079.51 | 16124.79 | 18150.09 | 11274.95 | 15155.34 |
| rung reached | COMFORTABLE_STOP | EMERGENCY_STOP FAIL | EMERGENCY_STOP FAIL | COMFORTABLE_STOP | COMFORTABLE_STOP | COMFORTABLE_STOP | COMFORTABLE_STOP |
| HPC alive: longest availability gap (host) | 500.00 | 582.02 FAIL | 1134.03 FAIL | 111.44 | 111.44 | 451.87 | 110.09 |
| entry speed (m/s) | 8.33 | 3.04 | - | 2.98 | 3.07 | 1.89 | 3.02 |

Load at start 27.4 / 55.7 / 27.4 / 32.9 / 32.5 / 34.5. b6-b8 were started
only below load 35. The planner hop (velocity limit -> first braking
command on `/control/command/control_cmd`) was 2216.91 / - / 868.25 /
2989.47 / 23.85 / 434.82 ms; it sits inside the settle row and is not a
declared term (the contract's settle starts at the operator's publish).
The settle derived at the OBSERVED entry speed (a 1.0, j 0.3) is 4707.86 /
- / 4651.54 / 4737.90 / 3553.06 / 4685.40 ms; the observed settle exceeds
that by the planner hop and the planner's own profile, and stays inside the
declared 9996.67 (derived at 8.33 m/s).

b6's island trace ends 0.52 s after the button (island clock 58.147 s,
both ends of the trace intact per `island_trace.py check`; cause not found),
so b6 is measured from host events only (`island.jsonl.ends-at-0.52s` kept
beside it); its window row therefore includes the probe's receipt latency.

### Encore: HPC loss

| term | declared | e1 | e2 | e3 |
|---|---|---|---|---|
| detect (last sample -> reaction tick) | 600.00 | 537.99 | 520.00 | 520.98 |
| route (reaction tick -> braking command) | 143.33 | 32.04 | 29.00 | 26.00 |
| detect + route (last sample -> braking command) | 643.33 | 570.02 | 548.99 | 546.98 |
| settle (braking command -> standstill) | 4165.33 | 2924.79 | 2958.15 | 2926.25 |
| total (last sample -> standstill) | 4808.67 | 3494.82 | 3507.14 | 3473.23 |
| within the FTTI | 10000.00 | 3494.82 | 3507.14 | 3473.23 |
| rung reached | EMERGENCY_STOP | EMERGENCY_STOP | EMERGENCY_STOP | EMERGENCY_STOP |
| entry speed (m/s) | 8.33 | 4.20 | 4.16 | 4.21 |

The declared detect is 500 plus the handler's 100 ms tick (the checker
charges that tick to the 110 ms route, so the row adds it back and the
detect + route row compares the sum the checker actually states). The
SIGSTOP landed 95.01 / 56.53 / 50.24 ms after the gate's last sample.

## 4. What the runs show

- **Branch A and the encore keep every declared term** in all three runs.
- **Branch B keeps every term in b5 and b7**, and reaches the comfortable
  stop and standstill inside the FTTI in b5-b8.
- **The window is one tick longer than the checker charges (b6, b8).** The
  handler counts the 10 s on its 100 ms tick, so the request goes off at
  10000 ms or 10000 + one tick (b8: 10099.00 on the island clock; b3, b5, b7:
  10000.00). The checker's WINDOWS term is route + window = 10110 and does
  not charge that tick, so b8 exceeds it by 30.21 ms (and b6, on host time,
  by 77.09). The comfortable-stop TOTAL keeps 9683 ms of slack, so no FTTI
  is at risk, but the term is under-declared by up to 100 ms: either the
  `takeover_request` window should carry the expiry tick (a route of the
  window's own) or the contract should declare `window: 10s` plus the
  handler's period. Not changed here; it is a play_launch/contract decision.
- **b3 and b4 are the island being right about a host that stalled.** The
  comfortable-stop rung requires `hpc_alive`. In b3 the availability stream
  on the wire went silent for 582.02 ms at 11821 ms, 1.8 s into the
  comfortable stop; the island raised `hpc_loss` and escalated to the
  emergency stop at 12327 ms (the timeline shows the comfortable-stop span
  cut by an emergency-stop span). In b4, started at load 55.7, the gate's
  first autonomous=false sample left 305 ms after the button (detect FAIL),
  and a 1134 ms gap 1467 ms in ended the window at 600 ms: emergency stop.
  Neither is an island fault: the host-side 10 Hz gate is a Python process
  on a machine at load 28-60. The gate now logs `stall` events for its own
  timer and for the raw stream (added after b5); in b7 the 451.87 ms gap is
  both at once (timer 454.40 ms late, raw stream 474.77 ms late), i.e. host
  scheduling, not Autoware's converter alone.
- **The branch A velocity drop is the simulator.** The planning simulator
  has no driver model: on MANUAL, |v| goes to 0 in one sample. Nothing after
  the MANUAL edge in branch A is vehicle behaviour.
- **Hazard lights.** The island's `/system/emergency/hazard_lights_cmd` is
  ENABLE from the takeover request on (the upstream policy: hazards while the
  handler sees an emergency) in every run. The planning simulator's
  `/vehicle/status/hazard_lights_status` never reported ENABLE during an
  island MRM in these runs; the probe records both. Open.
- **Entry speeds** were 1.89-4.21 m/s, well under the declared 8.33 m/s
  bound; the declared settle rows are therefore loose by construction (the
  dashed curve on each plot is the derived stop from the observed speed).

## 5. Plots

Rendered by `tools/timeline/render.py` (the slide copies are
`takeover_timeline_{a,b,encore}.png` in the deck's assets):

- `docs/takeover-trace/timeline_a_a1.png` - branch A, run a1
- `docs/takeover-trace/timeline_b_b5.png` - branch B, run b5
- `docs/takeover-trace/timeline_encore_e1.png` - the encore, run e1

Lanes, top to bottom: |v| with the ODD bound and the derived stop; the mode
band; declared bars (hatched, from the checker) over observed bars (solid,
from events), one pair per rung the hazard reaches; the event ticks; the
verdicts.

## 6. Reproduce

```
just zephyr-build                        # native_sim, tracing on
tools/timeline/run-native.sh b b9        # or a / encore; -> build/timeline/b9/
python3 tools/timeline/render.py build/timeline/b9 --table
```

Run one at a time, and on a host below load ~35: b4 shows what a starved
gate does.
