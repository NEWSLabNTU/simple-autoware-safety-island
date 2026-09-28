# D8-A: Autoware 1.5.0 container for the RTSS@Work 2026 takeover demo

Read-only investigation, 2026-09-28. No repository was modified. Sources are
the GitHub release API, a shallow clone of NEWSLabNTU/autosdv@develop
(6e7b709, 2026-09-25) in this scratchpad, the host's installed localrepo, and
/home/aeon/repos/simple-autoware-safety-island at branch contract-params.

## 0. Headline findings (read these first)

1. The localrepo carries NO RMW packages. It holds 459 packages, all
   `-1-5-0` suffixed, under `/opt/autoware/1.5.0`. The only RMW anywhere in its
   dependency graph is `ros-humble-rmw-cyclonedds-cpp`, which `autoware-config-1-5-0`
   depends on. rmw_zenoh_cpp has to come from the ROS apt repo
   (`ros-humble-rmw-zenoh-cpp`, 0.1.9 on this host).
2. The board speaks rmw_zenoh, not DDS. Today Autoware runs on
   `rmw_cyclonedds_cpp`, domain 10 (scripts/env.sh). The S32K344 image instead
   declares rmw_zenoh keyexprs such as
   `10/api/operation_mode/state/autoware_adapi_v1_msgs::msg::dds_::OperationModeState_/*`
   (docs/boot-through.md:131), over zenoh-pico serial at 115200 baud
   (just/board-peer.just). So the container must do one of two things:
   (a) run all of Autoware on rmw_zenoh_cpp, or (b) relay the 9 input and ~16
   output topics from Cyclone into rmw_zenoh. zenoh-bridge-ros2dds is NOT
   wire-compatible with rmw_zenoh keyexprs, and domain_bridge cannot cross
   RMWs.
3. The 115200-baud UART cannot carry the island contract. My estimate is
   ~44.6 kB/s host->board at Autoware's native rates, and ~18.3 kB/s even if
   everything is downsampled to the contract's `min_rate_hz`. The line
   carries 11.5 kB/s. `/localization/kinematic_state` alone is 716 B x 40 Hz.
   Board->host at contract rates is ~19 kB/s. This is a demo blocker that is
   independent of the container. It needs a higher baud (the FT232R does
   3 Mbaud; the board RX FIFO is only 4 bytes), router-side downsampling,
   contract rate cuts, or the T1 Ethernet link. Section 3.3 has the numbers.
4. A planning-simulator-only image does not need CUDA, a GPU, or the
   2 GB `autoware-data-1-5-0`. autosdv's 26.7 GB image carries a CUDA devel
   base because it builds CUDA code. The one hard obstacle is that
   `autoware_launch` transitively Depends on `libnvinfer10` and
   `libnvinfer-plugin10`, both unversioned. None of the 68 composables in this
   host's last planning-sim run (play_log/latest) loads a TensorRT library, so
   an equivs stub or the NVIDIA runtime libs will do.
5. autosdv already solved most container problems for 1.5.0 on this exact
   localrepo. Reusable pieces include the download (aria2c, checksum), the
   libnvinfer dependency, NET_ADMIN for loopback multicast, TurboVNC + noVNC
   for RViz, a UID/GID-matching entrypoint, the rmw fallback trap, and purging
   the localrepo pool after install.

## 1. autoware-localrepo release 1.5.0-2

Release metadata comes from `gh release view 1.5.0-2 -R NEWSLabNTU/autoware-localrepo`.
The release was published 2026-05-05. The repo itself is 2.5 GB; a shallow
clone died with "early EOF", so the API was used instead.

Assets:

| file | bytes | platform |
|---|---|---|
| autoware-localrepo-1-5-0_1.5.0-2ubuntu2204_all.deb | 1,988,674,572 (1.85 GiB) | Ubuntu 22.04 x86_64 |
| autoware-localrepo-1-5-0_1.5.0-2jetpack62_all.deb | 1,983,839,272 | JetPack 6.2 (Jetson Orin) |
| SHA256SUMS.txt | 233 | |

Release body, quoted:

> Debian packages for Autoware 1.5.0, bundled as a local APT repository -- patch release `-2`.
> Source: `NEWSLabNTU/autoware @ 1.5.0-2` -- upstream Autoware 1.5.0 plus NEWSLab build patches.
> - Versioned helper script paths (`/usr/share/autoware/1.5.0/`) and APT source files (`autoware-localrepo-1-5-0.list`/`.pref`) so 1.5.0 can coexist with other versions.
> - Versioned sysctl/systemd files (`10-cyclone-max-1-5-0.conf`, `multicast-lo-1-5-0.service`).
> - Split `setup.$shell` into pure ament workspace env + `autoware-env.$shell` (DDS/CycloneDDS/Qt config).
> Contents: 450+ ROS 2 Humble packages, ML models (ONNX) for perception, CycloneDDS configuration, sample maps, RViz theme.

Installation steps, quoted:

```
sudo dpkg -i autoware-localrepo-1-5-0_1.5.0-2ubuntu2204_all.deb
sha256sum -c SHA256SUMS.txt                               # optional
sudo /usr/share/autoware/1.5.0/setup-prerequisites.sh     # ROS 2 Humble, optionally CUDA/TensorRT/SpConv
sudo /usr/share/autoware/1.5.0/activate-dds-config.sh
sudo apt update && sudo apt install autoware-full-1-5-0
source /opt/autoware/1.5.0/setup.bash          # workspace env (ament + ROS)
source /opt/autoware/1.5.0/autoware-env.bash   # DDS/CycloneDDS/Qt config
```

Test command, quoted: `ros2 launch autoware_launch planning_simulator.launch.xml map_path:=/opt/autoware/1.5.0/share/autoware_maps/sample-map-planning vehicle_model:=sample_vehicle sensor_model:=sample_sensor_kit`

The Ubuntu/ROS target is Ubuntu 22.04 (jammy) with ROS 2 Humble. The Debian
packages are built by colcon2deb in a builder image based on
`ghcr.io/autowarefoundation/autoware-base:cuda-20251120`, which is CUDA 12.4,
cuDNN 8.9.7 and TensorRT 10.8.0. Config is in `1.5.0/amd64/config.yaml`:
`ros_distro: humble`, `install_prefix: /opt/autoware/1.5.0`, `package_suffix: "1-5-0"`.
That Dockerfile is the BUILDER, not a runtime image.

What the .deb is, per `dpkg -L autoware-localrepo-1-5-0` on this host (host
has 1.5.0-2ubuntu2204 installed):
- `/opt/autoware/1.5.0/repo/{Packages,Packages.gz,pool/main/*.deb}`: 459 debs,
  1.9 GB pool.
