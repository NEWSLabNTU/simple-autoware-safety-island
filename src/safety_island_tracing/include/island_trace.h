/* Island trace markers (phase7-W1). Authored; the ids it uses are generated.
 *
 * ONE macro for the components:
 *
 *     ISLAND_TRACE(ISLAND_MK_<marker>, arg);
 *
 * It is a no-op -- `arg` is not even evaluated -- unless the image is a Zephyr
 * build with CONFIG_TRACING_CTF and CONFIG_TRACING_BACKEND_RAM. The marker ids
 * come from island_trace_markers.h, generated from the island contract by
 * ../gen_markers.py; docs/tracing.md is the table of what each one means.
 *
 * WHAT IT WRITES. One record into Zephyr's CTF stream, laid out exactly like a
 * CTF event so the stream stays one format:
 *
 *     u32 timestamp_ns | event id | u16 marker | u32 arg
 *
 * The event id is 0xE0 on Zephyr 3.x (CTF ids are u8 there, the tree uses up
 * to 0x5B) and 0x1E0 on Zephyr 4.x (u16 ids, the tree uses up to 0xFF): 11
 * bytes per marker on the native_sim line, 12 on the board line. Two more
 * record types come from the runtime below, emitted once per image:
 *
 *     HEARTBEAT   u32 ts | id+1 | u32 seq | u32 uptime_ms     every 100 ms
 *     PROVENANCE  u32 ts | id+2 | u16 len | len bytes ASCII   once, at boot
 *
 * The heartbeat's `seq` is a monotonic counter: a gap in it is a lost record,
 * and on native_sim the dump trailer records the counter's final value, so a
 * buffer that filled before the run ended says so instead of looking short.
 *
 * WHY tracing_format_raw_data AND NOT sys_trace_named_event: the native_sim
 * image is on Zephyr 3.7, whose CTF has no user or named event at all; 4.4
 * has sys_trace_named_event, but it carries a 20-byte name string per event
 * (32 bytes a marker). The raw record is the same call the CTF_EVENT macro
 * ends in, taken under the same TRACING_LOCK (irq_lock) in the backend.
 *
 * The runtime (heartbeat, provenance, native_sim buffer dump) is compiled in
 * exactly one translation unit, the one that defines ISLAND_TRACE_DEFINE_RUNTIME
 * before including this header (mrm_handler_core.cpp). */
#ifndef ISLAND_TRACE_H
#define ISLAND_TRACE_H

#define ISLAND_TRACE_STR_(x) #x
#define ISLAND_TRACE_STR(x) ISLAND_TRACE_STR_(x)

#include "island_trace_markers.h"

#if defined(__ZEPHYR__) && defined(CONFIG_TRACING_CTF) && defined(CONFIG_TRACING_BACKEND_RAM)
#define ISLAND_TRACE_ENABLED 1

#include <string.h>
#include <zephyr/kernel.h>
#include <zephyr/version.h>
#include <zephyr/tracing/tracing_format.h>

#if KERNEL_VERSION_MAJOR >= 4
typedef uint16_t island_trace_evid_t;
#define ISLAND_TRACE_EV_BASE 0x1E0u
#else
typedef uint8_t island_trace_evid_t;
#define ISLAND_TRACE_EV_BASE 0xE0u
#endif
#define ISLAND_TRACE_EV_MARKER (ISLAND_TRACE_EV_BASE + 0u)
#define ISLAND_TRACE_EV_HEARTBEAT (ISLAND_TRACE_EV_BASE + 1u)
#define ISLAND_TRACE_EV_PROVENANCE (ISLAND_TRACE_EV_BASE + 2u)
#define ISLAND_TRACE_HEARTBEAT_MS 100

/* The CTF timestamp, in CTF_EVENT's units. The counter is read ONCE:
 * k_cyc_to_ns_floor64() expands its argument twice, and CTF_EVENT's own
 * `k_cyc_to_ns_floor64(k_cycle_get_32())` therefore reads SysTick twice on
 * the board (160 MHz does not divide 1e9, so the conversion splits the count
 * into seconds and remainder, one from each read: a pair that straddles a
 * second boundary is off by ~1 s). Seen in the board disassembly. */
static inline uint32_t island_trace_ts(void)
{
	const uint32_t cyc = k_cycle_get_32();

	return (uint32_t)k_cyc_to_ns_floor64(cyc);
}

