# phase7-W1 -- tracing recipes (docs/tracing.md). Imported by the last line of
# the main justfile. The image side is the tracing block in
# src/native_sim_entry/prj.conf and at the end of
# src/zephyr_entry/boards/mr_canhubk3_s32k344.conf; the marker ids are
# generated from the contract into src/safety_island_tracing/include/.

TRACE_DIR := "build/trace"
TRACE_PY := "src/safety_island_tracing/island_trace.py"
TRACE_GEN := "src/safety_island_tracing/gen_markers.py"

# Regenerate the marker header + table from the resolved model (after `just sync`).
trace-gen:
    python3 {{TRACE_GEN}} gen
    python3 {{TRACE_GEN}} sites > /dev/null && echo "trace-gen: every marker has a call site"

# Fail if the committed marker header/table is stale or a marker has no call site.
trace-gen-check:
    python3 {{TRACE_GEN}} check
    python3 {{TRACE_GEN}} sites > /dev/null && echo "trace-gen-check: every marker has a call site"

# The island joins the demo domain exactly as `just island` does (scripts/env.sh,
# the same zephyr.exe), so run `just autoware` and `just demo` beside it for the
# demo's island half, or use `just trace-demo`, which does all three. The image
# writes the RAM buffer at exit (--stop_at, SIGTERM or Ctrl-C) to <out>; <out>.meta
# records what the buffer cannot hold about itself: the image's sha256 and the
# source revision.
#
# Run the native_sim island for a bounded time (host seconds) and dump its trace.
trace-native secs="120" out=(TRACE_DIR / "island.trace"): (_not-running "demo/.island.pgid" "island") (_island-image-check "zephyr")
    #!/usr/bin/env bash
    source scripts/env.sh
    set -e
    mkdir -p "$(dirname "{{out}}")"
    : > "{{out}}"   # the image opens an existing file (see island_trace.h)
    just _trace-meta "{{out}}" build-zephyr/zephyr/zephyr.exe
    ps -o pgid= -p $$ | tr -d ' ' > demo/.island.pgid
    echo "trace-native: island for {{secs}} s -> {{out}} (log {{out}}.log)"
    set +e
    ./build-zephyr/zephyr/zephyr.exe --stop_at={{secs}} --trace-out="$PWD/{{out}}" > "{{out}}.log" 2>&1
    rc=$?
    rm -f demo/.island.pgid
    grep -a 'island_trace:' "{{out}}.log" || true
    [ -s "{{out}}" ] || { echo "trace-native: no trace written (exit $rc; is tracing in the image? see {{out}}.log)"; exit 1; }
    echo "trace-native: $(stat -c %s "{{out}}") B in {{out}} (island exit $rc)"

# Autoware + a TRACED island + the demo sequence; prints the VERDICT, then checks the trace.
trace-demo out=(TRACE_DIR / "demo.trace"): (_not-running "demo/.sim.pgid" "sim") (_not-running "demo/.island.pgid" "island") _sim-prereq-check (_island-image-check "zephyr")
    #!/usr/bin/env bash
    rm -f tmp_sim.log tmp_island.log
    mkdir -p "$(dirname "{{out}}")"
    : > "{{out}}"
    just _trace-meta "{{out}}" build-zephyr/zephyr/zephyr.exe
    parallel --lb --halt now,done=1 --termseq {{TERMSEQ}} ::: \
        "just _svc-sim" \
        "just _job-traced-island '$PWD/{{out}}'" \
        "just demo"
    rc=$?
    # the island dumps on SIGTERM; give the exit hook a moment to land
    for _ in 1 2 3 4 5; do pgrep -f 'build-zephyr/zephyr/zephyr.exe' >/dev/null || break; sleep 1; done
    echo "== demo exit $rc; island trace: $(stat -c %s "{{out}}" 2>/dev/null || echo 0) B in {{out}}"
    grep -a 'island_trace:' tmp_island.log || true
    python3 {{TRACE_PY}} check "{{out}}"
    trc=$?
    exit $(( rc != 0 ? rc : trc ))

