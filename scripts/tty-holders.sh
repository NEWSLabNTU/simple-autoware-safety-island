#!/usr/bin/env bash
# The pids that hold a device open, space-separated with a leading space
# (fuser's stdout format), or nothing.
#
#   scripts/tty-holders.sh <device>
#
# fuser stat()s every open file of every process to compare device and
# inode. Under a stray filesystem walk over a slow mount (a `find /` into
# the sshfs NAS holds ~2,000 directory fds there) each of those stats
# blocks, and fuser on the gateway tty took over 10 minutes (CARLA demo
# C6, trap 19). This reads /proc/<pid>/fd/* with readlink only, which
# names the target without touching its filesystem: a holder of the tty
# is found the same way, a walk elsewhere costs nothing.
set -u
exec python3 -I -c '
import os, sys
dev = os.path.realpath(sys.argv[1])
out = []
for pid in filter(str.isdigit, os.listdir("/proc")):
    try:
        fds = os.listdir(f"/proc/{pid}/fd")
    except OSError:
        continue
    for fd in fds:
        try:
            if os.readlink(f"/proc/{pid}/fd/{fd}") == dev:
                out.append(pid)
                break
        except OSError:
            pass
sys.stdout.write("".join(" " + p for p in out))
' "$1"
