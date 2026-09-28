# Brief D8-D: the RTSS@Work 2026 demo scenario (L3 takeover + MRM + HPC loss)

Design brief, read-only research, 2026-09-28. Nothing here is implemented.
Sources read: simple-autoware-safety-island (SAI) at `contract-params`
(e318253), ros-launch-manifest (rlm) v0.1.44, play_launch 87072fe9,
nano-ros-rt-eval ed1640a, Autoware 1.5.0 at /opt/autoware/1.5.0 (installed
share/ and lib/ only; no source tree on this host), autoware_sentinel
(for the vehicle_cmd_gate port).

Items marked VERIFY rest on reading binaries, launch files or memory of
upstream source rather than on a run. They are listed again in section 5.

---

## 0. The findings that shape everything else

1. **Autoware 1.5.0 has no takeover-request (TOR) concept.** No message,
   service or parameter in the installed tree mentions takeover. What it
   does have: `OperationModeState` (STOP/AUTONOMOUS/LOCAL/REMOTE,
   `is_autoware_control_enabled`), `ControlModeReport` (AUTONOMOUS=1,
   MANUAL=4), `/control/control_mode_request` (the planning simulator
   serves it) and the ADAPI `disable_autoware_control`. A TOR has to be
   added. The smallest place to add it is `mrm_handler`, which already
   holds the state machine and already subscribes to both inputs a TOR
   needs.
2. **The driver-response cancel already exists in the handler.**
   `updateMrmState()` leaves NORMAL for MRM_OPERATING only
   `if (is_control_mode_autonomous)`. A driver who switches the vehicle to
   MANUAL before the MRM starts stops it from ever starting. What is missing
   is the 10 s of waiting between "out of ODD" and "start MRM".
3. **The ODD exit is a value on a topic the island already reads.**
   `isEmergency()` is `!isAvailableCurrentOperationMode() || ... ||
   timeout`. So an ODD monitor on the HPC that clears
   `OperationModeAvailability.autonomous` is a value-domain fault. The
   handler then picks COMFORTABLE_STOP if `availability.comfortable_stop &&
   use_comfortable_stop`. An availability timeout always forces
   EMERGENCY_STOP, at any rung, and that escalation already exists in
   `getCurrentMrmBehavior()`.
4. **rlm already has `on: reported`.** It is checked:
   FDTI = the detector's publish period + its path `max_latency`
   (manifest_loader.rs ~2005). What it lacks is any way to say WHICH value.
   The runtime observer never reads payloads, so it cannot see a reported
   fault at all.
5. **`stop_mode_operator` does not matter for this demo.** In 1.5.0 it is
   launched only under `use_control_command_gate:=true`
   (tier4_control_launch/control.launch.xml, line 74). The demo uses
   vehicle_cmd_gate, so nothing consumes its `/system/stop_mode/*` outputs.
   It costs three 30 Hz inbound subscriptions over the link and three of
   the five TRANSIENT_LOCAL publishers that broke boot in W7/W8.
6. **Hazard lights in a comfortable stop do not reach the vehicle as
   wired (VERIFY).** vehicle_cmd_gate applies the island's
   `/system/emergency/{control,hazard_lights,...}` only when
   `mrm_state.behavior == EMERGENCY_STOP`. The sentinel port says the same
   ("MRM active with EMERGENCY_STOP behavior"). For COMFORTABLE_STOP the gate
   passes the planner's hazard command, which comes from
   `hazard_lights_selector`, whose system input is `/system/hazard_lights_cmd`.
   Drive Pilot's "hazards on" therefore needs one relay or remap.
7. **The link cannot carry the island's inputs as it is.** The only
   working link is serial at 115200 baud, about 11.5 kB/s per direction.
   `nav_msgs/Odometry` is 880 B (nxp-deployment.md), so 10 Hz is 8.8 kB/s
   before `control_cmd` at 30 Hz and before zenoh framing. The 100BASE-T1
   media converter has not been bought.
8. **The board has not yet run the island.** W8: the image links at
   323,112 of 327,680 B RAM and cannot reach FirstSpin while
   `param_services` is on (the heap is short by more than 100 KB; this
   waits on nano-ros phase-461 W6). The live demo lane must be native_sim
   (or QEMU) with the board as a stretch goal. Per the
   "slides carry only complete measurements" rule, the board goes on a slide
   only once it delivers the reaction.
9. **Two checker behaviours break a two-hazard, one-ladder contract**
   (section 1.6). (a) `ladder-rung-budget` checks every non-floor rung
   against the FTTI even when the hazard's own fault makes that rung
   unavailable. (b) The Linux observer records a reaction only from a host
   `Publish` of a sink, and the island's sinks are published off-host.

---

## 1. The scenario as contract vocabulary

### 1.1 The scenario, restated as behaviour

| # | Trigger (injected) | Expected behaviour | Rung reached |
|---|---|---|---|
| A | weather flag drops (or speed > bound) | TOR issued; driver presses "take over" within 10 s; control mode MANUAL; no MRM | manual (exit) |
| B | same, driver does nothing | TOR for 10 s; comfortable stop in lane, hazards on, to 0 m/s | comfortable_stop |
| C | availability stream stops (HPC loss) | 500 ms detection; emergency stop, hazards on | emergency_stop |
| D | B, then HPC loss during the comfortable stop | escalation to emergency stop (handler code path exists) | emergency_stop |
| E | A/B, then HPC loss during the TOR window | immediate emergency stop; the window is not waited out | emergency_stop |

### 1.2 What existing rlm constructs already cover

