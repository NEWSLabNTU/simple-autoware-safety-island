"""DIAG (spin latency): read and decode island_spin_diag over SWD.

  spin_diag.py read    --elf <zephyr.elf> --out <prefix>    attach, no halt
  spin_diag.py decode  [--elf <zephyr.elf>] <prefix>.bin
  spin_diag.py segment [--elf <zephyr.elf>] <pre>.bin <act>.bin | <run dir>
  spin_diag.py selftest <blob>      (the blob tests/spin_diag writes)

The struct is src/safety_island_tracing/include/island_spin_diag.h
(CONFIG_ISLAND_SPIN_DIAG, 'SDG2'): every spin_once-to-spin_once interval of
each executor level (one executor thread per derived sched task, followed
apart, up to the header's SD_LEVELS), its lateness against its OWN park
bound (late = interval - park bound, the bound phase 1 carries), and for
each interval at least 2 ms late the five segments (S0 entry->wait, S1
wait+drive_io, S2 dispatch, S3 post rules, S4 caller loop) charged to the
level's thread / idle / rest.

decode prints first the sum over the measured levels (the `spins=` and
`lateness histogram` lines tools/eval/actseg.py reads), then one block per
level. segment prints the act segment (act read minus pre read) per level;
<run dir> means its spin-diag-pre.bin and spin-diag-act.bin.
"""
import argparse
import os
import struct
import subprocess
import sys

SYM = "island_spin_diag"
EXTRA = ["_z_zephyr_serial_stats", "_z_zephyr_serial_tx_stats", "_z_zephyr_serial_isr_cycles",
         "_z_zephyr_serial_isr_calls", "_z_zephyr_serial_async_stats"]
SEGS = ["S0 pre", "S1 wait", "S2 disp", "S3 post", "S4 loop"]
REC = ["uptime_ms", "interval_us"] + [f"wall{i}" for i in range(5)] + [f"main{i}" for i in range(5)] \
    + [f"idle{i}" for i in range(5)] + ["park_bound_us", "idle_path", "ncb", "ntake", "cb_slot", "cb_wall_us",
                                        "cb_main_us", "cb_idle_us", "cb_off_us", "lk_main_n", "lk_main_us",
                                        "lk_main_max_us", "lk_main_max_ra", "lk_main_max_m", "lk_oth_n",
                                        "lk_oth_us", "lk_oth_max_us", "lk_oth_max_ra", "isr_us", "isr_n",
                                        "tt0", "tt1", "tt2", "tu0", "tu1", "tu2", "cb_isr_us", "cb_isr_n",
                                        "level", "late_us"]
LEV = ["tid", "prio"] + ["name"] * 4 + ["spins", "nobound", "late", "max_late_us", "bound_min_us",
                                        "bound_max_us", "interval_max_us"]
MAGIC_V1, MAGIC = 0x31474453, 0x32474453
HEAD_WORDS = 9
NO_BOUND = 0xFFFFFFFF


def find_addr2line():
    """arm-zephyr-eabi-addr2line: $ADDR2LINE, else $ZEPHYR_SDK_INSTALL_DIR's
    (scripts/board-env.sh exports it), else the newest SDK in the nros store
    (~/.nros/sdk), else PATH."""
    import glob
    import shutil
    tool = "arm-zephyr-eabi-addr2line"
    if os.environ.get("ADDR2LINE"):
        return os.environ["ADDR2LINE"]
    sdk = os.environ.get("ZEPHYR_SDK_INSTALL_DIR")
    if sdk and os.path.exists(os.path.join(sdk, "gnu/arm-zephyr-eabi/bin", tool)):
        return os.path.join(sdk, "gnu/arm-zephyr-eabi/bin", tool)
    store = sorted(glob.glob(os.path.expanduser(f"~/.nros/sdk/zephyr-sdk-*/*/zephyr-sdk-*/gnu/arm-zephyr-eabi/bin/{tool}")))
    if store:
        return store[-1]
    return shutil.which(tool) or tool


ADDR2LINE = find_addr2line()


def symbols(elf, names):
    from elftools.elf.elffile import ELFFile
    out = {}
    with open(elf, "rb") as f:
        for s in ELFFile(f).get_section_by_name(".symtab").iter_symbols():
            if s.name in names and s.name not in out:
                out[s.name] = (s["st_value"], s["st_size"])
    return out


def fn_at(elf, addr, cache={}):
    if not addr:
        return "-"
    if not elf:
        return hex(addr)
    if addr not in cache:
        try:
            r = subprocess.run([ADDR2LINE, "-f", "-s", "-e", elf, hex(addr & ~1)], capture_output=True, text=True)
            lines = r.stdout.split()
            cache[addr] = f"{lines[0]}@{lines[1]}" if len(lines) >= 2 else hex(addr)
        except OSError:
            cache[addr] = hex(addr)
    return cache[addr]


