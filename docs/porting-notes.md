# Porting notes — rclcpp → nano-ros friction log

First-class deliverable of this repo. One entry per friction point. Protocol:
minimal repro → entry here → nano-ros issue → fix upstream → drop workaround.

Template:

```
## NN — <short title>
- **Where:** <ported pkg / file:line>
- **Upstream expects:** <rclcpp API / semantics>
- **nano-ros does:** <current behavior / missing surface>
- **Workaround:** <what the port does meanwhile>
- **nano-ros issue:** <link / id>
- **Resolved:** <commit / date, or open>
```

## Confirmed entries (P1 — autoware_mrm_emergency_stop_operator, 2026-07-24)

## 01 — services/params/clock absent from rclcpp_compat
- **Where:** whole node; `rclcpp_compat.hpp` covers pub/sub/timer/QoS/log only.
- **Upstream expects:** `create_service`, `declare_parameter`, `this->now()`,
  `add_on_set_parameters_callback` on `rclcpp::Node`.
- **Workaround:** port derives `nros::ComponentNode` (RFC-0044 rclcpp shape)
  instead; services via `nros::bind_service`.
- **Resolved:** open — compat-surface extension is the nano-ros follow-up.

## 02 — identity rule forces namespace rename  **[FIXED — nano-ros #275 / RFC-0057, phase-305]**
- **Upstream:** `namespace autoware::mrm_emergency_stop_operator`.
- **Was:** class prefix had to equal pkg name (212.L.4) → flattened
  namespaces in every ported file.
- **RESOLVED (RFC-0057):** L.4 retired — pkg is explicit metadata; all four
  ported pkgs restored their verbatim upstream namespaces and register via
  `nros_components_register_node(<lib> PLUGIN autoware::… EXECUTABLE …)`
  (rclcpp_components keyword parity). Ports now C++17 like upstream.

## 03 — parameter update callback dropped
- `add_on_set_parameters_callback` + `autoware_utils::update_param` have no
  nano-ros equivalent; runtime reconfigure of target_acceleration/jerk lost.

## 04 — subscription callback signature
- `Control::ConstSharedPtr` → `const Control&` (no shared_ptr message
  ownership in nano-ros).

## 05 — no rclcpp::Clock / Time arithmetic
- Port stamps from `nros_cpp_time_ns()` (platform monotonic) and computes dt
  from message stamps. Note: monotonic epoch, not ROS time.

## 06 — parameters are node-local; launch param file not projected  **[nano-ros #276]**
- Upstream declares params with NO default (values injected from
  `config/*.param.yaml` via launch). nano-ros: `declare_parameter(name,
  default)` node-local; the upstream yaml values became in-code defaults.

## 07 — `~/` private names + `<remap>` not routed
- nano-ros parses launch `<remap>` but does not route it; `~/input/...`
  expansion unsupported. Port hardcodes the resolved contract names
  (launch XML keeps them as documentation).

## 08 — multi-interface-pkg link: duplicate FFI symbols  **[fixed in nano-ros; consumer boilerplate gone via RFC-0057 auto-wiring]**
- Each interface pkg's generated FFI staticlib was a flat-module superset of
  every preceding pkg → two pkgs on one link line = `multiple definition of
  nros_cpp_*`. Fixed in nano-ros: `nros_find_interfaces` now builds only the
  topo-last superset crate (`NO_FFI_CRATE` on the rest) and routes its archive
  through every pkg's INTERFACE target. Residual edge (two consumers with
  different topo-last in one build) documented in the nano-ros issue.
- Also fixed there: msg constants now emitted as struct members
  (`MrmBehaviorStatus::AVAILABLE`, rosidl convention) — namespace-level
  `Msg_CONST` aliases kept.

## 09 — generated message structs are uninitialized PODs
- rosidl C++ zero-initializes; nano-ros generated structs don't — a
  default-init `OperateMrm::Response response;` leaked stack garbage into
  `response.code` over the wire. Port uses value-init `{}`. Candidate
  nano-ros fix: emit `= {}` member initializers.