| Need | Construct | Status |
|---|---|---|
| HPC loss, 500 ms detection | `hazards.hpc_loss { guards, on: omission, ftti }`, handler sub `max_age: 500ms`, `on_violation {mechanism: application}` | exists, checked, traced (W3) |
| ODD exit as a detected fault | `on: reported` on `/system/operation_mode/availability`; FDTI from the ODD monitor's period + latency | exists; needs the HPC-side contract in the same tree so the publisher's path is known |
| Graded ladder, emergency as floor | `functions:`, `modes: {requires, fallback, reaction}`, `ladder-unterminated`, `ladder-rung-budget` | exists (phase 75; stage2-ladder fixture) |
| Severity to scheduling | `severity_levels`, `severity`, derived criticality (feeds/detects/reacts) | exists |
| Reaction route across the operate service | `cli` in path `output`, phase-82 service edge + sampling hop | exists |
| Plant share | `safe_state { emits, settle }` | exists, but settle is a constant (the W3 failure) |
| Driver as an event source | `trigger: spontaneous` ("caused outside the graph (operator ...)") | exists |
| Different requirement values per rung | `modes.<m>.overrides` | exists; not needed for the demo |

### 1.3 The gaps, each as a minimal proposal

Principle, taken from `operational-modes.md` ("mode transitions as
first-class edges ... deliberately not folded"): do not add general
transitions. Add ONE timed rung and ONE success exit. Everything else stays
selection by availability.

#### G1. A value-triggered hazard: `when:`

Today `on: reported` says "some node checks something". The demo needs the
contract to name the predicate, for three reasons: the observer can check
it, the plot can draw the ODD bound, and a function can be lost by value
rather than only by silence.

```yaml
hazards:
  odd_exit:
    guards: [/system/operation_mode/availability]
    on: reported
    when: { field: autonomous, equals: false }     # NEW

functions:
  hpc_alive:  [/system/operation_mode/availability]            # lost on silence
  hpc_in_odd:                                                  # NEW form: lost on value OR silence
    of: [/system/operation_mode/availability]
    when: { field: autonomous, equals: false }
```

Grammar: one scalar field (a dotted path is allowed), with one operator from
`equals | not_equals | lt | le | gt | ge`. The constant is a literal or a
message constant name (`MANUAL`). There are no conjunctions. A second
condition is a second function.

Checker:
- `when-requires-reported` (error): `when:` on a hazard whose `on:` does not
  include `reported`.
- `when-field-unknown` (error when the `.msg` resolves via the ament index
  from the topic's `type:`, warning when it cannot be resolved): the field
  does not exist or is not a scalar.
- Ladder selection learns fault classes. A `reported` fault removes the
  value functions on its topic. An omission, late or loss fault removes both
  kinds, because silence also means "not known to be in ODD".

Runtime, Linux: the interception layer carries 56-byte events with no
payload, so play_launch cannot evaluate `when`. The minimal answer is a
contract probe: a small rclpy node generated from the resolved model. It
subscribes to every topic named in a `when:` and writes `hazard-detected` /
`hazard-recovered` lines in the observer's JSONL schema, with the same
CLOCK_MONOTONIC. Later this could become a payload plugin in the
interception `.so`.

Runtime, nano-ros: nothing new. The predicate is application code in the
handler (`isAvailableCurrentOperationMode`). The contract describes it and
does not generate it.

Derivation into the image: none directly. Declaring the reaction path that
the reported fault triggers (G2) is what makes `gen_markers.py` emit its
markers.

#### G2. A timed rung: `window:` (the 10 s TOR)

```yaml
modes:
  takeover_request:
    requires: [hpc_alive, hpc_in_odd_hmi]    # see 1.4; skipped when the HPC is lost
    reaction: island.tor                     # scope path: guard -> TOR state topic
    window:                                  # NEW
      duration: 10s
      param: mrm_handler.takeover_request_timeout   # the number the image runs
```

Semantics: a windowed rung is transitional, not a safe state. The system
stays in it at most `duration` and then takes the next rung, even while this
one is still available. A scalar `window: 10s` also parses, but it is unbound
(see `window-unbound`).

Checker:
- `ladder-rung-budget` becomes cumulative. For rung k it checks
  `FDTI + sum over windowed rungs j < k that this hazard can land on of
  (route_j + window_j) + route_k + settle_k <= ftti`.
- `ladder-window-floor` (error): the last rung has a window. A floor you
  leave after a timeout is not a floor, the same sentence as
  `ladder-unterminated`.
- `window-param` (error): the named parameter's resolved launch value is not
  the declared duration. `window-unbound` (warning): no `param:`, so nothing
  in the image enforces the number. This follows the repo's existing
  pattern of restating `timeout_operation_mode_availability` as
  `max_age: 500ms`.
- The TOR rung is exempt from `reaction-unbudgeted`. Its sink is a
  notification and needs no `safe_state`.
- Window granularity: the handler notices expiry on its 10 Hz tick. The next
  rung's route therefore starts with `call_mrm`'s 110 ms, which is already
  its declared `max_latency`. No new term.

Runtime, Linux: a new observer event `mode-window` records rung entry and
exit (host takes of the TOR state topic and of the velocity limit) and the
measured dwell. It errors if the dwell exceeds the window plus one tick.

Runtime, nano-ros: nothing new. The window is a parameter in the existing
param store, sized from `params:`. The timer is the handler's existing
10 Hz tick.

Derivation into the image: through the parameter. The checker guarantees
that the contract value equals the value baked into the image. The new
contracted publisher (TOR state) and path grow the pools and the marker
table automatically.

Continuity worth one sentence on a slide: the stage2 L4 fixture had to
encode the design's `T_odd = 10 s` as an FTTI because no window construct
existed. G2 is that missing construct.

#### G3. A driver response that ends the ladder: `exit:`

```yaml
functions:
  driver_took_over:                               # value function (G1 form)
    of: [/vehicle/status/control_mode]
    when: { field: mode, equals: MANUAL }

modes:
  takeover_request:
    exit: { on: driver_took_over, to: manual }    # NEW
  manual:
    description: the driver drives; the ADS no longer commands the vehicle
    requires: []
```

Semantics: while this rung is active, the exit function holding ends the
ladder successfully in `to`. It is not a fallback rung and it gets no FTTI
check. The target is outside the ladder, and the check that matters is
"the window never expired while the driver had answered".

Checker:
- `mode-exit-unwired` (error): no node that implements this rung's reaction
  (the handler) subscribes to the exit function's topic with a path trigger.
  Without a trigger there is no TAKE marker and no evidence.
- `mode-exit-target` (error): `to:` is missing, or is a member of any
  `fallback:` list.
- Exit only on a windowed rung (error otherwise). This keeps "transitions"
  out of the grammar.

Runtime, Linux: the probe (G1) evaluates the exit predicate and emits
`mode-exit` with the response time since rung entry.

Runtime, nano-ros: the handler already subscribes to `control_mode`. The
contract gains a path `driver_exit: { trigger: { input: [control_mode] },
output: [takeover_request_state] }`, so the image traces the take
(`TAKE_MRM_HANDLER_CONTROL_MODE`). Declaring the exit in the contract is
what makes the island trace it.

Derivation: markers only.

#### G4. An entry speed for the settle term

W3 showed the island meeting its own terms while the vehicle missed the
FTTI, because the settle constant assumed 3.0 m/s and the demo braked from
4.23. The settle should be derived from the braking profile and an entry
speed, and the entry speed belongs to the hazard (the ODD bound).

```yaml
hazards:
  hpc_loss:
    entry_speed: 16.7          # NEW, m/s: the ODD speed bound; plain float, unit in the key's doc

nodes:
  mrm_emergency_stop_operator:
    paths:
      on_timer:
        safe_state:
          emits: emergency_control_cmd
          settle: { decel: target_acceleration, jerk: target_jerk }   # NEW form: params by name
```

The checker computes, per (hazard, rung), with a = |decel| and j = |jerk|:
`v_r = a^2 / (2 j)`; if `v0 <= v_r` then `t = sqrt(2 v0 / j)`, otherwise
`t = a/j + (v0 - v_r)/a`. This is exactly the arithmetic in the contract's
comment block: 3.0 m/s gives 2033.33 ms, and 4.23 m/s gives 2525.33 ms,
which matches W3's 2517-2527 ms.

Checker:
- `settle-derived` (info): prints the arithmetic.
- `settle-entry-missing` (warning): a profile with no `entry_speed` on the
  hazard. The check then falls back to a literal `settle` if one exists,
  otherwise the result is `reaction-unbudgeted`.
- `settle-param-unresolved` (error): the named parameter is not in the node's
  `params:` or has no resolved value.
- `settle-conflict` (warning): a literal settle and a profile disagree by
  more than 1 %.

Runtime, Linux: the logger records the velocity at the first braking command.
The plot raises "entry speed exceeded the declared bound", which is the W3
failure mode made visible.

Runtime, nano-ros: nothing. The operators already implement the profile.

Derivation: nothing new. The profile's parameters are the ones baked into
the image, so the checker and the image read one value.

#### Found while writing the demo contract (checker fixes, not grammar)

- **F1, ladder selection per hazard.** `ladder-rung-budget` (the
  `rungs.iter().take(len-1)` loop in manifest_loader.rs) checks every rung.
  With one ladder shared by `odd_exit` and `hpc_loss`, the comfortable-stop
  rung (18.4 s settle) would be checked against hpc_loss's 10 s FTTI, even
  though hpc_loss removes `hpc_alive`, which that rung requires. Fix: skip
  (and do not charge the window of) any rung that requires a function this
  fault removes. This is the same test `ladder-unterminated` already applies
  to the floor, with G1's fault classes.
- **F2, observer sinks published off-host.** `observe_hazards` pushes
  `sink_pubs` only on `EventKind::Publish`. The island publishes
  `/system/emergency/control_cmd` on the MCU, so the host sees only
  vehicle_cmd_gate's `Take`. Fix: when a sink's publisher is outside the
  instrumented set (contract `external`, or a non-host scope), count the
  first host `Take` and label the event `observed_at: take` so the link hop
  is not hidden.
- **F3, VERIFY: service-callback publishes.** The comfortable-stop operator
  publishes `max_velocity_candidates` inside its `operate` callback. Check
  that phase 82's walk continues from a server's callback path, i.e. that a
  path whose trigger names a `srv` endpoint is accepted. If it is not, this is
  one more small checker unit.

### 1.4 The demo contract, sketched (scope level plus the island deltas)

`hpc_in_odd_hmi` on the TOR rung is omitted below for brevity. The minimal
contract has the TOR rung require only `[hpc_alive]`.

```yaml
severity_levels: [QM, ASIL_A, ASIL_B, ASIL_C, ASIL_D]

functions:
  hpc_alive:  [/system/operation_mode/availability]
  hpc_in_odd: { of: [/system/operation_mode/availability], when: { field: autonomous, equals: false } }
  driver_took_over: { of: [/vehicle/status/control_mode], when: { field: mode, equals: MANUAL } }

hazards:
  odd_exit:                         # severities illustrative; HARA-owned
    severity: ASIL_B
    guards: [/system/operation_mode/availability]
    on: reported
    when: { field: autonomous, equals: false }
    entry_speed: 16.7
    ftti: 30s                       # a judgement, like the 3 s today; stated and checked
    reaction: l3_engaged
  hpc_loss:
    severity: ASIL_D
    guards: [/system/operation_mode/availability]
    on: omission
    entry_speed: 16.7
    ftti: 10s
    reaction: l3_engaged

modes:
  l3_engaged:
    requires: [hpc_alive, hpc_in_odd]
    fallback: [takeover_request, comfortable_stop, emergency_stop]
  takeover_request:
    requires: [hpc_alive]
    reaction: island.tor
    window: { duration: 10s, param: mrm_handler.takeover_request_timeout }
    exit: { on: driver_took_over, to: manual }
  comfortable_stop:
    requires: [hpc_alive]           # the HPC's planner executes the stop
    reaction: island.comfortable_stop
  emergency_stop:
    requires: []
    reaction: island.emergency_stop
  manual:
    requires: []

paths:
  island.tor:              { trigger: { input: [/system/operation_mode/availability] }, output: [/system/takeover_request/state], max_latency: 210ms }
  island.comfortable_stop: { trigger: { input: [/system/operation_mode/availability] }, output: [/control/command/control_cmd] }  # crosses the HPC planner (HPC contract)
  island.emergency_stop:   { trigger: { input: [/system/operation_mode/availability] }, output: [/system/emergency/control_cmd], max_latency: 210ms }
```

Island deltas:
- The handler gains the params `use_takeover_request: bool` and
  `takeover_request_timeout: double`, and a publisher
  `takeover_request_state` (`tier4_system_msgs/MrmBehaviorStatus` reused:
  AVAILABLE = idle, OPERATING = TOR active; this avoids a new message
  package on the island).
- `call_mrm.output` adds `takeover_request_state` and
  `comfortable_stop_operate`.
- The availability subscriber's `on_violation.on` becomes
  `[omission, reported]`.
- A new path `driver_exit`.
- `use_comfortable_stop: true`.
- The comfortable operator gets a `safe_state` with
  `settle: { decel: min_acceleration, jerk: min_jerk }`.
- `stop_mode_operator` gets `if: $(var with_stop_mode)`, default false in
  the demo.

The numbers the checker should print (ms; the planner hop of 300 ms is a
declared placeholder until it is measured):

| Hazard / rung | FDTI | TOR route + window | Rung route | Settle (v0 = 16.7) | Total | FTTI | Slack |
|---|---|---|---|---|---|---|---|
| odd_exit / comfortable | 120 (100 period + 20) | 110 + 10000 | 110 + 300 | 18366.67 | 29006.67 | 30000 | 993.33 |
| odd_exit / emergency (floor) | 120 | 110 + 10000 | 143.33 | 7513.33 | 17886.67 | 30000 | 12113.33 |
| hpc_loss / emergency (TOR, comfortable skipped by F1) | 500 | - | 143.33 | 7513.33 | 8156.67 | 10000 | 1843.33 |

One-line failing variants for slides, each naming exactly one term:
- `window: 12s`: `ladder-rung-budget` on comfortable_stop, total 31006.67 >
  30000.
- ODD bound or `entry_speed` 16.7 -> 19.4 (+10 km/h): the comfortable rung
  fails (settle 21066.67, total 31706.67), while the hpc_loss floor still
  fits (9236.67). The checker names the graded rung, not the floor.
- `window:` moved to `emergency_stop`: `ladder-window-floor`.
- Exit wired to a topic the handler does not read: `mode-exit-unwired`.

### 1.5 Why the TOR lives in mrm_handler and not in a fifth node

A proxy node between the HPC and the handler (it holds `autonomous=true`
for 10 s and republishes on receipt) keeps the handler verbatim. But it puts
itself in the omission path. The hazard's detector is then the handler on
an internal topic, the forwarding hop is uncounted, and the node costs a
subscriber, a publisher and a task slot on a board with 4.5 KB of RAM left.
The handler patch is about 40 lines in `updateMrmState()`'s NORMAL case:
start the TOR on `is_emergency && autonomous && !timeout`, go to
MRM_OPERATING on expiry or immediately on timeout, and clear the TOR on
MANUAL or on ODD re-entry. Record it in porting-notes as a demo extension
that is not upstream.

### 1.6 Severity and criticality

hpc_loss (ASIL_D) and odd_exit (ASIL_B) both reach the handler, so it keeps
ASIL_D (max, never sum). The comfortable operator now lies on odd_exit's
reaction walk and derives ASIL_B, which is the first time it derives
anything. The ODD monitor on the HPC derives ASIL_B as `feeds`, which is a
true statement that a slide can make.

---

## 2. Node architecture

Process groups (the "HPC loss" injection stops only the first):

```
HPC group (killable)                    VEHICLE group (stands in for the car)       ISLAND (native_sim | QEMU | S32K344)
------------------------------          ---------------------------------------     -----------------------------------
Autoware 1.5.0 planning stack           simple_planning_simulator                   mrm_handler (+ TOR patch)
  (planning, trajectory_follower,         (odometry, control_mode, control_mode_     mrm_comfortable_stop_operator
   external_velocity_limit_selector,       request, manual_ackermann input)          mrm_emergency_stop_operator
   hazard_lights_selector, ADAPI,       vehicle_cmd_gate (actuator arbitration)     [stop_mode_operator: excluded]
   diag graph, /system/converter)       TOR HMI (cabin): TOR banner, TAKE OVER
odd_monitor (NEW)                          button -> /control/control_mode_request
hazard_relay (NEW, 10 lines)            scenario_controller + timeline (observers)
```

Putting vehicle_cmd_gate in the vehicle group is a stated simplification:
in a car the island would command the actuator ECU directly. The gate stands
in for that ECU's arbitration, and it must survive an HPC loss for scenario
C to mean anything. The minimal injection is the existing one: SIGSTOP of the
availability publisher (now odd_monitor). The "full HPC" variant stops the
whole HPC group. Say which one ran.

New HPC and vehicle nodes (Python, rclpy, in the demo tree):
- **odd_monitor**. Remap `/system/converter`'s output to
  `/system/operation_mode/availability_raw`. On each raw sample, republish
  `/system/operation_mode/availability` with
  `autonomous &= in_odd(speed from /localization/kinematic_state, weather
  flag)`, with hysteresis on speed. Path `max_latency: 20ms`. The
  Autoware-native alternative is a leaf in the diag graph under the
  autonomous mode. It is more faithful but adds the aggregator's latency to
  FDTI; defer it.
- **tor_hmi**. Shows `/system/takeover_request/state` and `mrm_state`. Its
  button calls the SIMULATOR's `/control/control_mode_request` (MANUAL), so
  the takeover is vehicle-sensed as in a real L3. After takeover it
  publishes a gentle manual command (VERIFY the remap of
  `input/manual_ackermann_control_command`). Using ADAPI
  `disable_autoware_control` would route through the HPC, and it could not
  work in scenario E.
- **scenario_controller**. Extends `demo/scenario_driver.py`: init pose,
  goal, engage, cruise at the bound, then per scenario the weather flag
  toggle, raising `max_velocity_default` above the bound, SIGSTOP/SIGCONT,
  and a scripted or human button press. It writes `inject` events.
- **hazard_relay**. `/system/emergency/hazard_lights_cmd` ->
  `/system/hazard_lights_cmd` while `mrm_state.behavior ==
  COMFORTABLE_STOP`, so `hazard_lights_selector` lights them through the
  planner path. It needs the HPC, and so does the comfortable rung. The
  alternative is remapping the handler's output (VERIFY the gate's selection
  first; finding 6).

How the comfortable stop reaches the planner: `use_comfortable_stop: true`
in `mrm_handler.param.yaml`, and `availability.comfortable_stop == true`
(odd_monitor passes the converter's value; VERIFY it is true in the planning
simulator). The handler calls `/system/mrm/comfortable_stop/operate`. The
operator publishes TRANSIENT_LOCAL `VelocityLimit{max_velocity: 0,
use_constraints: true, min_acceleration -1.0, jerk +/-0.3}` on
`/planning/scenario_planning/max_velocity_candidates`. That feeds
`external_velocity_limit_selector` (its default `input_velocity_limit_from_internal`),
then `/planning/scenario_planning/max_velocity`, the velocity smoother, the
trajectory, trajectory_follower and the gate. The stop profile is therefore
the SMOOTHER's, and the declared 18.37 s is the operator's request. Measure
the difference.

Topics crossing the link (estimated bytes per second, excluding zenoh
framing):

| Direction | Topic | Rate | Approx B/s | Note |
|---|---|---|---|---|
| in | /localization/kinematic_state (Odometry, 880 B) | 10 | 8800 | dominates; handler uses only twist.x |
| in | /control/command/control_cmd | 30 | ~1800 | ramp seed, `state: true` |
| in | /system/operation_mode/availability | 10 | ~200 | the guard |
| in | /vehicle/status/control_mode | 10 | ~130 | the exit input |
| in | /control/command/gear_cmd, /api/operation_mode/state | 10 | ~300 | |
| in | steering, velocity, route_state (stop_mode) | 30 x 3 | ~3000 | REMOVED with stop_mode_operator |
| out | /system/emergency/control_cmd | 30 | ~1800 | |
| out | mrm_state, hazard, turn, gear, holding, TOR state | 10 x 6 | ~800 | |
| out | velocity limit / clear | event | small | transient local |

Inbound is about 11.2 kB/s against about 11.5 kB/s at 115200. Serial at that
baud is not a demo link. In order: (1) buy the 100BASE-T1 converter now;
(2) raise the UART to 921600 or 1 Mbaud and re-test the 4-byte RX FIFO
(W7 saw one wake per byte); (3) as a last resort, throttle
`kinematic_state` on the HPC side and state that the contract's 10 Hz is
then not met. A `link-budget` rule (sum of rate x the serialized bound that
nano-ros already computes, against a declared link capacity) would make this
a diagnostic. It is optional and not in the minimal set.

---

## 3. The live timeline plot

### 3.1 Inputs

| Source | Clock | Transport | Live? |
|---|---|---|---|
| play_launch observer `play_log/<ts>/runtime_violations.jsonl` (hazard-detected, hazard-reaction, mode-availability, plus the new mode-window / mode-exit) | CLOCK_MONOTONIC ns | file, flushed per line (mod.rs emit) | yes, tail at 50 ms |
| contract probe + logger (rclpy): velocity (`/vehicle/status/velocity_status`), mrm_state, TOR state, control_mode, availability fields, `when` predicates | receipt time, time.monotonic_ns | same JSONL schema | yes |
| scenario_controller: inject, SIGSTOP/SIGCONT, button | monotonic | JSONL | yes |
| island markers, native_sim | simulated ms since boot | today a dump at exit; live via Zephyr's POSIX tracing backend (a file, same CTF) | post-run by default; live optional |
| island markers, S32K344 | cycle counter / heartbeats | SWD polling of the existing RAM trace buffer with pyocd while the core runs (no firmware change); RTT (rtt.conf exists) as an alternative | yes, 100 ms polls |
| contract budgets | none (relative ms) | `play_launch check --budgets budgets.json` (NEW, structured terms per hazard and rung) | before the run |

Alignment: all host sources share CLOCK_MONOTONIC and need no alignment.
Island time is aligned on the anchor W3 already uses: the handler's
`PUB_MRM_HANDLER_MRM_STATE` marker against the host's receipt of that
sample, cross-checked on the last availability TAKE. W3 saw a disagreement
of 0.21-1.78 ms. The plot prints the disagreement. On silicon, add drift
correction from the 100 ms heartbeat. Caveats: the Zephyr RAM backend fills
linearly and then stops (16 KiB held 111 s of heartbeats with thread tracing
off), so size the buffer for one scenario, or reset between scenarios.

### 3.2 Event schema (JSON Lines, one record per event, ASCII)

```json
{"v":1,"run":"20261201T1000Z-B3","t":12.345678,"src":"island","kind":"marker","name":"CALL_MRM_HANDLER_COMFORTABLE_STOP_OPERATE","arg":1,"clk":"island_sim_ms","raw_t":40001.0}
{"v":1,"run":"...","t":2.101,"src":"scenario","kind":"inject","name":"odd_exit","how":"weather_flag"}
{"v":1,"run":"...","t":2.230,"src":"probe","kind":"hazard","hazard":"odd_exit","phase":"detected"}
{"v":1,"run":"...","t":2.340,"src":"logger","kind":"state","name":"tor","value":"OPERATING"}
{"v":1,"run":"...","t":2.35,"src":"logger","kind":"signal","name":"velocity","value":16.62,"unit":"m/s"}
{"v":1,"run":"...","t":12.44,"src":"observer","kind":"mode","name":"takeover_request","phase":"window_expired","dwell_ms":10090}
{"v":1,"run":"...","t":0.0,"src":"contract","kind":"budget","hazard":"odd_exit","rung":"comfortable_stop","term":"window","start_ms":230,"dur_ms":10000}
{"v":1,"run":"...","t":31.0,"src":"timeline","kind":"verdict","hazard":"odd_exit","term":"stop_within_ftti","ok":true,"margin_ms":812}
```

`t` is seconds on the host monotonic clock (or relative to the fault for
budget records). `raw_t` and `clk` keep the source clock so that any record
can be re-aligned later. Every run is one file, which is also the replay
input.

### 3.3 Tool choice

- **Live: pyqtgraph** (PySide6). It gives 20 Hz redraw with thousands of
  points, full control over swimlanes and bars, and a single Python process
  with an rclpy thread, a JSONL tail and a pyocd reader.
- **Static: matplotlib**, from the same JSONL, for the deck (python-pptx
  already builds the deck) and for a golden-image test.
- **Perfetto**: keep `island_trace.py --perfetto` for deep dives only. It is
  not live.
- **Rerun**: a credible alternative with built-in record and replay, but
  styling budget bars to slide quality is harder, and it adds a viewer
  dependency to a conference laptop. Not recommended as primary.
- nano-ros-rt-eval's `tools/vizstyle.py` / `plot_story.py` (E1 "tier Gantt
  + event marks + velocity panel") is prior art for the static style. Borrow
  it; do not depend on it.

### 3.4 Refresh model and what is drawn

Ingest threads push into one queue; a GUI timer redraws at 20 Hz. During
cruise the x axis scrolls over the last 60 s. On the first `inject`, the plot
anchors t = 0 at the fault and lays the declared bars from t = 0. At scenario
end it freezes, computes the verdicts, writes the PNG and appends the verdict
records.

Lanes, top to bottom:
1. Velocity (sim), with the ODD bound as a horizontal line and the DERIVED
   stop curve v(t) from G4 as a dashed line starting at the first braking
   command. An entry speed above the declared value is flagged in red.
2. Mode band: l3_engaged / takeover_request / comfortable_stop /
   emergency_stop / manual, from mrm_state + TOR state + control_mode.
3. Declared: stacked bars FDTI | TOR route | window | rung route | settle,
   with a vertical FTTI deadline, per hazard.
4. Observed: the same terms as bars measured from events (inject -> detected
   -> TOR -> expiry or driver -> operate call -> first brake -> v < 0.001),
   directly under lane 3.
5. Event ticks: island markers (source-coloured), observer lines, button
   press, hazard lights on.
6. Verdict box: per term observed <= declared, the stop within FTTI, the
   entry speed within the declared value, and the alignment error. PASS or
   FAIL with margins.

---

## 4. Repository plan

Options weighed:
- **nano-ros-rt-eval: no.** It is the IROS 2026 LBR poster workspace (E1-E4
  kernel and jitter experiments) with a synthetic Rust node set
  (gate_pkg, watchdog_pkg, mrm_operator_pkg), no launch contract, its own
  pinned nano-ros submodule, and no commits since 2026-08-14 (66 total).
  Nothing in the demo's chain (contract -> checker -> derived image ->
  markers) lives there. Borrow its plot style only.
