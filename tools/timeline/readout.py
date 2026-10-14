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
         reset. Exercised on the board by phase8-W8 (13 acts, the core
         halted 0.18-0.23 s per read). It uses the calls experiments/serial-interop/w2/tools/swd_poll.py
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

phase9-W4: in the same halt, the nano-ros violation record
(`NROS_VIOLATION_RECORD`) and the handler's arming words, when the image has
them; decoded by tools/timeline/violations.py into violations.txt (and the
raw record violations.bin) in the output's directory, so every act's run
directory carries the board's own violation readout beside its trace.

phase9-U1: in the same halt, zenoh-pico's serial counters
(`_z_zephyr_serial_stats`) into serial.txt and the nano-ros boot record
(`NROS_BOOT_REPORT`: heap and arena, at FirstSpin and running) into
bootrec.txt, decoded by the pinned nano-ros scripts/read-boot-report.py.
`--serial-only` reads the serial counters alone, attach, no halt, into
<out>.json: run-board.sh takes one just before the act, so serial.txt
can say which overruns and bad frames fell inside the act (end read minus
act-start snapshot) and which came before it.

phase9-C4: in the same halt, the island's assert record
(`island_assert_record`, src/zephyr_entry/src/assert_record.c). When an
assert has failed, assert.txt in the output's directory names its file and
line (the file string resolved from the ELF), its uptime and context, and
any nested assert that fired while it was being handled. `--assert-only`
reads the record alone (attach, halted for the read) and prints it, for a
board that stopped outside an act.

phase9-W2: `--rearm-only` re-arms the trace window for the next act on the
same boot (board): it writes 1 into `island_trace_rearm` (attach, no halt)
and waits for the image to clear it, which the next heartbeat tick does
after resetting the buffer, writing the provenance again and clearing the
trigger (src/safety_island_tracing/include/island_trace.h, "RE-ARMING").
The re-armed window opens at the first take of the guarded input after it,
so re-arm with the HPC down, after the previous act's readout and teardown
(tools/timeline/run-board.sh --keep-boot does it at its start). Every full
read also reports the window's re-arm count (`rearms`, 0 = the first window
since boot) and the uptime of the last re-arm.

CARLA demo (C5 trace margin): `--rearm-only --wait-go` attaches, prints
`re-arm ready` and writes the word only when a line arrives on stdin (EOF
cancels, exit 3). scenario.py starts it when the ego drives and sends the
line a few seconds before the ODD exit, so the window opens at the act
rather than a pyocd start-up (0.5 s warm, 5 s cold, far more under I/O
load) after the instant asked for.

