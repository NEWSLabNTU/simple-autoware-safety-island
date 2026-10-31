# Autoware Safety Island Example — task runner.
#
# Environment: `direnv allow` (see .envrc) sources ROS 2 Humble, the Autoware
# install, the nano-ros activate.sh and the play_launch overlay, and checks the
# prerequisites; without direnv, source those four by hand. Every recipe still
# sources what it needs, so it also works from a bare shell.
#
#   just setup        one-time prep (play_launch install, generated inputs)
#   just build        build the island (native)
#   just board-build  build the island for the MR-CANHUBK344
#
# Prerequisites NOT installed here: ROS 2 Humble and Autoware 1.5.0.
# play_launch IS installed by `just setup` (onto PATH). `just doctor` verifies.
#
# nano-ros resolves to the PINNED SUBMODULE, not a sibling checkout. That is the
# tree this repo commits a specific revision of, and the one whose sources the
# west module compiles -- a sibling default let the codegen CLI and the CMake
# package come from one tree while the module sources came from another, which
# is precisely the stale-CLI drift packages/cli/CLAUDE.md warns about.
# Override with NANO_ROS_ALLOW_EXTERNAL_ROOT=1 NANO_ROS_ROOT=<path>.
#
# 2026-08-26: the plain `env("NANO_ROS_ROOT", <submodule>)` form let an
# INHERITED value win, and a value inherited from the shell that launched a
# tool is indistinguishable from one typed on purpose. This repo spent a
# session with NANO_ROS_ROOT (and cmake's nano_ros_ROOT) both silently naming
# the SIBLING checkout while every recipe printed
# `scripts/build/cargo.sh: <sibling>/nano-ros/...: No such file or
# directory` and carried on. .envrc guards the interactive path; this guards
# the ones that never source it -- CI, an agent's tool shell, a bare `just`.
# An override now has to name itself, which cannot happen by inheritance.
NROS_ROOT := if env("NANO_ROS_ALLOW_EXTERNAL_ROOT", "") == "1" {
    env("NANO_ROS_ROOT", env("NROS_REPO_DIR", justfile_directory() / "third-party/nano-ros"))
} else if path_exists(justfile_directory() / "third-party/nano-ros/activate.sh") == "true" {
    justfile_directory() / "third-party/nano-ros"
} else {
    env("NANO_ROS_ROOT", justfile_directory() / "third-party/nano-ros")
}
# cmake's find_package(nano_ros) hint. Honoured OVER CMAKE_PREFIX_PATH, so a
# stale value resolves the cmake package to a different tree than the CLI --
# the two halves of one build disagreeing with no diagnostic. Pin it to match.
export nano_ros_ROOT := NROS_ROOT
# nano-ros phase-484 W1 (RFC-0103 D6) retired NANO_ROS_ROOT as an ENVIRONMENT
# name: its cmake package now refuses to configure while the variable is set
# ("the ENVIRONMENT variable NANO_ROS_ROOT is retired"), and NROS_REPO_DIR is
# the one environment name for the root. So the just variable is NROS_ROOT
# (it was NANO_ROS_ROOT; just refuses to unexport a name it also defines), its
# resolution and the NANO_ROS_ALLOW_EXTERNAL_ROOT=1 NANO_ROS_ROOT=<path>
# override are unchanged, and what a recipe's processes inherit is
# NROS_REPO_DIR naming the same tree, never NANO_ROS_ROOT (a direnv shell from
# before this change still exports it). A nested `just` under the override
# therefore finds the root in NROS_REPO_DIR, which the outer recipe exported.
unexport NANO_ROS_ROOT
export NROS_REPO_DIR := NROS_ROOT
# Optional: a play_launch SOURCE checkout to build+install from. Unset (the
# default) means `just setup` installs the published package instead.
PLAY_LAUNCH_REPO := env("PLAY_LAUNCH_REPO", "")
BUILD_DIR := "build"
BRINGUP := "safety_island_bringup"
# RViz needs an X display; the demo box runs TurboVNC on :1 (`vncserver :1`).
VNC_DISPLAY := env("VNC_DISPLAY", ":1")
# The nano-ros SDK CycloneDDS the island builds and runs against (NOT the ROS one).
CYCLONEDDS_HOME := env("NROS_CYCLONEDDS_HOME", env("HOME") / ".nros/sdk/cyclonedds/0.10.5-nros1")
# ── Phase 3: the MR-CANHUBK344 board, on Zephyr 4.4 ─────────────────────────
# 4.4 (rolling), NOT the 3.7 LTS native_sim runs on: 4.5 is expected to become
# the next LTS. nano-ros keeps the two lines in separate west workspaces so
# both work at once — see docs/roadmap/phase-3-canhubk344-real-silicon.md.
BOARD := env("NROS_BOARD", "mr_canhubk3/s32k344")
BOARD_RMW := env("NROS_BOARD_RMW", "nros-zenoh")
# Transport snippet. The board file states board facts and deliberately names
# no transport, so SOMETHING must select one -- and the board DTS has emac0,
# mdio0 and ethernet-phy@12 `status = "okay"`, which means the Ethernet stack
# arrives by default when nothing says otherwise. Leaving this unset does not
# yield "no transport", it yields the Ethernet one, silently, 45 KB over RAM.
BOARD_LINK := env("NROS_BOARD_LINK", "island-serial")
BOARD_BUILD_DIR := "build-board"
# The Zephyr 4.4 workspace, its py3.12 venv and the Zephyr SDK live in the nros
# store (~/.nros, nano-ros RFC-0095), shared by every project on the host, and
# are RESOLVED at recipe time by scripts/board-env.sh -- never a path literal
# here, which is how this repo came to build against a sibling clone's SDK.
# NROS_ZEPHYR_WORKSPACE still overrides the workspace.
# play_launch comes from PATH (installed by `just setup`); override with
# PLAY_LAUNCH=<path> to point at a specific binary. The minimum is the version
# CI pins (PLAY_LAUNCH_VERSION, .github/workflows/check.yml): older binaries
# reject the island contract's grammar (0.12.0: "unknown key in
# `hazards.<name>`") without naming a version. Kept in step by hand with
# .envrc and scripts/env.sh until phase9-W19 reads the pin.
PLAY_LAUNCH := env("PLAY_LAUNCH", "play_launch")
PLAY_LAUNCH_MIN := "0.21.0"

default:
    @just --list