- **A new repo: no.** It would have to copy or submodule the four ported
  nodes, the contract, `safety_island_tracing` (gen_markers, the decoder,
  unreachable.yaml), the board recipes, the emulation ladder and the
  nano-ros pin and lock story. It would also cut the provenance trail
  (reaction-trace.md, boot-through.md, board-facts.md) that every number on
  the deck points back to. There is no CI to preserve, but there is a great
  deal of `just` gating to rebuild.
- **SAI with a demo tree: yes.**

Recommended steps:
1. Land `contract-params` on main first (51 commits ahead). The working tree
   has uncommitted edits in four node headers, `system.toml` and the
   nano-ros submodule; resolve those before branching. Branch `l3-demo` from
   the result.
2. New tree `demo/l3/`:
   - `launch/l3_demo.launch.xml`, with `.contract.yaml` beside it (the
     scope-level hazards, functions, modes and paths, plus the HPC-side
     nodes).
   - `launch/variants/` (the one-line failing variants).
   - `nodes/` (odd_monitor, tor_hmi, scenario_controller, hazard_relay).
   - `maps/` (see risk 4).
   - `scenarios/{A..E}.yaml`.
   - `README.md` (the runbook).
   Recipes go in `just/l3-demo.just`, imported by one line, which is the
   phase-7 protocol.
