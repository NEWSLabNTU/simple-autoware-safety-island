# Phase 6 - the L4 design, as a checkable contract

**Goal:** encode the Autoware Reference Design WG's own L4 Safety Island
design in the contract language, stage by stage, so that the timing analysis
it defers to Part 2 is performed today from Part 1's own tables, and every
claim on the conference deck is a real diagnostic from a real run.

**Status (2026-09-25): W0 to W5 landed, W6 to W9 open; W7 claimed.** W5's
play_launch half is on `main` as `c1474126`; its nano-ros half is PR #1262,
auto-merge armed. The upstream fixes this phase found are nano-ros phase-467
and play_launch phase-82.

---

## 1. The document this phase consumes

`github.com/autowarefoundation/RFC_L4_SafetyIslandDesign`, "L4 Safety Island
for Autoware - Software Design", version 20260918, Reference Design WG. A
working copy is in the session scratchpad; do not vendor it into this tree.

Three sentences from it define this phase:

- Section 0 puts "FTTI budget derivation and timing analysis" OUT of scope
  for Part 1 and defers it to Parts 2-4.
- Section 9.2 prints a preliminary fault-reaction budget anyway, marked "To
  be reconciled with the FTTI in Part 2".
- Section 9.1 says the island is organised "following the declarative
  RT-configuration approach already demonstrated (contract facts -> priority
  bands, `chain_aware` mapper)", and that P0 completing without P2 or P3 is a
  property "the timing analysis in Part 2 must PROVE rather than observe".

The document also names this repository as an engineering baseline (section
1, and the references), and three of this island's four nodes are on its
ASIL-D T0 list: `I5 autoware_stop_mode_operator`,
`I6 autoware_mrm_emergency_stop_operator`, `I7 autoware_mrm_handler`.

## 2. The claim, and the shape that carries it

> The design says it in prose. The contract makes it a diagnostic.

One fixture at `docs/demo-l4/` that accretes across five stages. Stages 0 to
3 are the DESIGN, as declarative stand-in nodes with no source code, because
the claim is about the document rather than about this port. Stage 4 is this
island, because that is where the measurement is.

Every stage ships a passing run and a one-line-changed failing run. The
failing run is the slide.

## 3. The protocol here

- A unit is `phase6-Wk`, a branch of that name in THIS repository, and each
  unit owns a disjoint set of files so units can run in parallel.
- No unit rebuilds play_launch or runs a board build. The checker at
  `/home/aeon/repos/play_launch/install/play_launch/lib/play_launch/play_launch`
  (0.10.0) is fast and is all that is needed. If a unit believes it needs a
  rebuild, it stops and says so.
- Real output only. A number that was not produced by a run does not go in a
  file, and a number quoted from the design cites its section.
- ASCII in everything authored here. Tool output is pasted verbatim even when
  it contains an em dash or a unicode arrow; say so where it does.
- What each unit invents, because the design does not state it, is named in
  the contract header, not buried.

## 4. The units

### phase6-W0 - stage 1, the budget

Landed before this document existed, and it is the reason the rest is worth
doing. Section 9.2's four-stage table, encoded against its own 70 ms total:

```
info[fault-reaction-budget]: hazard 'hpc_loss': detection 30.00ms + reaction
40.00ms = 70.00ms fits the fault-tolerant time interval 70.00ms with 0.00ms
of slack
```

Exactly zero slack. The design's four stage rows sum to precisely its own
total row, so the budget is closed and has nothing left in it. Nothing in the
fixture was tuned to produce that.

Then one line changes `lease_duration: 30ms` to `500ms`, the watchdog the
island actually runs, and it becomes `540.00ms exceeds`, exit 1. The reaction
route is identical in both; all 470 ms of the difference is in the detector.

The tool also volunteers what the design left open, unprompted:

```
warning[reaction-unbudgeted]: ... no path there declares a `safe_state` with
a settle time -- the plant's share of the reaction is unknown, so the FTTI
check runs on INCOMPLETE EVIDENCE
```

because section 9.2's last row is "Actuator response: vehicle-specific".

MUST BE SAID ALOUD when this is presented: the failing run is NOT "the
design's backstop fails". The design keeps the 500 ms watchdog as a backstop
ALONGSIDE a 30 ms heartbeat. The failing run is the island as it exists
today, where the heartbeat does not exist and the watchdog is the only
detector, which is section 1's measured 0.49-0.67 s trip. This is the one
place a slide could mislead.

