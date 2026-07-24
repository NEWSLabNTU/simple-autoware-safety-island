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

## 02 — identity rule forces namespace rename
- **Upstream:** `namespace autoware::mrm_emergency_stop_operator`.
- **nano-ros:** class prefix must equal pkg name →
  `namespace autoware_mrm_emergency_stop_operator`. One-line diff; the ASI
  fork solved the same with a wrapper subclass.

## 03 — parameter update callback dropped
- `add_on_set_parameters_callback` + `autoware_utils::update_param` have no
  nano-ros equivalent; runtime reconfigure of target_acceleration/jerk lost.

## 04 — subscription callback signature
- `Control::ConstSharedPtr` → `const Control&` (no shared_ptr message
  ownership in nano-ros).

## 05 — no rclcpp::Clock / Time arithmetic
- Port stamps from `nros_cpp_time_ns()` (platform monotonic) and computes dt
  from message stamps. Note: monotonic epoch, not ROS time.

## 06 — parameters are node-local; launch param file not projected
- Upstream declares params with NO default (values injected from
  `config/*.param.yaml` via launch). nano-ros: `declare_parameter(name,
  default)` node-local; the upstream yaml values became in-code defaults.

## 07 — `~/` private names + `<remap>` not routed
- nano-ros parses launch `<remap>` but does not route it; `~/input/...`
  expansion unsupported. Port hardcodes the resolved contract names
  (launch XML keeps them as documentation).

## 08 — multi-interface-pkg link: duplicate FFI symbols  **[fixed in nano-ros]**
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

## 10 — `nros::QoS` lacked the rclcpp depth ctor  **[fixed in nano-ros]**
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

## 12 — one `nros_find_interfaces` closure per workspace (island_interfaces)
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

## 14 — polling subscribers + blocking service futures → cache + poll
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

## 16 — cyclone descriptor registry cap was 64, overflow SILENT  **[fixed in nano-ros]**
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

## 18 — Zephyr minimal libcpp: no std headers, stub <new>  **[fixed in nano-ros]**
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
- Image builds, boots, constructs all 4 nodes, spins. BUT: only RTPS
  unicast ports bound (7910/7911) — NO SPDP multicast socket under
  CONFIG_NET_NATIVE_OFFLOADED_SOCKETS; host peers (multicast or unicast-peer
  URI) never discover the island. nano-ros's zephyr-cyclone e2e cells claim
  SPDP multicast green — reconcile with those cells' exact runtime setup, or
  wire the zeth/TAP path instead of NSOS. NEXT ITEM for P4.
