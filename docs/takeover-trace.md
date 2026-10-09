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
each under the demo lock (`flock` on one host-wide file, now
`${XDG_RUNTIME_DIR:-/tmp}/sai-demo.lock`); image
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

## 9. On silicon (phase8-W8)

phase8-W8, 2026-09-30. The three acts on the S32K344 (NXP MR-CANHUBK3, the
DCD-LZ serial cable at 921,600 baud, `just l3-peer` as the island gateway),
with Autoware 1.5.0 in the container, all driven by
`tools/timeline/run-board.sh`. The script flashes the board, starts the
gateway and resets the board, waits for the island, then starts Autoware,
the gate, the probe and the act. At the end it reads the trace over SWD
and merges it.

- Island: main `88a336f` (W28: INIT ends when every input is
  established), nano-ros `f03d9d190`. `just board-build`, board ELF sha256
  `780195b0c8effb43f4e7ac09bf3580cd0fcb9d9ffee374adf29c7c525c80cde6`
  (hex `9c4d72a419fff86a417d5fffbb9ceab86a7f43a9d5e6e1e8c0cbcd3bfdc0117a`).
  RAM 290,728 of 327,680 B (88.72 %). The trace window has a 32 KiB
  buffer. The heap is 102,400 B, main runs at priority 5, the RX ring is
  4096 B and the lease 60 s.
- Autoware: `sai-l3-autoware:1.5.0-w24`. Every start read `nodes 31/31,
  containers 13/13, composable 68/68`, on the first attempt.
- Gate: `scenario.py gate` on the host, the C++ `availability_gate` from
  `just demo-host-ws`.
- Every run was flashed and reset. Each started under
  the demo lock at a 1-min load below 35 (run-board.sh takes
  `${XDG_RUNTIME_DIR:-/tmp}/sai-demo.lock` itself since phase9-W22).

**The heap on the board.** The boot record was read over SWD (attach mode,
no halt) with the island joined to the running container Autoware
through the gateway, 40 s after the gate came up (run `w8-bringup`):

    stage      6  FirstSpin -- registration complete and spinning
      platform heap PEAK            77160 bytes   (75.0% of the heap)
      platform heap capacity        102912 bytes   (NROS_ZEPHYR_HEAP_SIZE)
    HEAP HEADROOM: ok -- 25752 bytes spare (peak 77160 of 102912, floor 24576).

The record's peak is a running maximum: `nros_platform_alloc` updates it on
every allocation. Read again after the tenth run (w8-r10, act A), it still
said 77,160. So 102,400 B stays. The board's peak is 5,808 B above
QEMU's FirstSpin peak on the same pin (W26: 71,352), and it does not
exhaust the way W17's QEMU island did through the gateway. W17 expected
this: over TCP nothing paces Autoware's traffic the way the UART does.

### The verdicts

The three single acts, then the ten consecutive runs, all on the same
image (verbatim, from each run's `scenario.jsonl`; the load is the 1-min
average at the start):

```
w8-a1  (4.58) VERDICT: PASS a: v at the fault 3.84 m/s; TOR on True, TOR now 1, control mode 4, mrm (1, 1)
w8-b1  (4.79) VERDICT: PASS b: v at the fault 3.86 m/s; TOR on True, mrm (3, 3) (3 = COMFORTABLE_STOP), v 0.000
w8-e1  (8.10) VERDICT: PASS encore: v at the fault 3.88 m/s; mrm (3, 2) (2 = EMERGENCY_STOP), v 0.000, after restore mrm (1, 1)
w8-r01 (4.00) VERDICT: PASS a: v at the fault 3.86 m/s; TOR on True, TOR now 1, control mode 4, mrm (1, 1)
w8-r02 (9.09) VERDICT: PASS b: v at the fault 3.85 m/s; TOR on True, mrm (3, 3) (3 = COMFORTABLE_STOP), v 0.000
w8-r03 (8.83) VERDICT: PASS encore: v at the fault 3.88 m/s; mrm (3, 2) (2 = EMERGENCY_STOP), v 0.000, after restore mrm (1, 1)
w8-r04 (8.13) VERDICT: PASS a: v at the fault 3.92 m/s; TOR on True, TOR now 1, control mode 4, mrm (1, 1)
w8-r05 (8.82) VERDICT: PASS b: v at the fault 3.90 m/s; TOR on True, mrm (3, 3) (3 = COMFORTABLE_STOP), v 0.000
w8-r06 (6.15) VERDICT: PASS encore: v at the fault 3.90 m/s; mrm (3, 2) (2 = EMERGENCY_STOP), v 0.000, after restore mrm (1, 1)
w8-r07 (4.61) VERDICT: PASS a: v at the fault 3.92 m/s; TOR on True, TOR now 1, control mode 4, mrm (1, 1)
w8-r08 (4.82) VERDICT: PASS b: v at the fault 3.86 m/s; TOR on True, mrm (3, 3) (3 = COMFORTABLE_STOP), v 0.000
w8-r09 (7.94) VERDICT: PASS encore: v at the fault 3.92 m/s; mrm (3, 2) (2 = EMERGENCY_STOP), v 0.000, after restore mrm (1, 1)
w8-r10 (17.46) VERDICT: PASS a: v at the fault 3.90 m/s; TOR on True, TOR now 1, control mode 4, mrm (1, 1)
```

13 of 13 PASS, and `trace-check: PASS` on all 13 traces. Every act's
trigger was the detector path's ENTRY. The window's history ran 37-48
records over 1469-1500 ms. After the trigger the board wrote 534-607 B/s,
a 4.57-24.83 s act in 2,540-13,626 B of the 32 KiB buffer. The SWD
readout held the core halted 0.181-0.225 s.

### Encore: HPC loss, board next to native_sim

| term | declared | e1 | r03 | r06 | r09 | native_sim (W7 e1-e3) |
|---|---|---|---|---|---|---|
| detect (last sample -> reaction tick) | 600.00 | 567.56 | 575.78 | 534.90 | 535.40 | 520.00-537.99 |
| route (reaction tick -> braking command) | 143.33 | 8.37 | 7.32 | 7.43 | 6.88 | 26.00-32.04 |
| detect + route (last sample -> braking command) | 643.33 | 575.93 | 583.10 | 542.34 | 542.29 | 546.98-570.02 |
| settle (braking command -> standstill) | 4165.33 | 2963.67 | 2941.53 | 2923.25 | 2907.50 | 2924.79-2958.15 |
| total (last sample -> standstill) | 4808.67 | 3539.60 | 3524.63 | 3465.59 | 3449.79 | 3473.23-3507.14 |
| within the FTTI | 10000.00 | 3539.60 | 3524.63 | 3465.59 | 3449.79 | same as total |
| rung reached | EMERGENCY_STOP | EMERGENCY_STOP | EMERGENCY_STOP | EMERGENCY_STOP | EMERGENCY_STOP | EMERGENCY_STOP |
| entry speed (m/s) | 8.33 | 4.21 | 4.22 | 4.22 | 4.23 | 4.16-4.20 |

Every row PASS in all four. On the board the detect is real time. It is
the 500 ms staleness bound plus the handler's tick phase, 34.90-75.78 ms
of it. The route is the handler's EMERGENCY_STOP tick to the braking
command received on the host, 6.88-8.37 ms. On native_sim the same row was
26-32 ms of loopback and host scheduling. (W26 on native_sim: last
sample to braking 622.99 ms, to standstill 3,437.37; W28: detect 560.98,
total 3,406.56.)

### Branch A: ODD exit, the driver takes over

| term | declared | a1 | r01 | r04 | r07 | r10 |
|---|---|---|---|---|---|---|
| detect (button -> verdict on the wire) | 100.00 | 34.18 | 81.09 | 25.10 | 55.95 | 29.90 |
| takeover route (verdict -> request on) | 110.00 | 108.95 | 73.80 | 113.56 FAIL | 119.26 FAIL | 88.29 |
| driver answered inside the window | 10000.00 | 3033.92 | 3045.75 | 3085.41 | 3027.94 | 3032.06 |
| exit route (MANUAL taken -> request off) | 100.00 | 72.87 | 58.99 | 46.18 | 54.55 | 63.33 |
| no MRM | none | none | none | none | none | none |
| HPC alive: longest availability gap (host) | 500.00 | 110.95 | 103.31 | 108.91 | 101.45 | 104.84 |

### Branch B: ODD exit, nobody answers

