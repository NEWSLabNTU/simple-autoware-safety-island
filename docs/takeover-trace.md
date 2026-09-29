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
  **Resolved by phase8-W12 (section 6): the tick was charged, in the route
  below the window; this table cut at the wrong edge.**
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
  both at once (timer 454.40 ms late, raw stream 474.77 ms late). That was
  read as host scheduling; W16 measured it (section 7): it was the gate's
  own executor thread blocked in a file write, and the C++ gate that
  replaces it holds 10 Hz at load 100+.
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

## 6. The window, settled (phase8-W12)

**What `window:` means.** A LEAST time. The 10 s is what the driver is
given (Drive Pilot's figure, decision 3): the request is never withdrawn and
no MRM starts before 10 s after the request went on. The handler guarantees
that by construction (`now - stamp < timeout` against the stamp it took when
the request went on, on one clock), and every run so far shows it: the
island-clock dwell has never been below 10000.00 ms. How LATE the MRM may
start is not a second number. play_launch charges the window up to its
DEADLINE (request on + 10 s) and then the rung below its own route, walked
from the guard, whose first hop is `/mrm_handler/call_mrm` 110 ms = the
100 ms tick the handler reads the deadline on + the 10 ms call. That is the
same shape the checker uses after the 500 ms staleness window (`hpc_loss`:
detect 500, then a route that starts with the tick), which the encore table
above already adds back. So the request ends within [10000, 10110] ms of
going on, and the fallback's command within 110 ms of the deadline.

**What was wrong.** Not the handler and not the arithmetic: (1) rlm v0.1.46
documented the window as "stay at most this long", the opposite of the
promise and not meetable by any implementation, since whatever enforces a
deadline notices it after it passes; (2) nothing CHECKED that the route below
a window holds the owner's notice (it held it here only because
`call_mrm`'s declared 110 ms contains the tick); (3) this document's branch B
table cut at the request-OFF edge, which lies inside that route, so the tick
was counted in "windows" and again in "route" (the 0.01 ms route rows above
are the other half of the same mistake). Adding the tick to WINDOWS, or
declaring `window: 10.1s`, would have charged it twice.

**What changed.**
- ros-launch-manifest v0.1.47 (text only): `window` is "at least", with the
  interval written out.
- play_launch bbf9c044 (phase 84): rule `window-expiry` (the route below a
  window must start at the node its `param:` names, and charge it at least
  the period of that node's timer that publishes the rung's output; a
  warning when no such timer is declared); `--explain` prints
  `window >=10000.00` and the interval the request ends in. No TOTAL moved.
- `tools/timeline/analysis.py`: branch B is cut at the deadline (request on
  + the declared, parameter-bound window, a derived instant); the dwell is
  checked against `[window, ends within]` read from the checker, on the
  island clock and as the host received it; a "windows + route" row needs no
  derived instant at all. The hard-coded "+ one tick" is gone.

The checker's rows for the live contract (play_launch bbf9c044):

```
odd_exit  takeover_request  window   100.00      0.00  110.00  window >=10000.00         -  30000.00         -
odd_exit  comfortable_stop  rung     100.00  10110.00  110.00    9996.67 derived  20316.67  30000.00   9683.33
odd_exit  emergency_stop    floor    100.00  10110.00  143.33    4165.33 derived  14518.67  30000.00  15481.33
  TOTAL = DETECT + WINDOWS + ROUTE + SETTLE; WINDOWS is the route and window of every windowed rung passed on the way, up to its deadline.
  A window is a least time (`window >=`); noticing its deadline is the first hop of the ROUTE below it (`window-expiry`), never a second charge.
  odd_exit/takeover_request: lasts at least 10000.00ms once on, and ends within 10110.00ms: /mrm_handler reads the deadline on its 100.00ms timer ('on_timer'), charged inside /mrm_handler/call_mrm 110.00ms, the first hop of the route below
```

**Three runs of branch B** on an image built from main 55a65a4 in a
worktree, with no handler change (`build-zephyr/zephyr/zephyr.exe`, sha256
`828ee7f5...8161bd48a3`, native_sim, tracing on), `tools/timeline/run-native.sh b
w12-b<n>`, one at a time under the demo lock, each started below load 35:

```
w12-b1 VERDICT: PASS b: v at the fault 3.87 m/s; TOR on True, mrm (3, 3) (3 = COMFORTABLE_STOP), v 0.000
w12-b2 VERDICT: FAIL b: v at the fault 3.86 m/s; TOR on True, mrm (3, 2) (3 = COMFORTABLE_STOP), v 0.000
w12-b3 VERDICT: PASS b: v at the fault 3.91 m/s; TOR on True, mrm (3, 3) (3 = COMFORTABLE_STOP), v 0.000
```

| term | declared | w12-b1 | w12-b2 | w12-b3 |
|---|---|---|---|---|
| detect (button -> verdict on the wire) | 100.00 | 98.68 | 11.77 | 4.73 |
| takeover route (verdict -> request on) | 110.00 | 65.74 | 75.08 | 34.25 |
| window dwell, island clock (request on -> off) | [10000.00, 10110.00] | 10100.00 | 10000.00 | 10000.00 |
| window dwell, host (request on -> off as received) | [10000.00, 10110.00] | 10099.58 | 10000.01 | 10002.09 |
| windows (verdict -> deadline = request on + window) | 10110.00 | 10065.74 | 10075.08 | 10034.25 |
| route, island clock (deadline -> velocity limit) | 110.00 | 100.01 | 0.01 | 0.01 |
| route, host (deadline -> velocity limit received) | 110.00 | 100.59 | 9.70 | 3.33 |
| windows + route (verdict -> velocity limit) | 10220.00 | 10165.74 | 10075.09 | 10034.25 |
| windows + route, host (verdict -> velocity limit received) | 10220.00 | 10168.52 | 10087.67 | 10038.17 |
| settle (velocity limit -> standstill) | 9996.67 | 8334.73 | 4435.95 | 5686.58 |
| total (button -> standstill) | 20316.67 | 18599.16 | 14522.80 | 15725.56 |
| rung reached | COMFORTABLE_STOP | COMFORTABLE_STOP | EMERGENCY_STOP FAIL | COMFORTABLE_STOP |
| HPC alive: longest availability gap (host) | 500.00 | 106.58 | 600.35 FAIL | 114.41 |
| entry speed (m/s) | 8.33 | 2.90 | 2.99 | 3.00 |

Load at start 26.2 / 32.1 / 21.5. Every window row passes in every run, on
both clocks. w12-b1 is the case finding 1 was about: the handler read the
deadline one full tick late (dwell 10100.00 on the island clock); cut at the
deadline, the notice sits in the route (100.01 against 110) and the windows
term reads 10065.74 against 10110. w12-b2's act FAIL is not the window:
2.9 s into the comfortable stop the host's availability stream went silent
for 600.35 ms (the gate logged 8 `stall` events, tick and raw stream both,
host load 32-53), the island rightly raised `hpc_loss` and escalated to the
emergency stop, as b3 did in W7. The run trace's `check` reports FAIL only
for the two `DRIVER_EXIT` markers, which branch B never reaches (nobody
takes over). Plot: `docs/takeover-trace/timeline_b_w12-b1.png`.

## 7. Reproduce

```
just zephyr-build                        # native_sim, tracing on
tools/timeline/run-native.sh b b9        # or a / encore; -> build/timeline/b9/
python3 tools/timeline/render.py build/timeline/b9 --table
```

Run one at a time. The load-35 rule of W7 was for the rclpy gate; the C++
gate (section 7) held its 10 Hz at a 1-min load of 100-130.

## 7. The gate stall (phase8-W16)

b3, b4 (W7) and w12-b2 (W12) failed branch B the same way: the host-side
availability gate went silent for 582-1134 ms, the island rightly raised
`hpc_loss` and escalated to the emergency stop. W16 measured where the
silence came from and replaced the gate.

**Where it was: the gate's one executor thread, blocked in the kernel on a
file write.** Measured with a synthetic 10 Hz `availability_raw` source, the
W7 rclpy gate unchanged, an external subscriber, and a 5 ms sampler of
`/proc/<gate>/task/*/{stat,wchan,schedstat}`:

- The load on this host is I/O, not CPU. At a 1-min load of 44-58 the
  threads were 33-68 in D state and 2-4 runnable; PSI cpu `some` 1.3 %, io
  `some` 95 % / `full` 81 %.
- Every gate stall of 100 ms or more was its main (rclpy executor) thread in
  D state, in `rq_qos_wait`, `folio_wait_bit_common`,
  `do_get_write_access` or `wait_transaction_locked` (block-layer write
  throttling, page writeback, the ext4 journal). No thread's `run_delay`
  grew by 30 ms or more between two samples: the run queue was never the
  cause.
- `strace -T` names the call: the gate rewrote `build/timeline/gate.pid.count`
  on every tick (open O_TRUNC, write, close), and ext4 flushes a file
  truncated and rewritten on close; that `close()` took 138 ms at load 60,
  and the sampler saw the same thread 375-2322 ms in D state under stress.
  The JSONL writes sat on the same thread. While it was blocked, neither the
  timer nor the raw subscription ran, so both stall markers fired together
  (b7's 454 / 475 ms): the "raw stream late" half was the gate not reading
  it. In the same runs an independent subscriber saw the raw source's own
  largest gap at 110-175 ms.
- Not Autoware's converter, not DDS: with the raw source regular, the rclpy
  gate still went silent; the C++ gate on the same DDS config, in the same
  runs, did not.
- Start-up is a second, separate hazard: under stress both gates took about
  200 s to start, blocked opening the rcl log file in `~/.ros/log` (btrfs on
  the spinning /home disk). `scenario.py gate` now passes
  `--disable-external-lib-logs`.

**The fix: `demo/host_ws/src/availability_gate`, a C++ rclcpp node** under
the same node name, topic contract and control interface:

- a 10 Hz wall timer republishes the LATEST raw sample while it is younger
  than 1.0 s (`raw_max_age_ms`), `autonomous &= !odd_exit`; nothing once it
  is older. Publishing on its own timer, not per raw sample, stays: the
  converter's own jitter (b1: 400-704 ms) never reaches the island, and a
  dead converter still silences the stream 1 s later;
- no file-system call on the executor thread after start-up: events and
  console lines go through a queue to a writer thread; the sample count the
  hpc-loss button reads is a 64-byte record in a MAP_SHARED page on /dev/shm
  (tmpfs, no writeback), updated by memcpy; its path follows the pid in
  `build/timeline/gate.pid`;
- `mlockall(MCL_CURRENT|MCL_FUTURE)` after start-up (RLIMIT_MEMLOCK is 8 GB
  here), so reclaim cannot turn a callback into a major fault;
- `gate-rt` runs it under SCHED_FIFO 20 when `ulimit -r` allows, else
  SCHED_OTHER with a warning. This user's rtprio limit is 0 (only `@audio`
  has an rtprio entry), so on this host it runs SCHED_OTHER;
- SIGUSR1 / SIGUSR2 and `/demo/odd/exit` set the ODD flag (applied, and its
  `odd` event stamped, at the next tick); SIGSTOP / SIGCONT stop and resume
  every thread, so the HPC-loss act is still true silence (checked: 3.80 s
  with no sample, the `last` event's n matching the count record); a
  `stats` event at exit gives the largest publish gap, SIGCONT resumes
  excluded.

**Load test.** 600 s per gate, counted from its first sample; each gate
with its own synthetic raw source and domain; the external subscriber is a
C++ node that keeps receipt times in memory (a Python subscriber stalled on
its own writes and was dropped after the first try). The host's ROS was
upgraded at 18:30-18:36 (rclcpp 16.0.19 -> 16.0.21, rmw_zenoh 0.1.10); s2
and s3 ran before it, s4 after, with the gate rebuilt against 16.0.21.

- s2, s3 (before the upgrade): stress-ng `--cpu 16 --hdd 4 --iomix 4 --vm 2
  --vm-bytes 2g` on the disk holding the gates' logs, on top of the host's
  own load. This drove the 1-min load to 100-134, far past the failures'
  27-56, on a shared host: too much, kept only as a bound.
- s4 (after the upgrade): the 1-min load held near 50 by nice-19
  `stress-ng --cpu 1` instances added and removed every 30 s, CPU only, the
  rest of the load being the host's own (mostly I/O). 1-min load, sampled
  every 30 s: 37.6 at t+0 s, 44.3-62.3 from t+120 s on, median 51.8.

| run | gate | 1-min load (min / median / max) | largest gap, external | gaps > 150 ms | largest gap, gate's own | stall events |
|---|---|---|---|---|---|---|
| s4 | W7 rclpy | 37.6 / 51.8 / 62.3 | 937.62 ms | 1 (1 > 500) | - | 3 |
| s4 | W16 C++, SCHED_OTHER | same run | 122.46 ms | 0 | 113.67 ms | 0 |
| s2 | W7 rclpy | 38.8 / 108.9 / 133.9 | 733.42 ms | 81 (9 > 250, 2 > 500) | - | 92 |
| s2 | W16 C++, SCHED_OTHER | same run | 146.98 ms | 0 | 131.39 ms | 0 |
| s3 | W16 C++, SCHED_OTHER | 41.3 / 99.5 / 125.4 | 124.36 ms | 0 | 122.93 ms | 0 |
| s3 | W16 C++, SCHED_FIFO 20 (L3 image, `--cap-add SYS_NICE --ulimit rtprio=20`, no mlock: the container's memlock limit) | same run | 128.96 ms | 0 | 104.53 ms | 0 |

s4's one rclpy silence (937.62 ms) was its main thread in D state
(`__wait_on_buffer`, `folio_wait_bit_common`, `rq_qos_wait`) under
CPU-only added load: the host's own I/O is enough.
The W7 gate's worst gaps republished the same raw sample (stamp gap 0):
its raw callback had not run. The C++ gate's residual lateness (up to
+47 ms over the 100 ms period under SCHED_OTHER) is the CPU run queue at
load 100+; SCHED_FIFO takes its own timer to +4.5 ms, and what is left in
the external column is the subscriber's own scheduling.

**Branch B with the C++ gate** (`tools/timeline/run-native.sh b w16-b<n>`,
each under `flock /tmp/claude-1000005/sai-demo.lock`; image
`c28dba8f...bcc8e`, native_sim, origin/main 3fb4cfb). w16-b1 ran before the
ROS upgrade, w16-b2..b5 after it with the gate rebuilt. w16-b2 was held
until the 1-min load was at least 40 (no added load). Verdicts verbatim,
with the load at start, the gate's largest publish gap (its `stats`) and
the longest gap the probe saw on `/system/operation_mode/availability`:

```
w16-b1 [37.74 41.46 55.31] VERDICT: PASS b: v at the fault 3.88 m/s; TOR on True, mrm (3, 3) (3 = COMFORTABLE_STOP), v 0.000
w16-b2 [47.74 55.28 59.63] VERDICT: PASS b: v at the fault 3.94 m/s; TOR on True, mrm (3, 3) (3 = COMFORTABLE_STOP), v 0.000
w16-b3 [50.95 53.15 58.17] VERDICT: FAIL b: v at the fault 3.86 m/s; TOR on True, mrm (3, 2) (3 = COMFORTABLE_STOP), v 0.000
w16-b4 [48.11 52.92 57.75] VERDICT: PASS b: v at the fault 3.88 m/s; TOR on True, mrm (3, 3) (3 = COMFORTABLE_STOP), v 0.000
w16-b5 [36.88 48.50 55.68] VERDICT: PASS b: v at the fault 3.92 m/s; TOR on True, mrm (3, 3) (3 = COMFORTABLE_STOP), v 0.000
```

| run | gate's largest publish gap | probe's longest availability gap |
|---|---|---|
| w16-b1 | 106.60 ms | 108.52 ms |
| w16-b2 | 102.29 ms | 109.32 ms |
| w16-b3 | 105.22 ms | 106.48 ms |
| w16-b4 | 104.04 ms | 110.80 ms |
| w16-b5 | 104.91 ms | 110.90 ms |

**w16-b3 is not the gate.** The stream never paused for more than 106 ms.
The island escalated because Autoware's own availability said the
comfortable stop was unavailable: the raw `comfortable_stop` flag (the gate
passes it through untouched) was false from 11.97 s to 13.37 s after the
button, 1.9 s into the comfortable stop, and the handler logged "no mrm
operation available: operate emergency_stop". play_launch's
diagnostics.csv names the cause: `topic_state_monitor_scenario_planning_trajectory`
went ERROR when `/planning/trajectory` was more than its 1.0 s timeout old
(last message 1.03 s before, measured rate 8.9 Hz). The planner, not the
gate, was starved. The same flag dropped for 3.2 s in w16-b2 and 2.0 s in
w16-b4, but inside the 10 s takeover window, where it does no harm. The
island's escalation is, again, the contract working: the comfortable-stop
rung needs planning. A load-independent branch B needs the planner's
trajectory rate held too, which is outside the gate.

## 8. The start-up gap (phase8-W29)

Every traced native_sim run had the island's first availability take at
0.202 s of simulated time and the second at 0.69-0.83 s: w8a-e 514 ms,
w14-e 521 ms, w27-a/b/e 632/583/488 ms, w26-a/b/e up to 705 ms. Past the
500 ms bound, it gave one tick of false MRM just after start-up.
W26's `15.565 s` episode in w26-e is the same thing, on the stamp
recorder's time base (the recorder starts about 15 s before the island).

**Where it was: the island's clock, not any hop of the stream.** Measured in
w29-base-a (main 53f032e) with the island's console stamped on the host
(`tools/timeline/stamp.py`, `island.trace.stamped.log`) and a 2 ms sampler
of native_sim's lag behind the host:

- The gate published every 100 ms from its first sample (its `stats`:
  largest publish gap 101.7 ms in w27-a, 100.2 ms in w27-b and w27-e), and
  the host probe heard every sample 100 ms apart. There was no gap on the
  wire, so neither discovery nor the gate's start-up nor the converter
  caused it.
- The island's boot costs 500-650 ms of host time (participant creation,
  Cyclone ingesting a running Autoware graph's discovery, the components'
  registration) at simulated time 0 to 0.2 s. native_sim's simulated clock
  does not move while embedded code computes or blocks in a host call. In
  real-time mode it only ever sleeps when it is AHEAD of the host
  (`timer_model.c`, `hwtimer_tick_timer_reached`), so afterwards it sprints
  until it is level again. The sampler: 591 ms behind the host at 9 ms,
  still 543 ms behind at the first spin (0.204 s), then falling 6 ms per
  6 ms of simulated time, level at 0.77 s.
- The host stamps show the sprint. `0.202 ... claimed at first spin` came at
  host +729 ms and `0.712 silence-runtime` came at +760 ms: 510 ms of island
  time in 31 ms of host time. The island's emergency control commands,
  published 33 ms apart on its clock, reached the probe 15 within 40 ms
  (w27-e) and 18 within 31 ms (w29-base-a). W26's own wall-clock stamps
  show the same thing: mrm_state stamped 100 ms apart on the island arrived
  2 ms apart on the host, and the MRM came at the instant the clock caught
  up.

The island took the latest sample at its first spin, and then its clock ran
half a second ahead in about 40 ms of host time. Nothing could arrive in
that window.

**The fix: the first spin waits for the clock** (`src/native_sim_entry/src/sim_clock_catch_up.c`).
The link wraps `nros_cpp_spin_once`, and the first call waits in `k_sleep`
until native_sim's clock is level with the host. The sprint then happens
before the island takes or times anything. It prints one line:

    [native_sim] first spin at 268 ms: the clock was 517 ms behind the host (boot work at simulated time 0), held 637 ms to catch up, 0 ms behind now

The board image does not include this file. A board's boot costs real time
before its first spin. In W10's cold resets, each 10 Hz input was taken
20-21 times in the first 2 s (`experiments/serial-interop/w10/runs/*/poll.excerpt.txt`).

| run | lag caught up | first two takes (s) | gap | largest gap, first 3 s | verdict |
|---|---|---|---|---|---|
| w29-base-a (before) | - | 0.202, 0.823 | 621 ms | 621 ms | PASS, false MRM at start |
| w29-a1 | 517 ms | 0.905, 0.924 | 19 ms | 121 ms | PASS |
| w29-b1 | 418 ms | 0.671, 0.678 | 7 ms | 138 ms | PASS |
| w29-a2 | 450 ms | 0.685, 0.726 | 41 ms | 100 ms | PASS |
| w29-b2 | 307 ms | 0.587, 0.598 | 11 ms | 134 ms | PASS |
| w29-a3 | 392 ms | 0.723, 0.786 | 63 ms | 101 ms | PASS |

None of the five had a start-up MRM. w29-a1 had a 100 ms COMFORTABLE_STOP
2.7 s after engage, and so did w27-a. That episode is Autoware's own raw
availability: one sample with `autonomous: false`, which the gate relayed
as it should (gate `publish` events n=264/265, `raw_autonomous: false`).
It is not a gap.

nros's `silence-runtime .../operation_mode_availability` warning still
appears once, 500 ms after the first spin, in every native_sim run and in all five of W23's QEMU runs.
It does so even when the trace shows takes every 100 ms, so it is not
evidence of a gap. The silence rule counts only the takes its age monitor
observes, and here it observes none.
