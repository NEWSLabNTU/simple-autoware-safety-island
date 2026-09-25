# Phase 7 - execution results: tracing, emulation, and the numbers the derivation never had

**Goal:** the island's image is executed under observation, first in
emulation and then on silicon, and the observations flow back into the
contract chain: a trace of the fault reaction against the declared budgets,
a measured execution time per callback written as the `[wcet]` profile the
derivation has never been given, and the derivation re-run with it.

**Status (2026-09-25): planned; W1, W2 and W6 claimed the same evening.**
Companion: the deck plan `~/Downloads/contract-e2e-slides/DECK-PLAN-v3.md`
(outside this repository), whose Act 4 these units feed.

---

## 1. Why

Every derived schedule this island has produced ranks by rate and
criticality with `exec_ms = None`: the `[wcet]` profile RFC-0078 and
nano-ros phase-357 define has never been produced by anything. The
fault-reaction budget the checker closes (2677.33 ms against 3 s, phase 6)
is arithmetic on declared terms; no trace has ever shown the island reacting.
And the board has never executed (phase 3, phase 5 island-W4). The L4 design
is right that Part 2 must prove rather than observe; this phase at least
observes.

## 2. What already exists

- A tracing design, decided 2026-09-01 for the board and never added to any
  conf: `CONFIG_TRACING_SYNC` + `CONFIG_TRACING_BACKEND_RAM`, a cut event set
  (application markers + thread switches), a stated buffer size, a heartbeat
  carrying a monotonic sequence counter, and provenance (knob values, image
  SHA) in the buffer. UART, semihost and async backends are disqualified for
  reasons recorded with the design: sync's cost is paid with interrupts off,
  and only the RAM backend keeps that small.
- An emulation ladder in nano-ros, all rungs present: `native_sim` (this
  island's demo runs on it), QEMU Cortex-M3 on `mps2/an385` (nano-ros board
  package `mps2-an385-pac`), Renode, and Arm FVP (`FVP_BaseR_AEMv8R`, nano-ros
  phase-217; a Cortex-R model, the L4 spec's FSI class, not the island's
  Cortex-M7).
- `Tonbandgeraet` (nano-ros `third-party/tracing/`) to decode the RAM
  buffer.
- The derivation's unused entry point for WCETs:
  `mapper_input_from_model_with_wcet` and `SystemToml::wcet_profile_for`,
  both with test callers only.

## 3. Protocol

As phase 6: a unit is `phase7-Wk`; each unit owns a disjoint set of files;
new `just` recipes go in `just/<unit>.just` imported by one line from the
main justfile, so units do not edit the same recipe body; real output only;
ASCII in what is authored; durations from `native_sim` are host durations
and are never quoted as the island's; durations from QEMU are instruction
order; only FVP or silicon durations go on a slide without a qualifier. The
tracing's own cost is measured and stated.

## 4. Units

### phase7-W1 - tracing lands in the island image

Add the tracing design to the native_sim entry and the board entry. Application
markers at the points the contract names: every `on_violation` reaction path
entry and exit, every timer path, the service call and its callback, every
publish of a contracted output. Marker ids are GENERATED from the contract
(the entity inventory already knows every endpoint and path), never typed by
hand, into a header the components include. A recipe dumps the buffer
(native_sim: to a file; board: over SWD with pyocd) and decodes it with
Tonbandgeraet. The heartbeat's sequence counter is checked contiguous.

Gate: a trace of the native_sim demo with every generated marker present at
least once and the sequence counter contiguous; the trace's own cost (bytes
per event, interrupts-off time per write) measured and written down; the
board image still links with tracing on and its region delta stated.

Owns: `src/native_sim_entry/*.conf`, `src/zephyr_entry/boards/*.conf` (the
tracing block only), a new `src/safety_island_tracing/` (marker generation
and header), `just/tracing.just`, `docs/tracing.md`.

Status: landed 2026-09-25. Details are in
`docs/tracing.md`.

- The traced native_sim demo gives `VERDICT: PASS` and `trace-check: PASS`.
  26 of the 31 generated markers fire; the other 5 are unreachable under
  `use_comfortable_stop: false`. Heartbeats are contiguous and the buffer did
  not fill.
- The board image links: RAM +17,296 B, 7,776 B left.
- The interrupts-off cost is an estimate, 2-5 us per marker, to be measured
  in W6.
- Tonbandgeraet cannot decode CTF, so a CTF decoder reading the pinned TSDL
  replaces it.
- native_sim time is simulated: execution takes zero time, so section 3's
  "host durations" understates the limit. W4 cannot take a WCET from
  native_sim.

### phase7-W2 - the emulation ladder

Build the island for QEMU Cortex-M3 on `mps2/an385` as a third entry (no
Ethernet: the transport is loopback or the serial transport
`experiments/serial-interop` tried); confirm whether Renode has a platform
near the S32K344 and whether nano-ros's FVP runtime takes the island's entry;
run the demo's island half on each rung that works. Deliver a table: rung /
what it measures / what it cannot / cost to run.

Gate: the island boots to its boot report on QEMU with a recipe
(`just qemu-run`); the Renode and FVP verdicts written down with the command
that produced each; the table in `docs/emulation.md`.