| term | declared | b1 | r02 | r05 | r08 |
|---|---|---|---|---|---|
| detect (button -> verdict on the wire) | 100.00 | 60.30 | 30.49 | 53.93 | 40.33 |
| takeover route (verdict -> request on) | 110.00 | 145.35 FAIL | 51.18 | 60.23 | 118.82 FAIL |
| window dwell, island clock (request on -> off) | [10000.00, 10110.00] | 10114.30 FAIL | 10113.35 FAIL | 10114.26 FAIL | 10116.42 FAIL |
| window dwell, host (as received) | [10000.00, 10110.00] | 10109.94 | 10095.38 | 10139.04 FAIL | 10108.70 |
| windows (verdict -> deadline) | 10110.00 | 10145.35 FAIL | 10051.18 | 10060.23 | 10118.82 FAIL |
| route, island clock (deadline -> velocity limit) | 110.00 | 115.38 FAIL | 114.73 FAIL | 115.30 FAIL | 117.47 FAIL |
| route, host (deadline -> velocity limit received) | 110.00 | 110.17 FAIL | 95.75 | 139.26 FAIL | 109.01 |
| windows + route (verdict -> velocity limit) | 10220.00 | 10260.73 FAIL | 10165.90 | 10175.53 | 10236.28 FAIL |
| settle (velocity limit -> standstill) | 9996.67 | 6722.64 | 5128.49 | 5545.83 | 6372.61 |
| total (button -> standstill) | 20316.67 | 17043.67 | 15324.88 | 15775.29 | 16649.22 |
| within the FTTI | 30000.00 | 17043.67 | 15324.88 | 15775.29 | 16649.22 |
| rung reached | COMFORTABLE_STOP | COMFORTABLE_STOP | COMFORTABLE_STOP | COMFORTABLE_STOP | COMFORTABLE_STOP |
| HPC alive: longest availability gap (host) | 500.00 | 101.54 | 104.87 | 106.12 | 108.81 |
| entry speed (m/s) | 8.33 | 3.09 | 3.03 | 3.05 | 3.08 |

(The host form of `windows + route` equals the island form in every run
and is left out.)

### What the FAIL rows are

Every act reached its rung and every total stayed inside its FTTI. Six
of the 13 runs (b1, r02, r04, r05, r07, r08) have at least one
intermediate row that goes 0.17-40.73 ms past a 110 ms route or the window's 10,110 ms end. The island trace shows
three costs. Each one is real on silicon and is zero, or nearly zero, on
native_sim, where the contract's 110 ms (the handler's 100 ms tick plus
10 ms) was set:

1. **The serial hop in.** From the gate's publish on the host to the
   island's take of the first `autonomous: false` sample took 13.25-47.43 ms
   (a1 15.29, b1 42.18, r01 47.43, r02 30.32, r04 13.25, r05 30.22, r07
   33.51, r08 30.76, r10 34.23; host edge against the merged island edge).
   The takeover route is that hop plus the wait for the next handler tick
   (20.85-103.17 ms). It passes when the tick comes soon after the take
   (r01, r02, r05, r10) and fails when it does not (b1: 42.18 + 103.17;
   r08: 30.76 + 88.05).
2. **Work inside the tick, before the publish.** The on-tick publishes the
   TOR state 5.41-9.66 ms after the tick's `call_mrm` ENTRY. The expiry
   tick first makes the synchronous `comfortable_stop/operate` call
   (11.23-17.76 ms into the tick), then publishes `mrm_state` and the TOR
   state (17.44-23.97 ms in). The expiry tick itself came 10,097.39-10,102.24 ms
   after the on-tick: the window plus one tick, as on native_sim. The
   in-tick difference makes the island-clock dwell 10,113.35-10,116.42 ms.
   The velocity limit follows from the operator's service handler,
   114.73-117.47 ms after the deadline. native_sim runs that work in zero time; the MCU
   does not.
3. **The serial hop out.** In r05 the host received `mrm_state`, the TOR
   state and the velocity limit together, 24.8 ms after the island
   published TOR off. That is why r05's host dwell (10,139.04) and host
   route (139.26) exceed their island-clock values.

Also, the handler's tick on the board is spaced 81.96-114.84 ms (in a1;
90.13-106.60 in the other A and B runs). Merging the island clock onto the host
clock costs more over serial than on loopback: the publish/receipt pair
spread was 0.15-43.22 ms, and the two anchors disagreed by 13.05-47.62 ms
(native_sim: under 1 ms). So a cross-clock row (the takeover route,
`windows`) carries that much uncertainty. The island-clock rows (dwell,
route) and the host-only rows do not.

The contract's route terms were derived from the handler's tick. They do
not charge the link or the in-tick service call, so on silicon they are
10-40 ms short. The fault reaction as a whole has seconds of slack against
its FTTI: B's total 15.3-17.0 s against 30 s, the encore's 3.45-3.54 s
against 10 s. Charging the link's measured hop and the in-tick call to
the route is a contract change, which is a separate decision; nothing here
changes it.

Not seen on the board: the simulator's hazard-lights status never showed
ENABLE (`hazard_lights_on -` in every table). The board stamps from boot
(no SNTP over serial), so its hazard command carries a boot-relative
stamp. The island's own ENABLE (`island_hazard_cmd_on`) is in every trace,
at the TOR-on tick. Braking is unaffected.

Runs, tables and plots: `build/timeline/w8-{a1,b1,e1,r01..r10}/` in the W8
worktree (`timeline.png`, `table.md`, `island.trace*`, the JSONL files).
The render labels the rung from `island.trace.meta` (`target=board`).

## 10. The board budget (phase8-W30)

phase8-W30, 2026-09-30. Decision (the user's): the contract's budgets
respect the hardware the island runs on, the S32K344 behind the gateway
and the UART, not the native_sim calibration. Section 9 found three costs
the 110 ms handler hop did not hold. This section sizes each one from all
13 W8 board runs, states it in the contract, and re-analyses every run
offline against the new contract. Nothing here touched the board or W8's
run directories.

### The terms

Measured by `terms.py` (in the re-analysis directory below) from each
run's merged `island.jsonl` (the island's own clock, `island_ns`), and
`gate.jsonl`. Each term is the maximum over the 13 runs plus 20 %, rounded
up to the next ms. The 100 ms period is `update_rate: 10` and takes no
margin.

| term | what | observed (all 13 runs) | max (run) | +20 % | declared | over the max |
|---|---|---|---|---|---|---|
| link | gate publish (host) -> island take of the same verdict edge | 12.29-47.43 ms, 18 edges | 47.43 (r01) | 56.92 | 57 | +9.57 |
| tick | a take waits for the next tick: consecutive ticks | 81.96-114.84 ms, 1641 gaps | 114.84 (a1) | 100 + 17.81 | 118 | +3.16 |
| work | tick start -> the reaction's last publish (the velocity limit on the expiry tick) | 0.40-25.04 ms | 25.04 (b1) | 30.05 | 31 | +5.96 |
| **call_mrm** | link + tick + work | sum of maxima 187.31 | - | - | **206** | +18.69 |
| driver_exit | tick + work (starts at the island's take: no link) | observed 46.18-72.87 | 72.87 (a1) | - | 149 | +9.12 over tick + work maxima |
| control_mode transport | host receipt of MANUAL -> island take (link + the gateway's 40 -> 10 Hz downsampler) | 63.65-118.78 ms, 5 edges | 118.78 (r07) | 142.54 | 143 | +24.22 |

The pieces of `work`: the request goes on 5.41-9.66 ms into its tick; the
expiry tick calls `comfortable_stop/operate` 11.23-17.76 ms in, publishes
the request off 17.44-23.97 ms in and returns 17.64-24.16 ms in; the
operator is served next on the same executor and publishes the velocity
limit 0.85-1.18 ms after the handler returns (18.48-25.04 ms after the
tick began). a1's ticks run on the 100 ms grid up to 14.84 ms late (a late
tick is followed by a short one, 81.96 ms); every other run stays within
88.07-110.11 ms.

### Where each term is stated, and why there

- `call_mrm: max_latency: 206ms` (it was 110) and the subscriber's
  `on_violation.within: 206ms` (`reaction-within` requires within >= the
  path). The walk charges it as the takeover route and as the first hop
  after the window's deadline (`window-expiry`), so the request now ends
  within 10,206 ms of going on. The derivation, with the runs, is the
  comment at `call_mrm` in `safety_island.contract.yaml`.
- The link is ALSO `max_transport: 57ms` on `mrm_handler/
  operation_mode_availability`, the per-subscriber key rlm has for exactly
  this (the island's subscriber is behind the UART; a host subscriber of
  the same topic is not). play_launch 0.13.0 does not charge transport in
  the fault arithmetic: `walk_reaction` sums path latencies and sampling
  periods only, and a reported fault's detection is the publisher's period
  plus its path latency (manifest_loader.rs at v0.13.0). With an external
  publisher the nominal graph has no edge to weigh either: the island
  contract's `--explain` output is byte-identical with and without the
  key. So the 57 ms is counted once, inside `call_mrm`. That is follow-up
  F1. The cost is stated in the contract: after the deadline no message
  crosses the link, so there the 57 ms is slack, and 0.13.0 has one number
  per hop.
- `driver_exit: max_latency: 149ms` (it was 100): the same tick and work,
  no link.
- `control_mode: max_transport: 143ms`: stated as the fact; nothing in the
  fault arithmetic reads it (the driver's answer is bounded by the window,
  on the host).
- The comfortable operator's `operate` path gets NO `max_latency`. Its
  cost is inside `call_mrm`'s work term, measured to the limit publish. A
  number there would also become the node's derived deadline and a 2 ms
  runtime latency monitor on the velocity limit in the image: nano-ros
  derives both from node-path latencies (the 780195b0 build's generated
  entry bakes `mrm_state` and `takeover_request_state` at 110 ms, the max
  of the paths that publish them).
- The demo compositions (`demo/l3/contracts/*`) state the same 206 / 149 /
  143. They do NOT declare the 57 ms `max_transport`: there the gate is in
  the tree, the nominal walk weighs the gate -> handler edge, and the link
  would be charged twice (island.tor's critical path read 283 ms with it,
  226 ms without). island.tor's nominal budget there is 226 ms (the gate's
  20 + `call_mrm` 206; it was 210).

