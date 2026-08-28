#!/usr/bin/env python3
"""Decode a z-serial wire dump into frames.

Why this exists: tshark cannot help here. Wireshark's zenoh dissector arrived
in 4.2 (this host has 3.6.2), and even where it exists it dissects zenoh over
TCP/UDP -- there is no serial link-layer for it to sit on. The zenoh-pico
serial link is its own framing on a raw UART:

    COBS( header(1) | len(2, LE) | payload(len) | crc32(4, LE) )   0x00 delim

so the bytes on the wire are not a protocol tshark knows at any layer.

Feed it the hex dump socat writes:

    socat -x -v /dev/ttyUSB0,raw,echo=0,b115200 PTY,link=/tmp/ttyTAP,raw,echo=0 2>/tmp/tap.hex
    # point the router at serial//tmp/ttyTAP instead of /dev/ttyUSB0
    ./serial-tap.py /tmp/tap.hex

socat marks direction with '>' (into the pty side) and '<' (out of it), which
this keeps, so a frame can be attributed to the board or the router.
"""
import re
import sys

FLAG = {0x01: "INIT", 0x02: "ACK", 0x04: "RESET"}


def cobs_decode(data):
    """Standard COBS. The zero that terminates a group is emitted only when
    another group follows -- appending it unconditionally adds a phantom byte
    at the end of every frame and was why every CRC failed here first time."""
    out = bytearray()
    i = 0
    n = len(data)
    while i < n:
        code = data[i]
        if code == 0:
            return None
        i += 1
        take = code - 1
        if i + take > n:
            return None
        out += data[i:i + take]
        i += take
        if code < 0xFF and i < n:
            out.append(0)
    return bytes(out)


def decode_frame(raw, direction, n):
    d = cobs_decode(raw)
    if d is None or len(d) < 7:
        print(f"  [{n}] {direction} UNDECODABLE  {len(raw)}B cobs -> "
              f"{0 if d is None else len(d)}B")
        return
    header = d[0]
    ln = int.from_bytes(d[1:3], "little")
    payload = d[3:3 + ln]
    tail = d[3 + ln:7 + ln]
    flags = ",".join(v for k, v in FLAG.items() if header & k) or "-"
    # The trailing 4 bytes are reported, NOT verified. z-serial calls them a
    # crc32, but none of the eight standard CRC-32 variants (ISO-HDLC, BZIP2,
    # MPEG-2, POSIX, JAMCRC, CRC-32C, AUTOSAR, CD-ROM) over either the payload
    # or header+len+payload reproduces the observed value. Printing a
    # "CRC-BAD" that only means "I do not know the algorithm" would be worse
    # than printing the bytes -- it reads as corruption on every good frame.
    # What IS verified is the framing: `len` matches the bytes present, and a
    # short frame is called out below.
    trunc = "" if len(payload) == ln else f"  TRUNCATED {len(payload)}/{ln}"
    txt = "".join(chr(c) if 32 <= c < 127 else "." for c in payload[:32])
    print(f"  [{n}] {direction} hdr=0x{header:02x}({flags}) len={ln}"
          f" tail={tail.hex()}{trunc}  {txt}")


def main(path):
    """socat -x -v writes, per transfer:

        > 2026/08/28 20:17:42.753057  length=9 from=0 to=8
         02 01 01 01 01 01 01 01 00                       .........
        --

    The header line and the ASCII gutter both contain characters that look
    like hex bytes (a date has `20`, `28`, `17`), so tokens must come ONLY
    from the fixed-width hex column of a hex line -- 16 bytes at 3 chars
    each, starting at column 1. Taking `findall` over the whole file is what
    corrupted the first capture.

    Direction: socat's `>` is address1 -> address2. address1 is the real UART,
    so `>` is BOARD -> ROUTER.
    """
    direction = "?"
    buf = bytearray()
    n = 0
    for raw_line in open(path, "rb"):
        t = raw_line.decode("latin1").rstrip("\n")
        if t.startswith(">"):
            direction = "board->router"
            continue
        if t.startswith("<"):
            direction = "router->board"
            continue
        if not t.startswith(" "):
            continue
        for tok in re.findall(r"[0-9a-fA-F]{2}", t[1:49]):
            b = int(tok, 16)
            if b == 0x00:
                if buf:
                    n += 1
                    decode_frame(bytes(buf), direction, n)
                    buf.clear()
            else:
                buf.append(b)
    print(f"\n{n} frame(s) decoded")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "/tmp/tap.hex")
