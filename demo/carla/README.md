# demo/carla - the island demo on CARLA

Design and plan: `docs/design/carla-island-demo.md` (units C1-C8). Recipes:
`just/carla.just`. The CARLA side is carla-scenario-bridge (CSB,
`NEWSLabNTU/carla-scenario-bridge`, default checkout
`../carla-scenario-bridge` beside this repo, override with `CSB_DIR`) and its
submodule autoware_carla_bridge (acb).

| path | what | unit |
|---|---|---|
| `scenarios/town01_island_odd.xosc` | act b: the Town01 straight, the ODD declared in the file (design 2.5) and read by odd_monitor, which ends it at x 240; success 60 s after the stop | C3, C4 |
| `scenarios/town01_island_takeover.xosc` | act a: the same road and ODD, success at the route's goal under the driver | C3, C4 |
| `scenarios/town01_island_encore.xosc` | the encore: the same road, no ODD; at x 285 a CustomCommandAction tells the act "hpc-loss" | C4 |
| `act_trigger.py` | what that CustomCommandAction runs (`$(env SAI_ACT_TRIGGER)`): one datagram to the act's socket | C4 |
| `cast_dashboard.py`, `cast.sh` | the proof cast: a 1920x1080 dashboard (CARLA chase view, ODD, takeover request, island MRM with the LED mirrored, map, events) recorded with ffmpeg | C8 |
| `../../src/zephyr_entry/snippets/island-booth` | the booth image's snippet: `CONFIG_ISLAND_LED=y`, `CONFIG_ISLAND_BUTTONS=y` (`just board-build-booth`) | C5, C6 |
| `../../tools/timeline/board_buttons.py` | SW1/SW2 over SWD: the on-site check (`just board-buttons`), injection, and the act's button bridge (`RB_TRIGGER=board`) | C6 |
| `../../tools/timeline/run-board.sh --sim carla` | one act on the board with CARLA, the scenario side and the ego instead of the L3 container | C3 |
| `ego-overlay.bash` | what CSB's `just ego-av` sources between Autoware and acb (`EGO_OVERLAY`): the island's overlay and the patched librclcpp | C1 |
| `island_standin.py` | the island's two always-on outputs, for a run with no island | C1 |
| `play_launch.yaml` | the ego's play_launch runtime config: startup pacing, a wedged composable reloaded | C1 |
| `../host_ws/src/tier4_system_launch/config/diagnostics/autoware-carla-l3.yaml` | the merged diagnostic graph: acb's `autoware-carla.yaml` + phase9-C8's timeouts | C1 |

## C1: the CARLA ego on the island's domain

The ego (Autoware 1.5.0 + acb_bridge + acb_agent, CSB's `just ego-av`, i.e.
`acb_launch carla_simulator.launch.xml` under play_launch) runs on
**rmw_zenoh_cpp, domain 10**, through the stock router, with:

- this repo's overlay first for `tier4_system_launch` (Autoware's
  `mrm_handler` and both MRM operators are not started);