rlm has no key for a timer's release jitter or for a service edge's
queueing; both are stated inside `call_mrm` (F2, F3). `tools/timeline/
analysis.py` adds the tick share (118) back to the encore's detect row, as
it added 100 before, and reads the exit row's bound from the contract.

### Which rows compare the island clock with the host clock

- Host clock only: detect (A, B), dwell as received, route as received,
  `windows + route` as received, settle, total, the availability gap.
- Island clock only: dwell, route (deadline -> velocity limit), the exit
  route, and the whole encore up to the braking command.
- Cross-clock: the takeover route, `windows`, `windows + route` (an island
  edge against the gate's host stamp). The re-analysed tables mark them
  "island vs host clock".

How the uncertainty is treated: merge.py moves island stamps onto the host
clock by the SMALLEST publish -> receipt pair. A receipt is never before
its publish, so that offset never places an island event earlier than it
happened; a cross-clock row is over-stated by the smallest out-link delay
and never under-stated. The link term is sized from those same
cross-clock edges, so it carries the same (conservative) error. Section
9's "the two anchors disagreed by 13.05-47.62 ms" is, in the A and B runs,
the in-link hop itself rather than an error: anchor 2 is an availability
sample both sides saw, which assumes it reached both at once, and its
disagreement matches the measured link edge to 0.13-0.62 ms in all nine A
and B runs (b1 41.92 against 42.18, r01 46.81 against 47.43, a1 15.13
against 15.29).

### The checker

`just l3-check` and `.github/check-contracts.sh` with the pinned
play_launch 0.13.0: 14 contracts, every verdict as expected. The island
contract is clean (0 errors, the same 5 warnings without Autoware's `.msg`
files on the index, 2 with). The two variants still fail their
comfortable-stop rung and nothing else: `l3_takeover_window20` 30,828.67 ms
and `l3_takeover_65kmh` 30,558.67 ms against 30,000 (were 30,636.67 and
30,366.67); their floors fit (24,730.67 and 18,622.67; hpc_loss 4,904.67
and 8,796.67). No variant needed a change: the smallest breaks moved to a
window above 19.17 s and a bound above 63.0 km/h. The island contract's
table, as `tools/timeline/testdata/explain.txt` now holds it:

```
HAZARD    RUNG              ROLE     DETECT   WINDOWS   ROUTE             SETTLE     TOTAL      FTTI     SLACK
hpc_loss  takeover_request  skipped       -         -       -                  -         -  10000.00         -
hpc_loss  comfortable_stop  skipped       -         -       -                  -         -  10000.00         -
hpc_loss  emergency_stop    floor    500.00      0.00  239.33    4165.33 derived   4904.67  10000.00   5095.33
odd_exit  takeover_request  window   100.00      0.00  206.00  window >=10000.00         -  30000.00         -
odd_exit  comfortable_stop  rung     100.00  10206.00  206.00    9996.67 derived  20508.67  30000.00   9491.33
odd_exit  emergency_stop    floor    100.00  10206.00  239.33    4165.33 derived  14710.67  30000.00  15289.33
  odd_exit/takeover_request: lasts at least 10000.00ms once on, and ends within 10206.00ms: /mrm_handler reads the deadline on its 100.00ms timer ('on_timer'), charged inside /mrm_handler/call_mrm 206.00ms, the first hop of the route below
```

(Before: routes 110.00 and 143.33, WINDOWS 10110.00, totals 20316.67,
14518.67 and 4808.67.) The resolved model moves in three numbers only:
`within_ms` 110 -> 206, `call_mrm` 110 -> 206, `driver_exit` 100 -> 149;
it carries no transport. `just trace-gen` regenerated the marker header
and table for the new contract digest (`e88319a3...`); the next board
image bakes it, and by the rule above its `mrm_state` and
`takeover_request_state` monitors at 206 ms (not built here).

### Before and after, every board run

`analysis.py` and `render.py` on a copy of each run's JSONL files, with the
new `--explain`. "FAIL->PASS" is a verdict the new budget changed; the
last column is the new bound minus the largest observation.

**Branch A.**

| term | declared before | declared after | a1 | r01 | r04 | r07 | r10 | max observed | after - max |
|---|---|---|---|---|---|---|---|---|---|
| detect (button -> verdict on the wire) | 100.00 | 100.00 | 34.18 PASS | 81.09 PASS | 25.10 PASS | 55.95 PASS | 29.90 PASS | 81.09 | 18.91 |
| takeover route (verdict -> request on) | 110.00 | 206.00 | 108.95 PASS | 73.80 PASS | 113.56 FAIL->PASS | 119.26 FAIL->PASS | 88.29 PASS | 119.26 | 86.74 |
| driver answered inside the window | 10000.00 | 10000.00 | 3033.92 PASS | 3045.75 PASS | 3085.41 PASS | 3027.94 PASS | 3032.06 PASS | 3085.41 | 6914.59 |
| exit route (MANUAL taken -> request off) | 100.00 | 149.00 | 72.87 PASS | 58.99 PASS | 46.18 PASS | 54.55 PASS | 63.33 PASS | 72.87 | 76.13 |
| no MRM | none | none | none PASS | none PASS | none PASS | none PASS | none PASS | - | - |
| HPC alive: longest availability gap (host) | 500.00 | 500.00 | 110.95 PASS | 103.31 PASS | 108.91 PASS | 101.45 PASS | 104.84 PASS | 110.95 | 389.05 |

**Branch B.**

| term | declared before | declared after | b1 | r02 | r05 | r08 | max observed | after - max |
|---|---|---|---|---|---|---|---|---|
| detect (button -> verdict on the wire) | 100.00 | 100.00 | 60.30 PASS | 30.49 PASS | 53.93 PASS | 40.33 PASS | 60.30 | 39.70 |
| takeover route (verdict -> request on) | 110.00 | 206.00 | 145.35 FAIL->PASS | 51.18 PASS | 60.23 PASS | 118.82 FAIL->PASS | 145.35 | 60.65 |
| window dwell, island clock (request on -> off) | [10000.00, 10110.00] | [10000.00, 10206.00] | 10114.30 FAIL->PASS | 10113.35 FAIL->PASS | 10114.26 FAIL->PASS | 10116.42 FAIL->PASS | 10116.42 | 89.58 |
| window dwell, host (request on -> off as received) | [10000.00, 10110.00] | [10000.00, 10206.00] | 10109.94 PASS | 10095.38 PASS | 10139.04 FAIL->PASS | 10108.70 PASS | 10139.04 | 66.96 |
| windows (verdict -> deadline = request on + window) | 10110.00 | 10206.00 | 10145.35 FAIL->PASS | 10051.18 PASS | 10060.23 PASS | 10118.82 FAIL->PASS | 10145.35 | 60.65 |
| route, island clock (deadline -> velocity limit) | 110.00 | 206.00 | 115.38 FAIL->PASS | 114.73 FAIL->PASS | 115.30 FAIL->PASS | 117.47 FAIL->PASS | 117.47 | 88.53 |
| route, host (deadline -> velocity limit received) | 110.00 | 206.00 | 110.17 FAIL->PASS | 95.75 PASS | 139.26 FAIL->PASS | 109.01 PASS | 139.26 | 66.74 |
| windows + route (verdict -> velocity limit) | 10220.00 | 10412.00 | 10260.73 FAIL->PASS | 10165.90 PASS | 10175.53 PASS | 10236.28 FAIL->PASS | 10260.73 | 151.27 |
| windows + route, host (verdict -> velocity limit received) | 10220.00 | 10412.00 | 10260.73 FAIL->PASS | 10165.90 PASS | 10199.49 PASS | 10236.28 FAIL->PASS | 10260.73 | 151.27 |
| settle (velocity limit -> standstill) | 9996.67 | 9996.67 | 6722.64 PASS | 5128.49 PASS | 5545.83 PASS | 6372.61 PASS | 6722.64 | 3274.03 |
| total (button -> standstill) | 20316.67 | 20508.67 | 17043.67 PASS | 15324.88 PASS | 15775.29 PASS | 16649.22 PASS | 17043.67 | 3465.00 |
| within the FTTI | 30000.00 | 30000.00 | 17043.67 PASS | 15324.88 PASS | 15775.29 PASS | 16649.22 PASS | 17043.67 | 12956.33 |
| rung reached | COMFORTABLE_STOP | COMFORTABLE_STOP | COMFORTABLE_STOP PASS | COMFORTABLE_STOP PASS | COMFORTABLE_STOP PASS | COMFORTABLE_STOP PASS | - | - |
| HPC alive: longest availability gap (host) | 500.00 | 500.00 | 101.54 PASS | 104.87 PASS | 106.12 PASS | 108.81 PASS | 108.81 | 391.19 |
| entry speed (m/s) | 8.33 | 8.33 | 3.09 PASS | 3.03 PASS | 3.05 PASS | 3.08 PASS | 3.09 | 5.24 |

**Encore.**

| term | declared before | declared after | e1 | r03 | r06 | r09 | max observed | after - max |
|---|---|---|---|---|---|---|---|---|
| detect (last sample -> reaction tick) | 600.00 | 618.00 | 567.56 PASS | 575.78 PASS | 534.90 PASS | 535.40 PASS | 575.78 | 42.22 |
| route (reaction tick -> braking command) | 143.33 | 239.33 | 8.37 PASS | 7.32 PASS | 7.43 PASS | 6.88 PASS | 8.37 | 230.96 |
| detect + route (last sample -> braking command) | 643.33 | 739.33 | 575.93 PASS | 583.10 PASS | 542.34 PASS | 542.29 PASS | 583.10 | 156.23 |
| settle (braking command -> standstill) | 4165.33 | 4165.33 | 2963.67 PASS | 2941.53 PASS | 2923.25 PASS | 2907.50 PASS | 2963.67 | 1201.66 |
| total (last sample -> standstill) | 4808.67 | 4904.67 | 3539.60 PASS | 3524.63 PASS | 3465.59 PASS | 3449.79 PASS | 3539.60 | 1365.07 |
| within the FTTI | 10000.00 | 10000.00 | 3539.60 PASS | 3524.63 PASS | 3465.59 PASS | 3449.79 PASS | 3539.60 | 6460.40 |
| rung reached | EMERGENCY_STOP | EMERGENCY_STOP | EMERGENCY_STOP PASS | EMERGENCY_STOP PASS | EMERGENCY_STOP PASS | EMERGENCY_STOP PASS | - | - |
| entry speed (m/s) | 8.33 | 8.33 | 4.21 PASS | 4.22 PASS | 4.22 PASS | 4.23 PASS | 4.23 | 4.10 |

21 row verdicts moved FAIL -> PASS (b1 7, r08 6, r05 4, r02 2, r04 1,
r07 1); none moved the other way; the 13 act verdicts were PASS before and
are PASS now. Every row of every run passes.

Why the rows keep 60-90 ms over their largest observation when each term
keeps only 3-10 ms: the budget is the sum of three worst cases, and no run
put all three in one reaction (b1's 145.35 was a 42.18 link, a 93.51
wait and 9.66 of work; the largest work, 25.04, came on an expiry
tick, where the link is not in the route at all). After the deadline the
57 ms link term is slack by construction (F1). The encore's routes keep
the most (231 ms): an omission never crosses the link, and the emergency
operator's tick is charged in full by the walk.

### Follow-ups

- F1 (play_launch): charge `sub.max_transport ?? topic.max_transport` on
  the guard edge in `walk_reaction` and in a reported fault's detection,
  but not on the first hop after a window's deadline (the owner reads its
  own clock). Then `call_mrm` drops to 149 ms and the window ends within
  10,149 ms; the island contract says where to take the 57 out.
