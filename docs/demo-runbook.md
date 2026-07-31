# Demo runbook — bring-up on a fresh machine, and what is still open

Written 2026-07-31, at the point where the justfile was reorganized around the
three demo parts (commit `1a2de80`). The reorganization is done and pushed; the
end-to-end run has NOT been re-validated since, because the machine it was
being rebuilt on was too slow to finish the toolchain builds. The steps below
are what remains.

## Prerequisites (machine level)

| Thing | Where | Notes |
| --- | --- | --- |
| ROS 2 Humble | `/opt/ros/humble` | sourced by `.envrc` |
| Autoware 1.5.0 | `/opt/autoware/1.5.0` | host install, provides planning_simulator |
| nano-ros checkout | `$NANO_ROS_ROOT` (default `../nano-ros`) | `nros` CLI + cmake package |
| nano-ros SDK CycloneDDS | `~/.nros/sdk/cyclonedds/0.10.5-nros1` | `nros setup` provisions it; `$NROS_CYCLONEDDS_HOME` overrides |
| TurboVNC on `:1` | `vncserver :1` | RViz needs a display; `$VNC_DISPLAY` overrides |
| `just`, `direnv` | — | `direnv allow` once, then the env is checked on every cd |

`just doctor` reports all of the above (and the play_launch version) on demand.

## Remaining steps

### 1. play_launch >= 0.8.2 on PATH — THE BLOCKER

The demo launches Autoware with play_launch. The 0.5.x line stalls on
Autoware's busy composable containers and has no `resolve` verb, so >= 0.8.2
is required and both `just doctor` and `.envrc` reject anything older.

```sh
just setup-play-launch            # from the package index
# or, from a source checkout:
PLAY_LAUNCH_REPO=~/repos/play_launch just setup-play-launch force
```

State as of writing, on the slow machine: `~/.local/bin/play_launch` was a
wheel install that bundles a **0.5.1** binary even though the checkout's
`pyproject.toml` says 0.8.2 — the wheel had been built from stale artifacts.
The source-build path (`just build` in the play_launch checkout: colcon +
interception + `uv build --wheel`, then `pip install` that wheel) is what
produces a matching PATH binary.

Two failures hit while doing this, both worth expecting again:

* A half-populated `target/` made cargo fail with
  `couldn't read build/composition_interfaces/rosidl_cargo/.../build.rs` and
  missing `.rlib`s. Fix: `rm -rf target build install log` in the play_launch
  checkout, then rebuild.
* The rebuild takes a long time (colcon + a full release cargo build).

Verify with `play_launch --version` → `play_launch 0.8.2` (or newer).

### 2. Island images

```sh
just build          # native island   -> build/src/native_entry/native_entry
just zephyr-build   # Zephyr image    -> build-zephyr/zephyr/zephyr.exe
```

`just build` is green as of 2026-07-31 (verified on the slow machine). It
needed two fixes, both now committed:

* nano-ros `packages/rmw/cffi/CMakeLists.txt` resolved `../nros-rmw-abi`,
  which stopped existing when RFC-0054 moved the headers to
  `packages/core/nros-rmw-abi` — configure died with
  `add_subdirectory given source ... which is not an existing directory`.
  Fixed upstream in nano-ros `c53f65bf2`.
* `CycloneDDS_DIR` is now pinned by the `build` recipe to the nano-ros SDK
  Cyclone. With a ROS env sourced (which `.envrc` does), `find_package` picks
  `/opt/ros/humble`'s Cyclone instead and the link fails on undefined
  `ddsrt_malloc` / `ddsrt_free` / `ddsrt_strdup`.

`just zephyr-build` was still mid-flight when the machine was abandoned — it
recompiles every vendored interface crate (roughly a minute each), so budget
accordingly on the first run. It has no known failure; it just needs to
finish.

### 3. Demo overlay

```sh
just demo-host-ws   # colcon-builds the MRM-shadowed tier4_system_launch
```

This overlay is what disables Autoware's stock MRM: `demo/host_ws/src/
tier4_system_launch/launch/system.launch.xml` keeps the upstream file shape
with the MRM operator and handler nodes commented out, so the island is the
only MRM path. (The domain_bridge checkout is gone — the direct-connection
restructure removed the bridges and the relay entirely.)

### 4. The run itself — validated 2026-07-31 (direct connection)

The island sits directly on Autoware's domain 1: no bridges, no relay. Its
`mrm_state` and emergency commands reach `vehicle_cmd_gate` (and the RViz
AutowareStatePanel — the MRM row goes red live) natively. Blocking recipes
— one terminal each, Ctrl-C (or exit) tears the recipe's whole process
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
publisher — resolved from the live graph by the scenario), the island goes
`MRM_OPERATING / EMERGENCY_STOP` within 0.5 s and the vehicle stops
(4.26 → 0.00 m/s); the process is then SIGCONTed, the island returns to
`NORMAL`, and the vehicle resumes on its own — `VERDICT: PASS`.

If it fails, the logs to read are `tmp_sim.log` and `tmp_island.log`
(repo root, gitignored).

Discovery contract (the part that bit repeatedly): the native_sim island is
multicast-less (NSOS breaks cyclone's multicast waitset) and its sockets
only reach loopback-advertised locators, so EVERY host participant must run
the shared `demo/cyclonedds.xml` (lo-pinned, `ParticipantIndex auto`,
`MaxAutoParticipantIndex 120`) — `.envrc` exports it. The island's own
profile is compile-time: `CONFIG_NROS_CYCLONE_CONFIG_XML` in
`src/zephyr_entry/prj-cyclonedds.conf` (nano-ros issue 0367 wired the
knob), plus 16384-entry pthread mutex/cond pools and a 256 MiB malloc
arena — joining the full ~40-participant Autoware graph exhausts the old
sizes and cyclone abort()s at t=0.

### 5. Open items not on the critical path

* `just resolve-model` (part of `just setup`) has not been exercised since
  play_launch was reinstalled — it needs the `resolve` verb, which only the
  >= 0.8.x line has. `src/safety_island_bringup/config/system_model.yaml` is
  committed, so the demo does not depend on re-running it.
* Clock domains: the ported operators integrate `dt` from message stamps;
  host Autoware stamps are wall-clock while the island clock boots at ~0.
  The emergency stop operator carries a clamp (its unguarded first MRM tick
  computed `jerk × 1.8e9` and accelerated the vehicle to the sim cap);
  the deeper fix (epoch-synced island clock on native_sim) is a nano-ros
  question.
* The VNC session on `:1` had died and was restarted by hand; nothing
  automates that. `just doctor` prints the display it will use but does not
  check that an X server is actually listening on it.