3. `tools/timeline/`: `events.py` (schema), `probe.py`, `live.py`,
   `render.py`, `budgets.py`, `board_reader.py`.
4. Island changes stay in place: the handler patch, contract deltas and
   param yaml. `stop_mode_operator` stays in the port (the migration story)
   but is excluded by `if:`.
5. Keep and do not move: docs/demo-l4 (deck stages 0-3 cite it),
   experiments/, docs/roadmap. Rewrite: `demo/README.md` (still says
   "phase 5 - not wired yet"). Delete locally: the stale `build-*` trees
   (gitignored, but they poison workspace scans), `tmp_*.log` and
   `record.json` at the root.
6. Add minimal CI, which does not exist today. Run `gen_markers.py check`,
   `play_launch check` on the island, demo and variant contracts
   (expected diagnostics as goldens), unit tests for the schema and the
   budgets, and one replay-to-PNG golden. Autoware, Zephyr and board builds
   stay local `just` gates.
7. The rlm and play_launch changes (G1-G4, F1-F3, `--budgets`, the observer
   events) go to their own repos as numbered phases with fixtures, keeping
   phase 75's rule: byte-identical resolution for every existing contract.

---

## 5. Phased plan

Effort is in engineer-days with agent help. Phases 3-5 can overlap, and
phase 6 runs in parallel from day 1.