- F2 (rlm): a timer trigger has a rate and no release jitter. The tick
  share (100 + 18) is stated inside `call_mrm` and as `analysis.TICK_MS`;
  a jitter key on the timer would let the walk and `window-expiry` charge
  period + jitter themselves.
- F3 (rlm / nano-ros): a service edge has no transport or queueing key, and
  a node-path `max_latency` doubles as nano-ros's node deadline and runtime
  monitor, so the operator's serve-after-tick cost (0.85-1.18 ms) cannot
  be stated where it happens without changing the image's scheduling.
- F4 (measure): the link hop of kinematic_state, operation_mode_state and
  control_cmd (the trace keeps no per-sample take for them), and the
  emergency operator's 30 Hz tick jitter (its ticks are kept one in ten).
- F5 (board): run the three acts on an image built from this contract (the
  206 ms monitors, the new marker digest). What the handler does for
  5.4-9.7 ms before its first publish, and 11-18 ms before the operate
  call, is not profiled.

Re-analysis: `/mnt/mx500/aeon/worktrees/w30-reanalysis/<run>/` (`table.md`,
`table.before.md` = W8's, `timeline.png`, `explain.txt`), `terms.py` and
`terms.txt` (the terms), `compare.py` and `compare.md` (the tables above),
`l3-check.txt` and `check-contracts.txt`.

## 11. Fresh runs against the board-derived budgets (phase8-W31)

phase8-W31, 2026-09-30. Section 10 derived the board budgets from W8's
runs and re-analysed those same runs. This section runs the three acts
again on the S32K344 with an image built from that contract, so the
budgets are tested on runs they were not sized from. The rig and method
are section 9's: `tools/timeline/run-board.sh`, `sai-l3-autoware:1.5.0-w24`,
the C++ gate from `just demo-host-ws`, and every run flashed and reset
under the demo lock at a 1-min load below 35 (run-board.sh takes
`${XDG_RUNTIME_DIR:-/tmp}/sai-demo.lock` itself since phase9-W22).

**The image.** Main `71743c3` (W30), nano-ros `f03d9d190`, `just board-build`
in a fresh worktree. `just trace-gen-check`: "header and table current (31
markers)", every marker has a call site. Board ELF sha256
`664592d4cdb110ff64a9ef95410c4de7123cae0e006fe8a5bce302c68893289d`
(hex `13daca9c562a8877dacf8afbd4f65ecfe1e42a12f95e9423fe34abdd2c3d7099`).
RAM 290,728 of 327,680 B (88.72 %) and FLASH 611,672 B, against
780195b0's 611,668. Against W8's `780195b0`, the generated entry
(`zephyr_entry_nros_main_generated.cpp`) differs in two monitor rows,
and nowhere else except its own path:

```
<     { "/system/fail_safe/mrm_state", "/mrm_handler/mrm_state", 10000u, 110u },
<     { "/system/takeover_request/state", "/mrm_handler/takeover_request_state", 10000u, 110u },
---
>     { "/system/fail_safe/mrm_state", "/mrm_handler/mrm_state", 10000u, 206u },
>     { "/system/takeover_request/state", "/mrm_handler/takeover_request_state", 10000u, 206u },
```

The fourth field is `max_latency_ms`. The hazard-lights row (100) and the
availability age row (500) are unchanged. The per-node declared-QoS and
params headers are byte-identical. The resolved model moves in
`within_ms` 110 -> 206, `call_mrm` 110 -> 206 and `driver_exit`
100 -> 149, plus the diagnostics that quote them. The marker header
carries the contract digest `e88319a3...` (was `990442fc...`).

**The heap on the board.** Read as in section 9 (run `w31-bringup`: the
island joined to the container Autoware through `just l3-peer`, and the
boot record read over SWD 40 s after the gate came up):

    stage      6  FirstSpin -- registration complete and spinning
      platform heap PEAK            77160 bytes   (75.0% of the heap)
      platform heap capacity        102912 bytes   (NROS_ZEPHYR_HEAP_SIZE)
    HEAP HEADROOM: ok -- 25752 bytes spare (peak 77160 of 102912, floor 24576).

This is the same peak as 780195b0.

### The verdicts

The acts ran in the order a, b, encore, three times. The load is the 1-min
average at the start of each run:

```
w31-r01 (5.14) VERDICT: PASS a: v at the fault 3.92 m/s; TOR on True, TOR now 1, control mode 4, mrm (1, 1)
w31-r02 (5.76) VERDICT: PASS b: v at the fault 3.92 m/s; TOR on True, mrm (3, 3) (3 = COMFORTABLE_STOP), v 0.000
w31-r03 (3.24) VERDICT: PASS encore: v at the fault 3.92 m/s; mrm (3, 2) (2 = EMERGENCY_STOP), v 0.000, after restore mrm (1, 1)
w31-r04 (2.27) VERDICT: PASS a: v at the fault 3.88 m/s; TOR on True, TOR now 1, control mode 4, mrm (1, 1)
w31-r05 (2.54) VERDICT: PASS b: v at the fault 3.89 m/s; TOR on True, mrm (3, 3) (3 = COMFORTABLE_STOP), v 0.000
w31-r06 (5.07) VERDICT: PASS encore: v at the fault 3.90 m/s; mrm (3, 2) (2 = EMERGENCY_STOP), v 0.000, after restore mrm (1, 1)
w31-r07 (4.45) VERDICT: PASS a: v at the fault 3.84 m/s; TOR on True, TOR now 1, control mode 4, mrm (1, 1)
w31-r08 (7.93) VERDICT: PASS b: v at the fault 3.87 m/s; TOR on True, mrm (3, 3) (3 = COMFORTABLE_STOP), v 0.000
w31-r09 (5.82) VERDICT: PASS encore: v at the fault 3.88 m/s; mrm (3, 2) (2 = EMERGENCY_STOP), v 0.000, after restore mrm (1, 1)
```

All 9 runs PASS, and `trace-check: PASS` on all 9 traces. Each run's
`explain.txt` came from this contract: its budget table is identical to
`tools/timeline/testdata/explain.txt` (routes 206.00, WINDOWS 10206.00).
Every trace names image `664592d4`. Every Autoware start read `nodes
31/31, containers 13/13, composable 68/68`. The window's history ran 39-48
records over 1464-1496 ms. After the trigger the board wrote 464-605 B/s.
The SWD readout held the core halted 0.181-0.195 s.

One act-A attempt before the r07 that counts never faulted. Its Autoware
container came up with "0/2 composables loaded" in
`velocity_smoother_container` (`composable_loaded` 66 of 68, `"ok":false`).
run-board.sh still saw "Startup complete", and the vehicle never engaged
("FATAL: the vehicle did not reach 1.0 m/s"). No fault was injected, so
the trace never triggered. It is kept as `w31-r07-aw6668`, and act A was
run again as r07.

### The rows, fresh

Every row of every run PASS. The last column is the bound minus the
largest observation.

**Branch A.**

