# phase7-W2 -- the emulation ladder. Imported by one line at the end of the
# main justfile. What each rung can and cannot measure: docs/emulation.md.
#
#   just qemu-build          the island for QEMU mps2/an385 (src/qemu_entry)
#   just qemu-run [secs]     boot it under QEMU, bounded; console -> a file
#   just qemu-size           region report of the QEMU image
#   just renode-setup        fetch portable Renode 1.16.0 into build/emulation
#   just renode-run          the BOARD image on Renode's S32K3, bounded
#   just fvp-check           the Arm FVP verdict, re-derived on this host

QEMU_BUILD_DIR := "build-qemu"
# The transport snippet (src/qemu_entry/snippets/): qemu-ethernet (LAN9118 via
# SLIRP; the default, because it is the one that connects) or qemu-serial (the
# board's island-serial transport on UART1; builds, and cannot open a session
# on this board -- zenoh-pico calls uart_configure(), which Zephyr's CMSDK UART
# driver does not implement; docs/emulation.md). Switching it needs a fresh
# build dir (QEMU_BUILD_DIR=...).
QEMU_LINK := env("NROS_QEMU_LINK", "qemu-ethernet")
QEMU_BOARD := env("NROS_QEMU_BOARD", "mps2/an385")
QEMU_LOG_DIR := "build/emulation"
# The host router qemu-run starts. Not 7447: that port is the zenoh default and
# other units' routers and peers use it; a run must not join their graph.
QEMU_ROUTER_PORT := env("NROS_QEMU_ROUTER_PORT", "7449")