CARLA demo C6 (the board's buttons, RB_TRIGGER=board): `--rearm-only
--buttons` stays attached after the re-arm as the act's button bridge
(tools/timeline/board_buttons.py): it prints a line per SW1/SW2 press the
island records and takes `inject sw1|sw2 [ticks]` and `quit` on stdin, so
the re-arm and the buttons share one pyocd session.
"""
import argparse
import json
import os
import re
import socket
import struct
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, os.path.join(ROOT, "src/safety_island_tracing"))
import island_trace  # noqa: E402
import violations  # noqa: E402

BUFFER = "ram_tracing"
WORDS = [
    "island_trace_hb_seq", "island_trace_hb_last_uptime_ms",
    "island_trace_triggered", "island_trace_trigger_uptime_ms",
    "island_trace_filtered", "island_trace_pre_n", "island_trace_pre_lost",
    "island_trace_cost_n", "island_trace_cost_min", "island_trace_cost_max", "island_trace_cost_empty",
    "island_trace_rearms", "island_trace_rearm_uptime_ms",
]
REARM = "island_trace_rearm"

# zenoh-pico src/system/zephyr/network.c, `_z_zephyr_serial_stats_t`, all u32
SERIAL = "_z_zephyr_serial_stats"
SERIAL_FIELDS = ["rx_bytes", "rx_frames", "rx_bad_frames", "rx_partial", "overruns", "ring_overflows",
                 "ring_high_water", "tx_bytes", "tx_frames", "tx_busy_cycles", "framing_errors",
                 "noise_errors", "parity_errors", "rx_wakes"]
# the counters that mean a lost or damaged frame (ring_high_water is a level, the rest are volume)
SERIAL_ERRORS = ["rx_bad_frames", "overruns", "ring_overflows", "framing_errors", "noise_errors",
                 "parity_errors"]
BOOTREC = "NROS_BOOT_REPORT"
BOOTREC_TOOL = os.path.join(ROOT, "third-party/nano-ros/scripts/read-boot-report.py")
# src/zephyr_entry/src/assert_record.c, `struct island_assert_record`, all 32-bit
ASSERT = "island_assert_record"
ASSERT_FIELDS = ["magic", "count", "file", "line", "uptime_ms", "in_isr", "nested_file", "nested_line"]
ASSERT_MAGIC = 0x54525341


def serial_decode(blob):
    n = min(len(blob) // 4, len(SERIAL_FIELDS))
    return dict(zip(SERIAL_FIELDS, struct.unpack_from(f"<{n}I", blob)))


def serial_text(end, pre=None):
    """serial.txt: the counters at the readout and, with the act-start
    snapshot, how many of the error counters moved during the act."""
    lines = [f"serial counters ({SERIAL}) at the readout, after the act:",
             "  " + " ".join(f"{k}={v}" for k, v in end.items())]
    errs = {k: end[k] for k in SERIAL_ERRORS if k in end}
    if pre is None:
        lines.append("  no act-start snapshot: errors since boot " +
                     " ".join(f"{k}={v}" for k, v in errs.items()))
        lines.append(f"  in the act: unknown; since boot: overruns={errs.get('overruns', 0)} "
                     f"bad_frames={errs.get('rx_bad_frames', 0)}")
    else:
        d = {k: end[k] - pre.get(k, 0) for k in errs}
        lines.append("  at the act's start: " + " ".join(f"{k}={pre.get(k, 0)}" for k in errs))
        lines.append("  during the act:     " + " ".join(f"{k}={v}" for k, v in d.items()))
        lines.append(f"  in the act: overruns={d.get('overruns', 0)} bad_frames={d.get('rx_bad_frames', 0)}"
                     f"; before it: overruns={pre.get('overruns', 0)} bad_frames={pre.get('rx_bad_frames', 0)}"
                     f"; ring high water {end.get('ring_high_water', 0)} B")
    return "\n".join(lines) + "\n"


def bootrec_text(elf, dump):
    """bootrec.txt: the pinned decoder's report of the dump (it prints the
    heap at FirstSpin and the running peak, and the arena use)."""
    r = subprocess.run([sys.executable, BOOTREC_TOOL, elf, dump], capture_output=True, text=True)
    out = r.stdout + "".join(l + "\n" for l in r.stderr.splitlines() if "self-test" not in l)
    return out if out.strip() else f"read-boot-report.py exit {r.returncode}, no output\n"


def elf_string(elf, addr, limit=256):
    """The NUL-terminated string at a target address, read from the ELF's
    loadable sections (__FILE__ strings live in flash)."""
    from elftools.elf.elffile import ELFFile
    if not addr:
        return None
    with open(elf, "rb") as f:
        for sec in ELFFile(f).iter_sections():
            a, n = sec["sh_addr"], sec["sh_size"]
            if sec["sh_type"] == "SHT_PROGBITS" and a <= addr < a + n and sec["sh_flags"] & 2:
                data = sec.data()[addr - a:addr - a + limit]
                return data.split(b"\0", 1)[0].decode("ascii", "replace")
    return f"<{addr:#010x}: not in the ELF>"


def assert_text(elf, blob):
    """assert.txt, or None when no assert has failed (magic unset)."""
    n = min(len(blob) // 4, len(ASSERT_FIELDS))
    r = dict(zip(ASSERT_FIELDS, struct.unpack_from(f"<{n}I", blob)))
    if r.get("magic") != ASSERT_MAGIC:
        return None
    lines = [f"ASSERT {elf_string(elf, r['file'])}:{r['line']} at uptime {r['uptime_ms']} ms"
             f" ({'ISR/exception' if r['in_isr'] else 'thread'} context); failing asserts seen: {r['count']}"]
    if r.get("nested_file"):
        lines.append(f"  nested: {elf_string(elf, r['nested_file'])}:{r['nested_line']} fired while the first was"
                     f" handled; the record halted the core there")
    return "\n".join(lines) + "\n"


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
    """pyocd on the MCU-Link, attach mode (phase8-W8 ran it; see the module doc)."""

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

    def write32(self, addr, value):
        self.t.write32(addr, value)

    def read_block(self, addr, size, path):
        data = bytes(self.t.read_memory_block8(addr, size))
        open(path, "wb").write(data)
        return data

    def close(self):
        self.session.close()


def rearm(a, syms):
    """phase9-W2: write the re-arm word and wait for the image's acknowledgement."""
    if REARM not in syms or "island_trace_rearms" not in syms:
        print(f"readout: REARM FAILED {a.elf} has no {REARM}: an image from before phase9-W2 "
              f"cannot re-arm its trace window; flash and reset for the next act")
        return 1
    if a.target != "board":
        print("readout: REARM FAILED --rearm-only is board-only")
        return 1
    if a.dry_run:
        print(f"readout: write32 {REARM} @ {syms[REARM][0]:#010x} = 1, wait for 0")
        return 0
    if a.wait_go:
        print("readout: re-arm attaching (symbols read)", flush=True)
    dev = Board()
    try:
        before = dev.read32(syms["island_trace_rearms"][0])
        if a.wait_go:
            # CARLA demo: attach early, write late. The slow part (the ELF's
            # symbols, pyocd's probe and session) is done; the write waits
            # for the act's word on stdin, so the window opens at a chosen
            # instant, not a pyocd start-up after it
            print("readout: re-arm ready (attached; waiting for go on stdin)", flush=True)
            if not sys.stdin.readline().strip():
                print("readout: REARM CANCELLED no go on stdin (the act ended or gave up)")
                return 3
        dev.write32(syms[REARM][0], 1)
        t0 = time.monotonic()
        while dev.read32(syms[REARM][0]) != 0:
            if time.monotonic() - t0 > 2.0:
                print(f"readout: REARM FAILED the image did not acknowledge in 2 s ({REARM} still set): "
                      f"is the core running?")
                return 1
            time.sleep(0.05)
        took = time.monotonic() - t0
        n = dev.read32(syms["island_trace_rearms"][0])
        up = dev.read32(syms["island_trace_rearm_uptime_ms"][0])
        trig = dev.read32(syms["island_trace_triggered"][0])
        if n != before + 1:
            print(f"readout: REARM FAILED re-arm count {before} -> {n}")
            return 1
        print(f"readout: re-armed: window {n + 1} since boot (re-arm {n}) at uptime {up} ms, "
              f"acknowledged after {took * 1000:.0f} ms; triggered={trig}", flush=True)
        if a.buttons:
            # CARLA demo C6: stay attached as the act's button bridge (one
            # pyocd session holds the probe; board_buttons.py's module doc)
            import board_buttons
            if board_buttons.RECORD not in syms:
                print(f"buttons: BRIDGE FAILED {a.elf} has no {board_buttons.RECORD} "
                      f"(built without CONFIG_ISLAND_BUTTONS: the booth image has it)", flush=True)
                return 1
            return board_buttons.bridge(dev.t, *syms[board_buttons.RECORD],
                                        out=lambda s: print(s, flush=True))
    finally:
        dev.close()
    return 0


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--target", choices=["board", "qemu"], required=True)
    ap.add_argument("--elf", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--monitor", help="qemu: the monitor's unix socket")
    ap.add_argument("--zephyr", default="4.4")
    ap.add_argument("--no-resume", action="store_true", help="leave the core halted after the read")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--serial-only", action="store_true",
                    help="board: read the serial counters alone (attach, no halt) into <out>.json")
    ap.add_argument("--serial-pre", help="the act-start snapshot (<out>.json of a --serial-only read)")
    ap.add_argument("--assert-only", action="store_true",
                    help="board: read the assert record alone (halted for the read) and print it; "
                         "assert.txt beside --out when set")
    ap.add_argument("--rearm-only", action="store_true",
                    help="board: re-arm the trace window for the next act (attach, no halt); "
                         "--out is not written")
    ap.add_argument("--wait-go", action="store_true",
                    help="with --rearm-only: attach, print `re-arm ready`, then write the re-arm word "
                         "only when a line arrives on stdin (EOF cancels)")
    ap.add_argument("--buttons", action="store_true",
                    help="with --rearm-only: after the re-arm, stay attached as the act's button bridge "
                         "(board_buttons.py; CARLA demo C6) until `quit` or EOF on stdin")
    a = ap.parse_args()
    syms = symbols(a.elf, set(WORDS) | {BUFFER, violations.RECORD, SERIAL, BOOTREC, ASSERT} |
                   set(violations.ARM_WORDS) | {REARM, "island_button_record"})
    if a.rearm_only:
        return rearm(a, syms)
    if a.assert_only:
        if ASSERT not in syms:
            print(f"readout: {a.elf} has no {ASSERT} (CONFIG_ISLAND_ASSERT_RECORD is off)")
            return 0
        if a.dry_run:
            print(f"readout: read {ASSERT} @ {syms[ASSERT][0]:#010x}, {syms[ASSERT][1]} B")
            return 0
        os.makedirs(os.path.dirname(os.path.abspath(a.out)), exist_ok=True)
        dev = Board()
        try:
            dev.halt()
            blob = dev.read_block(syms[ASSERT][0], syms[ASSERT][1], a.out + ".assert.bin")
        finally:
            if not a.no_resume:
                dev.resume()
            dev.close()
        text = assert_text(a.elf, blob)
        if text is None:
            print("readout: no failing assert recorded")
            return 0
        open(os.path.join(os.path.dirname(os.path.abspath(a.out)), "assert.txt"), "w").write(text)
        print("readout: " + text.rstrip().replace("\n", "\nreadout: "))
        return 0
    if a.serial_only:
        if SERIAL not in syms:
            print(f"readout: {a.elf} has no {SERIAL}: no serial snapshot")
            return 0
        if a.dry_run:
            print(f"readout: read {SERIAL} @ {syms[SERIAL][0]:#010x}, {syms[SERIAL][1]} B (no halt)")
            return 0
        dev = Board()
        try:
            snap = serial_decode(dev.read_block(syms[SERIAL][0], syms[SERIAL][1], a.out + ".bin"))
        finally:
            dev.close()
        json.dump(snap, open(a.out + ".json", "w"), indent=1)
        print("readout: serial at the act's start: " + " ".join(f"{k}={snap[k]}" for k in SERIAL_ERRORS if k in snap))
        return 0
    if BUFFER not in syms:
        sys.exit(f"readout: {a.elf} has no {BUFFER} (tracing is not in this image)")
    addr, size = syms[BUFFER]
    plan = [f"read {BUFFER} @ {addr:#010x}, {size} B"] + \
        [f"read32 {n} @ {syms[n][0]:#010x}" for n in WORDS if n in syms]
    if violations.RECORD in syms:
        plan += [f"read {violations.RECORD} @ {syms[violations.RECORD][0]:#010x}, {syms[violations.RECORD][1]} B"] + \
            [f"read32 {n} @ {syms[n][0]:#010x}" for n in violations.ARM_WORDS if n in syms and n not in WORDS]
    for n in (SERIAL, BOOTREC, ASSERT):
        if n in syms:
            plan.append(f"read {n} @ {syms[n][0]:#010x}, {syms[n][1]} B")
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
    vdir = os.path.dirname(os.path.abspath(a.out))
    vrec = None
    extra = {}
    try:
        vals = {n: dev.read32(syms[n][0]) for n in WORDS if n in syms}
        data = dev.read_block(addr, size, raw)
        if violations.RECORD in syms:
            vaddr, vsize = syms[violations.RECORD]
            vrec = dev.read_block(vaddr, vsize, os.path.join(vdir, "violations.bin"))
            for n in violations.ARM_WORDS:
                if n in syms and n not in vals:
                    vals[n] = dev.read32(syms[n][0])
        for n, fname in ((SERIAL, "serial.bin"), (BOOTREC, "bootrec.bin"), (ASSERT, "assert.bin")):
            if n in syms:
                extra[n] = dev.read_block(syms[n][0], syms[n][1], os.path.join(vdir, fname))
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
    vtxt = os.path.join(vdir, "violations.txt")
    if vrec is None:
        open(vtxt, "w").write(f"no {violations.RECORD} in {a.elf} (no CONFIG_NROS_BOOT_REPORT on this "
                              f"target): the board's record was not read\n")
    else:
        try:
            text = violations.report(a.elf, vrec, {n: vals[n] for n in violations.ARM_WORDS if n in vals})
        except (SystemExit, Exception) as e:  # noqa: BLE001 -- say so, and keep the trace
            text = f"violation record unreadable: {e!r} (raw bytes in violations.bin)\n"
        open(vtxt, "w").write(text)
        print("readout: " + text.rstrip().replace("\n", "\nreadout: "))
    if SERIAL in extra:
        pre = None
        if a.serial_pre and os.path.exists(a.serial_pre):
            pre = json.load(open(a.serial_pre))
        stext = serial_text(serial_decode(extra[SERIAL]), pre)
        open(os.path.join(vdir, "serial.txt"), "w").write(stext)
        print("readout: " + stext.rstrip().replace("\n", "\nreadout: "))
    if BOOTREC in extra:
        btext = bootrec_text(a.elf, os.path.join(vdir, "bootrec.bin"))
        open(os.path.join(vdir, "bootrec.txt"), "w").write(btext)
        for line in btext.splitlines():
            if "HEAP HEADROOM" in line or "PEAK" in line or "arena used" in line:
                print("readout: " + line.strip())
    if ASSERT in extra:
        atext = assert_text(a.elf, extra[ASSERT])
        if atext is not None:
            open(os.path.join(vdir, "assert.txt"), "w").write(atext)
            print("readout: " + atext.rstrip().replace("\n", "\nreadout: "))
    island_trace.wrap(raw, a.out, a.zephyr, vals.get("island_trace_hb_seq", 0),
                      vals.get("island_trace_hb_last_uptime_ms", 0))
    if "island_trace_triggered" in vals and not vals["island_trace_triggered"]:
        print("readout: WARNING the trace window never triggered: the buffer holds the provenance only")
    return 0


if __name__ == "__main__":
    sys.exit(main())