| Phase | Units | Gate | Effort |
|---|---|---|---|
| P0 Ground | land contract-params; branch; clean root; order the T1 converter; choose the map and the ODD bound | `just doctor` green on main; W3 trace re-run PASS on main | 1-2 d |
| P1 Scenario on Linux, TOR stubbed on the HPC | odd_monitor, tor_hmi, scenario_controller, hazard_relay; `use_comfortable_stop: true`; island on native_sim unchanged except the params; the VERIFY items below | A-E each run 3x end to end on native_sim; hazard lights seen in B; comfortable stop reaches 0 m/s | 5-7 d |
| P2 Grammar + checker | rlm: `when`, function `of/when`, `window`, `exit`, `entry_speed`, settle profile; play_launch: cumulative rung budget, F1, the new rules, `--budgets` | the demo contract passes; each variant gives exactly its one diagnostic; existing fixtures byte-identical | 7-10 d |
| P3 Island TOR | handler patch plus contract deltas; stop_mode excluded; markers regenerated; QEMU FirstSpin | A-E with the island-owned TOR on native_sim; `trace-check` PASS including TAKE_..._CONTROL_MODE; QEMU FirstSpin; `window-param` green | 3-5 d |
| P4 Timeline | schema, probe, logger, observer tail, budgets import, native_sim marker ingest, live and static views | live view at 20 Hz on the demo laptop over a full A-E run; replay renders the identical PNG; alignment error printed | 6-8 d |
| P5 Observer (play_launch) | F2 take-as-reaction; mode-window and mode-exit events | the observer JSONL for A-E contains detected, reaction, window and exit with plausible timings | 3-5 d |
| P6 Board (stretch, external blockers) | nano-ros phase-461 W6 (param store without services), link (T1 or high baud), FirstSpin on silicon, markers, SWD live reader | silicon trace with the C reaction markers; C on silicon with the plot. Otherwise the board is not on a slide | 10-20 d, blocked |
| P7 Harden | one-command bring-up, 20 consecutive runs per scenario, recorded fallback video, laptop profile | 20/20 PASS on A-C; a video of every scenario | 3-5 d |

