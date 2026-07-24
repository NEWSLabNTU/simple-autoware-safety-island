// Porting Autoware Nodes to nano-ros — a Safety Island Case Study
// Build: typst compile main.typ slides.pdf
#import "@preview/polylux:0.4.0": *

// ── Theme ──────────────────────────────────────────────────────────────────
#let accent = rgb("#0b5394")      // deep blue
#let accent2 = rgb("#38761d")     // green (island)
#let warn = rgb("#b45309")        // amber
#let ink = rgb("#1a1a1a")
#let paper = rgb("#fcfcfa")
#let codebg = rgb("#f3f2ee")

#set page(
  paper: "presentation-16-9",
  fill: paper,
  margin: (x: 1.6cm, top: 1.1cm, bottom: 0.9cm),
  footer: context [
    #set text(size: 9pt, fill: luma(140), font: "Lato")
    #h(1fr) github.com/NEWSLabNTU/simple-autoware-safety-island
    #h(0.8cm) #toolbox.slide-number / #toolbox.last-slide-number
  ],
)
#set text(font: "Lato", size: 17pt, fill: ink)
#show raw: set text(font: "DejaVu Sans Mono", size: 0.85em)
#show raw.where(block: false): box.with(fill: codebg, inset: (x: 3pt, y: 0pt), outset: (y: 3pt), radius: 2pt)

// Sized code block: `size` is the EFFECTIVE rendered size of the raw text.
#let code(body, size: 10pt) = block(
  fill: codebg, stroke: 0.5pt + luma(200), radius: 4pt,
  inset: 8pt, width: 100%, text(size: size / 0.85, body))

#let stitle(t, sub: none) = {
  block(below: 0.55em)[
    #text(size: 25pt, weight: "bold", fill: accent)[#t]
    #if sub != none [ #h(0.5em) #text(size: 14pt, fill: luma(110))[#sub] ]
  ]
  line(length: 100%, stroke: 1.2pt + accent.lighten(50%))
  v(0.4em)
}

#let pill(body, fill: accent) = box(
  fill: fill.lighten(85%), stroke: 0.7pt + fill, radius: 4pt,
  inset: (x: 6pt, y: 3pt), text(size: 12pt, fill: fill.darken(20%), body))

#let nodebox(body, fill: accent2, w: auto) = box(
  fill: fill.lighten(88%), stroke: 1pt + fill, radius: 5pt,
  inset: (x: 8pt, y: 6pt), width: w, align(center, text(size: 12pt, body)))

#let fixed = pill(fill: accent2)[fixed in nano-ros]
#let openp = pill(fill: warn)[open]

// ════════════════════════════════════════════════════════ 1 · Title
#slide[
  #v(1fr)
  #text(size: 34pt, weight: "bold", fill: accent)[
    Porting Autoware Nodes to nano-ros]
  #v(0.2em)
  #text(size: 22pt, fill: ink)[a Safety Island Case Study]
  #v(1.2em)
  #line(length: 40%, stroke: 2pt + accent)
  #v(1.2em)
  #text(size: 16pt)[
    Real Autoware 1.5.0 C++ nodes, near-verbatim, running the MRM chain
    on an RTOS — co-working with an unmodified Autoware stack.
  ]
  #v(1.0em)
  #text(size: 17pt)[Jerry Lin, Chi-Sheng Shih]
  #v(0.2em)
  #text(size: 14.5pt, fill: luma(90))[NEWSLab, National Taiwan University]
  #v(0.8em)
  #text(size: 14pt, fill: luma(110))[
    `github.com/NEWSLabNTU/simple-autoware-safety-island` #h(1em) · #h(1em)
    nano-ros: `github.com/NEWSLabNTU/nano-ros`
  ]
  #v(1.5fr)
]