- `/etc/apt/sources.list.d/autoware-localrepo-1-5-0.list`, which reads
  `deb [trusted=yes] file:/opt/autoware/1.5.0/repo ./`.
- `/etc/apt/preferences.d/autoware-localrepo-1-5-0.pref`, which reads
  `Pin: origin ""`, `Pin-Priority: 1001`.
- `/usr/share/autoware/1.5.0/{setup-prerequisites.sh,activate-dds-config.sh,uninstall-autoware.sh}`.

Package facts, from `/opt/autoware/1.5.0/repo/Packages`:
- `autoware-full-1-5-0` Depends: `autoware-config-1-5-0, autoware-theme-1-5-0, autoware-data-1-5-0, autoware-ros-packages-1-5-0`.
- `autoware-data-1-5-0`: 1.79 GB download, 2.0 GiB installed. It holds ML
  models and is NOT in the `ros-humble-autoware-launch-1-5-0` closure, so skip
  it.
- `autoware-config-1-5-0` (1.5.0-2) Depends: `ros-humble-rmw-cyclonedds-cpp`.
  It ships `autoware-env.bash`, which unconditionally sets
  `export RMW_IMPLEMENTATION=rmw_cyclonedds_cpp` and
  `CYCLONEDDS_URI=file://$AUTOWARE_HOME/config/cyclonedds.xml`. For a zenoh
  container, DO NOT source it, or override RMW_IMPLEMENTATION after it.
- `autoware-theme-1-5-0` Depends: `qt5ct`.
- RMW packages in the pool: none. No rmw_zenoh, no zenoh.
- TensorRT dependencies: the unversioned `libnvinfer10` (5 packages) and
  `libnvinfer-plugin10` (1 package). They are reached from `autoware_launch`
  via `autoware_tensorrt_common`, `tensorrt_yolox`, `cuda_utils`,
  `cuda_blackboard`, and others. Recursive `apt-cache depends` on
  `ros-humble-autoware-launch-1-5-0` gives ~1,690 packages including
  libnvinfer10, libnvinfer-plugin10 and rviz2.
- Sum of Installed-Size over all 459 pool packages: 2.9 GiB, of which 2.0 GiB
  is autoware-data.
- `setup-prerequisites.sh` installs `ros-humble-ros-base ros-humble-rmw-cyclonedds-cpp`.
  With `--tensorrt` it pins `libnvinfer10=10.8.0.43-1+cuda12.8`, which is a
  1.97 GB download and 4.4 GB installed (`apt-cache show`). Newer 10.x builds
  are 2.5 GB (cuda13.2) or 3.5 GB (cuda12.9) installed.
- `activate-dds-config.sh` falls back to `ip link set lo multicast on` without
  systemd: "Direct approach for containers or systems without systemd".

How long it takes: autosdv measured the release host on an AGX Orin. They
report "wget 383 KB/s, aria2c 2905 KB/s -- 7.6x, which is four hours against
ten minutes" (autosdv setup/scripts/install-autoware-debian.sh). Always use
`aria2c -x 10 -s 10`.

Host note: this host's localrepo is 1.5.0-2, but the installed
`autoware-config-1-5-0` and `autoware-full-1-5-0` are still 1.5.0-1. So
`/opt/autoware/1.5.0/autoware-env.bash` does not exist here, and a stale
unversioned `/etc/apt/sources.list.d/autoware-localrepo.list` is still present.
It is harmless, but the host is not a clean reference for "-2".

## 2. autosdv (develop): what installs Autoware, what can be reused

Clone: `scratchpad/d8/autosdv` (shallow, LFS skipped).

### 2.1 Install path
- `setup/setup.sh` -> `setup/main.py` -> step registry
  `setup/autosdv_setup/registry.py`. The steps relevant here are `ros2`
  (`install-ros2.sh`: ros2-apt-source .deb then `ros-humble-desktop`),
  `tensorrt` (`install-tensorrt.sh`), and `autoware-debian`
  (`install-autoware-debian.sh`).
- `setup/scripts/install-autoware-debian.sh` does the following:
  1. Picks the deb by arch and pins the checksums
     `SHA256SUM_UBUNTU2204="f8e2d1d2f43d7a7186b7fbcd391b473783d1ef9cd131a12bfea898255d450acb"`
     and `SHA256SUM_JETPACK62="e3187ca5..."`.
  2. Downloads with aria2c (10 connections, `--checksum=sha-256=`), falling
     back to wget or curl with a loud warning.
  3. Runs `sudo apt install -y "$TEMP_DEB"`.
  4. Runs `yes | sudo /usr/share/autoware/setup-prerequisites.sh --no-ros --no-nvidia|--all-nvidia`.
  5. Installs chrony if no `time-daemon` provider exists.
  6. Runs `sudo apt install -y autoware-full-1-5-0`.
- BUG worth knowing: step 4 tests `/usr/share/autoware/setup-prerequisites.sh`,
  the unversioned path from 1.5.0-1. Release -2 moved it to
  `/usr/share/autoware/1.5.0/`, as the host's `dpkg -L` shows. On -2 that step
  prints "Warning: ... not found. Skipping." and continues. It is harmless
  only because ROS and TensorRT come from other steps.
- `install-tensorrt.sh` installs only `libnvinfer10 libnvinfer-plugin10 libnvonnxparsers10`,
  pinned to `versions.yaml nvidia_amd64.tensorrt_engine_abi`. Its note says it
  installs "three runtime libraries only: no CUDA toolkit, no driver".
  Rationale from the registry, quoted: "autoware-debian cannot resolve without
  libnvinfer10".

### 2.2 Container (docker/desktop/)
`Dockerfile` has two targets, `base` and `desktop`, on
`nvidia/cuda:12.8.1-cudnn-devel-ubuntu22.04`. Points worth lifting:
- On why the libs are present without a GPU, quoted: "They are libraries, not
  a driver: nothing in Autoware links libcuda.so.1 (0 of 840 amd64 ...
  shipped libraries), so no driver is installed and none is needed."
- `ENV RMW_IMPLEMENTATION=rmw_cyclonedds_cpp` exists because
  "Autoware's own setup.bash does not set it". A shell that does not set it
  falls to rmw_fastrtps_cpp, and "FastDDS ... runs out around 120 per host per
  domain ... Nothing reports an error." (Measured: fastrtps 2 topics
  visible vs cyclone 605.) For us the same trap applies to rmw_zenoh: set
  RMW_IMPLEMENTATION in the image ENV, not in a sourced script.