Core path without the board: about 6-7 weeks elapsed.

VERIFY list for P1 (each is a short run, not a design question):
1. Does vehicle_cmd_gate ignore island hazard lights under COMFORTABLE_STOP,
   and does `hazard_lights_selector` pass `/system/hazard_lights_cmd`?
2. Is `availability.comfortable_stop` true in the planning simulator?
3. Does the velocity smoother honour `VelocityLimit.use_constraints`, and
   what stop profile results?
4. Does `operation_mode_transition_manager` disengage by itself when
   `autonomous` goes false? (That would pre-empt the TOR.)
5. Who publishes `/localization/kinematic_state` in the planning simulator
   (the simulator or the HPC)? This decides what the "full HPC loss"
   variant kills.
6. The simulator's manual-command input remap.
7. F3, the service-callback walk.

### Top risks

1. **Board readiness (high).** RAM at 323,112 / 327,680 B; FirstSpin
   blocked on nano-ros phase-461 W6; the executor has never run on silicon.
   Mitigation: native_sim is the live lane; dropping stop_mode frees
   entities (re-derive and measure; do not assume); the board is shown only
   with complete measurements.
2. **Link bandwidth (high).** Serial at 115200 is already saturated by
   Odometry alone. Mitigation: buy the converter this week; high-baud test;
   state any throttling.