Owns: `docs/demo-l4/l4_designed.*`, `docs/demo-l4/l4_current.*`,
`docs/demo-l4/run.sh`.

Status: landed 2026-09-24, pushed as `dd749ad`.

RETRACTION, 2026-09-25: this document's protocol said the 0.10.0 binary
"loads only part of an overlay tree". It does not. The login shell on the
build machine has the island's `demo/host_ws/install` ahead of
`/opt/autoware/1.5.0` in AMENT_PREFIX_PATH, and that demo copy of
`tier4_system_launch` has the MRM handler and operator DISABLED because the
island provides them. Re-sourcing `/opt/autoware` does not move it forward.
From `env -i` the stock tree parses as 169 scopes / 34 nodes / 15
containers / 70 composable nodes, all four MRM contracts attach, and the
1944 ms / 56 ms verdict, the 1.5 s failure and the comfortable-stop rung
error are produced live. Every Autoware run for the deck starts from `env -i`
and confirms `ros2 pkg prefix tier4_system_launch` first.

### phase6-W1 - stage 0, the interface declared

Section 8.1 is a table of 11 HPC-to-island signals with Topic, Type, Rate and
Age limit. That table IS a contract file, and the slide is the two side by
side with no translation between them.

What it does: encode all 11 rows, plus section 8.2's island-to-HPC rows as
far as the grammar takes them. The failing variant changes one `rate_hz` so a
subscriber demands more than the topic carries, and `rate-hierarchy` names it
with a span.

Gate: `play_launch check` clean on the passing file, exit 0; the failing file
exits 1 with `rate-hierarchy` naming the row.

Owns: `docs/demo-l4/stage0-*`.

Status: landed 2026-09-24. All 11 rows of section 8.1 plus section 8.2 and
8.3, as 27 topics over 2 nodes. Passing file exits 0 clean; the broken one
drops the heartbeat from 100 Hz to 10 and exits 1 with `rate-hierarchy`
naming the row with a span. Six things section 8 states that the grammar
cannot take are listed in the file rather than dropped; the largest is a
whole column, the per-row protection profile.

### phase6-W2 - stage 2, the degradation ladder

The strongest feature match in the document. Section 3.1 declares four
behaviours with a precedence order, one-way escalations and two edges that
climb back; section 8.1 says "every input on this table is now degradable"
and gives each one an island-local substitute; and section 3 states B4's
precondition as a principle:

> "B4 precondition: None, by design. A fallback whose entry can be blocked is
> not a fallback."

The checker enforces exactly that sentence as `ladder-unterminated`.

What it does: encode B1 to B4 as `modes:` with `fallback:` and the design's
own timeouts (`T_ack` 2 s, `T_odd` 10 s, `T_refuge` 5 s). Two failing
variants: give B4 a requirement so the ladder loses its floor; and check a
graded rung in its own right so `ladder-rung-budget` fires.

Gate: `ladder-unterminated` and `ladder-rung-budget` each reproduced from a
real run, verbatim, with the one line that produced each.

Owns: `docs/demo-l4/stage2-*`.

Status: landed 2026-09-24, and it is the best artifact in the phase. Eleven
stand-in nodes, B1 to B4 as modes, T_ack as the guard's lease, T_odd as the
ftti, T_refuge as a path budget. T_hold is absent because open decision 14
fixes no number, and the file says so rather than inventing a placeholder.

`stage2-noFloor` gives B4 a requirement, one line, and the budget line is
UNCHANGED: still fits with 7,760 ms of slack. Every number in the file is
still right. What broke is the argument that the floor is always enterable,
and no timing analysis can find it. That is the phase's thesis in one run.

`stage2-rungBudget` changes one deadline from 3 s to 10 s, both numbers from
ONE row of section 3.1, and the graded rung fails in its own right.

### phase6-W3 - stage 3, the partitions, run privately first

Section 9.1 assigns five partitions with periods and priority bands and says
it follows the `chain_aware` mapper. So feed the document's facts to that
mapper and see whether its bands come back out.

This unit does NOT produce a slide. It produces a verdict and a
recommendation, because the mapper may order the bands differently from the
document, and section 9.1's ordering is deliberate and argued: the QM nominal
controller sits BELOW ASIL-B sensing so that overload sheds the MPC first.
Agreement is a strong slide; disagreement is a better conversation, and which
one it is must be understood before the talk rather than after.

