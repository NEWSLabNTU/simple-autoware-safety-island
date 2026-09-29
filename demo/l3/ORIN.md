# demo/l3 on the booth HPC: an NVIDIA Orin (phase8-W21)

The booth runs Autoware on an NVIDIA Orin (aarch64, JetPack/L4T) instead of
the x86 demo host. No Orin was attached when this was written (2026-09-29).
Everything below "Feasibility" was read from package indexes and upstream
sources on the x86 host; nothing was built or run for arm64. The
multi-arch Dockerfile (`container/Dockerfile`) and the recipe
`just l3-container-arm64` are **unbuilt and untested**. Repository
documentation only: none of this goes into the paper (no machine specs
there).

## Feasibility

| question | answer | evidence (2026-09-29) |
|---|---|---|
| Autoware 1.5.0 localrepo for arm64? | **yes** | release `1.5.0-2` carries `autoware-localrepo-1-5-0_1.5.0-2jetpack62_all.deb` (1,983,839,272 B, sha256 `e3187ca5a7e175aa...a064` from its `SHA256SUMS.txt`). Its pool index (`/opt/autoware/1.5.0/repo/Packages`, read out of the `.deb` by streaming the first 153,600 B of `data.tar.xz`): 459 packages, `453 Architecture: arm64`, `6 Architecture: all`, the same 459 names as the amd64 pool. `ros-humble-autoware-launch-1-5-0 0.48.0-0jammy arm64`; `autoware-ros-packages-1-5-0 1.5.0-1 all`, `autoware-config-1-5-0 1.5.0-2 all`, `autoware-theme-1-5-0 1.5.0-1 all` |
| ...installable on plain jammy arm64? | **yes, by name** | the image's install set (the three `autoware-*` packages, rmw_zenoh, ros-base, the tools) closes over 2076 packages with 0 unresolved Depends against Ubuntu jammy{,-updates,-security} main+universe arm64 (ports.ubuntu.com), ROS apt ros2-testing arm64, the pool and the stub (amd64, same method: 2082, 0 unresolved). Versions not checked; apt will. The pool was BUILT on `nvcr.io/nvidia/l4t-tensorrt:r10.3.0-devel` (JetPack 6.2, L4T r36.4, CUDA 12.6, TensorRT 10.3; `1.5.0/jp62/Dockerfile` in the localrepo repo), but declares no L4T or CUDA package: the only NVIDIA names are `libnvinfer10`, `libnvinfer-plugin10`, `libnvonnxparsers10`, from the same five packages as amd64 (`autoware-tensorrt-bevformer`, `-tensorrt-common`, `-tensorrt-plugins`, `bevdet-vendor`, `trt-batched-nms`) |
| TensorRT stub on arm64? | **yes** | equivs builds `sai-nvinfer-stub_10.0.0-stub1_all.deb`: Architecture `all` satisfies an arm64 Depends. Same three names as amd64 |
| rmw_zenoh_cpp 0.1.10 + zenoh_cpp_vendor 0.1.10 for arm64? | **yes, in testing only** | ros2-testing jammy `binary-arm64/Packages`: `ros-humble-rmw-zenoh-cpp 0.1.10-1jammy.20260916.050325`, `ros-humble-zenoh-cpp-vendor 0.1.10-1jammy.20260916.042209`. The build stamps differ from amd64 (`...20260915.210859` / `...20260915.201617`), so the Dockerfile pins per architecture. ros2 main arm64 still serves 0.1.9 (`0.1.9-1jammy.20260907.202349`) |
| rclcpp source build on arm64? | **expected yes; unbuilt** | the stage clones rclcpp 16.0.19, applies one patch, `colcon build`s one package: nothing architecture-specific. `git apply --check` of the patch passes on 16.0.19 and on 16.0.21 (`executor.cpp` identical in both). ROS apt now serves `ros-humble-rclcpp 16.0.21` on both architectures (main and testing); neither 16.0.20 nor 16.0.21 touches #2445 (CHANGELOG.rst at the tag; the issue is still open). The Dockerfile now pins the base by its multi-arch index digest so a rebuilt tag cannot move rclcpp under the patch; the arm64 variant's rclcpp version is unverified (same osrf revision `20e3ba6` and build day as the amd64 variant, which has 16.0.19). If it is not 16.0.19 the demo stage fails at its version check, loudly |
| base image for arm64? | **yes** | `ros:humble-ros-base-jammy@sha256:1813d3c8...` is an index with `linux/amd64` and `linux/arm64/v8`, both `org.opencontainers.image.revision 20e3ba685bb3...`, created 2026-09-09 |
| play_launch 0.12.0 for arm64? | **yes** | PyPI: `play_launch-0.12.0-py3-none-manylinux_2_35_aarch64.whl` (11,555,232 B); jammy's glibc is 2.35. The published 0.12.0 has `play_launch dump launch` (parse without spawning) |
| overlay + takeover_demo | **yes** | `tier4_system_launch` (launch files, CMake install only) and `takeover_demo` (ament_python): no compiled code |
| emulated arm64 build on this host | **possible, not run** | `/proc/sys/fs/binfmt_misc/qemu-aarch64`: `enabled`, `interpreter /usr/libexec/qemu-binfmt/aarch64-binfmt-P` (-> `qemu-aarch64-static`, qemu-user-static `1:6.2+dfsg-2ubuntu6.27`), `flags: PF`. `docker buildx ls`: the default builder (BuildKit v0.27.1) lists `linux/arm64`. No root needed. No `C` flag: setuid binaries under emulation would fail, and the build runs as root and needs none. Kernel 6.5.0-41, below the 6.8.0-50 on which the localrepo's jp62 README reports QEMU segfaults with ASLR on. Deferred to after the paper submission by the user's decision |