3. **Autoware behaviour in the comfortable path (medium).** Hazard-light
   routing, the smoother's profile and the planner hop's latency are
   Autoware's, not the island's. The declared settle is the request; the
   measured settle is the smoother's. Mitigation: P1 verifies before any
   grammar work depends on it.
4. **Map and speed (medium).** A 60 km/h bound needs about 170 m for the
   TOR window, 170 m for the comfortable stop and margin: about 400 m of
   straight lane. The sample map cannot provide it. Mitigation: a generated
   straight two-lane lanelet2 map (1-2 d). The fallback is a scaled ODD
   (30 km/h), stated as scaled.
5. **Grammar creep (medium).** `window` and `exit` reopen what
   operational-modes.md deliberately left out. Mitigation: exactly one
   windowed rung and one exit, exit only on a windowed rung, no general
   transitions; each rule gets a failing fixture.
6. **Host load and teardown (medium).** W3 lost 3 of 7 traces under load
   14-49 to a teardown during the dump. Mitigation: a dedicated laptop
   profile, stop-island-first teardown (already in `run.sh`), headless
   RViz.
7. **Late takeover semantics (low).** Once MRM_OPERATING, a driver switch to
   MANUAL does not reset the handler until the vehicle stops. It is
   cosmetic, but it shows on the mode lane. Decide and document.
