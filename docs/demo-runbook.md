# Demo runbook - the board demo on a fresh machine

**Validated 2026-10-13 (phase9-W21)**, on the demo host, by following this
file from a fresh worktree of `main` to three passing acts (encore, a, b) on
the MR-CANHUBK344; the SUMMARY lines are under "Validation record" at the end.
This is the path the RTSS demo runs: the island on the board, its zenoh
session over the serial link to a gateway router on the host, Autoware 1.5.0
on rmw_zenoh_cpp in a container, everything driven by
`tools/timeline/run-board.sh`. The measurements and the traps behind each
setting are in demo/l3/README.md; the earlier Cyclone/native_sim demo is
labelled "Legacy" at the end of this file.

## 0. The one rule: a clean shell

This host's login shell is not a clean one. `.envrc` (through
`scripts/env.sh`) exports the Cyclone RMW and `CYCLONEDDS_URI`, and, once
`just demo-host-ws` has been built, puts `demo/host_ws/install` (the
Cyclone-era overlay with the MRM nodes commented out) ahead of
`/opt/autoware/1.5.0`. From such a shell an Autoware contract check parses
163 scopes / 33 nodes / 2 manifests instead of 169 / 34 / 4 and every MRM
hazard reads `hazard-unguarded`, with no message saying why.

- Run every step below through `scripts/ienv.sh '<command>'`: `env -i` with a
  minimal PATH, then `scripts/env.sh` for this checkout only, so an inherited
  `NANO_ROS_ROOT`, another worktree's direnv or a sibling nano-ros cannot
  reach the build.
- Run every Autoware check under `env -i` with only
  `/opt/ros/humble/setup.bash` and `/opt/autoware/1.5.0/setup.bash` sourced,
  never from a direnv shell. `just l3-check`, the `l3-*` recipes and
  run-board.sh already do this themselves (just/l3-demo.just `_l3-host`,
  `l3-check`; demo/l3/container/bin/l3-env).
- The zenoh path does not need `just demo-host-ws` or `just setup` (both
  build the Cyclone overlay above); its own overlay is `build/l3-host-ws`.

## 1. Prerequisites (machine level)

| Thing | Where / check | Notes |
| --- | --- | --- |
| Ubuntu 22.04 + ROS 2 Humble | `/opt/ros/humble` | |
| rmw_zenoh_cpp 0.1.10 | `dpkg-query -W ros-humble-rmw-zenoh-cpp ros-humble-zenoh-cpp-vendor` -> `0.1.10-1jammy.20260915.*` | from ROS apt **testing**, held (`apt-mark hold`): 0.1.9 loses wakeups (demo/l3/README.md trap 2a). The host runs the stock router, the island gateway and run-board.sh's gate, probe and scenario on it |
| Autoware 1.5.0 | `/opt/autoware/1.5.0` | `just l3-host-ws` and `just l3-rviz` build and run against it. Its own `setup.bash` exports the Cyclone RMW and a `CYCLONEDDS_URI` (trap 8); the `l3-*` scripts override both |
| Docker with BuildKit | `docker buildx version`; your user in `docker` | the Autoware image is 5.3 GB |
| `just`, `git`, `uv` | `command -v` | uv makes the Zephyr 4.4 py3.12 venv |
| GNU parallel | `command -v parallel` | `just doctor` fails without it |
| pyserial | `python3 -c 'import serial'` | `just l3-peer` sets the FTDI low-latency flag with it (else 16 ms per frame) |
| pyocd 0.44 | `pyocd --version` (`pip install --user pyocd`) | flash, reset and the SWD readout |
| MCU-Link probe on the board's SWD | `pyocd list` shows it | never `pyocd erase --chip` (justfile `board-flash`) |
| DCD-LZ FTDI cable on lpuart2 | `ls /dev/serial/by-id/` | this host's is `usb-FTDI_FT232R_USB_UART_B001UCTE-if00-port0`; another machine exports `L3_PEER_TTY=/dev/serial/by-id/<its adapter>` (read by `just l3-peer` and run-board.sh) |
| disk | `~/.nros` (shared nros store) | Zephyr 4.4 workspace, its venv, SDK 1.0.1, hal_nxp (~1.3 GB) |
| an X display | `just doctor` checks it | only for RViz and the buttons window; **`:1` on the demo host is a user's desktop session**, not a demo VNC (trap 12): use your own (`vncserver :N`, `VNC_DISPLAY=:N`) |