Owns: a new `src/qemu_entry/`, `just/emulation.just`, `docs/emulation.md`.

Status: claimed 2026-09-25.

### phase7-W3 - the reaction trace

With W1's tracing and W2's cheapest rung: stop publishing
`/system/operation_mode/availability` on a running island, capture the trace,
extract the timeline (last sample -> handler detects -> `call_mrm` -> service
request -> operator latches -> operator tick -> braking command), overlay
the contract's declared terms (500 / 110 / 33.33 / settle). Native_sim first
for structure; QEMU for order; durations qualified per section 3.

Correction from W1 (2026-09-25): native_sim executes code in zero simulated
time, so every marker inside one callback carries the same timestamp. A
native_sim trace gives order and WAITS (tick phases, the 500 ms detection,
the service round trip across callbacks), never a duration inside a
callback. The timeline W3 draws from native_sim is therefore made of waits
between callbacks, which are real in simulated time, and says so. Also from
W1: the board's 16 KiB RAM buffer holds well under a second at the
native_sim switch rate (thread switches are 90% of the bytes); W3 decides,
with a measured board switch rate, whether `TRACING_THREAD` is cut on the
board so the buffer covers the whole reaction.

Gate: the timeline figure and its numbers, from a real trace, with the
rung named; the declared-versus-observed table.

Owns: `docs/reaction-trace.md`, `experiments/reaction-trace/`.

Status: ready to start on W1's native_sim trace (2026-09-25); the board
half waits on W6's SWD read.

### phase7-W4 - execution times per callback, as the `[wcet]` profile

From the same traces over N runs: distribution and maximum per timer
callback and per reaction path, against the `max_latency` the contract
declares; written as the `[wcet]` profile in `system.toml` in the shape
phase-357 / RFC-0078 define. The profile records its provenance (rung, N,
trace SHA).

Correction from W1: no execution time can come from native_sim (zero
simulated time inside a callback) and none worth the name from QEMU
(instruction count, no pipeline, no flash wait states). The `[wcet]` profile
is filled from silicon: W6's trace buffer read with the marker pairs, and
DWT `CYCCNT` around `island_trace_marker` for the tracing's own cost. FVP is
the fallback if the SWD read fails, qualified as a model of a Cortex-R. Until
one of those lands, W4 delivers the table with the "measured" column empty
and the profile absent, never a number from a rung that cannot produce one.

Gate: the table; the profile parses (`nros` validates it today, which is all
anything does with it).

Owns: `src/safety_island_bringup/system.toml` (the `[wcet]` section),
`docs/wcet.md`.

Status: waits on W3 for the marker pairs and on W6 for silicon durations.

### phase7-W5 - derive with the WCETs

Run the derivation with the profile (nano-ros
`mapper_input_from_model_with_wcet`, production-unused): the derived order,
chain feasibility with real `exec_ms`, and the utilisation the profile
implies. Expected and honest: the order does not change (phase 6 W3 proved
the ranking never reads `exec_ms`), the feasibility verdict gains evidence
it never had, and the utilisation number is the first schedulability figure
this island has produced. If a nano-ros change is needed to reach the
`_with_wcet` path from a real `system.toml`, it is filed and, if small,
fixed upstream.

Gate: the three numbers with their provenance; the "order, not proof"
sentence kept.

Owns: `docs/wcet.md` (the derivation section), `third-party/nano-ros` (the
pin, only if an upstream change lands).

Status: waits on W4.

### phase7-W6 - silicon Z0 and Z1a

Z0: `just board-hello`, console banner captured. Z1a: `just board-flash` of
the island image, the boot report captured on the console, the derived table
sizes and the trace buffer read over SWD. Z1b onward (network, `ros2 node
list`, the demo) is blocked by the 100BASE-T1 media converter the kit lacks.

Gate: the two console captures in `docs/board-facts.md`; the buffer read.

Owns: `docs/board-facts.md`, `docs/board-bringup-triage.md` (status lines).

Status: Z0 passed 2026-09-25 (the recipe needed hal_nxp named; fixed).
Z1a the same day, in two steps: the W8b island image runs on the board
(core idle, serial-link frames on the UART), first ever; then the W1 traced
image's buffer read over SWD with `just trace-board` gave the provenance
(contract and marker-table digests, delivered knobs) and a contiguous 22 s
heartbeat at a measured 99.999 ms, and showed that no marker ever fires:
`main` waits in the zenoh serial open-retry loop with no peer, so no node
starts. The reaction cannot be traced on silicon until a transport peer
exists (Z1b: the T1 media converter, or a host on the serial link). W4's
silicon durations are therefore blocked behind the same peer; the tracing's
own cost (DWT CYCCNT) can still be measured once a marker fires. Captures in
`docs/board-facts.md`.

## 5. Order

W1 and W2 in parallel now. W3 when W1 lands (on native_sim; again on W2's
best rung when it lands). W4 after W3, W5 after W4. W6 independent.

## 6. What this phase is not

It is not a schedulability proof. A trace is an observation of one run and a
WCET measured over N runs is a lower bound on the true worst case; the deck
says so wherever a number from this phase appears.
