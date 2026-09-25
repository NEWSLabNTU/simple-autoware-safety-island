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

# NOT EXERCISED in phase7-W1 -- no board had been flashed. The address and length
# come from the ELF symbol, never a literal; the buffer is one-shot from boot, so
# read it after the window you care about. `island_trace_hb_seq` (the heartbeat
# counter) is read too, which is what tells a full buffer from a short run.
#
# Board: read `ram_tracing` over SWD (MCU-Link + pyocd) from a flashed, running image.
trace-board out=(TRACE_DIR / "board.bin"):
    #!/usr/bin/env bash
    set -e
    source scripts/board-env.sh "{{NANO_ROS_ROOT}}"
    elf="{{BOARD_BUILD_DIR}}/zephyr/zephyr.elf"
    [ -f "$elf" ] || { echo "trace-board: no $elf -- just board-build"; exit 1; }
    # SDK 1.0 keeps the toolchain under gnu/; older SDKs at the top level.
    nm="$ZEPHYR_SDK_INSTALL_DIR/gnu/arm-zephyr-eabi/bin/arm-zephyr-eabi-nm"
    [ -x "$nm" ] || nm="$ZEPHYR_SDK_INSTALL_DIR/arm-zephyr-eabi/bin/arm-zephyr-eabi-nm"
    [ -x "$nm" ] || { echo "trace-board: no arm-zephyr-eabi-nm under $ZEPHYR_SDK_INSTALL_DIR"; exit 1; }
    read -r addr len _ < <("$nm" -S "$elf" | awk '$4=="ram_tracing"{print $1, $2}')
    read -r hbaddr _ < <("$nm" -S "$elf" | awk '$4=="island_trace_hb_seq"{print $1}')
    [ -n "$addr" ] || { echo "trace-board: $elf has no ram_tracing (tracing not in this image)"; exit 1; }
    mkdir -p "$(dirname "{{out}}")"
    echo "trace-board: ram_tracing @0x$addr, 0x$len bytes; heartbeat counter @0x$hbaddr"
    just _trace-meta "{{out}}" "$elf"
    pyocd cmd -t s32k344 -c "savemem 0x$addr $((16#$len)) {{out}}" -c "read32 0x$hbaddr"
    python3 {{TRACE_PY}} check "{{out}}" --zephyr 4.4