def sprio(p):
    return p - (1 << 32) if p >= 1 << 31 else p


def parse(blob):
    """The struct as a dict, or a str saying why it cannot be read."""
    w = lambda off, n: struct.unpack_from(f"<{n}I", blob, off)  # noqa: E731
    if len(blob) < 4 * HEAD_WORDS:
        return "spin_diag: short read\n"
    magic, rec_words, lev_words, dims, late_thr, nlev, dropped, ring_next, nthr = w(0, HEAD_WORDS)
    if magic == MAGIC_V1:
        return ("spin_diag: an SDG1 image (one thread, lateness against 10 ms, before island #14): "
                "decode it with spin_diag.py of island 378dd11\n")
    if magic != MAGIC:
        return f"spin_diag: bad magic {magic:#x} (no spin yet?)\n"
    if rec_words != len(REC):
        return f"spin_diag: record is {rec_words} words, decoder knows {len(REC)}\n"
    nlevels, bins, ring_n, nthreads = dims & 0xFF, (dims >> 8) & 0xFF, (dims >> 16) & 0xFF, dims >> 24
    if lev_words != len(LEV) + bins + 5 + rec_words:
        return f"spin_diag: level is {lev_words} words, decoder expects {len(LEV) + bins + 5 + rec_words}\n"
    rec = lambda o: dict(zip(REC, w(o, rec_words)))  # noqa: E731
    name = lambda o: blob[o:o + 16].split(b"\0")[0].decode(errors="replace")  # noqa: E731
    off = 4 * HEAD_WORDS
    levels = []
    for i in range(nlevels):
        o = off + i * 4 * lev_words
        tid, prio = w(o, 2)
        v = w(o + 24, 7)
        lv = dict(zip(["spins", "nobound", "late", "max_late_us", "bound_min_us", "bound_max_us",
                       "interval_max_us"], v))
        lv.update(index=i, tid=tid, prio=sprio(prio), name=name(o + 8) or hex(tid))
        lv["hist"] = list(w(o + 52, bins))
        lv["segmax"] = list(w(o + 52 + 4 * bins, 5))
        lv["worst"] = rec(o + 52 + 4 * bins + 20)
        if i < nlev:
            levels.append(lv)
    off += nlevels * 4 * lev_words
    thr = {}
    for i in range(nthreads):
        tid, prio = w(off, 2)
        if i < nthr:
            thr[tid] = f"{name(off + 8) or hex(tid)}(p{sprio(prio)})"
        off += 24
    recsz = 4 * rec_words
    ring = [rec(off + i * recsz) for i in range(ring_n)]
    n = min(ring_next, ring_n)
    order = [(ring_next - n + i) % ring_n for i in range(n)]
    return dict(levels=levels, dropped=dropped, ring_next=ring_next, ring_n=ring_n, bins=bins,
                late_thr=late_thr, thr=thr, ring=[(i, ring[i]) for i in order])


def lvname(lv):
    return f"{lv['name']}(p{lv['prio']})"


def hist_str(h):
    return " ".join(f"{i}:{c}" for i, c in enumerate(h) if c)


def bounds(lv):
    if lv["spins"] - lv["nobound"] == 0:
        return "-"
    return f"{lv['bound_min_us']}..{lv['bound_max_us']}"


