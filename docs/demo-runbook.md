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
just demo-host-ws   # clones ros2/domain_bridge (humble) if absent, colcon builds
                    # it + the MRM-shadowed tier4_system_launch
```

This overlay is what disables Autoware's stock MRM: `demo/host_ws/src/
tier4_system_launch/launch/system.launch.xml` keeps the upstream file shape
with the MRM operator and handler nodes commented out, so the island is the
only MRM path. `demo/host_ws/src/domain_bridge` is gitignored — hence the
clone step.

### 4. The run itself — validated 2026-07-31 (blocking recipes)

Blocking recipes — one terminal each, Ctrl-C (or exit) tears the recipe's
whole process tree down; `just demo-down` is crash cleanup only:

```sh
just autoware        # 1. planning_simulator, domain 1, stock MRM off
                     #    (blocks; prints "Startup complete" when ready)
just island          # 2. island + both bridge legs + control relay (blocks)
just demo            # 3. waits for the sim, then drive -> heartbeat fault ->
                     #    island MRM stop -> revive -> resume -> VERDICT

just demo-all        # all three, one command (add `native` for the native island)
just demo-down       # crash cleanup (recorded pgid groups + orphan sweep)
```

Expected outcome, from the validated run (2026-07-31): the vehicle drives
at ~4.2 m/s, the availability heartbeat is cut by SIGSTOPping the bridge
groups, the island goes `MRM_OPERATING / EMERGENCY_STOP` within 0.5 s and
the vehicle stops (4.24 → 0.00 m/s); the bridges are then resumed, the
island returns to `NORMAL`, and the vehicle resumes on its own —
`VERDICT: PASS`.

Re-run this end to end on the new machine and record the verdict. If it
passes, the reorganized recipe set is proven; if not, the logs to read are
`tmp_sim.log`, `tmp_island.log`, `tmp_bridge_fwd.log`, `tmp_bridge_rev.log`,
`tmp_relay.log` (all in the repo root, gitignored).

### 5. Open items not on the critical path

* `just resolve-model` (part of `just setup`) has not been exercised since
  play_launch was reinstalled — it needs the `resolve` verb, which only the
  >= 0.8.x line has. `src/safety_island_bringup/config/system_model.yaml` is
  committed, so the demo does not depend on re-running it.
* nano-ros #267: the island's `Control` message corrupts through
  domain_bridge's serialized rebroadcast, which is why `demo/control_relay.py`
  carries the emergency control d2 → d1 instead. Unchanged by this work.
* The VNC session on `:1` had died and was restarted by hand; nothing
  automates that. `just doctor` prints the display it will use but does not
  check that an X server is actually listening on it.
