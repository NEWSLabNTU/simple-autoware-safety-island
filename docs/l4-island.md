# L4 island and HPC contracts

The L4 safety island of RFC_L4_SafetyIslandDesign V1.0
(`docs/L4SafetyIsland_SoftwareDesign_GitHub.md`, commit f529052) as two
node interface contracts on launch trees, checked by `play_launch check`:

| Package | Launch tree | Contract | Platform file |
|---|---|---|---|
| `l4/l4_island_bringup` | `l4_island.launch.xml` (21 nodes, one S32Z280 image) | `l4_island.contract.yaml`: the B1-B4 ladder, 7 hazards | `l4_island.system.posix.yaml` (core placement) |
| `l4/l4_hpc_bringup` | `l4_hpc.launch.xml` (the H-nodes on the HPC) | `l4_hpc.contract.yaml`: what the HPC sends, `island_loss` | `l4_hpc.system.posix.yaml` |

Their messages are `src/safety_island_msgs` (RFC section 8) and the vendored
Autoware subsets under `src/` (island #16). Check them the way CI does:

    just contract-check

which builds the message packages as a ROS 2 overlay
(`scripts/build-host-msgs.sh`), sources it, and runs
`.github/check-contracts.sh` (`play_launch check --locked --strict` on every
contract under `src/` and `l4/`, with the pinned play_launch). Both L4
contracts are expected clean, with no `--expect` waiver, and every `when:`
and `commands` field resolved on the ament index.

## What is real and what is a placeholder

| Item | Status |
|---|---|
| Message types | **Real.** Every topic's type exists: `safety_island_msgs` or a vendored Autoware `.msg`. Every `when:` / `commands` field is checked |
| Autoware 2.0.0 node names | **Real** package, executable and node names, as Autoware 2.0.0 installs them: `autoware_control_command_gate`, `autoware_command_mode_decider`, `autoware_command_mode_switcher`, `autoware_mrm_steering_hold_stop_operator`, `autoware_pure_pursuit`, `autoware_trajectory_follower_node`, `autoware_velocity_smoother` |
| Autoware 2.0.0 wiring | **Real**, read from the 2.0.0 sources: availability -> decider -> `/system/command_mode/request` -> switcher -> the gate's `source/select` service -> `source/status`; the gate forwards the selected source's commands on arrival |
| Autoware 2.0.0 parameters | **Real** files (`l4/l4_island_bringup/config/`), verbatim from 2.0.0 except the gate's `rate` (see below) |
| New island nodes (N1-N19, I16) and HPC nodes (H4-H8) | **Placeholders**: the RFC's node names, each as a package of the same name. No such package exists; their paths and budgets are the RFC's or allocated inside its budgets |
| Any built node | **None.** This repository builds no L4 node. The contracts constrain code that does not exist yet |
| Numbers | All `source: requirement` (RFC or allocated) or derived by the checker. Nothing is measured. Integrity levels, requirement ids and FTTIs are illustrative: the HARA owns them |
| S32Z280 core placement | A POSIX proxy: `cpus` in the platform file stand for the lockstep R52 pair and the two split cores. Separate address spaces (MPU domains per partition) are not claimed; the grammar has no key for them |

The L4 packages live in `l4/`, not `src/`: `nros configure` resolves every
launch tree under `src/` with the resolver of the pinned nano-ros, and that
resolver (rlm v0.3.14) still refuses this contract (`dwell-expiry` from a
detector that is not the dwell's owner, fixed in later play_launch). Moving
them under `src/` waits for a nano-ros pin whose resolver accepts them and
for the nodes themselves.

## Results (play_launch 0.34.0, rlm v0.3.18)

| Contract | Verdict |
|---|---|
| `l4_island` | **2 errors (`level-within`, expected)**, 0 warnings, 6 acknowledged |
| `l4_hpc` | 0 errors, 0 warnings, 1 acknowledged |
| `safety_island` (the current image) | 0 errors, 6 warnings (`measured-unsupervised`), 2 acknowledged |

`l4_island` is registered in `.github/check-contracts.sh` as expected to
exit 1 with `level-within` as its only error: the contract states the RFC's
70 ms take-authority deadline as written, and the design does not meet it
(below). The `sched:` lines `check` prints are advisories on the POSIX
proxy's derived priorities, which are not the image's (nano-ros derives
those).

The contract uses the fallback-sequence grammar of rlm v0.3.18:

- B2 (`lane_keep_hold`) has `requires_lost: [hpc_alive, hpc_commands]`: a
  hazard that leaves the HPC running goes from B1 to B3 without B2's dwell.
- B2's T_hold is a range, `min_dwell: { duration: { min: 8s, max: 15s } }`:
  8 s is promised, the levels below are charged 15 s.
- B2's hand-back re-enters B1 (`exit.to: odd_degrade`); the twin mode
  `ads_constrained` and the separate `hpc_loss_authority` hazard are gone.
- The 70 ms take-authority deadline is `within: 70ms` on B2, judged from
  the fault to B2's settle (its first command out).
- B2's speed cap reads `$(param si_state_machine v_odd)` from the launch
  tree (one parameter file per ODD class).

Fault-reaction rows (`--explain`, ms), island:

| Hazard | Level | Detect | Dwells | Route | Settle | Total | Limit |
|---|---|---:|---:|---:|---:|---:|---:|
| hpc_loss | B2 lane keep hold | 30 | 0 | 12 | 50 | **92** | within 70 |
| hpc_link_integrity | B2 lane keep hold | 300 | 0 | 11 | 50 | **361** | within 70 |
| hpc_loss | B3 pull over | 30 | 15012 | 17 | 65000 | 80059 | FTTI 90000 |
| hpc_loss | B4 floor | 30 | 15012 | 44.03 | 6156.67 | 21242.70 | FTTI 90000 |
| hpc_link_integrity | B3 pull over | 300 | 15011 | 17 | 65000 | 80328 | FTTI 90000 |
| camera_loss | B4 floor | 150 | 0 | 39.03 | 6156.67 | 6345.70 | FTTI 10000 |
| camera_loss | B4 settle overrun | 150 | 0 | 6221.70 | 3228.33 | 9600.03 | FTTI 10000 |
| nominal_command_loss | MPC -> pure_pursuit | 67 | 0 | 31 | 14 | 112 | FTTI 1000 |
| odd_unsatisfiable | B3 pull over (B2 skipped) | 220 | 10007 | 17 | 65000 | 75244 | FTTI 120000 |
| odd_sensing_loss | B3 pull over (B2 skipped) | 150 | 10592 | 17 | 65000 | 75759 | FTTI 120000 |

With `requires_lost`, the two ODD hazards no longer pass through B2: their
B3 rows drop from 90261 and 90776 ms to 75244 and 75759 ms.

HPC: `island_loss` 100 (H6's age check) + 3 (link 1 + H6) + 8000 (the HPC's
own MRM, allocated) = 8103 of 10000.

**The RFC's 70 ms take-authority deadline (section 9.2) is not met.**

- On HPC heartbeat loss, B2 is entered 92 ms after the fault: N2's 30 ms
  silence timeout, a 12 ms route, and B2's 50 ms settle (first command out:
  pure_pursuit's next 50 Hz sample, the gate, I16's 100 Hz tick and the
  CAN FD hop). 22 ms over.
- On a late HPC trajectory (`hpc_link_integrity`), B2 is entered 361 ms
  after the fault: the gateway's 300 ms lateness window alone exceeds 70 ms.
  The RFC does not say whether its 70 ms applies to this fault.

This is a finding on the RFC's budget, not a checker limit; the numbers are
allocations, not measurements. Levers: a shorter heartbeat timeout (which
raises the false-trip risk; see play_launch #25), a faster fallback
controller tick, I16's tick, and a separate deadline for the lateness case.

## The gate's `rate` in Autoware 2.0.0

Read from `autoware_control_command_gate` 0.1.0 (Autoware 2.0.0,
autoware_universe 0.53.0):

- `rate` (`config/default.param.yaml`: **10.0**) drives `on_timer`
  (`src/control_command_gate.cpp`): `CommandSelector::update()`, which
  switches to the built-in stop when the selected source has timed out, and
  the status publishers;
- a control command is **forwarded on arrival** of the selected source's
  message (`CommandSubscription::on_control` -> `send_control`), not on the
  timer;
- the built-in stop publishes on its own fixed 10 Hz timer
  (`src/command/builtin.cpp`, not a parameter).

So the gate's tick is not on the take-authority route: what the route waits
for is the newly selected source's next sample, which the walk charges from
pure_pursuit's rate. The tick bounds the detection of a timed-out source: in
`nominal_command_loss` it is inside `select_fallback`'s allocated 31 ms (one
10 ms period at the island's `rate: 100.0`, one pure_pursuit period, 1 ms).
At 2.0.0's 10 Hz that term is 100 ms; the checker cannot see it, because no
reaction path is triggered by the gate's timer (a reaction must be a path the
violated input triggers), so the value is marked MUST MATCH in the contract
and in the parameter file.

## Changes from the design draft

- **G26**: `island.take_authority` ends at `/control/command/control_cmd`;
  the gate is modelled as 2.0.0 builds it (forward paths, `source/select`
  service, `rate` timer).
- **G20**: `links.hpc_tsn.clock: unsynced` (the island) and
  `links.island_tsn.clock: unsynced` (the HPC). Zephyr's S32 NETC driver has
  no PTP clock; every `max_age` on the link is judged by the receiver on its
  own clock (`mechanism: application`).
- **G27**: `island_loss` on the HPC side, detected by H6
  (`hpc_island_state_client`) on the island's `/si/out/state` (100 ms, five
  50 Hz periods); the island states the same number as `on_silence` on that
  topic (MUST MATCH).