What only a real Orin can answer:

- **CUDA/TensorRT.** The image has none (the stub). The planning simulator
  loads no CUDA library on amd64 once `l3-autoware` passes
  `perception/enable_detection_failure:=false` (README trap 7). Whether the
  jp62 pool links MORE composables against CUDA than the amd64 pool (it was
  compiled with CUDA present, `CUDAARCHS=87`) is unknown until a composable
  fails to load with `libcudart.so.12` / `libnvinfer.so.10` missing. That
  shows on the first start, emulated or on the Orin.
- **A GPU image** (only if the stub path fails): base
  `nvcr.io/nvidia/l4t-jetpack:r36.4.0` (or `l4t-tensorrt:r10.3.0-runtime`)
  instead of `ros:humble-ros-base-jammy`, ROS Humble added by hand (the L4T
  images carry no ROS; the rclcpp stage assumes `/opt/ros/humble`), the
  host at JetPack 6.2 / L4T r36.4 to match, `--runtime nvidia`. Not
  written: the demo does not need the GPU, and an L4T base must match the
  host's L4T release.
- **Performance**: start completion, the planner chain's rate and gaps, and
  the island's HPC-loss rung (0.58 s) on the Orin's CPU. Nothing measured
  under QEMU is evidence for any of these.
- **The island link** over the Orin's USB-serial (FTDI) or UART.

## After the paper: the emulated build and smoke test (x86 host)

Not run (scope). When it is, from the repository root, on `/mnt/mx500`:

```sh
just l3-container-arm64          # tags sai-l3-autoware:1.5.0-arm64; never touches :1.5.0
I=sai-l3-autoware:1.5.0-arm64
docker image inspect -f '{{.Architecture}}' $I                      # arm64
docker run --rm --platform linux/arm64 $I bash -lc 'uname -m; ros2 pkg list | wc -l; ros2 pkg prefix autoware_launch'
docker run --rm --platform linux/arm64 $I bash -lc 'timeout 20 ros2 run rmw_zenoh_cpp rmw_zenohd; echo rc=$?'   # still up at the timeout: rc=124
docker run --rm --platform linux/arm64 $I bash -lc 'source /usr/local/bin/l3-env; play_launch dump launch autoware_launch planning_simulator.launch.xml map_path:=$L3_MAP vehicle_model:=sample_vehicle sensor_model:=sample_sensor_kit rviz:=false perception/enable_detection_failure:=false -o /tmp/m.yaml && grep -c "" /tmp/m.yaml'
docker run --rm --platform linux/arm64 $I bash -lc 'dpkg-query -W ros-humble-rclcpp ros-humble-rmw-zenoh-cpp ros-humble-zenoh-cpp-vendor sai-nvinfer-stub; dpkg-divert --list | grep rclcpp'
```

The unresolved-library count is the one emulation can answer that matters
for the Orin (compare with 38 on amd64, README trap 7):

```sh
docker run --rm --platform linux/arm64 $I bash -lc 'source /usr/local/bin/l3-env; find /opt/autoware/1.5.0/lib -name "*.so" | xargs -r ldd 2>/dev/null | grep "not found" | sort | uniq -c | sort -rn | head'
```

If the build fails at the rclcpp version check, the arm64 base variant is
not 16.0.19: pass `--build-arg RCLCPP_VERSION=<its version>` (the patch
applies to 16.0.21 too) and re-check trap 2b on the Orin.

## Orin rehearsal checklist

### 0. Before touching Docker: what is this Orin?