static inline void island_trace_marker(uint16_t marker, uint32_t arg)
{
	const island_trace_evid_t id = (island_trace_evid_t)ISLAND_TRACE_EV_MARKER;
	uint8_t pkt[sizeof(uint32_t) + sizeof(island_trace_evid_t) + sizeof(uint16_t) + sizeof(uint32_t)];
	/* Same shape as 4.x CTF_EVENT: timestamp and write under one lock, so
	 * records are in timestamp order in the buffer. */
	const unsigned int key = irq_lock();
	const uint32_t ts = island_trace_ts();
	uint8_t *p = pkt;

	memcpy(p, &ts, sizeof(ts));
	p += sizeof(ts);
	memcpy(p, &id, sizeof(id));
	p += sizeof(id);
	memcpy(p, &marker, sizeof(marker));
	p += sizeof(marker);
	memcpy(p, &arg, sizeof(arg));
	tracing_format_raw_data(pkt, sizeof(pkt));
	irq_unlock(key);
}

#define ISLAND_TRACE(marker, arg) island_trace_marker((uint16_t)(marker), (uint32_t)(arg))

#else /* tracing off: nothing is compiled, `arg` is not evaluated */
#define ISLAND_TRACE_ENABLED 0
#define ISLAND_TRACE(marker, arg) ((void)0)
#endif

/* ------------------------------------------------------------------------ */
#if defined(ISLAND_TRACE_DEFINE_RUNTIME) && ISLAND_TRACE_ENABLED

#include <zephyr/init.h>

/* Readable by name over SWD on the board (docs/tracing.md, trace-board). */
#ifdef __cplusplus
extern "C" {
#endif
volatile uint32_t island_trace_hb_seq;
volatile uint32_t island_trace_hb_last_uptime_ms;
#ifdef __cplusplus
}
#endif

static const char island_trace_provenance[] =
	"island-trace/1"
	";zephyr=" KERNEL_VERSION_STRING
	";board=" CONFIG_BOARD
	";contract_sha256=" ISLAND_TRACE_CONTRACT_SHA256
	";markers=" ISLAND_TRACE_STR(ISLAND_TRACE_MARKER_COUNT)
	";table_sha256=" ISLAND_TRACE_TABLE_SHA256
	";entities=" ISLAND_TRACE_ENTITIES
	";heartbeat_ms=" ISLAND_TRACE_STR(ISLAND_TRACE_HEARTBEAT_MS)
	ISLAND_TRACE_KNOBS;

static struct k_timer island_trace_hb_timer;

static void island_trace_heartbeat(struct k_timer *timer)
{
	(void)timer;
	const island_trace_evid_t id = (island_trace_evid_t)ISLAND_TRACE_EV_HEARTBEAT;
	uint8_t pkt[sizeof(uint32_t) + sizeof(island_trace_evid_t) + 2 * sizeof(uint32_t)];
	const unsigned int key = irq_lock();
	const uint32_t ts = island_trace_ts();
	const uint32_t seq = island_trace_hb_seq;
	const uint32_t up = k_uptime_get_32();
	uint8_t *p = pkt;

	island_trace_hb_seq = seq + 1u;
	island_trace_hb_last_uptime_ms = up;
	memcpy(p, &ts, sizeof(ts));
	p += sizeof(ts);
	memcpy(p, &id, sizeof(id));
	p += sizeof(id);
	memcpy(p, &seq, sizeof(seq));
	p += sizeof(seq);
	memcpy(p, &up, sizeof(up));
	tracing_format_raw_data(pkt, sizeof(pkt));
	irq_unlock(key);
}