def decode(elf, blob):
    d = parse(blob)
    if isinstance(d, str):
        return d
    lv = d["levels"]
    thr_ms = d["late_thr"] / 1000
    hist = [sum(x["hist"][b] for x in lv) for b in range(d["bins"])]
    out = [f"spins={sum(x['spins'] for x in lv)} late(>={thr_ms:g}ms)={sum(x['late'] for x in lv)} "
           f"max_late_us={max([x['max_late_us'] for x in lv], default=0)} "
           f"levels={len(lv)} dropped={d['dropped']} (lateness = interval past its own park bound; "
           f"sum over the levels below)",
           "lateness histogram (ms bin: count): " + hist_str(hist)]
    for x in lv:
        i = x["index"]
        out.append(f"level {i} {lvname(x)}: spins={x['spins']} judged={x['spins'] - x['nobound']} "
                   f"nobound={x['nobound']} late(>={thr_ms:g}ms)={x['late']} max_late_us={x['max_late_us']} "
                   f"park_bound_us={bounds(x)} interval_max_us={x['interval_max_us']}")
        out.append(f"level {i} lateness (ms bin: count): " + hist_str(x["hist"]))
        out.append(f"level {i} segment max wall us: " + " ".join(f"{SEGS[k]}={x['segmax'][k]}" for k in range(5)))
    out.append("threads: " + " ".join(f"{hex(t)}={n}" for t, n in d["thr"].items()))
    names = {x["index"]: x["name"] for x in lv}
    thr = d["thr"]

    def fmt(r, tag):
        pb = "none" if r["park_bound_us"] == NO_BOUND else f"{r['park_bound_us']}us"
        s = [f"{tag} lvl={names.get(r['level'], r['level'])} t={r['uptime_ms']}ms interval={r['interval_us']}us "
             f"late={r['late_us']}us park_bound={pb}"
             f" idle_path={r['idle_path']} ncb={r['ncb']} ntake={r['ntake']} isr={r['isr_us']}us/{r['isr_n']}"]
        for i in range(5):
            wl, mn, idl = r[f"wall{i}"], r[f"main{i}"], r[f"idle{i}"]
            s.append(f"    {SEGS[i]}: wall={wl:6d} spin={mn:6d} idle={idl:6d} other={wl - mn - idl:6d}")
        s.append(f"    longest cb: slot={r['cb_slot']} wall={r['cb_wall_us']} spin={r['cb_main_us']} "
                 f"idle={r['cb_idle_us']} isr={r['cb_isr_us']}us/{r['cb_isr_n']} at +{r['cb_off_us']}us")
        s.append(f"    spin lock waits: n={r['lk_main_n']} total={r['lk_main_us']}us max={r['lk_main_max_us']}us "
                 f"in {fn_at(elf, r['lk_main_max_ra'])} m={r['lk_main_max_m']:#x}")
        s.append(f"    other lock waits: n={r['lk_oth_n']} total={r['lk_oth_us']}us max={r['lk_oth_max_us']}us "
                 f"in {fn_at(elf, r['lk_oth_max_ra'])}")
        s.append("    other threads: " + " ".join(f"{thr.get(r[f'tt{k}'], hex(r[f'tt{k}']))}={r[f'tu{k}']}us"
                                                  for k in range(3) if r[f"tt{k}"]))
        return "\n".join(s)
    for x in lv:
        if x["max_late_us"]:
            out.append(fmt(x["worst"], "WORST"))
    for i, r in d["ring"]:
        out.append(fmt(r, f"late#{i}"))
    return "\n".join(out) + "\n"


def segment(pre_blob, act_blob):
    """Per level, the act segment: the act read minus the pre read."""
    a = parse(act_blob)
    if isinstance(a, str):
        return a
    p = parse(pre_blob)
    if isinstance(p, str):
        # a pre read before the first spin: the act segment is the whole act read
        p = dict(levels=[], ring_next=0)
    pre = {x["tid"]: x for x in p["levels"]}
    new = a["ring_next"] - p["ring_next"]
    ring = {}  # level -> the act's late records the ring still holds
    for i, r in a["ring"][max(0, len(a["ring"]) - new):]:
        ring.setdefault(r["level"], []).append(r["late_us"])
    thr_ms = a["late_thr"] / 1000
    out = [f"{'level':34s} {'spins':>6s} {'judged':>6s} {'>=1ms':>6s} {f'>={thr_ms:g}ms':>6s} "
           f"{'worst late':>12s} {'park bound us (boot)':>20s}  lateness ms bins (act)"]
    for x in a["levels"]:
        q = pre.get(x["tid"], dict(spins=0, nobound=0, late=0, max_late_us=0, hist=[0] * len(x["hist"])))
        h = [c - c0 for c, c0 in zip(x["hist"], q["hist"])]
        spins = x["spins"] - q["spins"]
        judged = spins - (x["nobound"] - q["nobound"])
        late = x["late"] - q["late"]
        if x["max_late_us"] > q["max_late_us"]:
            worst = f"{x['max_late_us']}us"  # the boot maximum moved inside the act: exact
        elif ring.get(x["index"]) and new <= a["ring_n"]:
            worst = f"{max(ring[x['index']])}us"
        else:
            wb = max([b for b, c in enumerate(h) if c], default=None)
            worst = "-" if wb is None else f"<{wb + 1}ms"
        out.append(f"{lvname(x):34s} {spins:6d} {judged:6d} {sum(h[1:]):6d} {late:6d} {worst:>12s} "
                   f"{bounds(x):>20s}  {hist_str(h) or '-'}")
    if new > a["ring_n"]:
        out.append(f"(ring wrapped: {new} late records in the act, {a['ring_n']} kept)")
    return "\n".join(out) + "\n"