```sh
cat /etc/nv_tegra_release                 # L4T release; R36.4 = JetPack 6.2
head -1 /etc/os-release; uname -r         # jammy (JetPack 6) or focal (JetPack 5)
cat /proc/device-tree/model; nproc; free -g; df -h / /var/lib/docker
sudo nvpmodel -q                          # power mode; the demo wants MAXN
cat /sys/devices/system/cpu/cpu*/cpufreq/scaling_governor | sort | uniq -c
docker version; docker info | grep -i -E 'runtime|root dir|storage'
modinfo ftdi_sio | head -3                # the island cable's driver in the L4T kernel
```

Record them in this file (not in the paper). Decisions they drive:

- **JetPack 6.x (jammy host)**: host ROS tools install from ROS apt
  (`ros-humble-ros-base ros-humble-rmw-zenoh-cpp`), and `just l3-router`,
  `just l3-peer`, `just l3-nodes` run on the host as on x86.
- **JetPack 5.x (focal host)**: no Humble debs for the host. The image
  itself does not care (a CPU-only container carries its own userspace), but
  both routers and every `ros2` host command then run in the image: see
  step 4. A JetPack 6 reflash is the cleaner fix if there is time.
- **Docker's default runtime `nvidia`** (common on JetPack): it injects L4T
  libraries into every container. Harmless for the stub image in principle;
  if a composable picks up an injected library, run with `--runtime runc`.
- Disk: 5.3 GB image (x86 size) + 1.9 GB `.deb` in the BuildKit cache +
  the build's intermediate layers. Put Docker's root dir on NVMe if the
  module boots from eMMC or SD.

### 1. CPU governor and power mode

```sh
sudo nvpmodel -m 0          # MAXN (mode numbers differ per module; check nvpmodel -q --verbose)
sudo jetson_clocks          # pin clocks at max, fan up
sudo jetson_clocks --show
```

Both reset at reboot. Measure steps 3-5 once at the booth's setting and
note it; a throttled Orin under a warm booth is the likely cause of a slow
planner, not the middleware. `tegrastats` in a spare terminal shows
throttling while the demo runs.

### 2. Build the image natively

```sh
git clone ... && cd simple-autoware-safety-island
just l3-container                     # BuildKit picks TARGETARCH=arm64
docker image inspect -f '{{.Architecture}} {{.Size}}' sai-l3-autoware:1.5.0
```

Expect: the `.deb` download (aria2c, 10 connections; autosdv measured
2905 KB/s on an AGX Orin, about 11 min for 1.9 GB), the install, and the
rclcpp compile, which is the part x86 does in seconds and an Orin does in
minutes. Failure points, in order: the TARGETARCH check, the pinned
`rmw_zenoh` stamps (if ros2-testing moved on: read
`binary-arm64/Packages` and update the `_ARM64` ARGs), the localrepo sha256,
the rclcpp version check. Then the smoke test of the section above, without
`--platform`.

### 3. Start count (the gate W11 used)

Method as README "Start flake and silent planner": a start counts when
play_launch prints `Startup complete ... (nodes 31/31, containers 13/13,
composable 68/68)` within 120 s; Ctrl-C, wait 10 s (the zenoh lease),
again. W11's harness was a scratch script; the loop is:

```sh
just l3-router                                  # terminal 1
for i in $(seq 1 20); do                         # terminal 2
  t0=$(date +%s%N)
  timeout -s INT 120 just l3-autoware 2>&1 | tee /tmp/start-$i.log | grep -m1 'Startup complete' \
    && echo "start $i: COMPLETE t=$(( ($(date +%s%N) - t0) / 1000000 )) ms"
  docker rm -f sai-l3 >/dev/null 2>&1; sleep 10
done
```