## Confirmed entries (P2 — comfortable_stop + stop_mode, 2026-07-24)

## 10 — `nros::QoS` lacked the rclcpp depth ctor  **[fixed in nano-ros, #279]**
- Upstream spells `rclcpp::QoS(5)` / `rclcpp::QoS{1}.transient_local()`.
  Native `nros::QoS` had only the default ctor. Fixed: `explicit QoS(int
  depth)` added; ported code keeps its spelling. `transient_local()` chain
  already existed and works (latched VelocityLimit delivered to a
  late-joining `ros2 topic echo`).

## 11 — executor callback slots are a compile-time env knob
- `NROS_EXECUTOR_MAX_CBS` (nros-node build.rs, default 4). The 3-node island
  registers ~9 entries → boot died `create_timer (code=-6 Full)`. `just
  build` exports 16. Follow-up filed for nano-ros: the entry codegen KNOWS
  the model's entity counts — it should derive/validate the knob instead of
  the user discovering it at boot.
- Corollary: changing the knob resizes the executor arena — stale incremental
  objects mixed old/new `NROS_EXECUTOR_SIZE` and segfaulted in shutdown.
  Clean rebuild after changing it (the nano-ros fixture-treadmill rule).

## 12 — one `nros_find_interfaces` closure per workspace (island_interfaces)  **[nano-ros #277; manual topo-last consumer links gone via RFC-0057]**
- With per-call topo-last FFI crates (nano-ros #253 mitigation), node pkgs
  with DIFFERENT msg-dep subsets would miss or duplicate symbols. The
  `src/island_interfaces` shim pkg (first SUBDIR) resolves the UNION closure
  once; all later interface calls no-op idempotently.

## 13 — `std::optional` / C++17-isms
- `ContinuousCondition` used `std::optional<rclcpp::Time>`; the nano-ros C++
  surface targets C++14 → sentinel flags + double seconds. Mechanical.

## Still-predicted gaps (P3)

- Service *clients* + `autoware_utils::polling_subscriber` (mrm_handler).
- `FixedString<N>` capacity for `ResponseStatus.message` etc. (works so far —
  524-byte SERIALIZED_SIZE_MAX default; `sender` string round-trips).

## Environment notes (native dev loop)

- Domain: native reads `ROS_DOMAIN_ID` env (model `domain_id` is baked only on
  embedded). `just run` sets it.
- A sourced ROS Humble env shadows the pinned cyclonedds via LD_LIBRARY_PATH →
  SIGSEGV inside `/opt/ros/humble/.../libddsc.so.0`. `just run` pins
  `LD_LIBRARY_PATH=~/.nros/sdk/cyclonedds/0.10.5-nros1/lib`.
- Host-side tooling: build `tmp/host_msgs_ws` colcon overlay from the vendored
  msg pkgs (they build verbatim — proven) to `ros2 topic echo`/`service call`
  the island.

## Confirmed entries (P3 — mrm_handler, 2026-07-24)

## 14 — polling subscribers + blocking service futures → cache + poll  **[nano-ros #278]**
- `autoware_utils::InterProcessPollingSubscriber` → member-callback subs
  caching latest + has_ flag. The 10 ms blocking `future.wait_for` in
  `requestMrmBehavior` → send-and-poll (a blocking wait inside a timer
  callback would need nested executor spin); replies drained next ticks,
  "success" = request sent. Behavior weakening documented in-source.
- Callback groups dropped (single executor); pull_over client dropped.

## 15 — full-pkg interface closure drags srv IDL the embedded cyclone can't parse
- Depending on AMENT `nav_msgs` pulled its srv files (GetMap/LoadMap/SetMap);
  their generated IDL fails cyclone idlc (`syntax error`). Workaround: vendor
  a workspace-shadowing `nav_msgs` subset (Odometry only) — shadowing is a
  supported nano-ros pattern. nano-ros follow-up: scope generation to
  msg-only or fix srv IDL lowering.

## 16 — cyclone descriptor registry cap was 64, overflow SILENT  **[fixed in nano-ros, #280]**
- `kMaxRegisteredTypes = 64` (descriptors.cpp); the island registers ~86
  types (std_msgs + geometry_msgs full sets alone ~60). Whichever ts archive
  was link-order last (tier4) dropped silently → `create_publisher` failed
  UNSUPPORTED(-5) surfaced as TransportError(-100) at boot. Fixed upstream:
  cap 256, `#define NROS_CYCLONEDDS_MAX_DESCRIPTOR_TYPES` override. (The
  `NROS_CYCLONEDDS_MAX_TYPES` env knob is a DIFFERENT registry — red
  herring during diagnosis.)

## 17 — stale host-tooling overlay masquerades as delivery failure
- `ros2 topic pub` from an overlay built before a msg was added publishes
  nothing useful; the island callback never fires and it looks like an RMW
  bug. Rebuild `tmp/host_msgs_ws` after any vendored-msg change.

## Confirmed entries (P4 — zephyr native_sim, 2026-07-24)

## 18 — Zephyr minimal libcpp: no std headers, stub <new>  **[fixed in nano-ros, #281]**
- `<algorithm>`/`<cmath>` don't exist (ports now use local `max_d`/`abs_d`);
  GLIBCXX full libcpp is NOT reachable on native_sim host-gcc
  (`PICOLIBC_USE_MODULE depends on !GLIBCXX_LIBCPP`, host gcc has no
  toolchain picolibc). The stub `<new>` also lacks placement new — every
  `NROS_COMPONENT` factory failed to compile; fixed in nano-ros
  (component_node.hpp declares the non-allocating forms when the Zephyr stub
  guard is present). ASI's FVP build never hit this (full-libcpp toolchain).

## 19 — 4-node cyclone image sizing + NSOS discovery gap  **[open]**
- `CONFIG_MAX_PTHREAD_MUTEX_COUNT/COND_COUNT` 256 → 1024 (30+ DDS entities;
  boot aborted in ddsrt_mutex_init — the documented pitfall, scaled).
- RESOLVED: the native_sim baked cyclone profile is multicast-OFF +
  unicast SPDP peer-scan of 127.0.0.1 (idx ≤ 20; session.cpp phase-180 —
  NSOS multicast breaks the select waitset). nano-ros CI proves it
  zephyr↔zephyr (symmetric). A HOST peer must run the mirror config AND
  pin the `lo` interface — with the default NIC the host advertises its
  eth locator and the pairing never completes:
    CYCLONEDDS_URI = Interfaces lo + AllowMulticast false +
    ParticipantIndex auto + MaxAutoParticipantIndex 20+ + Peer 127.0.0.1
  (`just host-env` prints it). With that, the FULL P3 e2e passes against
  zephyr.exe — heartbeat loss → cancel comfortable → call emergency →
  ramp + hazards, all four nodes in one Zephyr image.

## Confirmed entries (phase 8 -- mrm_handler start-up, 2026-09-29)

## 20 -- an explicit INIT/RUN lifecycle replaces isDataReady()  **[island, not upstream]**
- Upstream gates every tick on `isDataReady()`: until the availability and
  each operator status in use (reporting anything but NOT_AVAILABLE) have
  been heard, the tick returns and nothing is published, with no deadline.
  phase8-W10 added a join grace for the operation mode on top of it. Both
  mixed start-up with failure: an input that never arrived kept the handler
  silent for ever, with no fault; the grace clock started at the first
  availability sample, not at boot; and a real fault present at join was
  seen up to 0.5 s late, undeclared.
- phase8-W27 (`mrm_handler_core.cpp`, `updatePhase()`): two phases in an
  explicit member, `Phase::Init` and `Phase::Run`.

      boot --> INIT   publishes nothing; logs the pending inputs once a second
      INIT --(every required input established)--> RUN    marker INIT_DONE (arg: ms since boot)
      INIT --(init_timeout, 3.0 s from construction)--> RUN + init failure
                                                          marker INIT_TIMEOUT (arg: pending bitmasks)
      RUN + init failure --(every required input established)--> RUN (failure cleared)
      RUN never returns to INIT.

  Required = upstream's `isDataReady()` set plus the operation mode state:
  `operation_mode_availability`, `operation_mode_state`,
  `comfortable_stop_status` (when `use_comfortable_stop`) and
  `emergency_stop_status`, each operator status reporting anything but
  NOT_AVAILABLE. Odometry and the control mode are not required, as
  upstream: unheard they read "not stopped" and "not AUTONOMOUS".
- phase8-W28: "established", not "heard once". W27 left INIT on the first
  sample of each input; in acts a and b that was the first availability
  sample at 0.202 s, the host stream's next came at 0.834 s (632 ms against
  the 0.5 s timeout), and RUN published MRM_OPERATING / EMERGENCY_STOP for
  one tick at 0.8 s, NORMAL again at 0.9 s. One sample says a publisher
  exists, not that its stream keeps its period. The rule, per input
  (`getUnestablishedInputs()`, `isEstablished()`; each callback records its
  last two arrival times, `Arrivals`):

      input                        established when
      operation_mode_availability  two consecutive samples at most
                                   timeout_operation_mode_availability (0.5 s)
                                   apart, the newer at most that old at the tick
      comfortable_stop_status,     two consecutive samples reporting anything
      emergency_stop_status        but NOT_AVAILABLE (NOT_AVAILABLE restarts
                                   the count), same window and freshness
      operation_mode_state         one sample

  The availability's window is the timeout RUN judges it by, so a stream
  established in INIT cannot time out on RUN's first tick unless it stalls
  after it. The operator statuses have no timeout parameter: the operators
  publish every tick (10 Hz, 30 Hz) and the availability timeout, the only
  stream bound the handler has, is five periods of the slower; RUN does not
  watch them, so the window is a start-up rule only. The operation mode is
  TRANSIENT_LOCAL and published on change (default_adapi latches it): a
  second sample may never come, so one suffices -- the publisher's cache or
  a change, either is the current mode.
