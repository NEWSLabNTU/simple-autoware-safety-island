// The application's console prints, behind one switch.
//
// phase9 (spin latency, I10): the MRM handler's std::printf lines in the
// reaction tick cost 4.9 ms each on the board's 115,200-baud console, which
// nothing reads (lpuart0 is unwired), and sat inside the route figure and
// the spin's release jitter. On the board CONFIG_ISLAND_APP_CONSOLE is off
// and ISLAND_PRINTF compiles to nothing; native_sim and QEMU, whose
// consoles are read, keep it on. A host build (no Zephyr) prints as before.
// The arguments stay in the expression so a value computed only for a
// print is still "used" and no warning changes with the switch.
#pragma once
#include <cstdio>
#if defined(__ZEPHYR__)
#include <zephyr/autoconf.h>
#endif
#if defined(CONFIG_ISLAND_APP_CONSOLE) || !defined(__ZEPHYR__)
#define ISLAND_APP_CONSOLE 1
#else
#define ISLAND_APP_CONSOLE 0
#endif
#define ISLAND_PRINTF(...)                 \
  do {                                     \
    if (ISLAND_APP_CONSOLE) {              \
      std::printf(__VA_ARGS__);            \
    }                                      \
  } while (0)