(`grep -m1` ends the pipe on the first match, which leaves the container
running until the `docker rm -f`; the `timeout` catches a hung start. The
elapsed time includes `docker run`, so it reads above play_launch's own.) x86 reference: 40 of 40, 4.1-4.2 s each. Record n of 20 and the
time to complete. A hang shows as in trap 2; run `L3_DEBUG=1` and dump it
before changing anything.

Also record RSS: `docker stats --no-stream sai-l3` (3.0 GiB on x86). On a
16 GB or 8 GB module watch for the OOM killer in `dmesg`.

### 4. The island link

Board cable first, UART pins only if USB fails.

- **USB-serial (FTDI, the cable used on x86).** Same by-id path
  (`/dev/serial/by-id/usb-FTDI_FT232R_USB_UART_B001UCTE-if00-port0`).
  Check the 1 ms latency timer: `cat
  /sys/bus/usb-serial/devices/ttyUSB0/latency_timer` after `just l3-peer`
  sets it (16 ms otherwise, added to every island sample). JetPack host:
  `just l3-peer` unchanged. Focal host or no host ROS: run the gateway in
  the image (it carries `rmw_zenohd` 0.1.10, the same zenoh 1.8.0):

  ```sh
  docker run --rm -it --network host --device /dev/serial/by-id/...:/dev/ttyL3 \
    -v $PWD/demo/l3/router:/cfg:ro sai-l3-autoware:1.5.0 bash -lc '
      export ZENOH_ROUTER_CONFIG_URI=/cfg/island-gateway.json5
      export ZENOH_CONFIG_OVERRIDE="listen/endpoints=[\"serial//dev/ttyL3#baudrate=921600\",\"tcp/[::]:7449\"];connect/endpoints=[\"tcp/127.0.0.1:7447\"]"
      exec ros2 run rmw_zenoh_cpp rmw_zenohd'
  ```

  (the stock router likewise: `ros2 run rmw_zenoh_cpp rmw_zenohd` in a
  second container). First check that the arm64 `rmw_zenohd` opens the
  serial link at all (its log, or `fuser` on the tty); the amd64 build of
  the same source does. The gateway config is a copy of the 0.1.9 default;
  diff it against the image's 0.1.10 default (the command is in its header).
- **Orin UART (`/dev/ttyTHS*`)**: only if USB fails. 921,600 baud and
  3.3 V levels to confirm against the board; the island image's
  `CONFIG_NROS_ZENOH_LOCATOR` rate must match. Unmeasured.

Measure: the join (graph_watcher `JOIN` lines for the four island nodes),
then `just l3-run drive` and `just l3-run hpc` with the lines README "Step
2" quotes: `/system/fail_safe/mrm_state` 10.0 Hz with its largest gap
(118.9 ms on x86; `vehicle_cmd_gate` times out at 0.5 s), and MRM announced
after the last availability sample (0.64 s on x86).

### 5. Planner rate

`just l3-run drive`, then a route with `REROUTE=1` (trap 2b is a re-route
bug). Record `path_with_lane_id`, `lane_driving/trajectory`,
`/planning/trajectory`, `/control/command/control_cmd`: rate and largest
gap over 75 s. x86: 10.0 / 10.0 / 10.0 / 33.3 Hz, largest gaps 117 / 156 /
202 / 59 ms. The margin that matters: W7's island escalates on a gate
silent for 0.58 s, so a planner-chain gap near 0.5 s on the Orin is a
false HPC loss waiting to happen (trap 2c's client-mode numbers were
0.54-0.92 s, which is why the image uses peers with 8 Net workers).
`ZENOH_RUNTIME` worker count may want tuning on fewer cores; change one
thing at a time and repeat step 3.

### 6. Host tools

- `ros2` on the host: the `env -i` recipes (`l3-nodes`, `l3-rviz`) need
  Humble on the host (JetPack 6). Otherwise `just l3-nodes
  where=container`.
- RViz: on the Orin's own display over zenoh (`just l3-rviz`), or on a
  laptop joined to the Orin's router
  (`ZENOH_CONFIG_OVERRIDE='connect/endpoints=["tcp/<orin>:7447"]'`).
  Software GL on x86 drew 7 fps at 264 % CPU; on the Orin that CPU comes out
  of Autoware's budget. Prefer the laptop.
- `pyocd` (flashing the board) and the FTDI low-latency call need Python on
  the host; flash from the x86 laptop if the Orin lacks them.
- `just` and `git` on the host.

### Risks

| risk | why | what to do |
|---|---|---|
| JetPack 5 on the Orin | no Humble host debs | routers and `ros2` in the image (step 4); or reflash JetPack 6.2 |
| a composable links CUDA on arm64 that does not on amd64 | the jp62 pool was built with CUDA present | find it on the first start (`ldd` line above); disable its launch arg as trap 7 did, or the GPU image |
| arm64 base's rclcpp is not 16.0.19 | not verified | `--build-arg RCLCPP_VERSION=...`; the patch applies to 16.0.21 |
| ros2-testing moves or 0.1.10 reaches main | exact build stamps | update the `_ARM64` ARGs; drop the testing source once main has 0.1.10 |
| CPU governor, thermal throttling | booth temperature, default power mode | `nvpmodel -m 0`, `jetson_clocks`, `tegrastats` |
| fewer, slower cores than x86 | 57 processes, 3.0 GiB | start count and planner gaps first (steps 3, 5) before any island run |
| `nvidia` default Docker runtime | injects L4T libraries | `--runtime runc` if a load error names a Tegra library |
| RAM on 8/16 GB modules | 3.0 GiB RSS + `--shm-size 2g` + RViz | RViz off the Orin; watch `dmesg` |
| serial link on another USB host controller | FTDI latency timer, power | check `latency_timer`; a powered hub if the board browns out |
