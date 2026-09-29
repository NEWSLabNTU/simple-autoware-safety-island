#!/usr/bin/env python3
"""A minimal unprivileged SNTP responder for the native_sim island (phase8-W18).

The island stamps its commands from the wall clock once nano-ros has an epoch
(CONFIG_NROS_SNTP_EPOCH, nano-ros issue 0758), and it asks for that epoch
ONCE, at boot, before any component is constructed. native_sim's sockets are
offloaded to the host (NSOS), so the island reaches this responder at
127.0.0.1:<port>; port 123 would need root, hence a high port, which
CONFIG_NROS_SNTP_SERVER names ("127.0.0.1:12323").

It answers every request with this host's CLOCK_REALTIME. The recipes start
it in the background and then `exec` zephyr.exe, so its parent IS the island;
it exits once it is reparented, i.e. when the island has gone, however it was
stopped (demo-down, the timeline's stop-island.sh, Ctrl-C).

    python3 scripts/sntp-server.py [host:port]      # default 127.0.0.1:12323
"""
import os
import select
import socket
import struct
import sys
import time

NTP_DELTA = 2208988800  # 1900-01-01 -> 1970-01-01, seconds


def ntp_ts(t):
    sec = int(t)
    frac = int((t - sec) * (1 << 32)) & 0xFFFFFFFF
    return struct.pack("!II", (sec + NTP_DELTA) & 0xFFFFFFFF, frac)


def main():
    host, _, port = (sys.argv[1] if len(sys.argv) > 1 else "127.0.0.1:12323").rpartition(":")
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    s.bind((host, int(port)))
    print(f"sntp-server: answering on {host}:{port}", flush=True)
    parent = os.getppid()
    while os.getppid() == parent:
        if not select.select([s], [], [], 1.0)[0]:
            continue
        data, peer = s.recvfrom(512)
        rx = time.time()
        if len(data) < 48:
            continue
        vn = (data[0] >> 3) & 0x7
        # LI=0, VN=request's, mode 4 (server); stratum 1; poll; precision -20
        head = struct.pack("!BBbb", (vn << 3) | 4, 1, data[2], -20)
        # root delay, root dispersion, reference id "LOCL"
        head += struct.pack("!II", 0, 0) + b"LOCL"
        # reference ts, originate ts (= client's transmit), receive ts, transmit ts
        pkt = head + ntp_ts(rx) + data[40:48] + ntp_ts(rx) + ntp_ts(time.time())
        s.sendto(pkt, peer)
        print(f"sntp-server: answered {peer[0]}:{peer[1]} at {rx:.6f}", flush=True)


if __name__ == "__main__":
    main()
