#!/usr/bin/env python3
"""The board's SW1/SW2, off the board over SWD (CONFIG_ISLAND_BUTTONS,
src/zephyr_entry/src/island_buttons.c; docs/design/carla-island-demo.md 3.4, C6).

  board_buttons.py watch  --elf <zephyr.elf> [--secs N]   the on-site check: attach (no halt)
                          and print every SW1/SW2 pin edge and every press the island records,
                          live, until Ctrl-C (or N s). Nothing is written, nothing reflashed.
  board_buttons.py inject --elf <zephyr.elf> sw1|sw2 [--ticks 3]
                          press a button through the firmware path with nobody at the board:
                          write the record's inject word (the button reads pressed for N
                          handler ticks), then print the press the island recorded
  board_buttons.py show   --elf <zephyr.elf>              one reading of the record
  board_buttons.py --dry-run ...                          resolve the symbol, touch nothing

Two readings, independent of each other:
  pins    the SIUL2 parallel input registers (PGPDI) read straight from the
          peripheral: SW1 is PTD15, PGPDI(D low) at 0x4029174E, SW2 PTA25,
          PGPDI(A high) at 0x40291740; bit (15 - pin%16) per pin, active high
          (gpio_nxp_siul2.c: PGPDI = gpio base + 0x40; the gpio bases from the
          booth image's zephyr.dts, gpiod_l 0x4029170e, gpioa_h 0x40291700).
          What the pads read now, with no firmware in between.
  record  island_button_record: the level the handler sampled at its last
          tick, the debounced level, and the last 8 presses with their uptime,
          the handler's state, and whether the island accepted them.

The act's bridge (bridge(), run by readout.py --rearm-only --buttons in the
same pyocd session that re-arms the trace window, so one session holds the
probe) polls the record every POLL_S and prints one line per new press:

  buttons: press SW1 accepted uptime_ms=<ms> state=NORMAL/NONE n=<presses>
  buttons: press SW2 ignored (not NORMAL) uptime_ms=<ms> state=... n=<presses>

and reads commands on stdin: `inject sw1|sw2 [ticks]`, `quit` (EOF quits).
"""
import argparse
import os
import select
import struct
import sys
import time

RECORD = "island_button_record"
MAGIC = 0x534E5442
RING = 8
# struct island_button_record (all u32): magic ticks level debounced presses
# accepted[2] ignored[2] inject[2] gpio_errors, then ring[8] of (uptime_ms, code)
HDR = ["magic", "ticks", "level", "debounced", "presses", "acc1", "acc2", "ign1", "ign2", "inj1", "inj2",
       "gpio_errors"]
OFF_INJECT = 4 * HDR.index("inj1")
OFF_RING = 4 * len(HDR)
PGPDI = {"SW1": (0x4029174E, 15), "SW2": (0x40291740, 9)}  # (register, pin index in the 16-pin half)
NAMES = {1: "SW1", 2: "SW2"}
WHY = {0: "accepted", 1: "ignored (handler in INIT)", 2: "ignored (no takeover request)",
       3: "ignored (not NORMAL)"}
STATE = {0: "-", 1: "NORMAL", 2: "MRM_OPERATING", 3: "MRM_SUCCEEDED", 4: "MRM_FAILED"}
BEHAVIOR = {0: "-", 1: "NONE", 2: "EMERGENCY_STOP", 3: "COMFORTABLE_STOP", 4: "PULL_OVER"}
POLL_S = 0.025


def symbol(elf, name=RECORD):
    from elftools.elf.elffile import ELFFile
    with open(elf, "rb") as f:
        for s in ELFFile(f).get_section_by_name(".symtab").iter_symbols():
            if s.name == name:
                return s["st_value"], s["st_size"]
    return None


def read_record(t, addr, size):
    blob = bytes(t.read_memory_block8(addr, size))
    hdr = dict(zip(HDR, struct.unpack_from(f"<{len(HDR)}I", blob, 0)))
    ring = [struct.unpack_from("<2I", blob, OFF_RING + 8 * i) for i in range(RING)]
    return hdr, ring


def read_pins(t):
    return {n: 1 if t.read16(reg) & (1 << (15 - pin)) else 0 for n, (reg, pin) in PGPDI.items()}


def press_text(up, code):
    b, why, st, beh = code >> 24, (code >> 16) & 0xF, (code >> 8) & 0xFF, code & 0xFF
    return (f"{NAMES.get(b, b)} {WHY.get(why, why)} uptime_ms={up} "
            f"state={STATE.get(st, st)}/{BEHAVIOR.get(beh, beh)}")


def new_presses(hdr, ring, seen):
    """(n, uptime, code) of each press after `seen`, oldest first (at most RING)."""
    n = hdr["presses"]
    return [(i + 1, *ring[i % RING]) for i in range(max(seen, n - RING), n)]


def inject(t, addr, button, ticks):
    b = {"sw1": 0, "sw2": 1}[button.lower()]
    t.write32(addr + OFF_INJECT + 4 * b, ticks)


def summary(hdr):
    return (f"presses {hdr['presses']}, SW1 accepted {hdr['acc1']} ignored {hdr['ign1']}, "
            f"SW2 accepted {hdr['acc2']} ignored {hdr['ign2']}, ticks {hdr['ticks']}, "
            f"gpio_errors {hdr['gpio_errors']}")