- `operation_mode_availability_topic:=/system/operation_mode/availability_raw`,
  so takeover_demo's `availability_gate` publishes the availability the
  island reads (and Autoware's ADAPI too);
- `l3_diagnostic_graph_path:=` the merged `autoware-carla-l3.yaml`.
- play_launch in **observable** container mode (one process per container)
  rather than CSB's isolated (one per composable), `-c play_launch.yaml`,
  `ZENOH_RUNTIME="(net: (worker_threads: 8))"` and the patched librclcpp
  (traps below).

The CSB knobs this uses (`csb:justfile` `ego-av`, all unset by default):
`EGO_ROS_DOMAIN_ID`, `EGO_RMW_IMPLEMENTATION`, `EGO_OVERLAY`,
`EGO_LAUNCH_ARGS`, `EGO_PLAY_LAUNCH_ARGS`, `EGO_CONTAINER_MODE`; `just
scenario`'s readiness check reads the first three, so it finds the ego.

The scenario side (csb bridge, agent relay, SSv2) stays on Cyclone domain 9;
it reaches the ego only through the agent relay (TCP 5560).

### Once

```sh
just l3-host-ws        # the overlay + takeover_demo -> build/l3-host-ws
just carla-rclcpp      # patched librclcpp for the host's rclcpp version -> build/l3-host-rclcpp
# CSB built (its `just build`), Town01 staged under $CSB_DIR/data/carla-autoware-bridge
```

### Run (one terminal each, in order)

```sh
just carla-server      # 1. CARLA 0.9.16 offscreen, Town01 (CARLA_DIR, default ~/carla-0.9.16); RPC up in 1-2 min
just l3-router         # 2. the stock rmw_zenohd, 7447
just carla-sim         # 3. csb bridge + agent relay (Cyclone domain 9, web 8084)
just carla-ego         # 4. the ego; wait for "Startup complete ... composable 125/125"
just carla-takeover    # 5. availability_gate, odd_monitor, takeover_hmi, hazard_relay, graph_watcher
just carla-standin     # 6. ONLY with no island attached (below)
just carla-scenario $CSB_DIR/src/csb_examples/scenarios/basic/town01_ego_drive.xosc
                       # 7. one scenario; junit in $OUTPUT_DIR/scenario_test_runner/result.junit.xml
just l3-nodes          # the domain-10 graph (no mrm_handler / mrm_*_stop_operator)
```

Stop in reverse order (Ctrl-C each); CARLA last. Under zenoh, bound any
`ros2 topic hz` with `timeout -s INT -k 5 <secs>`: it ignores SIGTERM. `carla-ego` refuses to start
without the router. Extra launch arguments for the ego go in
`CARLA_EGO_ARGS="name:=value ..."`.

### Traps found bringing it up (2026-10-14)

1. **The ego needs the island's always-on outputs.** With the overlay, nothing
   on the host publishes `/system/fail_safe/mrm_state` or
   `/system/emergency/control_cmd`. The second is in every mode's subtree of
   the diagnostic graph (`/autoware/system`, acb's `system.yaml` like the
   stock one), so autonomous is never available and the agent waits in
   PLANNING until SSv2 gives up ("waited for the Autoware state to transition
   to WAITING_FOR_ENGAGE ... The current Autoware state is PLANNING"). With
   the island attached the island publishes both; without it, run
   `just carla-standin` (mrm_state NORMAL at 10 Hz, the emergency operator's
   idle pass-through at 30 Hz; it never reacts). Never run it beside an island.
2. **Trap 2b of demo/l3 on the host's rclcpp 16.0.21.** behavior_path_planner
   went silent on the first route ("New uuid route is received. Resetting
   modules.", then no path), every scenario. `just carla-rclcpp` builds the L3
   image's patch over the host's version; `ego-overlay.bash` puts it first on
   `LD_LIBRARY_PATH` for the ego only (checked with `ldd`: both Autoware's
   libraries and play_launch's `component_node` resolve to it) and refuses to
   source without it.
3. **Trap 2c of demo/l3, and the peer mesh.** Without
   `ZENOH_RUNTIME="(net: (worker_threads: 8))"` the first start hung one
   composable (`iv_msgs`, the deprecated API) in its constructor for 7 min
   (`composable 124/125 loaded (1 pending)`). With it, still in CSB's
   isolated mode (~200 processes, each a zenoh peer, gossip-meshed with the
   others), one start wedged `/adapi/node/mrm_request` the same way (all 8 net
   workers and two rx threads in futex waits), and of five starts one had
   behavior_path_planner "waiting for scenario_topic" for the whole run (a
   subscription that never received) and one engaged but did not arrive
   within the scenario's 180 s. `play_launch.yaml` makes play_launch pace the
   start (16 processes at a time) and cancel and reload a composable alive at
   zero CPU after 90 s (it did, once: `lanelet2_map_visualization stalled at
   90s ... cancelled and confirmed gone -- reloading`), and `carla-ego` runs
   observable mode (one process per container): 6 of 6 starts clean, all
   125 composables, no stall. Evidence: the C1 row of the design doc.
4. **`ros2 topic hz` under zenoh ignores SIGTERM**: bound it with
   `timeout -s INT -k 5 <secs>`.
5. **The 62 MB latched `/map/pointcloud_map` is missed.**
   `topic_state_monitor_pointcloud_map` never received it in 3 of 8 starts
   in isolated mode (and in one debug stack; 0 of 6 in observable mode),
   while a late `ros2 topic echo` did; that holds
   `/autoware/map`, and so every mode, in ERROR, with the same PLANNING
   symptom as trap 1. NDT does not read the topic (it loads through the
   differential map loader's service), so `autoware-carla-l3.yaml` drops that
   link from `/autoware/map` and keeps the vector map's; the unit stays
   defined, visible in the graph dump. The mechanism (a startup race or a
   dropped large message under rmw_zenoh) was not established.

## C2: a driver's takeover in acb (`allow_manual`)

acb (CSB's submodule, `9ec6343`) takes `allow_manual:=true` (default
false): `/control/control_mode_request` accepts MANUAL,
`/vehicle/status/control_mode` reports it, Autoware's control command is
no longer applied, and a scripted driver holds the lane at the takeover
speed (pure pursuit on CARLA's lane waypoints) until AUTONOMOUS is asked
for or the next vehicle session starts. `honor_emergency_cmd` (default
false) is a launch argument too: false is what the design called
`emergency_full_brake:=false`, the MRM operator's command through the
pedal maps. By hand: `CARLA_EGO_ARGS="allow_manual:=true" just carla-ego`;
run-board.sh `--sim carla` always passes it.

## C3: an act on the board with CARLA

```sh
# once, as for C1 (just l3-host-ws, just carla-rclcpp, CSB built), and the board image
tools/timeline/run-board.sh --sim carla --elf <zephyr.elf> encore <run-id>
tools/timeline/run-board.sh --sim carla --elf <zephyr.elf> b <run-id>
tools/timeline/run-board.sh --sim carla --elf <zephyr.elf> a <run-id>
```

Nothing else may be up: no CARLA (2000), csb (5560), Traffic Manager
(8000), router or gateway; preflight refuses otherwise. Do not run
`just carla-standin` beside the board. One act takes 8-10 minutes, most
of it CARLA's start (up to 270 s) and the scenario's localization and engage
(60-90 s). The SUMMARY line ends with `sim carla, RTF <r>, SSv2 junit
<v>`; the run directory adds `carla.log`, `csb.log`, `ssv2.log`,
`ssv2/`, `result.junit.xml`, `load.log` and `orphans.txt`. Env knobs are
in the script's header (`RB_XOSC`, `RB_RTF_MIN`, `RB_SSV2_TIMEOUT`,
`RB_PYOCD_TIMEOUT`, `CARLA_HOLD_SECS`, `ENGAGE_SECS`).

### Traps found in C2/C3 (2026-10-14)

6. **A goal the mission planner refuses.** (110.0, -130.3) and (120.0,
   -130.3) on the Town01 straight: "Goal's footprint exceeds lane!", and the
   agent fails `set_route_points` five times. (120.0, -129.8), the goal of
   CSB's `town01_ego_drive`, is accepted.
7. **StandStillCondition never fires for the CARLA ego**: SSv2 counts
   standstill only at a speed of exactly 0. Use `SpeedCondition` below 0.1
   m/s, guarded by a `DistanceCondition` from the start (simulation time
   starts at engage, so a time guard does not exclude the start).
8. **The scenario's end is an HPC loss.** csb pauses the world when a
   scenario ends; the availability converter runs on sim time, the gate
   goes silent 1 s later and the island takes an EMERGENCY_STOP. The
   scenarios end well after the act (b and encore 60 s after the stop, a
   at a goal 195 m away) and run-board stops the probe before it waits for
   the scenario, so that stop is in no act's record.
9. **The trace window opens at arming, a minute before the act.** The
   scenario poses, localizes and engages first; scenario.py re-arms the
   window (`readout.py --rearm-only`, attach, no halt): the encore when
   the ego drives, a and b 4 s before the ODD exit (trap 18).
10. **The agent's localization timeout.** NDT's align took 9.4 s on a
    loaded host and the agent gave up at 8 s five times: acb `b463171`
    waits 30 s.
11. **Host load.** The ego's start drives the 1-min load to 230; other
    users' jobs held it above 35 (with up to 68% I/O wait) for long
    stretches. run-board waits up to 900 s with `--sim carla`; under
    heavy I/O wait `pyocd list` alone can exceed 30 s
    (`RB_PYOCD_TIMEOUT=90`), and one run (load 234) never localized.
12. **A wedged ros2 daemon.** The ros2 CLI starts a daemon (domain 10,
    rmw_zenoh_cpp) that outlives the run; one sent SIGTERM by hand hung
    and the next run's join check (`ros2 topic echo`) never answered.
    Leave it, or kill it with SIGKILL.

## C4: the scenario triggers the act

`run-board.sh --sim carla` (with `RB_TRIGGER=scenario`, the default) lets
the scenario decide when the fault comes, at its place on the road:

- **encore** (`town01_island_encore.xosc`): at x 285 a CustomCommandAction
  with the type `$(env SAI_ACT_TRIGGER true) hpc-loss` runs. SSv2
  fork-execs an unknown type as a command line and `waitpid()`s it, so the
  command must return at once: `act_trigger.py` sends one datagram to the
  act's socket (`build/timeline/<id>/act.sock`) and exits; the act
  (`scenario.py`, `SCENARIO_TRIGGER=scenario`) presses hpc-loss on it. The
  datagram's arrival and the ego's pose are its `trigger` event. Without
  `SAI_ACT_TRIGGER` the action runs `true hpc-loss`, a no-op.
- **a, b** (`town01_island_takeover.xosc`, `town01_island_odd.xosc`): no
  press. run-board starts `odd_monitor` with `scenario_file:=` the act's
  scenario (`<dir>/odd_monitor.log`); the ego leaving the declared polygon
  at x 240 is the ODD exit. The act's start edge is the gate's receipt of
  `/demo/odd/exit` (its `odd` event in `gate.jsonl`): the contract's odd_exit
  detection is the gate's timer and starts there. odd_monitor's own `ODD
  EXIT (...)` line and its hop to the gate are in the SUMMARY:
  `trigger ODD EXIT segment (239.9, -129.4) outside the ODD polygon,
  odd_monitor -> gate 0.33 ms`.

Several acts on one boot, as phase9-W2 (the booth):

```sh
scripts/ienv.sh 'tools/timeline/run-board.sh --sim carla --keep-link --elf <elf> encore <id1>'
scripts/ienv.sh 'tools/timeline/run-board.sh --sim carla --keep-boot --keep-link --elf <elf> a <id2>'
scripts/ienv.sh 'tools/timeline/run-board.sh --sim carla --keep-boot --elf <elf> b <id3>'
```

Each act still starts its own CARLA, scenario side and ego; only the
island's boot and link are kept. `RB_TRIGGER=button` is C3's way (the act
presses the button itself, after `DRIVE_SECS`).

### Traps found in C4 (2026-10-14)

13. **SSv2 does not send `Performance maxSpeed` to Autoware.** The velocity
    limit SSv2 sets through `/api/autoware/set/velocity_limit` is the
    Controller's `Property maxSpeed` (`simulator_core.hpp`
    `applyAssignControllerAction`); without it SSv2 sends DBL_MAX. The
    scenarios declare `<Property name="maxSpeed" value="7.0"/>`; the act
    reads `max_velocity_default` 7.00 and the selector's `max_velocity`
    4.17: Autoware's own `max_vel` (4.17 m/s, autoware_launch
    common.param.yaml) caps the cruise, so the ego drives at 4.1 m/s.
14. **A re-arm that never exits holds the probe.** c4-e1: the act's
    re-arm (`readout.py --rearm-only`, attach, no halt) wrote the word, the
    window counted it, and the process never exited under a 1-min load of
    54; `subprocess.run`'s timeout killed the shell only, and the readout
    after the act failed with `USBError: [Errno 16] Resource busy`. The
    re-arm now runs in its own session and is killed whole after
    `SCENARIO_REARM_TIMEOUT` (60 s); `--keep-boot`'s re-arm is bounded at
    90 s.
15. **The act can see `/demo/odd/exit` before the gate does.** c4-b1: the
    act's sample arrived 1 ms before the gate logged its receipt, and a
    filter "the gate's flip before the act saw it" found nothing. The act
    takes the gate's first flip to true of the run.

## C5: the booth image (LEDs on)

```sh
just board-build-booth     # snippet island-booth (CONFIG_ISLAND_LED=y) -> build-board-booth
tools/timeline/run-board.sh --sim carla --elf build-board-booth/zephyr/zephyr.elf <act> <id>
python3 tools/timeline/led_readout.py --elf build-board-booth/zephyr/zephyr.elf > build/timeline/<id>/led.txt
python3 tools/timeline/led_vs_trace.py build/timeline/<id>
```

The gate image (`just board-build`, build-board) has no LED code; the booth
image adds the snippet `src/zephyr_entry/snippets/island-booth` and nothing
else (FLASH +744 B, DTCM +88 B, ITCM +32 B, SRAM 0; design 3.3). The RGB LED
follows design 3.2 (green NORMAL, amber blinking takeover requested, amber
COMFORTABLE_STOP, red blinking EMERGENCY_STOP, red stopped), CAN LED0 is the
handler's 1 Hz heartbeat. `led_readout.py` reads the LED record (the last 8
transitions with the island's uptime) and the pins over SWD, attach, no
halt; read it right after the act, before the next one adds transitions.
`led_vs_trace.py` matches every mrm_state and takeover-request edge of the
act's trace (island clock) with an LED transition and passes when each is
within one handler tick (100 ms).

## C6: the board's buttons (SW1 take over, SW2 HPC loss)

The booth image (`just board-build-booth`) records the board's two user
buttons (`CONFIG_ISLAND_BUTTONS`, `src/zephyr_entry/src/island_buttons.c`;
design 3.4): SW1 is the driver's takeover, accepted only while the
island's takeover request is on (amber blinking); SW2 is the encore's HPC
loss, accepted while the MRM state is NORMAL (green). Hold a button about
half a second: the island reads it once per 100 ms tick and wants two
ticks in a row. The island does not act on a press; the act reads it over
SWD and does what its own buttons did (MANUAL from the vehicle, SIGSTOP of
the availability gate). A demo affordance, not a safety function.

A visitor's act, with the operator starting the rest:

```sh
RB_TRIGGER=board tools/timeline/run-board.sh --sim carla --elf build-board-booth/zephyr/zephyr.elf a <id>
RB_TRIGGER=board tools/timeline/run-board.sh --sim carla --elf build-board-booth/zephyr/zephyr.elf encore <id>
```

- **a**: the ego leaves the scenario's ODD by itself (odd_monitor, as in
  C4) and the LED blinks amber; the visitor presses SW1 within the 10 s
  window and the car is the driver's (MANUAL). No press: the island stops
  the car, which is act b and a FAIL for a.
- **encore**: the visitor presses SW2 while the car drives (LED green);
  the island loses the availability stream and stops the car (red).
- b has no button (`RB_TRIGGER=board` refuses it); run it with the
  default trigger.

The re-arm helper (`readout.py --rearm-only --buttons`) stays attached as
the button bridge for the act, so the probe is busy during it. The SUMMARY
reads `trigger board SW1 (pressed, island uptime <ms> ms, seen -> MANUAL
request <ms> ms) after ODD EXIT ...` for a and `trigger board SW2 (...) at
(<x>, <y>)` for the encore.

With nobody at the board (the gate), `RB_BUTTON_INJECT=1` makes the act
press through the firmware: it writes the record's inject word, the button
reads pressed for 3 ticks (OR'ed with the pin), and the debounce, the edge,
the state check and the record are the real path. SW1 is injected
`RESPOND_AFTER` (3) s into the takeover request, SW2 when the encore
scenario reaches x 285 (its C4 place). The SUMMARY then says `injected`
instead of `pressed`.

### On site: check the buttons (no reflash)

With the booth image running on the board (any state; no act running,
the check needs the probe):

```sh
just board-buttons          # Ctrl-C to stop
```

It prints every pad edge read straight from the SIUL2 input registers
(`pad SW1 DOWN` / `up`): that is the check of the buttons themselves, and
it needs nothing but the image running. With the island's link up (the
handler ticks only once the island has joined; `just l3-router` and `just
l3-peer`, or between acts of a `--keep-link` chain) it also prints the
island's debounced level (`island SW1 down`) and each press the island
records, with accepted/ignored and its state, e.g. `island press SW2
ignored (not NORMAL) ... state=MRM_OPERATING/EMERGENCY_STOP` (with no
Autoware the island sits in its init-timeout stop, so both buttons read
ignored). `python3 tools/timeline/board_buttons.py inject sw1 --elf <elf>`
presses through the firmware without a finger, to tell a dead pad from a
dead firmware path.

### Traps found in C6 (2026-10-15)

19. **fuser hangs behind a filesystem walk.** A `find /` that had walked
    into the sshfs NAS held about 1,900 directory fds there; fuser stat()s
    every open file of every process, and on the gateway tty it ran over
    10 minutes, so `just l3-peer` (and run-board's preflight) refused.
    `scripts/tty-holders.sh` finds the tty's holders with readlink on
    /proc/<pid>/fd only (0.03 s with the walk running); l3-peer,
    board-peer and run-board use it.
20. **A press must last about 200 ms.** The island reads the buttons once
    per 100 ms tick and wants two ticks in a row; a tap shorter than a
    tick can be missed. Hold each button for half a second.

## C8: the proof cast (re-recording it)

```sh
just carla-cast-display        # once: TurboVNC :3, 1920x1080, no desktop (removes a stale ~/.vnc pid file)
just carla-cast --no-flash --elf <booth or gate elf> b cast-b<N>   # one act, recorded
just carla-cast --no-flash --elf <elf> a cast-a<N>
/opt/TurboVNC/bin/vncserver -kill :3                             # when done
```

`carla-cast` runs `demo/carla/cast.sh` under `scripts/ienv.sh`. It starts
`tools/timeline/run-board.sh --sim carla` with the arguments given, the
dashboard (`cast_dashboard.py`) on the display at run-board's step 6, and
`ffmpeg -f x11grab` from step 7 (the scenario starts) to `CAST_TAIL` (8) s
after step 8 (the readout). Everything else is the act as always: same
preflight, same record in `build/timeline/<id>/`, same SUMMARY. Out, in
`CAST_DIR` (default `build/casts`): `<id>.mp4` (h264_nvenc, 30 fps;
`CAST_CODEC=libx264` without the GPU encoder), `<id>.events.jsonl` (each
transition the dashboard saw, wall and sim time), `<id>.meta`, and a still
per transition the act is about (`<id>-NN-odd-exit.png`, `-takeover-request`,
`-mrm-operating`, `-standstill`, `-mrm-succeeded`, `-manual`), cut
`CAST_STILL_AFTER` (1.0) s after it. With a booth image it also writes
`led.txt` and `led_vs_trace.md` into the run directory.

The dashboard alone, e.g. to check the layout: `DISPLAY=:3 python3
demo/carla/cast_dashboard.py --no-ros --no-camera`. Its chase view is a
camera the dashboard attaches to the CARLA vehicle whose role_name is
`hero`; it is destroyed when the dashboard exits.

- `CAST_DISPLAY` refuses `:1`, `:2` and `:9` (the user's desktops and
  another user's). Nothing else may draw on the cast's display.
- During the island's MRM, the takeover panel's operation mode and
  control mode still read AUTONOMOUS (Autoware's modes; the island acts
  below them), and the panel says so in one line: "island MRM overrides
  control; Autoware's modes stay AUTONOMOUS".
- The LED on screen is mirrored from `/system/fail_safe/mrm_state` and
  the takeover request with design 3.2's mapping; the board's own LED is
  checked against the trace by `led_vs_trace.py`, not filmed.
- A take is an act: under a high host load it waits or is refused like
  any run (traps 11 and 16), and a take whose act did not run (no verdict)
  has no stills worth keeping; record it again.

### Traps found in C5/C8 (2026-10-14)

16. **Other jobs on the host stall the whole run.** c5-e1: no load.log
    sample for 44 s at 60% I/O wait; the act read RTF 0.098 and the
    SUMMARY said INVALID, as it should. c5-b1, cast-b2: at a 1-min load of
    220-290 Autoware never left INITIALIZING and the ego never drove; c5-e2:
    SSv2 "The simulator reported a failed frame". None is the island's;
    wait for the load (the cast recipes can be started behind `until awk
    '{exit !($1 < 25)}' /proc/loadavg; do sleep 30; done`).
17. **odd_monitor's log line can block.** c5-b2: 572 ms between the `ODD
    EXIT` stamp and the line, on a loaded disk; the exit was published
    after it. odd_monitor now publishes first. The act's start edge, the
    gate's receipt, did not move.
18. **A/b's trace window from the first drive nearly filled.** c5-b2 used
    50,410 of 53,248 B over 74.9 s (first drive to readout). scenario.py
    now re-arms a and b at `SCENARIO_REARM_LEAD_S` (4.0) s before the ego,
    at its speed and heading, reaches the edge of the scenario's ODD
    polygon (`SCENARIO_ODD_FILE`, set by run-board to the act's `.xosc`):
    tm-b2 21,256 B over 29.5 s, tm-a2 19,936 B over 27.8 s. The re-arm is
    split because pyocd's start-up is slow and unbounded under load
    (tm-b1: nothing from it in 22 s): `readout.py --rearm-only --wait-go`
    starts with the act, attaches, prints `re-arm ready`, and writes the
    word when the act sends `go` (65-108 ms to the acknowledgement). An
    acknowledgement after the start edge, or none, ends the act FATAL;
    the SUMMARY reads `trace <used> of <buffer> B over <s> s, re-armed <s>
    s before the ODD exit (go -> ack <ms> ms)`. The encore keeps the
    first-drive re-arm (its fault is the trigger itself; 20 s, 12 KB).