| term | declared | r01 | r04 | r07 | max observed | declared - max |
|---|---|---|---|---|---|---|
| detect (button -> verdict on the wire) | 100.00 | 76.23 | 62.78 | 45.96 | 76.23 | 23.77 |
| takeover route (verdict -> request on) | 206.00 | 66.77 | 69.76 | 72.52 | 72.52 | 133.48 |
| driver answered inside the window | 10000.00 | 3030.11 | 3041.02 | 3055.56 | 3055.56 | 6944.44 |
| exit route (MANUAL taken -> request off) | 149.00 | 16.17 | 104.53 | 20.50 | 104.53 | 44.47 |
| no MRM | none | none | none | none | - | - |
| HPC alive: longest availability gap (host) | 500.00 | 113.07 | 107.83 | 105.84 | 113.07 | 386.93 |

**Branch B.**

| term | declared | r02 | r05 | r08 | max observed | declared - max |
|---|---|---|---|---|---|---|
| detect (button -> verdict on the wire) | 100.00 | 6.79 | 86.70 | 89.96 | 89.96 | 10.04 |
| takeover route (verdict -> request on) | 206.00 | 83.06 | 51.78 | 112.75 | 112.75 | 93.25 |
| window dwell, island clock (request on -> off) | [10000.00, 10206.00] | 10112.04 | 10013.48 | 10111.86 | 10112.04 | 93.96 |
| window dwell, host (request on -> off as received) | [10000.00, 10206.00] | 10127.99 | 10010.58 | 10103.55 | 10127.99 | 78.01 |
| windows (verdict -> deadline = request on + window) | 10206.00 | 10083.06 | 10051.78 | 10112.75 | 10112.75 | 93.25 |
| route, island clock (deadline -> velocity limit) | 206.00 | 113.06 | 14.56 | 112.45 | 113.06 | 92.94 |
| route, host (deadline -> velocity limit received) | 206.00 | 128.22 | 10.95 | 103.86 | 128.22 | 77.78 |
| windows + route (verdict -> velocity limit) | 10412.00 | 10196.12 | 10066.34 | 10225.20 | 10225.20 | 186.80 |
| windows + route, host (verdict -> velocity limit received) | 10412.00 | 10228.93 | 10070.53 | 10225.20 | 10228.93 | 183.07 |
| settle (velocity limit -> standstill) | 9996.67 | 5422.42 | 5020.11 | 6085.30 | 6085.30 | 3911.37 |
| total (button -> standstill) | 20508.67 | 15625.33 | 15173.15 | 16400.46 | 16400.46 | 4108.21 |
| within the FTTI | 30000.00 | 15625.33 | 15173.15 | 16400.46 | 16400.46 | 13599.54 |
| rung reached | COMFORTABLE_STOP | COMFORTABLE_STOP | COMFORTABLE_STOP | COMFORTABLE_STOP | - | - |
| HPC alive: longest availability gap (host) | 500.00 | 107.38 | 104.45 | 108.43 | 108.43 | 391.57 |
| entry speed (m/s) | 8.33 | 3.05 | 3.05 | 3.06 | 3.06 | 5.27 |

**Encore.**

| term | declared | r03 | r06 | r09 | max observed | declared - max |
|---|---|---|---|---|---|---|
| detect (last sample -> reaction tick) | 618.00 | 553.91 | 556.82 | 579.60 | 579.60 | 38.40 |
| route (reaction tick -> braking command) | 239.33 | 17.22 | 7.04 | 8.36 | 17.22 | 222.11 |
| detect + route (last sample -> braking command) | 739.33 | 571.13 | 563.86 | 587.95 | 587.95 | 151.38 |
| settle (braking command -> standstill) | 4165.33 | 2915.21 | 2897.72 | 2917.58 | 2917.58 | 1247.75 |
| total (last sample -> standstill) | 4904.67 | 3486.34 | 3461.58 | 3505.54 | 3505.54 | 1399.13 |
| within the FTTI | 10000.00 | 3486.34 | 3461.58 | 3505.54 | 3505.54 | 6494.46 |
| rung reached | EMERGENCY_STOP | EMERGENCY_STOP | EMERGENCY_STOP | EMERGENCY_STOP | - | - |
| entry speed (m/s) | 8.33 | 4.22 | 4.23 | 4.24 | 4.24 | 4.09 |

Several fresh values go past what the 13 W8 runs showed, and all of them
stay inside the new bounds:

- r04's exit route, 104.53, is past W8's largest (72.87) and would have
  failed the old 100 ms bound. Its island trace: the TOR-off publish came
  7.97 ms into the tick after the take of MANUAL, so the take waited 96.56
  ms for that tick. That is one full tick of waiting, which is the case
  `driver_exit`'s 149 = 118 + 31 is sized for.
- r08's takeover route, 112.75, is past the old 110 ms bound. In the
  trace it is 27.39 of link, 79.99 of waiting for the tick, and 5.37 into
  the tick.
- r09's encore detect, 579.60, is past W8's largest (575.78), and inside
  618.
- In r05 the expiry tick came 10,000.13 ms after the on-tick (island
  clock), not about 10,100 as in r02 (10,100.01), r08 (10,095.73) and all
  of W8's B runs. So the dwell was 10,013.48 (= 10,000.13 + 21.40 of work
  in the expiry tick - 8.05 in the on-tick), and the route 14.56. The
  handler's 100 ms timer hit the deadline tick on or just after it, not
  just before, so no extra tick was needed. That is tick phase, inside
  the rung.

### The terms, fresh

These are section 10's `terms.py` on the 9 runs (island clock except
`link`):

```
max: link 67.02, wait 79.99, spacing 108.34, work 21.69, tor_on 8.05, call 13.79, tor_off 21.49, operate 0.88, exit 104.53
```

| term | declared from W8 (section 10) | fresh, 9 runs | inside? |
|---|---|---|---|
| link (gate publish -> island take) | 57 (max 47.43) | 8.93-67.02 (12 edges; r01 60.64 and 67.02) | **no, +10.02** |
| tick spacing | 118 | 90.62-108.34 (1104 gaps) | yes |
| work (tick -> last publish) | 31 | 0.40-21.69 | yes |
| `call_mrm` = link + tick + work | 206 | takeover route at most 112.75 | yes |
| `driver_exit` = tick + work | 149 | 16.17-104.53 | yes |
| control_mode transport (host MANUAL -> island take) | 143 | 25.79-57.68 (3 edges) | yes |

The one term past its figure is the link. In r01 both of its edges took
longer than the 57 ms `max_transport` stated on the handler's
availability subscriber: the fault edge 60.64 ms, the restore edge
67.02. It is a cross-clock measure: over-stated, never under-stated, by
the smallest out-link delay (section 10). r01's second anchor disagreed
with the first by 59.95 ms, and its publish/receipt pair spread was
0.08 ms. As in section 10, that disagreement tracks the in-link hop
itself (60.64). No row failed: the island took the fault edge 0.07 ms
before its tick, so `call_mrm` held 66.77 of 206. Two things follow.
First, `max_transport: 57ms` is not an upper bound on this link. Once
more runs size it again, it wants about 81 at +20 % over 67.02. Second,
`call_mrm`'s 206 stays sound, because it is the sum of three worst cases
and no run has put them together: the largest link, wait and work in
these 9 runs sum to 67.02 + 79.99 + 21.69 = 168.70. play_launch 0.13.0
reads neither number in the fault arithmetic (section 10, F1), so the
contract's verdicts do not move.

### Runtime contract violations

The image carries the 206 ms `max-latency-runtime` monitors, and nothing
the board can show says one fired. There is also no channel on which it
could have been seen, so the offline measure below is the evidence:

- **Console.** The monitor reports with `log_warn` ("contract violation:
  <rule> <fqn> measured=... declared=...", nros-node
  `executor/monitor.rs` `log_violation`). The board's console is lpuart0,
  which is not wired. lpuart2 carries the zenoh link.
- **The ring.** Nothing drains the executor's violation ring. It keeps the
  first 8 violations since boot and drops the rest. Read over SWD at
  bring-up (`w31-bringup/vscan.txt`), it was already full: 8 of 8 slots,
  all from start-up. That is 4 `timer-overrun-runtime timer`, 1
  `release-jitter-runtime spin measured=57751 declared=10000`, 1
  `silence-runtime /mrm_handler/operation_mode_availability declared=500`,
  and 2 `rate-hierarchy-runtime` on the comfortable-stop operator's
  clear_velocity_limit and max_velocity_candidates (on-demand topics with
  a 10 Hz `min_rate_hz`). So a latency violation during an act would not
  be stored.