[private]
_job-traced-island out:
    #!/usr/bin/env bash
    set -e
    just _wait-sim > /dev/null
    source scripts/env.sh
    ps -o pgid= -p $$ | tr -d ' ' > demo/.island.pgid
    exec ./build-zephyr/zephyr/zephyr.exe --trace-out="{{out}}" > tmp_island.log 2>&1

[private]
_trace-meta out image:
    #!/usr/bin/env bash
    {
      echo "image={{image}}"
      echo "image_sha256=$(sha256sum "{{image}}" | cut -d' ' -f1)"
      echo "git_rev=$(git rev-parse HEAD)$(git diff --quiet --ignore-submodules HEAD -- src just 2>/dev/null || echo -dirty)"
      echo "captured=$(date -u +%Y-%m-%dT%H:%M:%SZ)"
    } > "{{out}}.meta"

# Decode a trace: event counts and bytes, the provenance, a marker timeline, a Perfetto JSON.
trace-decode file zephyr="":
    python3 {{TRACE_PY}} decode "{{file}}" {{ if zephyr != "" { "--zephyr " + zephyr } else { "" } }} --timeline 60 --perfetto "{{file}}.perfetto.json"

# Check a trace: every marker seen, heartbeat sequence contiguous, buffer not filled early.
trace-check file zephyr="":
    python3 {{TRACE_PY}} check "{{file}}" {{ if zephyr != "" { "--zephyr " + zephyr } else { "" } }}

# phase8-W17: the trace window (docs/tracing.md section 8) on native_sim, for
# verification. EXTRA_CONF_FILE adds src/native_sim_entry/trace-window.conf to
# the build in build-zephyr; zephyr_get() caches the value, so a later plain
# `just zephyr-build` keeps it until `west build -p -d build-zephyr`.
#
# Build the native_sim island with the board's trace window (build-zephyr).
trace-window-native-build:
    EXTRA_CONF_FILE="$PWD/src/native_sim_entry/trace-window.conf" just zephyr-build

# phase8-W17: the QEMU island with the board's tracing block and window, into
# build-qemu-trace (src/qemu_entry/trace.conf). Its buffer is read over the
# QEMU monitor (tools/timeline/readout.py --target qemu); one traced act:
#   tools/timeline/run-board.sh --target qemu --elf build-qemu-trace/zephyr/zephyr.elf b <id>
# The heap is 1 MiB, through qemu-build's triage lever (W3's precedent): at
# the stated 102,400 B the QEMU island died of HEAP EXHAUSTED in zpico_read
# when Autoware joined, over a TCP link that nothing paces (docs/tracing.md
# section 8). Not a board fact.
#
# Build the QEMU island with the board's tracing block and window (build-qemu-trace).
trace-qemu-build:
    EXTRA_CONF_FILE="$PWD/src/qemu_entry/trace.conf" CONFIG_NROS_ZEPHYR_HEAP_SIZE=1048576 just --set QEMU_BUILD_DIR build-qemu-trace qemu-build

# phase8-W17: the read goes through tools/timeline/readout.py: every address
# from the ELF symbol table, the core halted for the read (buffer and
# counters are one instant) and resumed, the heartbeat counter and the trace
# window's counters beside the buffer, and the buffer wrapped in the
# native_sim dump's header so `trace-check` can tell a full buffer from a
# short act. NOT EXERCISED: no board was touched in W17 (W10 held it); the
# same readout runs against QEMU (`readout.py --target qemu`).
#
# Board: read `ram_tracing` over SWD (MCU-Link + pyocd) from a flashed, running image.
trace-board out=(TRACE_DIR / "board.trace") elf=(BOARD_BUILD_DIR / "zephyr/zephyr.elf"):
    #!/usr/bin/env bash
    set -e
    [ -f "{{elf}}" ] || { echo "trace-board: no {{elf}} -- just board-build"; exit 1; }
    mkdir -p "$(dirname "{{out}}")"
    just _trace-meta "{{out}}" "{{elf}}"
    python3 tools/timeline/readout.py --target board --elf "{{elf}}" --out "{{out}}"
    python3 {{TRACE_PY}} check "{{out}}"
