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
# Two stages, split where a source edit stops invalidating the install:
#
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

ARG BASE_IMAGE=ros:humble-ros-base-jammy

# ===========================================================================
FROM ${BASE_IMAGE} AS autoware

SHELL ["/bin/bash", "-o", "pipefail", "-c"]
ENV DEBIAN_FRONTEND=noninteractive LANG=C.UTF-8 LC_ALL=C.UTF-8

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

# --- rmw_zenoh_cpp from ROS apt, pinned ---------------------------------------
# The localrepo ships no RMW but Cyclone. 0.1.9 is what phase 7 proved against
# the island's zenoh-pico. ROS apt serves only the newest build of a version,
# so the exact strings below are what it served on 2026-09-28; when a newer
# 0.1.9 rebuild replaces them the build fails HERE, loudly, and the ARGs are
# the one place to move. The host this was measured on runs
# 0.1.9-1jammy.20260723.022609 of rmw_zenoh_cpp (same source, older rebuild).
ARG RMW_ZENOH_VERSION=0.1.9-1jammy.20260907.200640
ARG ZENOH_VENDOR_VERSION=0.1.9-1jammy.20260723.020902
RUN apt-get update && apt-get install -y --no-install-recommends \
        ros-humble-rmw-zenoh-cpp=${RMW_ZENOH_VERSION} \
        ros-humble-zenoh-cpp-vendor=${ZENOH_VENDOR_VERSION} \
    && apt-mark hold ros-humble-rmw-zenoh-cpp ros-humble-zenoh-cpp-vendor \
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
ARG AW_RELEASE=1.5.0-2
ARG AW_DEB=autoware-localrepo-1-5-0_1.5.0-2ubuntu2204_all.deb
ARG AW_SHA256=f8e2d1d2f43d7a7186b7fbcd391b473783d1ef9cd131a12bfea898255d450acb
ARG AW_URL=https://github.com/NEWSLabNTU/autoware-localrepo/releases/download
RUN --mount=type=cache,target=/var/cache/autoware-localrepo,sharing=locked \
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

COPY demo/l3/container/entrypoint.sh /usr/local/bin/entrypoint.sh
COPY demo/l3/container/bin/ /usr/local/bin/
RUN chmod +x /usr/local/bin/entrypoint.sh /usr/local/bin/l3-*

# The middleware is set HERE, not in a sourced script (autosdv's lesson: a
# shell that sources the workspace and nothing else falls back to the
# default RMW, silently). NEVER source /opt/autoware/1.5.0/autoware-env.bash
# in this image: it hard-sets RMW_IMPLEMENTATION=rmw_cyclonedds_cpp.
# The zenoh session dials the host's router at tcp/localhost:7447 (rmw_zenoh's
# default) -- the container runs on the host network and starts no router.
ENV RMW_IMPLEMENTATION=rmw_zenoh_cpp \
    ROS_DOMAIN_ID=10 \
    L3_MAP=/opt/demo/map/sample-map-planning \
    L3_WS=/opt/demo_ws/install

ENTRYPOINT ["/usr/local/bin/entrypoint.sh"]
CMD ["bash"]
