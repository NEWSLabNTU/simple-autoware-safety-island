#!/usr/bin/env python3
"""Read the island's RAM trace buffer off a running target (phase8-W17).

  readout.py --target board --elf <zephyr.elf> --out <dir>/island.trace
  readout.py --target qemu  --elf <zephyr.elf> --out <dir>/island.trace --monitor <unix socket>
  readout.py ... --dry-run          print what would be read, touch nothing

Every address comes from the ELF's symbol table (pyelftools), never a
literal: `ram_tracing` (the buffer; Zephyr's RAM backend), the heartbeat
counter and its last uptime, and the trace window's counters
(island_trace.h): triggered, trigger uptime, markers the record policy
dropped, pre-trigger records written and not flushed; on the board also the
marker self-cost statistics (DWT). The core is halted for the read, so the
buffer and the counters are one instant, then resumed.

  board  pyocd's Python API on the MCU-Link (target s32k344), attach mode: no
         reset. NOT EXERCISED: W17 did not touch the board (W10 held it).
         It uses the calls experiments/serial-interop/w2/tools/swd_poll.py
         ran against this board (session_with_chosen_probe, read32,
         read_memory_block8) plus halt/resume.
  qemu   the QEMU human monitor on a unix socket (`-monitor
         unix:<sock>,server,nowait`): `stop`, `pmemsave`, `xp /1wx`, `cont`.
         Exercised against the QEMU island (tools/timeline/run-board.sh
         --target qemu).

The raw buffer is written beside the output as <out>.raw, and <out> is that
buffer wrapped in the native_sim dump's header (island_trace.py wrap), with
the heartbeat counter as the "emitted" count, so `island_trace.py check` can
tell a full buffer from a short act. <out>.readout.json has every value read.
"""
import argparse
import json
import os
import re
import socket
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, os.path.join(ROOT, "src/safety_island_tracing"))
import island_trace  # noqa: E402

BUFFER = "ram_tracing"
WORDS = [
    "island_trace_hb_seq", "island_trace_hb_last_uptime_ms",
    "island_trace_triggered", "island_trace_trigger_uptime_ms",
    "island_trace_filtered", "island_trace_pre_n", "island_trace_pre_lost",
    "island_trace_cost_n", "island_trace_cost_min", "island_trace_cost_max", "island_trace_cost_empty",
]


def symbols(elf, names):
    from elftools.elf.elffile import ELFFile
    out = {}
    with open(elf, "rb") as f:
        e = ELFFile(f)
        st = e.get_section_by_name(".symtab")
        if st is None:
            sys.exit(f"readout: {elf} has no symbol table")
        for s in st.iter_symbols():
            if s.name in names and s.name not in out:
                out[s.name] = (s["st_value"], s["st_size"])
    return out


class Qemu:
    """The QEMU human monitor over a unix socket."""

    def __init__(self, path):
        self.s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.s.connect(path)
        self.s.settimeout(10)
        self._until_prompt()

    def _until_prompt(self):
        buf = b""
        while not buf.rstrip().endswith(b"(qemu)"):
            chunk = self.s.recv(65536)
            if not chunk:
                raise RuntimeError("qemu monitor closed")
            buf += chunk
        return buf.decode("ascii", "replace")

    def cmd(self, line):
        self.s.sendall(line.encode() + b"\n")
        return self._until_prompt()

    def halt(self):
        self.cmd("stop")

    def resume(self):
        self.cmd("cont")

    def read32(self, addr):
        out = self.cmd(f"xp /1wx {addr:#x}")
        m = re.search(r"[0-9a-fA-F]+:\s+0x([0-9a-fA-F]+)", out)
        if not m:
            raise RuntimeError(f"qemu monitor: cannot parse {out!r}")
        return int(m.group(1), 16)

    def read_block(self, addr, size, path):
        tmp = os.path.abspath(path)
        self.cmd(f'pmemsave {addr:#x} {size} "{tmp}"')
        for _ in range(50):  # pmemsave is synchronous; the file is there after the prompt
            if os.path.exists(tmp) and os.path.getsize(tmp) == size:
                break
            time.sleep(0.1)
        return open(tmp, "rb").read()

    def close(self):
        self.s.close()


class Board:
    """pyocd on the MCU-Link, attach mode. NOT EXERCISED (see the module doc)."""

    def __init__(self, target="s32k344"):
        from pyocd.core.helpers import ConnectHelper
        self.session = ConnectHelper.session_with_chosen_probe(
            target_override=target, connect_mode="attach", options={"frequency": 4000000})
        self.session.open()
        self.t = self.session.board.target

    def halt(self):
        self.t.halt()

    def resume(self):
        self.t.resume()

    def read32(self, addr):
        return self.t.read32(addr)

    def read_block(self, addr, size, path):
        data = bytes(self.t.read_memory_block8(addr, size))
        open(path, "wb").write(data)
        return data

    def close(self):
        self.session.close()


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--target", choices=["board", "qemu"], required=True)
    ap.add_argument("--elf", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--monitor", help="qemu: the monitor's unix socket")
    ap.add_argument("--zephyr", default="4.4")
    ap.add_argument("--no-resume", action="store_true", help="leave the core halted after the read")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()
    syms = symbols(a.elf, set(WORDS) | {BUFFER})
    if BUFFER not in syms:
        sys.exit(f"readout: {a.elf} has no {BUFFER} (tracing is not in this image)")
    addr, size = syms[BUFFER]
    plan = [f"read {BUFFER} @ {addr:#010x}, {size} B"] + \
        [f"read32 {n} @ {syms[n][0]:#010x}" for n in WORDS if n in syms]
    print(f"readout: {a.target}, {a.elf}")
    for p in plan:
        print(f"readout:   {p}")
    if a.dry_run:
        print("readout: --dry-run, nothing read")
        return 0
    if a.target == "qemu":
        if not a.monitor:
            sys.exit("readout: --target qemu needs --monitor <socket>")
        dev = Qemu(a.monitor)
    else:
        dev = Board()
    raw = a.out + ".raw"
    os.makedirs(os.path.dirname(os.path.abspath(a.out)), exist_ok=True)
    t0 = time.monotonic()
    dev.halt()
    try:
        vals = {n: dev.read32(syms[n][0]) for n in WORDS if n in syms}
        data = dev.read_block(addr, size, raw)
    finally:
        if not a.no_resume:
            dev.resume()
        dev.close()
    took = time.monotonic() - t0
    if len(data) != size:
        sys.exit(f"readout: read {len(data)} of {size} B")
    vals["halted_s"] = round(took, 3)
    json.dump(dict(target=a.target, elf=os.path.abspath(a.elf), buffer_addr=addr, buffer_size=size,
                   symbols={n: syms[n][0] for n in syms}, values=vals),
              open(a.out + ".readout.json", "w"), indent=1)
    print("readout: " + ", ".join(f"{k.replace('island_trace_', '')}={v}" for k, v in vals.items()))
    island_trace.wrap(raw, a.out, a.zephyr, vals.get("island_trace_hb_seq", 0),
                      vals.get("island_trace_hb_last_uptime_ms", 0))
    if "island_trace_triggered" in vals and not vals["island_trace_triggered"]:
        print("readout: WARNING the trace window never triggered: the buffer holds the provenance only")
    return 0


if __name__ == "__main__":
    sys.exit(main())