## 2. Clone and submodules

```sh
git clone https://github.com/NEWSLabNTU/simple-autoware-safety-island.git
cd simple-autoware-safety-island
git submodule update --init third-party/nano-ros
git -C third-party/nano-ros submodule update --init \
    packages/cli/third-party/play_launch packages/rmw/zenoh/zpico-sys/zenoh-pico
```

Not `--recursive`: that also clones nano-ros's PX4, NuttX, Cyclone, XRCE and
QEMU trees, none of which this build reads. The nano-ros clone is large (it
took over 20 min from GitHub here; `--reference <an existing nano-ros
clone>` makes it seconds).

## 3. The nano-ros tools

```sh
scripts/ienv.sh '(cd third-party/nano-ros && just setup-cli)'
scripts/ienv.sh '(cd third-party/nano-ros && just setup-launch-resolve)'
```

About a minute with a warm sccache. Re-run both after any change of the
nano-ros pin or of its play_launch submodule; `just doctor` says which.

- After `setup-launch-resolve` the doctor warns that play_launch has a
  modified `src/ros-launch-resolve/parser/Cargo.lock`. Harmless at this pin
  (nano-ros issue 1863, fixed after it); `git -C
  third-party/nano-ros/packages/cli/third-party/play_launch checkout
  src/ros-launch-resolve/parser/Cargo.lock` clears it.
- Build and check the resolver in the same locale. At this pin its
  freshness stamp sorts in the caller's locale, so a resolver built under
  `C.UTF-8` (what `scripts/ienv.sh` sets) reads STALE to
  `check-launch-resolve-fresh.sh` under `en_US.UTF-8` (nano-ros issue 1869,
  fixed after this pin). `just doctor` accepts either.

## 4. play_launch and the doctor

```sh
scripts/ienv.sh 'just setup-play-launch'     # play_launch >= 0.16.0 into ~/.local/bin
scripts/ienv.sh 'just doctor'
```

The minimum is the CI pin (`PLAY_LAUNCH_VERSION`, .github/workflows/check.yml),
0.16.0: 0.14.x and older reject the demo contracts' timer `jitter` key, 0.15.x
does not charge it, and 0.12.0 rejects the island contract without naming a
version. A source build instead of the package index:
`PLAY_LAUNCH_REPO=<checkout> just setup-play-launch force`.

`just doctor` ends in `doctor: OK (...)`. Its findings each name their
command, in order: the nano-ros pin, the nested submodules, `setup-cli`,
`setup-launch-resolve`, play_launch, cmake, GNU parallel, ROS, Autoware. Two
warnings do not fail it: no X server, and the real-time limit (section 8).

## 5. The Zephyr 4.4 toolchain

```sh
scripts/ienv.sh 'just board-setup'
scripts/ienv.sh 'just board-doctor'
```

`board-setup` provisions into the shared nros store (`~/.nros`): the Zephyr
4.4 west workspace and its py3.12 venv (`.venv312`, made with uv), the
Zephyr SDK 1.0.1 and its installer, hal_nxp at the revision Zephyr's
`west.yml` names, and this repo's `patches/zephyr/0001` (DTCM relocation).
Idempotent: on a provisioned host it takes seconds; re-run it after any
`west update`. `board-doctor` should end with `[OK] one ROS domain
everywhere: 10` and show the probe.

Then the one package the store's venv lacks at this pin (nano-ros issue
1870, fixed after it): Zephyr's size reports import `anytree`, so without it
`just board-build` prints `board-size: rom_report failed (advisory, the
image is fine): ModuleNotFoundError` for both reports.

```sh
uv pip install --python ~/.nros/workspaces/zephyr/4.4/.venv312/bin/python anytree
```

## 6. The model and the board image

```sh
scripts/ienv.sh 'just sync'          # the SystemModel, build/nros/models/...
scripts/ienv.sh 'just board-build'   # build-board/zephyr/zephyr.elf (runs sync too)
```