def bridge(t, addr, size, out=print):
    """The act's side (module doc): until `quit` or EOF on stdin."""
    hdr, _ = read_record(t, addr, size)
    if hdr["magic"] != MAGIC:
        out(f"buttons: BRIDGE FAILED record magic {hdr['magic']:#x} (built without CONFIG_ISLAND_BUTTONS?)")
        return 1
    seen = hdr["presses"]
    out(f"buttons: bridge ready ({summary(hdr)})")
    sys.stdout.flush()
    fd, buf = sys.stdin.fileno(), b""
    while True:
        r, _, _ = select.select([fd], [], [], POLL_S)
        if r:
            chunk = os.read(fd, 4096)
            if not chunk:
                out("buttons: bridge done (EOF)")
                return 0
            buf += chunk
        while b"\n" in buf:
            line, buf = buf.split(b"\n", 1)
            w = line.decode(errors="replace").split()
            if w == ["quit"]:
                out("buttons: bridge done")
                return 0
            if len(w) >= 2 and w[0] == "inject" and w[1].lower() in ("sw1", "sw2"):
                ticks = int(w[2]) if len(w) > 2 else 3
                inject(t, addr, w[1], ticks)
                out(f"buttons: injected {w[1].upper()} {ticks} ticks")
        hdr, ring = read_record(t, addr, size)
        for n, up, code in new_presses(hdr, ring, seen):
            out(f"buttons: press {press_text(up, code)} n={n}")
        seen = hdr["presses"]
        sys.stdout.flush()


def show(hdr, ring, pins=None):
    lv, db = hdr["level"], hdr["debounced"]
    print(f"record: magic={'ok' if hdr['magic'] == MAGIC else hex(hdr['magic'])} {summary(hdr)}")
    print(f"  last tick: SW1 pin {lv >> 8 & 1} inject {lv >> 16 & 1} -> down {db & 1};"
          f" SW2 pin {lv >> 9 & 1} inject {lv >> 17 & 1} -> down {db >> 1 & 1}"
          + ("" if pins is None else f"; pads now SW1 {pins['SW1']} SW2 {pins['SW2']}"))
    for n, up, code in new_presses(hdr, ring, 0):
        print(f"  #{n:<3d} {up / 1000:9.3f} s  {press_text(up, code)}")


def session():
    from pyocd.core.helpers import ConnectHelper
    s = ConnectHelper.session_with_chosen_probe(
        target_override="s32k344", connect_mode="attach", options={"frequency": 4000000})
    s.open()
    return s


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("cmd", choices=["watch", "inject", "show"])
    ap.add_argument("button", nargs="?", choices=["sw1", "sw2", "SW1", "SW2"])
    ap.add_argument("--elf", required=True)
    ap.add_argument("--secs", type=float, default=0.0, help="watch: stop after N s (0: until Ctrl-C)")
    ap.add_argument("--ticks", type=int, default=3, help="inject: handler ticks the button reads pressed")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()
    sym = symbol(a.elf)
    if sym is None:
        sys.exit(f"board_buttons: {a.elf} has no {RECORD} (built without CONFIG_ISLAND_BUTTONS: "
                 f"the booth image, just board-build-booth, has it)")
    addr, size = sym
    print(f"board_buttons: {RECORD} @ {addr:#010x}, {size} B")
    if a.dry_run:
        return 0
    if a.cmd == "inject" and not a.button:
        sys.exit("board_buttons: inject sw1|sw2")
    s = session()
    try:
        t = s.board.target
        hdr, ring = read_record(t, addr, size)
        if hdr["magic"] != MAGIC:
            print(f"board_buttons: record magic {hdr['magic']:#x}: is the image on the board this ELF?")
            return 1
        show(hdr, ring, read_pins(t))
        if a.cmd == "show":
            return 0
        if a.cmd == "inject":
            seen = hdr["presses"]
            t0 = time.monotonic()
            inject(t, addr, a.button, a.ticks)
            while time.monotonic() - t0 < 2.0:
                hdr, ring = read_record(t, addr, size)
                if hdr["presses"] > seen:
                    for n, up, code in new_presses(hdr, ring, seen):
                        print(f"injected {a.button.upper()}: press {press_text(up, code)} n={n}, "
                              f"seen {(time.monotonic() - t0) * 1000:.0f} ms after the write")
                    return 0
                time.sleep(POLL_S)
            print(f"injected {a.button.upper()}: NO press recorded in 2 s ({summary(hdr)})")
            return 1
        # watch: the on-site check
        print("watching: press SW1 and SW2 (hold each about half a second); Ctrl-C to stop", flush=True)
        seen, last_pins, last_db = hdr["presses"], read_pins(t), hdr["debounced"]
        end = time.monotonic() + a.secs if a.secs else None
        try:
            while end is None or time.monotonic() < end:
                time.sleep(POLL_S)
                pins = read_pins(t)
                hdr, ring = read_record(t, addr, size)
                ts = time.strftime("%H:%M:%S") + f".{int(time.time() * 1000) % 1000:03d}"
                for n in ("SW1", "SW2"):
                    if pins[n] != last_pins[n]:
                        print(f"{ts} pad {n} {'DOWN' if pins[n] else 'up'}", flush=True)
                for b, n in ((0, "SW1"), (1, "SW2")):
                    if (hdr["debounced"] ^ last_db) >> b & 1:
                        print(f"{ts} island {n} {'down' if hdr['debounced'] >> b & 1 else 'released'} "
                              f"(debounced, tick {hdr['ticks']})", flush=True)
                for n, up, code in new_presses(hdr, ring, seen):
                    print(f"{ts} island press {press_text(up, code)} n={n}", flush=True)
                last_pins, last_db, seen = pins, hdr["debounced"], hdr["presses"]
        except KeyboardInterrupt:
            pass
        hdr, ring = read_record(t, addr, size)
        show(hdr, ring, read_pins(t))
    finally:
        s.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