- The install and prune happen in one RUN with a cache mount for the deb:
  `RUN --mount=type=cache,target=/opt/AutoSDV/data/autoware-debian ... ./setup/setup.sh --run --profile container --yes && apt-get purge -y autoware-localrepo-1-5-0 && rm -f /opt/tensorrt/*/lib/libnvinfer_builder_resource_win.so.* ...`.
  Quote on why: "After the 333 packages are installed, that pool is a second
  copy of them. Purged rather than rm'd ... (verified: 0 packages cascade)."
- The `container` profile (registry.py:678-725) excludes `cyclonedds-sysctl`
  and `multicast-lo`. Reason, quoted: "net.core.rmem_max is not namespaced ...
  `docker run --sysctl net.core.rmem_max=...` refuses to start at all". The
  entrypoint instead runs `ip link set lo multicast on` with NET_ADMIN.
- Graphics: TurboVNC + VirtualGL + noVNC on :6080. The entrypoint picks
  "Mesa d3d12 on WSL2, VirtualGL on a Linux GPU, software otherwise".
- Entrypoint: starts as root, `usermod` to HOST_UID/HOST_GID, then `gosu`.
- Run command, quoted from docker/desktop/README.md:84:
  ```
  docker run -it --rm -p 6080:6080 -v "$PWD/data:/opt/AutoSDV/data" -v "$PWD:/workspace" \
    -e HOST_UID="$(id -u)" -e HOST_GID="$(id -g)" --shm-size=2gb --cap-add=NET_ADMIN \
    jerry73204/autosdv:desktop
  ```
- Measured numbers (README "Known gaps" and the size table):
  - Image sizes: amd64 26.7 GB, arm64 11.2 GB; 14.34 GB compressed for the
    older `:sim` amd64. The first build was 34.8 GB, with 1.9 GB each for pool,
    deb and the TensorRT Windows blob, plus 3.6 GB of CUDA `.a` files.
  - The planning sim "reaches 34/34 nodes, 15/15 containers and 70/70
    composables".
  - "RViz draws nothing for about 90 seconds after `Startup complete`".
  - Setup time: "Installing ROS 2 and Autoware takes about seventy minutes".
  - `--container-mode observable` (play_launch) gives "all nodes ready in 7 s
    against ~90 s, 3.09 GiB against 5.71 GiB, 49 processes against 119".
- The RViz cost without a GPU is in docs/reports/gpu-less-simulation-and-rviz.md
  (Ryzen 9950X):

  | RViz config | renderer | fps | CPU |
  |---|---|---|---|
  | stock autoware.rviz | llvmpipe | 2 | 443 % |
  | stock autoware.rviz | RTX 5090 | 10 | 99 % |
  | PointCloudMap display off | llvmpipe | 31 | 161 % |

  Quote: "the map point cloud is the whole difference between 3 fps and 31".
  Our map's `pointcloud_map.pcd` is 28 MB (demo/map/sample-map-planning).

### 2.3 What to reuse vs. drop
Reuse:
- the aria2c + sha256 download logic;
- the libnvinfer handling, or replace it with a stub, see 4.2;
- the one-RUN install + purge of the localrepo with a cache mount;
- `RMW_IMPLEMENTATION` in the image ENV;
- the NET_ADMIN/lo-multicast entrypoint snippet (not needed with rmw_zenoh);
- the TurboVNC/noVNC graphics layer and gosu UID mapping, if RViz goes in the
  container;
- the play-launch setup step and `--container-mode observable`.

Drop:
- the CUDA devel base;
- Rust/cargo, range-libc, ZED/Blickfeld and TensorRT engines;
- autoware-data;
- the student /workspace build flow.

## 3. The host demo today

### 3.1 How Autoware is launched
- Recipe `just autoware` -> `_svc-sim` (justfile:695-735). It sources
  `scripts/env.sh`, then:
  ```
  play_launch launch autoware_launch planning_simulator.launch.xml \
    map_path:=$PWD/demo/map/sample-map-planning vehicle_model:=sample_vehicle \
    sensor_model:=sample_sensor_kit rviz:=true   > tmp_sim.log
  ```
  Readiness is `grep "Startup complete" tmp_sim.log`, with a 300 s timeout.
  play_launch must be >= 0.8.2 (0.12.0 in play_log/latest/run_info.json).
  DISPLAY defaults to TurboVNC `:1`.
- Env from scripts/env.sh:
  - `RMW_IMPLEMENTATION=rmw_cyclonedds_cpp`, `ROS_DOMAIN_ID=10`,
    `CYCLONEDDS_URI=file://.../demo/cyclonedds.xml`. That file sets
    ParticipantIndex auto with range 120, because the native_sim island
    peer-scans 127.0.0.1.
  - It sources `/opt/ros/humble`, `/opt/autoware/1.5.0/setup.bash`, then
    the `demo/host_ws` overlay.
- The stock MRM is disabled by `demo/host_ws/src/tier4_system_launch/launch/system.launch.xml`,
  which shadows the upstream package. Its line 115 has
  "MRM Operator -- DISABLED: the safety island provides the only MRM path",
  and line 135 has "MRM Handler -- DISABLED". The container must carry this
  overlay; it is a colcon build of one launch-only package.
- `just demo` runs `demo/scenario_driver.py` (rclpy):
  1. `/initialpose` and the goal on `/planning/mission_planning/goal`;
  2. `/api/operation_mode/change_to_autonomous`;
  3. drive;
  4. SIGSTOP the process publishing `/system/operation_mode/availability`
     (the diagnostic-graph `converter_node`);
  5. the island MRM stops the vehicle;
  6. SIGCONT, resume, then the VERDICT.

  SIGSTOP by pid means the driver must share the PID namespace with Autoware,
  so it runs in the same container.
