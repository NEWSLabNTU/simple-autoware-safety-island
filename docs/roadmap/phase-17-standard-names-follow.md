# Phase 17 - follow the standard-names renames (rlm v0.3.6 to v0.3.8)

**Goal:** the island's contract, CI and board tools keep passing as
play_launch retires the names that phase 98 replaced with the standards'
words, and they move to the new names while the old ones are still read,
not after they are refused.

**Status (2026-11-04): S1-S5 done for rlm v0.3.8.** The island pins
play_launch 0.25.0 (CI `PLAY_LAUNCH_VERSION`, the justfile's
`PLAY_LAUNCH_MIN`), the release carrying rlm v0.3.8, and nano-ros at the
merge of its phase-534 W1 pull request. The model's schema 4 (nano-ros
phase-534 W3) is still to come; S3 already reads it.

Design of record: rlm's
[`docs/design/standard-names.md`](https://github.com/NEWSLabNTU/ros-launch-manifest/blob/v0.3.8/docs/design/standard-names.md),
section 6 for the release schedule. Each rename goes through three
releases:

- **R:** the new name is in, and the old one is read with a
  `deprecated-spelling` warning.
- **R+1:** the old name is a parse error naming the new one.
- **R+2:** the old name is gone from every message.

`play_launch migrate` rewrites old keys and `acknowledged:` rule ids
throughout. It prints a diff, and `--write` applies it.

## What changes, and what it does to the island

### Refused (rlm v0.3.6)

`severity_levels:`, a hazard's `severity:`, a mode's `window:` and a
profile's `severity_scale:` are parse errors. An old rule id in
`acknowledged:` is `error[ack-renamed]`. **No effect here:** the contract
already uses `integrity`/`min_dwell` (commit "the phase-98 spellings"),
and `acknowledged:` names only `reaction-unguarded`, which did not move.

### Renamed, old spelling still read (rlm v0.3.7, contract keys)

| Old | New |
|---|---|
| `hazards.<h>.guards` | `hazards.<h>.monitors` |
| `sub.<e>.ingress` | `sub.<e>.arrival_curve` |
| `on_demand: true`, `trigger: spontaneous` | `aperiodic: true`, `trigger: aperiodic` |
| platform file `mapper:` | `priority_assignment:` |

The island uses one of them: `safety_island.contract.yaml` lines 582 and
593, `guards: [/system/operation_mode/availability]`. Under the next
play_launch release that is one `warning[deprecated-spelling]` per hazard.
CI stays green: `check --strict` promotes only `worst-case-unknown`, and
`.github/check-contracts.sh` fails on errors, not warnings. At R+1 it is a
parse error, and every island contract check fails with
`error[manifest-parse]`.

### Renamed, old id still matched (rlm v0.3.8, rule ids)

| Old | New |
|---|---|
| `fault-reaction-budget` | `fault-reaction-time` |
| `degradation-level-budget` (and `ladder-rung-budget`) | `degradation-level-time` |
| `budget-overflow` | `latency-bound-overflow` |

"Budget" now means only a reservation's CPU time. The island's
`acknowledged:` uses none of these ids. They appear in:

- `tools/board/testdata/explain.txt` lines 10 and 12
  (`info[fault-reaction-budget]`). This is a captured `--explain` output
  for `tlcommon.py selftest`. `parse_explain` does not read the rule id,
  so the selftest still passes. Recapture the file when the pin moves, so
  it matches what the pinned binary prints.
- `safety_island_bringup/launch/safety_island.contract.yaml` line 387, a
  comment naming `ladder-rung-budget`.
- Phase 10 and 11 docs. These are history and keep the words of their
  time.

### Not moved yet: the MODEL's field names

The SystemModel still writes `hazards[].guards`, `ingress` and
`on_demand`, because nano-ros reads them. They move at model schema 4,
together with a nano-ros PR (nano-ros phase-534 W3). rlm keeps reading a
schema-3 model. A schema-4 model written by a newer play_launch, though,
names `monitors`. The island has two readers of the model's `guards`:

- `src/safety_island_tracing/gen_markers.py:367`: `hz.get("guards", [])`.
- `tools/board/tlcommon.py:203`: `guards=hz.get("guards", [])`.

### A heading the board tools match

`parse_explain` starts at a line beginning `-- Fault-reaction budgets`.
That heading is unchanged on play_launch `main`. Under M3's rule
("budget" is CPU time), though, it is a candidate for a later rename to
"times". A prefix match on `-- Fault-reaction` would survive that.

## Work items

**S1 - contract keys.** Rewrite `guards:` to `monitors:` in
`safety_island.contract.yaml` (`play_launch migrate --write`, or by hand).
Fix the line-387 comment to `degradation-level-time`. Do this in the same
commit that moves the pin to the first play_launch release carrying rlm
v0.3.7 or later. The current pin (0.24.2, rlm v0.3.5) does not know
`monitors:` and would refuse it.
*Acceptance:* `.github/check-contracts.sh` passes on the new pin with no
`warning[deprecated-spelling]` in its output.

**S2 - recapture `explain.txt`.** Recapture it from the new pin, and
loosen `parse_explain`'s heading match to `-- Fault-reaction`.
*Acceptance:* `tlcommon.py selftest` passes on the recaptured file and on
the old one.

**S3 - schema-4 readiness.** `gen_markers.py` and `tlcommon.py` read
`hz.get("monitors", hz.get("guards", []))`, the same shape `tlcommon.py`
already uses for `integrity`/`severity`.
*Acceptance:* both read a model whose hazards carry `monitors:`. This can
land before schema 4 exists.

**S4 - docs.** Update the active docs to the new words:

- `docs/tracing.md:475` (a hazard's `guards:`).
- `gen_markers.py:31`'s comment.
- `docs/nxp-deployment.md:971` (`mapper: rate_monotonic`, now
  `priority_assignment:`).

Roadmap history stays as written.

**S5 - the nano-ros pin.** When nano-ros merges its bump to rlm v0.3.8
(nano-ros phase-534 W1), and later schema 4 (W3), the island's nano-ros
pin follows, as it did for play_launch 0.24.2.

Order: S3 and S4 can land now. S1 and S2 wait for the play_launch release
and move with the pin. All of S1 must land before the island bumps to a
play_launch carrying rlm's R+1 release.

## Progress

- **S1** (2026-11-04): `play_launch migrate --write` rewrote both
  hazards' `guards:` to `monitors:`; the line-387 comment says
  `degradation-level-time`. On 0.25.0 `check-contracts.sh` passes with no
  `deprecated-spelling` warning: 0 errors, 6 warnings, 2 acknowledged, as
  on 0.24.2. The `--explain` output differs from 0.24.2's only in
  `fault-reaction-budget` printed as `fault-reaction-time` and the
  `reaction-unguarded` message naming `monitors:`; every total is the
  same.
- **S2**: `parse_explain` matches the heading by `-- Fault-reaction`.
  `testdata/explain.txt` is NOT recaptured: the tools do not read the rule
  id, so the old capture still checks the parser, and a capture of today's
  contract has 14 table rows (the selftest wants 10) and settle-derived
  lines in the profile form (`settle = ... derived by vehicle.braking`),
  which the evaluation's `analysis.py` settle-profile regex (the `rung
  '<x>': settle from ...` form) does not read. Recapturing it is a change
  to both selftests and to that regex, not a rename, so it is its own item.
- **S3**: `tlcommon.py` (which reads the CONTRACT's hazards) and
  `gen_markers.py` (the model's) read `monitors`, falling back to `guards`.
- **S4**: `docs/tracing.md`, `gen_markers.py`'s comment and
  `docs/nxp-deployment.md` say the new words.
- **S5**: third-party/nano-ros at `c975001f9b`, nano-ros phase 534 W1 (rlm v0.3.8,
  play_launch 0.25.0).