- `just sync` prints `no producer for <node> (metadata probe run failed ...
  declare_parameter (code=-16))` for the island's nodes and then `sync:
  done.`: known and harmless at this pin (phase-9 open items, section 5,
  item 4).
- `just board-build` exits 0 and ends with the rom and ram reports; the
  linker's own table is the footprint of record. Validated build: FLASH
  581,676 B, RAM 276,040 B (84.24 %), ITCM 12,800 B, DTCM 117,536 B (89.67 %,
  the 8 KiB headroom guard of phase9-C10 passes).
- `board-build: REFUSING this image -- a resolved knob did not reach the
  compile` on a first build: run it again, the second pass converges (the
  recipe says so).

## 7. The host side

```sh
scripts/ienv.sh 'just l3-host-ws'     # build/l3-host-ws: overlay, takeover_demo, the C++ gate (~20 s)
scripts/ienv.sh 'just l3-container'   # the Autoware image, sai-l3-autoware:1.5.0-c8
scripts/ienv.sh 'just l3-check'       # 14 contracts, the CI job, under env -i
```

- `l3-host-ws` is what run-board.sh's gate needs (its preflight refuses
  without it).
- `l3-container` tags `sai-l3-autoware:1.5.0-c8` (main's overlay with
  phase9-C8's diagnostic graph timeout), the tag `just l3-autoware`,
  `demo/l3/container/run.sh` and run-board.sh all default to. A cold build is
  about 7.7 min (the 1.85 GiB localrepo download is most of it); cached, a
  few seconds. The bare `sai-l3-autoware:1.5.0` tag on the demo host is W3's
  old image (no rmw_zenoh 0.1.10, no rclcpp patch): do not run it.
- `l3-check` ends `14 contract(s) checked; every verdict as expected`.
- The image launches Autoware with its own play_launch (0.12.0, the
  Dockerfile's `PLAY_LAUNCH_VERSION`): a launcher only. The checker of record
  is `l3-check`'s pinned 0.16.0 in `build/l3-ci`.

## 8. Real-time limits (optional, measured without)

The host availability gate (run-board.sh's default `RB_GATE`, through
`gate-rt`) runs SCHED_FIFO 20 with `mlockall` when the shell's rtprio limit
allows it, else SCHED_OTHER with `gate-rt: SCHED_FIFO 20 not permitted
(ulimit -r 0); running SCHED_OTHER` in `build/timeline/<id>/gate.stdout`.
Every round measured so far, this validation included, ran it SCHED_OTHER.
The container's copy needs nothing from the host: `run.sh` passes `--cap-add
SYS_NICE --ulimit rtprio=20 --ulimit memlock=-1`.

To give the host gate the real-time class, as root:

```sh
printf '%s\n' "$USER  -  rtprio   20" "$USER  -  memlock  unlimited" \
    > /etc/security/limits.d/90-$USER-rt.conf