// ════════════════════════════════════════════════════════ 3 · What was ported
#slide[
  #stitle[What was ported #h(0.4em) #pill[Autoware 1.5.0 · verbatim-first]]
  From `autoware_universe/{system,control}`, easiest → hardest:
  #v(0.4em)
  #table(
    columns: (auto, auto, 1fr),
    stroke: 0.5pt + luma(200), inset: 7pt,
    fill: (x, y) => if y == 0 { accent.lighten(88%) },
    table.header([*Package*], [*LOC*], [*Role*]),
    [`autoware_mrm_emergency_stop_operator`], [\~156], [jerk-limited hard stop ramp],
    [`autoware_mrm_comfortable_stop_operator`], [\~131], [gentle stop via velocity limit],
    [`autoware_stop_mode_operator`], [\~110], [continuous safe-command emitter],
    [`autoware_mrm_handler`], [\~600], [MRM state machine — the island brain],
  )
  #v(0.5em)
  - Ported sources keep the upstream *file layout, `package.xml`, launch XML*,
    and an ament-shaped CMake surface — a ROS user recognizes everything.
  - Message deps vendored *verbatim*: `autoware_control_msgs`, `autoware_vehicle_msgs`,
    `autoware_adapi_v1_msgs`, `tier4_system_msgs`, … — stock
    `rosidl_generate_interfaces()` + `package.xml`, unchanged.
]

// ════════════════════════════════════════════════════════ 4 · Architecture
#slide[
  #stitle[Architecture — two domains, one bridge]
  #v(0.3em)
  #align(center)[
    #grid(columns: (6.2cm, 3.6cm, 6.6cm), column-gutter: 0.4cm, align: center + horizon,
      // Autoware side
      rect(stroke: 1.4pt + accent, radius: 6pt, fill: accent.lighten(94%), inset: 10pt)[
        #text(weight: "bold", fill: accent)[Autoware — domain 1]
        #v(4pt)
        #nodebox(fill: accent, w: 100%)[planning_simulator]
        #v(3pt)
        #nodebox(fill: accent, w: 100%)[vehicle_cmd_gate]
        #v(3pt)
        #nodebox(fill: luma(120), w: 100%)[#strike[mrm_handler + operators]\ #text(size: 10pt)[shadowed out of launch]]
      ],
      // Bridge
      stack(spacing: 6pt,
        text(size: 12pt)[availability, odometry,\ control_cmd, mode, …],
        text(size: 18pt, fill: accent)[⟶],
        rect(stroke: 1.2pt + luma(120), radius: 6pt, inset: 8pt, fill: white)[
          #text(size: 12pt, weight: "bold")[domain_bridge]\
          #text(size: 10pt, fill: luma(110))[`bridge-config.yaml`\ = the topic contract]],
        text(size: 18pt, fill: accent2)[⟵],
        text(size: 12pt)[emergency control_cmd,\ gear, hazards, mrm_state],
      ),
      // Island side
      rect(stroke: 1.4pt + accent2, radius: 6pt, fill: accent2.lighten(94%), inset: 10pt)[
        #text(weight: "bold", fill: accent2)[Safety island — domain 2]
        #text(size: 11pt, fill: luma(110))[ (one process / one Zephyr image)]
        #v(4pt)
        #nodebox(w: 100%)[mrm_handler]
        #v(3pt)
        #nodebox(w: 100%)[#text(size: 11pt)[mrm_emergency_stop_operator]]
        #v(3pt)
        #nodebox(w: 100%)[#text(size: 11pt)[mrm_comfortable_stop_operator]]
        #v(3pt)
        #nodebox(w: 100%)[#text(size: 11pt)[stop_mode_operator]]
      ],
    )
  ]
  #v(0.4em)
  #text(size: 13pt)[Nothing else crosses: `docs/topic-contract.md` is the SSoT,
  the bridge YAML is the machine artifact. Same island binary runs native (dev loop) and Zephyr.]
]