# Build the island for QEMU mps2/an385 (zenoh over UART1, or the LAN9118).
qemu-build: sync
    #!/usr/bin/env bash
    set -e
    # The board's Zephyr line (4.4), workspace, venv and SDK, from the nros
    # store -- the same resolver board-build uses.
    source scripts/board-env.sh "{{NANO_ROS_ROOT}}"
    export NROS_INTERFACE_SEARCH_PATH=$PWD/src
    # Capabilities from system.toml, as board-build does.
    caps="$PWD/build/nros/nros_capabilities.cmake"
    mkdir -p "$(dirname "$caps")"
    "{{NANO_ROS_ROOT}}/packages/cli/target/release/nros" config show \
        --workspace "$PWD" --system {{BRINGUP}} --format cmake > "$caps"
    source "{{NANO_ROS_ROOT}}/scripts/lib/zephyr-module.sh"
    nros_module="$(nros_zephyr_module_root "{{NANO_ROS_ROOT}}")"
    # Triage lever, as board-build's: an env var named like a Kconfig symbol
    # overrides it for ONE build without editing a tracked file. Unset ones
    # are not passed. (ZPICO_* cargo knobs reach build.rs from the env as is.)
    EXTRA=()
    for k in CONFIG_NROS_ZEPHYR_HEAP_SIZE CONFIG_MAIN_STACK_SIZE \
             CONFIG_NROS_ZEPHYR_TASK_STACK_SIZE CONFIG_NROS_ZEPHYR_TASK_SLOTS \
             CONFIG_MAX_PTHREAD_MUTEX_COUNT CONFIG_MAX_PTHREAD_COND_COUNT; do
        [ -n "${!k:-}" ] && EXTRA+=("-D${k}=${!k}")
    done
    [ ${#EXTRA[@]} -gt 0 ] && echo "qemu-build: env overrides -> ${EXTRA[*]}"
    # nano_ros_DIR is named, not left to the CMakeLists default (the
    # submodule): with NANO_ROS_ALLOW_EXTERNAL_ROOT=1 NANO_ROS_ROOT=<clone>
    # the cmake package, the Zephyr module and the CLI then all come from ONE
    # tree. Without it an external root got the submodule's cmake modules and
    # the clone's Zephyr module (phase7-W8, testing a nano-ros change before
    # it merged). With the default root the value is the default, unchanged.
    # Snippet form, so src/qemu_entry/boards/mps2_an385.conf is applied. No
    # hal_nxp: this SoC is an ARM CMSDK part, not an NXP one.
    # The build log is kept: the linker's region table is in it, and
    # qemu-size reads it from there.
    mkdir -p {{QEMU_LOG_DIR}}
    set -o pipefail
    west build -b {{QEMU_BOARD}} -S nros-zenoh -S {{QEMU_LINK}} -d {{QEMU_BUILD_DIR}} $PWD/src/qemu_entry -- \
        -C "$caps" \
        -Dnano_ros_ROOT={{NANO_ROS_ROOT}} \
        -Dnano_ros_DIR={{NANO_ROS_ROOT}} \
        -DZEPHYR_EXTRA_MODULES="$nros_module" \
        -DCMAKE_PREFIX_PATH={{NANO_ROS_ROOT}} "${EXTRA[@]}" 2>&1 | tee {{QEMU_LOG_DIR}}/{{QEMU_BUILD_DIR}}.build.log
    # Same refusal as board-build, for the same reason (see the note there):
    # a derived knob that did not ARRIVE is not a derived image.
    #
    # ONE line is tolerated, by name: NROS_DERIVED_SUBSCRIBED_TYPE_BOUNDS. It
    # is red on every build of this pin, board included (phase6-W8b's commit:
    # "red only on the upstream NROS_DERIVED_SUBSCRIBED_TYPE_BOUNDS line
    # (phase-412 W4)"), and a second pass does not converge it. Any OTHER
    # undelivered knob still refuses the image.
    if ! python3 {{NANO_ROS_ROOT}}/scripts/check-knob-delivery.py {{QEMU_BUILD_DIR}} \
            > {{QEMU_LOG_DIR}}/{{QEMU_BUILD_DIR}}.knob-delivery.log 2>&1; then
        cat {{QEMU_LOG_DIR}}/{{QEMU_BUILD_DIR}}.knob-delivery.log
        if grep '^  - ' {{QEMU_LOG_DIR}}/{{QEMU_BUILD_DIR}}.knob-delivery.log | grep -qv '^  - NROS_DERIVED_SUBSCRIBED_TYPE_BOUNDS='; then
            echo ""
            echo "qemu-build: REFUSING this image -- a resolved knob did not reach the compile."
            echo '  Run `just qemu-build` again; the second pass converges.'
            exit 1
        fi
        echo "qemu-build: tolerating the known upstream SUBSCRIBED_TYPE_BOUNDS line (phase-412 W4); nothing else is red."
    else
        cat {{QEMU_LOG_DIR}}/{{QEMU_BUILD_DIR}}.knob-delivery.log
    fi
    just QEMU_BUILD_DIR={{QEMU_BUILD_DIR}} qemu-size

# Region report of the QEMU image (compare: just board-size).
qemu-size:
    #!/usr/bin/env bash
    set -e
    source scripts/board-env.sh "{{NANO_ROS_ROOT}}"
    if [ ! -f "{{QEMU_BUILD_DIR}}/build.ninja" ]; then
        echo "qemu-size: no configured build at {{QEMU_BUILD_DIR}}; run 'just qemu-build'" >&2
        exit 1
    fi
    # The link's own region table, from the last qemu-build's log.
    grep -A4 'Memory region' {{QEMU_LOG_DIR}}/{{QEMU_BUILD_DIR}}.build.log | tail -5 || \
        echo "qemu-size: no region table in {{QEMU_LOG_DIR}}/{{QEMU_BUILD_DIR}}.build.log (a no-op rebuild does not relink)"
    # The largest RAM symbols, which is where a board-vs-QEMU difference shows.
    west build -d {{QEMU_BUILD_DIR}} -t ram_report 2>/dev/null | grep -E '^Root|^=+|[0-9]+ +[0-9.]+%' | head -25

# Boot the QEMU island, bounded, with a host zenoh router it can reach at
# 10.0.2.2:7447 (SLIRP), then list the ROS graph on domain 10 while it runs.
# The console goes to build/emulation/qemu-<stamp>.log and to the terminal.
#
#   just qemu-run          40 s
#   just qemu-run 90
#
# Boot the island under QEMU (bounded), with a host router and a graph listing.
qemu-run secs="40":
    #!/usr/bin/env bash
    set -euo pipefail
    elf="{{QEMU_BUILD_DIR}}/zephyr/zephyr.elf"
    [ -f "$elf" ] || { echo "qemu-run: no $elf; run 'just qemu-build'" >&2; exit 1; }
    nros="{{NANO_ROS_ROOT}}/packages/cli/target/release/nros"
    # The nros store's patched QEMU (nros-sdk-index.toml [tool.qemu]); the
    # distro one is the fallback, and which one ran is printed.
    qemu_dir="$("$nros" sdk-path qemu --require --index "{{NANO_ROS_ROOT}}/nros-sdk-index.toml" 2>/dev/null || true)"
    qemu="${qemu_dir:+$qemu_dir/bin/}qemu-system-arm"
    command -v "$qemu" >/dev/null || { echo "qemu-run: no qemu-system-arm (nros setup --tool qemu)" >&2; exit 1; }
    mkdir -p {{QEMU_LOG_DIR}}
    stamp="$(date +%Y%m%dT%H%M%S)"
    log="{{QEMU_LOG_DIR}}/qemu-$stamp.log"
    graph="{{QEMU_LOG_DIR}}/qemu-$stamp.graph.txt"
    router_log="{{QEMU_LOG_DIR}}/qemu-$stamp.router.log"
    echo "qemu-run: $("$qemu" --version | head -1) ($qemu)"
    echo "qemu-run: console -> $log (bounded to {{secs}} s)"
    pids=()
    cleanup() { for p in "${pids[@]}"; do kill -- -"$p" 2>/dev/null || kill "$p" 2>/dev/null || true; done; }
    trap cleanup EXIT
    set +u; source /opt/ros/humble/setup.bash; set -u
    mon="{{QEMU_LOG_DIR}}/qemu-$stamp.mon"
    # Which transport the image was built with decides how QEMU is wired.
    if grep -q '^CONFIG_NROS_TRANSPORT_SERIAL=y' {{QEMU_BUILD_DIR}}/zephyr/.config; then
        link=serial
    else
        link=ethernet
    fi
    echo "qemu-run: transport $link"
    # -icount off: the guest's timers run on host time, which is what host
    # I/O needs (src/qemu_entry/boards/mps2_an385.conf, "Guest clock"). The
    # monitor is on a socket: the boot report (below) is read through it.
    if [ $link = serial ]; then
        # UART0 = console -> the log file; UART1 = zenoh -> a host PTY. Start
        # paused (-S), put the router on the PTY, then let the guest run, so
        # the first bytes of the session find a listener.
        qout="{{QEMU_LOG_DIR}}/qemu-$stamp.qemu.out"
        qstart=$(date +%s)
        setsid timeout --foreground -s INT {{secs}} "$qemu" \
            -cpu cortex-m3 -machine mps2-an385 -nographic -vga none -S \
            -serial "file:$log" -serial pty \
            -monitor "unix:$mon,server,nowait" \
            -kernel "$elf" </dev/null >"$qout" 2>&1 &
        qpid=$!; pids+=($qpid)
        pty=""
        for i in $(seq 1 40); do
            pty="$(sed -n 's/.*redirected to \(\/dev\/pts\/[0-9]*\) (label serial1).*/\1/p' "$qout")"
            [ -n "$pty" ] && break; sleep 0.25
        done
        [ -n "$pty" ] || { echo "qemu-run: QEMU gave UART1 no PTY" >&2; cat "$qout"; exit 1; }
        echo "qemu-run: UART1 (zenoh) on $pty"
        if true; then
            # The host half, exactly as experiments/serial-interop runs it
            # against the board's UART (router-serial.json5 is required).
            ZENOH_ROUTER_CONFIG_URI=$PWD/experiments/serial-interop/router-serial.json5 \
            ZENOH_CONFIG_OVERRIDE="listen/endpoints=[\"serial/$pty#baudrate=115200\",\"tcp/[::]:{{QEMU_ROUTER_PORT}}\"]" \
                setsid ros2 run rmw_zenoh_cpp rmw_zenohd >"$router_log" 2>&1 &
            pids+=($!)
            sleep 3
        fi
        echo cont | socat -t1 - "UNIX-CONNECT:$mon" >/dev/null 2>&1
    else
        # The image dials 10.0.2.100:7447 (snippets/qemu-ethernet); guestfwd
        # maps that one address to THIS run's router, so a run needs its router.
        ss -ltn 2>/dev/null | grep ':{{QEMU_ROUTER_PORT}} ' >/dev/null && \
            { echo "qemu-run: :{{QEMU_ROUTER_PORT}} is taken; set NROS_QEMU_ROUTER_PORT" >&2; exit 1; }
        ZENOH_CONFIG_OVERRIDE='listen/endpoints=["tcp/[::]:{{QEMU_ROUTER_PORT}}"]' \
            setsid ros2 run rmw_zenoh_cpp rmw_zenohd >"$router_log" 2>&1 &
        pids+=($!)
        # The image dials once, ~2 s after boot (CONFIG_NROS_INIT_DELAY_MS),
        # and a refused dial is a boot that stops at stage 2
        # (ConnectionFailed). So wait for the listener, not a fixed time.
        for i in $(seq 1 60); do ss -ltn 2>/dev/null | grep ':{{QEMU_ROUTER_PORT}} ' >/dev/null && break; sleep 0.5; done
        ss -ltn 2>/dev/null | grep ':{{QEMU_ROUTER_PORT}} ' >/dev/null || { echo "qemu-run: router never listened" >&2; exit 1; }
        qstart=$(date +%s)
        setsid timeout --foreground -s INT {{secs}} "$qemu" \
            -cpu cortex-m3 -machine mps2-an385 -nographic -vga none \
            -nic "user,model=lan9118,guestfwd=tcp:10.0.2.100:7447-tcp:127.0.0.1:{{QEMU_ROUTER_PORT}}" \
            -monitor "unix:$mon,server,nowait" \
            -kernel "$elf" </dev/null >"$log" 2>&1 &
        qpid=$!; pids+=($qpid)
    fi
    tail -n +1 -f "$log" --pid=$qpid &
    tpid=$!
    # The BOOT REPORT: nano-ros's fixed RAM record (CONFIG_NROS_BOOT_REPORT,
    # the board's only diagnostic channel). Read here the way a debugger reads
    # it on the board -- a memory dump at the address the ELF names -- through
    # the QEMU monitor, 3 s before the bound, and decoded by nano-ros's reader.
    report="{{QEMU_LOG_DIR}}/qemu-$stamp.boot-report.txt"
    dump="$PWD/{{QEMU_LOG_DIR}}/qemu-$stamp.boot-report.bin"
    read -r addr len < <(python3 {{NANO_ROS_ROOT}}/scripts/read-boot-report.py --addr-only "$elf" 2>/dev/null)
    ( now=$(date +%s); left=$(( qstart + {{secs}} - 3 - now ))
      sleep $(( left > 0 ? left : 0 ))
      printf 'stop\npmemsave %s %s "%s"\ncont\n' "$addr" "$len" "$dump" \
          | socat -t2 - "UNIX-CONNECT:$mon" >/dev/null 2>&1 || true ) &
    dpid=$!
    gpid=""
    if true; then
        # The graph as the host sees it, half-way through the bound.
        ( sleep $(( {{secs}} / 2 ))
          {
            echo "== ros2 node list (rmw_zenoh_cpp, domain 10), t=+$(( {{secs}} / 2 )) s =="
            RMW_IMPLEMENTATION=rmw_zenoh_cpp ROS_DOMAIN_ID=10 ZENOH_CONFIG_OVERRIDE='connect/endpoints=["tcp/127.0.0.1:{{QEMU_ROUTER_PORT}}"]' timeout 10 ros2 node list --no-daemon 2>&1 || true
            echo "== ros2 topic list =="
            RMW_IMPLEMENTATION=rmw_zenoh_cpp ROS_DOMAIN_ID=10 ZENOH_CONFIG_OVERRIDE='connect/endpoints=["tcp/127.0.0.1:{{QEMU_ROUTER_PORT}}"]' timeout 10 ros2 topic list --no-daemon 2>&1 || true
          } > "$graph" ) &
        gpid=$!
    fi
    wait $dpid || true
    wait $qpid || true
    wait $tpid 2>/dev/null || true
    [ -n "$gpid" ] && { wait $gpid 2>/dev/null || true; }
    echo ""
    echo "qemu-run: console captured in $log"
    if [ -s "$dump" ]; then
        python3 {{NANO_ROS_ROOT}}/scripts/read-boot-report.py "$elf" "$dump" > "$report" 2>&1 || true
        echo "qemu-run: boot report ($addr, $len B) decoded into $report:"
        cat "$report"
    else
        echo "qemu-run: no boot-report dump (monitor unreachable?)"
    fi
    [ -f "$graph" ] && { echo "qemu-run: graph seen from the host ($graph):"; cat "$graph"; }
    true

# -- Renode: the S32K344 board image itself --------------------------------------
# Renode 1.16.0 ships `platforms/cpus/nxp-s32k388.repl`: an S32K3 with the
# same LPUART/STM/SIUL2/GMAC map as the S32K344. The island's delta on it
# (TCM sizes, core clock) is generated below. nano-ros provisions no Renode,
# so this fetches the upstream portable build (76 MB, self-contained .NET)
# into build/emulation/ -- nothing is installed system-wide.
RENODE_VERSION := "1.16.0"
RENODE_DIR := "build/emulation/renode_" + RENODE_VERSION + "-dotnet_portable"

# Fetch the portable Renode into build/emulation (76 MB, once).
renode-setup:
    #!/usr/bin/env bash
    set -euo pipefail
    if [ -x "{{RENODE_DIR}}/renode" ]; then "{{RENODE_DIR}}/renode" --version | head -1; exit 0; fi
    command -v renode >/dev/null && { echo "renode-setup: using $(command -v renode)"; exit 0; }
    mkdir -p build/emulation
    url="https://github.com/renode/renode/releases/download/v{{RENODE_VERSION}}/renode-{{RENODE_VERSION}}.linux-portable-dotnet.tar.gz"
    echo "renode-setup: $url"
    curl -fL --retry 3 -o build/emulation/renode.tar.gz "$url"
    tar -C build/emulation -xzf build/emulation/renode.tar.gz
    rm -f build/emulation/renode.tar.gz
    "{{RENODE_DIR}}/renode" --version | head -1

# Boot a board image (default: the last `just board-build`) on Renode's S32K3,
# bounded, with lpuart2 (the island-serial zenoh link) on a host PTY served by
# rmw_zenohd, the console (lpuart0) to a file, and the boot report read out.
#
#   just renode-run
#   just renode-run build-board/zephyr/zephyr.elf 40
#
# Boot the S32K344 board image on Renode (bounded; zenoh-serial to a host router).
renode-run elf="build-board/zephyr/zephyr.elf" secs="40": renode-setup
    #!/usr/bin/env bash
    set -euo pipefail
    [ -n "${NROS_EMU_TRACE:-}" ] && set -x
    renode="$PWD/{{RENODE_DIR}}/renode"; [ -x "$renode" ] || renode="$(command -v renode)"
    rroot="$(cd "$(dirname "$(readlink -f "$renode")")" && pwd)"
    [ -f "{{elf}}" ] || { echo "renode-run: no {{elf}} (just board-build)" >&2; exit 1; }
    out="$PWD/build/emulation"; stamp="$(date +%Y%m%dT%H%M%S)"
    elf="$out/renode-$stamp.elf"; cp "{{elf}}" "$elf"   # a snapshot: a rebuild mid-run cannot swap it
    pty="$out/renode-lpuart2.pty"; rm -f "$pty"
    log="$out/renode-$stamp.lpuart0.log"
    # The S32K344 as a delta on the S32K388 model. Measured need: the island
    # image puts 84,528 B of .bss in DTCM (the S32K388 model has 64 KiB, the
    # S32K344 128 KiB) and 12,812 B of text in ITCM; the core runs at 160 MHz.
    cat > "$out/s32k344.repl" <<'REPL'
    using "platforms/cpus/nxp-s32k388.repl"
    itcm0:
        size: 0x10000
    dtcm0:
        size: 0x20000
    nvic0:
        systickFrequency: 160000000
    dwt:
        frequency: 160000000
    REPL
    printf '%s\n' \
      'mach create "s32k344-island"' \
      "machine LoadPlatformDescription @$out/s32k344.repl" \
      "sysbus.lpuart0 CreateFileBackend @$log true" \
      "emulation CreateUartPtyTerminal \"term2\" \"$pty\" true" \
      'connector Connect sysbus.lpuart2 term2' \
      "sysbus LoadELF @$elf" \
      'sysbus.cpu0 VectorTableOffset `sysbus GetSymbolAddress "_vector_table"`' \
      > "$out/renode-$stamp.resc"
    port=$(( 20000 + RANDOM % 10000 ))
    pids=()
    cleanup() { echo quit | timeout 3 nc -q1 localhost $port >/dev/null 2>&1 || true
                for p in "${pids[@]}"; do kill -- -"$p" 2>/dev/null || kill "$p" 2>/dev/null || true; done; }
    trap cleanup EXIT
    ( cd "$rroot" && setsid "$renode" --disable-gui --plain -P $port -e "include @$out/renode-$stamp.resc" ) \
        > "$out/renode-$stamp.renode.log" 2>&1 &
    pids+=($!)
    for i in $(seq 1 60); do [ -e "$pty" ] && break; sleep 0.5; done
    [ -e "$pty" ] || { echo "renode-run: Renode never created $pty" >&2; tail "$out/renode-$stamp.renode.log"; exit 1; }
    # The host half of the serial link, exactly as experiments/serial-interop
    # runs it against the real DCD-LZ UART (router-serial.json5 is required;
    # its header says why). TCP on 7448 so a qemu-run router can coexist.
    set +u; source /opt/ros/humble/setup.bash; set -u
    ZENOH_ROUTER_CONFIG_URI=$PWD/experiments/serial-interop/router-serial.json5 \
    ZENOH_CONFIG_OVERRIDE="listen/endpoints=[\"serial/$pty#baudrate=115200\",\"tcp/[::]:7448\"]" \
        setsid ros2 run rmw_zenoh_cpp rmw_zenohd > "$out/renode-$stamp.router.log" 2>&1 &
    pids+=($!)
    sleep 4
    echo start | timeout 3 nc -q1 localhost $port >/dev/null || true   # nc does not return on its own here
    echo "renode-run: image $(sha256sum "$elf" | cut -c1-12), bounded to {{secs}} s"
    sleep {{secs}}
    read -r addr len < <(python3 {{NANO_ROS_ROOT}}/scripts/read-boot-report.py --addr-only "$elf" 2>/dev/null)
    ( echo "sysbus ReadBytes $addr $len"; sleep 2 ) | timeout 6 nc -q3 localhost $port > "$out/renode-$stamp.mon.log" || true
    python3 - "$out/renode-$stamp.mon.log" "$out/renode-$stamp.boot-report.bin" <<'PY'
    import re, sys
    t = open(sys.argv[1], errors="replace").read()
    m = re.findall(r"0x([0-9A-Fa-f]{2})", t[t.rfind("["):] if "[" in t else "")
    open(sys.argv[2], "wb").write(bytes(int(x, 16) for x in m))
    PY
    echo "renode-run: console (lpuart0) $log:"
    cat "$log"; echo
    echo "renode-run: boot report ($addr, $len B):"
    python3 {{NANO_ROS_ROOT}}/scripts/read-boot-report.py "$elf" "$out/renode-$stamp.boot-report.bin" 2>&1 \
        | tee "$out/renode-$stamp.boot-report.txt" || true

# The FVP rung: is any Arm FVP model on this host?
fvp-check:
    #!/usr/bin/env bash
    set -u
    found=0
    for m in FVP_BaseR_AEMv8R FVP_MPS2_Cortex-M7 FVP_MPS2_Cortex-M3; do
        if command -v "$m" >/dev/null; then echo "fvp-check: $m -> $(command -v "$m")"; found=1; fi
    done
    ls -d "$HOME"/.nros/sdk/arm-fvp/* 2>/dev/null && found=1
    [ $found = 1 ] || echo "fvp-check: no FVP model on PATH or in ~/.nros/sdk/arm-fvp"
