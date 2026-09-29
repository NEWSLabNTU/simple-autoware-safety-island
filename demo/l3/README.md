# demo/l3 - the RTSS@Work 2026 takeover demo, HPC side (phase 8)

Design: `docs/roadmap/phase-8-rtss-work-demo.md` (D2, D3, D5). Recipes:
`just/l3-demo.just`. Everything here was measured on the demo host on
2026-09-28; output quoted below is verbatim.

| path | what | unit |
|---|---|---|
| `container/` | the Autoware 1.5.0 image (Dockerfile, entrypoint, `run.sh`, the `l3-*` scripts it carries) | W3 |
| `takeover_demo/` | the host-side ROS 2 package (ament_python) and its launch contract | W3 |
| `router/` | the island gateway router (`just l3-peer`) | W2 |
| `contracts/` | the demo contract with the four new keys | W6 |

## Run it

One domain (10), one stock `rmw_zenohd` on the host (7447). Autoware runs in
the container on the host network and dials it; the island reaches it through
the gateway router (W2, `just l3-peer`, on the host). RViz runs on the host.

```sh
just l3-container                 # build the image (once; layers cached)
just l3-router                    # terminal 1: the stock router, 7447
just l3-autoware                  # terminal 2: Autoware in the container
just l3-takeover                  # terminal 3: the takeover nodes, same container
just l3-peer                      # terminal 4: the island gateway (W2), then reset the board
just l3-run hpc                   # one act: drive | hpc | odd | odd-respond
just l3-nodes                     # ros2 node list, domain 10, over zenoh
just l3-rviz                      # RViz on the host
just l3-button                    # the booth keyboard (run l3-takeover driver_button:=false)
```

`where=host` on `l3-autoware`, `l3-takeover`, `l3-button`, `l3-run` runs the
same scripts on the host under `env -i` (build the host copy of the overlay
first: `just l3-host-ws`). `just l3-island-qemu <elf> <port> <secs> <host>`
boots a QEMU island image into a router on the host. `just l3-check` is the CI
job.

Order matters (see "Traps"): the island joins BEFORE Autoware is engaged.
A healthy start prints `Startup complete ... composable 68/68` about 4 s
after `Registered 112 members`; if it does not within a minute, Ctrl-C it,
wait 10 s (the zenoh lease) and start it again, and see trap 2.

A second router on one host (a rehearsal beside the booth): `just
l3-router 7461` and `L3_ROUTER_PORT=7461
ZENOH_CONFIG_OVERRIDE='connect/endpoints=["tcp/localhost:7461"]' just
l3-autoware` (`run.sh` passes both through), with another `ROS_DOMAIN_ID`.

## The container (`container/`)

`ros:humble-ros-base-jammy`, then, following autosdv's desktop image
(NEWSLabNTU/autosdv@6e7b709 `docker/desktop/`,
`setup/scripts/install-autoware-debian.sh`):

- the localrepo `.deb` (1.85 GiB, sha256 `f8e2d1d2...`) fetched by `aria2c -x 10
  -s 10` into a BuildKit cache mount, installed, and the pool purged in the
  same RUN; `autoware-ros-packages-1-5-0` + `autoware-config-1-5-0` +
  `autoware-theme-1-5-0` (autoware-full minus the 1.79 GB `autoware-data`);
- an equivs stub that Provides `libnvinfer10`, `libnvinfer-plugin10`,
  `libnvonnxparsers10` (no CUDA, no TensorRT);
- `ros-humble-rmw-zenoh-cpp=0.1.10-1jammy.20260915.210859` and
  `ros-humble-zenoh-cpp-vendor=0.1.10-1jammy.20260915.201617` from ROS apt
  **testing**, held (W11, trap 2a: 0.1.9 loses wakeups; main still serves
  0.1.9 on 2026-09-29; the host runs rmw_zenoh_cpp
  `0.1.9-1jammy.20260723.022609` and its router is unaffected);
- `librclcpp.so` rebuilt from rclcpp 16.0.19 (the packaged version) with
  `container/patches/rclcpp-16.0.19-executor-keep-group-guard-conditions.patch`,
  diverted over the packaged one (W11, trap 2b);
- `ZENOH_RUNTIME="(net: (worker_threads: 8))"` in the image ENV: zenoh's
  Net runtime gets 8 workers instead of 1 (W11, trap 2c);
- `play_launch==0.12.0` from the package index;
- the `demo/host_ws` overlay and `takeover_demo`, colcon-built to
  `/opt/demo_ws/install`; the sample map at `/opt/demo/map`;
- `RMW_IMPLEMENTATION=rmw_zenoh_cpp`, `ROS_DOMAIN_ID=10` in the image ENV;
  `autoware-env.bash` is never sourced (it forces Cyclone).