// ════════════════════════════════════════════════════════ 6 · Project structure
#slide[
  #stitle[Project structure — a 3-role nano-ros workspace]
  #grid(columns: (12.4cm, 1fr), column-gutter: 0.8cm,
    [
      #code(size: 10.5pt)[```
CMakeLists.txt              workspace root
src/
  autoware_control_msgs/    ┐ vendored rosidl pkgs
  autoware_vehicle_msgs/    │ (subset of files,
  tier4_system_msgs/  …     ┘  otherwise VERBATIM)
  autoware_mrm_handler/     ┐ ported node pkgs
  autoware_mrm_*_operator/  │ (upstream layout:
  autoware_stop_mode_op…/   ┘  include src launch config)
  island_interfaces/        msg-closure shim (1 FFI union)
  safety_island_bringup/    system.toml + launch XML
                            + params + resolved model
  native_entry/             native entry (fast dev loop)
  zephyr_entry/             Zephyr image entry
demo/                       sim + domain_bridge + scenario
docs/porting-notes.md       the friction log (deliverable!)
      ```]
    ],
    [
      *Three roles:*
      #v(0.3em)
      #pill(fill: accent)[interface pkgs] \ #text(size: 13pt)[verbatim rosidl]
      #v(0.5em)
      #pill(fill: accent2)[node pkgs] \ #text(size: 13pt)[your C++, barely touched]
      #v(0.5em)
      #pill(fill: warn)[bringup + entry] \ #text(size: 13pt)[the only nano-ros-specific part]
    ]
  )
]

// ════════════════════════════════════════════════════════ 7 · The recipe
#slide[
  #stitle[The porting recipe]
  #grid(columns: (1fr, 1fr), column-gutter: 0.9cm,
    [
      *1 — vendor the message subset* \
      #text(size: 14pt)[Copy the `.msg`/`.srv` files + `package.xml` +
      `rosidl_generate_interfaces()` CMake — *unchanged*. nano-ros codegen consumes stock rosidl pkgs.]
      #v(0.5em)
      *2 — copy the package* \
      #text(size: 14pt)[Keep `include/autoware/<pkg>/`, `src/`, `launch/`, `config/*.param.yaml` as-is.]
      #v(0.5em)
      *3 — apply six mechanical edits* → \
      #v(0.5em)
      *4 — wire it up* \
      #text(size: 14pt)[Add the pkg to workspace CMake + one `[[component]]` block in `system.toml`; `just setup && just build && just run`.]
    ],
    [
      *The six edits (per node):*
      #set text(size: 14pt)
      #set enum(spacing: 0.75em)
      + Base class: `rclcpp::Node` → `nros::ComponentNode` (rclcpp shape)
      + Ctor: `(const NodeOptions&)` → `(nros::NodeHandle)`
      + Callbacks: `Msg::ConstSharedPtr` → `const Msg&`
      + Register: `RCLCPP_COMPONENTS_REGISTER_NODE` → `NROS_COMPONENT(...)`
      + Topic names: write the *resolved* contract names (remaps not routed yet)
      + Value-init messages: `Response r{};` (generated structs are PODs)
    ]
  )
  #v(0.3em)
  #text(size: 13pt, fill: luma(110))[Everything else — the actual node logic — is a diff you can read in one sitting.]
]

// ════════════════════════════════════════════════════════ 8 · Before/after
#slide[
  #stitle[Before / after — emergency stop ctor #h(0.4em) #pill[156 LOC pkg, diff ≈ 20 lines]]
  #grid(columns: (1fr, 1fr), column-gutter: 0.55cm,
    [
      #text(size: 13pt, weight: "bold", fill: accent)[upstream (rclcpp)]
      #code(size: 8.3pt)[```cpp
MrmEmergencyStopOperator::MrmEmergencyStopOperator(
  const rclcpp::NodeOptions & node_options)
: Node("mrm_emergency_stop_operator", node_options)
{
  params_.update_rate =
    declare_parameter<int>("update_rate");
  sub_control_cmd_ = create_subscription<Control>(
    "~/input/control/control_cmd", 1,
    std::bind(&Op::onControlCommand, this, _1));
  service_operation_ = create_service<OperateMrm>(
    "~/input/mrm/emergency_stop/operate",
    std::bind(&Op::operateEmergencyStop, this, _1, _2));
  pub_status_ = create_publisher<MrmBehaviorStatus>(
    "~/output/mrm/emergency_stop/status", 1);
  timer_ = rclcpp::create_timer(this, get_clock(),
    rclcpp::Rate(params_.update_rate).period(),
    std::bind(&Op::onTimer, this));
}
RCLCPP_COMPONENTS_REGISTER_NODE(
  autoware::mrm_emergency_stop_operator::
    MrmEmergencyStopOperator)
      ```]
    ],
    [
      #text(size: 13pt, weight: "bold", fill: accent2)[ported (nano-ros)]
      #code(size: 8.3pt)[```cpp
MrmEmergencyStopOperator::MrmEmergencyStopOperator(
  ::nros::NodeHandle handle)
: ::nros::ComponentNode(handle,
    "mrm_emergency_stop_operator")
{
  params_.update_rate =
    declare_parameter<int64_t>("update_rate", 30);
  NROS_SUBSCRIBE(Control, onControlCommand,
    "/control/command/control_cmd");
  ::nros::bind_service<OperateMrm, Op,
      &Op::operateEmergencyStop>(
    node(), "/system/mrm/emergency_stop/operate", this);
  pub_status_ = create_publisher<MrmBehaviorStatus>(
    "/system/mrm/emergency_stop/status");
  NROS_CREATE_TIMER(
    1000 / params_.update_rate, onTimer);
}
NROS_COMPONENT(
  autoware_mrm_emergency_stop_operator::
    MrmEmergencyStopOperator);
      ```]
    ]
  )
  #v(0.15em)
  #text(size: 12.5pt)[Timer/pub/sub bodies, the ramp math, the state handling — *byte-identical* to upstream.]
]

// ════════════════════════════════════════════════════════ 9 · CMake + launch
#slide[
  #stitle[CMake and launch — ament-shaped on purpose]
  #grid(columns: (1fr, 1fr), column-gutter: 0.7cm,
    [
      *Node pkg CMake* — `ament_cmake_auto` becomes one verb:
      #code(size: 9.5pt)[```cmake
find_package(nano_ros REQUIRED)
find_package(tier4_system_msgs REQUIRED)

nano_ros_add_node(mrm_emergency_stop_operator
  CLASS  autoware_mrm_emergency_stop_operator::
         MrmEmergencyStopOperator
  HEADER autoware/mrm_emergency_stop_operator/
         mrm_emergency_stop_operator_core.hpp
  SHAPE  rclcpp
  SOURCES src/.../mrm_emergency_stop_operator_core.cpp)
      ```]
      #text(size: 13pt)[No `main()` — the node pkg builds a component; the *entry* pkg owns boot.]
    ],
    [
      *Bringup* — launch XML stays ROS 2 schema, verbatim:
      #code(size: 9.5pt)[```xml
<launch>
  <node pkg="autoware_mrm_handler"
        exec="mrm_handler" name="mrm_handler"/>
  <node pkg="autoware_mrm_emergency_stop_operator"
        exec="mrm_emergency_stop_operator" .../>
  ...
</launch>
      ```]
      `system.toml` adds what ROS has no word for — domain, RMW, components, tiers:
      #code(size: 9.5pt)[```
play_launch resolve safety_island.launch.xml
  --system system.toml -o system_model.yaml
      ```]
      #text(size: 13pt)[One resolved model bakes into *both* the native and the Zephyr entry.]
    ]
  )
]

// ════════════════════════════════════════════════════════ 13 · Zephyr
#slide[
  #stitle[Zephyr: one image, four nodes]
  #grid(columns: (1fr, 1fr), column-gutter: 0.8cm,
    [
      *Entry pkg = prj.conf + one CMake verb:*
      #code(size: 9.5pt)[```
CONFIG_NROS=y
CONFIG_NROS_CPP_API=y
CONFIG_STD_CPP14=y
CONFIG_NETWORKING=y  CONFIG_NET_UDP=y ...
# sized up for 30+ DDS entities:
CONFIG_MAX_PTHREAD_MUTEX_COUNT=1024
      ```
      ```cmake
nano_ros_add_executable(zephyr_entry
  BOARD zephyr  TYPED  DEPLOY zephyr
  MODEL .../config/system_model.yaml)
      ```]
      #text(size: 14pt)[Same model as native — no `[deploy]` pins, so nodes stay board-agnostic.]
    ],
    [
      *Build & run:*
      #code(size: 10pt)[```sh
just zephyr-build   # west build -b native_sim/native/64
just zephyr-run     # ./build-zephyr/zephyr/zephyr.exe
      ```]
      *Talking to it from the host:* native_sim bakes multicast-off, unicast-peer
      discovery — the host must mirror it:
      #code(size: 10pt)[```sh
just host-env   # prints CYCLONEDDS_URI:
# lo iface, AllowMulticast=false,
# Peer 127.0.0.1, ParticipantIndex auto
      ```]
      #text(size: 14pt)[With that: the *full e2e passes against `zephyr.exe` — identical result to native*.]
    ]
  )
]

// ════════════════════════════════════════════════════════ 14b · Demo timeline
#slide[
  #stitle[The demo, second by second]
  #set text(size: 13pt)
  #table(
    columns: (2.4cm, 1fr, 5.2cm),
    stroke: 0.4pt + gray,
    inset: 5pt,
    table.header([*t*], [*step*], [*visible in RViz*]),
    [0 s], [sim-stack readiness gate (ADAPI routing up)], [map],
    [\~1 s], [`/initialpose` published], [vehicle appears],
    [\~6 s], [goal published → route SET], [route ribbon],
    [\~10 s], [`change_to_autonomous`], [mode AUTONOMOUS],
    [T₀], [velocity > 0], [*vehicle drives (\~4 m/s)*],
    [T₀+15 s], [bridge SIGSTOP — availability heartbeat cut], [—],
    [*T₀+15.5 s*], [island 0.5 s timeout → `MRM_OPERATING / EMERGENCY_STOP`], [*hard decel starts*],
    [T₀+\~18 s], [jerk-limited ramp (a = −2.5 m/s²) complete], [*stopped, hazards on*],
  )
  #v(0.5em)
  - Validated result: *PASS — 3.90 → 0.00 m/s*. One-shot: `demo/scenario-drive-and-kill.sh` (`DRIVE_SECS` overridable).
  - The 0.5 s reaction time is the ported handler's upstream `timeout_operation_mode_availability` default.
]

// ════════════════════════════════════════════════════════ 15 · Scorecard
#slide[
  #stitle[Scorecard]
  #grid(columns: (1fr, 1fr), column-gutter: 0.8cm,
    [
      #text(weight: "bold", fill: accent2)[Worked well]
      #set text(size: 14.5pt)
      - Vendored rosidl pkgs build *verbatim* — they even double as the host colcon overlay
      - Node logic ports near-verbatim; \~600-LOC state machine unchanged
      - Launch XML consumed as-is; ament-shaped CMake
      - QoS chains (`transient_local` latched pubs) just work
      - Same sources, native ↔ Zephyr, identical e2e behavior
      - Friction→issue→same-day-fix loop with nano-ros mainline
    ],
    [
      #text(weight: "bold", fill: warn)[Gaps (rclcpp-compat trajectory)]
      #set text(size: 14.5pt)
      #table(
        columns: (1fr, auto),
        stroke: 0.5pt + luma(200), inset: 6pt,
        [services / params / clock in the compat header], [next],
        [`<remap>` routing + `~/` expansion], [planned],
        [param-file projection at launch], [planned],
        [zero-initialized generated messages], [planned],
        [service clients with futures, callback groups], [open],
        [executor sizing derived from the model], [filed],
      )
      #v(0.2em)
      #text(size: 13pt, fill: luma(110))[Every gap has a documented, mechanical workaround — see `docs/porting-notes.md` (19 entries).]
    ]
  )
]

// ════════════════════════════════════════════════════════ 16 · Takeaways
#slide[
  #stitle[Takeaways — you can port your own nodes]
  #set text(size: 16.5pt)
  + *The port is mostly a copy.* Msg pkgs verbatim; node pkgs keep their layout;
    six mechanical edits per node, and the compiler finds every site.
  + *Your ROS 2 knowledge transfers.* `package.xml`, launch XML, QoS spellings,
    the ament CMake shape — all recognizable; `system.toml` is the only new file.
  + *The friction is finite and logged.* 19 notes from four packages;
    5 fixes already in nano-ros mainline — the list *shrinks* as compat grows.
  + *The payoff is real*: the actual Autoware MRM chain on an RTOS image,
    stopping the vehicle when the main stack dies.
  #v(0.8em)
  #line(length: 100%, stroke: 0.8pt + luma(200))
  #v(0.3em)
  #text(size: 14pt)[
    *Start here:* `github.com/NEWSLabNTU/simple-autoware-safety-island` — README quick start,
    `docs/porting-notes.md`, `docs/topic-contract.md` \
    *nano-ros:* `github.com/NEWSLabNTU/nano-ros` — RFC-0044 (rclcpp shape), RFC-0028 (safety / E2E),
    the `nros` CLI + `play_launch`
  ]
]

// ════════════════════════════════════════════════════════ A0 · Appendix divider
#slide[
  #v(1fr)
  #align(center)[
    #text(size: 30pt, weight: "bold", fill: accent)[Appendix]
    #v(0.4em)
    #text(size: 17pt, fill: luma(100))[Migration notes — the full friction log\ (nano-ros-internal work items; full detail in `docs/porting-notes.md`)]
  ]
  #v(1fr)
]
// ════════════════════════════════════════════════════════ 10 · Friction 1
#slide[
  #stitle[What to expect — API surface #h(0.4em) #text(size: 13pt, fill: luma(110))[porting-notes 01–05, 13]]
  #set text(size: 15pt)
  #table(
    columns: (auto, 1fr, 1fr, auto),
    stroke: 0.5pt + luma(200), inset: 6.5pt,
    fill: (x, y) => if y == 0 { accent.lighten(88%) },
    table.header([\#], [*Upstream expects*], [*What you do*], [*Status*]),
    [01], [`create_service`, params, `now()` on `rclcpp::Node` — compat header covers pub/sub/timer/QoS/log only],
      [derive `nros::ComponentNode` (rclcpp shape); services via `nros::bind_service`], [#openp],
    [04], [`Msg::ConstSharedPtr` callbacks], [`const Msg&` — no shared_ptr message ownership], [by design],
    [05], [`rclcpp::Clock` / `Time` arithmetic], [`nros_cpp_time_ns()` + dt from message stamps (monotonic epoch)], [#openp],
    [13], [C++17 (`std::optional`)], [C++14 surface — sentinel flag + value; mechanical], [by design],
  )
  #v(0.4em)
  All of these are *local, mechanical* edits — the compiler finds every site for you.
]

// ════════════════════════════════════════════════════════ 11 · Friction 2
#slide[
  #stitle[What to expect — semantics #h(0.4em) #text(size: 13pt, fill: luma(110))[porting-notes 06, 07, 09, 14]]
  #set text(size: 15pt)
  #table(
    columns: (auto, 1fr, 1fr, auto),
    stroke: 0.5pt + luma(200), inset: 6.5pt,
    fill: (x, y) => if y == 0 { accent.lighten(88%) },
    table.header([\#], [*Upstream expects*], [*What you do*], [*Status*]),
    [07], [`~/private` names + launch `<remap>` routing], [write resolved contract names in-source; launch XML keeps remaps as documentation], [#openp],
    [06], [params injected from `*.param.yaml` at launch], [param-file values become in-code `declare_parameter` defaults (node-local)], [#openp],
    [09], [rosidl C++ zero-initializes messages], [*value-init*: `Response r{};` — generated structs are PODs (garbage leaked on the wire otherwise)], [#openp — fix planned],
    [14], [`polling_subscriber`, blocking service futures], [cache-latest member subs; send-and-poll service clients (no nested spin in a timer cb)], [#openp],
  )
  #v(0.3em)
  \#09 is the one that *bites silently* — make `{}` a porting reflex.
]

// ════════════════════════════════════════════════════════ 12 · Friction 3
#slide[
  #stitle[What to expect — build & scale #h(0.4em) #pill(fill: accent2)[5 nano-ros fixes landed same-day]]
  #set text(size: 15pt)
  #table(
    columns: (auto, 1fr, auto),
    stroke: 0.5pt + luma(200), inset: 6.5pt,
    fill: (x, y) => if y == 0 { accent.lighten(88%) },
    table.header([\#], [*Friction → outcome*], [*Status*]),
    [08], [two interface pkgs on one link line → duplicate FFI symbols → nano-ros now builds one topo-last superset crate; also: msg constants as struct members (`MrmBehaviorStatus::AVAILABLE`)], [#fixed],
    [10], [`rclcpp::QoS(5)` / `.transient_local()` spelling → depth ctor added; ported code unchanged], [#fixed],
    [16], [type-descriptor registry cap 64, overflow *silent* (island registers \~86 types) → cap 256 + override knob], [#fixed],
    [18], [Zephyr minimal libcpp: stub `<new>` broke every component factory → placement-new forms declared], [#fixed],
    [11], [executor callback slots = compile-time env knob (`NROS_EXECUTOR_MAX_CBS`); boot fails loud (`Full`) → export 16+; codegen-derived sizing filed], [#openp],
    [12/15], [one msg-closure per workspace (`island_interfaces` shim); full-pkg deps drag srv IDL embedded idlc rejects → vendor msg-only subsets], [#openp],
  )
  #v(0.2em)
  The protocol: every friction point → `porting-notes.md` entry → nano-ros issue → fix *upstream*, not a local fork.
]