- **The trace.** No marker records a violation. What the monitor measures
  is one dispatch's elapsed time, charged to each monitored publisher
  whose count advanced in it (`attribute_latency` in `executor/spin.rs`),
  and the trace brackets every handler callback with ENTRY/EXIT. The
  longest handler callback that published `mrm_state` or the TOR state
  was 6.86-24.93 ms per run (r03's EMERGENCY_STOP tick, 24.93). The
  longest handler callback of any kind was 24.93 ms. So none came within
  181 ms of the 206 ms rows, and none would have tripped W8's 110 either.
  The monitor bounds the handler's work in one callback. It does not
  bound the route, which is waiting for the tick plus crossing the link.

Runs, tables and plots are in `build/timeline/w31-{bringup,r01..r09,r07-aw6668}/`
in the W31 worktree (`timeline.png`, `table.md`, `explain.txt`,
`island.trace*`, the JSONL files). The per-run logs, `terms.txt`, and the
tools (`vscan.py` for the ring, `mon.py` for the callback times, `agg.py`
for the tables above) are in `/mnt/mx500/aeon/worktrees/w31-logs/`.

## 12. Runtime violations, seen (phase9-W4)

phase9-W4, 2026-10-06. Section 11 ended with "nothing the board can show
says one fired". This section is the board showing it. The image: branch
`phase9-w4` at `abb83d6` (code as of `928898c`), nano-ros pinned at
`5b3ac4567`, the head of PR #1729 (phase-474 I1/I2; in the merge queue,
not merged at the time of these runs), `just board-build`, ELF sha256
`9491f076755518ec1d9e00f82ee6034c1b03ec3a79fb18d699b438c32ff4c7bb`, RAM
299,200 of 327,680 B (91.31 %). The rig is section 9's: run-board.sh,
`sai-l3-autoware:1.5.0-w24`, the C++ gate from `just demo-host-ws`, the
demo lock, 1-min load 3-9.

### The channel

