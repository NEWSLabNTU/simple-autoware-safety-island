# syntax=docker/dockerfile:1.6
#
# phase8-W3: Autoware 1.5.0's planning simulator on rmw_zenoh_cpp, domain 10,
# built from the NEWSLabNTU autoware-localrepo, with the demo's host_ws overlay
# (stock MRM disabled, availability output renamable) and the takeover_demo
# package. Design: docs/roadmap/phase-8-rtss-work-demo.md D2, D3;
# docs/design/rtss-work-2026/brief-A-container.md.
#
# Build from the REPOSITORY ROOT (the context is filtered by
# Dockerfile.dockerignore next to this file):
#
#   just l3-container
#   # = docker build -f demo/l3/container/Dockerfile -t sai-l3-autoware:1.5.0 .
#
# Three stages, split where a source edit stops invalidating the install:
#
#   rclcpp     rclcpp 16.0.19 + one executor patch, built alone (W11).
#   autoware   ROS base + rmw_zenoh_cpp (pinned) + the localrepo install.
#              Keyed on nothing in this repository, so editing the overlay or
#              the takeover package never re-installs Autoware.
#   demo       the user, the entrypoint, play_launch, the overlay and the
#              takeover package. Cheap (about a minute).
#
# The references this copies rather than invents (autosdv@develop 6e7b709,
# docker/desktop/Dockerfile and setup/scripts/install-autoware-debian.sh):
# the aria2c parallel download with an inline sha256, the .deb in a BuildKit
# cache mount so a rebuild never re-downloads 1.85 GiB, the install and the
# purge of the pool in ONE RUN (a later rm only writes a whiteout), the RMW in
# the image ENV rather than in a sourced script, and the gosu entrypoint that
# bends a build-time user to the host's uid/gid.
#
# What it does NOT copy: the CUDA devel base (the planning simulator loads no
# TensorRT library; a stub satisfies the packaging), autoware-data (2 GB of
# models nothing here loads), TurboVNC (RViz runs on the host over zenoh; the
# container can also draw into the host's X/VNC display through the socket),
# and loopback multicast (zenoh does not scout).
#
# Two architectures (phase8-W21): amd64 (the demo host, measured) and arm64
# (the booth HPC, an NVIDIA Orin; UNBUILT AND UNTESTED as of 2026-09-29).
# BuildKit sets TARGETARCH; the stage that differs per architecture picks the
# localrepo .deb and the pinned rmw_zenoh build stamps from it, and fails on
# any other value. Nothing else in the image is architecture-specific: the
# base is a multi-arch index, the TensorRT stub is Architecture: all, the
# overlay is launch files and Python, play_launch has an aarch64 wheel.
#
#   docker build -f demo/l3/container/Dockerfile -t sai-l3-autoware:1.5.0 .
#       native: amd64 here, arm64 on the Orin (build it ON the Orin)
#   just l3-container-arm64
#       arm64 on an x86 host under QEMU binfmt (slow; nothing real-time)
#
# The arm64 path keeps the same stub as amd64 in place of CUDA/TensorRT: the
# image runs on the Orin's CPU only, exactly as the planning simulator runs
# here. demo/l3/ORIN.md has the feasibility evidence and the rehearsal
# checklist.

# The multi-arch INDEX digest of ros:humble-ros-base-jammy the amd64 image
# was built from (osrf/docker_images 20e3ba6, 2026-09-09; its amd64 variant
# carries ros-humble-rclcpp 16.0.19-1jammy.20260724). Pinned because the tag
# moves: ROS apt now serves rclcpp 16.0.21 on both architectures, and a
# rebuilt base would fail the rclcpp version check in the demo stage. The
# arm64 variant of this index comes from the same osrf revision and build
# day; its rclcpp version is not verified (the check will say).
ARG BASE_IMAGE=ros:humble-ros-base-jammy@sha256:1813d3c85d7f96ff7d3012d865204583255740182db5d0065f8f8cd029a83138

