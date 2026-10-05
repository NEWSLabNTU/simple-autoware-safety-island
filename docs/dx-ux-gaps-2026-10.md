# DX / UX gaps in the launch-contract toolchain (2026-10)

Scope: ros-launch-manifest grammar (rlm), play_launch (checker and launcher),
nano-ros (RTOS client library and image derivation), and the Autoware safety
island demo on the S32K344 (simple-autoware-safety-island, "SAI").
Read-only survey, 2026-10-03. Every gap cites a file and line or section.
Nothing was re-measured except where marked VERIFIED 2026-10-03.

Audiences:

- DEV: writes a contract beside an Autoware launch file, runs
  `play_launch check`, builds a nano-ros image, flashes the board, reads a
  trace.
- USER-WG: a working-group engineer adopting contracts in CI.
- USER-BOOTH: a booth presenter or visitor running the three-act demo.

Field legend for every gap:

- Hits: who meets it.
- Sev: BLOCKS (cannot proceed or the claim is unsupported), HOURS (costs
  hours or days once), COSMETIC (friction, noise, misreading).
- Owner: SAI, PL (play_launch), RLM, NR (nano-ros), UP (upstream zenoh /
  rmw_zenoh / rclcpp / Zephyr).
- Tracked: P9 Wn (SAI docs/roadmap/phase-9-rtss-demo-open-items.md),
  PL85 Dn/In/Tn (play_launch docs/roadmap/phase-85-what-the-island-left-open.md),
  NR474 Dn/In/Tn (nano-ros worktree nros-island-phase,
  docs/roadmap/phase-474-safety-island-board-findings.md), NR #nnnn (an open
  nano-ros docs/issues file), or UNTRACKED.

Path shorthands: P8 = SAI docs/roadmap/phase-8-rtss-work-demo.md; TT = SAI
docs/takeover-trace.md; CON = SAI
src/safety_island_bringup/launch/safety_island.contract.yaml; CONF = SAI
src/zephyr_entry/boards/mr_canhubk3_s32k344.conf; L3R = SAI demo/l3/README.md;
TRI = SAI docs/board-bringup-triage.md; DECK = ~/Downloads/contract-e2e-slides;
MEM = ~/.claude/projects/-home-aeon-repos-simple-autoware-safety-island/memory.

Note on sources: the nano-ros checkout at ~/repos/nano-ros is at 7a0713318
(2026-08-20) and its docs/issues stops near 0414; the island's pin and every
issue the island cites (1533, 1534, 1567...) live in newer trees. Issue
titles below were read from /mnt/mx500/aeon/worktrees/nros-island-phase
(9c15b76d9, 2026-10-01; 209 files with `status: open`). That stale default
checkout is itself gap 3.1.

--------------------------------------------------------------------------------

## 1. Authoring a contract

### 1.1 The contract cannot hold its own rationale; two thirds of the file is comment

- Hits: DEV, USER-WG.
- What: the island contract carries a 102-line head comment (CON:1-102)
  before `version: 1` at CON:103, and 546 of its 804 lines are comments.
  The comments explain things the grammar cannot say: why the platform
  file is not needed (CON:15-21), why endpoint keys are local names
  (CON:32-35), why services must be declared or pools under-size
  (CON:76-80), where every number comes from (CON:156-241), why the
  intervals are judgements (CON:242-258), and which warnings are true and
  left alone (CON:307-318). A second author inherits an essay, not a model.
- Evidence: CON:1-103; `grep -c '^ *#'` = 546 of `wc -l` 804 (VERIFIED
  2026-10-03). The board conf has the same shape: CONF is 700 lines, 607 of
  them comments.
- Sev: HOURS. Owner: RLM (a provenance / `source:` field per number),
  SAI. Tracked: UNTRACKED.

### 1.2 Composite budgets: no keys for transport on the walk, timer jitter, or service-edge cost

