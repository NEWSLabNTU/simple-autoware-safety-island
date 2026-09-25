# The reaction trace

phase7-W3, 2026-09-25. The island's fault reaction, traced on `native_sim`
and set against the terms the contract declares for the hazard
`operation_mode_unavailable`.

**The rung is native_sim. Every duration here is SIMULATED time.**
native_sim runs code in zero simulated time. So an interval inside one
callback is an artefact: it reads 0, or a few microseconds of timer-read
granularity. It is never an execution time. What the trace does measure is
the WAITS between callbacks: the 500 ms staleness window, the phase of the
handler's 100 ms tick, the executor turn that carries the service request,
and the phase of the operator's 30 Hz tick. Every table below says which rows
are waits and which are zero-time artefacts. The board half, with silicon
durations, belongs to phase7-W6.

Short version:

- **The island stays inside every term it declares.** Over 7 traces, the
  last availability sample to the first braking command takes at most
  **607.99 ms**. The budget up to that point is 643.33 ms (500 + 110 + 33.33).
- **The vehicle does not stop inside the FTTI.** In all 4 runs with a
  velocity log, the vehicle takes 3196-3293 ms from the last sample to
  |v| < 0.001 m/s. The FTTI is 3000 ms. The cause is the settle term, not the
  island: the demo enters the stop at 4.21-4.23 m/s, not the 3.0 m/s the
  contract assumes, and the observed stop takes 2666-2685 ms against the
  declared 2034.

## 1. What was run

Contract terms, from `src/safety_island_bringup/launch/safety_island.contract.yaml`:

- The availability subscriber has `max_age: 500ms`.
- `on_violation` is `reaction: call_mrm, within: 110ms`. That is the handler's
  100 ms tick plus `timeout_call_mrm_behavior` 10 ms.
- `call_mrm` outputs `emergency_stop_operate`. The operator's `on_timer` runs
  at 30 Hz, a 33.33 ms sampling hop.
- The operator publishes `emergency_control_cmd` with `settle: 2034ms`.

The checker's diagnostic (phase 6 W8a) is:

```
detection 500.00ms + reaction 2177.33ms (reaction route /mrm_handler/call_mrm
-> /mrm_emergency_stop_operator/on_timer (+33.33ms sampling) = 143.33ms +
settle 2034.00ms) = 2677.33ms fits the fault-tolerant time interval
3000.00ms with 322.67ms of slack
```