# ===========================================================================
# rclcpp 16.0.19 (the version ROS apt ships, checked below) with one patch:
# the executor holds a strong reference to every callback group's notify
# guard condition it put in its wait set (ros2/rclcpp#2445, open on Humble).
# behavior_path_planner destroys module callback groups when a new route
# arrives; in a component_container_mt another executor thread is inside
# rmw_wait on that guard condition, and on rmw_zenoh_cpp the freed object is
# written to (heap corruption, then an abort in malloc under glog's failure
# handler, which deadlocks) or locked (a stale mutex): the planner goes
# silent after a re-route (demo/l3/README.md, trap 2b). Built alone, dropped
# over the packaged library in the demo stage (dpkg-divert); the patch
# touches executor.cpp only, so the library's ABI is unchanged.
# Architecture-neutral: built from source for whatever TARGETARCH is. (The
# patch also applies cleanly to 16.0.21, whose executor.cpp is identical;
# neither 16.0.20 nor 16.0.21 fixes #2445, which is still open.)
FROM ${BASE_IMAGE} AS rclcpp
SHELL ["/bin/bash", "-o", "pipefail", "-c"]
ARG RCLCPP_VERSION=16.0.19
COPY demo/l3/container/patches/rclcpp-16.0.19-executor-keep-group-guard-conditions.patch /tmp/rclcpp.patch
RUN apt-get update && apt-get install -y --no-install-recommends git \
    && rm -rf /var/lib/apt/lists/* \
    && git clone -q --depth 1 --branch ${RCLCPP_VERSION} https://github.com/ros2/rclcpp.git /ws/src/rclcpp \
    && git -C /ws/src/rclcpp apply /tmp/rclcpp.patch \
    && source /opt/ros/humble/setup.bash && cd /ws \
    && colcon build --packages-select rclcpp --event-handlers console_direct- \
        --cmake-args -DCMAKE_BUILD_TYPE=RelWithDebInfo -DBUILD_TESTING=OFF > /tmp/build.log 2>&1 \
        || { tail -40 /tmp/build.log; exit 1; } \
    && strip --strip-debug /ws/install/rclcpp/lib/librclcpp.so

# ===========================================================================
FROM ${BASE_IMAGE} AS autoware

SHELL ["/bin/bash", "-o", "pipefail", "-c"]
ENV DEBIAN_FRONTEND=noninteractive LANG=C.UTF-8 LC_ALL=C.UTF-8

# Set by BuildKit from --platform (or the builder's own architecture). Empty
# under the legacy builder: the RUNs below then refuse to guess.
ARG TARGETARCH
RUN case "${TARGETARCH}" in amd64|arm64) ;; \
        *) echo "TARGETARCH='${TARGETARCH}': build with BuildKit for linux/amd64 or linux/arm64" >&2; exit 1;; \
    esac; \
    [ "$(dpkg --print-architecture)" = "${TARGETARCH}" ] \
    || { echo "base image is $(dpkg --print-architecture), TARGETARCH is ${TARGETARCH}" >&2; exit 1; }

# aria2 earns its place as in autosdv: the release host throttles per
# connection (autosdv measured wget 383 KB/s against aria2c 2905 KB/s on this
# exact URL). equivs builds the TensorRT stub below. gosu/sudo are the
# entrypoint's. The rest is what a person debugging the demo reaches for.
RUN apt-get update && apt-get install -y --no-install-recommends \
        aria2 ca-certificates equivs gosu sudo iproute2 procps psmisc \
        less python3-pip \
    && rm -rf /var/lib/apt/lists/*

# --- libnvinfer10: a stub, not TensorRT --------------------------------------
# ros-humble-autoware-launch-1-5-0 reaches autoware_tensorrt_common, cuda_utils
# and friends, which Depend on the UNVERSIONED libnvinfer10 (5 packages),
# libnvinfer-plugin10 (1) and libnvonnxparsers10 (3) -- counted in the pool's
# Packages file. None of the 68 composables the planning simulator loads links
# a TensorRT library (brief A, play_log), so the dependency is packaging only.
# The real runtime libs are 2.5-4.4 GB installed; this is 0.
# Both architectures: equivs builds it Architecture: all, which satisfies an
# arm64 Depends as well; the JetPack 6.2 pool depends on the same three
# unversioned names from the same five packages as the amd64 pool (W21,
# compared index to index). On the Orin, JetPack's real TensorRT lives on
# the HOST; this image neither sees nor needs it.
RUN mkdir /tmp/stub && cd /tmp/stub \
    && printf '%s\n' \
        'Section: misc' 'Priority: optional' 'Standards-Version: 3.9.2' \
        'Package: sai-nvinfer-stub' 'Version: 10.0.0-stub1' \
        'Provides: libnvinfer10, libnvinfer-plugin10, libnvonnxparsers10' \
        'Description: packaging stub for the planning simulator (no TensorRT)' \
        ' Autoware 1.5.0 debs depend on TensorRT runtime packages that the' \
        ' planning simulator never loads. See demo/l3/container/Dockerfile.' \
        > sai-nvinfer-stub.ctl \
    && equivs-build sai-nvinfer-stub.ctl >/dev/null \
    && dpkg -i sai-nvinfer-stub_*_all.deb \
    && cd / && rm -rf /tmp/stub

# --- rmw_zenoh_cpp 0.1.10 from ROS apt TESTING, pinned ------------------------
# The localrepo ships no RMW but Cyclone. NOT 0.1.9 (phase8-W11): 0.1.9's
# rmw_wait clears wait_set_data->triggered at the end of
# check_and_attach_condition() WITHOUT condition_mutex (a regression from the
# lock-order fix ros2/rmw_zenoh#1005, backported as #1015). A guard condition
# or a service that fires while rmw_wait is still attaching the rest of the
# wait set has its wakeup overwritten, and the thread sleeps in an untimed
# pthread_cond_wait for good: component containers that stop loading
# composables ("N composable(s) still constructing"). Upstream issue #1032,
# fix #1036, humble backport #1041, released in 0.1.10. Measured in
# demo/l3/README.md, trap 2a.
#
# 0.1.10 is in ros2-testing only (the main repo still serves 0.1.9 on
# 2026-09-29); the testing source is added for this RUN and removed in it.
# zenoh_cpp_vendor 0.1.10 vendors the same zenoh as 0.1.9 (the diff touches
# no zenoh version), so the host's 0.1.9 rmw_zenohd and the island's
# zenoh-pico talk to it unchanged. Exact strings: when a rebuild replaces
# them the build fails HERE, loudly, and the ARGs are the one place to move
# (once 0.1.10 syncs to main, drop the testing source).
#
# The build stamp differs per architecture (the buildfarm builds each on its
# own; ros2-testing jammy binary-{amd64,arm64}/Packages, read 2026-09-29).
# The testing source is the ros2 source with its URI changed; it names no
# architecture, so apt reads the TARGETARCH index (ports.ubuntu.com serves
# the Ubuntu side of an arm64 base; the ROS side is one host for both).
ARG RMW_ZENOH_VERSION_AMD64=0.1.10-1jammy.20260915.210859
ARG ZENOH_VENDOR_VERSION_AMD64=0.1.10-1jammy.20260915.201617
ARG RMW_ZENOH_VERSION_ARM64=0.1.10-1jammy.20260916.050325
ARG ZENOH_VENDOR_VERSION_ARM64=0.1.10-1jammy.20260916.042209
RUN case "${TARGETARCH}" in \
        amd64) rmw=${RMW_ZENOH_VERSION_AMD64}; vendor=${ZENOH_VENDOR_VERSION_AMD64};; \
        arm64) rmw=${RMW_ZENOH_VERSION_ARM64}; vendor=${ZENOH_VENDOR_VERSION_ARM64};; \
    esac \
    && sed 's#/ros2/ubuntu#/ros2-testing/ubuntu#' \
        /etc/apt/sources.list.d/ros2.sources > /etc/apt/sources.list.d/ros2-testing.sources \
    && apt-get update && apt-get install -y --no-install-recommends \
        ros-humble-rmw-zenoh-cpp="$rmw" \
        ros-humble-zenoh-cpp-vendor="$vendor" \
    && apt-mark hold ros-humble-rmw-zenoh-cpp ros-humble-zenoh-cpp-vendor \
    && rm /etc/apt/sources.list.d/ros2-testing.sources \
    && rm -rf /var/lib/apt/lists/*

# --- Autoware 1.5.0 from the localrepo ----------------------------------------
# One RUN, so the 1.9 GB pool the .deb unpacks never lands in a layer:
#   1. the .deb, into a cache mount (never committed), downloaded only when it
#      is missing or its sha256 is wrong; aria2c checks the hash inline;
#   2. dpkg it (writes the file: apt source + the priority-1001 pin);
#   3. autoware-ros-packages + config + theme: autoware-full minus
#      autoware-data (1.79 GB of ONNX models the planning simulator never
#      loads). NOT just ros-humble-autoware-launch-1-5-0, as brief A
#      proposed: its dependency closure is 249 of the 459 packages and
#      misses components the planning simulator loads by plugin name --
#      measured: sample_vehicle_description (the parse stops there), and the
#      AEB, collision detector, control validator, lanelet2 map visualizer,
#      motion velocity planner, operation-mode transition manager and path
#      smoother packages. The launch packages do not declare them.
#   4. purge the localrepo package: the pool is a second copy of what step 3
#      installed, and purging (rather than rm) keeps dpkg consistent and takes
#      the apt source and pin with it.
# setup-prerequisites.sh and activate-dds-config.sh are NOT run: the first
# installs ROS (present) and TensorRT (stubbed), the second configures
# CycloneDDS sysctls this image does not use.
#
# Per architecture (release 1.5.0-2, SHA256SUMS.txt): the ubuntu2204 .deb is
# the amd64 pool, the jetpack62 .deb the arm64 one (built on
# nvcr.io/nvidia/l4t-tensorrt:r10.3.0-devel, JetPack 6.2 / L4T r36.4, but
# installable on plain jammy arm64: the same 459 package names, 453 arm64 +
# 6 all, and every Depends name of the install set resolves against Ubuntu
# jammy arm64 + ROS apt + the stub; W21, from the pool's own Packages file).
# Both are "_all.deb" wrappers; the architecture is inside.
ARG AW_RELEASE=1.5.0-2
ARG AW_DEB_AMD64=autoware-localrepo-1-5-0_1.5.0-2ubuntu2204_all.deb
ARG AW_SHA256_AMD64=f8e2d1d2f43d7a7186b7fbcd391b473783d1ef9cd131a12bfea898255d450acb
ARG AW_DEB_ARM64=autoware-localrepo-1-5-0_1.5.0-2jetpack62_all.deb
ARG AW_SHA256_ARM64=e3187ca5a7e175aaabd239b5056d7ec1fb6eba92f6c232f8be67ee9958a6a064
ARG AW_URL=https://github.com/NEWSLabNTU/autoware-localrepo/releases/download
RUN --mount=type=cache,target=/var/cache/autoware-localrepo,sharing=locked \
    case "${TARGETARCH}" in \
        amd64) AW_DEB=${AW_DEB_AMD64}; AW_SHA256=${AW_SHA256_AMD64};; \
        arm64) AW_DEB=${AW_DEB_ARM64}; AW_SHA256=${AW_SHA256_ARM64};; \
    esac; \
    deb=/var/cache/autoware-localrepo/${AW_DEB}; \
    if [ -f "$deb" ] && echo "${AW_SHA256}  $deb" | sha256sum -c --status; then \
        echo "localrepo: cached $deb (sha256 ok)"; \
    else \
        rm -f "$deb"; \
        echo "localrepo: downloading ${AW_URL}/${AW_RELEASE}/${AW_DEB}"; \
        aria2c -x 10 -s 10 -k 1M --console-log-level=warn --summary-interval=60 \
            --checksum=sha-256=${AW_SHA256} \
            --dir=/var/cache/autoware-localrepo --out=${AW_DEB} \
            "${AW_URL}/${AW_RELEASE}/${AW_DEB}"; \
    fi \
    && apt-get update \
    && apt-get install -y --no-install-recommends "$deb" \
    && apt-get update \
    && apt-get install -y --no-install-recommends \
        autoware-ros-packages-1-5-0 autoware-config-1-5-0 autoware-theme-1-5-0 \
    && apt-get purge -y autoware-localrepo-1-5-0 \
    && rm -rf /var/lib/apt/lists/* /opt/autoware/1.5.0/repo \
    && echo "localrepo: installed $(dpkg -l | grep -c -- '-1-5-0 ') packages suffixed -1-5-0"

# ===========================================================================
FROM autoware AS demo

# `just l3-container` prunes dangling images by this label only, never
# another project's on a shared docker host.
LABEL org.newslab.sai.image="l3-autoware"

# play_launch runs Autoware (>= 0.8.2; --container-mode observable) and is the
# contract checker. Pinned to what the host runs.
ARG PLAY_LAUNCH_VERSION=0.12.0
RUN pip3 install --no-cache-dir "play_launch==${PLAY_LAUNCH_VERSION}"

# --- the account the entrypoint hands over to (autosdv's model) ---------------
# Created at 1000 and bent to HOST_UID/HOST_GID at start-up by the entrypoint,
# because `docker run --user` gives a uid with no passwd entry, no $HOME and no
# ~/.ros. dialout (serial), video (/dev/dri) and plugdev (USB buttons), and
# passwordless sudo: a disposable single-user demo container with no secrets.
# -l: no lastlog entry (a large host uid makes a multi-GB sparse lastlog).
ARG USERNAME=aw
RUN (getent group 1000 >/dev/null || groupadd -g 1000 ${USERNAME}) \
    && useradd -l -u 1000 -g 1000 -m -s /bin/bash -G dialout,video,plugdev ${USERNAME} \
    && echo "${USERNAME} ALL=(ALL) NOPASSWD:ALL" > /etc/sudoers.d/${USERNAME} \
    && chmod 0440 /etc/sudoers.d/${USERNAME}

# --- the demo's sources: overlay + takeover package + map ---------------------
# /opt/demo_ws/src/tier4_system_launch is the island's shadow of the stock
# launch package: the MRM operator and handler are commented out (the island
# is the only MRM path), and the availability converter's output topic is an
# argument so the takeover package's gate can sit in front of the island.
COPY demo/host_ws/src/ /opt/demo_ws/src/
COPY demo/l3/takeover_demo/ /opt/demo_ws/src/takeover_demo/
RUN source /opt/ros/humble/setup.bash \
    && source /opt/autoware/1.5.0/setup.bash \
    && cd /opt/demo_ws \
    && colcon build --merge-install --event-handlers console_direct- \
    && rm -rf build log
COPY demo/map/sample-map-planning/ /opt/demo/map/sample-map-planning/

# The patched rclcpp (stage `rclcpp` above), over the packaged one. Fails
# loudly if ROS apt has moved rclcpp past the version the patch was made on.
ARG RCLCPP_VERSION=16.0.19
COPY --from=rclcpp /ws/install/rclcpp/lib/librclcpp.so /tmp/librclcpp.so
RUN dpkg-query -W -f '${Version}' ros-humble-rclcpp | grep -q "^${RCLCPP_VERSION}-" \
    && dpkg-divert --add --rename --divert /opt/ros/humble/lib/librclcpp.so.distrib /opt/ros/humble/lib/librclcpp.so \
    && install -m 0644 /tmp/librclcpp.so /opt/ros/humble/lib/librclcpp.so && rm /tmp/librclcpp.so

COPY demo/l3/container/entrypoint.sh /usr/local/bin/entrypoint.sh
COPY demo/l3/container/bin/ /usr/local/bin/
RUN chmod +x /usr/local/bin/entrypoint.sh /usr/local/bin/l3-*

# The middleware is set HERE, not in a sourced script (autosdv's lesson: a
# shell that sources the workspace and nothing else falls back to the
# default RMW, silently). NEVER source /opt/autoware/1.5.0/autoware-env.bash
# in this image: it hard-sets RMW_IMPLEMENTATION=rmw_cyclonedds_cpp.
# The zenoh session dials the host's router at tcp/localhost:7447 (rmw_zenoh's
# default) -- the container runs on the host network and starts no router.
#
# ZENOH_RUNTIME gives zenoh's Net runtime 8 worker threads instead of 1
# (phase8-W11). While Autoware's ~57 peer sessions all join at once, zenoh
# 1.8.0 (vendored by rmw_zenoh_cpp 0.1.9 and 0.1.10) can deadlock a session
# for good: an RX thread holds the routing ctrl_lock and parks in
# block_in_place (Gossip::link_states, p2p_peer hat) until a task on the Net
# runtime runs, while that runtime's ONLY worker waits for ctrl_lock to open
# the next gossiped link (eclipse-zenoh/zenoh#2581, fixed on main by #2779
# after 1.8.0; the PR names the single worker as the precondition). Seen
# here as play_launch frozen 0.2 s after "Registered 112 members" and as a
# container stuck in rclcpp::init -> z_liveliness_get. With more workers one
# is free to run the task unless all of them are waiting on ctrl_lock at
# once. Client mode (no gossip at all) also cured it but routes every
# message through the router: largest gaps of 0.54-0.92 s on the planner
# chain against 0.11-0.17 s as peers (demo/l3/README.md, trap 2c), too
# close to the island's HPC-loss rung.
ENV RMW_IMPLEMENTATION=rmw_zenoh_cpp \
    ROS_DOMAIN_ID=10 \
    ZENOH_RUNTIME="(net: (worker_threads: 8))" \
    L3_MAP=/opt/demo/map/sample-map-planning \
    L3_WS=/opt/demo_ws/install

ENTRYPOINT ["/usr/local/bin/entrypoint.sh"]
CMD ["bash"]