- The board path is separate: `just board-peer` (just/board-peer.just)
  - runs `rmw_zenohd` under `env -i` with ZENOH_ROUTER_CONFIG_URI=
    experiments/serial-interop/router-serial.json5 (keep_alive 6 for the
    board's 20 s lease), and
  - uses `ZENOH_CONFIG_OVERRIDE='listen/endpoints=["serial//dev/ttyUSB0#baudrate=115200","tcp/[::]:7449"]'`,
    with `ROS_DOMAIN_ID=10`, the image's CONFIG_NROS_DOMAIN_ID.

  Quote: "the router must be listening BEFORE the board dials: start this,
  then reset the board." Quote: "nothing else may hold /dev/ttyUSB0".
  State (docs/board-facts.md:414-441, W7): "the session opens, but the
  executor does not start". Registration fails at the third TRANSIENT_LOCAL
  publisher, and W8 (HEAD e318253) says "the heap is what remains". So the
  board has not yet run the island against Autoware.

### 3.2 Topic table
Types and rates are from `src/safety_island_bringup/launch/safety_island.contract.yaml`.
The contract's `rate_hz`/`min_rate_hz` are the island's sizing assumptions.
The "source rate" column is what Autoware's configuration implies:
- the simple_planning_simulator timer is `timer_sampling_time_ms: 25`, so
  40 Hz;
- vehicle_cmd_gate has `update_rate: 10.0`, and forwards control_cmd per
  controller input at about 30 Hz;
- the diagnostic_graph_aggregator has `rate: 10.0`.

VERIFY the source rates with `ros2 topic hz`; I did not launch Autoware.

Sizes are CDR bytes including the 4-byte encapsulation header. I computed them
with `rclpy.serialization.serialize_message` on default-valued messages:
frame_id "map"/"base_link" and sender "mrm_comfortable_stop_operator". The
script is scratchpad/d8/sizes.py. Covariance arrays dominate Odometry.

Autoware -> island (9):

| topic | type | source rate | contract rate | CDR B |
|---|---|---|---|---|
| /system/operation_mode/availability | tier4_system_msgs/msg/OperationModeAvailability | 10 Hz (aggregator) | 10 | 19 |
| /localization/kinematic_state | nav_msgs/msg/Odometry | 40 Hz (sim) | 10 | 716 |
| /vehicle/status/control_mode | autoware_vehicle_msgs/msg/ControlModeReport | 40 Hz (sim) | 10 | 13 |
| /control/command/gear_cmd | autoware_vehicle_msgs/msg/GearCommand | 10 Hz (gate timer) | 10 | 13 |
| /api/operation_mode/state | autoware_adapi_v1_msgs/msg/OperationModeState | on change (ADAPI) | 10 | 19 |
| /control/command/control_cmd | autoware_control_msgs/msg/Control | ~30 Hz (gate) | 30 | 78 |
| /planning/route_state | autoware_planning_msgs/msg/RouteState (transient local) | on change | 30 | 13 |
| /vehicle/status/steering_status | autoware_vehicle_msgs/msg/SteeringReport | 40 Hz (sim) | 30 | 16 |
| /vehicle/status/velocity_status | autoware_vehicle_msgs/msg/VelocityReport | 40 Hz (sim) | 30 | 40 |

Note: `/planning/route_state` is `autoware_planning_msgs/msg/RouteState`
(mission_planner `~/main/state`). The adapi RouteState, at 14 B, is a
different type on `/api/routing/state`. docs/topic-contract.md is stale: it
still says domain 1/2 plus domain_bridge and lists the adapi type.

Island -> Autoware (13 external; `external: sub` in the contract):

| topic | type | contract rate | CDR B | QoS |
|---|---|---|---|---|
| /system/emergency/control_cmd | autoware_control_msgs/msg/Control | 30 | 78 | volatile |
| /system/fail_safe/mrm_state | autoware_adapi_v1_msgs/msg/MrmState | 10 | 16 | volatile |
| /system/emergency/gear_cmd | autoware_vehicle_msgs/msg/GearCommand | 10 | 13 | volatile |
| /system/emergency/hazard_lights_cmd | autoware_vehicle_msgs/msg/HazardLightsCommand | 10 | 13 | volatile |
| /system/emergency/turn_indicators_cmd | autoware_vehicle_msgs/msg/TurnIndicatorsCommand | 10 | 13 | volatile |
| /system/fail_safe/emergency_holding | tier4_system_msgs/msg/EmergencyHoldingState | 10 | 13 | volatile |
| /planning/scenario_planning/max_velocity_candidates | autoware_internal_planning_msgs/msg/VelocityLimit | 10 | 70 | TL depth 1 |
| /planning/scenario_planning/clear_velocity_limit | autoware_internal_planning_msgs/msg/VelocityLimitClearCommand | 10 | 50 | TL depth 1 |
| /system/stop_mode/control | autoware_control_msgs/msg/Control | 30 | 78 | volatile |
| /system/stop_mode/gear | autoware_vehicle_msgs/msg/GearCommand | 30 | 13 | TL depth 1 |
| /system/stop_mode/hazard_lights | autoware_vehicle_msgs/msg/HazardLightsCommand | 30 | 13 | TL depth 1 |
| /system/stop_mode/turn_indicators | autoware_vehicle_msgs/msg/TurnIndicatorsCommand | 30 | 13 | TL depth 1 |

Island-internal: MrmBehaviorStatus (13 B) at 10 and 30 Hz, and 2x OperateMrm
services. They stay on the board if zenoh-pico local delivery is on. The
nano-ros platform notes say `Z_FEATURE_LOCAL_SUBSCRIBER=1` "set by
zephyr/cmake/nros_rmw_zenoh.cmake on Zephyr". Whether those puts are ALSO
sent to the router is an open question; see Q5.

### 3.3 Serial budget: 115200 8N1 carries 11,520 B/s each way
Assumptions:
- ~50 B per-sample overhead on the wire: rmw_zenoh attachment (seq + source
  timestamp + 16 B GID, ~36 B), a zenoh PUT header with a declared keyexpr id,
  and serial COBS + length + CRC32 + delimiter;
- no batching, since bare-metal zpico has `Z_FEATURE_BATCHING 0`
  (nano-ros issue 1096 table).

Estimates only. Measure with `experiments/serial-interop/serial-tap.py`.

- Host -> board at the source rates: kinematic_state 30,640, velocity 3,600,
  control_cmd 3,840, steering 2,640, control_mode 2,520, availability 690,
  gear 630, op-mode ~70. That is ~44.6 kB/s, 3.9x the line.
- Host -> board downsampled to the contract rates: kinematic 7,660 +
  velocity 2,700 + steering 1,980 + control_cmd 3,840 + control_mode 630 +
  availability 690 + gear 630 + op-mode 70. That is ~18.3 kB/s, 1.6x the line.
- Board -> host at the contract rates:
  - emergency control 3,840, stop_mode control 3,840;
  - stop_mode gear/hazard/turn at 30 Hz: 5,670;
  - emergency gear/hazard/turn at 10 Hz: 1,890;
  - mrm_state 660, holding 630;
  - velocity limit + clear 2,200.

  That is ~18.7 kB/s, 1.6x the line.

Options, which can be combined:
- (i) Raise the baud to 921,600 (92 kB/s) or 1-3 Mbaud. The FT232R
  (`/dev/serial/by-id/usb-FTDI_FT232R_USB_UART_B001UCTE-if00-port0`) supports
  3 Mbaud. On the board, the LPUART2 RX FIFO is 4 bytes, which at 921,600
  overflows in ~43 us without DMA (experiments/serial-interop/README.md:200).
  The locator `serial/uart@40330000#baudrate=115200` is compiled into the
  image.
- (ii) Router egress downsampling on the serial link only. rmw_zenoh's
  router config already has the block (router-serial.json5:432-462):
  `downsampling: [{ link_protocols: ["serial"], flows: ["egress"], messages: ["put"], rules: [{ key_expr: "10/localization/kinematic_state/**", freq: 10.0 }, ...] }]`.
  This keeps Autoware and RViz at full rate and only thins the board feed.
- (iii) Cut the island's publish rates: stop_mode_operator at 30 Hz with
  three TL publishers, and the operators' 30 Hz ticks.
- (iv) The T1 Ethernet link, which needs the 100BASE-T1 media converter the
  project does not have (docs/board-facts.md:85-99, 464).

## 4. Proposed container architecture

### 4.1 Topology (recommended: one container, all of it on rmw_zenoh_cpp)

```
 host (Ubuntu 22.04 / any Docker or Podman host)          NXP S32K344 (Zephyr, nano-ros, zenoh-pico)
 +----------------------------------------------------+
 | container "aw-demo" (network: bridge or host)       |
 |  rmw_zenohd  (router)                              |
 |    listen tcp/[::]:7447          <-- Autoware peers |   /dev/ttyUSB0 (FTDI, P6)
 |    listen serial//dev/ttyUSB0#baudrate=B  <---------+---- serial/uart@40330000
 |    downsampling (egress, serial only)              |
 |  Autoware 1.5.0 planning_simulator (play_launch,   |
 |    --container-mode observable, rviz optional)      |
 |  demo/host_ws overlay (stock MRM disabled)          |
 |  takeover_demo pkg: odd_monitor, availability_gate, |
 |    takeover_hmi (10 s TOR), driver_button           |
 |  RMW_IMPLEMENTATION=rmw_zenoh_cpp ROS_DOMAIN_ID=10  |
 +----------------------------------------------------+
```

Why a single router for both sides: the board is a zenoh-pico client on
serial, and every Autoware process is an rmw_zenoh peer that dials
`tcp/localhost:7447` (DEFAULT_RMW_ZENOH_SESSION_CONFIG.json5: `mode: "peer"`,
multicast scouting off, gossip on). One router listening on both endpoints is
the whole bridge. The downsampling rules in the same router protect the UART.

Alternative B: Autoware stays on Cyclone and a CDR relay feeds the board.
Use this if Autoware on rmw_zenoh_cpp misbehaves. It is two small processes:
- one on rmw_cyclonedds_cpp subscribes to the 9 inputs with
  `create_subscription(..., raw=True)` / generic serialized subscriptions;
- one on rmw_zenoh_cpp republishes the bytes;
- plus the reverse direction for the 13 outputs.

They are linked by a local socket or pipe. CDR bytes are identical across
both RMWs, so this is a byte copy, with ~150 lines per direction. It keeps
the validated Cyclone demo unchanged, and the relay is also a natural
per-topic rate limiter. Cost: one extra hop of latency to measure, and a
component that is QM by construction.

External-router variant: the router runs on the host, outside the container.
Everything is identical except that the container gets
`ZENOH_CONFIG_OVERRIDE='connect/endpoints=["tcp/host.docker.internal:7447"]'`
(add `--add-host=host.docker.internal:host-gateway`), or uses
`--network host` and dials `tcp/127.0.0.1:7447`. The container then needs no
serial device, and the board-peer recipe stays the host tool it is today.
Use port 7449, as board-peer.just already chose, so as not to collide with
other rmw_zenoh processes on the host.

### 4.2 Dockerfile outline (amd64; arm64 is the same with the jetpack62 deb)

```
# syntax=docker/dockerfile:1.6
FROM ros:humble-ros-base-jammy AS base           # ubuntu 22.04 + ROS 2 Humble apt source
ENV DEBIAN_FRONTEND=noninteractive LANG=C.UTF-8
RUN apt-get update && apt-get install -y --no-install-recommends \
      aria2 ca-certificates equivs gosu iproute2 sudo python3-pip \
      ros-humble-rmw-zenoh-cpp ros-humble-rmw-cyclonedds-cpp \
      ros-humble-topic-tools python3-colcon-common-extensions chrony

# libnvinfer10: EITHER stub it (planning sim loads no TensorRT lib) ...
RUN printf 'Package: nvinfer-stub\nVersion: 10.0\nProvides: libnvinfer10, libnvinfer-plugin10\nDescription: stub\n' > /tmp/s \
 && equivs-build /tmp/s && dpkg -i nvinfer-stub_10.0_all.deb
# ... OR the real runtime libs: cuda-keyring deb, then
#     apt-get install libnvinfer10 libnvinfer-plugin10  (+2.5..4.4 GB)

# Autoware from the localrepo, deb in a cache mount, pool purged in the same RUN
ARG AW_DEB=autoware-localrepo-1-5-0_1.5.0-2ubuntu2204_all.deb
ARG AW_SHA=f8e2d1d2f43d7a7186b7fbcd391b473783d1ef9cd131a12bfea898255d450acb
RUN --mount=type=cache,target=/var/cache/aw \
    [ -f /var/cache/aw/$AW_DEB ] || aria2c -x10 -s10 -k1M --checksum=sha-256=$AW_SHA \
       -d /var/cache/aw -o $AW_DEB \
       https://github.com/NEWSLabNTU/autoware-localrepo/releases/download/1.5.0-2/$AW_DEB \
 && apt-get install -y /var/cache/aw/$AW_DEB && apt-get update \
 && apt-get install -y --no-install-recommends \
      ros-humble-autoware-launch-1-5-0 autoware-config-1-5-0 autoware-theme-1-5-0 \
      # NOT autoware-full (pulls autoware-data, 2 GB of ONNX models)
 && apt-get purge -y autoware-localrepo-1-5-0 && rm -rf /var/lib/apt/lists/*

RUN pip3 install play_launch==<pinned >=0.8.2>        # or autosdv's play-launch step

# overlay + demo package (from the repo, not the whole tree)
COPY demo/host_ws/src /opt/demo_ws/src               # tier4_system_launch shadow
COPY demo/takeover_demo /opt/demo_ws/src/takeover_demo
COPY demo/map/sample-map-planning /opt/demo/map/sample-map-planning
COPY experiments/serial-interop/router-serial.json5 /opt/demo/zenoh/router.json5  # + downsampling block
RUN . /opt/ros/humble/setup.sh && . /opt/autoware/1.5.0/setup.sh \
 && cd /opt/demo_ws && colcon build --merge-install

ENV RMW_IMPLEMENTATION=rmw_zenoh_cpp ROS_DOMAIN_ID=10 \
    ZENOH_ROUTER_CONFIG_URI=/opt/demo/zenoh/router.json5
# NOTE: never source /opt/autoware/1.5.0/autoware-env.bash (forces cyclone)
COPY docker/entrypoint.sh /entrypoint.sh             # UID map + gosu, start zenohd, then CMD
ENTRYPOINT ["/entrypoint.sh"]
CMD ["demo-run"]                                     # zenohd + play_launch (rviz:=false) + takeover nodes

FROM base AS gui                                      # optional RViz layer
RUN apt-get update && apt-get install -y --no-install-recommends \
      turbovnc virtualgl novnc websockify openbox mesa-utils   # lift from autosdv
```

Entrypoint order:
1. rmw_zenohd with the serial endpoint in ZENOH_CONFIG_OVERRIDE, only if
   `/dev/ttyUSB0` is present;
2. wait for the router to print its listening endpoints;
3. play_launch;
4. wait for "Startup complete";
5. the takeover nodes;
6. print the instruction "now reset the board", because the router must be
   listening before the board dials.

### 4.3 Run commands

Headless, with the board on USB serial and everything in the container:
```
docker run --rm -it --name aw-demo \
  --device /dev/serial/by-id/usb-FTDI_FT232R_USB_UART_B001UCTE-if00-port0:/dev/ttyUSB0 \
  --group-add dialout --shm-size=2g \
  -e HOST_UID=$(id -u) -e HOST_GID=$(id -g) \
  -p 7447:7447 \
  aw-demo:1.5.0 demo-run
```
- Podman rootless: use `--group-add keep-groups` so dialout survives.
  Podman here is 3.4.4 (jammy); Docker is 29.2.1 with the `nvidia` runtime.
- `-p 7447` is only for host-side `ros2` CLI or RViz. The bridge network is
  otherwise sufficient, because rmw_zenoh needs no multicast (unlike Cyclone,
  which needed NET_ADMIN for lo multicast).

With RViz:
- (a) noVNC: autosdv style, `--target gui`, `-p 6080:6080`, open a browser.
- (b) Host X: `-e DISPLAY=$DISPLAY -v /tmp/.X11-unix:/tmp/.X11-unix:ro`, plus
  `xhost +si:localuser:$(id -un)`. Add `--device /dev/dri` for Mesa GPUs, or
  `--gpus all` with the nvidia runtime (RTX 3090 here).
- (c) RViz on the host, container headless. The host needs only
  ros-humble-rmw-zenoh-cpp plus the Autoware rviz plugins and message
  packages; this host has them. Connect with
  `ZENOH_CONFIG_OVERRIDE='connect/endpoints=["tcp/127.0.0.1:7447"]'`.

  Option (c) is the lowest-risk for the booth: the laptop's native GL, no
  GUI plumbing in the image.

Router outside the container: drop `--device`, add
`-e ZENOH_CONFIG_OVERRIDE='connect/endpoints=["tcp/host.docker.internal:7449"]' --add-host=host.docker.internal:host-gateway`,
and do not start zenohd in the entrypoint. The host runs `just board-peer`
(port 7449).

### 4.4 The takeover scenario package (`takeover_demo`, ament_python, in the container)

Design principle: the island image and its contract stay unchanged. The
island already treats `availability.autonomous == false` in AUTONOMOUS mode,
or availability silence for more than 0.5 s, as an emergency:
`isEmergency() = !isAvailableCurrentOperationMode() || is_emergency_holding_ || is_operation_mode_availability_timeout`
(src/autoware_mrm_handler/src/mrm_handler/mrm_handler_core.cpp:574-578,
`timeout_operation_mode_availability: 0.5`). So the takeover logic expresses
"TOR expired" through the topic the island already guards.

Nodes (rclpy, all rmw_zenoh_cpp, domain 10):

1. `odd_monitor`
   - Subscribes `/localization/kinematic_state` (full rate, in the container).
     Optionally subscribes `/planning/route_state`.
   - Params: ODD polygon in map coordinates (a stretch of sample-map-planning),
     `max_speed_mps`, `lead_time_s`.
   - Service `~/inject_exit` (std_srvs/Trigger), so the booth operator can
     also force an exit, e.g. "weather".
   - Publishes `/demo/odd/state` at 10 Hz. Type is either
     `takeover_demo/msg/OddState {stamp, bool in_odd, bool exit_imminent, float32 time_to_exit_s, string reason}`
     or, to avoid a custom msg, std_msgs/Bool plus a String.
2. `takeover_hmi` (TOR manager): a state machine
   `AUTOPILOT -> TOR_ACTIVE(10 s countdown) -> {DRIVER_TOOK_OVER | TOR_EXPIRED}`.
   - Entering TOR_ACTIVE: on `exit_imminent` while
     `/api/operation_mode/state.mode == AUTONOMOUS`.
   - Publishes `/demo/takeover/state` at 10 Hz. It also publishes an overlay
     string (autoware_internal_debug_msgs/StringStamped, rendered by the
     localrepo's `autoware_string_stamped_rviz_plugin`), e.g.
     "TAKE OVER 7.3 s".
   - Publishes turn-indicator/hazard intent only through the island, never
     directly.
   - On DRIVER_TOOK_OVER, it hands control to the driver. Either call ADAPI
     `/api/operation_mode/disable_autoware_control`, or call the simulator's
     `/control/control_mode_request` (autoware_vehicle_msgs/srv/ControlModeCommand,
     MANUAL; simple_planning_simulator remaps `input/control_mode_request` to
     it). Optionally stream `/vehicle/command/manual_control_cmd`
     (`input/manual_ackermann_control_command`) to show the driver
     decelerating or holding the lane.

     With control mode MANUAL, the island's `isControlModeAutonomous()` is
     false and it stays NORMAL.
   - On TOR_EXPIRED, it latches `tor_expired = true`, which `availability_gate`
     consumes.
3. `availability_gate`
   - The aggregator's `converter_node` is re-remapped from
     `/system/operation_mode/availability` to
     `/system/operation_mode/availability_raw`.
   - The gate republishes each raw sample to
     `/system/operation_mode/availability` with `autonomous &= !tor_expired`.
   - Same rate (10 Hz), same QoS (depth 1). The contract adds
     `liveliness: manual_by_topic, lease 500ms`, so check that rmw_zenoh
     honours what the island expects.
   - Fail-safe property: if the gate dies, the heartbeat stops and the island
     triggers MRM on timeout. That is the existing, validated demo fault,
     which becomes the second scenario for free.
   - Wiring:
     - The remap is hard-coded in upstream
       `autoware_diagnostic_graph_aggregator/launch/aggregator.launch.xml`
       (`<remap from="~/operation_mode/availability" to="/system/operation_mode/availability"/>`),
       so it is not an arg.
     - The overlay `demo/host_ws/src/tier4_system_launch/launch/system.launch.xml:118-126`,
       which already includes that file, must instead launch
       `aggregator_node` and `converter_node` inline with the new remap.
       This is a small edit to a file the demo already owns.
4. `driver_button`
   - Publishes `/demo/driver/response` (std_msgs/Empty) on any of:
     - a key on the booth keyboard (stdin/termios);
     - a USB HID "big red button". It reads `/dev/input/by-id/...` via
       python3-evdev, which needs `--device /dev/input/eventN` or a udev
       rule;
     - optionally, a small web button.
   - The RViz AutowareStatePanel already has operation-mode and autoware-control
     buttons, but a physical button reads better on stage.

Launch: `takeover_demo/launch/takeover.launch.xml`, started by the
entrypoint after "Startup complete". The scenario driver, which extends
demo/scenario_driver.py, runs:
1. init pose, goal, engage;
2. drive into the ODD exit;
3. run A: the driver presses the button -> MANUAL, island NORMAL,
   VERDICT A;
4. run B: no press -> at t=10 s the island `MRM_OPERATING/EMERGENCY_STOP`
   (or COMFORTABLE_STOP if `use_comfortable_stop: true`, which is closer to
   Drive Pilot's in-lane stop; the island config has `false` today)
   -> v = 0, hazards on -> VERDICT B.

## 5. Risks

1. Autoware 1.5.0 fully on rmw_zenoh_cpp (Humble 0.1.9) is unproven here.
   - Nothing in the repo or autosdv runs Autoware on rmw_zenoh. The
     autoware.org "Driving Autoware with Zenoh" post (2023) used
     zenoh-bridge-dds, not rmw_zenoh.
   - The default rmw_zenoh peer config is `peer_to_peer`: every process meshes
     with every other. play_launch's default isolated mode forks ~119
     processes; autosdv measured that. Use `--container-mode observable`
     (49 processes) or stock `ros2 launch` containers.
   - The 28 MB transient-local pointcloud map and the ~826-topic graph
     (play_log/latest/discovered_topic_types.tsv) are the loads to watch.
   - Gate: run this on the HOST first, outside any container:
     `RMW_IMPLEMENTATION=rmw_zenoh_cpp`, `ros2 run rmw_zenoh_cpp rmw_zenohd`,
     then `just autoware`, `demo/scenario_driver.py`, and the native_sim
     island. That needs a zenoh native_sim island build; today native_sim is
     Cyclone (docs/emulation.md:13).
   - If it fails, use Alternative B, the CDR relay.
2. Serial bandwidth (section 3.3) and the flaky serial handshake. For the
   latter, experiments/serial-interop/README.md reports "roughly one run in
   three establishes a link", although W7 saw 6 of 6 with the island image.
   Both are independent of the container, but the container must own the
   router config (downsampling) and the device.
3. RViz from a container.
   - X11 socket passthrough needs xhost and matching UID; Wayland hosts need
     XWayland.
   - Software GL gives 2 fps with the stock autoware.rviz, because of the
     PointCloudMap. Disable that display or use GPU passthrough
     (`--device /dev/dri` for Intel/AMD, or `--gpus all` with the nvidia
     runtime).
   - Expect ~90 s of blank viewport after "Startup complete" (autosdv).
   - Lowest risk: RViz on the host, or on a second laptop, over rmw_zenoh.
4. GPU: not needed for the planning simulator. The libnvinfer10 dependency is
   packaging only. The stub path saves 2.5-4.4 GB, but check it with `ldd` on
   every component the sim loads; play_log/latest shows 68 composables and
   none of the 31 TensorRT-linked libs.
5. Build time and size, estimates.
   - Download: 1.85 GiB at ~2.9 MB/s with aria2c, ~11 min; single stream,
     hours.
   - apt install of the ~1,500-package closure: ~10-20 min on the NVMe docker
     root (`/ext_sys/docker` on nvme0n1p2, 413 GB free; /home is the spinning
     disk and is not involved).
   - Final image: ~6-8 GB. The installed closure on the host sums to 7.7 GiB
     including a real libnvinfer, so ~5 GB with the stub, plus ~0.5 GB for
     the GUI layer.
   - autosdv's full image took ~70 min and 26.7 GB, but with CUDA devel and a
     workspace build.
   - Use a BuildKit cache mount for the deb so rebuilds do not re-download
     2 GB.
6. Network mode for zenoh.
   - rmw_zenoh needs no multicast (scouting is off; peers learn each other
     through the router's gossip). So the default bridge network works when
     router and nodes share the container.
   - `--network host` is only needed if other host processes must mesh as
     peers without port publishing. It then collides with any host
     rmw_zenohd on 7447; board-peer.just deliberately uses 7449 for this
     reason ("a router here on 7447 was joined by another session's QEMU
     island").
   - Peer-to-peer connections advertise container IPs. A host-side peer
     connecting in via `-p 7447` can see locators it cannot reach. Either set
     the container sessions to `mode: "client"` for outside tools, or use
     `--network host` for simplicity at the booth.
7. Clock and time source.
   - Container and host share the kernel CLOCK_REALTIME; Docker does not use
     time namespaces.
   - The board stamps with `nros_cpp_time_ns()`, the platform monotonic clock
     that boots near 0. The code already carries a "CLOCK-DOMAIN GUARD"
     because a host stamp minus a board stamp is ~1.8e9 s
     (src/autoware_mrm_emergency_stop_operator/.../mrm_emergency_stop_operator_core.cpp:163-171).
   - Consequences for the demo:
     - the island's own timeouts use island receive time, so they are
       correct;
     - host-side consumers must not age-check board stamps (vehicle_cmd_gate
       and RViz did not in the validated Cyclone runs, which used native_sim
       stamps);
     - end-to-end latency must be measured on host receive times or through
       the island trace, not by subtracting stamps;
     - rosbag timelines mix two clock domains.
   - `use_sim_time` stays false, as in the planning sim default. No gPTP over
     serial.
8. Serial device lifecycle.
   - A board reset does not re-enumerate the FTDI (it is on the DCD-LZ
     adapter), but unplugging it does. Pass the `/dev/serial/by-id/...` path.
     For hot-plug robustness use `--device-cgroup-rule='c 188:* rmw' -v /dev/serial:/dev/serial:ro`.
   - Nothing else may open the tty: no console `screen`, no host
     board-peer, while the container router holds it.
   - Flashing (pyocd / MCU-Link on ttyACM0) stays on the host.
9. Version pinning. rmw_zenoh 0.1.9 is what W7 proved against the board's
   zenoh-pico. The ROS apt repo only serves the latest build
   (0.1.9-1jammy.20260907 today), so pin by snapshot repo or vendor the .deb
   into the build context.

## 6. One-page summary

- Release: `autoware-localrepo 1.5.0-2`, 2026-05-05.
  - A 1.85 GiB `_all.deb` for Ubuntu 22.04 amd64, and one for JetPack 6.2.
    It unpacks a 459-package APT pool (1.9 GB) to `/opt/autoware/1.5.0/repo`
    and pins it at priority 1001.
  - ROS 2 Humble packages, suffixed `-1-5-0`, install to `/opt/autoware/1.5.0`.
  - Install: `dpkg -i`, `setup-prerequisites.sh`, `activate-dds-config.sh`,
    `apt install autoware-full-1-5-0`, then source `setup.bash` and
    `autoware-env.bash`.
  - It ships no RMW. It depends on rmw_cyclonedds_cpp, and `autoware-env.bash`
    forces Cyclone.
- autosdv@develop:
  - `setup/scripts/install-autoware-debian.sh` handles aria2c + sha256 + the
    install. It has a stale path to setup-prerequisites.sh for -2.
  - `docker/desktop/Dockerfile` is a proven 1.5.0 container: CUDA base, a
    libnvinfer10 workaround, the pool purged, RMW set in ENV, NET_ADMIN lo
    multicast, TurboVNC + noVNC. Measured 26.7 GB, 34/34 nodes.
  - Reuse its patterns, not its base image.
- Host demo:
  - Autoware runs via play_launch `planning_simulator.launch.xml` on
    rmw_cyclonedds_cpp, domain 10, with the stock MRM disabled by the
    demo/host_ws overlay.
  - The island consumes 9 topics (13-716 B) and publishes 13 (13-78 B).
  - The board talks rmw_zenoh over zenoh-pico serial at 115200 through
    `rmw_zenohd` (`just board-peer`).
- Proposal: one image, `ros:humble-ros-base-jammy` + the localrepo.
  - Install `ros-humble-autoware-launch-1-5-0` + config + theme; skip
    autoware-data; stub libnvinfer10.
  - Add `ros-humble-rmw-zenoh-cpp` and the demo overlay.
  - Add a `takeover_demo` package: `odd_monitor`, a 10 s `takeover_hmi`,
    `availability_gate` and `driver_button`.
  - The container runs `rmw_zenohd`, listening on `tcp/7447` and on
    `serial//dev/ttyUSB0` (passed with `--device`), with egress downsampling
    on the serial link. `RMW_IMPLEMENTATION=rmw_zenoh_cpp`, `ROS_DOMAIN_ID=10`.
  - RViz is optional. Lowest risk is RViz on the host over zenoh; otherwise
    noVNC or X11 with `/dev/dri`.
  - The takeover-expired path reuses the island's existing trigger
    (availability.autonomous false), so no board or contract change is
    needed.
- Blockers, in order:
  1. The UART budget: 115200 is 1.6-3.9x oversubscribed.
  2. The board image does not yet pass registration (W7/W8).
  3. Autoware on rmw_zenoh_cpp is unvalidated. Fallback: the Cyclone <->
     zenoh CDR relay.

## 7. Open questions

1. Which way should the demo take: all-zenoh Autoware (A), or Cyclone
   Autoware plus a CDR relay (B)? A is fewer moving parts. B keeps the
   validated Cyclone demo and makes rate limiting explicit.
2. Baud rate: can the Zephyr LPUART2 driver run at 921,600 or higher with
   DMA/idle-line RX, given the 4-byte FIFO? Or should the island contract's
   rates (30 Hz stop_mode_operator, 40 Hz inputs) be cut for the serial demo?
3. Is `/localization/kinematic_state` (716 B) needed on the board at all?
   mrm_handler uses it only for the stopped check. A slimmer
   VelocityReport-only path would save ~7.7 kB/s at 10 Hz, but changes the
   contract.
4. Does rmw_zenoh_cpp 0.1.9 implement what the contract assumes for
   `/system/operation_mode/availability`
   (`liveliness: manual_by_topic, lease_duration: 500ms`)? Or does the island
   rely solely on its own 0.5 s receive-time timeout? It does the latter
   today (mrm_handler_core.cpp:425).
5. With `Z_FEATURE_LOCAL_SUBSCRIBER=1`, does zenoh-pico also push
   island-internal puts (MrmBehaviorStatus at 10 and 30 Hz) over the serial
   link when the router has no remote subscriber? That would add ~2.5 kB/s
   outbound.
6. Driver takeover in the planning sim: is ADAPI
   `disable_autoware_control` or `/control/control_mode_request` MANUAL the
   right "driver has control" signal? And what should drive the vehicle
   afterwards: stream `/vehicle/command/manual_control_cmd`, or just coast?
7. Should MRM after TOR expiry be COMFORTABLE_STOP (Drive Pilot-like in-lane
   stop)? That needs `use_comfortable_stop: true` on the island, and the
   velocity-limit topics reaching the planner over the link.
8. Which booth hardware: one laptop with the board on USB, or a second screen
   for RViz? That decides GUI option (a), (b) or (c) and whether
   `--gpus`/`/dev/dri` is needed.
9. Pin rmw_zenoh via a ROS snapshot repo, or vendor the 0.1.9 .debs used in
   W7?
10. docs/topic-contract.md still describes domain 1/2 plus domain_bridge.
    Should it be updated to the contract.yaml truth before the demo write-up?

## Sources
- https://github.com/NEWSLabNTU/autoware-localrepo/releases/tag/1.5.0-2 (gh API), repo files 1.5.0/amd64/{README.md,Dockerfile,config.yaml}, README.md, setup.sh at tag 1.5.0-2
- host: /usr/share/autoware/1.5.0/*.sh, /opt/autoware/1.5.0/repo/Packages, autoware-config-1-5-0_1.5.0-2_all.deb (autoware-env.bash)
- scratchpad/d8/autosdv: setup/scripts/install-autoware-debian.sh, install-tensorrt.sh, install-ros2.sh, setup/autosdv_setup/registry.py, docker/desktop/{Dockerfile,README.md,entrypoint.sh}, docs/reports/gpu-less-simulation-and-rviz.md
- repo: justfile (autoware/_svc-sim/demo/island), scripts/env.sh, .envrc, demo/{README.md,scenario_driver.py,cyclonedds.xml,host_ws}, just/board-peer.just, experiments/serial-interop/{README.md,router-serial.json5}, docs/{demo-runbook.md,topic-contract.md,board-facts.md,boot-through.md,emulation.md}, src/safety_island_bringup/launch/safety_island.contract.yaml, src/autoware_mrm_handler/{config,src}, src/autoware_mrm_emergency_stop_operator/src, play_log/latest
- /opt/autoware/1.5.0/share/*/msg/*.msg; scratchpad/d8/sizes.py for CDR sizes
- https://autoware.org/driving-autoware-with-zenoh/ ; https://docs.ros.org/en/humble/p/rmw_zenoh_cpp/