```

and verify in the shell that will run run-board.sh (`just doctor` prints the
same): `ulimit -r` -> `20`. The file is read by `pam_limits` at login, so
only a NEW session gets it, and only one whose PAM stack runs `pam_limits`:
on the demo host `login`, `sshd` and `gdm-password` do, while `xrdp-sesman`
and anything started by the systemd user manager (a `screen` from a user
service, this validation's shell) do not and keep `ulimit -r` at 0. There,
add `session required pam_limits.so` to `/etc/pam.d/common-session`, or set
`LimitRTPRIO=20` for `user@.service`.

## 9. Run the acts

Check that nothing else uses the board or the demo: `docker ps` shows no
`sai-l3*` container and `pgrep -af run-board` nothing (run-board.sh's
preflight refuses either, and takes the demo lock
`${XDG_RUNTIME_DIR:-/tmp}/sai-demo.lock` itself; do not wrap it in `flock`).

```sh
scripts/ienv.sh 'tools/timeline/run-board.sh encore w21-e1'
scripts/ienv.sh 'tools/timeline/run-board.sh a w21-a1'
scripts/ienv.sh 'tools/timeline/run-board.sh b w21-b1'
```

Each run flashes `build-board/zephyr/zephyr.elf`, starts the stock router
(7447) and the gateway (`just l3-peer`, the serial link at 921,600 baud),
resets the board, waits for the island to join, starts Autoware in the
container until `Startup complete`, then the gate and the probe, settles
15 s, runs the act, reads the trace and the violation record over SWD,
tears everything down and prints the table, the VERDICT and one SUMMARY
line. Everything lands in `build/timeline/<id>/` (`run.log`, `summary.txt`).
About 70-80 s per act on a warm host (validation: encore 71 s, a 79 s, b
81 s, flash to SUMMARY).

- encore: HPC loss (the gate SIGSTOPped), the island's emergency stop, then
  recovery; a: ODD exit, the driver takes over after 3 s; b: ODD exit,
  nobody answers, the comfortable stop to standstill.
- Exit 0 PASS, 1 FAIL, 3 REFUSED (a preflight finding, one line naming it,
  before anything is flashed, or at the act), 4 VOID (the probe or the gate
  did not run through the act; the scenario's own verdict is not evidence).
- The preflight refuses above a 1-min load of 35 (`RB_LOAD_MAX`), after
  waiting up to 180 s (`RB_LOAD_WAIT`): an overloaded host makes Autoware
  withdraw availability and the island correctly escalates (phase9-C6).
- `--dry-run` prints every step; `--no-flash` keeps the image on the board
  (but still resets it; `--keep-boot` below does not);
  `--target qemu` runs the same act against the QEMU island
  (`just trace-qemu-build` first). `tools/timeline/run-board.sh --help` has
  every option and variable.

### Several acts on one boot (phase9-W2)

The acts above flash and reset the board each time. To run them back to
back on one boot (the booth), keep the island's link up between them and
re-arm the trace window instead:

```sh
scripts/ienv.sh 'tools/timeline/run-board.sh --keep-link encore w2-e2'
scripts/ienv.sh 'tools/timeline/run-board.sh --keep-boot --keep-link a w2-a2'
scripts/ienv.sh 'tools/timeline/run-board.sh --keep-boot b w2-b2'
```

- `--keep-link` leaves the gateway (and the router, if the run started it)
  up after the act, the island joined, and records their process groups in
  `build/timeline/link.state`. Autoware, the gate and the probe are still
  stopped, so the next act starts from a fresh Autoware as before.
- `--keep-boot` uses that link: no flash and no reset; at step 1 it re-arms
  the trace window (`readout.py --rearm-only`: `readout: re-armed: window 2
  since boot ...`), and the new window opens when this act's availability
  stream starts (docs/tracing.md section 8, "Re-arming"). Its preflight
  refuses without a live kept link (`REFUSED no kept link ...`), when the
  tty is held by anything but the kept gateway, or when `--elf` is not the
  image the kept link's run flashed. Add `--keep-link` again for one more
  act; the last act without it tears the link down.
- `run-board.sh --link-down` stops a kept link by hand (after an
  interrupted chain). A plain run refuses while a kept link holds the tty
  and says so.
- The SUMMARY of a re-armed act reads `trace-check PASS (window <n> of the
  boot)`; its `stored` count is the boot's (the violation record is never
  drained).
- Why the link is kept and not restarted: the island rejoined a restarted
  gateway, without a reset, only after 107 s (zenoh-pico's reconnect), so
  each act would wait out most of 2 minutes at step 4.

`--late-join` (phase9-W12) holds the island's core halted from step 1 and
resets it only after Autoware, the gate and the probe are up (step 6b): the
island joins a running Autoware.

The presenter's manual path (one terminal per part: `just l3-router`,
`l3-autoware`, `l3-takeover`, `l3-peer` then reset the board, `l3-run`,
`l3-rviz`, `l3-button`) is in demo/l3/README.md, "Run it". It uses the same
image and the same `L3_PEER_TTY`; run-board.sh is the path that records
evidence.

## 10. Host traps

Each of these cost a session on the demo host:

- `:1` is a user's desktop, not the demo's VNC (demo/l3/README.md trap 12).
- `ros2 topic echo` without `--no-daemon` answers for the wrong RMW: a daemon
  started under Cyclone answers for itself ("does not appear to be
  published" for a topic at 10 Hz; trap 9). Use `--no-daemon` or `just
  l3-nodes`.
- `/opt/autoware/1.5.0/setup.bash` itself exports `RMW_IMPLEMENTATION=
  rmw_cyclonedds_cpp` and a `CYCLONEDDS_URI`, not only `autoware-env.bash`
  (trap 8); `l3-env` sets the zenoh RMW after sourcing it.
- A shared domain is a shared namespace. The demo runs on domain 10. On
  Cyclone, two stacks on one domain leave no participant creatable and every
  host node dies with `rcl node's rmw handle is invalid` (legacy item below);
  on zenoh, a second stack on one host needs its own router port and domain
  (demo/l3/README.md, "Run it": `just l3-router 7461`).