- Hits: DEV.
- What: `call_mrm: 206ms` is link 57 + tick 118 + work 31 folded into one
  node-path latency because rlm/play_launch 0.13.0 has no place for each
  term (CON:176-194). The tick share is duplicated by hand as
  `analysis.TICK_MS` in tools/timeline (TT section 10, "rlm has no key for a
  timer's release jitter"). After the window's deadline the 57 ms link term
  is pure slack, charged anyway.
- Evidence: TT:759-800 (Where each term is stated), TT:922-944 (F1-F5);
  PL85:37-45.
- Sev: HOURS (every budget change is hand arithmetic in a comment).
  Owner: RLM, PL. Tracked: PL85 D1, D2, I1; P9 W5.

### 1.3 A declared key that the checker silently ignores (`max_transport`)

- Hits: DEV, USER-WG.
- What: `max_transport: 57ms` on the handler's availability subscriber is
  legal grammar and changes nothing: "the island contract's `--explain`
  output is byte-identical with and without the key". No diagnostic says
  "declared, not charged". An author reasonably believes the link is
  budgeted.
- Evidence: TT:770-781; PL85:26-35.
- Sev: HOURS. Owner: PL. Tracked: PL85 I1, T1 (the fix); the missing
  "not charged" notice is UNTRACKED.

### 1.4 A budget is also a deadline and a runtime monitor

- Hits: DEV.
- What: a node-path `max_latency` becomes nano-ros's derived node deadline
  and a `max-latency-runtime` monitor row. So the comfortable-stop
  operator's 0.85-1.18 ms serve cost cannot be stated where it happens
  without baking a 2 ms monitor and deadline into the image; the author
  hides it inside `call_mrm` instead.
- Evidence: TT:782-790; NR474 D4 (lines 138-154); PL85 D2 (lines 67-75).
- Sev: HOURS, structural. Owner: RLM, NR. Tracked: PL85 D2, NR474 D4.

### 1.5 No way to say "on-demand, no minimum rate"

- Hits: DEV.
- What: two on-demand topics carry `min_rate_hz: 10`; on the board they
  raise `rate-hierarchy-runtime` at start-up and take 2 of the 8 violation
  slots before any act.
- Evidence: TT:1134-1160 ("The ring"); PL85 D3 (lines 76-81); NR474 D2
  table (lines 88-95).
- Sev: HOURS (pollutes the only violation store). Owner: RLM (key) or SAI
  (drop the claim). Tracked: PL85 D3, P9 W7.

### 1.6 Declaration is never cross-checked against the code

- Hits: DEV.
- What: an omitted endpoint under-sizes every pool and is found only at
  boot (`ExecutorFull`, or "an opaque transport error"; the 2026-09-04
  seventh subscription "cost several days", CON:23-28). A phantom endpoint
  over-sizes pools and is never found. An endpoint under `sub:` but absent
  from `topics:` is dropped with no diagnostic, because counts come from
  the wiring. Omitting services under-derived MAX_QUERYABLES (CON:76-80).
- Evidence: DECK/brief-D-island-experiments.md:363-386 (E3a-E3c) and the
  summary table at :784-805; DECK/brief-B-nanoros-chain.md:560-566
  ("TRUSTED: that sub:/pub:/srv:/cli: lists equal what the code creates").
  Brief D ran on play_launch 0.10.0; E3c should be re-checked on 0.13.0.
- Sev: BLOCKS (silent under-size reaches the board). Owner: NR (code-side
  declared_qos / registration counts vs the model), PL. Tracked: UNTRACKED.

### 1.7 Author-chosen names are unchecked; an absolute endpoint path is silently malformed

- Hits: DEV.
- What: endpoint keys are LOCAL names; an absolute path "is concatenated
  onto the node FQN and produces a malformed `/node//abs/path` endpoint
  that matches no topic" (CON:32-35). The closed grammar deliberately does
  not check author-chosen keys (node, topic, endpoint, path names).
- Evidence: CON:32-35; DECK/brief-A-rlm-grammar.md:31-41 (field_table.rs:31-38,
  parse.rs:1191-1193).
- Sev: HOURS. Owner: RLM (refuse a `/` in an endpoint key). Tracked:
  UNTRACKED. Cheap.

### 1.8 Parameter-derived numbers are restated by hand except where a binding exists

- Hits: DEV.
- What: the window is bound to `takeover_request_timeout` (`window-param`
  refuses a mismatch) and settle is derived from the operators' parameter
  files, but the 500 ms FDTI is restated by hand as `lease_duration: 500ms`
  "the same fact in the vocabulary FDTI is derived from", and the timer
  rates are asserted in prose to equal each node's `update_rate`.
- Evidence: CON:42-44, CON:158-166, CON:199-202 (window-param), CON:226-232
  (settle derived).
- Sev: COSMETIC to HOURS (drift risk). Owner: RLM/PL (generalise the
  param binding). Tracked: UNTRACKED.

### 1.9 Criticality propagates by reachability; decomposition cannot be stated

- Hits: USER-WG.
- What: with the L4 design's own hazard declared, the QM MPC ranks EQUAL
  to the ASIL-B fallback meant to replace it, because derived criticality
  is reachability. No fact expresses "Y bounds every output of X". The
  `bounded_by:` relation is proposed, not implemented.
- Evidence: DECK/WG-NOTE.md:30-60; DECK/OPEN-QUESTIONS.md:212-229.
- Sev: BLOCKS for adopting the scheduler derivation on the L4 design;
  structural. Owner: RLM + WG. Tracked: UNTRACKED (WG proposal only).

### 1.10 Weak "did you mean" and one-error-at-a-time parse

- Hits: DEV.
- What: `max_rate` (meant `max_rate_hz`) gets "did you mean `max_age`?";
  the whole file is dropped on the first unknown key.
- Evidence: DECK/brief-C-playlaunch-usage.md:458-490.
- Sev: COSMETIC. Owner: RLM. Tracked: UNTRACKED.

### 1.11 Grammar documentation drifts behind the parser

- Hits: DEV, USER-WG.
- What: as of rlm v0.1.34 the hand-written docs/launch-manifest.md,
  docs/slides.md, scheduling.md and contract-verification.md showed
  spellings that are parse errors (`max_drop_rate`, `max_latency_ms`,
  top-level `sub:`) and removed rules (`chain-*`); the runtime monitor had
  no user guide. play_launch issues 0036 and 0038 are marked resolved
  (play_launch docs/issues/README.md:19-22, "None" open), so re-verify at
  0.13.0 / rlm v0.1.47 before quoting. Only the generated
  docs/format-reference.md is current by construction.
- Evidence: DECK/brief-A-rlm-grammar.md:1204-1341; DECK/brief-C:273-285.
- Sev: HOURS for a newcomer who learns from the docs. Owner: RLM, PL.
  Tracked: PL 0036/0038 (resolved; unverified here).

--------------------------------------------------------------------------------

## 2. Checking (play_launch check)

### 2.1 The play_launch on PATH is too old, and the error does not say so

- Hits: DEV, USER-WG.
- What: `~/.local/bin/play_launch` reports 0.12.0. On the island contract
  it prints "at 'hazards.hpc_loss.entry_speed': unknown key in
  `hazards.<name>` ... Every contract in this file is now UNCHECKED" and
  exits 1. Nothing says "this contract needs play_launch >= 0.13.0"; the
  contract states only `version: 1` (CON:103). The island's own doctor
  still accepts it: `PLAY_LAUNCH_MIN := "0.8.2"` (justfile:73), .envrc:14
  and scripts/env.sh:21 warn only below 0.8.2, while CI pins 0.13.0
  (.github/workflows/check.yml:21).
- Evidence: VERIFIED 2026-10-03 (`play_launch check
  src/safety_island_bringup/launch/safety_island.launch.xml`, exit 1).
- Sev: BLOCKS (every fresh shell). Owner: SAI (doctor minimum, one line),
  RLM (a minimum-tool or grammar version in the file, and an "unknown key
  that a newer grammar knows" message). Tracked: UNTRACKED.

### 2.2 Two binaries that both call themselves 0.12.0 disagree

- Hits: DEV.
- What: the source build at
  ~/repos/play_launch/build/.cargo_target/play_launch/release/play_launch
  also reports "play_launch 0.12.0" and passes the same contract clean
  (0 errors, 2 warnings); the pip wheel fails it. The version string does
  not identify the grammar. Older form of the same trap: a wheel that
  bundled a 0.5.1 binary while pyproject said 0.8.2 (demo-runbook.md:36-41),
  and a stale binary in src/.../target that "silently ignores newer
  contract fields" (MEM/play-launch-stale-target-dir.md).
- Evidence: VERIFIED 2026-10-03; L3R:515-520 (trap 10);
  .github/check-contracts.sh:9-11; demo-runbook.md:232-236.
- Sev: HOURS. Owner: PL (git describe / rlm tag in `--version`).
  Tracked: UNTRACKED. Cheap.

### 2.3 Three play_launch version surfaces move independently

- Hits: DEV, USER-WG.
- What: PATH (0.12.0), the CI pin (0.13.0, pip), and the copy vendored
  inside nano-ros (third-party/nano-ros/packages/cli/third-party/play_launch,
  moved by nano-ros PRs: P8:368-369 "nano-ros PR 1394 moves the vendored
  pin to play_launch 92043c82 / rlm v0.1.46"). CI's EXPECT could not flip
  until a release past 0.12.0 reached the package index (P8:502-507). The
  deck's "What NOT to say" warns that line numbers from the vendored copy
  are stale (DECK/OUTLINE.md:492-512).
- Sev: HOURS. Owner: SAI, NR, PL. Tracked: UNTRACKED.

### 2.4 CI negative tests compare exit codes only

- Hits: USER-WG.
- What: `.github/check-contracts.sh` expects exit 1 for six contracts
  meant to fail a specific rule ("each must fail its comfortable-stop rung
  and nothing else") but compares only `$got = $want`
  (check-contracts.sh:20-34, 47-55). A `manifest-parse` failure also exits
  1, so a play_launch too old to parse the variants would report them
  "ok". The `--format json` output exists and is not used.
- Evidence: .github/check-contracts.sh:20-55; 2.1 above (0.12.0 exits 1
  on parse).
- Sev: HOURS (false confidence in CI). Owner: SAI. Tracked: UNTRACKED.
  Cheap (match the rule id per EXPECT row).

### 2.5 Output is hard to read in CI logs and in ASCII documents

- Hits: USER-WG, DEV.
- What: log lines carry ANSI colour codes even when redirected (the CI
  script strips them with sed, check-contracts.sh:48, 53); a parse error is
  printed twice (a WARN log line and the error block); diagnostic lines are
  unwrapped up to 463 characters; non-ASCII appears in normal output: the
  box-drawing rule (U+2500), an em dash (U+2014), and a U+2192 arrow in the
  fault-reaction-budget route ("call_mrm <U+2192> ..."). Brief A had to
  transliterate em dashes for an ASCII document (brief-A:16-19); the deck
  build fails on non-ASCII (DECK/CLAUDE.md, "The build fails ... on any
  non-ASCII character").
- Evidence: VERIFIED 2026-10-03 on the source build: 4 box-drawing, 2 em
  dash, 2 arrow characters with `--explain`; longest line 463.
- Sev: COSMETIC. Owner: PL (`--color never` when not a TTY, an `--ascii`
  or plain mode, wrap). Tracked: UNTRACKED. Cheap.

### 2.6 `--explain` is documented as something else

- Hits: DEV.
- What: `check --help` (0.12.0) describes `--explain` as the scheduling
  plan's provenance, "Only meaningful together with a resolved scheduling
  platform file ... a no-op note is printed otherwise". The hazard budget
  table (HAZARD RUNG ROLE DETECT WINDOWS ROUTE SETTLE TOTAL FTTI SLACK),
  which is what the island and the timeline use, is not mentioned. The
  ROUTE column shows 206.00 as one number; its link/tick/work terms are
  visible only in the contract comment (see 1.2).
- Evidence: VERIFIED 2026-10-03 (`check --help`, `check --explain`);
  TT:841-850.
- Sev: COSMETIC. Owner: PL. Tracked: UNTRACKED.

### 2.7 `--export-graph` leaves out what the reaction walk uses

- Hits: DEV, USER-WG (tooling, the deck's graph figure).
- What: the JSON has only version, nodes, topics, pub_edges, sub_edges,
  node_paths, scope_paths, cycles. No services or service edges (the
  island's reaction crosses `operate`), no externals, no hazards / modes /
  ladder, and no path trigger (a timer path appears as `"input": []`).
  Nodes carry only fqn and scope_id.
- Evidence: VERIFIED 2026-10-03 (source build, island contract; 3 nodes,
  13 topics, 6 node paths, 0 service entries).
- Sev: HOURS (anything drawn from it misses the service hop the budget
  depends on). Owner: PL. Tracked: UNTRACKED.

### 2.8 Verdicts depend on the shell's environment

- Hits: DEV, USER-WG.
- What: (a) the island contract gives 5 warnings without Autoware's `.msg`
  files on the index and 2 with (TT:831-833); (b) from a login shell the
  demo's host_ws shadows stock `tier4_system_launch`, so an Autoware check
  parses 163 scopes / 33 nodes / 2 manifests instead of 169 / 34 / 4, and
  every MRM hazard reads `hazard-unguarded` (MEM/demo-host-ws-shadows-stock-autoware.md;
  DECK/OPEN-QUESTIONS.md:22-49: "It cost most of 2026-09-24"). `just
  l3-check` therefore runs under `env -i` (just/l3-demo.just:185-192).
  Nothing in the output names which install prefix each scope came from.
- Sev: HOURS. Owner: PL (print resolved package prefixes), SAI.
  Tracked: UNTRACKED.

### 2.9 Known-true warnings cannot be acknowledged; infos ask to delete what is kept

- Hits: USER-WG.
- What: the two `reaction-unguarded` warnings are true and deliberately
  kept (CON:307-318), so CI can never be warning-free and a new warning
  looks like the old ones. The clean run also prints 8 `derivable-rate` /
  `derivable-min-rate` infos telling the author to delete declarations
  the island keeps (24 infos on 0.10.0, brief-C:1044-1046). There is no
  in-file "acknowledged, because ..." that the tool reads.
- Evidence: VERIFIED 2026-10-03 output; CON:307-318.
- Sev: COSMETIC to HOURS in CI adoption. Owner: PL/RLM. Tracked:
  UNTRACKED.

### 2.10 Bare-filename quirk (re-verify)

- What: on 0.10.0, `play_launch check safety_island.launch.xml` from
  inside the launch directory printed the cross-scope header and no
  cross-scope diagnostics; any path with a directory component worked.
- Evidence: DECK/brief-C-playlaunch-usage.md:52-56.
- Sev: HOURS when hit (a silently thinner check). Owner: PL. Tracked:
  UNTRACKED; not re-verified on 0.13.0.

--------------------------------------------------------------------------------

## 3. Building the image (nano-ros)

### 3.1 Tooling silently picks up another checkout

- Hits: DEV.
- What: nano-ros tools resolve `nros` from PATH; a fresh worktree without
  its own CLI falls back to the island's vendored, older one. On
  2026-09-24 this surfaced as a codegen version refusal, and "eight-plus
  units were told this was a known host red and pushed with
  NROS_SKIP_PREPUSH_CHECKS=1" (MEM/nano-ros-sibling-checkout-trap.md).
  The island fixed its side (scripts/env.sh:26-60: the submodule wins),
  but docs/demo-runbook.md:15 still names `../nano-ros` as the default,
  and ~/repos/nano-ros is at 2026-08-20.
- Evidence: memory note; NR #1253 (a Zephyr workspace compiles the module
  of whichever checkout provisioned it), #1254 (SDK provisioned inside the
  checkout), #1234 (a linked worktree writes into the parent's build dir),
  #1596 (one shared Zephyr workspace across worktrees), #1399 (no lock on
  the shared store build dir), #1373 (a fresh worktree fails two gates).
- Sev: HOURS (repeatedly). Owner: NR. Tracked: NR issues above (open);
  not in NR474.

### 3.2 Environment first: per-worktree setup and the bootstrap doctor

- Hits: DEV.
- What: "each missing piece surfaces as a DIFFERENT error at a different
  stage -- so fixing one just reveals the next and looks like a cascade of
  real bugs"; a worktree needs `just setup-cli` (about 80 s) and
  submodule init before any gate; unset `core.hooksPath` makes pre-push
  checks inert. None of this is enforced by the build entry point.
- Evidence: MEM/nano-ros-bootstrap-doctor-first.md;
  MEM/nano-ros-sibling-checkout-trap.md ("How to apply"); NR #1373.
- Sev: HOURS. Owner: NR. Tracked: NR #1373 (partly).

### 3.3 A value written in the wrong file is silently ignored

- Hits: DEV.
- What: three files hold configuration; Zephyr merges the nros-zenoh
  snippet after the board conf, so MAIN_STACK_SIZE, HEAP_MEM_POOL_SIZE and
  the NET_PKT/NET_BUF counts written in the board conf "are overwritten
  without warning". The heap is one knob with two decoys
  (HEAP_MEM_POOL_SIZE, COMMON_LIBC_MALLOC_ARENA_SIZE).
- Evidence: TRI:297-325 (section 5), TRI:177-190; NR #0934 ("The same fact
  is authored in up to five config surfaces"), #0941 (board facts fail
  soft).
- Sev: HOURS. Owner: NR. Tracked: NR #0934, #0941.

### 3.4 A stated knob silently beats the derivation

- Hits: DEV.
- What: "Stating a number here WINS." The board conf's
  `CONFIG_NROS_MAX_LIVELINESS=32` was right at 29 tokens and went 26 short
  the day `params:` was declared; liveliness exhaustion is not a boot
  failure, the entity just disappears from `ros2 node list` (TRI:242-251:
  "the one failure in this document that gives you nothing to grep
  for"). The rule "state board facts, never contract-derivable counts" is
  a convention in a comment (CONF:560-570), not a check.
- Evidence: DECK/OPEN-QUESTIONS.md:51-94; CONF:169-171, 560-570.
- Sev: HOURS (silent). Owner: NR. Tracked: partly by
  `check-knob-delivery`; NR #1490 (the forwarding check proves a knob is
  mentioned, not that it is a table row).

### 3.5 The heap is hand-set and three reports disagree

- Hits: DEV.
- What: the W1 QEMU report asks `>= 133,952 B` (P8:309-310); the board runs
  at configured 102,400 / capacity 102,912 with FirstSpin peak 77,160
  (TT section 11); a QEMU island behind the gateway exhausted 102,400 in
  `zpico_read` after FirstSpin and needed 1 MiB (P8:535-537). The headroom
  line judges the FirstSpin peak only, and does not say why capacity
  differs from the configured value.
- Evidence: P8:295-310, 525-538; NR474 I5 (lines 219-247); NR #1424 ("set
  by hand; the high-water reporter ... nothing reads it off a board").
- Sev: HOURS. Owner: NR. Tracked: NR474 I5, NR #1424.

### 3.6 Derived counts arrive without their arithmetic

- Hits: DEV.
- What: the current image's derived liveliness count is recorded as a bare
  25 (docs/boot-through.md:607, W8a); the only formula written down
  (CONF:563-567, 1 + 4 names + 14 pubs + 11 subs + 2 + 2 + 24 parameter
  services = 58) describes the earlier 4-node image with parameter
  services. `settle-derived` prints its arithmetic; the image derivation
  does not.
- Sev: COSMETIC to HOURS. Owner: NR (print the formula beside each
  derived knob), SAI (refresh the comment). Tracked: UNTRACKED. Cheap
  on the SAI side.

### 3.7 Refusals and failures that mislead or say nothing

- Hits: DEV.
- What, each from an open nano-ros issue or the island's docs:
  - the entity-inventory refusal tells you to add `ENTITIES`, which is
    retired and now a hard configure error (NR #1120);
  - the two runtime refusals emit through a sink that is a no-op on every
    freestanding target, so they "abort anonymously on an RTOS" (NR #1303);
  - heap exhaustion is a printk that returns NULL, and a C++
    BufferTooSmall returns RET_FULL with length 0; neither reaches the
    boot report on a consoleless board (NR #1425, #1036);
  - the board build refused its own image on
    `NROS_DERIVED_SUBSCRIBED_TYPE_BOUNDS` ("DERIVED but ... never reached
    the resolver") and `check-knob-delivery` was red on that line
    (docs/tracing.md:395-400; docs/nxp-deployment.md:1231-1238; NR #1252);
  - the refusal's advice, echoed inside double quotes with backticks,
    re-ran the board build recursively: 32 nested builds (fixed;
    docs/nxp-deployment.md:1238-1241).
- Sev: BLOCKS to HOURS. Owner: NR, SAI. Tracked: the NR issues named;
  UNTRACKED in NR474.

### 3.8 Contract edits do not invalidate the model

- What: adding a `<stem>.contract.yaml` does not invalidate the
  SystemModel it feeds; `nros sync` leaves the stale model.
- Evidence: NR #1121.
- Sev: HOURS. Owner: NR. Tracked: NR #1121.

### 3.9 A standing "no producer" on every sync

- What: `just sync` prints "no producer" for the source metadata of all
  four components (unbounded `header.frame_id` in the host probe), so a
  warning is printed every time and learnt as noise.
- Evidence: P8:576-577 (W26 Open); NR474 I4 (lines 205-217).
- Sev: COSMETIC. Owner: NR. Tracked: NR474 I4.

### 3.10 Scheduling derivation is inert, and the only signal is a stderr line

- What: the island declares no callback groups, so no tier, thread,
  priority or deadline is derived; all 19 callbacks share `main`. The
  only sign is a stderr line nothing retains.
- Evidence: NR #1371; docs/nxp-deployment.md:1256-1261; DECK/brief-B:609-614.
- Sev: COSMETIC today (no claim depends on it), structural.
  Owner: NR. Tracked: NR #1371.

### 3.11 Builds are slow and fragile on this host

- Hits: DEV.
- What: the first `just zephyr-build` recompiles every vendored interface
  crate at "roughly a minute each" (demo-runbook.md:73-76); stale
  `build-*` trees made one `nros image-facts` open 362,782 directories and
  sit in D state for 6+ minutes (MEM/stale-build-trees-poison-workspace-scans.md);
  /home is a spinning disk and build "low memory" kills are I/O, not RAM
  (MEM/build-kills-are-disk-not-memory.md); `nros setup native`
  source-builds zenohd (NR #0374).
- Sev: HOURS. Owner: SAI (host), NR. Tracked: P9 W17 (hygiene, caches off
  /home); NR #0374.

### 3.12 `nros-sdk.lock` is untracked in the island repo

- What: `?? nros-sdk.lock` (137 B, 2026-09-10, one tool: zephyr-sdk 0.16.8)
  sits untracked and not ignored. nano-ros design 0014 says the lock is
  "committed per project" and `nros store gc` reads locks back
  (changelog.d/1262.fix.md), so an uncommitted lock pins nothing for the
  next clone. Same `git status` shows `?? experiments/serial-interop/d8/`
  and a modified submodule.
- Evidence: VERIFIED 2026-10-03 (`git status --short`, `git ls-files
  --error-unmatch` fails); nano-ros docs/design/0014-nros-setup-toolchain-management.md:283.
- Sev: COSMETIC. Owner: SAI. Tracked: UNTRACKED. Cheap (commit or
  ignore, with a reason).

### 3.13 `image-facts` refused on the pristine tree (re-verify)

- What: `nros image-facts --for-entry zephyr_entry` was refused (no launch
  file in zephyr_entry), so it printed no knobs for any experiment.
- Evidence: DECK/brief-D-island-experiments.md:815-817.
- Sev: COSMETIC. Owner: NR. Tracked: UNTRACKED; not re-verified.

--------------------------------------------------------------------------------

## 4. Flashing, booting, bring-up

### 4.1 The board has no console; reading logs needs four unannounced steps

- Hits: DEV.
- What: lpuart0 (console) is not wired; lpuart2 carries the zenoh link. RTT
  needs the SEGGER module cloned by hand, `-DZEPHYR_EXTRA_MODULES`, `pyocd
  rtt` under `script` for a TTY, and the `_SEGGER_RTT` address, "none of
  which any error message mentions"; the default 1 KiB RTT buffer wraps
  before a post-hoc reader attaches.
- Evidence: TRI:108-128; TT:1136-1141.
- Sev: HOURS. Owner: SAI (board), NR. Tracked: UNTRACKED (NR474 D1 covers
  violations only, not logs).

### 4.2 Serial link defaults: RX ring at its edge, main thread priority unstated

- Hits: DEV.
- What: the 1 KiB RX ring overflowed while the busy-wait transmit starved
  the reader; zenoh-pico's read task exited on the first rejected message
  and the lease closed the session at 21 s. The island works around it by
  configuration: `CONFIG_MAIN_THREAD_PRIORITY=5` (Zephyr default 0 sits
  above every transport band, and nano-ros does not state it) and
  `CONFIG_NROS_ZENOH_SERIAL_RX_RING_BYTES=4096` (CONF:685-700). The issue
  files for 1533 and 1534 still read `status: open` although 1533's fix is
  pinned (NR474:279-297).
- Evidence: P8:311-325; docs/serial-link.md:21-35, 451-460, 490-500.
- Sev: BLOCKS (the stall) for anyone not copying the island's conf.
  Owner: NR. Tracked: NR474 T3; NR #1534, #0852.

### 4.3 A misleading symptom: the lease mismatch looked like a peer join

- What: zenoh-pico measures router silence against min(router lease, own
  lease) = 10 s while a stock router keepalives every 30 s; the CLOSE
  reaches the wire with the next byte the router sends, which is why a
  host peer's join looked like the trigger. Fixed by a 60 s default; the
  `min()` deviation is "an issue candidate, not filed".
- Evidence: NR474 T1 (lines 251-273); P8:502-504.
- Sev: HOURS (to find). Owner: NR / UP (zenoh-pico). Tracked: NR474 T1.

### 4.4 Join order and graph floods

- Hits: DEV, USER-BOOTH.
- What: unfiltered, the QEMU island died of heap exhaustion 2.3 s after
  joining a full Autoware graph, at 120 KiB and at 1 MiB; an ACL denying a
  little more than `liveliness_token` also killed it (L3R:478-488). Graph
  discovery is now derived off on serial images, but whether the gateway's
  liveliness ACL can be retired was never re-measured on the board
  (docs/serial-link.md:463-471; L3R:533-537). A late-joining island ran a
  150 ms EMERGENCY_STOP 80 ms after INIT -> RUN (P8:573-576).
- Sev: HOURS. Owner: SAI, NR. Tracked: late join P9 W12; the ACL
  re-measurement (phase-8 W10/W14 "Open") is UNTRACKED in P9.

### 4.5 Failures that do not announce themselves

- What: a silent hang on the boot path is stack exhaustion "until proven
  otherwise" (no guard page); `zephyr_code_relocate()` relocates nothing
  without the Zephyr patch, prints nothing and exits 0; liveliness
  exhaustion (3.4).
- Evidence: TRI:150-165, TRI:242-276.
- Sev: HOURS. Owner: NR / UP (Zephyr). Tracked: `just board-doctor`
  checks the relocation; the rest UNTRACKED.

### 4.6 Bring-up docs state things that are no longer true

- Hits: DEV, newcomers.
- What:
  - TRI:339-341 "Nothing in this image has executed on silicon" and
    TRI:183 heap "94208"; TRI:245 liveliness "32 against 29 tokens";
  - docs/nxp-deployment.md:1247-1250 "94208 was chosen without a
    measurement" and :1252 "Never executed on silicon. The board is
    blocked on the MCU-Link probe" (13 + 9 board acts have run since);
  - L3R:529-532 lists G5 ("announces but does not brake") as open, closed
    by W24; demo-runbook.md:228-229 repeats it;
  - demo-runbook.md:1-7 says the end-to-end run "has NOT been re-validated"
    since 2026-07-31; demo-runbook.md:15 names `../nano-ros` as the default
    checkout.
- Sev: HOURS (a newcomer follows the wrong page). Owner: SAI.
  Tracked: UNTRACKED. Cheap.

--------------------------------------------------------------------------------

## 5. Running and observing

### 5.1 Runtime violations are invisible on the board

- Hits: DEV, USER-WG.
- What: the monitor logs to the unwired console; nothing drains the
  executor's violation ring; no trace marker records a violation. "No
  runtime violation was seen: the console (lpuart0) is unwired, and the
  executor's never-drained violation ring was full (8 start-up entries)
  by bring-up." The evidence that no monitor would have fired was made
  offline from the trace, around nano-ros. "A contract monitor whose
  verdict cannot leave the board is not yet a safety measurement."
- Evidence: P8:615-622 (W31); TT:1134-1169; NR474:25-43, D1 (52-84).
- Sev: BLOCKS (the runtime half of the contract claim). Owner: NR, SAI.
  Tracked: NR474 D1, I1, T4; P9 W4.

### 5.2 The ring keeps the first 8 and the monitors are armed before RUN

- What: `MAX_VIOLATIONS` = 8, keep-first, `violations_dropped()` read by
  nothing; the 8 slots were all start-up entries (4 timer-overrun, 1
  release-jitter 57,751 us vs 10,000, 1 silence, 2 rate-hierarchy on
  on-demand topics). The island's own INIT/RUN state machine already marks
  the end of start-up.
- Evidence: NR474 D1 (54-64), D2 (86-116); TT:1142-1151.
- Sev: BLOCKS (with 5.1). Owner: NR. Tracked: NR474 D2, I2; P9 W4, W7.

### 5.3 The runtime monitor checks a callback; the contract budgets a route

- What: `max-latency-runtime` bounds one dispatch (longest 24.93 ms) while
  `call_mrm` 206 ms is link + tick wait + work; "a 206 ms route made of a
  slow link and a full tick wait passes a callback-level check with 180 ms
  to spare." The static and runtime halves state different quantities.
- Evidence: NR474 D3 (118-136); PL85 D4 (82-86); TT:1161-1166.
- Sev: HOURS, structural. Owner: NR, PL. Tracked: NR474 D3, PL85 D4.

### 5.4 No board time source: hazard lights and the clock merge

- Hits: DEV, USER-BOOTH.
- What: the board stamps from boot (no SNTP over serial). Its hazard
  command carries a boot-relative stamp, so the simulator never shows
  ENABLE from the board (TT:713-718), although native_sim with SNTP shows
  it 38-167 ms later (P8:570-572). The merge's two anchors disagree
  13.05-47.62 ms over serial (TT:699-703); cross-clock rows are upper
  bounds (TT:804-826). native_sim needs `scripts/sntp-server.py` beside
  every zephyr.exe launch (P8:565-567).
- Sev: HOURS; visible at the booth. Owner: SAI, NR. Tracked: P9 W3, W9;
  NR #0758 (no platform wall-clock epoch source).

### 5.5 The trace trigger fires once per boot

- What: a second act needs a reset; a pre-act availability flap can fire
  the trigger early (P8:535-539; docs/tracing.md:601-602).
- Sev: BLOCKS for back-to-back acts. Owner: SAI. Tracked: P9 W2.

### 5.6 Instruments that read zero or are not there

- What: `island_trace_cost_max` read 0 in two runs (P8:410-411); no
  per-sample take marker for kinematic_state, operation_mode_state and
  control_cmd, and the 30 Hz tick kept one in ten, so those hops are
  unmeasured (TT:937-940).
- Sev: COSMETIC to HOURS. Owner: SAI, NR. Tracked: NR474 T2, I3; P9 W13.

### 5.7 native_sim warnings that are not evidence

- What: native_sim's simulated clock sprints after boot work and gave a
  false MRM at start (fixed by `sim_clock_catch_up.c`, native_sim only);
  the `silence-runtime .../operation_mode_availability` warning "still
  appears once, 500 ms after the first spin, in every native_sim run and
  in all five of W23's QEMU runs", "not evidence of a gap". Readers must
  be told to ignore it.
- Evidence: TT:470-541.
- Sev: COSMETIC (noise that trains people to ignore warnings).
  Owner: NR (arming, see 5.2). Tracked: indirectly NR474 D2.

### 5.8 Results depend on host load; runs need a lock and a load ceiling

- Hits: DEV, USER-BOOTH.
- What: every board run was started under a flock at a 1-min load below
  35 (TT section 9); a QEMU guest spin stall of 578 ms under host load gave
  a false MRM (P8:518-522); A and B failed on host gate gaps of 1,600 /
  1,901 ms at load 20-31 (P8:496-498); the planner dropped the comfortable
  stop availability under load (P8:452-455).
- Sev: HOURS. Owner: SAI. Tracked: P9 W15.

### 5.9 Link bad frames, cause unknown

- What: about one in-run bad frame per 80 min with no UART error and no
  ring overflow (docs/serial-link.md:472-474).
- Sev: COSMETIC today. Owner: SAI/NR. Tracked: P9 W16.

--------------------------------------------------------------------------------

## 6. Demo and booth

### 6.1 No visitor UI: the acts are presenter-run shell scripts

- Hits: USER-BOOTH.
- What: "today an act is a `tools/timeline/run-board.sh` invocation by the
  presenter, and the plot is rendered from the run directory afterwards";
  the proposal promises that visitors trigger each act.
- Evidence: P9:40-49 (W1), P9:133-137 (W11).
- Sev: BLOCKS (the proposal's promise). Owner: SAI. Tracked: P9 W1, W11.

### 6.2 Every act reflashes, resets, and restarts Autoware

- What: run-board.sh flashes (pyocd), starts the router and gateway,
  resets the board, waits for the island, starts the container, the gate,
  the probe and the act, then reads the trace over SWD (core halted
  0.18-0.23 s) (tools/timeline/run-board.sh:19-31; docs/tracing.md:596-599).
  No reset-between-acts sequence exists, and what the visitor sees while
  the board resets is undesigned.
- Sev: BLOCKS for a booth cadence. Owner: SAI. Tracked: P9 W1, W2.

### 6.3 The manual path is six terminals and an order to remember

- What: l3-router, l3-autoware, l3-takeover, l3-peer ("then reset the
  board"), l3-run, l3-rviz; "the island joins BEFORE Autoware is engaged";
  on a stuck start "Ctrl-C it, wait 10 s (the zenoh lease) and start it
  again" (L3R:14-41). The justfile tree has about 77 recipes (justfile 36
  + emulation 6 + tracing 11 + board-peer 2 + l3-demo 18, plus setup
  recipes), with the Cyclone-era demo (`just autoware/island/demo`,
  domain 10) beside the zenoh `l3-*` path (demo-runbook.md:90-107 vs
  191-215).
- Sev: HOURS for a presenter. Owner: SAI. Tracked: partly P9 W1.

### 6.4 A bad Autoware start is not refused

- What: one act-A attempt came up at 66/68 composables (`"ok":false`);
  run-board.sh still saw "Startup complete" and ran until "FATAL: the
  vehicle did not reach 1.0 m/s" (run-board.sh:211-212 greps only
  "Startup complete").
- Evidence: P9:118-122 (W8); P8:618-619.
- Sev: HOURS (a void run). Owner: SAI. Tracked: P9 W8. Cheap.

### 6.5 Host stack flakes fixed only in the image

- What: three hangs that looked like one: rmw_zenoh_cpp 0.1.9 losing
  wakeups in `rmw_wait` (ros2/rmw_zenoh#1032), rclcpp Humble freeing a
  guard condition under the waiter (ros2/rclcpp#2445), zenoh 1.8.0 gossip
  deadlock with one Net worker (eclipse-zenoh/zenoh#2581). Starts went
  from 3 of 10 to 40 of 40 with a ROS apt testing source, a 60-line rclcpp
  patch and `ZENOH_RUNTIME`; "the host path keeps all three".
- Evidence: P8:459-477 (W11); L3R:415-477, 543-547.
- Sev: HOURS (each start flake reads as your bug). Owner: UP, SAI.
  Tracked: P9 W17 (drop the patches when apt ships).

### 6.6 The host gate stalled on disk I/O, and RT needs host setup

- What: the rclpy availability gate went silent 582-1134 ms, "its executor
  thread blocked in the kernel on file writes", and the island rightly
  escalated, so branch B FAILed for a host reason (TT:334-346). The C++
  replacement wants SCHED_FIFO through `gate-rt`, which needs a limits.d
  rtprio entry (`ulimit -r` is 0 for this user) and the container needs
  `--cap-add SYS_NICE --ulimit rtprio=20 --ulimit memlock=-1`
  (P8:440-456, 545-547). The demo compositions still model the gate as
  input-triggered at 20 ms (P8:556-558).
- Sev: HOURS. Owner: SAI. Tracked: P9 W6 (compositions), P9 W15 (load);
  the rtprio host setup is UNTRACKED.

### 6.7 The demo lock is an agent sandbox path and only a comment

- What: run-board.sh:38-39 and TT section 9 tell the operator to run
  under `flock /tmp/claude-1000005/sai-demo.lock`; the script does not take
  the lock itself, and that path exists only in this machine's agent
  sandbox. A booth machine (the Orin) will not have it.
- Evidence: tools/timeline/run-board.sh:38-39; TT:432, 565, 958.
- Sev: COSMETIC to HOURS (two concurrent acts corrupt each other).
  Owner: SAI. Tracked: UNTRACKED. Cheap.

### 6.8 What the visitor cannot see

- What: hazard lights never show from the board (5.4); a violation could
  not be shown (5.1); the plot comes after the act (6.1).
- Sev: BLOCKS for the "every number the demo shows is one the board can
  report" goal (P9:3-6). Tracked: P9 W3, W4, W9, W11.

### 6.9 The booth machine is not built for yet

- What: the booth host is an Orin; the `sai-l3-autoware` image (5.29 GB,
  cold build about 7.7 min on amd64) has not been built for arm64.
- Evidence: P9:128-132 (W10); P8:331-335.
- Sev: BLOCKS for the booth. Owner: SAI. Tracked: P9 W10.

### 6.10 Small host traps a presenter will meet

- What: `:1` is a user's desktop, not the demo's VNC, and `just doctor`
  does not check that an X server listens (L3R:523-524;
  demo-runbook.md:153-155); `ros2 topic echo` without `--no-daemon`
  answers for the wrong RMW (L3R:511-514); `/opt/autoware/1.5.0/setup.bash`
  itself exports the Cyclone RMW (L3R:507-510); a shared DDS domain makes
  every host node die with "rcl node's rmw handle is invalid", which
  "reads as a bug in whatever you changed last" (demo-runbook.md:156-167).
- Sev: COSMETIC to HOURS. Owner: SAI. Tracked: UNTRACKED.

--------------------------------------------------------------------------------

## 7. Repository and infrastructure hygiene

### 7.1 The disk, not memory

- What: /home is a WDC spinning disk; builds fill page cache and Claude
  Code's memory-pressure reaper SIGTERMs background builds while 38 GB is
  available. `~/.nros`, `~/.cargo`, `~/.cache/zephyr` and the repo all sit
  on it.
- Evidence: MEM/build-kills-are-disk-not-memory.md.
- Sev: HOURS. Owner: host. Tracked: P9 W17 ("caches and worktrees off
  /home"); approved move pending (MEM index).

### 7.2 Stale build trees and worktrees

- What: 19 `build-*` dirs in the island today (85 at the 2026-09-12 peak,
  which made workspace scans open 362k directories); 179 entries under
  /mnt/mx500/aeon/worktrees. Only `build`, `build-board`, `build-zephyr`
  are live.
- Evidence: VERIFIED 2026-10-03 (counts); P9:170-176;
  MEM/stale-build-trees-poison-workspace-scans.md; NR #1565 (`find .`
  walks into worktrees).
- Sev: HOURS. Owner: SAI, NR. Tracked: P9 W17.

### 7.3 Kill switches that hit bystanders

- What: `just demo-down` swept processes by `CYCLONEDDS_URI`, which
  .envrc exports into every direnv shell, and SIGKILLed Claude Code
  twice (fixed eb82dcf with an SAI_DEMO_RUN marker); `pkill -f` kills the
  shell running it (L3R:521-522); a name-based `pkill -f play_launch` hits
  every project on the box (demo-runbook.md:168-173).
- Evidence: MEM/demo-down-kills-claude.md.
- Sev: HOURS (looked like OOM). Owner: SAI. Tracked: fixed; no regression
  test.

### 7.4 Environment shadowing

- What: host_ws shadows stock tier4_system_launch (2.8); the Autoware
  setup scripts hard-set Cyclone (L3R:507-510; P8:96-99). The remedy is a
  convention: run under `env -i`.
- Sev: HOURS. Owner: SAI. Tracked: UNTRACKED.

### 7.5 Issue status drift across trees

- What: nano-ros issue files 1533/1534 read open while their fixes are
  pinned (NR474:279-297); "A phase's claims go stale when ANOTHER phase does
  the work" (NR #1489); the default ~/repos/nano-ros checkout is six weeks
  behind (see the source note). Readers cannot trust an issue's status
  without checking the pin.
- Sev: COSMETIC. Owner: NR. Tracked: NR474 T3, NR #1489.

--------------------------------------------------------------------------------

## 8. Top 10, ranked by severity x how often it is hit

1. **Runtime violations invisible on the board; ring keeps first 8 and fills
   at start-up** (5.1, 5.2). BLOCKS the runtime claim, every board run.
   NR. Tracked NR474 D1/D2/I1/I2/T4, P9 W4.
2. **play_launch version skew with a message that does not name the
   version** (2.1, 2.2, 2.3). BLOCKS any fresh shell today; the doctor
   accepts 0.8.2, two "0.12.0" binaries disagree. SAI/PL/RLM. UNTRACKED.
3. **Declaration vs code never cross-checked** (1.6). An omitted endpoint
   reaches the board as an opaque failure; cost days once. NR/PL.
   UNTRACKED.
4. **Booth: no visitor UI, reflash + Autoware restart per act, trigger once
   per boot** (6.1, 6.2, 5.5). BLOCKS the proposal's promise. SAI.
   Tracked P9 W1/W2/W11.
5. **Wrong-checkout and per-worktree environment traps** (3.1, 3.2).
   HOURS, every new worktree; led to pushes with checks skipped. NR.
   NR issues 1253/1254/1234/1596/1373; not in NR474.
6. **Budgets with no keys: composite `call_mrm`, `max_transport` silently
   not charged, budget = deadline = monitor** (1.2, 1.3, 1.4, 5.3). HOURS on
   every budget change. RLM/PL/NR. Tracked PL85 D1/D2/D4/I1, NR474 D3/D4.
7. **No board time source** (5.4, 6.8). Hazard lights never shown from the
   board; every cross-clock row an upper bound. SAI/NR. Tracked P9 W3/W9,
   NR #0758.
8. **CI negative tests by exit code only** (2.4). Every CI run; a parse
   failure satisfies an expected rule failure. SAI. UNTRACKED.
9. **Hand-set heap and stated knobs that silently beat derivation**
   (3.4, 3.5, 3.6). HOURS per image change; liveliness exhaustion is
   invisible. NR. Tracked NR474 I5, NR #1424/#1490.
10. **Host-side flakiness read as island faults: start flake, gate stall,
    load** (6.5, 6.6, 5.8). HOURS per occurrence; voids acts. UP/SAI.
    Tracked P9 W15/W17; rtprio setup untracked.

Honourable mentions: stale bring-up docs (4.6), `--export-graph` missing
services/hazards (2.7), environment-dependent verdicts (2.8), console-less
board logging (4.1).

## 9. Cheap (< 1 day) versus structural

Cheap, each one change in one repository:

- SAI: raise `PLAY_LAUNCH_MIN` to 0.13.0 in justfile:73, .envrc:14 and
  scripts/env.sh:21 (2.1).
- SAI: make check-contracts.sh match the expected rule id per EXPECT row
  (or use `--format json`) (2.4).
- SAI: run-board.sh refuses `"ok":false` (6.4, P9 W8).
- SAI: run-board.sh takes its own lock at a repo-relative or $XDG path
  (6.7).
- SAI: refresh TRI sections 3/6/7, nxp-deployment section 10, L3R "Open",
  demo-runbook header and line 15 (4.6).
- SAI: drop `min_rate_hz` on the two on-demand topics until the key exists
  (1.5, P9 W7 option 2).
- SAI: commit or ignore nros-sdk.lock with a reason (3.12); refresh the
  liveliness formula comment in CONF (3.6).
- PL: put the git describe / rlm tag in `--version` (2.2).
- PL: `--color never` when stdout is not a TTY, ASCII-only option, print a
  parse failure once (2.5); document the hazard table under `--explain`
  (2.6).
- PL: a notice when `max_transport` is declared but not charged (1.3).
- RLM: refuse `/` in an endpoint key (1.7); better nearest-key suggestion
  (1.10).
- NR: ring keeps the latest 8 and reports `violations_dropped()` (part of
  NR474 I1); fix the ENTITIES advice in the refusal (NR #1120).

Structural (design decisions, cross-repo, or upstream):

- A violation channel off a console-less board, and monitor arming
  (NR474 D1/D2, P9 W4).
- A route-level runtime check that states the same quantity as the static
  walk (NR474 D3, PL85 D4).
- New grammar: transport on the walk, timer jitter, service-edge cost,
  on-demand topics, budget vs deadline (PL85 D1-D3/I1, NR474 D4).
- Code-vs-contract endpoint cross-check (1.6).
- A minimum tool / grammar version in the contract (2.1).
- `--export-graph` that carries services, externals, hazards and triggers
  (2.7; probably a day or two, not a design question).
- A board time source over serial (P9 W3) and hazard lights from the board
  (P9 W9).
- The booth UI with re-arm and per-act reset (P9 W1/W2/W11), the Orin
  image (P9 W10).
- A heap derived to cover the read path after FirstSpin (NR474 I5).
- Worktree/store isolation in nano-ros (NR #1253/#1254/#1234/#1596/#1399).
- Criticality decomposition (`bounded_by:`) with the WG (1.9).
- Upstream fixes for the host stack (rmw_zenoh 0.1.10 on apt, rclcpp#2445,
  zenoh#2581) (6.5).
