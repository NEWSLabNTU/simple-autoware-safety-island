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

Status: landed 2026-09-25 (uncommitted), gate met with a failing boot.
`just qemu-run` boots the QEMU image to its boot report, and it fails on
entity registration. `just renode-run` runs the unmodified S32K344 board image
on Renode's S32K3 and fails at the same point. In both, stop_mode_operator's
create_publisher returns -100 because the transient-local retention pool is 2
and the island has 5 such publishers. The FVP rung was not run: the nano-ros
model is AArch64 v8-R and cannot run a Cortex-M image. See docs/emulation.md.

W8 follow-up (2026-09-25). F1, F2 and F3 are resolved, and the QEMU image
reaches FirstSpin. See phase7-W8 below and `docs/boot-through.md`.

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

Status: native_sim half landed 2026-09-25 (`docs/reaction-trace.md`,
`experiments/reaction-trace/`); the board half waits on W6's SWD read.
Over 7 traces the island stays inside its terms: last availability sample
to the first braking command at most 607.99 ms of simulated time, against
500 + 110 + 33.33 = 643.33. One sampling wait was 33.98 ms against the
declared 33.33, because the operator's timer period is an integer 33 ms and
it jitters under load. The vehicle does NOT stop inside the FTTI. From the
last sample to standstill took 3196-3293 ms in all 4 runs with a velocity
log. The settle took 2666-2685 ms against the declared 2034, because the
demo brakes from 4.2 m/s and the settle term assumes 3.0 m/s. Board:
cutting `TRACING_THREAD` makes 16 KiB hold 3.3 s of markers, but the buffer
is one-shot from boot, so it also needs re-arming at injection.

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

### phase7-W7 - a transport peer on the serial link, and the first markers on silicon

W6 showed the traced image waiting in the zenoh serial session's open-retry
loop. `experiments/serial-interop/` already has the host side: a
`rmw_zenohd` router listening on `serial//dev/ttyUSB0#baudrate=115200`
(with `router-serial.json5`, which fixes the keepalive that otherwise
expires the board every 20 s) bridging to TCP. With that peer up the
session opens, the executor starts, the four nodes' timers run, and the
markers fire on silicon; with no availability publisher anywhere, the
handler's `on_violation` (max_age 500 ms) is the natural fault, so the
reaction route may be observable without Autoware at all, if the handler's
readiness gate lets it (native_sim with no Autoware left 11 handler
markers missing, so it may not; say which).

Deliver: the router recipe (`just board-peer`), the trace read with markers
present, per-marker-pair durations on silicon for every timer path that
ran (cycle-counter time, N ticks, distribution and maximum), the tracing's
own cost bracketed with DWT `CYCCNT` if it can be added without a rebuild
that changes the region report by more than the counter code, and the
reaction timeline if it fires. Every number qualified: silicon, this image
sha, this run. This is W4's silicon source and W6's Z1b-over-serial.

Gate: `trace-check` on a board read with the timer-path markers present;
the duration table in `docs/wcet.md` (the silicon section) with its
provenance; the serial-link caveats (4-byte RX FIFO, one run in three)
restated from what actually happened.

Owns: `just/board-peer.just` (one import line in the justfile),
`experiments/serial-interop/` (additions), `docs/wcet.md` (silicon
section), `docs/board-facts.md` (a Z1b-serial paragraph).

Status: 2026-09-25, recipe landed; gate not met, blocked on the image.
Details are in `docs/wcet.md` ("Silicon (W7)") and in `docs/board-facts.md`
(Z1b over serial). Data is in `experiments/serial-interop/w7/`.

- `just board-peer` works. The serial session opened on every boot, 6 of 6.
  The "one run in three" did not reproduce.
- The executor never starts. The image has five TRANSIENT_LOCAL publishers
  and a retention pool of 2, because the contract stated no durability. So
  `stop_mode_operator` fails at `create_publisher_in` (-100), the same as W2
  on QEMU and Renode. Everything is torn down about 0.6 s after the session
  opens. No marker fired, so the duration table in `docs/wcet.md` is empty.
- `CONFIG_TRACING_THREAD=n` on the board. With a serial peer, thread
  switches filled the buffer 31 ms after boot, at one wake per received
  byte.
- DWT `CYCCNT` now brackets `island_trace_marker` on the M7 and is live on
  the board. Its count is 0 because no marker has run.
- Heads-up for the contract fix. A 5-slot pool at 1,024 B did not fit the
  board's RAM (overflowed by 3,352 B); 256 B per slot fits, with 488 B left.
  `mrm_handler`'s `/api/operation_mode/state` subscription is
  TRANSIENT_LOCAL, which the zenoh shim refuses on subscriptions, so the
  handler will fail next. W2's 5-slot QEMU image showed the handler failing
  after `stop_mode_operator` had registered.
- The reaction will not fire by itself. `isDataReady()` needs one
  availability sample before the timeout can ever be seen.

Corrections to this unit's text above:

- "the session opens, the executor starts, the four nodes' timers run" is
  wrong for this image: only the first of the three happens.
- "if it can be added without a rebuild" cannot hold: the DWT bracket is
  code, so it needed a rebuild, and it shared the one that cut
  `TRACING_THREAD`.

### phase7-W8 - boot through registration

Take the QEMU island image from W2's stage-4 failure to the executor's first
spin, with every pool derived from the contract, and build the board image
with the same fixes (not flashed).

Gate: the QEMU console at FirstSpin and the host's `ros2 node list` showing
the four nodes; the board image's region report.

Owns: `docs/boot-through.md`, and the fixes:
- the contract's durability rows;
- `mrm_handler_core.cpp` (the operation-mode QoS);
- `src/qemu_entry/`;
- `just/emulation.just`;
- the pthread block of the board conf;
- nano-ros PR #1311.

Status: 2026-09-25. QEMU reaches stage 6, FirstSpin, and the host lists all
four nodes. Two board facts had to be raised through the env lever, not in
any conf: the heap (peak 190,216 B, against 94,720) and the main stack
(21,464 B used, against 16,384).

Six causes, in order:
1. The contract stated durability on 5 of 14 publishers, so nano-ros refused
   to count the transient-local ones.
2. On the Zephyr road the retention pool never received the count. nano-ros
   PR #1311 fixes this, and derives the slot size too: 105 B, not 1,024 B.
3. The zenoh-pico cond pool was at 16. This was F2, and it is what left four
   of the handler's subscriptions without a token.
4. The mutex floor counted subscribers only. It now counts queryables, and
   the pools are 70 mutexes and 48 conds.
5. The heap and the main stack.
6. The parameter services' heap at the first spin.

F3 is fixed on the island side, by a volatile operation-mode subscription.

The board image links at 323,112 of 327,680 B RAM on the merged pin 91a9a1edc, with nothing cut. It cannot
reach FirstSpin while `param_services` is on: its heap is short by more than
100 KB. That waits on nano-ros phase-461 W6 (a parameter store without the
services).

## 5. Order

W1 and W2 in parallel now. W3 when W1 lands (on native_sim; again on W2's
best rung when it lands). W4 after W3, W5 after W4. W6 independent; W7
after W6, and it feeds W4's silicon column.

## 6. What this phase is not

It is not a schedulability proof. A trace is an observation of one run and a
WCET measured over N runs is a lower bound on the true worst case; the deck
says so wherever a number from this phase appears.
