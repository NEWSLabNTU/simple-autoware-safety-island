# Upstream PR draft

**Opened as https://github.com/eclipse-zenoh/zenoh-pico/pull/1301** (2026-08-30).
Body below is what was submitted; the submitter notes at the end were not.

Repo `eclipse-zenoh/zenoh-pico`, base `main`. Branch `serial-fixes`, two commits:

- `e64e099b` fix(zephyr/serial): bound the read, yield between polls, and report overruns
- `8cdb509c` fix: allow a build with no socket link at all

Title: `fix(serial): make a serial-only build work on a board with no IP stack`

---

## Description

Two things stop zenoh-pico running over serial on an MCU with no network: the
Zephyr UART read is unbounded and silent about errors, and the build cannot be
configured without sockets. Fixed here as one story, since neither alone gets a
serial-only image onto the wire.

### What does this PR do?

**1 -- the Zephyr UART read** (`src/link/transport/serial/uart_zephyr.c`).
It spins on `uart_poll_in` with no timeout, no yield and no error check, and
returns `len` regardless of what happened.

```c
static size_t _z_zephyr_uart_read(_z_sys_net_socket_t sock, uint8_t *ptr, size_t len) {
    for (size_t i = 0; i < len; i++) {
        int res = -1;
        while (res != 0) {
            res = uart_poll_in(sock._serial, &ptr[i]);
        }
    }
    return len;
}
```

- Bounds the wait. New `Z_ZEPHYR_SERIAL_READ_TIMEOUT_MS` (default 1000,
  overridable); returns `SIZE_MAX` on expiry.
- Yields between polls: `k_yield()`, not `z_sleep_ms(1)`. Shortest sleep is a
  whole tick; at 115200 a byte lands every ~87 us, so sleeping drops bytes.
- Checks `uart_err_check` per byte, logs `UART_ERROR_OVERRUN`. Per byte because
  the flag is sticky until read -- that attributes the loss to the damaged byte.

`SIZE_MAX` is not new API. `tty_posix.c` in the same directory already returns
it, and callers already handle it (`_z_read_exact_serial` breaks on it,
`_z_connect_serial` maps it to `_Z_ERR_TRANSPORT_RX_FAILED`). Zephyr was the one
backend that could never produce it.

```c
// src/link/transport/serial/tty_posix.c
ssize_t rb = read(sock._fd, ptr, count);
if (rb <= 0) {
    return SIZE_MAX;
}
```

**2 -- building with no socket link.** Three files chose their implementation
from the *platform* alone, so a platform that merely *could* do sockets took the
socket path even when no socket link was enabled. A serial-only Zephyr image
(`CONFIG_NETWORKING=n`) then failed to compile on `AF_INET` / `AF_INET6` /
`socklen_t` / `struct sockaddr`.

New `Z_HAS_SOCKET_LINK` in `include/zenoh-pico/link/transport/socket.h`:

```c
#if Z_FEATURE_LINK_TCP == 1 || Z_FEATURE_LINK_TLS == 1 || Z_FEATURE_LINK_WS == 1 || \
    Z_FEATURE_LINK_UDP_UNICAST == 1 || Z_FEATURE_LINK_UDP_MULTICAST == 1
#define Z_HAS_SOCKET_LINK 1
#else
#define Z_HAS_SOCKET_LINK 0
#endif
```

- `link/transport/common/address.c`, `link/transport/common/endpoints.c` --
  require it alongside the platform check. Both already carried a
  `_Z_ERR_TRANSPORT_NOT_AVAILABLE` stub for exactly this case; it was simply
  unreachable on a socket-capable platform. No new stubs written.
- `transport/peer.c` -- guard the socket-ownership close on
  `Z_FEATURE_UNICAST_PEER`. Only the peer paths take ownership (`accept.c` and
  `_z_new_peer` pass `owns_socket=true`; the client path passes `false`), so
  with that feature off the branch is dead -- but it still pulled
  `_z_socket_close` into the link.

### Why is this change needed?

Three runtime failure modes, all observed on an NXP MR-CANHUBK344 (S32K344,
Cortex-M7), Zephyr 4.4, zenoh-pico over 115200 to a `zenohd` router.

- **No timeout -> hang.** No exit from the inner loop. A peer that stops
  mid-frame parks the calling thread forever. On a single-core MCU that is
  usually the thread driving the session, so the link does not fail, it hangs --
  the lease never fires because the lease task cannot run.
- **No yield -> starvation.** Under cooperative scheduling, or at equal
  priority, the spin never releases the CPU, including to whoever would refill
  the line.
- **No `uart_err_check` -> silent data loss.** `uart_poll_in` says "no character
  available"; it cannot say "a character was destroyed before you asked". A
  receiver reading only the return value cannot tell a quiet link from one it is
  failing to keep up with.

The third cost the most. It ended in a bug report filed against the peer
implementation. The peer was innocent -- once the flag was read, it was set on
exactly the frame that had been truncated and on no other. The receiver had been
dropping bytes and reporting success.

And the build reason: serial is a legitimate transport for a board with no
network, but requiring an IP stack to compile it is not free on a small MCU --
a Zephyr net stack costs tens of KiB of RAM in an image whose only link is a
UART.

### Open question for reviewers

The overrun is logged, not returned as failure -- the function still returns
`len`. An overrun corrupts the current frame and the framing layer already drops
it on CRC32, so failing the read would tear down a link over recoverable frame
loss. The missing piece was the diagnostic, not the teardown. Happy to switch to
`SIZE_MAX` if you prefer the stricter contract.

### Testing

On `mr_canhubk3/s32k344`, serial only, `CONFIG_NETWORKING=n`, to `rmw_zenohd`,
with ROS 2 on top:

- builds with no IP stack linked; FLASH 326560 B, RAM 285376 B
- session opens and holds, no reconnects across a 3.5 min soak
- steady 2.000 Hz (min 0.464 s, max 0.519 s)
- overrun log fires only on frames actually truncated

No behaviour change for a build that has a socket link, and none on a serial
link that never stalls and never overruns.

### Related Issues

None filed upstream by us.

---

## Submitter notes (not part of the PR body)

- **Sign-off: done.** Both commits carry
  `Signed-off-by: jerry73204 <jerry73204@gmail.com>`. The ECA account must match
  that email. Author name is still `aeon` (same email) -- say the word if you want
  it aligned to `jerry73204`.
- **Expect pushback on `k_yield()`.** It only yields to threads of equal or
  higher priority. If the thread refilling the line is *lower* priority, the read
  now times out instead of hanging -- better, not fixed. A maintainer may ask for
  `k_msleep(0)` or interrupt-driven RX. Worth raising first.
- **Expect a question on `Z_HAS_SOCKET_LINK` living in `socket.h`.** `address.c`
  now includes that header before its own guard so the macro is in scope. If a
  maintainer prefers it in `config.h` (generated from `config.h.in`), that is a
  small move.