Whatever the outcome, one thing is disclosed: the derivation runs with
`exec_ms = None` on every road in production, so it ranks by rate alone.
Section 9.1 asks Part 2 to prove the partitions; this is the gap between
deriving an order and proving a schedule.

Gate: the mapper's ranked plan for the fixture, the document's table, and a
written verdict on whether they agree and why.

Owns: `docs/demo-l4/stage3-*`.

Status: landed 2026-09-24. VERDICT: they do not agree, and NOT a slide.
P0 is reproduced exactly. P1 and P2 cannot be separated, and that is a
MISSING FACT rather than a mapper limit: section 2.2 gives T1 and T1s the
same ASIL-B(D) and section 9.1's periods overlap at 20 ms. With the design's
own hazard declared, the QM MPC ranks EQUAL to the ASIL-B fallback meant to
replace it, which section 9.1 says must not happen; the cause is that the two
criticality mechanisms do not compose, and hazard-derived criticality is
reachability rather than decomposition.

One line for the open column, and one question for the WG: what fact should a
contract state so a tool can derive T2 as QM-under-a-bounding-arbiter rather
than as reachable-from-a-hazard.

Also disclosed: a derived schedule is an ORDER, not a proof. Proved by
negative control, declaring budgets for seven of eleven nodes returned an
identical sequence.

### phase6-W4 - stage 4, the cost, measured

Section 9.1's sizing note says P2 "is the partition most likely to force a
larger MCU than the current S32Z-class target". This unit answers the
neighbouring question with a measurement: what a real allocation of Autoware
MRM nodes costs in RAM on a real 320 KiB part, with every pool derived from
the contract rather than hand-maintained.

What it does: finish what island-W3 still owes. Rewrite `docs/nxp-deployment.md`
sections 5 and 8 from the current map, including the region report and the
seventeen largest symbols; correct section 10, which still says the board
does not fit; and run `just check-knob-delivery`.

Gate: the region report and the seventeen largest symbols in the document;
section 10 corrected; `check-knob-delivery` green.

Owns: `docs/nxp-deployment.md`.

Status: landed 2026-09-24, gate two-thirds met. Region report and seventeen
largest symbols in the document, every row traced to a knob, 94.33% of SRAM
in named symbols. Section 10 corrected. Roughly twenty figures corrected,
including the service-inbox table, which was 115,128 in the old text and is
11,544 at this geometry.

`check-knob-delivery` is RED and was left red: the board file states
`CONFIG_NROS_MAX_LIVELINESS=32` against a derivation that now says 58, so it
is 26 short and liveliness would exhaust silently; and
`NROS_DERIVED_SUBSCRIBED_TYPE_BOUNDS` never reaches the resolver, an upstream
loader-whitelist gap. Neither blocks the link. The board conf belongs to
another task, so neither was fixed here.

OPEN, and it matters: `DECLARED_APP_QUERYABLES` is `usize::MAX` in the
generated config, which makes `BUILTIN_INBOX_PER_SESSION` zero, so the
hand-derived `CONFIG_NROS_PARAM_SERVICE_INBOX_BYTES=1016` is allocated zero
times and all 26 queryables fall back to a 24 byte ring. Nothing has run on
silicon, so this is an open item rather than a failure.

### phase6-W5 - the upstream gaps this phase found

Three, each with evidence already in hand.

1. **The reaction walk follows topic edges only.** The island's real reaction
   crosses `/system/mrm/emergency_stop/operate`, a service, so the hazard's
   ASIL_D lands on `mrm_handler`, which NOTICES, and never on
   `mrm_emergency_stop_operator`, which ACTS. Found by giving the island a
   hazard. play_launch accepts direct pushes.
2. **`MAX_MONITORS` is a hard-coded 8 and this island needs 14.** No rung on
   any knob ladder. Install refuses rather than truncates, so the C++ image
   would return `NROS_CPP_RET_FULL` at boot. nano-ros's own comment describes
   this island: "an image that boots with six of its fourteen contracts
   silently unwatched". nano-ros is merge-queue only, so this is an issue and
   a PR, not a push.