Permissions, as autosdv: a user `aw` created at uid 1000 and bent by the
entrypoint to `HOST_UID`/`HOST_GID`, in `dialout`, `video`, `plugdev` (their
gids taken from the host), passwordless sudo, `gosu` to drop root. `run.sh`
passes `--network host --shm-size 2g --init` and, for the gate (W24),
`--cap-add SYS_NICE --ulimit rtprio=20 --ulimit memlock=-1`: SCHED_FIFO 20
for the unprivileged user comes from the rtprio limit (gosu drops the
capability, the limit survives), and `mlockall` fails with ENOMEM under
Docker's 64 KiB memlock default (W16); `GATE_RTPRIO=0` runs the gate
SCHED_OTHER; `L3_SERIAL=/dev/serial/by-id/...`
passes a serial device by id (default none: W2's router owns the board's
port on the host); `L3_X=1` mounts the host X socket (and `/dev/dri`) for
RViz inside; `L3_DEBUG=1` adds SYS_PTRACE for gdb.

Measured:

```
l3-container: sai-l3-autoware:1.5.0 in 5 s, 5.29 GB          (layers cached)
#10 244.5 localrepo: installed 456 packages suffixed -1-5-0
BUILD rc=0 elapsed=283 s                                      (heavy stage, .deb cached)
#10 0.220 localrepo: downloading https://github.com/NEWSLabNTU/autoware-localrepo/releases/download/1.5.0-2/...
#10 179.8 Fetched 52.3 MB in 9s (5528 kB/s)                   (the .deb itself took ~180 s)
```

So a cold build is about 180 s of download plus 283 s of install, 7.7 min
(summed from two builds, not one end to end); a change to the overlay or the
takeover package rebuilds in 5-40 s. Image 5.29 GB. Autoware in the container
(stock component containers): 57 processes, 3.0 GiB RSS.

