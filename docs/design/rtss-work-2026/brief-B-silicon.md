# D8-B: can the island run live on silicon, with traces?

Feasibility brief for RTSS@Work 2026, 2026-09-28. Repo
simple-autoware-safety-island, branch contract-params, HEAD e318253. Board:
MR-CANHUBK344 (S32K344, Cortex-M7 at 160 MHz). The host peer was rmw_zenohd on
/dev/ttyUSB0 (FT232R) at 115200 baud, with TCP on 7449.

Everything below was measured today unless it says otherwise. Every experiment
edit was local and has since been reverted. The combined diff is in
`d8-local-edits.patch`, next to this file, and is listed in section 6.

## 0. Short answer

- With the parameter services off, the board image **registers, spins and runs
  the whole reaction on silicon**. That is the first time on this board. The
  chain was: the availability stream went stale, then CALL_MRM, then the
  operate service, then the emergency operator went to OPERATING, then the
  braking command.
  - From the last availability sample to the first
    `/system/emergency/control_cmd` in OPERATING took **554.8 ms** in run 5
    and **588.9 ms** in run 4.
  - From the detecting tick to the braking command took 39.0 ms and 49.0 ms.
- Three changes were needed. Only the heap change is a board fact.
  1. `features = []` in the bringup, plus two island-side workarounds for
     nano-ros gaps (section 1).
  2. The nano-ros heap raised from 94,208 to 122,880 B. The board then has
     10,208 B of SRAM left.
  3. `Z_FEATURE_LOCAL_QUERYABLE=1`. Without it, the handler's operate call
     never reaches the operator in the same image.
- **The blocking item is the 115200 serial link, not memory.** It carried only
  3 host topics at 10 Hz, and it could not keep even that up.
  - Availability samples stopped arriving about 1 s after the first spin, so
    the island raised a FALSE emergency stop (run 5).
  - With host publishers running, the router expired the board's session about
    21 s after it opened in 3 of 3 runs. It did not expire in the one run
    without host publishers (64 s).
  - At the contract's rates, the island's 11 subscriptions need 2.4x to 3.8x
    what 115200 baud carries.

## 1. Turning the parameter services off

**The switch.** The switch is `features = ["param_services"]` in
`src/safety_island_bringup/system.toml`:36. There is no Kconfig for it.
`board-build` and `qemu-build` pass the list through
`nros config show --format cmake` as `NANO_ROS_FEATURES`. It selects the cargo
feature `param-services`, and the entity inventory counts 6 queryables per
node for it.

**What `features = []` does to the table.** From `build-qemu-d8`:

    set(NROS_DERIVED_MAX_QUERYABLES 7)
    set(NROS_ENTITY_APP_QUERYABLES 7)
    set(NROS_DERIVED_TL_PUBLISHERS 5)
    NROS_RESOLVED_ZPICO_MAX_QUERYABLES:INTERNAL=7

That is 31 queryables before and 7 now: 5 transient-local caches and 2
operate servers.

**It does not build as is.** Two gaps stand in the way.