# Verify the environment is usable (nros CLI, play_launch, cmake, ROS 2).
doctor:
    #!/usr/bin/env bash
    set -u
    ok=1
    # The recipes call the PINNED checkout's own CLI by path (board-env.sh,
    # board-build), never a PATH lookup -- so check that binary, not whatever
    # `nros` an activate.sh or ~/.nros/bin put first on PATH. The message uses
    # the justfile value: $NANO_ROS_ROOT is not exported, and under `set -u`
    # expanding it killed this recipe instead of reporting.
    #
    # phase9-U4 (tooling picked up another checkout silently): present is not
    # enough. A CLI built from another commit, or one another checkout put
    # first on PATH, still runs; a nested
    # nano-ros submodule left behind by a non-recursive `git submodule update`
    # surfaces later as a --locked Cargo.lock error. scripts/check-nros-fresh.sh
    # checks the pin, the nested submodules the build reads, and both host
    # tools against their sources, and prints the command for each finding.
    scripts/check-nros-fresh.sh "{{NROS_ROOT}}" || ok=0
    command -v cmake >/dev/null || { echo "MISSING: cmake"; ok=0; }
    [ -d "{{NROS_ROOT}}/cmake" ] || { echo "MISSING: NANO_ROS_ROOT ({{NROS_ROOT}}) is not a nano-ros checkout"; ok=0; }
    [ -f /opt/ros/humble/setup.bash ] || { echo "MISSING: /opt/ros/humble"; ok=0; }
    [ -f /opt/autoware/1.5.0/setup.bash ] || { echo "MISSING: /opt/autoware/1.5.0 (the host-side Autoware the island runs against)"; ok=0; }
    if ! command -v {{PLAY_LAUNCH}} >/dev/null; then
        echo "MISSING: play_launch — run: just setup   (or PLAY_LAUNCH=<path>)"; ok=0
    else
        ver="$({{PLAY_LAUNCH}} --version 2>/dev/null | awk '{print $2}')"
        echo "play_launch: $(command -v {{PLAY_LAUNCH}}) ($ver)"
        if [ -z "$ver" ] || [ "$(printf '%s\n%s\n' "{{PLAY_LAUNCH_MIN}}" "$ver" | sort -V | head -n1)" != "{{PLAY_LAUNCH_MIN}}" ]; then
            echo "  WARNING: play_launch ${ver:-(no version)} is older than the required {{PLAY_LAUNCH_MIN}} (the CI pin; older ones reject the island contract) -- run: just setup-play-launch force"; ok=0
        fi
    fi
    # The host gate (run-board.sh's RB_GATE, through gate-rt) runs SCHED_FIFO 20
    # only when this shell's rtprio limit allows it, else SCHED_OTHER with a
    # line in gate.stdout. A warning: every measured round so far ran it
    # SCHED_OTHER. The limits.d line is in rtss-work-2026-demo:docs/demo-runbook.md
    # section 4 (phase9-W21).
    rtprio="$(ulimit -r)"
    if [ "$rtprio" = unlimited ] || [ "$rtprio" -ge 20 ] 2>/dev/null; then
        echo "rtprio: ulimit -r $rtprio (the host gate can run SCHED_FIFO 20)"
    else
        echo "  WARNING: ulimit -r is $rtprio -- the host availability gate will run SCHED_OTHER, not SCHED_FIFO 20 (rtss-work-2026-demo:docs/demo-runbook.md, 'Real-time limits')"
    fi
    # The display RViz and the demo UI use: a warning, not a failure (the
    # board and CI paths need no display). A headless shell made the demo UI
    # fail with nothing said (phase9-W22).
    disp="{{VNC_DISPLAY}}"; dn="${disp#*:}"; dn="${dn%%.*}"
    if command -v xset >/dev/null && DISPLAY="$disp" timeout 3 xset q >/dev/null 2>&1; then
        echo "X server: $disp answers (xset q)"
    elif [ -S "/tmp/.X11-unix/X$dn" ]; then
        echo "X server: $disp has a socket (/tmp/.X11-unix/X$dn)$(command -v xset >/dev/null && echo ', but xset q got no answer (auth?)')"
    else
        echo "  WARNING: no X server on DISPLAY=$disp (no /tmp/.X11-unix/X$dn) -- RViz and the demo UI will not open; start one (vncserver $disp) or set VNC_DISPLAY"
    fi
    [ "$ok" = 1 ] && echo "doctor: OK (NROS_ROOT={{NROS_ROOT}}, DISPLAY={{VNC_DISPLAY}})"
    [ "$ok" = 1 ]

# Regenerate the generated inputs the build consumes: the message crates and
# the SystemModel.
#
# WHAT A HUMAN AUTHORS, AND WHAT IS GENERATED
#
# Authored, in src/{{BRINGUP}}/: system.toml, launch/*.launch.xml, and the
# launch file's sidecar (<stem>.contract.yaml naming each node's endpoints,
# paths, services and parameters). Those are the only files anyone edits.
#
# Generated: build/nros/models/{{BRINGUP}}/system_model.yaml. It is a BUILD
# ARTIFACT -- never committed, never hand-edited, and never named by an entry
# (the entries say `BRINGUP <pkg>` and let `nros model-path` locate it).
#
# This recipe used to run `play_launch resolve -o src/.../config/
# system_model.yaml`, writing a resolved model INTO the source tree and
# committing it. That put a generated file under human maintenance, and it
# went stale the moment it stopped being regenerated: the committed model was
# resolved before the contract sidecar existed, so it carried `topics: 0` and
# every pool derived from it was sized for a system with no wiring. `nros
# sync` resolves the same tree, records every input's sha256 in the model's
# `meta.inputs` (the contract INCLUDED, which is what makes staleness
# detectable), and writes it where nobody is tempted to edit it.
sync:
    #!/usr/bin/env bash
    set -e
    source /opt/ros/humble/setup.bash
    source "{{NROS_ROOT}}/activate.sh"
    nros sync

# One-time workspace prep, in dependency order:
#   play_launch (source build + wheel install) -> env check -> generated inputs.
# Interface codegen runs at cmake-configure time, so `just build` is next.
#
# One-time workspace prep (play_launch, generated inputs).
setup: setup-play-launch doctor sync