8. **Clock alignment on silicon (low).** SWD poll jitter and the linear RAM
   buffer. Mitigation: heartbeat drift fit; print the error; reset the buffer
   per scenario.

---

## 6. One-page summary

**Scenario.** L3 on a highway ODD with a speed bound of 16.7 m/s (60 km/h)
and a weather flag. There are two hazards and one ladder:

```
odd_exit (reported, ASIL_B, ftti 30 s)
  -> takeover_request (10 s window, driver exit -> manual)
  -> comfortable_stop
  -> emergency_stop

hpc_loss (omission, ASIL_D, ftti 10 s)
  -> the same ladder; TOR and comfortable are unavailable without the HPC,
     so it lands on emergency_stop within 500 ms detection
```

Five scripted runs cover them: A takeover, B no response, C HPC loss, D
escalation mid-stop, E HPC loss mid-TOR.

**What Autoware gives and what it lacks.** Autoware 1.5.0 has no TOR.
mrm_handler already provides:
- the driver cancel: no MRM unless control mode is AUTONOMOUS;
- ODD exit as a value on the availability topic it reads;
- comfortable-vs-emergency selection;
- escalation to emergency on timeout.

The only island code change is a roughly 40-line TOR window in the handler's
NORMAL state, driven by two parameters. `stop_mode_operator` is unused in the
vehicle_cmd_gate architecture: exclude it from the demo image.

**Grammar (minimal): four additions.** Most of the scenario is already rlm
(`on: reported`, modes/fallback/requires, `on_violation`, `safe_state`,
severity). Missing:
- (G1) `when:` predicates on hazards and functions, so a value can be a
  fault and a function can be lost by value;
- (G2) `window:` on one rung, bound to the parameter that enforces it,
  giving a cumulative rung budget and a no-window-on-the-floor rule;
- (G3) `exit:` from a windowed rung to a non-fallback mode, wired to a
  traced input;
- (G4) `entry_speed` on a hazard plus a param-named decel profile, from
  which settle is derived. This is the fix for W3's assumed 3.0 m/s.

**Checker fixes: three.** (F1) the rung budget must skip rungs the hazard
makes unavailable; (F2) the observer must count off-host sink takes;
(F3) VERIFY the service-callback walk.

**nano-ros.** It needs no new feature. The window is a parameter, the timer
is the existing tick, and pools and markers re-derive from the contract.

**Numbers the checker should print.**

| Hazard / rung | Total | FTTI | Slack |
|---|---|---|---|
| odd_exit / comfortable | 29006.67 ms | 30 s | 993.33 ms |
| hpc_loss / emergency | 8156.67 ms | 10 s | 1843.33 ms |

The planner hop is a 300 ms placeholder until measured. Slide variants:
+2 s on the window, or +10 km/h on the bound, each fails exactly the
comfortable rung.

**Architecture.**

| Group | Contents |
|---|---|
| HPC (killable) | Autoware + odd_monitor + hazard_relay |
| Vehicle (survives) | planning simulator + vehicle_cmd_gate + cabin HMI with the TAKE OVER button calling the vehicle's control_mode_request |
| Island | mrm_handler + two operators |

The comfortable stop runs: velocity limit -> external_velocity_limit_selector
-> smoother -> controller -> gate. Hazard lights in a comfortable stop need a
relay into hazard_lights_selector (VERIFY).

**Plot.** One JSONL event schema fed by:
- the play_launch observer (already flushes per line on CLOCK_MONOTONIC);
- a contract-generated probe and logger (payload predicates, velocity);
- the scenario controller;
- island markers (native_sim dump or POSIX backend; silicon via SWD
  polling of the RAM buffer, aligned on the W3 anchor).

pyqtgraph draws it live and matplotlib renders the same file for slides. The
lanes are velocity with the ODD bound and the derived stop curve, the mode
band, declared bars against observed bars with the FTTI line, event ticks,
and verdicts that include "entry speed exceeded".

**Repo.** Stay in simple-autoware-safety-island:
- land contract-params first;
- add `demo/l3/`, `tools/timeline/` and `just/l3-demo.just`;
- keep docs/demo-l4 and experiments;
- add the first CI (checks and goldens only).

Not nano-ros-rt-eval (a different purpose, synthetic nodes, stale) and not a
new repo (it would cut the provenance trail and duplicate the port).

**Plan.** P0-P5 and P7 in about 6-7 weeks. The board (P6) is a parallel,
externally blocked stretch.

**Top risks.** Board RAM and FirstSpin; serial link bandwidth (buy the T1
converter now); Autoware's comfortable path (lights, smoother); the map
length for 60 km/h; grammar creep.