- **Arming.** `CONFIG_NROS_MONITOR_ARM_ON_CALL=y`; the handler calls
  `nros::arm_monitors()` on the first tick that finds every required input
  established: INIT_DONE, or the clearing of an init failure. Not at
  INIT_TIMEOUT: in run-board.sh the island is reset at step 3 and Autoware
  starts at step 5, so `init_timeout` (3.0 s) always passes first, and in
  all three runs below the arming came through the recovery ("init failure
  cleared"), 6.3-7.0 s after boot. Two words record it over SWD
  (`island_monitors_armed_uptime_ms`, `island_monitors_armed_via`). No
  grace deadline. Before the call a verdict is counted in
  `suppressed_before_arm` and not stored.
- **The SWD record.** `NROS_VIOLATION_RECORD`, read by symbol by
  `tools/timeline/violations.py` and inside readout.py's halted read; every
  run directory has `violations.txt`. 8 slots
  (`CONFIG_NROS_EXECUTOR_MAX_VIOLATIONS`, the latest kept).
- **The trace.** nano-ros's violation events 21-24, forwarded by the
  island's sink at ids 277-280 (docs/tracing.md section 9); a stored
  violation opens the trace window.
- **The log.** `CONFIG_NROS_VIOLATION_DRAIN_REPORT` is off on the board:
  the log goes to lpuart0, which is not wired (on in native_sim).

### First, a halt: the reporter overflowed the main stack

The first bring-up (`w4-bringup`, image `a014674d...`, main stack 16 KiB)
stopped 60 ms after its first stored violation: the heartbeat froze at
uptime 8,700 ms, the core sat in `arch_system_halt` with reason 35
(`K_ERR_ARM_USAGE_ILLEGAL_EPSR`), PSP inside `z_idle_stacks`, and that
stack and the bottom 128 B of `z_main_stack` above it were all zeros.
From this pin a stored violation runs nano-ros's `/diagnostics` reporter
(issue 1635) on the spin thread, which is main: one `DiagnosticArray`
serialised into a zeroed 512 B stack buffer and published, per violation.
That ran main below its 16 KiB into the idle thread's stack (no MPU guard on
this image), and the idle thread resumed at PC 0. Bisected on the bench
(the island alone, the monitors armed by a 6 s grace so that the
availability's silence fires without Autoware): the halt stays with
`CONFIG_NROS_TRACE_CALLBACKS=n`, with `CONFIG_NROS_BOOT_REPORT=n` and with
`CONFIG_NROS_LOG_MAX_LEVEL=4` (the violation log compiled out), and goes
with `CONFIG_MAIN_STACK_SIZE=24576`, where 7 violations were stored and the
stack paint read over SWD put main's high-water at 18,780 B. The board conf
now states 24576 (commit `928898c`). The bring-up's trace had already
shown the channel: the window opened at the violation and decoded as
`#1: silence-runtime /mrm_handler/operation_mode_availability measured=0
declared=500`.

### (a) Bring-up: before and after arming

Run `w4-bringup2` (encore, with the act replaced by readouts). Readout 1,
taken right after the island joined (step 4), before Autoware:

```
violation record (NROS_VIOLATION_RECORD, layout v1, capacity 8):
  total=0 dropped=0 suppressed_before_arm=5 armed=0
  handler armed the monitors: not armed
  read at uptime ~3500 ms (last trace heartbeat)
  EMPTY: no violation stored since boot
```

Readout 2, 45 s after Autoware's start and the gate, nothing commanded:

```
violation record (NROS_VIOLATION_RECORD, layout v1, capacity 8):
  total=10 dropped=2 suppressed_before_arm=8 armed=1
  handler armed the monitors: init failure cleared at uptime 6974 ms
  read at uptime ~52000 ms (last trace heartbeat)
  #10: rate-hierarchy-runtime /mrm_emergency_stop_operator/status measured=29990 declared=30000
  #9: rate-hierarchy-runtime /mrm_emergency_stop_operator/emergency_control_cmd measured=29990 declared=30000
  #8: release-jitter-runtime spin measured=88585 declared=10000
  #7: timer-overrun-runtime timer measured=1 declared=0
  #6: rate-hierarchy-runtime /mrm_handler/takeover_request_state measured=9984 declared=10000
  #5: rate-hierarchy-runtime /mrm_handler/mrm_state measured=9984 declared=10000
  #4: rate-hierarchy-runtime /mrm_handler/hazard_lights_cmd measured=9984 declared=10000
  #3: rate-hierarchy-runtime /mrm_comfortable_stop_operator/status measured=9984 declared=10000
```

The ring is not empty after RUN. The trace holds all ten, with their island
times (`island_trace.py violations`; the window opened at #1):

```
trace violations: 17 (trace window opened by NROS_VIOLATION)
      7540.518 ms  #1: silence-runtime /mrm_handler/operation_mode_availability measured=0 declared=500
      7560.090 ms  #2: release-jitter-runtime spin measured=11575 declared=10000
     12039.635 ms  #3: rate-hierarchy-runtime /mrm_comfortable_stop_operator/status measured=9984 declared=10000
     12059.845 ms  #4: rate-hierarchy-runtime /mrm_handler/hazard_lights_cmd measured=9984 declared=10000
     12076.084 ms  #5: rate-hierarchy-runtime /mrm_handler/mrm_state measured=9984 declared=10000
     12093.460 ms  #6: rate-hierarchy-runtime /mrm_handler/takeover_request_state measured=9984 declared=10000
     12120.619 ms  #7: timer-overrun-runtime timer measured=1 declared=0
     12136.056 ms  #8: release-jitter-runtime spin measured=88585 declared=10000
     17044.172 ms  #9: rate-hierarchy-runtime /mrm_emergency_stop_operator/emergency_control_cmd measured=29990 declared=30000
     17063.548 ms  #10: rate-hierarchy-runtime /mrm_emergency_stop_operator/status measured=29990 declared=30000
```

What each one is:

- `armed` 0 -> 1, and the 8 pre-arm verdicts (5 by 3.5 s after boot) are
  counted, not stored: the start-up noise of W31's ring is gone from it.
  The two `rate-hierarchy-runtime` verdicts of W31 on the comfortable-stop
  operator's `clear_velocity_limit` and `max_velocity_candidates` are gone
  too (W7 dropped their rate claims).
- **#1, silence on the availability, is structural.** nano-ros counts a take
  for the age and silence rules only when it can read the message stamp
  against an epoch clock (nros-node `arena.rs` `observe_age`: "None =
  uncontracted (or no epoch source / no stamp in the type)"). The board has
  no epoch (no SNTP over serial, phase9-W3), so the takes never count: the
  trace shows `TAKE_MRM_HANDLER_OPERATION_MODE_AVAILABILITY` every 100 ms
  in the 566 ms between arming and the verdict. It is reported once and
  never recovers. It is W31's start-up `silence-runtime` entry too.
- **#3-#6 and #9-#10, `rate-hierarchy-runtime` at 9984 of 10000 mHz and 29990
  of 30000 mHz**, are the first rate window after arming (5.0 s and 10.1 s
  after it) reading the 10 Hz and 30 Hz publishers 0.03-0.16 % short. The
  rule has no tolerance. They do not recur in the 35 s after.
- **#2, #7 and #8, release jitter and a timer overrun, are the reporter's
  own cost.** The verdicts are 15-20 ms apart in the trace: each one's
  `/diagnostics` publish holds the spin that long over the 921,600-baud
  link. #3-#7 took 81 ms, and #8 is the spin's jitter of 88.6 ms measured
  right after them; #2 (11.6 ms) follows #1 the same way.

### (b) A commanded overrun

Then, same boot: `violations.py overrun 250` wrote 250 into
`island_debug_overrun_ms` (CONFIG_ISLAND_DEBUG_OVERRUN; inert while 0), and
the handler's next RUN tick busy-waited 250 ms after its publishes. Readout
3, 5 s later:

```
violation record (NROS_VIOLATION_RECORD, layout v1, capacity 8):
  total=17 dropped=9 suppressed_before_arm=8 armed=1
  handler armed the monitors: init failure cleared at uptime 6974 ms
  read at uptime ~57900 ms (last trace heartbeat)
  #17: rate-hierarchy-runtime /mrm_emergency_stop_operator/status measured=28788 declared=30000
  #16: rate-hierarchy-runtime /mrm_emergency_stop_operator/emergency_control_cmd measured=28788 declared=30000
  #15: timer-overrun-runtime timer measured=1 declared=0
  #14: release-jitter-runtime spin measured=246918 declared=10000
  #13: timer-overrun-runtime timer measured=1 declared=0
  #12: timer-overrun-runtime timer measured=1 declared=0
  #11: timer-overrun-runtime timer measured=7 declared=0
  #10: rate-hierarchy-runtime /mrm_emergency_stop_operator/status measured=29990 declared=30000
```

and in the trace, the tick and the verdicts on one clock:

```
   52574.604 ms  PATH_MRM_COMFORTABLE_STOP_OPERATOR_ON_TIMER_ENTRY        arg=1
   52574.860 ms  PATH_MRM_COMFORTABLE_STOP_OPERATOR_ON_TIMER_EXIT         arg=1
   52574.870 ms  PATH_MRM_HANDLER_ON_TIMER_ENTRY                          arg=1
   52599.569 ms  heartbeat seq=525 uptime=52600 ms
   52699.569 ms  heartbeat seq=526 uptime=52700 ms
   52799.569 ms  heartbeat seq=527 uptime=52800 ms
   52825.518 ms  PATH_MRM_HANDLER_ON_TIMER_EXIT                           arg=1
   52826.376 ms  TAKE_MRM_HANDLER_OPERATION_MODE_AVAILABILITY             arg=0
   52826.396 ms  TAKE_MRM_HANDLER_OPERATION_MODE_AVAILABILITY             arg=0
   52826.414 ms  TAKE_MRM_HANDLER_OPERATION_MODE_AVAILABILITY             arg=0
   52841.227 ms  NROS_VIOLATION                                           arg=2824  #11: timer-overrun-runtime timer measured=7 declared=0
   52855.290 ms  NROS_VIOLATION                                           arg=3080  #12: timer-overrun-runtime timer measured=1 declared=0
   52876.017 ms  NROS_VIOLATION                                           arg=3336  #13: timer-overrun-runtime timer measured=1 declared=0
   52891.053 ms  NROS_VIOLATION                                           arg=3593  #14: release-jitter-runtime spin measured=246918 declared=10000
   52899.571 ms  heartbeat seq=528 uptime=52900 ms
   52906.689 ms  NROS_VIOLATION                                           arg=3848  #15: timer-overrun-runtime timer measured=1 declared=0
```

The handler's tick ran 250.65 ms (ENTRY 52574.870 -> EXIT 52825.518), and
the channel carried what the monitors said about it: the spin's release
jitter 246,918 us against 10,000, the timers' overruns (7 activations
dropped, then 1, 1, 1), and 5 s later the emergency operator's rate at
28,788 of 30,000 mHz. It did NOT carry `max-latency-runtime`: the tick
published `mrm_state`, `takeover_request_state` and `hazard_lights_cmd`,
all three monitored at 206, 206 and 100 ms, and no latency verdict was
stored. The rule did not see the timer's dispatch. The likely cause, read
in the pin and not yet confirmed by a test: nano-ros attributes a
dispatch's elapsed time to the publishers it advanced only in the measured
EDF and FIFO drains (`spin.rs` `attribute_latency`, two call sites), while
a spin whose trigger does not pass, as when only timers are due, fires the
timers in a sweep that measures nothing (`spin.rs`, "Timers still need
delta accumulation even when trigger doesn't pass"). Whatever the cause,
the latency rows the contract bakes (206 ms on the TOR and MRM state, 100
on the hazard lights) are not judged on this image, and section 11's "none
came within 181 ms" was never a monitor's verdict either.

### (c) A real act: the encore

Run `w4-encore`, a normal `run-board.sh encore`: VERDICT PASS, every row
of the table PASS (detect 575.10 of 618 ms, route 10.26 of 239.33, total
3469.15 of 4904.67, EMERGENCY_STOP reached). The readout at its end:

```
violation record (NROS_VIOLATION_RECORD, layout v1, capacity 8):
  total=8 dropped=0 suppressed_before_arm=8 armed=1
  handler armed the monitors: init failure cleared at uptime 6274 ms
  read at uptime ~43500 ms (last trace heartbeat)
  #8: release-jitter-runtime spin measured=86278 declared=10000
  #7: timer-overrun-runtime timer measured=1 declared=0
  #6: rate-hierarchy-runtime /mrm_handler/takeover_request_state measured=9990 declared=10000
  #5: rate-hierarchy-runtime /mrm_handler/mrm_state measured=9990 declared=10000
  #4: rate-hierarchy-runtime /mrm_handler/hazard_lights_cmd measured=9990 declared=10000
  #3: rate-hierarchy-runtime /mrm_comfortable_stop_operator/status measured=9990 declared=10000
  #2: release-jitter-runtime spin measured=15428 declared=10000
  #1: silence-runtime /mrm_handler/operation_mode_availability measured=0 declared=500
```

```
trace violations: 8 (trace window opened by NROS_VIOLATION)
      6834.570 ms  #1: silence-runtime /mrm_handler/operation_mode_availability measured=0 declared=500
      6857.941 ms  #2: release-jitter-runtime spin measured=15428 declared=10000
     11333.170 ms  #3: rate-hierarchy-runtime /mrm_comfortable_stop_operator/status measured=9990 declared=10000
     11353.536 ms  #4: rate-hierarchy-runtime /mrm_handler/hazard_lights_cmd measured=9990 declared=10000
     11369.775 ms  #5: rate-hierarchy-runtime /mrm_handler/mrm_state measured=9990 declared=10000
     11387.151 ms  #6: rate-hierarchy-runtime /mrm_handler/takeover_request_state measured=9990 declared=10000
     11411.849 ms  #7: timer-overrun-runtime timer measured=1 declared=0
     11427.324 ms  #8: release-jitter-runtime spin measured=86278 declared=10000
```

The HPC loss was at island uptime ~38.3 s and the restore at ~42.9 s (the
merge's offset): all 8 verdicts are 27-32 s before the act, the same
post-arming set as in (a), and none was stored during it (the
availability's silence had been reported at arming, so the real silence
of the HPC loss added nothing). The trace window opened at #1, 6.8 s after
boot, and still held the whole act (17,062 of 32,768 B); `trace-check`
PASS, merge and table as before.

### What is open, and whose

- **max-latency-runtime is blind to timer callbacks fired in the trigger
  sweep** (nano-ros; phase-474 D3 is the route-level question, this is the
  callback-level rule not running at all). Until then (b) cannot show the
  rule the contract's 206 ms rows name.
- **The /diagnostics reporter runs on the spin thread**: 15-20 ms per
  verdict over serial, its own release-jitter and timer-overrun verdicts,
  and a 512 B stack buffer that overflowed a 16 KiB main stack (nano-ros,
  issue 1635's reporter; the island states 24 KiB).
- **The rate rule's first window after arming** reads a 10 Hz timer at
  9984-9990 mHz (nano-ros: a tolerance, or no verdict on a window the
  arming cut).
- **Silence and age on the board need an epoch** (phase9-W3): until then
  the availability's silence verdict at arming is certain on every board
  run, and its age is never judged.
- **The boot record's heap headroom** reads REFUSED on this pin (peak
  79,712 of 102,912 B, 23,200 spare against a 24,576 floor; W31 had 77,160):
  the `/diagnostics` publisher is new; not resized here.

Runs: `build/timeline/w4-{bringup,bringup2,encore}/` in the W4 worktree
(`/mnt/mx500/aeon/worktrees/w4-island`), their text outputs and the bench
variants under `/mnt/mx500/aeon/worktrees/w4-logs/runs/`.

### The gate, at the merged nano-ros (2026-10-10)

The readouts above are the first W4 runs (nano-ros `5b3ac4567`). The
rerun (branch `phase9-w4-rerun`) pins nano-ros `319715968`, nano-ros main
with PR #1764 (phase-474 I7 reporter off the judged tick, I5 heap record,
I3 take/timer trace hooks, I4 workspace-root caps; merge `2b8153621`) and
PR #1825 (I9: the rate rule judges the window's count against
floor(min_rate * window) instead of flooring the quotient). On the island
side it carries `CONFIG_LOG_DEFAULT_LEVEL=1` on the board (`cbf2ad5`): the
15-20 ms per verdict was the detection log shifted out on the unwired
lpuart0 at 115200 baud on the spin thread, not the reporter. Main stack
16384 (the reporter no longer runs on it), heap 106496, trace buffer
40960, takes forwarded at 281-283 (docs/tracing.md section 9). Image
`39dd6433...` (sha256 of build-board/zephyr/zephyr.elf), RAM 305,056 of
327,680 B, built pristine under `env -i` with scripts/env.sh. Same rig.

**(a) and (b), run `w4-gate-ab`** (encore with the act replaced by
readouts). Before Autoware:

```
violation record (NROS_VIOLATION_RECORD, layout v1, capacity 8):
  total=0 dropped=0 suppressed_before_arm=3 armed=0
  handler armed the monitors: not armed
  read at uptime ~1900 ms (last trace heartbeat)
  EMPTY: no violation stored since boot
```

40 s after the gate, nothing commanded:

```
violation record (NROS_VIOLATION_RECORD, layout v1, capacity 8):
  total=1 dropped=0 suppressed_before_arm=4 armed=1
  handler armed the monitors: init failure cleared at uptime 6074 ms
  read at uptime ~61100 ms (last trace heartbeat)
  #1: silence-runtime /mrm_handler/operation_mode_availability measured=0 declared=500
```

Then `violations.py overrun 250`, and 5 s later:

```
violation record (NROS_VIOLATION_RECORD, layout v1, capacity 8):
  total=14 dropped=6 suppressed_before_arm=4 armed=1
  handler armed the monitors: init failure cleared at uptime 6074 ms
  read at uptime ~66900 ms (last trace heartbeat)
  #14: rate-hierarchy-runtime /mrm_handler/takeover_request_state measured=9787 declared=10000
  #13: rate-hierarchy-runtime /mrm_handler/mrm_state measured=9787 declared=10000
  #12: rate-hierarchy-runtime /mrm_handler/hazard_lights_cmd measured=9787 declared=10000
  #11: rate-hierarchy-runtime /mrm_comfortable_stop_operator/status measured=9787 declared=10000
  #10: rate-hierarchy-runtime /mrm_emergency_stop_operator/status measured=28921 declared=30000
  #9: rate-hierarchy-runtime /mrm_emergency_stop_operator/emergency_control_cmd measured=28921 declared=30000
  #8: release-jitter-runtime spin measured=242922 declared=10000
  #7: timer-overrun-runtime timer measured=1 declared=0
```

```
trace violations: 14 (trace window opened by NROS_VIOLATION)
      6599.790 ms  #1: silence-runtime /mrm_handler/operation_mode_availability measured=0 declared=500
     61825.694 ms  #2: max-latency-runtime /mrm_handler/hazard_lights_cmd measured=250 declared=100
     61825.782 ms  #3: max-latency-runtime /mrm_handler/mrm_state measured=250 declared=206
     61825.871 ms  #4: max-latency-runtime /mrm_handler/takeover_request_state measured=250 declared=206
     61827.614 ms  #5: timer-overrun-runtime timer measured=7 declared=0
     61827.700 ms  #6: timer-overrun-runtime timer measured=1 declared=0
     61827.785 ms  #7: timer-overrun-runtime timer measured=1 declared=0
     61827.872 ms  #8: release-jitter-runtime spin measured=242922 declared=10000
     66163.167 ms  #9: rate-hierarchy-runtime /mrm_emergency_stop_operator/emergency_control_cmd measured=28921 declared=30000
     66163.475 ms  #10: rate-hierarchy-runtime /mrm_emergency_stop_operator/status measured=28921 declared=30000
     66232.772 ms  #11: rate-hierarchy-runtime /mrm_comfortable_stop_operator/status measured=9787 declared=10000
     66232.868 ms  #12: rate-hierarchy-runtime /mrm_handler/hazard_lights_cmd measured=9787 declared=10000
     66232.958 ms  #13: rate-hierarchy-runtime /mrm_handler/mrm_state measured=9787 declared=10000
     66233.052 ms  #14: rate-hierarchy-runtime /mrm_handler/takeover_request_state measured=9787 declared=10000
```

The tick and the verdicts on one clock (the trace keeps 1 timer tick in 10,
spin_keep 10, and did not keep the overrunning tick; the spin's last event
before the stall is a take at 61548.834 ms):

```
   61548.834 ms  TAKE_MRM_HANDLER_OPERATION_MODE_AVAILABILITY             arg=0
   61825.694 ms  NROS_VIOLATION                                           arg=515  #2: max-latency-runtime /mrm_handler/hazard_lights_cmd measured=250 declared=100
   61825.782 ms  NROS_VIOLATION                                           arg=771  #3: max-latency-runtime /mrm_handler/mrm_state measured=250 declared=206
   61825.871 ms  NROS_VIOLATION                                           arg=1027  #4: max-latency-runtime /mrm_handler/takeover_request_state measured=250 declared=206
   61826.447 ms  PATH_MRM_COMFORTABLE_STOP_OPERATOR_ON_TIMER_ENTRY        arg=1
   61826.695 ms  PATH_MRM_COMFORTABLE_STOP_OPERATOR_ON_TIMER_EXIT         arg=1
   61826.729 ms  TAKE_MRM_HANDLER_OPERATION_MODE_AVAILABILITY             arg=0
   61826.751 ms  TAKE_MRM_HANDLER_OPERATION_MODE_AVAILABILITY             arg=0
   61826.869 ms  PATH_MRM_HANDLER_ON_TIMER_ENTRY                          arg=1
   61827.525 ms  PATH_MRM_HANDLER_ON_TIMER_EXIT                           arg=1
   61827.614 ms  NROS_VIOLATION                                           arg=1288  #5: timer-overrun-runtime timer measured=7 declared=0
   61827.700 ms  NROS_VIOLATION                                           arg=1544  #6: timer-overrun-runtime timer measured=1 declared=0
   61827.785 ms  NROS_VIOLATION                                           arg=1800  #7: timer-overrun-runtime timer measured=1 declared=0
   61827.872 ms  NROS_VIOLATION                                           arg=2057  #8: release-jitter-runtime spin measured=242922 declared=10000
```

- After arming, nothing but the availability's silence (W3: no epoch on
  the board, so its takes never count). No 9999/10000 rate verdict (I9),
  no 29773/30000 on the emergency operator (no log stall to drop its
  ticks), no timer overrun and no release jitter: (a) PASS.
- The overrun: three `max-latency-runtime` verdicts, one per monitored
  publisher of the tick (hazard lights 100, MRM state 206, TOR state 206),
  measured 250, stored 0.18 ms apart (I6 judges the sweep-fired timer).
  Everything after is the overrun's own: 0.26 ms of the three timers' Skip
  counts (the 30 Hz emergency operator 7 periods, the two 10 Hz timers 1
  each) and the spin's 242.9 ms release jitter, then 5 s later the rate
  windows that held the stall, short by exactly those activations (30 Hz
  at 28,921 mHz, 10 Hz at 9,787). Nothing is 15 ms apart and no verdict
  breeds another: (b) PASS.

**(c), run `w4-gate-encore`**, a normal `run-board.sh encore`: VERDICT
PASS.

| term | declared ms | observed ms | verdict | note |
|---|---|---|---|---|
| detect (last sample -> reaction tick) | 618.00 | 602.00 | PASS | 500 + the tick the route's call_mrm already holds |
| route (reaction tick -> braking command) | 239.33 | 8.41 | PASS |  |
| detect + route (last sample -> braking command) | 739.33 | 610.41 | PASS |  |
| settle (braking command -> standstill) | 4165.33 | 2865.15 | PASS |  |
| total (last sample -> standstill) | 4904.67 | 3475.57 | PASS |  |
| within the FTTI | 10000.00 | 3475.57 | PASS |  |
| rung reached | EMERGENCY_STOP | EMERGENCY_STOP | PASS |  |
| entry speed (m/s) | 8.33 | 4.25 | PASS |  |

```
violation record (NROS_VIOLATION_RECORD, layout v1, capacity 8):
  total=5 dropped=0 suppressed_before_arm=4 armed=1
  handler armed the monitors: init failure cleared at uptime 5965 ms
  read at uptime ~43500 ms (last trace heartbeat)
  #5: release-jitter-runtime spin measured=17888 declared=10000
  #4: release-jitter-runtime spin measured=14905 declared=10000
  #3: release-jitter-runtime spin measured=13794 declared=10000
  #2: release-jitter-runtime spin measured=13625 declared=10000
  #1: silence-runtime /mrm_handler/operation_mode_availability measured=0 declared=500

trace violations: 5 (trace window opened by NROS_VIOLATION)
      6494.773 ms  #1: silence-runtime /mrm_handler/operation_mode_availability measured=0 declared=500
     21121.524 ms  #2: release-jitter-runtime spin measured=13625 declared=10000
     22121.692 ms  #3: release-jitter-runtime spin measured=13794 declared=10000
     32318.925 ms  #4: release-jitter-runtime spin measured=14905 declared=10000
     33230.385 ms  #5: release-jitter-runtime spin measured=17888 declared=10000
```

The HPC loss is at island ~38.5 s (the merge's anchors: the last
availability sample before the gate stopped at 38,470 ms, MRM_OPERATING
at 39,079 ms): no verdict was stored during the act, the last 5.2 s
before it. The boot record, read over SWD after the run:
`HEAP HEADROOM: ok -- 35088 bytes spare (peak 71920 of 107008, floor
24576).` The main stack's paint: high-water 11,640 B of 16,384 (4,744 B
spare), the same after (b). Takes in the trace: 431 (kinematic_state 224,
control_cmd 196, operation_mode_state 11, all stamped). Trace buffer:
28,135 of 40,960 B, the window 26,038 B over 37.07 s after the trigger.

One thing (a) did not show: #2-#5, four single `release-jitter-runtime`
verdicts of 13.6-17.9 ms against the contract's 10 ms, 0.9-10 s apart,
while the scenario set the pose and goal and engaged (21-33 s). Each sits
on a `kinematic_state` take or an emergency-operator tick and none is
followed by another verdict, so neither the log floor nor the reporter.
In (a) nothing published `kinematic_state` (no pose was set). The cause is
not established here; like the rate rule's margin, the 10 ms bound is a
contract question. The gate as written (none during the act) passes.

Runs: `build/timeline/w4-gate-{ab,encore}/` in the W4 worktree.