3. **`max_age` is inert for an `on: omission` hazard.** Section 8.1 gives
   every signal an Age limit, and for an omission hazard only the lease is
   counted, so the design's 20 ms age limit rides along as a fact no rule
   consumes. Report it; do not guess the fix.

Gate: item 1 fixed or filed with a failing test; items 2 and 3 filed with
evidence.

Owns: nothing in this tree.

Status: landed. Item 1 is play_launch `main` `c1474126` (215 tests, the
snapshot gate included, re-run against rlm v0.1.41 after a rebase). Item 2 is
nano-ros PR #1262, auto-merge armed. Item 3 is play_launch issue #0046, now
being ruled on by play_launch phase-82 W3.

The diagnosis of item 1 is worth keeping: the existing Autoware fixtures only
reached the stop operator by declaring the service as a TOPIC with
`type: tier4_system_msgs/msg/OperateMrm`, `msg/` where `srv/` belongs. The
phase-71 flagship result existed because its author worked around the gap.

Item 2 is nano-ros issue 1471, on branch `issues-monitors-and-age`. The
island's own count is 14 monitor rows against a hard-coded 8, and nano-ros's
comment describes this island by number: "an image that boots with six of its
fourteen contracts silently unwatched". The refusal propagates: generated
setup returns -6 before it creates a node.

Item 3 became play_launch issue 0046, filed there because the rule lives
there. It is written as a DESIGN QUESTION, not a defect, because `max_age`
bounds the staleness of a message that arrived and omission is the absence of
one. Two things in it are not questions: the `hazard-unguarded` message
recommends `max_age` and `min_rate_hz` as detectors that cannot satisfy it;
and omitting the hazard's `on:` entirely counts every mechanism and buys
10 ms of slack, so a contract that names its fault class precisely is scored
more harshly than one that declines to. That inversion is reproduced
independently.

### phase6-W7 - the board file states board facts

The island's own half of nano-ros phase-467. Two lines in
`src/zephyr_entry/boards/mr_canhubk3_s32k344.conf` state counts the contract
determines, and both are wrong today:

- `CONFIG_NROS_MAX_LIVELINESS=32`, with a comment that says liveliness is
  "sized by the PEER graph ... probably never derivable". That is the
  PRE-correction text of nano-ros phase-412's knob table; row 192 of that
  table was corrected on 2026-09-08 ("not remote peers, and it IS
  derivable"), the Kconfig default has been `-1 = derive` since, and the
  derivation says 58: 1 session + 4 names + 14 pubs + 11 subs + 2 servers +
  2 clients + 24 parameter services. The 32 was right at 29 tokens and went
  silently 26 short when `params:` was declared. Liveliness exhaustion is
  not a boot failure; the entity is simply invisible to `ros2 node list`.
- `CONFIG_NROS_PARAM_SERVICE_INBOX_BYTES=1016`, hand-derived on 2026-09-24
  as a workaround, is allocated ZERO times (see W4), and its comment cites
  "nano-ros issue 1471", which is now the MAX_MONITORS issue. The sentinel it
  worked around is phase-467 W2.

What it does: delete the liveliness line and its comment; where the file
lists what is derived and what is stated, move liveliness to the derived
column and record the rule (board facts only). Revert the temporary
`nros sync --no-metadata` in `justfile` if the build passes without it.
Then `just board-build` and read `check-knob-delivery`.

CORRECTED 2026-09-25, on the first attempt: the inbox line does NOT come out
here. It is allocated zero times, but on the current pin it is also the only
value that passes `parameter_services.rs:1655`'s compile-time assert
("NROS_PARAM_SERVICE_INBOX_BYTES is smaller than the largest parameter
request ... Raise it, or drop the override and let it derive"), because the
Kconfig default 0 arrives as a STATED zero (the sentinel bug phase-467 W2
fixes). Deleting it fails the build at compile, before the link. So W7 is
liveliness only, and the inbox line leaves in W8 with the pin bump. The
line's comment now says exactly that and names phase-467 W2 rather than the
issue number it used to cite.

Gate: the image still links; `check-knob-delivery` no longer reports
liveliness (`NROS_RESOLVED_NROS_MAX_LIVELINESS` = 58); the remaining red,
`NROS_DERIVED_SUBSCRIBED_TYPE_BOUNDS` never reaching the resolver, is named
as upstream and left; the region report before and after is pasted into
`docs/nxp-deployment.md` section 5 with the delta of 58 tokens versus 32
explained.

Owns: `src/zephyr_entry/boards/mr_canhubk3_s32k344.conf`, `justfile`,
`docs/nxp-deployment.md` sections 5 and 10 (the two figures).

Status: landed 2026-09-25 as `607501f`. Liveliness delivered as 58; image
links at 281,384 B, +416 B, all of it `g_sessions` (26 entries of 16 B);
`check-knob-delivery` red on the one upstream line only. The temporary
`--no-metadata` is reverted. Also fixed in passing: the recipe's refusal
advice ran another board build to print itself (backticks in a double-quoted
echo); 32 were found nested and killed.

### phase6-W8 - consume phase-467 and phase-82

When nano-ros phase-467 W1 and W2 and play_launch phase-82 land: bump the
nano-ros pin forward; DELETE `CONFIG_NROS_PARAM_SERVICE_INBOX_BYTES=1016`
from the board file (it could not leave in W7, see above); confirm the
emitted config carries a derived `MAX_MONITORS` of 14 (rate) and 0 (age) and
a derived builtin inbox of 1016 B with no inbox line in the board file; then make the island's own
hazard route through the operator. play_launch phase-82 W4 measured
(2026-09-25) that this takes THREE contract edits, not the one line W5
predicted: the hazard's sink is the scope path's output, and `call_mrm`'s
`safe_state` emits `mrm_state`, so the walk correctly ends at the handler
however the client endpoint is named.

1. `mrm_handler.paths.call_mrm.output: [mrm_state, emergency_stop_operate]`
2. `paths.island.emergency_stop.output: [/system/emergency/control_cmd]`,
   so the braking command is the sink, not the handler's state report
3. move `safe_state: { emits: emergency_control_cmd, settle: 2034ms }` onto
   the operator's `on_timer` and off `call_mrm`, or the settle is lost and
   `reaction-unbudgeted` fires

And one correction: the operator's `on_timer` declares `max_latency: 33ms`
because the island meant that number to be the unseen tick. The walk now
charges the tick itself (the period plus the path's own `max_latency`, the
same quantity as `traversal_latency_ms`), so 33 ms there counts the clock
TWICE. That field becomes the callback's execution budget, a few
milliseconds; the tick is the walk's to charge.

Measured on a scratch copy against the W4 binary with all four edits:
`reaction route /mrm_handler/call_mrm -> /mrm_emergency_stop_operator/on_timer
(+33.33ms sampling)`, `node_criticality` carrying both `/mrm_handler` and
`/mrm_emergency_stop_operator` as `high`, budget still inside 3 s. Then W6's
"open" column loses three lines.

Owns: `third-party/nano-ros` (the pin), `docs/nxp-deployment.md`.

Status: not started; waits on upstream.

### phase6-W9 - the note to the working group

After W6. Not a question but a proposal: a `bounded_by:` relation from which
criticality DECOMPOSES rather than propagates (X may be QM while Y is ASIL-D
exactly when Y bounds every command X produces), which is section 2.2's own
argument and the R6 mitigation-barrier rule play_launch reviewed and did not
implement. Attached: stage 3's run B. Separately and briefly, two errata: N1
is given a "per-message" rate in section 6.1 and a 10 ms partition in 9.1;
N9 (100 Hz in 6.1, P1 at 50 Hz in 9.1) and N12 (1 Hz, P1) make the two
sections derive different orders.

Owns: nothing in this tree.

Status: not started.

### phase6-W6 - the six slides

One per stage, plus the prose-to-diagnostic table that ties them together.
Waits on W1 to W4.

Owns: `~/Downloads/contract-e2e-slides/`, which is outside this repository.

Status: not started.

## 5. Order

W1 first, because W2 and W3 build on its file. W0 is done. W7 is independent
of everything and unblocks silicon; W8 waits on upstream; W6 and W9 last. W2, W3, W4 and W5 are then
independent of one another. W6 last.

## 6. What this phase is not

It is not a claim to have implemented the L4 design. Four declarative
stand-in nodes are not an island. The claim is narrower and holds: the
arithmetic Part 1 defers can be written down and checked today, from Part 1's
own tables.

It is also not a critique of the document. Where a run disagrees with the
design, the finding is reported with its evidence and the design is given the
benefit of being read again first.