1. **Launch seeds do not link (a nano-ros gap).** The generated entry still
   seeds the launch file's `<param from=...>` values through
   `nros_cpp_declare_param`. That symbol is compiled only under
   `feature = "param-services"` (`params_shim.rs:76`). The link fails:

       qemu_entry_nros_main_generated.cpp:81:(.text._ZL18__nros_entry_setupv+0x3a): undefined reference to `nros_cpp_declare_param'

   Phase-461 W6 says launch seeds "keep going through
   `nros_cpp_declare_param`, unchanged". That holds only once the
   `param-store` feature exists. Today, a `features = []` bringup with launch
   parameters cannot link. This is worth filing upstream.
   Local workaround: I commented out the four `<param from=...>` lines in
   `safety_island.launch.xml`.
2. **`declare_parameter` is boot-fatal.** The stubs answer Unsupported (-16).
   Each component's `declare_parameter` helper calls `set_error`, which halts
   boot, as `system.toml` says.
   Local workaround: in each of the 4 helpers, if the code is `Unsupported`,
   return the compiled-in default.

**Where the parameters come from then.** They come only from the compiled-in
default, which is the second argument of `declare_parameter` in the source.
- The contract's `params:` block carries names and types, not values.
- There is no `--ros-args -p` on the MCU.
- The launch seeds are the path that does not link.

The island loses:
- `ros2 param get/set/list/describe/dump`,
- the launch file's values,
- the `use_sim_time` switch.

**Which of the 21 parameters matter, and do the defaults match the yaml?**

| param | yaml | source default | matters for the demo |
| --- | --- | --- | --- |
| update_rate: emergency 30, comfortable 10, handler 10; stop_mode `rate` 30.0 | same | same | yes. They are the timer periods the contract's `rate_hz` states. |
| timeout_operation_mode_availability | 0.5 | 0.5 | yes. It is the detection bound (contract `max_age: 500ms`). |
| timeout_call_mrm_behavior, timeout_cancel_mrm_behavior | 0.01 | 0.01 | no. The port sends and polls. |
| target_acceleration, target_jerk (emergency) | -2.5, -1.5 | same | yes. They shape the braking ramp. |
| **use_comfortable_stop** | **false** | **true** | **differs**, see below |
| min_acceleration, max_jerk, min_jerk (comfortable) | -1.0, 0.3, -0.3 | same | only on the comfortable path |
| stop_hold_acceleration, enable_auto_parking | -1.5, true | same | stop_mode outputs only |
| use_emergency_holding, timeout_emergency_recovery, use_parking_after_stopped, use_pull_over, turning_*_on.emergency | false, 5.0, false, false, true, true | same | no |

Only `use_comfortable_stop` changes, from false (yaml) to true (source).
- On the timeout path it makes no difference: `getCurrentMrmBehavior`
  returns EMERGENCY_STOP on a timeout whatever the flag says.
- With `true`, `isDataReady()` also waits for the comfortable operator's
  status.
- With `true`, an emergency that is not a timeout (`autonomous: false`)
  picks COMFORTABLE_STOP.
- `trace-check` reports `exemption lapsed: use_comfortable_stop is None`,
  because it reads the value from the launch file.

To keep the yaml's behaviour without seeds, flip the default in
`mrm_handler_core.cpp:85`, or wait for phase-461 W6 ("not started").

## 2. Measurements: QEMU and board images

**QEMU** (`mps2/an385`, ethernet transport, parameter services off):

| image | FLASH | RAM | run |
| --- | --- | --- | --- |
| merged pin with param services (W8, for reference) | 603,080 | 438,324 | stage 4, heap exhausted |
| `build-qemu-d8`, conf heap 94,208 / stack 16,384 | 541,948 | 403,892 | **stage 4, heap exhausted, peak 87,528** |
| `build-qemu-d8b`, heap 196,608 / stack 32,768 (diagnostic) | 541,964 | 522,676 | FirstSpin, **peak 95,216** |
| `build-qemu-d8c`, heap 122,880 / stack 16,384 (conf stack) | 541,948 | 432,564 | **FirstSpin, clean console**, 4 nodes plus 23 topics in the host graph |

The heap is not met at the conf value (`qemu-20260928T165723`):

    nros: HEAP EXHAUSTED: request 408 bytes, arena 94720 bytes, caller 0x59913
    stage      4  RegisteringEntities -- an entity claimed arena; registration in flight
      platform heap PEAK            87528 bytes   (92.4% of the heap)

With 120 KiB (`qemu-20260928T170858`):

    stage      6  FirstSpin -- registration complete and spinning
      platform heap PEAK            95216 bytes   (77.2% of the heap)
      platform heap capacity        123392 bytes   (NROS_ZEPHYR_HEAP_SIZE)
    HEAP HEADROOM: ok -- 28176 bytes spare (peak 95216 of 123392, floor 24576).

So the parameter services cost 95,000 B of heap at the first spin (190,216
against 95,216). They also cost 34,432 B of static RAM on QEMU. Registration
without them still needs more than the board's 94,720 B. The main stack at
16,384 B was enough without the parameter services, because W8's overflow
was in `create_service` for the parameter servers.

**Board** (`just BOARD_BUILD_DIR=build-board-d8 board-build`, run twice;
`build-board-d8q` is the variant for section 3). Region reports as printed
(both passes identical, knob check converged):

| image | RAM (SRAM, of 327,680) | free | DTCM | ITCM | FLASH |
| --- | --- | --- | --- | --- | --- |
| W8, param services on (reference) | 323,112 (98.61%) | 4,568 | 84,528 | 14,108 | 628,376 |
| **build-board-d8**, off, conf heap 94,208 | **288,792 (88.13%)** | **38,888** | 84,416 | 14,164 | 472,844 |
| build-board-d8, off, heap 122,880 | 317,472 (96.88%) | 10,208 | 84,416 | 14,164 | 472,844 |
| build-board-d8q: plus LOCAL_QUERYABLE, trace buffer 24 KiB (the flashed image) | 325,664 (99.38%) | 2,016 | 84,416 | 14,164 | 473,348 |

    Memory region         Used Size  Region Size  %age Used
          IVT_HEADER:         256 B        256 B    100.00%
               FLASH:      472844 B    4144896 B     11.41%
                 RAM:      288792 B       320 KB     88.13%
                ITCM:       14164 B        64 KB     21.61%
                DTCM:       84416 B       128 KB     64.40%
            IDT_LIST:           0 B        32 KB      0.00%
    check-knob-delivery: DERIVED_PAIRS names every one of the 25 resolver call site(s) over 23 fact(s).
    board-build: tolerating the known upstream SUBSCRIBED_TYPE_BOUNDS line (phase-412 W4); nothing else is red.

## 3. Silicon

Flashed with `pyocd flash -t s32k344` and reset with `pyocd reset`. The router
is `just board-peer`. Raw reads, the router log, CSVs and decodes are in
`experiments/serial-interop/d8/` (untracked).

| run | image | host publishers | session | registration | spins | result |
| --- | --- | --- | --- | --- | --- | --- |
| 1 | d8, heap 94,208 | none | opens | **fails**: heap peak 86,840 of 94,720 (boot report over SWD) | no | 11 heartbeats, then panic |
| 2 | d8, heap 122,880 | none | opens 1.2 s after reset, alive 64 s | passes | **yes**, first marker at 2,402.8 ms uptime | `ros2 node list` shows all 4 nodes and 23 topics |
| 3 | d8 | control_mode, operation_mode/state, availability (stopped 3.5 s after reset) | opens; router expires it at +21.2 s | passes | yes | CALL_MRM fires; **operate never served** |
| 4 | d8q (LOCAL_QUERYABLE, 24 KiB) | same, availability stopped at about 4.1 s uptime | opens; expired at +21.2 s | passes | yes | full chain, but triggered BEFORE the stop (samples stalled) |
| 5 | d8q | same, availability NEVER stopped | opens; expired at +21.2 s | passes | yes | 3 samples, then none; **false reaction** 515.8 ms later |

**Markers that fire.**
- Run 2 fired 15 of 31. These are every ON_TIMER pair and every PUB marker
  of the operators and stop_mode. The handler exits with arg 0
  (`isDataReady()` is false with no availability), as `docs/wcet.md`
  predicted.
- Run 4 fired 26 of 31. The only markers missing are the 5 comfortable-path
  markers, which the timeout reaction does not take.

**Per-pair durations** (w7_pairs.py, cycle-counter time, us):

    run 2 (idle, 16 KiB, 3.4 s of spin):
    pair (ENTRY->EXIT)                                       N     min us  median us     max us
    PATH_MRM_COMFORTABLE_STOP_OPERATOR_ON_TIMER             36      245.3      253.2      258.7
    PATH_MRM_EMERGENCY_STOP_OPERATOR_ON_TIMER              105      334.3      339.4      346.3
    PATH_MRM_HANDLER_ON_TIMER                               36        9.3        9.9       10.3
    PATH_STOP_MODE_OPERATOR_ON_TIMER                       105      353.9      362.3      366.7

    run 4 (reaction, 24 KiB, 4.5 s of spin):
    PATH_MRM_COMFORTABLE_STOP_OPERATOR_ON_TIMER             46      242.1      250.6      279.4
    PATH_MRM_EMERGENCY_STOP_OPERATOR_ON_TIMER              136      331.0      352.6      397.3
    PATH_MRM_HANDLER_CALL_MRM                               37       84.4       87.4    37698.3
    PATH_MRM_HANDLER_ON_TIMER                               46        9.8      424.8    38036.7
    PATH_STOP_MODE_OPERATOR_ON_TIMER                       135      345.8      352.4      400.2
    SERVE_MRM_EMERGENCY_STOP_OPERATOR_OPERATE                1        6.2        6.2        6.2

    run 5: CALL_MRM 40 / 84.9 / 87.3 / 28266.8; ON_TIMER(handler) 46 / 9.5 / 425.3 / 28606.0

How to read these durations:
- The operator callbacks take 250 to 360 us. Each one publishes 1 to 4 times,
  with local delivery.
- The handler's tick is 425 us once it has data.
- The first CALL_MRM tick takes **28 to 38 ms**. It sends the operate request
  over the UART, and zenoh-pico's Zephyr serial TX is `uart_poll_out` per
  byte (`network.c:1227`): 86.8 us of busy-wait per byte at 115200, inside the
  callback.
- That tick delays the 30 Hz timers. Their period maximum is 61 to 68 ms in
  runs 3 to 5, against 42 ms idle.

**The reaction, run 5** (availability never stopped; uptime in ms):

      1412.201 TAKE_MRM_HANDLER_OPERATION_MODE_AVAILABILITY      (last of 3; no more ever arrived)
      1927.954 PATH_MRM_HANDLER_CALL_MRM_ENTRY
      1932.852 CALL_MRM_HANDLER_EMERGENCY_STOP_OPERATE
      1956.144 PUB_MRM_HANDLER_MRM_STATE arg=131074               (MRM_OPERATING / EMERGENCY_STOP)
      1966.705 SERVE_MRM_EMERGENCY_STOP_OPERATOR_OPERATE_ENTRY
      1967.001 PUB_MRM_EMERGENCY_STOP_OPERATOR_EMERGENCY_CONTROL_CMD arg=2

Run 4 has the same shape: last TAKE at 3338.077, CALL at 3877.948, SERVE at
3926.697, braking command at 3926.986.

Against the contract, from the last sample to the braking command took
554.8 ms and 588.9 ms. The contract allows 500 ms of detection plus the
110 ms `within`, and the FTTI is 3 s.

**Without LOCAL_QUERYABLE (run 3).** CALL fires and there is no SERVE. At
t = 66 s the host sees the result verbatim:

    state: 2          (mrm_state: MRM_OPERATING)
    behavior: 2       (EMERGENCY_STOP)
    state: 1          (/system/mrm/emergency_stop/status: AVAILABLE, not OPERATING)
    longitudinal: velocity: 0.0 acceleration: 0.0 ...   (control_cmd not braking)

The cause: the island has one zenoh-pico session. nano-ros sets
`Z_FEATURE_LOCAL_SUBSCRIBER=1` for this reason (`nros_rmw_zenoh.cmake:203`),
but `Z_FEATURE_LOCAL_QUERYABLE` stays at zenoh-pico's 0. A service call
between nodes in the same image therefore goes to the router, which never
routes it back to the session it came from. The upstream fix is one line
beside the LOCAL_SUBSCRIBER one. The local experiment put
`zephyr_compile_definitions(Z_FEATURE_LOCAL_QUERYABLE=1)` in the entry
CMakeLists.

**The link failure (runs 3 to 5).**
- In run 5, `ros2 topic pub -r 10` ran for the whole window. The island took
  3 samples in 6 ms at its first spin, then none for 4.5 s.
- In run 4, the last sample arrived at uptime 3.338 s. The publisher was
  stopped at about 4.10 s: the router saw the board's session open at
  09:16:43.776, and the stop came at 09:16:45.921. So the reaction came from
  missing samples, not from the stop.
- The router expired the board's session 21.17 to 21.2 s after it opened in
  runs 3, 4 and 5:

      2026-09-28T09:18:49.478158Z DEBUG net-0 ... Closing transport with peer: c09dda6cd0f9cf6f04d9233b448394cb

  The board then auto-reconnects under the same ZID, and the router logs
  `Route data with unknown scope 7!`.
- In run 2 (no host publishers), the session lived 64 s with no expiry.
- The root cause is not diagnosed. The candidates are:
  - the 1 KiB RX ring (`_Z_ZEPHYR_SERIAL_RX_RING_BYTES`) overflowing, with
    the error log going to the unwired console;
  - the read task starving behind busy-wait TX.

  Polling zpico's RX counters over SWD, the way W7 polled the tables, is the
  next step.

**Tracing cost, DWT CYCCNT** (run 2 image, read over SWD at uptime 37.8 s):

    2042c344:  000030f2   island_trace_cost_n     = 12,530
    20400cd4:  00000000   island_trace_cost_min   = 0
    2042c340:  000003ba   island_trace_cost_max   = 954 cycles = 5.96 us
    2040bcc0:  005dee01 00000000   island_trace_cost_sum = 6,155,777 -> mean 491.3 cycles = 3.07 us
    2042c33c:  00000001   island_trace_cost_empty = 1
    e0001000:  40000001   DWT_CTRL (CYCCNT on)

Two caveats about these numbers:
- n includes markers after the buffer latched full, which take a shorter
  path. So the mean mixes the two paths. The maximum, 5.96 us, is the upper
  bound for a real write.
- A minimum of 0 is suspicious for the bracket, and should be checked.

**Buffer coverage.**
- 16 KiB covered **3.4 s of spinning**. In run 2, the first marker came at
  2.40 s, the buffer was full at 5.84 s, and the rate was 359 markers/s, or
  4.3 KB/s.
- Run 3 caught the reaction only because availability was stopped 3.5 s
  after reset.
- 24 KiB covered 4.5 s, up to 7.52 s. Registration ends 1.4 to 3.1 s after
  reset.

What to cut, in order:
1. The 4 stop_mode PUB markers. They are 420 of 1,233 markers, 34%, and
   stop_mode is not on the reaction path.
2. The PUB markers of the emergency operator. Their arg already appears as
   the ON_TIMER arg.
3. The comfortable operator's PUB marker.

Keeping only the PATH pairs, TAKE, CALL/SERVE and MRM_STATE gives about 200
markers/s, which roughly doubles the window. The real fix is a start trigger:
begin recording at the first TAKE, or keep a pre-roll ring. Zephyr's RAM
backend is one-shot. Heartbeats cost 14 B per 100 ms, and provenance costs
776 B once.

## 4. The UART link

**What the subscriptions need at contract rates.** Payloads are the derived
XCDR bounds (`message_bound_knobs.cmake`). The per-sample overhead is
estimated, not measured:
- 55 B with a declared key id: serial header, length and CRC 7; COBS 2;
  zenoh frame, push and put about 10; rmw_zenoh attachment 36;
- plus about 100 B more if the full key string travels.

| direction | B/s (low / high) | x 115200 capacity (11,520 B/s at 8N1) |
| --- | --- | --- |
| host -> island, 9 external topics (control_cmd 30, availability 10, odometry 10 at 880 B, control_mode 10, gear 10, op state 10, steering 30, velocity 30, route_state 30) | 27,350 / 44,140 | **2.4x / 3.8x** |
| island -> host, 14 publishers, when Autoware subscribes | 24,480 / 48,180 | 2.1x / 4.2x |

Odometry alone is 9.3 KB/s at the contract's 10 Hz. Autoware publishes
`/localization/kinematic_state` at 50 Hz unless it is downsampled. TX is also
CPU time: busy-wait costs 86.8 us per byte, so 24 KB/s of output would need
2.1 s of CPU per second.

**A faster baud rate is possible on both ends. It has not been tested.**
- LPUART2 (`uart@40330000`) is clocked from AIPS_SLOW_CLK at 40 MHz
  (`hal_nxp .../s32k344/src/Clock_Ip_Cfg.c`: AIPS_SLOW_CLK 40000000U), and
  the baud rate is clk/(OSR x SBR) with OSR 4 to 32. That gives exactly
  1,000,000 (OSR 20, SBR 2) and 2,000,000 (OSR 20, SBR 1).
- The host adapter is an FT232R (`0403:6001`, ftdi_sio). It supports up to
  3 Mbaud, and 1M and 2M are exact.

Three places change:
- `CONFIG_NROS_ZENOH_LOCATOR` in `snippets/island-serial/serial.conf`
  (`#baudrate=`). zenoh-pico calls `uart_configure()` with that value.