def selftest(path):
    """Decode the blob tests/spin_diag/test_spin_diag.c writes and check the
    numbers its scenario fixes (two levels: bounds 29-30 ms and 85 ms)."""
    sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "diag"))
    import late_records
    blob = open(path, "rb").read()
    txt = decode(None, blob)
    fails = []

    def want(cond, what):
        if not cond:
            fails.append(what)
    want(txt.startswith("spins=5 late(>=2ms)=1 max_late_us=3600 levels=2 dropped=0"), "sum line")
    want("lateness histogram (ms bin: count): 0:1 1:2 3:1\n" in txt, "sum histogram")
    want("level 0 derived-a(p5): spins=3 judged=3 nobound=0 late(>=2ms)=1 max_late_us=3600 "
         "park_bound_us=29000..30000 interval_max_us=32600" in txt, "level 0")
    want("level 1 derived-b(p8): spins=2 judged=1 nobound=1 late(>=2ms)=0 max_late_us=1000 "
         "park_bound_us=85000..85000" in txt, "level 1")
    want("late#0 lvl=derived-a t=63ms interval=32600us late=3600us park_bound=29000us" in txt, "ring record")
    want("WORST lvl=derived-b t=87ms interval=86000us late=1000us park_bound=85000us" in txt, "level 1 worst")
    want("other threads: " in txt and "zpico_rx(p3)=1500us" in txt, "other threads")
    lr = late_records.lines(txt)
    want(len(lr) == 3 and "lvl=derived-a" in lr[0] and "late=  3600" in lr[0], f"late_records {lr}")
    want(late_records.lines(txt, 2000) == [lr[0], lr[2]], "late_records min_late")
    # a pre read with no level yet: the act segment is the whole act read
    pre = bytearray(blob)
    struct.pack_into("<I", pre, 4 * 5, 0)  # nlev
    struct.pack_into("<I", pre, 4 * 7, 0)  # ring_next
    seg = segment(bytes(pre), blob).splitlines()
    want(len(seg) == 3, f"segment rows {seg}")
    want(seg[1].split()[:6] == ["derived-a(p5)", "3", "3", "2", "1", "3600us"], f"segment a {seg[1:2]}")
    want(seg[2].split()[:6] == ["derived-b(p8)", "2", "1", "1", "0", "1000us"], f"segment b {seg[2:3]}")
    want(segment(blob, blob).splitlines()[1].split()[1:6] == ["0", "0", "0", "0", "-"], "segment empty")
    want("SDG1" in decode(None, struct.pack("<I", MAGIC_V1) + bytes(64)), "v1 refused")
    for f in fails:
        print(f"FAIL {f}")
    print("spin_diag selftest: " + ("OK" if not fails else f"{len(fails)} FAILED"))
    return 1 if fails else 0


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("cmd", choices=["read", "decode", "segment", "selftest"])
    ap.add_argument("arg", nargs="*")
    ap.add_argument("--elf")
    ap.add_argument("--out")
    a = ap.parse_intermixed_args()
    if a.cmd == "selftest":
        return selftest(a.arg[0] if a.arg else "build/tests/spin_diag.bin")
    if a.cmd == "decode":
        sys.stdout.write(decode(a.elf, open(a.arg[0], "rb").read()))
        return 0
    if a.cmd == "segment":
        if len(a.arg) == 1:
            pre, act = (os.path.join(a.arg[0], f"spin-diag-{k}.bin") for k in ("pre", "act"))
        else:
            pre, act = a.arg[:2]
        sys.stdout.write(segment(open(pre, "rb").read(), open(act, "rb").read()))
        return 0
    if not a.elf or not a.out:
        ap.error("read needs --elf and --out")
    syms = symbols(a.elf, {SYM, *EXTRA})
    from pyocd.core.helpers import ConnectHelper
    s = ConnectHelper.session_with_chosen_probe(target_override="s32k344", connect_mode="attach",
                                                options={"frequency": 4000000})
    s.open()
    try:
        t = s.board.target
        addr, size = syms[SYM]
        blob = bytes(t.read_memory_block8(addr, size))
        extra = {n: bytes(t.read_memory_block8(*syms[n])) for n in EXTRA if n in syms}
    finally:
        s.close()
    open(a.out + ".bin", "wb").write(blob)
    text = decode(a.elf, blob)
    for n, b in extra.items():
        text += f"{n}: " + " ".join(str(x) for x in struct.unpack(f"<{len(b) // 4}I", b)) + "\n"
    open(a.out + ".txt", "w").write(text)
    sys.stdout.write(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
