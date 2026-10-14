# demo/carla - the island demo on CARLA

Design and plan: `docs/design/carla-island-demo.md` (units C1-C7). Recipes:
`just/carla.just`. The CARLA side is carla-scenario-bridge (CSB,
`NEWSLabNTU/carla-scenario-bridge`, default checkout
`/mnt/evo/aeon/repos/carla-scenario-bridge`, override with `CSB_DIR`) and its
submodule autoware_carla_bridge (acb).

| path | what | unit |
|---|---|---|
| `scenarios/town01_island_odd.xosc` | acts b and encore: the Town01 straight, the ODD declared in the file (design 2.5, read by odd_monitor from C4), success 60 s after the stop | C3, C4 |
| `scenarios/town01_island_takeover.xosc` | act a: the same road, success at the route's goal under the driver | C3 |
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
   window when the ego drives (`readout.py --rearm-only`, attach, no halt).
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