- `current-speed` in `serial.overlay`.
- The listen endpoint in `just/board-peer.just`.

The risks: there is no flow control (`UART_CFG_FLOW_CTRL_NONE`), and the RX
ring is 1 KiB. At 200 KB/s the ring fills in about 5 ms if the read task
lags. 2 Mbaud (200 KB/s) covers the inbound estimate 4.5 to 7 times over.
1 Mbaud covers it 2.3 to 3.7 times.

**CAN as the demo link.** The story fits the setting, but it is not a
near-term option.
- nano-ros has `NROS_ZENOH_LINK_CAN`, a multicast datagram link with a
  63 B MTU. It carries topics only: queries and liveliness do not route to a
  multicast face, so there are no services, no `operate` call and no ROS
  graph.
- It also has `NROS_ZENOH_LINK_ISOTP`, which is unicast with a 4,095 B MTU
  and full ROS semantics. Both have been proven only on vcan. Phase-394 says
  "Tier 3 -- hardware. MR-CANHUBK344 to a Linux host. Still untouched", and
  flow control is untested on a real bus.
- The host side needs a zenohd with the CAN link. The upstream PR
  (zenoh#2757) is in review, so the stock Humble `rmw_zenohd` cannot listen
  on CAN.
- This host has no CAN adapter. `lsusb` shows only the MCU-LINK and the
  FT232R, and `/sys/class/net` shows only `vcan0`.
- ISO-TP on classic CAN at 500 kbit/s gives roughly 30 to 40 KB/s of payload
  at best. That is no better than UART at 1 to 2 Mbaud.

Verdict on CAN: 2 to 4 weeks, with hardware to buy. It is a later-phase
story, not the demo link.

## 5. One-page summary

**Is a live silicon demo with traces feasible?** Yes, with a reduced input
set. It is not feasible at 115200 baud with the contract's full inputs.

Today's silicon results:
- The board boots, registers all four nodes and spins.
- It runs the complete reaction: detection, the operate service, operator
  OPERATING and the braking command.
- The trace records it, with per-callback durations in cycle-counter time and
  the marker cost bracketed.

Last availability sample to braking command took 555 ms and 589 ms, inside
the 610 ms the contract composes and the 3 s FTTI.

**The blocking item** is the serial link. At 115200 it is 2.4 to 3.8 times
short of the contracted input rates. Even at 3 topics x 10 Hz it stalled
host-to-island delivery after the first spin, which produced a false
emergency stop 516 ms later. The router also expired the session at about
21 s in every run with host traffic. A demo on this link would show a
reaction the link causes, not the fault. The root cause (RX ring overflow or
read-task starvation behind busy-wait TX) is not yet known.

**What it takes, estimated:**
1. **Parameter services off, done properly: 0.5 to 1 day.** Commit
   `features = []`, the helper fallback, the launch-seed removal and the
   `use_comfortable_stop` default. File the nano-ros gap that seeds do not
   link without param-services. Alternatively, wait for phase-461 W6, which
   has not started.
2. **Heap 122,880 in the board conf: 0.5 day.** Record today's boot-report
   dump beside it. This leaves 10,208 B of SRAM, or 2,016 B with a 24 KiB
   trace buffer.
3. **`Z_FEATURE_LOCAL_QUERYABLE=1`: less than 0.5 day** for the island-side
   workaround. Upstream, it is one line beside LOCAL_SUBSCRIBER in nano-ros.
4. **The link: 2 to 5 days.** This is the risk.
   - Raise the baud rate to 1 or 2 Mbaud (0.5 day).
   - Poll zpico's RX counters and ring over SWD to find the stall
     (1 to 2 days).
   - Shape the traffic (1 day): router downsampling for odometry and the
     30 Hz vehicle topics, or a demo input set of availability, control_mode,
     operation-mode state and control_cmd.
   - Soak test well past 21 s.
5. **Trace window: 0.5 day.** Cut the stop_mode and operator PUB markers, or
   add a start trigger.

Total: about 1 to 1.5 weeks for an honest live demo on the board, driven from
host scripts or a thinned Autoware. The fallback for the talk is a scripted
fault injection with 3 host topics after items 1 to 4, replaying the
recorded trace from today's run as backup. CAN is not on the critical path.

## 6. Files touched (all reverted; combined diff: `d8-local-edits.patch`)

The combined diff is 146 lines. Tracked files, edited for the experiment and
restored with `git checkout`:
- `src/safety_island_bringup/system.toml`: `features = []`.
- `src/safety_island_bringup/launch/safety_island.launch.xml`: the 4
  `<param from>` lines commented out.
- The four `declare_parameter` helpers: `if (r.code() ==
  ::nros::ErrorCode::Unsupported) return default_value;`. The files are
  `mrm_handler_core.hpp`, `mrm_emergency_stop_operator_core.hpp`,
  `mrm_comfortable_stop_operator_core.hpp` and `stop_mode_operator.hpp`.
- `src/zephyr_entry/CMakeLists.txt`:
  `zephyr_compile_definitions(Z_FEATURE_LOCAL_QUERYABLE=1)`.
- `src/zephyr_entry/boards/mr_canhubk3_s32k344.conf`:
  `CONFIG_NROS_ZEPHYR_HEAP_SIZE=122880` (was 94208) and
  `CONFIG_RAM_TRACING_BUFFER_SIZE=24576` (was 16384).

Nothing under third-party/nano-ros was touched. It was already `m` at the
start.

New or untracked files and build outputs:
- `experiments/serial-interop/d8/`: d8-{1..5} trace reads, .meta,
  markers/pairs CSV, decode and pairs text, and the router logs.
- `build/trace/d8-*`.
- `build-qemu-d8`, `build-qemu-d8b`, `build-qemu-d8c`, `build-board-d8` and
  `build-board-d8q`.
- `build/emulation/qemu-20260928T*`.

Regenerated shared outputs: `build/nros/models`,
`build/nros/nros_capabilities.cmake` and `entity_inventory.*`. After the
revert, `just sync` ran and the capabilities file was rewritten. It now reads
`NANO_ROS_FEATURES "param_services"` again.