# Put play_launch (>= {{PLAY_LAUNCH_MIN}}) on PATH. Two sources:
#   * default          — pip install the published package
#   * PLAY_LAUNCH_REPO — a source checkout: build it (colcon + interception +
#                        wheel) and install THAT wheel, so PATH carries exactly
#                        the binary you built
# No-op when PATH already has a new enough one; `just setup-play-launch force`
# reinstalls regardless.
#
# Install play_launch onto PATH.
setup-play-launch force="":
    #!/usr/bin/env bash
    set -e
    if [ -z "{{force}}" ] && command -v {{PLAY_LAUNCH}} >/dev/null; then
        ver="$({{PLAY_LAUNCH}} --version 2>/dev/null | awk '{print $2}')"
        if [ -n "$ver" ] && [ "$(printf '%s\n%s\n' "{{PLAY_LAUNCH_MIN}}" "$ver" | sort -V | head -n1)" = "{{PLAY_LAUNCH_MIN}}" ]; then
            echo "play_launch $ver already on PATH ($(command -v {{PLAY_LAUNCH}}))"; exit 0
        fi
    fi
    if [ -n "{{PLAY_LAUNCH_REPO}}" ]; then
        [ -d "{{PLAY_LAUNCH_REPO}}" ] || { echo "PLAY_LAUNCH_REPO={{PLAY_LAUNCH_REPO}} does not exist"; exit 1; }
        echo "-- building play_launch from source: {{PLAY_LAUNCH_REPO}}"
        source /opt/ros/humble/setup.bash
        ( cd "{{PLAY_LAUNCH_REPO}}" && just build )
        pip install --force-reinstall --no-deps "{{PLAY_LAUNCH_REPO}}"/dist/*.whl
    else
        echo "-- installing play_launch (>= {{PLAY_LAUNCH_MIN}}) from the package index"
        pip install --upgrade "play_launch>={{PLAY_LAUNCH_MIN}}"
    fi
    command -v play_launch >/dev/null || { echo "play_launch still not on PATH — is ~/.local/bin in PATH?"; exit 1; }
    echo "play_launch: $(command -v play_launch) ($(play_launch --version 2>/dev/null))"

# Install play_launch's own build deps (colcon-cargo-ros2, rosdep packages) —
# only needed when building it from a source checkout. Interactive.
#
# Install play_launch's build dependencies (source builds only).
setup-deps:
    #!/usr/bin/env bash
    set -e
    [ -n "{{PLAY_LAUNCH_REPO}}" ] || { echo "set PLAY_LAUNCH_REPO=<play_launch checkout> first (only needed for source builds)"; exit 1; }
    cd "{{PLAY_LAUNCH_REPO}}" && just install-deps

# Native build (fast dev loop).
# NROS_EXECUTOR_MAX_CBS: compile-time executor callback-slot count (nros-node
# build.rs env knob, default 4); NROS_CYCLONEDDS_MAX_TYPES: cyclone type-registry
# capacity (default 32 — the island vendors ~35+ msg types). Both compile-time;
# clean-rebuild after changing. The island registers ~9 entries
# (subs + services + timers) + the handler ~10 more; 32 gives headroom.
# CycloneDDS_DIR is PINNED to the nano-ros SDK build: with a ROS env sourced
# (which .envrc does) find_package would otherwise pick /opt/ros/humble's
# Cyclone, and the island links against the SDK one at runtime anyway.
#
# Build the island for the native board.
#
# ROS is sourced HERE, the way `sync` does it, not left to .envrc: the Cyclone
# typesupport step runs ROS's rosidl_adapter from inside the nested cmake
# build, and a shell direnv never touched (CI, a script, an agent) reached it
# with no ROS site-packages on PYTHONPATH and failed with "rosidl_adapter is not
# importable by this build's interpreter". The CycloneDDS_DIR pin above is what
# keeps a sourced ROS from also supplying the wrong Cyclone.
#
# NROS_BRINGUP_DIR names the bringup this build is for. The workspace holds
# four system.toml files (the bringup and the three Zephyr entries), and
# since the nano-ros pin of phase10-B3 `nros ws board-facts` refuses to pick
# one when the configure names none (nano-ros issue 1827: `nros build` passes
# the same variable). The bringup declares no image, so the posix build has
# no board facts to carry, as before.
build: sync
    #!/usr/bin/env bash
    set -e
    source /opt/ros/humble/setup.bash
    env NROS_EXECUTOR_MAX_CBS=32 cmake -S . -B {{BUILD_DIR}} -Dnano_ros_ROOT={{NROS_ROOT}} \
        -DNROS_BRINGUP_DIR=$PWD/src/{{BRINGUP}} \
        -DCycloneDDS_DIR={{CYCLONEDDS_HOME}}/lib/cmake/CycloneDDS
    env NROS_EXECUTOR_MAX_CBS=32 cmake --build {{BUILD_DIR}} -j

# Boot the island on the native board (demo domain, pinned cyclonedds — a
# sourced ROS env otherwise shadows the SDK lib → SIGSEGV; porting-notes env).
#
# Build and boot the island on the native board (foreground).
run: build
    env LD_LIBRARY_PATH="{{CYCLONEDDS_HOME}}/lib" \
        ROS_DOMAIN_ID="${ROS_DOMAIN_ID:-10}" \
        ./{{BUILD_DIR}}/src/native_entry/native_entry

# Build the vendored msg pkgs as a host colcon overlay so ros2 CLI tools can
# echo/call the island's typed topics (also proves the pkgs build verbatim).
#
# Build the vendored msg pkgs as a host colcon overlay.
host-msgs:
    #!/usr/bin/env bash
    set -e
    source /opt/ros/humble/setup.bash
    mkdir -p tmp/host_msgs_ws/src && cd tmp/host_msgs_ws/src
    ln -sfn ../../../src/autoware_common_msgs ../../../src/autoware_control_msgs ../../../src/tier4_system_msgs .
    cd .. && colcon build --symlink-install
    echo "source tmp/host_msgs_ws/install/setup.bash + RMW_IMPLEMENTATION=rmw_cyclonedds_cpp ROS_DOMAIN_ID=$ROS_DOMAIN_ID"

# Remove the native build tree.
clean:
    rm -rf {{BUILD_DIR}}

# ── Zephyr (phase 4) ────────────────────────────────────────────────────────
# native_sim first; QEMU board bring-up is a follow-up item.

# Build the island as a Zephyr native_sim image.
zephyr-build: sync
    #!/usr/bin/env bash
    set -e
    # The 3.7 LTS workspace and its SDK come from the nros store, the same way
    # the board's do (`just zephyr-setup` provisions them).
    source scripts/board-env.sh "{{NROS_ROOT}}" 3.7
    # This image uses Cyclone, whose typesupport step runs ROS's rosidl_adapter
    # inside the nested build; ROS is sourced here for the reason `build`
    # sources it (the board image is zenoh and never needed it).
    source /opt/ros/humble/setup.bash
    export NROS_EXECUTOR_MAX_CBS="${NROS_EXECUTOR_MAX_CBS:-32}" NROS_INTERFACE_SEARCH_PATH=$PWD/src
    # Capabilities from system.toml, as board-build does (see the note there).
    caps="$PWD/build/nros/nros_capabilities.cmake"
    mkdir -p "$(dirname "$caps")"
    "{{NROS_ROOT}}/packages/cli/target/release/nros" config show \
        --workspace "$PWD" --system {{BRINGUP}} --format cmake > "$caps"
    # Name the `nros` Zephyr module -- THIS submodule -- on the command line.
    #
    # Until nano-ros issue 1379 the store workspace's `nano-ros` manifest
    # project was a SYMLINK to whichever checkout ran `just zephyr setup`, and
    # every image built there, ours included, took the nros module (the zpico
    # shim, the platform sources, the nros-c/nros-cpp headers, the knob
    # inventory) from THAT tree while codegen and the cmake verbs came from the
    # one this recipe names with -Dnano_ros_ROOT. The halves agreed here only
    # because the link happened to point at this submodule. nano-ros now
    # unbinds the link in `just zephyr setup` (which _zephyr-provision runs)
    # and every one of its own builds names its module through
    # scripts/lib/zephyr-module.sh; once the workspace is unbound a build that
    # does not configures with NO nros module. Use the helper rather than
    # spell the path: it is the one spelling nano-ros gates, and it names the
    # checkout ROOT (the directory holding zephyr/module.yml), not
    # <root>/zephyr, which configure rejects as "not a valid zephyr module".
    # Naming it while the link still exists is harmless -- Zephyr keys modules
    # by name, so the same tree listed twice is one module.
    source "{{NROS_ROOT}}/scripts/lib/zephyr-module.sh"
    module_arg="$(nros_zephyr_module_cmake_arg "{{NROS_ROOT}}")"
    # src/native_sim_entry, not src/zephyr_entry: the board image is zenoh
    # and nano-ros checks an image's declared `rmw` against Kconfig per ENTRY
    # PACKAGE, so the Cyclone native_sim image has its own (see the
    # CMakeLists there). The build dir and the demo recipes are unchanged.
    west build -b native_sim/native/64 -d build-zephyr src/native_sim_entry -- \
        -C "$caps" \
        -DCONF_FILE="prj.conf;prj-cyclonedds.conf" \
        "$module_arg" \
        -Dnano_ros_ROOT={{NROS_ROOT}} -DCMAKE_PREFIX_PATH={{NROS_ROOT}}

# Run the Zephyr island (domain 2 baked; host side: `just host-env`).
# One line on purpose: each recipe line is its own shell, and the SNTP responder
# exits once its parent is gone, so it must share the island's line and the
# island must be that shell (exec) -- phase8-W18's epoch (prj.conf).
zephyr-run:
    python3 scripts/sntp-server.py >> tmp_sntp.log 2>&1 & exec ./build-zephyr/zephyr/zephyr.exe

# ── The board: NXP MR-CANHUBK344 (S32K344) on Zephyr 4.4 ────────────────────
# Separate recipes rather than parameters on zephyr-build, because all three of
# its LTS-isms differ: the workspace, the board, and the RMW-selection form.
# native_sim uses -DCONF_FILE=, which SUPPRESSES boards/<board>.conf; the board
# uses a 4.x snippet (-S), which leaves the board file in play. Mixing them
# would silently drop the hardware config.


# Skips the Micro XRCE-DDS Agent (a Fast-DDS superbuild) — that is only needed
# for XRCE *runtime* tests and the island uses zenoh/cyclone. Builds nano-ros's
# CLI first: `nros setup --source` runs inside the zephyr setup and resolves the
# binary from $NROS_CLI / PATH / ~/.nros, none of which are guaranteed here.
#
# Provisions into the nros store (~/.nros), the user-workflow layout of nano-ros
# RFC-0095, in three steps: the Zephyr 4.4 workspace and its py3.12 venv, the
# Zephyr SDK that tree asks for, then this island's own Zephyr patch. Every step
# is idempotent, so re-run it after a `west update` drops the patch.
#
# One-time: provision the Zephyr 4.4 workspace, venv and SDK into ~/.nros (large).
board-setup: (_zephyr-provision "4.4")
    #!/usr/bin/env bash
    set -e
    source scripts/board-env.sh "{{NROS_ROOT}}" 4.4
    # patches/zephyr/0001 (DTCM relocation), board-only. See board-doctor for
    # what its absence looks like.
    if ! grep -q 'trailing_match' "$ISLAND_ZEPHYR_WS/zephyr/scripts/build/gen_relocate_app.py"; then
        git -C "$ISLAND_ZEPHYR_WS/zephyr" apply {{justfile_directory()}}/patches/zephyr/*.patch
    fi
    # hal_nxp — this board's vendor HAL. nano-ros's 4.4 allowlist omits it on
    # purpose and names this tree as the downstream that re-enables it; see the
    # long note in `board-build` for why we name the module there rather than
    # re-rooting the west manifest. west therefore never fetches it, so fetch it
    # here, pinned to what THIS Zephyr asks for (its own west.yml entry) rather
    # than a revision of our choosing.
    hal_nxp="$ISLAND_ZEPHYR_WS/modules/hal/nxp"
    rev="$(awk '/^    - name: hal_nxp$/{f=1;next} f&&/revision:/{print $2;exit}' \
        "$ISLAND_ZEPHYR_WS/zephyr/west.yml")"
    if [ -z "$rev" ]; then
        echo "board-setup: no hal_nxp revision in $ISLAND_ZEPHYR_WS/zephyr/west.yml" >&2
        exit 1
    fi
    if [ ! -d "$hal_nxp/.git" ]; then
        echo "[board-setup] fetching hal_nxp @ $rev (~1.3 GB, the index's approx_mb)"
        git clone --filter=blob:none https://github.com/zephyrproject-rtos/hal_nxp "$hal_nxp"
    fi
    if [ "$(git -C "$hal_nxp" rev-parse HEAD)" != "$rev" ]; then
        git -C "$hal_nxp" fetch origin "$rev"
        git -C "$hal_nxp" checkout --detach "$rev"
    fi
    echo "workspace: $ISLAND_ZEPHYR_WS"
    echo "hal_nxp:   $hal_nxp @ $rev"
    echo "sdk:       $ZEPHYR_SDK_INSTALL_DIR"

# One-time: provision the Zephyr 3.7 LTS workspace and SDK (native_sim) into ~/.nros.
zephyr-setup: (_zephyr-provision "3.7")
    #!/usr/bin/env bash
    set -e
    source scripts/board-env.sh "{{NROS_ROOT}}" 3.7
    echo "workspace: $ISLAND_ZEPHYR_WS"
    echo "sdk:       $ZEPHYR_SDK_INSTALL_DIR"

# One Zephyr line into the store: the west workspace (and, for 4.4, its py3.12
# venv), then the SDK that tree asks for. Idempotent.
[private]
_zephyr-provision line:
    #!/usr/bin/env bash
    set -e
    root="{{NROS_ROOT}}"
    nros="$root/packages/cli/target/release/nros"
    index="$root/nros-sdk-index.toml"
    if [ ! -x "$nros" ]; then
        echo "[zephyr-provision] building the nros CLI first..."
        (cd "$root" && just setup-cli)
    fi
    ws="${NROS_ZEPHYR_WORKSPACE:-$("$root/scripts/lib/zephyr-workspace.sh" --version {{line}} resolve-or-default)}"
    # 1. The west workspace. `just zephyr setup` is nano-ros's only provisioner
    #    for one; the index does not model a west workspace. --skip-sdk because
    #    its SDK install lands INSIDE the checkout (nano-ros issue 1254); step 2
    #    puts the SDK in the store instead. NROS_ZEPHYR_CREATE_VENV=1 lets it
    #    create .venv312 with uv; without it the 4.4 line only checks for one.
    (cd "$root" && NROS_ZEPHYR_VERSION={{line}} NROS_ZEPHYR_WORKSPACE="$ws" \
        NROS_ZEPHYR_CREATE_VENV=1 NROS_ZEPHYR_SKIP_XRCE_AGENT=1 \
        just zephyr setup --skip-sdk)
    # 2. The SDK the tree asks for, into the store. `nros setup --tool` unpacks
    #    the bundle only (nano-ros issue 1259). The SDK's own installer does the
    #    rest -- the toolchains when the bundle is `_minimal` (1.x), the host
    #    tools (-h) and the CMake package registration (-c) always -- and
    #    nano-ros runs it only when it installs the SDK itself, into the
    #    checkout. Run it every time: it skips a toolchain already present, and
    #    "a toolchain directory exists" does not mean the host tools do.
    read -r tool ver < <(scripts/zephyr-sdk-tool.sh "$root" "$ws")
    [ -n "$tool" ] || exit 1
    "$nros" setup --tool "$tool" --index "$index"
    # `nros sdk-path` returns the SDK root itself at this pin (and the store
    # prefix above it at older ones); accept both, as scripts/board-env.sh does.
    # Appending unconditionally made every board-setup on a provisioned host
    # die on `cd: .../zephyr-sdk-1.0.1/zephyr-sdk-1.0.1` (phase9-W21).
    sdk="$("$nros" sdk-path "$tool" --require --index "$index")"
    [ "$(basename "$sdk")" = "zephyr-sdk-$ver" ] || sdk="$sdk/zephyr-sdk-$ver"
    (cd "$sdk" && ./setup.sh -t x86_64-zephyr-elf -t arm-zephyr-eabi -h -c)

# Report whether the board toolchain is ready. Read-only.
board-doctor:
    #!/usr/bin/env bash
    set +e
    fail=0
    # Resolve exactly what board-build will use; on a miss board-env.sh names
    # what is missing and the remedy.
    if source scripts/board-env.sh "{{NROS_ROOT}}"; then
        echo "  [OK]      zephyr 4.4 workspace: $ISLAND_ZEPHYR_WS"
        echo "  [OK]      zephyr sdk: $ZEPHYR_SDK_INSTALL_DIR"
        echo "  [OK]      west (py3.12 venv): $(python --version 2>&1)"
    else
        fail=1
    fi
    if [ -d "$ISLAND_ZEPHYR_WS/zephyr/boards/nxp/mr_canhubk3" ]; then
        echo "  [OK]      board mr_canhubk3 present upstream"
    else
        echo "  [MISSING] boards/nxp/mr_canhubk3 in the workspace"; fail=1
    fi
    if command -v pyocd >/dev/null; then
        echo "  [OK]      pyocd $(pyocd --version 2>/dev/null)"
        pyocd list 2>/dev/null | grep -qiE 'cmsis|mcu-link' \
            && echo "  [OK]      a CMSIS-DAP probe is connected" \
            || echo "  [note]    no probe connected (MCU-Link needed to flash)"
    else
        echo "  [MISSING] pyocd"; fail=1
    fi
    [ -f src/zephyr_entry/boards/mr_canhubk3_s32k344.conf ] \
        && echo "  [OK]      board conf present" \
        || { echo "  [MISSING] src/zephyr_entry/boards/mr_canhubk3_s32k344.conf"; fail=1; }
    # patches/zephyr/0001 must be applied for the entry's .bss to reach DTCM.
    # `west update` resets the Zephyr tree and silently drops it. Without it
    # zephyr_code_relocate() emits an empty fragment, prints nothing, exits 0 --
    # and the build then fails with "region RAM overflowed by ~39000 bytes",
    # which does not name the real cause. Check for the fix, not the patch file.
    if grep -q 'trailing_match' "$ISLAND_ZEPHYR_WS/zephyr/scripts/build/gen_relocate_app.py" 2>/dev/null; then
        echo "  [OK]      zephyr patch 0001 (gen_relocate_app) applied"
    else
        echo "  [MISSING] zephyr patch 0001 — DTCM relocation will silently no-op"
        echo "            and the build will overflow RAM. Re-apply:"
        echo "            cd $ISLAND_ZEPHYR_WS/zephyr && git apply {{justfile_directory()}}/patches/zephyr/*.patch"
        fail=1
    fi
    # The ROS domain, from every place that states it (nano-ros issue 1550;
    # docs/boot-through.md F6). The image bakes CONFIG_NROS_DOMAIN_ID and
    # nothing else reaches it; the transport snippet is where it is stated;
    # system.toml is a check, not a writer; ROS_DOMAIN_ID is what every host
    # ros2 / rmw_zenoh_cpp process in THIS shell joins. A mismatch is silent at
    # run time -- the session opens and the graph is simply empty -- so all of
    # them must say the same number.
    conf_dom() { sed -n 's/^CONFIG_NROS_DOMAIN_ID=\([0-9]*\).*/\1/p' "$@" 2>/dev/null | tail -1; }
    doms=()
    sys_dom="$(sed -n 's/^domain_id *= *\([0-9]*\).*/\1/p' src/zephyr_entry/system.toml | head -1)"
    printf '  %-9s %-44s %s\n' domain "system.toml (src/zephyr_entry)" "${sys_dom:-not stated}"
    [ -n "$sys_dom" ] && doms+=("$sys_dom")
    board_dom="$(conf_dom src/zephyr_entry/boards/mr_canhubk3_s32k344.conf)"
    printf '  %-9s %-44s %s\n' domain "board conf" "${board_dom:-not stated}"
    for snip in src/zephyr_entry/snippets/*/; do
        name="$(basename "$snip")"
        d="$(conf_dom "$snip"*.conf)"
        if [ -n "$d" ]; then
            printf '  %-9s %-44s %s\n' domain "snippet $name" "$d"
            doms+=("$d")
        else
            eff="${board_dom:-0}"
            printf '  %-9s %-44s %s\n' domain "snippet $name" \
                "not stated -> the image falls to $eff${board_dom:+ (the board conf)}${board_dom:- (Kconfig default)}"
            doms+=("$eff")
        fi
    done
    cfg="{{BOARD_BUILD_DIR}}/zephyr/.config"
    if [ -f "$cfg" ]; then
        link=ethernet; grep -q '^CONFIG_NROS_TRANSPORT_SERIAL=y' "$cfg" && link=serial
        img_dom="$(conf_dom "$cfg")"
        printf '  %-9s %-44s %s\n' domain "image {{BOARD_BUILD_DIR}} ($link)" "${img_dom:-0 (Kconfig default)}"
        doms+=("${img_dom:-0}")
    else
        printf '  %-9s %-44s %s\n' domain "image {{BOARD_BUILD_DIR}}" "not built"
    fi
    printf '  %-9s %-44s %s\n' domain "ROS_DOMAIN_ID in this shell" "${ROS_DOMAIN_ID:-unset (ros2 joins 0)}"
    doms+=("${ROS_DOMAIN_ID:-0}")
    uniq_doms="$(printf '%s\n' "${doms[@]}" | sort -u | tr '\n' ' ')"
    if [ "$(printf '%s\n' "${doms[@]}" | sort -u | wc -l)" -eq 1 ]; then
        echo "  [OK]      one ROS domain everywhere: ${doms[0]}"
    else
        echo "  [MISMATCH] the image, a snippet, system.toml and the shell name different"
        echo "            domains ($uniq_doms). State CONFIG_NROS_DOMAIN_ID once per transport"
        echo "            snippet and export ROS_DOMAIN_ID to match (source scripts/env.sh)."
        fail=1
    fi
    exit $fail

# Exercises the IVT header, the FS26 watchdog and the flash chain, so a failure
# here is unambiguously board-or-probe rather than ours.
#
# Z0 — stock Zephyr hello_world on the board. NO nano-ros. Run this FIRST.
board-hello:
    #!/usr/bin/env bash
    set -e
    source scripts/board-env.sh "{{NROS_ROOT}}"
    # Build output stays with this project, never inside the shared store
    # workspace (nano-ros RFC-0095 D2).
    # hal_nxp is not in nano-ros's west-4.4 allowlist (see board-build); the
    # board's pinctrl headers live there, so the sample needs it named too.
    # Without it: `fatal error: nxp/s32/S32K344-172MQFP-pinctrl.h`.
    hal_nxp="$ISLAND_ZEPHYR_WS/modules/hal/nxp"
    if [ ! -d "$hal_nxp" ]; then
        echo "board-hello: hal_nxp is not in the workspace ($hal_nxp); run just board-setup" >&2
        exit 1
    fi
    west build -b {{BOARD}} -d build-hello "$ZEPHYR_BASE/samples/hello_world" --pristine=auto \
        -- -DZEPHYR_EXTRA_MODULES="$hal_nxp"
    # -r pyocd explicitly: the board lists jlink FIRST in board.cmake, so west
    # picks it by default and dies on `JLinkExe not found`. We flash with an
    # MCU-Link (CMSIS-DAP), which is pyocd's job.
    west flash -d build-hello -r pyocd
    echo "Now attach the console: just board-console"

# RMW via a 4.x snippet (-S), which keeps boards/<board>.conf in play — do NOT
# switch this to -DCONF_FILE, that suppresses the board file.
#
# Build the island for the board.
board-build: sync
    #!/usr/bin/env bash
    set -e
    # `west build` from outside the workspace finds it through ZEPHYR_BASE, or
    # reports `unknown command "build"`. board-env.sh resolves the workspace,
    # its py3.12 venv (west itself; 4.4 needs python >= 3.12) and the SDK from
    # the nros store, and puts the pinned checkout's `nros` first on PATH
    # (never ~/.nros/bin -- see the note in board-env.sh).
    source scripts/board-env.sh "{{NROS_ROOT}}"
    export NROS_INTERFACE_SEARCH_PATH=$PWD/src
    # -- Kconfig sizing: the board conf, not -D -----------------------------
    # Until nano-ros 3d52070ec (2026-08-24; in the pin f03d9d190) the
    # nros-zenoh snippet, merged after the board conf as EXTRA_CONF_FILE, set
    # MAIN_STACK_SIZE, HEAP_MEM_POOL_SIZE, SYSTEM_WORKQUEUE_STACK_SIZE and the
    # NET_PKT/NET_BUF counts outright, so this recipe carried them as a column
    # of -DCONFIG_* (the one hook that merges last). That column is gone; the
    # precedence is now  -D > board conf > snippet configdefault.
    #
    # The entity limits, the executor and zenoh pools and the net caps reach
    # cargo through Kconfig rows (nano-ros #0749, #0752); before those, five
    # of them reached build.rs only from this shell's environment and a bare
    # `ninja` rebuilt the image at crate defaults.
    #
    # MAIN_STACK_SIZE is charged twice on this platform: once for the main
    # thread, and again as NROS_ZEPHYR_STACK_SIZE x NROS_ZEPHYR_MAX_THREADS for
    # the pthread stack pool (nros_platform_zephyr_shims.c:293-301). The entry
    # CMakeLists pins MAX_THREADS to 4, so the pool costs 4 x 8192 there.
    #
    # Sizing moved to boards/mr_canhubk3_s32k344.conf. It could not live there
    # while an RMW snippet -- EXTRA_CONF_FILE, merged after the board file --
    # set the same symbols outright; nano-ros now supplies snippet sizing as
    # `configdefault`, so the board conf wins and the values sit next to their
    # reasoning instead of in a build recipe.
    #
    # These env vars remain as a TRIAGE lever: set one to override the conf for
    # a single build without editing a tracked file. Unset ones are not passed.
    # `find_package(nano_ros)` resolves via CMake's `<pkg>_ROOT`, and the
    # precedence is  -Dnano_ros_ROOT  >  $nano_ros_ROOT  >  CMAKE_PREFIX_PATH
    # (measured, not assumed). nano-ros's activate.sh EXPORTS nano_ros_ROOT, so a
    # shell that sourced some other checkout silently outranked the
    # -DCMAKE_PREFIX_PATH this recipe used to pass alone, and the build resolved
    # to a tree nobody named on the command line. We now pass -Dnano_ros_ROOT,
    # which wins; say so when the env disagrees, because the symptom otherwise is
    # an error citing a path you did not choose.
    if [ -n "${nano_ros_ROOT:-}" ] && \
       [ "$(readlink -f "$nano_ros_ROOT")" != "$(readlink -f "{{NROS_ROOT}}")" ]; then
        echo "board-build: NOTE \$nano_ros_ROOT=$nano_ros_ROOT is being overridden"
        echo "board-build:       building against {{NROS_ROOT}}"
    fi

    EXTRA=()
    for k in CONFIG_MAIN_STACK_SIZE CONFIG_HEAP_MEM_POOL_SIZE \
             CONFIG_SYSTEM_WORKQUEUE_STACK_SIZE \
             CONFIG_NET_PKT_RX_COUNT CONFIG_NET_PKT_TX_COUNT \
             CONFIG_NET_BUF_RX_COUNT CONFIG_NET_BUF_TX_COUNT \
             CONFIG_COMMON_LIBC_MALLOC_ARENA_SIZE; do
        [ -n "${!k:-}" ] && EXTRA+=("-D${k}=${!k}")
    done
    # ISLAND_BOARD_KCONFIG="CONFIG_A=y CONFIG_B=2": any Kconfig symbol, as -D,
    # without editing the tracked board conf. `just board-build-diag` sets it
    # (with its own build dir); a normal build leaves it unset.
    for kv in ${ISLAND_BOARD_KCONFIG:-}; do
        case "$kv" in CONFIG_*=*) EXTRA+=("-D$kv");;
            *) echo "board-build: ISLAND_BOARD_KCONFIG entry '$kv' is not CONFIG_<name>=<value>" >&2; exit 2;; esac
    done
    [ ${#EXTRA[@]} -gt 0 ] && echo "board-build: env overrides -> ${EXTRA[*]}"
    # ISLAND_BOARD_SNIPPETS="island-booth": more snippets (src/zephyr_entry/snippets),
    # after the RMW and the link; `just board-build-booth` sets it (with its own
    # build dir). A normal build leaves it unset: the gate image.
    SNIP=()
    for sn in ${ISLAND_BOARD_SNIPPETS:-}; do SNIP+=(-S "$sn"); done
    [ ${#SNIP[@]} -gt 0 ] && echo "board-build: extra snippets -> ${SNIP[*]}"
    # The image's capabilities (param_services), from system.toml through the
    # CLI's SSoT accessor. The Zephyr lane does not resolve them from the
    # entry's BRINGUP yet (nano-ros zephyr/CMakeLists.txt, "Follow-up: resolve
    # from the entry's BRINGUP"), so it reads NANO_ROS_FEATURES; the CLI's
    # `--format cmake` output is a `set(... CACHE ... FORCE)` line, which is
    # exactly an initial-cache file for `-C`. Nothing here restates the list.
    caps="$PWD/build/nros/nros_capabilities.cmake"
    mkdir -p "$(dirname "$caps")"
    "{{NROS_ROOT}}/packages/cli/target/release/nros" config show \
        --workspace "$PWD" --system {{BRINGUP}} --format cmake > "$caps"
    # hal_nxp is NOT in nano-ros's west-4.4 allowlist, on purpose:
    # `nros-sdk-index.toml` `[zephyr_module.hal_nxp]` says "no build in this
    # repo needs `hal_nxp`; a downstream one does", and names US as that
    # downstream. This board IS an NXP S32K344, and its board files include
    #     #include <nxp/s32/S32K344-172MQFP-pinctrl.h>
    # which ships in the module's `dts/`. Unregistered, west never lists the
    # module, Zephyr never puts that `dts/` on the devicetree include path, and
    # the build dies in devicetree preprocessing with "No such file or
    # directory" -- with the header sitting on disk the whole time, because
    # FETCHED and REGISTERED AS A ZEPHYR MODULE are different things.
    #
    # The index suggests a downstream manifest that `import:`s nano-ros's. We
    # do not take that route: re-rooting the manifest would clone a SECOND
    # nano-ros at whatever `revision:` we wrote, free to drift from the
    # submodule pin this tree actually builds. Naming the module directly
    # keeps one nano-ros and one pin.
    #
    # This paragraph used to add that nano-ros was "already in this workspace
    # as the manifest repo (a symlink to our own submodule)". It was, until
    # nano-ros issue 1379 unbound the store workspace from any checkout; the
    # nros module is now named on the command line too, beside hal_nxp, for
    # the reason written above the same line in zephyr-build.
    # ZEPHYR_EXTRA_MODULES is a cmake LIST: the two entries are `;`-joined.
    hal_nxp="$ISLAND_ZEPHYR_WS/modules/hal/nxp"
    if [ ! -d "$hal_nxp" ]; then
        echo "board-build: hal_nxp is not in the workspace ($hal_nxp)" >&2
        echo "board-build:   provision it: just board-setup" >&2
        exit 1
    fi

    source "{{NROS_ROOT}}/scripts/lib/zephyr-module.sh"
    nros_module="$(nros_zephyr_module_root "{{NROS_ROOT}}")"

    west build -b {{BOARD}} -S {{BOARD_RMW}} -S {{BOARD_LINK}} "${SNIP[@]}" -d {{BOARD_BUILD_DIR}} $PWD/src/zephyr_entry -- \
        -C "$caps" \
        -Dnano_ros_ROOT={{NROS_ROOT}} \
        -DZEPHYR_EXTRA_MODULES="$nros_module;$hal_nxp" \
        -DCMAKE_PREFIX_PATH={{NROS_ROOT}} "${EXTRA[@]}"

    # A DERIVED value being right is not the question; whether it ARRIVED is.
    #
    # The knob chain here is two producers deep -- the entity inventory feeds
    # the message-bound sizes, which the knob resolver reads FIRST, inside
    # find_package(Zephyr) -- so the value delivered to the compiler settles
    # only on the third configure. nano-ros arms those re-configures and states
    # that ninja runs all three inside one `west build`. Measured on this board
    # 2026-09-06, it does not: a clean build dir gets 2 configures against 3
    # arming requests, and the image links with the pass-2 value.
    #
    # That is not cosmetic. The subscriber payload class arrives as the whole
    # linked CLOSURE (1496 B) instead of the SUBSCRIBED set (880 B), the arena
    # model bills three receive buffers per subscription at the wrong one, and
    # the image ships a 70296-byte arena where 46272 is correct -- 24 KB, on a
    # part with 320 KB of RAM. It is silent because over-sized always is.
    #
    # So the build refuses instead of flashing it. Running `just board-build`
    # again is what converges it, which is why the message says so rather than
    # this recipe looping: a build that quietly re-runs itself hides how many
    # passes the chain actually needs, and that number is the bug.
    #
    # ONE line is tolerated, by name: NROS_DERIVED_SUBSCRIBED_TYPE_BOUNDS. It
    # is red on every build of this pin (phase6-W8b: "red only on the
    # upstream NROS_DERIVED_SUBSCRIBED_TYPE_BOUNDS line (phase-412 W4)"), a
    # second pass does not converge it, and until phase7-W1 it made this
    # recipe exit 1 on an image that had in fact linked. Same tolerance as
    # qemu-build (just/emulation.just). Any OTHER undelivered knob refuses.
    knob_log={{BOARD_BUILD_DIR}}/check-knob-delivery.log
    if ! python3 {{NROS_ROOT}}/scripts/check-knob-delivery.py {{BOARD_BUILD_DIR}} > "$knob_log" 2>&1; then
        cat "$knob_log"
        if grep '^  - ' "$knob_log" \
                | grep -qv '^  - NROS_DERIVED_SUBSCRIBED_TYPE_BOUNDS='; then
            echo ""
            echo "board-build: REFUSING this image -- a resolved knob did not reach the compile."
            echo "  The fragments on disk are correct and the delivered value is one pass behind."
            # (single quotes: inside a double-quoted string the backticks were a
            # command substitution, so every refusal RAN another full board build
            # to print this line, recursively, until killed; found 2026-09-25)
            echo '  Run `just board-build` again; the second pass converges.'
            exit 1
        fi
        echo "board-build: tolerating the known upstream SUBSCRIBED_TYPE_BOUNDS line (phase-412 W4); nothing else is red."
    else
        cat "$knob_log"
    fi
    # Pass the build dir through: a nested `just` starts a FRESH invocation and
    # does NOT inherit a `BOARD_BUILD_DIR=` override from the outer one, so a
    # bare `just board-size` here reported on `build-board` no matter which
    # directory was actually built. With `BOARD_BUILD_DIR=build-cyclone` and no
    # build-board present that surfaced as `ninja: error: unknown target
    # 'rom_report'` -- an error about the report, from a directory nobody built.
    just BOARD_BUILD_DIR={{BOARD_BUILD_DIR}} board-size
    # phase13-D5: the image against the priority plan it was derived from.
    just BOARD_BUILD_DIR={{BOARD_BUILD_DIR}} priority-check

# phase13-D5: hold the board image to the priority plan nano-ros derived for
# it (nano-ros RFC-0079): `nros codegen entry` records the plan and the tier
# priorities in <build>/nros_priority_plan.json; nano-ros's checker resolves
# the band again from the image's .config and compares, and compares the
# generated entry's tier table. With board=1 it also reads the supervisor
# record of the running board over SWD (the priorities the kernel gave the
# spin thread, the reaction thread and zenoh-pico's tasks at the first spin)
# and fails unless they agree with the plan.
#
# Check the board image (and with board=1 the running board) against its derived priority plan.
priority-check board="0":
    #!/usr/bin/env bash
    set -euo pipefail
    b="{{BOARD_BUILD_DIR}}"
    echo "priority-check: $b"
    python3 "{{NROS_ROOT}}/scripts/check-tier-priority-plan-image.py" --derived-plan \
        "$b/nros_priority_plan.json" "$b/zephyr/.config" "$b/zephyr_entry_nros_main_generated.cpp"
    python3 - "$b/nros_priority_plan.json" <<'PY'
    import json, sys
    r = json.load(open(sys.argv[1]))
    p = r["plan"]
    print(f"  plan: transport {p['reserved'].get('transport')}, pool.app {p['app']} ({p['source']})")
    for t in r["tiers"]:
        print(f"  tier {t['name']}: {t['priority']} ({t['origin']}; spin period {t['spin_period_us']} us)")
    for n in r["ranks"]:
        print(f"  rank {n['node']}: {n['priority']} (period {n['period_us']} us, deadline {n['deadline_us']} us)")
    PY
    if [ "{{board}}" = "1" ]; then
        source scripts/board-env.sh "{{NROS_ROOT}}" >/dev/null
        out="$(python3 tools/board/violations.py supervisor --elf "$b/zephyr/zephyr.elf")"
        printf '%s\n' "$out" | grep -E "priorit" || true
        printf '%s\n' "$out" | grep -q "priorities: AGREE with the plan" \
            || { echo "priority-check: the board's priorities do not agree with the plan" >&2; exit 1; }
    fi

# CARLA demo C5: the booth image, the gate image plus snippet island-booth
# (src/zephyr_entry/snippets/island-booth: CONFIG_ISLAND_LED=y, the MRM state on
# the board's RGB LED and a heartbeat on CAN LED0; C6: CONFIG_ISLAND_BUTTONS=y,
# SW1/SW2 recorded for the act; rtss-work-2026-demo:docs/design/carla-island-demo.md
# section 3),
# into build-board-booth. build-board, the gate image, is not touched.
#
# Build the booth image (LEDs and buttons on) into build-board-booth.
board-build-booth:
    ISLAND_BOARD_SNIPPETS="island-booth ${ISLAND_BOARD_SNIPPETS:-}" just BOARD_BUILD_DIR=build-board-booth board-build

# phase15-S4: the floor's fault-injection image, the gate image plus snippet
# island-floor-inject (src/zephyr_entry/snippets/island-floor-inject:
# CONFIG_ISLAND_DEBUG_FLOOR_INJECT=y, the three SWD words of
# violations.py floor-inject), into build-board-floor-inject. Test only:
# build-board, the gate image, carries none of the words.
#
# Build the floor fault-injection image into build-board-floor-inject.
board-build-floor-inject:
    ISLAND_BOARD_SNIPPETS="island-floor-inject ${ISLAND_BOARD_SNIPPETS:-}" just BOARD_BUILD_DIR=build-board-floor-inject board-build

# CARLA demo C6: the on-site check of SW1/SW2 on a running booth image. Attaches
# over SWD (no halt, no reflash) and prints every pad edge (PGPDI, no firmware
# in between) and every press the island records (island_button_record, with
# accepted/ignored and the handler's state), live, until Ctrl-C. Nothing else
# may hold the probe (no act running).
#
# Watch SW1/SW2 live on the board running the booth image (Ctrl-C to stop).
board-buttons elf="build-board-booth/zephyr/zephyr.elf":
    python3 tools/board/board_buttons.py watch --elf {{elf}}

# phase9-U3: the spin-latency diagnostic image (docs/tracing.md section 9,
# tools/diag/README.md). Applies the two diag patches to the
# submodules, builds into build-board-diag (BOARD_DIAG_BUILD_DIR) with
# CONFIG_ISLAND_SPIN_DIAG and CONFIG_NROS_ZENOH_SERIAL_ISR_STATS (plus any
# CONFIG_X=value given here), and reverts the patches on any exit. build-board
# is not touched; never flash this image for a gate run.
#
# Build the spin-diag board image into build-board-diag (patches reverted after).
board-build-diag *conf:
    ISLAND_NROS_ROOT="{{NROS_ROOT}}" tools/diag/build-diag.sh {{conf}}

# Flash the island. pyocd via MCU-Link; the runner comes from the board itself.
#
# WARNING: never `pyocd erase --chip` on this part. pyocd's pflash region spans
# 0x00400000-0x007FFFFF, which INCLUDES the 176 KB reserved for sBAF and HSE
# firmware. `west flash` sector-erases only what it writes, which is safe.
#
# Flash the island to the board (MCU-Link + pyocd).
board-flash:
    #!/usr/bin/env bash
    set -e
    source scripts/board-env.sh "{{NROS_ROOT}}"
    west flash -d {{BOARD_BUILD_DIR}} -r pyocd

# 320 KiB SRAM total for .data + .bss + heap + every stack.
#
# RAM/flash footprint — the number that decides whether this fits at all.
board-size:
    #!/usr/bin/env bash
    set -e
    source scripts/board-env.sh "{{NROS_ROOT}}"
    # A missing or unconfigured build dir makes ninja complain that `rom_report`
    # is an unknown target, which reads as "this build cannot produce a report"
    # rather than "there is no build here". Say the true thing.
    if [ ! -f "{{BOARD_BUILD_DIR}}/build.ninja" ]; then
        echo "board-size: no configured build at {{BOARD_BUILD_DIR}}" >&2
        echo "board-size: run 'just board-build' first (or pass BOARD_BUILD_DIR=<dir>)" >&2
        exit 1
    fi
    # The image first, and fatally: the report targets depend on zephyr.elf and
    # relink it (the cargo step is always out of date), so a link error must
    # not hide behind the advisory reports below.
    west build -d {{BOARD_BUILD_DIR}} > "{{BOARD_BUILD_DIR}}/board-size-link.log" 2>&1 \
        || { tail -40 "{{BOARD_BUILD_DIR}}/board-size-link.log"; echo "board-size: the image does not link" >&2; exit 1; }
    # The reports are ADVISORY (phase9-U2). Zephyr's size_report needs
    # `anytree`, which the workspace venv this repo provisions does not carry
    # (requirements-base.txt lists it; the nros provisioning installs a
    # subset; nano-ros issue 1870, after the pin: `--create` installs it and
    # setup warns), so both reports fail with ModuleNotFoundError until it is
    # installed by hand (docs/demo-runbook.md section 5).
    # The `| tail -20` this used to end in hid that (no pipefail), so the
    # traceback scrolled past and the recipe exited 0. A report failure is
    # printed, named, and does not fail board-build; the linker's own
    # "Memory region" table above is the footprint of record.
    for rep in rom_report ram_report; do
        echo "-- $rep --"
        log="{{BOARD_BUILD_DIR}}/board-size-$rep.log"
        if west build -d {{BOARD_BUILD_DIR}} -t "$rep" > "$log" 2>&1; then
            tail -20 "$log"
        else
            why="$(grep -E 'Error|error:' "$log" | grep -v '^FATAL ERROR' | tail -1)"
            echo "board-size: $rep failed (advisory, the image is fine): ${why:-see $log}"
            echo "board-size:   the full output is in $log"
        fi
    done

# Board DTS puts zephyr,console on lpuart2. Ctrl-A k to quit screen.
#
# Console over the DCD-LZ adapter's FTDI header.
board-console port="/dev/ttyUSB0" baud="115200":
    screen {{port}} {{baud}}

# Wipe the board build tree.
board-clean:
    rm -rf {{BOARD_BUILD_DIR}}

# ── Run guards (trace-native) ───────────────────────────────────────────────
# Refuse to double-start the island: a second copy collides with the first
# one's ports and participant. Stale pgid files are cleaned up.
[private]
_not-running file label:
    #!/usr/bin/env bash
    pg=$(cat {{file}} 2>/dev/null) || exit 0
    if kill -0 -- -"$pg" 2>/dev/null; then
        echo "{{label}} already running (pgid $pg) -- stop it first"; exit 1
    fi
    rm -f {{file}}

[private]
_island-image-check target:
    #!/usr/bin/env bash
    if [ "{{target}}" = "zephyr" ]; then
        [ -x ./build-zephyr/zephyr/zephyr.exe ] || { echo "no zephyr image — run: just zephyr-build"; exit 1; }
    else
        [ -x ./{{BUILD_DIR}}/src/native_entry/native_entry ] || { echo "no native image — run: just build"; exit 1; }
    fi

# The zephyr island's cyclone profile is COMPILE-TIME: env CYCLONEDDS_URI
# never reaches zephyr.exe (native_sim getenv sees no host environment —
# nano-ros issue 0367). It is baked via CONFIG_NROS_CYCLONE_CONFIG_XML in
# src/native_sim_entry/prj-cyclonedds.conf; edit there + `just zephyr-build`.

# The CI job locally (.github/check-contracts.sh): `play_launch check` on every
# contract with check.yml's pinned wheel, in build/l3-ci, under env -i.
# Was `l3-check` before phase 14; the alias stays.
#
# play_launch check on every contract with the CI's pinned wheel (build/l3-ci). phase8-W3
contract-check:
    #!/usr/bin/env bash
    set -eo pipefail
    ver="$(sed -n 's/^ *PLAY_LAUNCH_VERSION: *"\(.*\)"/\1/p' .github/workflows/check.yml)"
    venv=build/l3-ci/play_launch-$ver
    # play_launch[humble] from the GitHub release's assets until PyPI has the
    # per-distribution projects (check.yml says why); a local wheelhouse
    # (PLAY_LAUNCH_WHEELHOUSE/play_launch-<ver>) wins.
    links="https://github.com/NEWSLabNTU/play_launch/releases/expanded_assets/v$ver"
    wh="${PLAY_LAUNCH_WHEELHOUSE:-}"
    [ -n "$wh" ] && [ -d "$wh/play_launch-$ver" ] && links="$wh/play_launch-$ver"
    [ -x $venv/bin/play_launch ] || { python3 -m venv $venv && $venv/bin/pip install -q "play_launch[humble]==$ver" --find-links "$links"; }
    env -i HOME="$HOME" USER="$USER" PATH=/usr/bin:/bin PLAY_LAUNCH="$PWD/$venv/bin/play_launch" \
        bash -c 'source /opt/ros/humble/setup.bash && exec .github/check-contracts.sh'

alias l3-check := contract-check

# phase15-S3: the supervisor's standstill verdicts on the host (route 2 and
# route 3: met, missed, stale sample; src/zephyr_entry/src/
# island_supervisor_judge.h) and the record decoder against its layout.
supervisor-test:
    mkdir -p build/tests
    cc -std=c11 -Wall -Wextra -Werror -o build/tests/supervisor_judge tests/supervisor/test_judge.c
    build/tests/supervisor_judge
    python3 tools/board/violations.py selftest

import 'just/emulation.just'
import 'just/tracing.just'
import 'just/board-peer.just'