- The seven `when:` predicates that were acknowledged as `when-field-unknown`
  (`camera_lanes`, `hpc_in_odd`, `odd_accepted`, `refuge`,
  `hpc_requalified`, and the hazards `camera_loss`, `odd_unsatisfiable`) are
  checked against `safety_island_msgs`; their acknowledgements are gone.
  `hpc_requalified` reads `IslandState.authority` (lost while it is not
  `AUTHORITY_HPC`).
- Invented internal types are replaced by real ones: N2 publishes
  `tier4_system_msgs/OperationModeAvailability` (RFC section 6.1), N3 the
  2.0.0 `CommandModeAvailability`, N7 `autoware_planning_msgs/Trajectory`.
- N3 takes N5's corridor verdict directly (B4 has no guard) and publishes
  the in-lane stop trigger from it; I16 sends on a 100 Hz tick (section 8.3).
- `nodes` instead of a component container, as the current image's launch
  tree; process separation was never claimed.

## Open items

- The 2.0.0 switcher's `source/select` call has no timeout
  (`ControlGateInterface::request`). The island port has to bound it or
  supervise the gate's output. play_launch 0.34.0 no longer draws
  `call-unbounded-mrc` on this ladder, so the contract carries it as a
  comment only.
- Take authority misses the RFC's 70 ms (92 ms on heartbeat loss, 361 ms on
  a late trajectory; above). To raise with the RFC working group.
- The gate's `rate` is not derived into any row (above).
- No rule compares the two contracts (each MUST MATCH pair is a comment).
- The trajectory the island receives needs a nano-ros codegen cap of 250
  points (RFC section 7, H5) once a node subscribes to it; `just l4-msgs`
  currently derives its bound from the blanket sequence cap.
- Everything under "placeholder" above.
