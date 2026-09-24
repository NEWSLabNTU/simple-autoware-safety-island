# Stage 3 - the partitions, run privately first

Unit `phase6-W3`. **This unit does not produce a slide.** It produces a verdict
and a recommendation.

Section 9.1 of "L4 Safety Island for Autoware - Software Design" (v20260918,
Reference Design WG) assigns every island node to one of five executors with a
period and a fixed priority band, and says the island is organised

> following the declarative RT-configuration approach already demonstrated
> (contract facts -> priority bands, `chain_aware` mapper)

So this unit fed that mapper the document's own facts and read back the order
it produces.

Files: `stage3-partitions.*` (the labelled fixture), `stage3-derived.*` (the
same island with criticality derived from the design's own hazard),
`stage3-run.sh`, `stage3-output.txt` (both runs, verbatim).

---

## 1. What was run

```
source /opt/ros/humble/setup.bash
play_launch check <stem>.launch.xml --sched <stem>.system.posix.yaml --explain
```

against `play_launch` 0.10.0 at
`/home/aeon/repos/play_launch/install/play_launch/lib/play_launch/play_launch`.
Nothing was built. No Rust harness was needed: `check --sched --explain` prints
the merged scheduling plan with the mapper's own provenance string per node,
which is the ranked output this unit wanted.

Two fixtures, because there are two different questions:

**Run A, `stage3-partitions`** - 38 nodes: the section 4.1 migrated nodes that
section 9.1 places in a partition, the 20 new nodes of sections 6.1 to 6.4, and
section 9.1's unnamed "telemetry egress". Each carries its section 2.2 tier as
a `criticality:` label and the rate the document gives it. This asks: *can the
mapper reproduce section 9.1's bands when it is told section 2.2's tiers?*

**Run B, `stage3-derived`** - 11 nodes, one or two per partition, wired into
section 9.2's reaction chain, with **no criticality labels at all** and the
design's ASIL_D `hpc_loss` hazard declared instead. This asks the question the
island actually has to live with, because when a contract declares `hazards:`
the checker stops reading the label and derives criticality from the hazard
(play_launch `model_builder.rs`: "the hazards decide first, the authored label
only where no hazard reaches the node"), and stage 1 `l4_designed.contract.yaml`
already declares exactly that hazard.

The priority band is `{min: 10, max: 80}` in both, wider than the node count, so
nothing collapses for want of priorities. Two nodes on one priority came back
that way because the mapper judged them equal.

---

## 2. The mapper's ranked output, verbatim

Reproduce with `bash docs/demo-l4/stage3-run.sh`. Full capture in
`stage3-output.txt`. The excerpts below are the `--explain` provenance tables,
copied unchanged. **The tool's own text contains em dashes and a unicode
arrow**; they are left as the tool printed them.

### Run A - `stage3-partitions`, section 2.2's tiers as labels

```
FQN                                CLASS        PRIO  CORE  PROVENANCE
/i16_vehicle_interface             SCHED_FIFO     80     -  derived(chain_aware: non-chain criticality=Some(High) budget_ms=10) -> prio 80
/i1_control_command_gate           SCHED_FIFO     80     -  derived(chain_aware: non-chain criticality=Some(High) budget_ms=10) -> prio 80
/i2_command_mode_decider           SCHED_FIFO     80     -  derived(chain_aware: non-chain criticality=Some(High) budget_ms=10) -> prio 80
/i3_command_mode_switcher          SCHED_FIFO     80     -  derived(chain_aware: non-chain criticality=Some(High) budget_ms=10) -> prio 80
/i5_stop_mode_operator             SCHED_FIFO     80     -  derived(chain_aware: non-chain criticality=Some(High) budget_ms=10) -> prio 80
/i6_mrm_emergency_stop_operator    SCHED_FIFO     80     -  derived(chain_aware: non-chain criticality=Some(High) budget_ms=10) -> prio 80
/i7_mrm_handler                    SCHED_FIFO     80     -  derived(chain_aware: non-chain criticality=Some(High) budget_ms=10) -> prio 80
/n2_hpc_supervisor                 SCHED_FIFO     80     -  derived(chain_aware: non-chain criticality=Some(High) budget_ms=10) -> prio 80
/n3_state_machine                  SCHED_FIFO     80     -  derived(chain_aware: non-chain criticality=Some(High) budget_ms=10) -> prio 80
/n4_vehicle_state_estimator        SCHED_FIFO     80     -  derived(chain_aware: non-chain criticality=Some(High) budget_ms=10) -> prio 80
/n8_fault_manager                  SCHED_FIFO     80     -  derived(chain_aware: non-chain criticality=Some(High) budget_ms=10) -> prio 80
/n9_actuator_supervisor            SCHED_FIFO     79     -  derived(chain_aware: non-chain criticality=Some(Medium) budget_ms=10) -> prio 79
/i13_pure_pursuit                  SCHED_FIFO     78     -  derived(chain_aware: non-chain criticality=Some(Medium) budget_ms=20) -> prio 78
/i19_autonomous_emergency_braking  SCHED_FIFO     78     -  derived(chain_aware: non-chain criticality=Some(Medium) budget_ms=20) -> prio 78
/i20_collision_detector            SCHED_FIFO     78     -  derived(chain_aware: non-chain criticality=Some(Medium) budget_ms=20) -> prio 78
/i8_control_validator              SCHED_FIFO     78     -  derived(chain_aware: non-chain criticality=Some(Medium) budget_ms=20) -> prio 78
/n10_envelope_monitor              SCHED_FIFO     78     -  derived(chain_aware: non-chain criticality=Some(Medium) budget_ms=20) -> prio 78
/n16_safety_world_model            SCHED_FIFO     78     -  derived(chain_aware: non-chain criticality=Some(Medium) budget_ms=20) -> prio 78
/n5_corridor_monitor               SCHED_FIFO     78     -  derived(chain_aware: non-chain criticality=Some(Medium) budget_ms=20) -> prio 78
/n6_radar_guard                    SCHED_FIFO     78     -  derived(chain_aware: non-chain criticality=Some(Medium) budget_ms=20) -> prio 78
/n7_mrm_planner                    SCHED_FIFO     78     -  derived(chain_aware: non-chain criticality=Some(Medium) budget_ms=20) -> prio 78
/n13_scan_guard                    SCHED_FIFO     77     -  derived(chain_aware: non-chain criticality=Some(Medium) budget_ms=25) -> prio 77
/n14_vision_guard                  SCHED_FIFO     76     -  derived(chain_aware: non-chain criticality=Some(Medium) budget_ms=50) -> prio 76
/n15_proximity_guard               SCHED_FIFO     76     -  derived(chain_aware: non-chain criticality=Some(Medium) budget_ms=50) -> prio 76
/n18_pull_over_manager             SCHED_FIFO     76     -  derived(chain_aware: non-chain criticality=Some(Medium) budget_ms=50) -> prio 76
/n17_sensor_health                 SCHED_FIFO     75     -  derived(chain_aware: non-chain criticality=Some(Medium) budget_ms=100) -> prio 75
/n20_object_digest                 SCHED_FIFO     75     -  derived(chain_aware: non-chain criticality=Some(Medium) budget_ms=100) -> prio 75
/n19_odd_monitor                   SCHED_FIFO     74     -  derived(chain_aware: non-chain criticality=Some(Medium) budget_ms=200) -> prio 74
/n12_time_quality_monitor          SCHED_FIFO     73     -  derived(chain_aware: non-chain criticality=Some(Medium) budget_ms=1000) -> prio 73
/i10_mpc_lateral_controller        SCHED_FIFO     72     -  derived(chain_aware: non-chain criticality=Some(Low) budget_ms=20) -> prio 72
/i11_pid_longitudinal_controller   SCHED_FIFO     72     -  derived(chain_aware: non-chain criticality=Some(Low) budget_ms=20) -> prio 72
/i12_trajectory_follower_base      SCHED_FIFO     72     -  derived(chain_aware: non-chain criticality=Some(Low) budget_ms=20) -> prio 72
/i14_shift_decider                 SCHED_FIFO     72     -  derived(chain_aware: non-chain criticality=Some(Low) budget_ms=20) -> prio 72
/i15_raw_vehicle_cmd_converter     SCHED_FIFO     72     -  derived(chain_aware: non-chain criticality=Some(Low) budget_ms=20) -> prio 72
/i9_trajectory_follower_node       SCHED_FIFO     72     -  derived(chain_aware: non-chain criticality=Some(Low) budget_ms=20) -> prio 72
/n11_event_recorder                SCHED_FIFO     71     -  derived(chain_aware: non-chain criticality=Some(Low) budget_ms=100) -> prio 71
/telemetry_egress                  SCHED_FIFO     71     -  derived(chain_aware: non-chain criticality=Some(Low) budget_ms=100) -> prio 71
/n1_safety_gateway                 SCHED_OTHER     0     -  default (no timing facts)
```

### Run B - `stage3-derived`, criticality from the design's own hazard

```
FQN                          CLASS       PRIO  CORE  PROVENANCE
/i16_vehicle_interface       SCHED_FIFO    80     -  derived(chain_aware: island.mrm_command segment drain 1/4) -> prio 80
/i1_control_command_gate     SCHED_FIFO    79     -  derived(chain_aware: island.mrm_command segment drain 2/4) -> prio 79
/n3_state_machine            SCHED_FIFO    78     -  derived(chain_aware: island.mrm_command segment drain 3/4) -> prio 78
/n2_hpc_supervisor           SCHED_FIFO    77     -  derived(chain_aware: island.mrm_command segment drain 4/4) -> prio 77
/n4_vehicle_state_estimator  SCHED_FIFO    76     -  derived(chain_aware: non-chain criticality=None budget_ms=10) -> prio 76
/i10_mpc_lateral_controller  SCHED_FIFO    75     -  derived(chain_aware: non-chain criticality=None budget_ms=20) -> prio 75
/i13_pure_pursuit            SCHED_FIFO    75     -  derived(chain_aware: non-chain criticality=None budget_ms=20) -> prio 75
/n16_safety_world_model      SCHED_FIFO    75     -  derived(chain_aware: non-chain criticality=None budget_ms=20) -> prio 75
/n11_event_recorder          SCHED_FIFO    74     -  derived(chain_aware: non-chain criticality=None budget_ms=100) -> prio 74
/n17_sensor_health           SCHED_FIFO    74     -  derived(chain_aware: non-chain criticality=None budget_ms=100) -> prio 74
/n12_time_quality_monitor    SCHED_FIFO    73     -  derived(chain_aware: non-chain criticality=None budget_ms=1000) -> prio 73
```

Run B also reproduces stage 1's budget line unchanged, from a different file:

```
  info[fault-reaction-budget]: hazard 'hpc_loss': detection 30.00ms (/n2_hpc_supervisor/heartbeat detects within 30.00ms) + reaction 40.00ms (reaction route /n2_hpc_supervisor/declare_hpc_lost → /n3_state_machine/escalate → /i1_control_command_gate/select_mrm_source → /i16_vehicle_interface/transmit = 40.00ms) = 70.00ms fits the fault-tolerant time interval 70.00ms with 0.00ms of slack
```

(unicode arrow in the tool's output, left as printed).

---

## 3. Side by side - section 9.1's five bands versus the derived order

Priority runs high to low. A shared PRIO means the mapper ranked those nodes
equal.

| Design band (9.1) | Nodes | Run A prio | Run B prio |
| :-- | :-- | :-- | :-- |
| **1 - P0 safety core**, 100 Hz, ASIL-D | I1 I2 I3 I5 I6 I7 I16 N2 N3 N4 N8 | **80** | 80-77 chain, **76** for N4 |
| | N1 `si_safety_gateway` (T0, ASIL-D) | **0, SCHED_OTHER** | not in run B |
| **2 - P1 supervision + fallback**, 50 Hz, ASIL-B(D) | N9 | **79** | - |
| | I8 I13 N5 N7 N10 | **78** | I13 at **75** |
| | N18 | **76** | - |
| | N12 | **73** | **73** |
| **3 - P2 safety sensing**, 20-50 Hz, ASIL-B(D) | I19 I20 N6 N16 | **78** | N16 at **75** |
| | N13 | **77** | - |
| | N14 N15 | **76** | - |
| | N17 N20 | **75** | N17 at **74** |
| | N19 | **74** | - |
| **4 - P3 nominal control**, 33-50 Hz, QM | I9 I10 I11 I12 I14 I15 | **72** | I10 at **75** |
| **5 - P4 non-real-time**, 1-10 Hz, QM | N11, telemetry egress | **71** | N11 at **74** |

Read down the two derived columns and the shape of the answer is visible before
any argument about it:

- Run A: `80 | 79 78 77 76 75 74 73 | 72 71` - **three** blocks, not five, and
  P1 and P2 are inside the same block, interleaved.
- Run B: the reaction chain, then one undifferentiated slope in which P3's MPC,
  P1's fallback controller and P2's world model all sit on **75**, and P4's
  event recorder sits on **74**, *above* P1's `N12` on 73.

---

## 4. VERDICT

**They do not agree. Run A agrees on the shape of the ends and loses the
middle; run B loses almost all of it.**

Taken claim by claim.

### 4.1 P0 is reproduced exactly, and that is real

Run A puts all eleven labelled T0 nodes on priority 80, above everything, with
no exception and no near-miss. Run B independently puts section 9.2's four-node
reaction chain on 80-77 by drain-toward-sink, which is the same claim arrived at
from a hazard rather than a label. **Band 1 of section 9.1 is a derived result,
not just an assertion.** That much of section 9.1's sentence holds.

### 4.2 P1 and P2 cannot be separated, and the reason is in the design's own tables

This is the central disagreement and it is not a bug.

`chain_aware`'s non-chain ranking (ros-launch-manifest,
`sched/src/chain_aware_mapper.rs`, algorithm step 4) orders by exactly two
facts: the node's **criticality bucket**, then one ascending **time budget**
(`1000/rate_hz` for a timer path). Section 2.2 gives T1 and T1s the **same**
target integrity, ASIL-B(D). Section 9.1 gives P1 a 20 ms period and P2 a
20-50 ms period, which overlap at 20 ms. So on both of the mapper's two axes,
P1 and P2 are indistinguishable in the document's own tables, and run A shows
them interleaved on priority 78: `i13_pure_pursuit` (P1) alongside
`i19_autonomous_emergency_braking` and `n16_safety_world_model` (P2).

What actually separates them in the design is a **policy** stated in prose:

> Under overload the island sheds the expensive MPC first ... Shedding sensing
> instead would silently downgrade an obstacle-aware MRM to a blind one - the
> worse outcome.

That is a degradation preference between two elements of equal integrity and
overlapping rate. **No fact in the contract language expresses it**, so no
mapper reading that contract can produce it. This is a *missing fact*, not a
mapper limitation and not a disagreement about the right order.

### 4.3 P3 below P2 - the deliberate part - agrees in run A, and inverts in run B

Section 9.1 argues its most counter-intuitive edge explicitly: the QM nominal
controller sits *below* ASIL-B sensing.

In run A the mapper agrees: `i10_mpc_lateral_controller` lands on 72, below
every P2 node. But read the provenance for why. The MPC's `budget_ms=20` is
*shorter* - more urgent, by rate-monotonic - than `n17_sensor_health`'s 100,
`n19_odd_monitor`'s 200 and `n12_time_quality_monitor`'s 1000. **Rate alone
would have put the MPC above them.** The only thing holding section 9.1's
deliberate ordering in place is the `criticality=Some(Low)` bucket, i.e. the
hand-written label.

Run B removes the label and asks the hazard instead, and the ordering inverts:
`i10_mpc_lateral_controller` (QM) comes back on **75, the same priority as
`i13_pure_pursuit` (ASIL-B fallback) and `n16_safety_world_model` (ASIL-B
sensing)**. That is precisely the outcome section 9.1 says must not happen. It
is worse than a tie, because the run also prints:

```
  warning[sched:other]: scheduling: /i10_mpc_lateral_controller, /i13_pure_pursuit, /n16_safety_world_model share RT priority 75 and SCHED_RR was not derived to time-slice between them, because the platform file does not declare `resources.rr_timeslice`, so the host's slice is unknown — it is not assumed to be the 100ms default. Under SCHED_FIFO whichever runs first holds the CPU until it blocks.
```

(em dash in the tool's output.) Under `SCHED_FIFO` at equal priority, the MPC
can hold the CPU until it blocks, against the fallback controller that is
supposed to replace it "within one cycle". And one row further down, P4's
`n11_event_recorder` (QM telemetry) sits on **74, above** P1's
`n12_time_quality_monitor` on 73.

### 4.4 Why run B loses the tiers: the derivation is reachability, not decomposition

Every off-chain node in run B comes back `criticality=None` - including
`n4_vehicle_state_estimator`, which section 2.2 puts in the **ASIL-D** safety
core. The implemented derivation (play_launch,
`manifest_loader.rs::derive_criticality_from_hazards`) assigns severity to
exactly three roles: publishers of a guard topic and their upstream closure
(`feeds`), the subscriber whose `on_violation` detects the fault (`detects`),
and every hop of the reaction walk (`reacts`). A node that is neither on the
guard's ancestry nor on the reaction route gets nothing at all, whatever its
tier.

So section 2.2's five tiers survive only as hand-written labels, and the moment
a contract declares the hazard the design is about, the labels stop being read.
**The two mechanisms the contract offers for criticality do not compose**: you
get the labels or you get the hazard, and the design needs both.

This is worth stating carefully to the WG, because it is the same gap on both
sides. Section 2.2's argument is *ASIL decomposition by monitoring*: "a
lower-integrity nominal controller is admissible because a higher-integrity
arbiter bounds its output." play_launch's own design note for the derivation
proposes that rule as **R6, mitigation barriers**, and records that it was
reviewed and deliberately **not implemented** (`docs/design/criticality-from-hazards.md`,
`r6-mitigation-barriers-review.md`). The design's central structural argument
and the checker's unimplemented rule are the same idea. Neither side can
currently check it.

### 4.5 N1, the ASIL-D node that ranks below everything

Section 6.1 gives `N1 si_safety_gateway` the tier T0 (ASIL-D) and the rate
column **"per-message"**. It is the E2E gateway every HPC message crosses.
The fixture declines to invent a period for it, and the run says:

```
/n1_safety_gateway                 SCHED_OTHER     0     -  default (no timing facts)
```

Not merely last in the real-time band - outside it, on `SCHED_OTHER`. An
ASIL-D node in P0 with no derived real-time priority at all, because the
document gives it no period and no latency budget. This is a genuine gap in
section 9.1's table: P0 lists N1 as a member of a 10 ms executor, and section
6.1 says N1 is not periodic. One of the two has to give.

### 4.6 Section 6.x and section 9.1 disagree with each other

Independently of the mapper, the document's per-node rates do not fit its own
partition periods:

- `N9 si_actuator_supervisor` - P1 (20 ms period), section 6.1 says **100 Hz**.
  Run A ranks it on 79, alone, above every other P1 and P2 node.
- `N12 si_time_quality_monitor` - P1 (20 ms period), section 6.1 says **1 Hz**.
  Run A ranks it on 73, below every P2 node including the 2-5 Hz ODD monitor.
- `N17` (5-10 Hz) and `N19` (2-5 Hz) are in P2, whose stated period is
  20-50 ms.

An executor's period is not each member's rate, so this is not a contradiction
on its face. But it means section 9.1's "Period" column cannot be read as the
cadence of its members, and a reader deriving a schedule from the table will
get a different answer from a reader deriving one from sections 6.1 to 6.4.
Both readings are in this fixture and they produce different orders.

### 4.7 The disclosure: `exec_ms` is absent, and supplying it changes nothing here

Verified in the source, both roads:

- **nano-ros.** `WcetProfile` reaches the derivation only through
  `mapper_input_from_model_with_wcet(model, Some(&profile))`
  (`packages/core/nros-orchestration-ir/src/mapper_input.rs`). Its only two
  callers in the tree are at lines 155 and 214, inside that file's own
  `#[cfg(test)]` module, which starts at line 108. The production entry,
  `derive_tiers_from_contracts` in `derive.rs:58`, calls
  `mapper_input_from_model(model)`, which is `..._with_wcet(model, None)`.
  `wcet_profile_for`, the function that would *select* a profile
  (`packages/cli/nros-cli-core/src/orchestration/cargo_metadata_schema.rs:889`),
  has callers only at lines 2916, 2932, 2938, 2948, 2964 and 2981, all inside
  the `#[cfg(test)]` module that starts at line 2873. **Confirmed: on the
  nano-ros road every road in production runs with `exec_ms = None`.**

- **play_launch.** The briefing's wording needs one correction.
  `mapper_input_from_model` does **not** pass `None` unconditionally. It is
  called with `derive_facts_from_budgets(posix_budgets(platform_file))`
  (`src/ros-launch-resolve/resolve/src/ros/sched_derive.rs`), so `exec_ms` is
  filled from a platform file's `budget:` override - and only when the node has
  exactly one path, because `DeriveFacts::exec_ms_for` refuses to split a node
  budget across several paths. The practical conclusion is the same, because no
  contract in this tree declares a `budget:`, but the mechanism exists and the
  gap is a missing *declaration*, not a missing code path.

And the sharper half, which is the part worth taking to the WG. `exec_ms` is
read in exactly one place: `chain_feasibility`, the sum of a chain's **boundary**
`period_ms + exec_ms`. It feeds (a) whether a chain is flagged infeasible and
(b) the relative order of *several* chains by slack. It plays **no part** in
step 3's within-chain drain order and **no part** in step 4's non-chain
criticality-and-budget ranking - the ranking every node in both runs went
through. Confirmed by experiment: a scratch copy of run B with a `budget:`
declared for seven of the eleven nodes, including 18 ms for the MPC on its 20 ms
period and 0.9 ms for the pure-pursuit fallback, returns the **identical**
priority sequence 80, 79, 78, 77, 76, 75, 75, 75, 74, 74, 73. The MPC at 90%
utilisation still ranks equal to the fallback that is meant to replace it.

So: **the ranking is by rate and criticality bucket alone, and supplying the
missing execution times would not change it.** Section 9.1 asks Part 2 to
*prove* the partitions. This is the exact shape of the gap between deriving an
order and proving a schedule: the derivation is a total order over nodes, and it
never forms the inequality that a proof is - no utilisation sum, no response-time
recurrence, no interference term. The tool says the same thing about itself
elsewhere, in the words it uses when a chain's boundary has no WCET: "feasible
ON INCOMPLETE EVIDENCE ... The reported slack is an upper bound on what the
chain can afford, not a statement about what it costs."

### 4.8 Is the difference a mapper limitation, a missing fact, or a real disagreement?

All three are present, and separating them is the finding:

| Where | Which kind | Evidence |
| :-- | :-- | :-- |
| P0 at the top | agreement | run A prio 80; run B chain drain 80-77 |
| P1 vs P2 not separable | **missing fact** - no contract vocabulary for a degradation preference between equal-integrity partitions | run A, nine P1 and P2 nodes on prio 78 |
| P3 below P2 under labels | agreement, but carried entirely by the criticality bucket | run A, MPC 72 with `budget_ms=20`, below `n17` 75 with `budget_ms=100` |
| P3 equal to P1 and P2 under hazards | **mapper limitation** - the derivation is reachability, not ASIL decomposition; the barrier rule R6 is designed and not implemented | run B, three nodes on prio 75 |
| N1 outside the real-time band | **missing fact in the design** - T0 with no period | run A, `SCHED_OTHER 0` |
| 6.x rates vs 9.1 periods | **the design disagreeing with itself** | run A, N9 on 79, N12 on 73 |
| `exec_ms` absent everywhere | **missing fact**, and one that would not move the order | scratch WCET run, identical sequence |

Nothing here is a genuine disagreement about the *right* order. Section 9.1's
ordering is argued and the argument is sound; the tool has no way to reach it,
and says so rather than contradicting it. That is the honest framing.

---

## 5. RECOMMENDATION

**Not a slide. It belongs in the "open" column, and one row of it belongs in a
conversation with the WG before the talk.**

Three reasons it should not be a slide.

1. **It cannot be shown in one screen without misleading.** The single most
   quotable line - "the derivation puts the QM MPC at the same priority as the
   ASIL-B fallback" - is true only of run B, and only because the criticality
   derivation is reachability-based. On a slide, stripped of that, it reads as
   "the tool contradicts the design", which is not what happened and is not
   fair to either.

2. **Run A's agreement is weaker than it looks and the weakness is the point.**
   P3 below P2 comes out right, but only because the fixture wrote section 2.2's
   tiers in by hand; and the moment the design's own hazard is declared, the
   labels stop being read. A slide would have to show both runs and explain why
   they differ, which is a five-minute argument, not a slide.

3. **Stages 0, 1, 2 and 4 all end in a checker diagnostic with a number in it.**
   This one ends in an ordering that has to be argued about. It is a different
   kind of claim and putting it in the same deck would weaken the four that are
   clean.

What to do with it instead:

- **Open column, one line.** "Section 9.1's P0 band is reproduced by the mapper
  it names; bands 2 and 3 are not separable from the facts the document states,
  and the ordering of band 4 under band 3 depends on a criticality source the
  tool does not currently derive." That is accurate, short, and invites the
  question rather than answering it.

- **To the WG, one question, with run B attached.** Section 2.2's safety
  argument is ASIL decomposition by monitoring. play_launch's criticality
  derivation designed that exact rule as R6 and deliberately did not implement
  it. The question to ask is not "is your table right" - it is *"what fact
  should a contract state so that a tool can derive T2 as QM-under-a-bounding-arbiter
  rather than as reachable-from-a-hazard?"* That is a question the WG is better
  placed to answer than this repository, it is the pre-condition for section
  9.1's ordering being derivable at all, and it is a contribution rather than a
  correction.

- **To the WG, one editorial note.** N1's "per-message" rate and the 6.x-versus-9.1
  rate disagreements (4.5, 4.6) are small, concrete and easy to fix in Part 1.
  They are worth reporting as errata, separately from the structural question,
  and they are the kind of finding that demonstrates the contract was actually
  read rather than admired.

- **If the talk wants one sentence from this unit**, the disclosure in 4.7 is
  the one that earns its place, because it is about this toolchain's own limits
  rather than about someone else's document: *the derivation ranks by rate and
  criticality alone, every road in production runs with no execution-time data,
  and supplying that data would not change the order - which is exactly why
  section 9.1 is right to say Part 2 must prove the partitions rather than
  observe them.*

---

## 6. What was NOT run, and why

- **No Rust harness, no `cargo` anything.** `check --sched --explain` prints the
  mapper's ranked plan with its provenance, so `chain_aware_rank` was exercised
  through the shipped 0.10.0 binary and never rebuilt. The cargo package cache
  was never touched.
- **play_launch was not rebuilt** and no board build was run, per the phase
  protocol.
- **The `exec_ms` experiment in 4.7 ran from the session scratchpad**, not from
  this tree, because it is a negative control rather than a deliverable: it
  exists to show that a fact the fixture does not declare would not have changed
  the answer. It is a copy of `stage3-derived.*` with a `budget:` per node added
  to the platform file; the priority sequence it returns is quoted in 4.7 and is
  identical to run B's.
- **Nothing was committed, pushed, or opened as a PR**, and nothing outside
  `docs/demo-l4/stage3-*` was modified in this repository. No file in
  `ros-launch-manifest` or `play_launch` was modified.