**Injection.** The injection is the one the demo already uses
(`demo/scenario_driver.py`). The driver drives the vehicle on the sample
route for 15 s. It then finds the process publishing
`/system/operation_mode/availability` (Autoware's `/system/converter`) from
the live graph and sends it SIGSTOP. That stops the stream at a known wall
time. The island's handler sees the sample go stale and stops the vehicle.
After 10 s the driver sends SIGCONT.

`experiments/reaction-trace/inject.py` runs the same sequence, using the same
helpers. It adds a time-stamped JSON-lines log with these records:

- the wall time just before and just after the `os.kill`;
- every availability sample the host receives;
- every island `mrm_state` and island emergency `control_cmd`;
- `/localization/kinematic_state` from 5 s before the fault to 20 s after it.

`experiments/reaction-trace/run.sh <id>` runs one traced run: host Autoware,
the traced island, and the injector. It is `just trace-demo` with the
injector in place of the scenario.

**Aligning wall and simulated time.** The trace is in simulated time. The
injector's log is in host wall time. `extract.py` aligns them on the first
MRM_OPERATING `mrm_state` sample. The host received that sample, and the
island traced its publish as `PUB_MRM_HANDLER_MRM_STATE`. A second anchor
checks the alignment: the last availability sample before the fault, which
both the island (`TAKE`) and the host received. The two anchors agree within
0.21-1.78 ms. That is the error bar on every plant-side row below.

**Runs.** All runs use image sha256 `070baae6f877...` (the W1 gate image),
under host load 14-49 (`/proc/loadavg`, recorded in each `.meta`). W2's QEMU
jobs and a nano-ros CI runner were running at the same time.

| run | trace | demo verdict | trace-check | used |
| --- | --- | --- | --- | --- |
| r1 | `build/trace/w3-r1.trace` | PASS (4.25 -> 0.00 m/s) | PASS | yes |
| r2 | `build/trace/w3-r2.trace` | PASS (4.26 -> 0.00 m/s) | trace 0 B | no, trace lost |
| r3 | `build/trace/w3-r3.trace` | PASS (4.27 -> 0.00 m/s) | trace 0 B | no, trace lost |
| r4 | `build/trace/w3-r4.trace` | PASS (4.16 -> 0.00 m/s) | trace 0 B | no, trace lost |
| r5 | `build/trace/w3-r5.trace` | PASS (4.25 -> 0.00 m/s) | PASS | yes |
| r6 | `build/trace/w3-r6.trace` | PASS (4.26 -> 0.00 m/s) | PASS | yes |
| r7 | `build/trace/w3-r7.trace` | PASS (4.27 -> 0.00 m/s) | PASS | yes (the figure) |
| w1-demo | `build/trace/demo.trace` (W1 run 1) | FAIL (no recovery) | PASS | island side only |
| w1-demo2 | `build/trace/demo2.trace` (W1) | PASS | PASS | island side only |
| w1-demo3 | `build/trace/demo3.trace` (W1 gate) | PASS | PASS | island side only |

**What went wrong in the runs, and why.**

- **r2-r4 lost their traces.** Each file is 0 B. The island dumps its buffer
  from an exit-time hook. The supervisor's `TERM,5000,KILL` teardown killed it
  during that dump, with the host disk busy and load at 14-33. r1 survived
  only because its injector aborted on exit (see the next item).
  `run.sh` now has the injector's own job stop the island
  (`stop-island.sh`: SIGTERM, then wait up to 120 s) before the supervisor
  tears anything down. r5-r7 were run that way.
  `just trace-demo` has the same teardown and can lose the trace the same way
  under load; that recipe belongs to W1 and was not changed.
- **r1's injector exited with 134** ("terminate called without an active
  exception"): rclpy was torn down under the logger thread. The trace and the
  log are intact. `inject.py` now exits with `os._exit`.
- **W1's run 1 failure (no availability sample after SIGCONT) did not
  recur.** All 7 W3 runs recovered to NORMAL.
- The W1 traces have no injector log, so they give the island-side rows only.
  `demo.trace` and `demo2.trace` come from an earlier build (image
  `2879fee4...`, before W1's single-read timestamp fix). Their rows agree with
  the rest.

## 2. The timeline

Markers are from `src/safety_island_tracing/markers.json`. The last event in
the chain is `PUB_MRM_EMERGENCY_STOP_OPERATOR_EMERGENCY_CONTROL_CMD` (id 21).
The task text called it `..._CONTROL_CMD`; no marker has that name. Its arg
is the operator state, so "braking" means arg 2 (OPERATING). The host log
shows the first such command carrying a negative acceleration: -0.039 m/s^2
in r1, -0.030 in r7. That is the jerk-limited ramp starting.

Run r7 as `extract.py` prints it (`build/trace/w3-r7.trace`; simulated ms
since island boot):

```
    take                 39423.015
    fresh                39901.000
    detect               40001.000
    call                 40001.000
    mrm_state            40001.000
    serve_entry          40001.006
    serve_exit           40001.006
    op_prev_tick         39997.000
    op_brake_tick        40031.000
    brake_pub            40031.000
    stopped_state        42802.003
    resume_take          50625.010
  order detect..brake: PATH_MRM_HANDLER_ON_TIMER_ENTRY > PATH_MRM_HANDLER_CALL_MRM_ENTRY > CALL_MRM_HANDLER_EMERGENCY_STOP_OPERATE > PUB_MRM_HANDLER_MRM_STATE > PATH_MRM_HANDLER_CALL_MRM_EXIT > PATH_MRM_HANDLER_ON_TIMER_EXIT > SERVE_MRM_EMERGENCY_STOP_OPERATOR_OPERATE_ENTRY > SERVE_MRM_EMERGENCY_STOP_OPERATOR_OPERATE_EXIT > PATH_MRM_EMERGENCY_STOP_OPERATOR_ON_TIMER_ENTRY > PUB_MRM_EMERGENCY_STOP_OPERATOR_EMERGENCY_CONTROL_CMD
  host sigstop_sim_ms: 39451.401710510254
  host alignment_disagreement_ms: 0.21123886108398438
  host v0_sim_ms_by_stamp: 42716.22586250305
  host v_at_brake_mps: 4.223516525377227
```

The events, in order:

- `take` is the last `TAKE_MRM_HANDLER_OPERATION_MODE_AVAILABILITY`.
- `fresh` is the last handler tick that still saw the sample as fresh.
- `detect` is the tick where `PATH_MRM_HANDLER_CALL_MRM_ENTRY` first fires.
- `call` is the operate=1 `CALL`.
- `serve_*` is the operator's `operate` callback.
- `op_brake_tick` / `brake_pub` is the operator's first tick in OPERATING,
  and its braking publish.
- `stopped_state` is the first `mrm_state` publish with MRM_SUCCEEDED. The
  handler sets that state once its odometry input shows |v| < 0.001 m/s.

The same walk for every run is in `experiments/reaction-trace/events.csv`
and `runs/*.json`.

What the order shows, in every trace:

- `call_mrm`, the `CALL` and the `mrm_state` publish happen on one handler
  tick, at one instant.
- The operator's `operate` callback runs 5-7 us later in simulated time, in
  the same executor turn, right after the handler's callback exits.
- The braking command leaves on the operator's next 30 Hz tick.
- The service reply is not on the path. The handler drains it on its next
  tick.

## 3. Declared versus observed

All values are ms of native_sim SIMULATED time. In the plant rows, the host
wall clock is mapped onto simulated time with the error given in the last
row. "Zero-time artefact" means an interval inside one callback, which
native_sim runs in zero simulated time. Output of `extract.py summary`,
verbatim (also `experiments/reaction-trace/summary.csv`):

```
All values in native_sim SIMULATED ms (plant rows: host wall clock mapped onto it).
Zero-time artefact = inside one callback; native_sim runs code in zero simulated time.
interval                                     declared_ms                     kind                           run r1   run r5   run r6   run r7   run w1-demo  run w1-demo2  run w1-demo3  max    
last take -> last fresh tick                 -                               wait (tick phase)              416.99   459.99   472.99   477.99   445.99       442.00        426.99        477.99 
last take -> call_mrm tick                   500 + tick<=100                 wait (staleness + tick phase)  517.98   560.99   573.99   577.99   546.00       542.00        527.00        577.99 
  of which past the 500 ms bound             <=100 (tick in the 110)         wait (tick phase)              17.98    60.99    73.99    77.99    46.00        42.00         27.00         77.99  
call_mrm entry -> CALL                       (inside the 110)                zero-time artefact             0.00     0.00     0.00     0.00     0.00         0.00          0.00          0.00   
CALL -> operate callback entry               10 (timeout_call_mrm_behavior)  wait (executor turn)           0.01     0.01     0.01     0.01     0.01         0.01          0.01          0.01   
operate callback entry -> exit               -                               zero-time artefact             0.00     0.00     0.00     0.00     0.00         0.00          0.00          0.00   
operate exit -> first braking PUB            33.33 (sampling)                wait (30 Hz tick phase)        11.99    20.99    29.99    29.99    1.98         14.99         33.98         33.98  
call_mrm tick -> first braking PUB           110 + 33.33 = 143.33            wait                           12.00    21.00    30.00    30.00    1.99         15.00         33.98         33.98  
last take -> first braking PUB               500 + 143.33 = 643.33           wait                           529.98   581.99   603.99   607.99   547.99       557.00        560.99        607.99 
first braking PUB -> v < 0.001 (odom stamp)  2034 (settle, at 3.0 m/s)       plant (host wall clock)        2666.29  2684.62  2678.85  2685.23  -            -             -             2685.23
first braking PUB -> MRM_SUCCEEDED pub       2034 + odom + tick              plant + wait                   2688.00  2778.00  2770.00  2771.00  2698.03      2784.00       2766.01       2784.00
last take -> v < 0.001 (odom stamp)          2677.33 (FTTI 3000)             whole budget                   3196.27  3266.61  3282.84  3293.21  -            -             -             3293.21
v at fault (m/s)                             -                               context                        4.25     4.25     4.25     4.27     -            -             -             -      
SIGSTOP after last take (ms)                 -                               context                        81.67    17.69    9.96     28.39    -            -             -             -      
alignment disagreement (ms)                  -                               context                        1.78     1.08     0.98     0.21     -            -             -             -      
```

Reading it, term by term:

- **Detection, 500 ms (declared `max_age`). A wait.** The handler compares
  `now - stamp > 0.5` on its tick, so the call cannot come before 500 ms.
  Over 7 traces it came 517.98-577.99 ms after the last sample. The part past
  500 is the phase of the 100 ms tick: 17.98-77.99 ms, so up to one period.
  The last fresh tick is always 417-478 ms after the sample, one tick earlier.
  The declared detection plus reaction is 610 ms, and the observed maximum is
  577.99 ms. The 500 is counted from the last SAMPLE, not from the fault. The
  SIGSTOP came 9.96-81.67 ms after the last sample, so fault-to-detection was
  436-564 ms.
- **Reaction, 110 ms (declared). The tick is a wait; the rest is zero-time.**
  The tick's share is inside the row above. The 10 ms
  `timeout_call_mrm_behavior` has nothing to wait on here. `call_mrm` to
  `CALL` reads 0.00, and `CALL` to the operator's callback reads 0.01
  (5-7 us). Both are the same executor turn: a zero-time artefact of
  native_sim, not an observation that the hop is free. On silicon these rows
  are execution time, which is W6's measurement.
- **Sampling, 33.33 ms (declared). A wait.** The time from `operate` returning
  to the first braking publish is the phase of the operator's 30 Hz tick:
  1.98-33.98 ms. **One trace, w1-demo3, exceeds the declared 33.33 by
  0.65 ms.** The operator's timer is
  `NROS_CREATE_WALL_TIMER(1000 / params_.update_rate)`, integer ms, so its
  period is 33 ms, not 33.33. In w1-demo3 the tick periods near the fault
  average 33.000 ms and range 31.003-34.0 ms. That single wait is one late
  tick. The chain is still far inside its budget: `call_mrm` to braking is at
  most 33.98 ms against 143.33, because the tick phase and the operator
  phase are not both worst-case at once. But the per-term statement "the
  sampling hop is at most one declared period" does not hold under this
  load, by 0.65 ms.
- **Settle, 2034 ms (declared). Plant, host wall clock.** From the first
  braking command to the first odometry sample with |v| < 0.001 m/s took
  2666.29-2685.23 ms, so **the declared settle is exceeded in every run, by
  632-651 ms.** The contract derives 2034 ms from the operator's jerk (-1.5)
  and acceleration (-2.5) at an ASSUMED entry speed of 3.0 m/s. The demo
  brakes from 4.21-4.23 m/s (`v_at_brake_mps`). The same formula at the
  observed speeds gives 2517-2527 ms. The remaining 139-168 ms is consistent
  with the planning simulator's vehicle model (`DELAY_STEER_ACC_GEARED`,
  `acc_time_delay: 0.1`, `acc_time_constant: 0.1` in
  `/opt/autoware/1.5.0/share/sample_vehicle_description/config/simulator_model.param.yaml`).
  The trace cannot separate that from the vehicle command gate's own hop. The
  in-trace MRM_SUCCEEDED publish comes 2688-2784 ms after braking: the same
  plant time plus the odometry hop and up to one handler tick.
- **The whole budget, 2677.33 against the FTTI of 3000. Exceeded.** The
  last sample to standstill took 3196.27-3293.21 ms: 196-293 ms past the
  FTTI in all 4 runs with a velocity log. The island's own part (607.99 ms at
  most) is inside its 643.33. The overrun is all in the settle term's entry
  speed assumption.