- `pkill -f play_launch` (or any name pattern) hits every project on the
  box, and kills the shell running it when the pattern is in its own command
  line (trap 11). run-board.sh tears down only its own process groups; for
  the Cyclone path use `just demo-down`.
- The host overlay shadow above (section 0).

## Validation record

2026-10-13, phase9-W21, the demo host (load 5-8), a fresh worktree of `main`
at `13ff8e5` (nano-ros `43fc1c2f7`), every step above in order through
`scripts/ienv.sh`. The submodule clone used `--reference` to a local
nano-ros clone (a plain one from GitHub had not finished in 20 min). The
image: `just board-build` exit 0, ELF sha256 `0ebd641254a98cf0...`, the
region table of section 6; `sai-l3-autoware:1.5.0-c8` rebuilt fully cached
(the same image id, `412a94ab5a40...`); `just l3-check` 14/14. The host
gate ran SCHED_OTHER (`ulimit -r` 0 in this shell, section 8).

```
SUMMARY w21-e1 encore: PASS; load 5.33 at act; table 8/8 PASS, total 3522.30 of 4909.67 ms; trace-check PASS; stored 1 (silence-runtime x1); serial in act 0/0 (overruns/bad frames); heap peak 66184 of 107008 B
SUMMARY w21-a1 a: PASS; load 7.89 at act; table 6/6 PASS; trace-check PASS; stored 1 (silence-runtime x1); serial in act 0/0 (overruns/bad frames); heap peak 66184 of 107008 B
SUMMARY w21-b1 b: PASS; load 7.94 at act; table 15/15 PASS, total 15350.55 of 20450.67 ms; trace-check PASS; stored 1 (silence-runtime x1); serial in act 0/0 (overruns/bad frames); heap peak 66232 of 107008 B
```

"stored 1 (silence-runtime x1)" is the known
`silence-runtime /mrm_handler/operation_mode_availability` verdict at
arming (phase-9 open items, W3); every act has it.

2026-10-13, phase9-W2, the same worktree on branch `phase9-w2-w12` (ELF
sha256 `cc55cfcc7a4a4cfd...`), three acts on one boot with section 9's
"Several acts on one boot" commands:

```
SUMMARY w2-e2 encore: PASS; load 16.10 at act; table 8/8 PASS, total 3472.83 of 4909.67 ms; trace-check PASS; stored 1 (silence-runtime x1); serial in act 0/0 (overruns/bad frames); heap peak 66432 of 107008 B
SUMMARY w2-a2 a: PASS; load 20.93 at act; table 6/6 PASS; trace-check PASS (window 2 of the boot); stored 1 (silence-runtime x1); serial in act 0/0 (overruns/bad frames); heap peak 66432 of 107008 B
SUMMARY w2-b2 b: PASS; load 29.62 at act; table 15/15 PASS, total 15698.33 of 20450.67 ms; trace-check PASS (window 3 of the boot); stored 1 (silence-runtime x1); serial in act 0/0 (overruns/bad frames); heap peak 66432 of 107008 B
```

## Legacy: the Cyclone / native_sim demo (phases 2-7)