- The INIT log and the init-failure log name both kinds of pending input:
  "never heard: ...; not yet steady: ...". INIT_TIMEOUT's arg keeps W27's
  never-heard bitmask in bits 0-3 and adds the heard-but-not-established
  bitmask in bits 8-11 (same bit order); INIT_DONE's arg is the ms from
  construction to the tick that found every input established.
- The init failure is one more input fault, `isInputLost()`, beside the
  stale availability stream: `isEmergency()` holds, `getCurrentMrmBehavior()`
  forces EMERGENCY_STOP, and the takeover request is skipped. So the handler
  takes the availability-loss path: NORMAL -> MRM_OPERATING / EMERGENCY_STOP
  once the control mode reads AUTONOMOUS (upstream's rule: no MRM for a
  vehicle not in autonomous control), hazard lights on in any state. If the
  availability itself was never heard, its stamp is the boot, so the
  availability timeout holds too.
- Recovery is the state machine's, as from any fault: on the first tick
  that has every required input established the failure clears, and `isEmergency()` is
  judged on the inputs alone; if nothing else is wrong `updateMrmState()`
  returns to NORMAL from MRM_OPERATING, MRM_SUCCEEDED or MRM_FAILED, and
  `operateMrm()` cancels the emergency stop. It is cleared by the inputs,
  never by time.
- In RUN a missing or stale input is a fault judged by the existing
  timeouts (`timeout_operation_mode_availability`). An operator status that
  turns NOT_AVAILABLE in RUN no longer silences the handler (upstream's
  per-tick gate did); nothing watches it there, as before for staleness.
- The contract declares `init_timeout` in the handler's `params:`. rlm has no
  key for a start-up budget: the detection budgets apply from RUN, and the
  INIT budget is `init_timeout`, stated in a comment.