static int island_trace_start(void)
{
	const island_trace_evid_t id = (island_trace_evid_t)ISLAND_TRACE_EV_PROVENANCE;
	const uint16_t len = (uint16_t)(sizeof(island_trace_provenance) - 1u);
	static uint8_t pkt[sizeof(uint32_t) + sizeof(island_trace_evid_t) + sizeof(uint16_t) +
			   sizeof(island_trace_provenance)];
	const unsigned int key = irq_lock();
	const uint32_t ts = island_trace_ts();
	uint8_t *p = pkt;

	memcpy(p, &ts, sizeof(ts));
	p += sizeof(ts);
	memcpy(p, &id, sizeof(id));
	p += sizeof(id);
	memcpy(p, &len, sizeof(len));
	p += sizeof(len);
	memcpy(p, island_trace_provenance, len);
	p += len;
	tracing_format_raw_data(pkt, (uint32_t)(p - pkt));
	irq_unlock(key);

	k_timer_init(&island_trace_hb_timer, island_trace_heartbeat, NULL);
	k_timer_start(&island_trace_hb_timer, K_MSEC(ISLAND_TRACE_HEARTBEAT_MS),
		      K_MSEC(ISLAND_TRACE_HEARTBEAT_MS));
	return 0;
}

/* After tracing_init (APPLICATION 0), which enables the stream. */
SYS_INIT(island_trace_start, APPLICATION, 90);

#if defined(CONFIG_ARCH_POSIX)
/* native_sim: write the RAM buffer to the file named by --trace-out=<path>
 * when the process exits (--stop_at, SIGTERM or SIGINT all run ON_EXIT
 * tasks). The recipe creates the file first: nsi_host_open() passes flags
 * straight to the host's open(2) with no mode argument, so the dump opens an
 * existing file (O_WRONLY|O_TRUNC, Linux values) rather than creating one.
 *
 * File layout (little-endian u32 unless noted):
 *   "ISLTRC01" | header_len (36) | zephyr_version (0xMMmmpp) |
 *   buffer_size | heartbeats_emitted | heartbeat_ms |
 *   last_heartbeat_uptime_ms | dumped_len | ram_tracing[0 .. dumped_len)
 * dumped_len stops at the last non-zero byte: the backend zeroes the buffer
 * at init and keeps its fill position static, so trailing zeros are unused
 * space (a record never starts with id 0). */
#include <posix_native_task.h>
#include <cmdline.h>
#include <nsi_host_trampolines.h>
#include <nsi_tracing.h>

#ifdef __cplusplus
extern "C" {
#endif
extern uint8_t ram_tracing[];
#ifdef __cplusplus
}
#endif

static char *island_trace_out;

static void island_trace_register_opts(void)
{
	static struct args_struct_t opts[] = {
		{false, false, false, (char *)"trace-out", (char *)"path", 's',
		 (void *)&island_trace_out, NULL,
		 (char *)"Write the RAM trace buffer to this (existing) file at exit"},
		ARG_TABLE_ENDMARKER,
	};
	native_add_command_line_opts(opts);
}
NATIVE_TASK(island_trace_register_opts, PRE_BOOT_1, 50);

static void island_trace_dump(void)
{
	if (island_trace_out == NULL) {
		return;
	}
	uint32_t used = CONFIG_RAM_TRACING_BUFFER_SIZE;
	while (used > 0u && ram_tracing[used - 1u] == 0u) {
		used--;
	}
	const uint32_t hdr[9] = {
		0x544c5349u, 0x31304352u, /* "ISLTRC01" */
		(uint32_t)sizeof(hdr), (uint32_t)KERNEL_VERSION_NUMBER,
		(uint32_t)CONFIG_RAM_TRACING_BUFFER_SIZE, island_trace_hb_seq,
		(uint32_t)ISLAND_TRACE_HEARTBEAT_MS, island_trace_hb_last_uptime_ms,
		used,
	};
	const int fd = nsi_host_open(island_trace_out, 01 | 01000 /* O_WRONLY|O_TRUNC */);

	if (fd < 0) {
		nsi_print_warning("island_trace: cannot open %s (create it first)\n", island_trace_out);
		return;
	}
	(void)nsi_host_write(fd, hdr, sizeof(hdr));
	(void)nsi_host_write(fd, ram_tracing, used);
	(void)nsi_host_close(fd);
	nsi_print_trace("island_trace: %u of %u buffer bytes, %u heartbeats -> %s\n", used,
			(unsigned)CONFIG_RAM_TRACING_BUFFER_SIZE, island_trace_hb_seq,
			island_trace_out);
}
NATIVE_TASK(island_trace_dump, ON_EXIT, 10);
#endif /* CONFIG_ARCH_POSIX */

#endif /* ISLAND_TRACE_DEFINE_RUNTIME && ISLAND_TRACE_ENABLED */

#endif /* ISLAND_TRACE_H */