`just autoware` / `island` / `demo` / `demo-all`, the native and native_sim
islands on CycloneDDS with Autoware on the host. Superseded by the zenoh
board path above for the RTSS demo and **not re-validated since
2026-07-31**; kept because the recipes still exist and the overlay's
defaults keep it working in principle. Prerequisites beyond section 1: the
nano-ros SDK CycloneDDS (`~/.nros/sdk/cyclonedds/0.10.5-nros1`, `nros setup`
provisions it; `$NROS_CYCLONEDDS_HOME` overrides) and `just setup` (which
also builds the `demo/host_ws` overlay of section 0).

### Island images

```sh
just build          # native island   -> build/src/native_entry/native_entry
just zephyr-build   # Zephyr image    -> build-zephyr/zephyr/zephyr.exe
```

`just build` is green as of 2026-07-31 (verified on the slow machine). It
needed two fixes, both now committed:

* nano-ros `packages/rmw/cffi/CMakeLists.txt` resolved `../nros-rmw-abi`,
  which stopped existing when RFC-0054 moved the headers to
  `packages/core/nros-rmw-abi` -- configure died with
  `add_subdirectory given source ... which is not an existing directory`.
  Fixed upstream in nano-ros `c53f65bf2`.
* `CycloneDDS_DIR` is now pinned by the `build` recipe to the nano-ros SDK
  Cyclone. With a ROS env sourced (which `.envrc` does), `find_package` picks
  `/opt/ros/humble`'s Cyclone instead and the link fails on undefined
  `ddsrt_malloc` / `ddsrt_free` / `ddsrt_strdup`.

`just zephyr-build` was still mid-flight when the machine was abandoned -- it
recompiles every vendored interface crate (roughly a minute each), so budget
accordingly on the first run. It has no known failure; it just needs to
finish.

### Demo overlay

```sh
just demo-host-ws   # colcon-builds the MRM-shadowed tier4_system_launch
```

This overlay is what disables Autoware's stock MRM: `demo/host_ws/src/
tier4_system_launch/launch/system.launch.xml` keeps the upstream file shape
with the MRM operator and handler nodes commented out, so the island is the
only MRM path. (The domain_bridge checkout is gone -- the direct-connection
restructure removed the bridges and the relay entirely.)

### The run itself (validated 2026-07-31, direct connection)

The island sits directly on Autoware's domain 1: no bridges, no relay. Its
`mrm_state` and emergency commands reach `vehicle_cmd_gate` (and the RViz
AutowareStatePanel -- the MRM row goes red live) natively. Blocking recipes
-- one terminal each, Ctrl-C (or exit) tears the recipe's whole process
tree down; `just demo-down` is crash cleanup only:

```sh
just autoware        # 1. planning_simulator, domain 1, stock MRM off
                     #    (blocks; prints "Startup complete" when ready)
just island          # 2. the island, domain 1 direct (blocks)
just demo            # 3. waits for the sim, then drive -> heartbeat fault ->
                     #    island MRM stop -> revive -> resume -> VERDICT