## 4. The figure

`~/Downloads/contract-e2e-slides/assets/diagrams/reaction_trace.typ` and
`reaction_trace.png` (300 ppi, 2302 x 625 px, aspect 3.68). The declared
budget is drawn above and the observed intervals of run r7 below, on one time
axis. The axis is broken at 700 ms: linear on each side, compressed after the
break.

r7 is used because it is the best-aligned run (anchors 0.21 ms apart). It
also has the largest detection wait (577.99 ms) and the largest standstill
time (3293.21 ms) of the four runs with a velocity log. So the figure shows
the worst observed case, not a lucky one.

## 5. For the board (W6)

The W1 correction asked W3 to decide whether `TRACING_THREAD` is cut on the
board so that the buffer covers the whole reaction.

- **No interval in this document needs a thread switch.** All of them come
  from markers. Thread switches are 90.6% of the bytes in `w3-r7.trace`
  (105,865 B/s each for switched_in and switched_out, against 4,553 B/s for
  markers).
- **With the switches cut, the reaction fits.** The native_sim marker rate is
  412-421 markers/s. At the board's 12 B per marker, 16 KiB holds 3.3 s. The
  reaction takes about 3.3 s including the plant, and 0.61 s up to the
  braking command.
- **Cutting the switches alone is not enough.** The RAM buffer is one-shot
  from boot, so 3.3 s of markers covers boot, not a fault injected at 40 s.
  The board trace needs one of three things: the fault injected in the first
  seconds after boot, the buffer re-armed at injection, or a
  stop-on-first-`CALL_MRM` trigger.