RViz. The lowest-risk option is RViz on the host over zenoh (`just l3-rviz`);
the image also carries it (`L3_X=1`). Measured side by side on one private
Xvfb display (software GL, 2813x1565 window, `autoware.rviz` with the point
cloud map, RViz's own frame-rate readout, three readings each, host load ~20):

| where | fps | CPU |
|---|---|---|
| host, over zenoh (`just l3-rviz`) | 7, 7, 7 | 264 % |
| container, X socket (`L3_X=1`) | 6, 6, 6 | 261 % |

`just l3-rviz` passes `sample_vehicle_description`'s `vehicle_info.param.yaml`:
without it the config fails ("Statically typed parameter 'wheel_radius' must
be initialized").

## The takeover package (`takeover_demo/`)

`launch/takeover.launch.xml` with its sidecar contract
`launch/takeover.contract.yaml` (nodes, endpoints, rates, services; `play_launch
check` clean). All nodes are rclpy on rmw_zenoh_cpp, domain 10, except the
gate: since phase8-W24 the launch file starts W16's C++ `availability_gate`
(package `demo/host_ws/src/availability_gate`, through its `gate-rt`
wrapper) in place of W3's rclpy one, which is deleted.

| node | subscribes | publishes / serves |
|---|---|---|
| `odd_monitor` | `/localization/kinematic_state`, `/demo/odd/inject` | `/demo/odd/exit` (Bool, 10 Hz), `/demo/odd/reason` (String, 10 Hz); `~/inject_exit`, `~/clear` (Trigger). 30 km/h bound, optional `segment_polygon`; an exit latches |
| `availability_gate` (C++, W16/W24) | `/system/operation_mode/availability_raw`, `/demo/odd/exit` | `/system/operation_mode/availability` with `autonomous &= !odd_exit`, from a 10 Hz wall timer: the latest raw sample while it is younger than 1 s, nothing once it is older; `odd_timeout_s: 1.0`, so an ODD monitor silent for 1 s (or never heard) counts as an exit, W3's rule. No file-system call on the executor thread, `mlockall`, SCHED_FIFO 20 through `gate-rt`; SIGSTOP silences every thread (the HPC-loss act). `scenario hpc` finds it by its installed path (`lib/availability_gate/availability_gate`) |
| `takeover_hmi` | `/demo/odd/exit`, `/api/operation_mode/state` (TL), `/vehicle/status/control_mode`, `/system/fail_safe/mrm_state`, `/demo/driver/response` | `/demo/takeover/state` (String), `/demo/takeover/remaining` (Float32), 10 Hz; client `/control/control_mode_request` (MANUAL, the simulator's) |
| `driver_button` | keyboard when stdin is a tty | `/demo/driver/response` (Empty), `/demo/odd/inject` (Bool); `~/take_over`, `~/odd_exit`, `~/odd_clear` (Trigger) |
| `hazard_relay` | `/system/fail_safe/mrm_state`, `/system/emergency/hazard_lights_cmd` | `/system/hazard_lights_cmd` (10 Hz): the island's hazard command in COMFORTABLE_STOP, DISABLE otherwise |
| `graph_watcher` | the graph cache | `JOIN`/`LEAVE` per island node, `/demo/graph/event` (String) |
| `scenario` (not launched) | | the acts: `drive`, `hpc`, `odd`, `odd-respond` |

The overlay (`demo/host_ws/src/tier4_system_launch/launch/system.launch.xml`)
gained an argument `operation_mode_availability_topic` (default the stock
name, so `just autoware` is unchanged; `l3-autoware` passes
`.../availability_raw`) by inlining the aggregator's two nodes, whose stock
launch file hard-codes the remap. It also inlines `hazard_status_converter`
to read `/system/fail_safe/emergency_holding`, the island's name (gap G10);
the other half of G10, `/system/stop_mode/*` with no reader, goes away with
`stop_mode_operator` (D4) and needs nothing on the host.

VERIFIED, `vehicle_cmd_gate.cpp` `onMrmState` in 1.5.0: the gate takes the
island's `/system/emergency/*` commands only while `mrm_state.state` is
MRM_OPERATING, MRM_SUCCEEDED or MRM_FAILED **and** `behavior ==
EMERGENCY_STOP`. In a COMFORTABLE_STOP the planner's commands pass, and the
planner's hazard lights come from `autoware_hazard_lights_selector`, which ORs
its system input `/system/hazard_lights_cmd` in and keeps its last sample
forever; hence the relay, and hence the relay never falls silent. Wiring
measured: `/system/hazard_lights_cmd 10.0 Hz, commands seen [1]`, subscribers
`autoware_hazard_lights_selector`. The comfortable-stop branch itself has not
run (the island's `use_comfortable_stop` is false).

## Measured, 2026-09-28

### Step 1: the host, no container

`env -i`, ROS sourced fresh, host overlay `build/l3-host-ws`, stock
`rmw_zenohd` on 7447:

```
l3-autoware: /home/aeon/.local/bin/play_launch (play_launch 0.12.0), RMW rmw_zenoh_cpp, domain 10
l3-autoware: tier4_system_launch from build/l3-host-ws/install, availability converter -> /system/operation_mode/availability_raw
2026-09-28T10:59:20.129553Z  INFO Startup complete: all nodes ready (nodes 32/32, containers 13/13, composable 68/68)
```

It starts (32 nodes, 13 containers, 68 composables; 49 processes, 3.2 GiB
RSS); `ros2 node list` reads 136 nodes with the six takeover nodes and no
island. An engaged drive on the sample map works: with a stand-in for the
island's two always-on outputs the planner chain runs at 10 Hz, engage
succeeds on the second attempt and the vehicle cruises at 4.17 m/s and stops
at the stop line as on Cyclone. No island image joins on the host path: the
native_sim image is Cyclone only (`CONFIG_NROS_RMW_CYCLONEDDS=y` in
build-zephyr); a zenoh native_sim needs its own entry package with its own
`system.toml` (nano-ros checks `rmw` per entry) and was not made. The zenoh
island here is the QEMU mps2/an385 image (zenoh over the LAN9118, TCP).

### Step 2: the container, with the island in the loop

The island is the current tree built for QEMU with a 1 MiB heap
(`CONFIG_NROS_ZEPHYR_HEAP_SIZE=1048576 just QEMU_BUILD_DIR=build-qemu-w3
qemu-build`, parameter services off per W1), behind a copy of W2's gateway
config whose island face was moved from the serial link to a TCP listener
(`access_control/subjects=[{id:"island-serial",interfaces:["docker0"]}]`).

```
[graph_watcher-6] JOIN  /mrm_emergency_stop_operator           wall=1790598219.301 mono=4585226.286
[graph_watcher-6] JOIN  /mrm_comfortable_stop_operator         wall=1790598219.401 mono=4585226.386
[graph_watcher-6] JOIN  /mrm_handler                           wall=1790598219.401 mono=4585226.386
[graph_watcher-6] JOIN  /stop_mode_operator                    wall=1790598219.401 mono=4585226.386
== ros2 node list (RMW rmw_zenoh_cpp, domain 10) 2026-09-28T20:02:36+08:00 ==
(140 nodes; among them)
/availability_gate
/control/vehicle_cmd_gate
/driver_button
/graph_watcher
/hazard_relay
/mrm_comfortable_stop_operator
/mrm_emergency_stop_operator
/mrm_handler
/odd_monitor
/planning/scenario_planning/lane_driving/behavior_planning/behavior_path_planner
/simulation/simple_planning_simulator
/stop_mode_operator
/system/converter
/takeover_hmi
```

The gate (W3's): an engaged drive with the island in the loop, stock MRM off:

```
== 4b. driving 15 s ==
velocity 4.12 m/s, mrm_state NORMAL, control_mode AUTONOMOUS, availability samples so far 395
VERDICT: PASS drive: v 4.12 -> 1.56 m/s, availability 10.0 Hz, mrm NORMAL
/system/fail_safe/mrm_state                      10.0 Hz  max gap    118.9 ms  n=100
/system/emergency/control_cmd                    30.1 Hz  max gap     68.3 ms  n=301
/system/operation_mode/availability              10.0 Hz  max gap    109.7 ms  n=100
```

`vehicle_cmd_gate`'s 0.5 s heartbeat holds: the island's `mrm_state` at
10.0 Hz with a largest gap of 118.9 ms, and zero "system_emergency heartbeat
is timeout" lines in the run.

HPC loss (SIGSTOP of `availability_gate`):

```
== 5. HPC loss: SIGSTOP the availability gate (pids [2185]) ==
  +  0.000 s  SIGSTOP availability_gate  v=3.36 m/s
  +  0.559 s  mrm_state MRM_OPERATING/EMERGENCY_STOP  v=3.16 m/s
== 6. SIGCONT the gate ==
  + 16.568 s  SIGCONT availability_gate
  + 21.907 s  mrm_state NORMAL/NONE  v=4.18 m/s
VERDICT: FAIL hpc: MRM_OPERATING seen 638 ms after the last availability sample, v 3.36 -> 3.78 m/s, standstill 15.57 s after SIGSTOP, recovered to NORMAL: True
```

The island detects and announces within 0.64 s of the last sample, and the
gate switches to its emergency commands, but the car does not stop: the
handler's `operate` request never reaches the operator in the same image (the
operator's status stays AVAILABLE, its command frozen at 4.17 m/s; a probe
over 4 s of a second stop). That is gap G5 (`Z_FEATURE_LOCAL_QUERYABLE`,
unit W5), exactly as brief B found it on the board.

ODD exit, the driver responding after 2 s, and nobody responding (today's
handler reacts to `availability.autonomous == false` at once; the 10 s rung
is W7's):

```
== 5. ODD exit (the presenter's button) ==
  +  0.004 s  ODD exit injected (inject)  v=4.21 m/s
  +  0.141 s  takeover TOR_ACTIVE
  +  0.184 s  mrm_state MRM_OPERATING/EMERGENCY_STOP  v=4.20 m/s
  +  2.027 s  driver response (TAKE OVER)
  +  2.049 s  control_mode MANUAL
  +  2.099 s  mrm_state MRM_SUCCEEDED/EMERGENCY_STOP  v=0.00 m/s
  +  2.140 s  takeover DRIVER_TOOK_OVER

== 5. ODD exit (the presenter's button) ==
  +  0.003 s  ODD exit injected (inject)  v=4.21 m/s
  +  0.140 s  takeover TOR_ACTIVE
  +  0.193 s  mrm_state MRM_OPERATING/EMERGENCY_STOP  v=4.20 m/s
  + 10.140 s  takeover TOR_EXPIRED
```

(Those two runs printed their VERDICT lines with an earlier format; the
second one's "-1204 ms" counted an MRM from before the exit, since fixed.)
The simulator's MANUAL mode with no manual command drops the speed to 0 at
once.

## Start flake and silent planner (W11, 2026-09-29)

Method: a private `rmw_zenohd` on 7461 and domain 61 (other units share
the host), every start under `flock /tmp/claude-1000005/sai-demo.lock`,
begun when the 1-min load was below 35 (or after 10 min of waiting). A start
counts when play_launch prints `Startup complete` with n/n containers and
composables within the timeout (300 s for the first three, then 120 s; a
healthy start takes 4-7 s). A hung start was dumped with gdb inside the
container (`docker exec --privileged`, the matching `-dbgsym`).

| image / path | rmw_zenoh_cpp | rclcpp | zenoh Net workers | starts complete | load at start |
|---|---|---|---|---|---|
| `1.5.0` (W3) + gdb | 0.1.9 | 16.0.19 | 1 | 3 of 10 | 13.8-34.1 |
| host, `where=host` | 0.1.9 | 16.0.19 | 1 | 7 of 8 | 33.1-55.1 |
| rmw_zenoh_cpp from testing | 0.1.10 | 16.0.19 | 1 | 19 of 20 | 21.8-44.8 |
| + the rclcpp patch | 0.1.10 | patched | 1 | 18 of 20 | 16.2-34.2 |
| + client mode instead of 8 workers | 0.1.10 | patched | (client) | 20 of 20 | 21.7-34.7 |
| **the image now** | 0.1.10 | patched | 8 | **40 of 40** | 18.9-41.3 |

The gate on the image now, first and last lines verbatim:

```
start 1: COMPLETE t=4.1s load_at_start=25.71 load_at_end=25.01 | 2026-09-29T02:15:22.808942Z  INFO Startup complete: all nodes ready (nodes 31/31, containers 13/13, composable 68/68)
start 40: COMPLETE t=4.2s load_at_start=33.68 load_at_end=34.11 | 2026-09-29T02:40:56.697730Z  INFO Startup complete: all nodes ready (nodes 31/31, containers 13/13, composable 68/68)
```

Then one more start and four routed drives in it (`REROUTE=1` each: the
last three are re-routes, each resetting behavior_path_planner's modules),
the island's two outputs from a stand-in, rates over 75 s from the start of
each act. Rows: `path_with_lane_id`, `lane_driving/trajectory`,
`/planning/trajectory`, `/control/command/control_cmd`:

```
start d: COMPLETE t=4.2s load_at_start=32.88 load_at_end=32.88 | 2026-09-29T02:41:17.876604Z  INFO Startup complete: all nodes ready (nodes 31/31, containers 13/13, composable 68/68)
== route 4 load=28.82
scenario rc=0: VERDICT: PASS drive: v 3.72 -> 1.79 m/s, availability 10.0 Hz, mrm NORMAL
path_with_lane_id   10.0 Hz from first msg (+  0.0 s)  n= 750  max gap    117.1 ms  silent at end     77.9 ms
trajectory          10.0 Hz from first msg (+  0.0 s)  n= 750  max gap    155.7 ms  silent at end     49.6 ms
trajectory          10.0 Hz from first msg (+  0.0 s)  n= 749  max gap    201.7 ms  silent at end     47.5 ms
control_cmd         33.3 Hz from first msg (+  0.0 s)  n=2501  max gap     58.9 ms  silent at end     -8.2 ms
```

All four routes PASS, `path_with_lane_id` at 10.0 Hz with a largest gap
of 117-130 ms. Before the rclcpp patch the first or second re-route
silenced the planner in 3 of 3 runs (3 of 4 module resets), with and
without play_launch's interception (`--interception off`); with it, 7 of 7
re-routes in one run and 3 of 3 here kept it at 10 Hz.

## The C++ gate in the container (W24, 2026-09-29)

`takeover.launch.xml` starts W16's C++ gate through `gate-rt`
(`odd_timeout_s: 1.0`); `run.sh` gives the container `--cap-add SYS_NICE
--ulimit rtprio=20 --ulimit memlock=-1`. Image `sai-l3-autoware:1.5.0-w24`
(the Dockerfile unchanged: the local `ros:humble-ros-base-jammy` is already
W21's digest `sha256:1813d3c8...`, so every Autoware layer came from cache and
the rclcpp 16.0.19 check passed). Same method as W11: a private
`rmw_zenohd` (keep_alive 6, `experiments/serial-interop/router-serial.json5`)
on 7484, every Autoware start under `flock /tmp/claude-1000005/sai-demo.lock`,
a start counted when play_launch prints `Startup complete` with n/n
containers and composables.

Starts: 10 of 10 on the final image (load 13.5-28.8; 3-4 s each), and 10 of
10 plus one on the image one scenario.py edit earlier. Four of the 21 read
`nodes 30/31`: `logging_diag_graph` "Exited without code", trap 13. In every
start the takeover launch came up and the gate ran SCHED_FIFO 20 with
`mlockall MCL_CURRENT|MCL_FUTURE`, as root (`docker exec`, what `just
l3-takeover` does) on odd starts and as the image user `aw` on even ones:

```
[gate-rt-2] gate: /system/operation_mode/availability_raw -> /system/operation_mode/availability (pid 2058), log -, SCHED_FIFO 20, mlockall MCL_CURRENT|MCL_FUTURE, count /dev/shm/sai-availability-gate-2058.count
pid 1993's current scheduling policy: SCHED_FIFO          (chrt -p; user aw)
pid 1993's current scheduling priority: 20
policy                                       :                    1
prio                                         :                   79
VmLck:	 1811072 kB
VmRSS:	  137440 kB
limits: Max locked memory unlimited unlimited bytes
Max realtime priority 20 20
```

Every thread of the gate inherits the class (21-36 threads `FF 20`, zenoh's
`net-*`, `rx-*`, `tx-0` among them). VmLck counts the locked mappings,
1,278,040-2,292,088 kB, most of it not resident (VmRSS
126,192-166,008 kB).

The acts, one start, the QEMU island (the island sources at f7c9369, main
when W24 began; W15's lease and W25's trim landed later; domain 10, heap 102,400; `w15-ctl/build-qemu-m10`, sha256 `2560fe38be6a`)
joined before the first engage, `l3-scenario` for each:

```
VERDICT: PASS drive: v 2.97 -> 4.12 m/s, availability 10.0 Hz, mrm NORMAL          (initial pose, goal, route SET, engage)
  +  0.072 s  takeover TOR_ACTIVE
  +  2.024 s  driver response (TAKE OVER)
  +  2.044 s  control_mode MANUAL
  +  2.072 s  takeover DRIVER_TOOK_OVER
VERDICT: PASS odd-respond: island MRM_OPERATING never after the exit; takeover state DRIVER_TOOK_OVER; control_mode MANUAL; v 2.72 -> 0.00 m/s
  +  0.054 s  takeover TOR_ACTIVE
  + 10.153 s  takeover TOR_EXPIRED
  + 10.237 s  mrm_state MRM_OPERATING/COMFORTABLE_STOP  v=2.69 m/s
VERDICT: PASS odd: island MRM_OPERATING 10237 ms after the exit; takeover state TOR_EXPIRED; control_mode AUTONOMOUS; v 4.17 -> 0.21 m/s
== 5. HPC loss: SIGSTOP the availability gate (pids [2297]) ==
  +  0.566 s  mrm_state MRM_OPERATING/EMERGENCY_STOP  v=4.17 m/s
  +  3.362 s  mrm_state MRM_SUCCEEDED/EMERGENCY_STOP  v=0.00 m/s
  +  4.314 s  SIGCONT availability_gate
  +  4.399 s  mrm_state NORMAL/NONE  v=0.00 m/s
VERDICT: PASS hpc: MRM_OPERATING seen 644 ms after the last availability sample, v 4.17 -> 0.04 m/s, standstill 3.31 s after SIGSTOP, recovered to NORMAL: True
probe: n=211 span=25.3 s rate=8.30 Hz max_gap=4400.07 ms (at mono 4671160.661 s) gaps>150ms=1 >250ms=1 >500ms=1 ...
gate: stats: 1439 samples, largest publish gap 101.876 ms, 0 gaps over 150.000 ms, largest tick gap 101.874 ms, largest raw gap 108.871 ms (SIGCONT resumes excluded: 1)
```

The probe is a TEST-ONLY C++ subscriber in the container around the hpc
act: one silence, 4.40 s, the SIGSTOP; nothing else over 150 ms. The HPC-loss
act now brakes (W3's run did not: G5). odd-respond changed verdict rule:
since W7 the island holds the 10 s window, so a driver who answers inside it
sees no MRM, and `scenario` no longer demands one (it failed on that before
the edit, with the same timeline). W3's `odd_timeout_s` rule, live: ODD
monitor SIGSTOPped 3 s during an engaged drive, the gate kept 10 Hz and
dropped `autonomous` 1.05 s after the stop, back 0.10 s after SIGCONT
(external probe; stop and resume times from the host clock).

Idle, 600 s from the gate's first sample, 1-min load held by nice-19
`stress-ng --cpu 1` instances (25-40, added and removed every 30 s), CPU
only; the load logged every 30 s: 42.6 / 54.2 / 67.0 (min / median / max
over the window; the start overshot: 40 instances at a load of 6, and the
host's own load rose at the end):

```
gate: stats: 6029 samples, largest publish gap 101.671 ms, 0 gaps over 150.000 ms, largest tick gap 101.675 ms, largest raw gap 117.277 ms (SIGCONT resumes excluded: 0)
probe: n=5993 span=599.2 s rate=10.00 Hz max_gap=111.38 ms ... gaps>150ms=0 >250ms=0 >500ms=0
```

W16's s4 (same load band, the host, SCHED_OTHER): 113.67 ms own, 122.46 ms
external. The host path (`where=host`) builds the same gate in
`just l3-host-ws`; with this user's rtprio limit of 0 it runs SCHED_OTHER.

## Traps (each one cost time today)

1. **`--container-mode observable` + rmw_zenoh_cpp: the planner never plans.**
   Every input of `behavior_path_planner` flowed and it passed its own
   `isDataReady`, yet `path_with_lane_id` stayed at 0 Hz and engage was
   refused ("The target mode is not available"). `stock` works;
   `l3-autoware` defaults to it (`L3_CONTAINER_MODE` overrides). `isolated`
   (117 processes, 7.3 GiB) never set a route in the one run tried.
2. **Three hangs that looked like one (root-caused by W11, 2026-09-29; the
   measurements are in "Start flake and silent planner" below).** W3 saw
   component containers that never finish loading ("3 composable(s) still
   constructing", "Query queue depth of 10 reached ... list_nodes") and a
   `behavior_path_planner` that goes silent after a route; all three causes
   below are fixed in the image.
   - **2a. rmw_zenoh_cpp 0.1.9 loses wakeups** (the start flake). Its
     `rmw_wait` clears `wait_set_data->triggered` at the end of
     `check_and_attach_condition()` without `condition_mutex`, a regression
     of the lock-order fix #1005 (humble backport in 0.1.9). A guard
     condition or a request that fires while the waiter is still attaching
     the rest of its wait set has its wakeup overwritten, and the waiter
     sleeps in an untimed `pthread_cond_wait` for good. Upstream: issue
     ros2/rmw_zenoh#1032, fix #1036, humble #1041, released in 0.1.10 (ROS
     apt testing). Evidence, with the 0.1.9 debug symbols: in the stuck
     container the executor's only waiter is in an untimed wait with
     `wait_set_data->triggered = false` while an attached guard condition
     reads `has_triggered_ = true`, a state only the unlocked clear can
     leave; the other 19 executor threads wait for its mutex:
     ```
     /map/map_container  LWP1215 UNTIMED triggered=false gc_true=1/3 srv_nonempty=[] subscriptions: 0 services: 0
     ```
     12 of the 13 containers play_launch named as pending in 7 hung starts
     show that state (the 13th had finished by the dump). The window is the
     scan of the wait set, so load widens it.
   - **2b. rclcpp Humble frees a guard condition under the waiter** (the
     silent planner; NOT 2a: it reproduced on 0.1.10). A new route makes
     `behavior_path_planner` reset its modules ("New uuid route is received.
     Resetting modules."), which destroys module callback groups. rclcpp
     16.0.19's executor keeps each group's notify guard condition in the
     wait set through a raw pointer, and `~CallbackGroup` triggers it, so in
     `component_container_mt` another thread wakes inside `rmw_wait` onto a
     freed rmw_zenoh `GuardCondition` (ros2/rclcpp#2445, open on Humble).
     Two dumps: the executor blocked in
     `GuardCondition::detach_condition_and_is_trigger_set` on a stale
     mutex, and `PlannerManager::run` -> `RouteHandler::getCenterLinePath`
     -> `malloc` taking a signal, glog's failure handler then deadlocking in
     `malloc` (`*** Aborted at ...` at the second of the reset). Cyclone's
     handle-based guard conditions do not write into the freed object,
     which is why only zenoh showed it. Fix: rclcpp rebuilt with the
     executor holding a strong reference until it takes the guard condition
     out of its wait set (`container/patches/`, ABI unchanged).
   - **2c. zenoh 1.8.0 peer gossip deadlocks under join churn** (what
     remained after 2a: 4 of 45 starts on 0.1.10, 3 of them dumped). An RX thread holds the
     routing `ctrl_lock` and parks in `block_in_place`
     (`Gossip::link_states`, p2p_peer hat) while the Net runtime's only
     worker waits for that lock to open the next link; every later declare
     waits behind it. Seen as play_launch frozen 0.2 s after "Registered 112
     members" (no progress line ever again) and as a container stuck in
     `rclcpp::init` -> `rmw_init` -> `z_liveliness_get` ("LoadNode service
     not available after 30s"). Upstream: eclipse-zenoh/zenoh#2581, fixed on
     main by #2779 (2026-09-11), not in any rmw_zenoh release; the PR names
     the Net runtime's single worker as the precondition. Fix: the image
     sets `ZENOH_RUNTIME="(net: (worker_threads: 8))"`, so a free worker
     runs the task the RX thread waits for. Client mode (no gossip) also
     cured it, 20 of 20 starts, but put every message through the router:
     the largest gap on the planner chain rose from 0.11-0.17 s as peers to
     0.54-0.92 s (`control_cmd` 0.57-0.86 s), too close to the 0.58 s at
     which W7's island already escalated on a silent gate.
   The scenario still keeps a SET route by default (`REROUTE=1` redoes it);
   with 2b fixed a re-route no longer silences the planner. Trap 1 was
   probably 2b (observable mode's first route), not the container mode;
   not re-measured.
3. **The island cannot join a full Autoware graph unfiltered.** On a plain
   router the QEMU island died of heap exhaustion 2.3 s after boot
   (`_z_slist_push_empty`, `_z_slice_init` in `zpico_read`), with the 120 KiB
   heap AND with 1 MiB: the liveliness burst of 136 nodes (brief C, G3).
   Behind W2's liveliness ACL it ran, until Autoware was restarted under it
   (1 MiB exhausted at 9 min 49 s, the restart's burst). Booting it first
   behind an isolated router and bridging later did not help. W4's discovery
   switch is the fix; until then the gateway ACL is required, on TCP too.
4. **An ACL that denies more than `liveliness_token` kills the island.**
   Denying `declare_liveliness_subscriber` and `liveliness_query` as well
   (egress) panicked the d8c image 2.3 s after boot with no Autoware at all.
5. **Late join reads UNKNOWN (G4).** An island that boots after Autoware's
   operation mode latched starts an MRM at once and oscillates
   NORMAL/MRM_OPERATING (21 transitions in one run) with Autoware's
   availability, because the diag graph reacts to the island's emergency.
   An operation-mode CHANGE after the join (the scenario's STOP, or the
   first initial pose) clears it.
6. **The launch closure is not the runtime closure.**
   `ros-humble-autoware-launch-1-5-0` pulls 249 of 459 packages; the parse
   stops at `sample_vehicle_description`, and AEB, collision detector,
   control validator, motion velocity planner, operation-mode transition
   manager (and more) are loaded by plugin name without being declared.
   The image installs `autoware-ros-packages-1-5-0` (456 packages).
7. **The TensorRT stub is not enough for the default planning simulator.**
   `autoware_shape_estimation` (the dummy perception's "real" path) links
   `libcudart.so.12` and TensorRT and dies at load. `l3-autoware` passes
   `perception/enable_detection_failure:=false`, the dummy perception
   without it; 38 libraries in the image have unresolved CUDA/TensorRT
   dependencies, none loaded by the planning simulator after that.
8. **This host's `/opt/autoware/1.5.0/setup.bash` (config 1.5.0-1) itself
   exports `RMW_IMPLEMENTATION=rmw_cyclonedds_cpp` and a `CYCLONEDDS_URI`**,
   not only `autoware-env.bash`. `l3-env` exports the RMW after sourcing it
   and unsets the Cyclone URI.
9. **`ros2 topic echo` without `--no-daemon`** answered "does not appear to
   be published" for a topic flowing at 10 Hz: a daemon started under
   another RMW answers for itself (nano-ros issue 1342). `ros2 topic hz` has
   no such flag in Humble; the scratch probes used rclpy.
10. **The host's play_launch "0.12.0" is not the published 0.12.0.** It is a
    wheel built from `~/repos/play_launch` on 2026-09-25 (v0.12.0-34).
    The published wheel rejected the island contract
    (`reaction-unreachable`: no service-edge walk) while the host's passed
    it; CI pins the published one and expects exit 1. (From 20:45 the
    island contract carries W6's `entry_speed` and neither parses it.)
11. **`pkill -f <pattern>` kills the shell that runs it** when the pattern is
    in its own command line; `pgrep -f '[q]emu...'` does not.
12. **`:1` on this host is a user's desktop session**, not the demo's
    TurboVNC; the fps above were taken on a private `Xvfb :97`.
13. Two host-side nodes died at start on zenoh and not on Cyclone, once
    each: `logging_diag_graph` (observable and once stock, "Exited without
    code") and `shape_estimation` (trap 7).

## Open

- G5 (W5): the island's `operate` call must reach its own operator; until
  then the HPC-loss act announces but does not brake. W24, QEMU island at
  f7c9369: it brakes (standstill 3.31 s after the SIGSTOP).
- G3 (W4): discovery off on the island; until then only the gateway ACL keeps
  the island alive, and not through an Autoware restart. phase8-W14: the
  nano-ros pin carries the knob; serial images derive it off and both TCP
  snippets state it off. Whether the gateway's liveliness ACL can go needs a
  re-measurement on the board behind the gateway, without the ACL and
  through an Autoware restart (W10 decides); until then keep it.
- G4 (W4): a late-joining island must read the current operation mode.
  phase8-W14: `mrm_handler` subscribes TRANSIENT_LOCAL again on the pin that
  serves it (phase-473 W2); the late-join run itself is not measured here.
- Trap 2's fixes live in the image only. The host path (`where=host`)
  still runs rmw_zenoh_cpp 0.1.9, stock rclcpp and peer sessions: 7 of 8
  host starts completed (W11). Drop the testing source and the rclcpp patch
  once ROS apt ships rmw_zenoh_cpp 0.1.10 and rclcpp#2445 is fixed on
  Humble; client mode can go once rmw_zenoh vendors a zenoh with #2779.
- The comfortable-stop branch and the relay's ENABLE path wait for
  `use_comfortable_stop: true` on the island (W7).