just demo-all        # all three, one command (add `native` for the native island)
just demo-down       # crash cleanup (recorded pgid groups + orphan sweep)
```

Expected outcome, from the validated runs (2026-07-31, twice): the vehicle
drives at ~4.3 m/s, the availability heartbeat is cut by SIGSTOPping the
`converter_node` process (the `/system/operation_mode/availability`
publisher -- resolved from the live graph by the scenario), the island goes
`MRM_OPERATING / EMERGENCY_STOP` within 0.5 s and the vehicle stops
(4.26 -> 0.00 m/s); the process is then SIGCONTed, the island returns to
`NORMAL`, and the vehicle resumes on its own -- `VERDICT: PASS`.

If it fails, the logs to read are `tmp_sim.log` and `tmp_island.log`
(repo root, gitignored).

Discovery contract (the part that bit repeatedly): the native_sim island is
multicast-less (NSOS breaks cyclone's multicast waitset) and its sockets
only reach loopback-advertised locators, so EVERY host participant must run
the shared `demo/cyclonedds.xml` (lo-pinned, `ParticipantIndex auto`,
`MaxAutoParticipantIndex 120`) -- `.envrc` exports it. The island's own
profile is compile-time: `CONFIG_NROS_CYCLONE_CONFIG_XML` in
`src/native_sim_entry/prj-cyclonedds.conf` (nano-ros issue 0367 wired the
knob), plus a 256 MiB malloc arena.

The pthread mutex/cond pools used to be part of that sizing story and no
longer are. Cyclone took a pool mutex per DDS entity and per addrset, so
joining the full ~40-participant graph exhausted 16384 slots ~19 s in and
died as an anonymous `abort()` (nano-ros issue 0371); the pools had been
walked 256 -> 16384 -> 131072 chasing graph size. Cyclone on Zephyr now
uses a native ddsrt sync backend (embedded `k_mutex`/`k_condvar`, nano-ros
issue 0496), takes no pool slots at all, and the knobs are back at the 256
default. If you ever see the pool named in an abort again, that backend is
not in the build.

### Open items of that path

* The model is no longer committed. `just sync` (part of `just setup`, and a
  dependency of `just build` / `just zephyr-build` / `just board-build`)
  resolves it into `build/nros/models/safety_island_bringup/system_model.yaml`
  and costs 0.08 s when nothing changed. It needs play_launch's `resolve`
  verb (0.8.x and later), and the island contract needs 0.13.0 (the CI pin is 0.16.0), so
  `just doctor` checks the version.
* Clock domains: the ported operators integrate `dt` from message stamps;
  host Autoware stamps are wall-clock while the island clock boots at ~0.
  The emergency stop operator carries a clamp (its unguarded first MRM tick
  computed `jerk x 1.8e9` and accelerated the vehicle to the sim cap);
  the deeper fix (epoch-synced island clock on native_sim) is a nano-ros
  question.
* The VNC session on `:1` had died and was restarted by hand; nothing
  automates that. `just doctor` now checks that an X server answers on the
  display it prints (`xset q`, else the /tmp/.X11-unix socket) and warns,
  without failing, when none does (phase9-W22).
* **This build host is shared, and a DDS domain is a shared namespace.** The
  demo runs on domain **10** (`ROS_DOMAIN_ID` in `.envrc` +
  `CONFIG_NROS_CYCLONE_DOMAIN_ID` in the island's Kconfig fragment, which must
  stay in step because the island bakes its domain at compile time). Another
  project's Autoware has occupied domains 1-3. Two stacks on one domain
  contend for participant indices and see each other's topics, and the symptom
  is not obvious: no cyclone participant can be created on the domain at all,
  so every host node dies with `rcl node's rmw handle is invalid` and the sim
  half-starts (18/33 nodes, 0/13 containers) -- which reads as a bug in
  whatever you changed last. To confirm it is the domain and not your change:
  a plain `rclpy` node on that domain fails for ANY config including no
  config, while the same node on an unused domain, or on fastrtps, succeeds.
* **`just demo-down` is scoped to this checkout; ad-hoc `pkill` is not.** The
  sweep discriminates on this checkout's `CYCLONEDDS_URI`, so it cleans our
  ~110 processes and leaves other projects' Autoware alone. A name-based
  `pkill -f play_launch` hits every project on the box -- one killed this
  demo's sim mid-scenario (SIGTERM at "driving for 15s"), and conversely
  another agent's cleanup can kill ours. Prefer `just demo-down`.
* Two scenario flakes under load, both timing rather than island behaviour.
  Neither has been chased down; both are worth knowing before reading a FAIL
  as a regression:
  - The initial `ChangeOperationMode` (`== 3. engage autonomous ==`) can
    return `success=False` for all 8 attempts, then engage on attempt 1 the
    very next run. Observed once; MRM operated and recovered correctly in the
    same run, so the island was healthy throughout.
  - `VERDICT: FAIL` on the velocity check when the vehicle is still
    accelerating at fault-injection time -- e.g. `stop=True v 0.57 -> 0.0`
    where the check wants a drop from ~4 m/s. The MRM cycle itself
    (`NORMAL -> MRM_OPERATING -> MRM_SUCCEEDED -> NORMAL`) completes. Read the
    verdict's own fields before blaming the island: `stop`, `mrm`, `recover`
    and `resume_v` tell you whether the safety path worked.
  A fix for the second would be to gate `== 5. cut the heartbeat ==` on the
  vehicle actually reaching a threshold speed rather than on `DRIVE_SECS`
  elapsing.
