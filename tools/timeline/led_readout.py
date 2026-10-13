#!/usr/bin/env python3
"""The island's LED state, off the board (CONFIG_ISLAND_LED, src/zephyr_entry/src/island_led.c).

  led_readout.py --elf <zephyr.elf>                 attach (no halt), one reading
  led_readout.py --elf <zephyr.elf> --watch 60      a reading every 0.5 s for 60 s,
                                                    printed when the pins change
  led_readout.py --elf <zephyr.elf> --dry-run       resolve the symbol, touch nothing

Two independent readings per sample:
  pins    the SIUL2 parallel output registers (PGPDO) of the four LED pins, read
          straight from the peripheral: what the pads drive. Active low, so
          bit 0 = lit. Red PTE14 and blue PTE12 are in PGPDO(E low) at
          0x40291712, green PTA27 in PGPDO(A high) at 0x40291700, CAN LED0
          PTC18 in PGPDO(C high) at 0x40291708; bit (15 - pin%16) per pin
          (gpio_nxp_siul2.c; nxp_s32k344_m7.dtsi).
  record  island_led_record: the pattern the handler selected, the tick count
          and the last 8 transitions with their uptime.
"""
import argparse
import struct
import sys
import time

PGPDO = {"A_H": 0x40291700, "C_H": 0x40291708, "E_L": 0x40291712}
PINS = {  # name: (register, pin index within the 16-pin half)
    "red": ("E_L", 14), "green": ("A_H", 11), "blue": ("E_L", 12), "hb": ("C_H", 2)}
MAGIC = 0x5344454C
RING = 8
STATE = {1: "NORMAL", 2: "MRM_OPERATING", 3: "MRM_SUCCEEDED", 4: "MRM_FAILED", 0: "-"}
BEHAVIOR = {0: "", 1: "NONE", 2: "EMERGENCY_STOP", 3: "COMFORTABLE_STOP", 4: "PULL_OVER"}  # MrmState.msg


def symbol(elf, name):
    from elftools.elf.elffile import ELFFile
    with open(elf, "rb") as f:
        for s in ELFFile(f).get_section_by_name(".symtab").iter_symbols():
            if s.name == name:
                return s["st_value"], s["st_size"]
    sys.exit(f"led_readout: {elf} has no {name} (built without CONFIG_ISLAND_LED)")


def pattern_text(p):
    c = "".join(n for b, n in ((1, "R"), (2, "G"), (4, "B")) if p & b) or "off"
    return c + (" blink" if p & 8 else "")


def code_text(code):
    st, beh, tk, p = code >> 24, (code >> 16) & 0xFF, (code >> 8) & 0xFF, code & 0xFF
    s = STATE.get(st, str(st))
    if BEHAVIOR.get(beh):
        s += "/" + BEHAVIOR[beh]
    if tk:
        s += " +takeover"
    return f"{s:36s} -> {pattern_text(p)}"


def read_pins(t):
    regs = {k: t.read16(a) for k, a in PGPDO.items()}
    return {n: 0 if regs[r] & (1 << (15 - pin)) else 1 for n, (r, pin) in PINS.items()}


def read_record(t, addr, size):
    blob = bytes(t.read_memory_block8(addr, size))
    hdr = struct.unpack_from("<6I", blob, 0)
    ring = [struct.unpack_from("<2I", blob, 24 + 8 * i) for i in range(RING)]
    return hdr, ring


def show(hdr, ring, pins):
    magic, pattern, code, ticks, trans, errs = hdr
    lit = "".join(n[0].upper() for n in ("red", "green", "blue") if pins[n]) or "off"
    print(f"pins lit={lit:3s} hb={pins['hb']}  record: magic={'ok' if magic == MAGIC else hex(magic)} "
          f"pattern={pattern_text(pattern)} ticks={ticks} transitions={trans} gpio_errors={errs}")
    n = min(trans, RING)
    for i in range(trans - n, trans):
        up, c = ring[i % RING]
        print(f"  #{i:<3d} {up / 1000:9.3f} s  {code_text(c)}")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--elf", required=True)
    ap.add_argument("--watch", type=float, default=0.0, help="seconds to poll the pins")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()
    addr, size = symbol(a.elf, "island_led_record")
    print(f"led_readout: island_led_record @ {addr:#010x}, {size} B")
    if a.dry_run:
        return 0
    from pyocd.core.helpers import ConnectHelper
    s = ConnectHelper.session_with_chosen_probe(
        target_override="s32k344", connect_mode="attach", options={"frequency": 4000000})
    s.open()
    try:
        t = s.board.target
        pins = read_pins(t)
        hdr, ring = read_record(t, addr, size)
        show(hdr, ring, pins)
        end, last = time.monotonic() + a.watch, None
        while time.monotonic() < end:
            time.sleep(0.5)
            pins = read_pins(t)
            hdr, _ = read_record(t, addr, size)
            key = (pins["red"], pins["green"], pins["blue"], hdr[1])
            if key != last:
                lit = "".join(n[0].upper() for n in ("red", "green", "blue") if pins[n]) or "off"
                print(f"{time.strftime('%H:%M:%S')} pins lit={lit:3s} hb={pins['hb']} "
                      f"pattern={pattern_text(hdr[1])} ticks={hdr[3]}", flush=True)
                last = key
        if a.watch:
            hdr, ring = read_record(t, addr, size)
            show(hdr, ring, read_pins(t))
    finally:
        s.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