- **Recommendation:** cut `TRACING_THREAD` on the board and re-arm at
  injection. W3 does not own the board conf, and the board switch rate has
  not been measured (W6).

## 6. Files

`experiments/reaction-trace/`:

- `inject.py` is the injector: the demo sequence plus the time-stamped log.
- `run.sh` runs one traced run.
- `stop-island.sh` stops the island and waits for its trace dump.
- `extract.py` walks the timeline for one trace (`--json` writes it) and
  builds the `summary` table and CSV. It decodes with
  `src/safety_island_tracing/island_trace.py`, unchanged.
- `events.csv` has the event times per run. `summary.csv` is the table in
  section 3.
- `runs/` has, per run: `*.json` (the full extraction, including the
  injector-side numbers), `*.trace.meta` (image sha256, source revision,
  loadavg, wall seconds) and `*.trace.check.txt` (trace-check output).

The traces themselves (11-12 MB each) and the injector logs stay under
`build/trace/` and are not committed. To reproduce:

    experiments/reaction-trace/run.sh r8
    python3 experiments/reaction-trace/extract.py summary experiments/reaction-trace/runs/*.json

## 7. What this is not

This is one rung (native_sim), N = 4 runs with the plant and 7 without, on a
loaded host. Every island-side number is a wait in simulated time. It says
nothing about execution time on the S32K344. Every observed maximum is a lower
bound on the true worst case.
