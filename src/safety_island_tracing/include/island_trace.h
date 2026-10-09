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
 * THE TRACE WINDOW (phase8-W17, CONFIG_ISLAND_TRACE_WINDOW, docs/tracing.md
 * section 8). The RAM backend is one-shot from boot, and a board buffer holds
 * seconds, not an act. With the window on, nothing but the provenance enters
 * the stream until the TRIGGER: markers and heartbeats go to a small ring
 * (CONFIG_ISLAND_TRACE_PRE_BYTES). The trigger is the first ENTRY of
 * the contract's detector path (the input-triggered path whose input is a
 * hazard-guarded topic: mrm_handler/call_mrm) after the ARM marker (the take
 * of that guarded input) has carried a non-zero arg, i.e. after the HPC has
 * once said "autonomous available"; the boot-time call_mrm ticks, before
 * Autoware is up, do not trigger. At the trigger the ring's records from the
 * last CONFIG_ISLAND_TRACE_PRE_MS are written in order, then one TRIGGER
 * record, then everything is written straight through until the buffer is
 * full. A per-marker RECORD POLICY, generated from the contract into
 * island_trace_markers.h, applies before and after the trigger:
 *
 *   EVERY    paths that are not timer-triggered, service calls, callbacks
 *            and request takes, and the take of a hazard-guarded input (its
 *            gaps ARE the detection measurement): every occurrence;
 *   CHANGE   other takes and every publish: when the arg differs from the
 *            last recorded one of that marker (and the first after the
 *            trigger);
 *   SPIN     timer-path ENTRY/EXIT: when the ENTRY arg changed, or every
 *            CONFIG_ISLAND_TRACE_SPIN_KEEP-th tick (execution-time samples);
 *            the EXIT follows its ENTRY's decision.
 *
 *     TRIGGER     u32 ts | id+3 | u16 marker | u16 pre_ms | u16 pre_kept |
 *                 u16 spin_keep | u32 pre_lost | u32 filtered    once
 *
 * phase9-W4: a stored nano-ros contract violation (ISLAND_MK_NROS_VIOLATION,
 * forwarded from the executor by the sink in the runtime below) is a second
 * trigger: whichever comes first opens the window, and the TRIGGER record
 * names it.
 *
 * With the window off (native_sim's default) the stream is phase 7's: every
 * marker from boot.
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
#define ISLAND_TRACE_EV_TRIGGER (ISLAND_TRACE_EV_BASE + 3u)
#define ISLAND_TRACE_HEARTBEAT_MS 100

/* The CTF timestamp, in CTF_EVENT's units. The counter is read ONCE:
 * k_cyc_to_ns_floor64() expands its argument twice, and CTF_EVENT's own
 * `k_cyc_to_ns_floor64(k_cycle_get_32())` therefore reads SysTick twice on
 * the board (160 MHz does not divide 1e9, so the conversion splits the count
 * into seconds and remainder, one from each read: a pair that straddles a
 * second boundary is off by ~1 s). Seen in the board disassembly.
 *
 * phase8-W17: the 64-bit count where the timer has one (the board's SysTick
 * driver does at 160 MHz, CORTEX_M_SYSTICK_64BIT_CYCLE_COUNTER). From a u32
 * count the ns value jumped back by 2^30 ns every 2^32 cycles (26.8 s at
 * 160 MHz): not a multiple of 2^32, so the decoder's modular unwrap could not
 * absorb it, and an act is longer than 26.8 s. From the 64-bit count the u32
 * ns wraps only modulo 2^32, which it does absorb. */
static inline uint32_t island_trace_ts(void)
{
#if defined(CONFIG_TIMER_HAS_64BIT_CYCLE_COUNTER)
	const uint64_t cyc = k_cycle_get_64();
#else
	const uint32_t cyc = k_cycle_get_32();
#endif

	return (uint32_t)k_cyc_to_ns_floor64(cyc);
}

/* phase7-W7: the marker's OWN cost on the board, bracketed with DWT CYCCNT
 * (ARMv7-M, the core clock: 160 MHz here). From just before irq_lock() to just
 * before irq_unlock(), i.e. the whole locked write plus the lock itself; the
 * statistics are updated under the same lock, after the second read, so they
 * are not in the measured span. Read over SWD by name: island_trace_cost_*.
 * `island_trace_cost_empty` is the bracket with nothing inside it, measured
 * once at start, to subtract. Board (Cortex-M7) only: native_sim has no DWT,
 * and QEMU does not model its cycle counter. */
#if defined(CONFIG_CPU_CORTEX_M7)
#define ISLAND_TRACE_SELF_COST 1
#define ISLAND_TRACE_DWT_CYCCNT (*(volatile uint32_t *)0xE0001004u)
#ifdef __cplusplus
extern "C" {
#endif
extern volatile uint32_t island_trace_cost_n;
extern volatile uint32_t island_trace_cost_min;
extern volatile uint32_t island_trace_cost_max;
extern volatile uint64_t island_trace_cost_sum;
extern volatile uint32_t island_trace_cost_empty;
#ifdef __cplusplus
}
#endif
static inline void island_trace_cost_note(uint32_t d)
{
	island_trace_cost_n = island_trace_cost_n + 1u;
	island_trace_cost_sum = island_trace_cost_sum + d;
	if (d < island_trace_cost_min) {
		island_trace_cost_min = d;
	}
	if (d > island_trace_cost_max) {
		island_trace_cost_max = d;
	}
}
#else
#define ISLAND_TRACE_SELF_COST 0
#endif

/* One MARKER record into the stream. The caller holds irq_lock. */
static inline void island_trace_put_marker(uint32_t ts, uint16_t marker, uint32_t arg)
{
	const island_trace_evid_t id = (island_trace_evid_t)ISLAND_TRACE_EV_MARKER;
	uint8_t pkt[sizeof(uint32_t) + sizeof(island_trace_evid_t) + sizeof(uint16_t) + sizeof(uint32_t)];
	uint8_t *p = pkt;

	memcpy(p, &ts, sizeof(ts));
	p += sizeof(ts);
	memcpy(p, &id, sizeof(id));
	p += sizeof(id);
	memcpy(p, &marker, sizeof(marker));
	p += sizeof(marker);
	memcpy(p, &arg, sizeof(arg));
	tracing_format_raw_data(pkt, sizeof(pkt));
}

static inline void island_trace_marker(uint16_t marker, uint32_t arg)
{
#if ISLAND_TRACE_SELF_COST
	const uint32_t c0 = ISLAND_TRACE_DWT_CYCCNT;
#endif
	/* Same shape as 4.x CTF_EVENT: timestamp and write under one lock, so
	 * records are in timestamp order in the buffer. */
	const unsigned int key = irq_lock();

	island_trace_put_marker(island_trace_ts(), marker, arg);
#if ISLAND_TRACE_SELF_COST
	island_trace_cost_note(ISLAND_TRACE_DWT_CYCCNT - c0);
#endif
	irq_unlock(key);
}

#if defined(CONFIG_ISLAND_TRACE_WINDOW)
/* The windowed marker (record policy, pre-trigger ring, trigger) keeps state
 * shared by every component, so it is one out-of-line function, defined with
 * the runtime below. */
#define ISLAND_TRACE_WINDOW 1
#ifdef __cplusplus
extern "C" {
#endif
void island_trace_marker_windowed(uint16_t marker, uint32_t arg);
#ifdef __cplusplus
}
#endif
#define ISLAND_TRACE(marker, arg) island_trace_marker_windowed((uint16_t)(marker), (uint32_t)(arg))
#else
#define ISLAND_TRACE_WINDOW 0
#define ISLAND_TRACE(marker, arg) island_trace_marker((uint16_t)(marker), (uint32_t)(arg))
#endif

/* phase9-W4 rerun (nano-ros phase-474 I3; phase 9 W13's F4). nano-ros names a
 * subscription or timer in its trace events only by its executor slot, and
 * registers a C/C++ subscription as `sub#N`: the island cannot ask which slot
 * is which. It learns it instead, in the callback: nano-ros emits a take (25)
 * right before a subscription's callback and a start (18) right before a
 * timer's, on the spin thread, and the sink below remembers the last slot of
 * each. ISLAND_TRACE_TAKE_BIND(input), called first thing in an input's
 * callback, binds that slot to the input (an index of markers.json
 * `nros.take_inputs`), turns on its stamp (nros_trace_set_take(slot, true, 4))
 * and from then on the sink forwards its takes at 281-283.
 * ISLAND_TRACE_TIMER_BIND(every), in a timer's callback, sets that timer's
 * sampling (nros_trace_set_timer_every(slot, every)). Each binds once; after
 * that the call is one compare. */
#if defined(CONFIG_NROS_TRACE_CALLBACKS)
#ifdef __cplusplus
extern "C" {
#endif
void island_trace_take_bind(uint8_t input, uint8_t keep);
void island_trace_timer_bind(uint16_t every);
#ifdef __cplusplus
}
#endif
#define ISLAND_TRACE_TAKE_BIND(input) \
	island_trace_take_bind((uint8_t)ISLAND_TRACE_TAKE_##input, (uint8_t)ISLAND_TRACE_TAKE_KEEP_##input)
#define ISLAND_TRACE_TIMER_BIND(every) island_trace_timer_bind((uint16_t)(every))
#else
#define ISLAND_TRACE_TAKE_BIND(input) ((void)0)
#define ISLAND_TRACE_TIMER_BIND(every) ((void)0)
#endif

#else /* tracing off: nothing is compiled, `arg` is not evaluated */
#define ISLAND_TRACE_ENABLED 0
#define ISLAND_TRACE(marker, arg) ((void)0)
#define ISLAND_TRACE_TAKE_BIND(input) ((void)0)
#define ISLAND_TRACE_TIMER_BIND(every) ((void)0)
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
#if ISLAND_TRACE_SELF_COST
volatile uint32_t island_trace_cost_n;
volatile uint32_t island_trace_cost_min = 0xFFFFFFFFu;
volatile uint32_t island_trace_cost_max;
volatile uint64_t island_trace_cost_sum;
volatile uint32_t island_trace_cost_empty;
#endif
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
#if defined(CONFIG_NROS_TRACE_CALLBACKS)
	";nros_base=" ISLAND_TRACE_STR(ISLAND_TRACE_NROS_BASE)
#endif
#if ISLAND_TRACE_WINDOW
	";window=trigger"
	";trigger_marker=" ISLAND_TRACE_STR(ISLAND_TRACE_TRIGGER_MARKER)
	";arm_marker=" ISLAND_TRACE_STR(ISLAND_TRACE_ARM_MARKER)
	";pre_ms=" ISLAND_TRACE_STR(CONFIG_ISLAND_TRACE_PRE_MS)
	";pre_bytes=" ISLAND_TRACE_STR(CONFIG_ISLAND_TRACE_PRE_BYTES)
	";spin_keep=" ISLAND_TRACE_STR(CONFIG_ISLAND_TRACE_SPIN_KEEP)
#else
	";window=boot"
#endif
	ISLAND_TRACE_KNOBS;

static struct k_timer island_trace_hb_timer;

/* phase9-W4: nano-ros's contract-violation markers into this stream. With
 * CONFIG_NROS_TRACE_CALLBACKS the executor calls the installed sink as
 * sink(id, arg) for its dispatch events (16-20) and, per stored violation,
 * four events 21-24 (rule|seq, endpoint hash, measured, declared; phase-474
 * I1). Those ids overlap the island's own 1..N, so the four are written at
 * ISLAND_TRACE_NROS_BASE + id (generated, island_trace_markers.h) and the
 * dispatch events are dropped: a record per callback would fill the buffer,
 * and the paths the island measures carry their own ENTRY/EXIT. The sink is
 * called on the spin thread, the same as any ISLAND_TRACE call site. */
#if defined(CONFIG_NROS_TRACE_CALLBACKS)
#ifdef __cplusplus
extern "C" {
#endif
void nros_set_trace_sink(void (*sink)(uint32_t, uint32_t));
void nros_trace_set_take(uint8_t handle, bool on, int32_t stamp_offset);
void nros_trace_set_timer_every(uint8_t handle, uint16_t every);

/* phase9-W4 rerun: the take forwarding (see ISLAND_TRACE_TAKE_BIND above).
 * Readable by name over SWD: island_trace_take_slot[i] is input i's slot + 1
 * (0 = not bound yet), island_trace_timer_slot the bound timer's slot + 1. */
volatile uint8_t island_trace_take_slot[ISLAND_TRACE_TAKE_INPUTS];
volatile uint8_t island_trace_timer_slot;
#ifdef __cplusplus
}
#endif
static uint8_t island_trace_take_keep[ISLAND_TRACE_TAKE_INPUTS];
static uint8_t island_trace_take_n[ISLAND_TRACE_TAKE_INPUTS];
static uint32_t island_trace_take_sec[ISLAND_TRACE_TAKE_INPUTS];
static uint8_t island_trace_last_take = 0xFFu;  /* slot of the last take (25) */
static uint8_t island_trace_last_start = 0xFFu; /* slot of an open start (18) */
static uint8_t island_trace_take_cur = 0xFFu;   /* input whose stamp follows */

static void island_trace_nros_sink(uint32_t id, uint32_t arg)
{
	if (id >= ISLAND_TRACE_NROS_FIRST && id <= ISLAND_TRACE_NROS_LAST) {
		ISLAND_TRACE(ISLAND_TRACE_NROS_BASE + id, arg);
		return;
	}
	switch (id) {
	case ISLAND_TRACE_NROS_START:
		island_trace_last_start = (uint8_t)arg;
		return;
	case ISLAND_TRACE_NROS_END:
		island_trace_last_start = 0xFFu;
		return;
	case ISLAND_TRACE_NROS_TAKE: {
		const uint8_t slot = (uint8_t)(arg >> 24);

		island_trace_last_take = slot;
		island_trace_take_cur = 0xFFu;
		for (uint8_t i = 0; i < ISLAND_TRACE_TAKE_INPUTS; i++) {
			if (island_trace_take_slot[i] != (uint8_t)(slot + 1u)) {
				continue;
			}
			island_trace_take_n[i] = (uint8_t)(island_trace_take_n[i] + 1u);
			if (island_trace_take_n[i] >= island_trace_take_keep[i]) {
				island_trace_take_n[i] = 0u;
				island_trace_take_cur = i;
				ISLAND_TRACE(ISLAND_MK_NROS_TAKE, ((uint32_t)i << 24) | (arg & 0x00FFFFFFu));
			}
			break;
		}
		return;
	}
	case ISLAND_TRACE_NROS_TAKE_STAMP_SEC:
		if (island_trace_take_cur < ISLAND_TRACE_TAKE_INPUTS &&
		    island_trace_take_sec[island_trace_take_cur] != arg) {
			island_trace_take_sec[island_trace_take_cur] = arg;
			ISLAND_TRACE(ISLAND_MK_NROS_TAKE_STAMP_SEC, arg);
		}
		return;
	case ISLAND_TRACE_NROS_TAKE_STAMP_NSEC:
		if (island_trace_take_cur < ISLAND_TRACE_TAKE_INPUTS) {
			ISLAND_TRACE(ISLAND_MK_NROS_TAKE_STAMP_NSEC, arg);
		}
		island_trace_take_cur = 0xFFu;
		return;
	default:
		return;
	}
}

void island_trace_take_bind(uint8_t input, uint8_t keep)
{
	if (input >= ISLAND_TRACE_TAKE_INPUTS || island_trace_take_slot[input] != 0u ||
	    island_trace_last_take == 0xFFu) {
		return;
	}
	island_trace_take_keep[input] = keep ? keep : 1u;
	island_trace_take_n[input] = (uint8_t)(island_trace_take_keep[input] - 1u); /* the next one */
	island_trace_take_sec[input] = 0xFFFFFFFFu;
	nros_trace_set_take(island_trace_last_take, true, ISLAND_TRACE_TAKE_STAMP_OFFSET);
	island_trace_take_slot[input] = (uint8_t)(island_trace_last_take + 1u);
}

void island_trace_timer_bind(uint16_t every)
{
	if (island_trace_timer_slot != 0u || island_trace_last_start == 0xFFu) {
		return;
	}
	nros_trace_set_timer_every(island_trace_last_start, every);
	island_trace_timer_slot = (uint8_t)(island_trace_last_start + 1u);
}
#endif

/* One HEARTBEAT record into the stream. The caller holds irq_lock. */
static void island_trace_put_heartbeat(uint32_t ts, uint32_t seq, uint32_t up)
{
	const island_trace_evid_t id = (island_trace_evid_t)ISLAND_TRACE_EV_HEARTBEAT;
	uint8_t pkt[sizeof(uint32_t) + sizeof(island_trace_evid_t) + 2 * sizeof(uint32_t)];
	uint8_t *p = pkt;

	memcpy(p, &ts, sizeof(ts));
	p += sizeof(ts);
	memcpy(p, &id, sizeof(id));
	p += sizeof(id);
	memcpy(p, &seq, sizeof(seq));
	p += sizeof(seq);
	memcpy(p, &up, sizeof(up));
	tracing_format_raw_data(pkt, sizeof(pkt));
}

#if ISLAND_TRACE_WINDOW
/* ---- the trace window (phase8-W17; the head of this file says what) ----
 *
 * The pre-trigger ring holds records already in their stream form, in two
 * halves of CONFIG_ISLAND_TRACE_PRE_BYTES / 2, each filled linearly with whole
 * records; when the current half is full the other one is cleared and becomes
 * current. At the trigger the older half and the current one hold the last
 * half-to-whole ring of records, oldest first, so the flush is: walk the older
 * half to the first record inside pre_ms (reading only timestamps), then TWO
 * tracing_format_raw_data calls, a memcpy each in the RAM backend. Writing the
 * records one by one instead would hold irq_lock for one backend call per
 * record, some 70 of them, at the moment the island reacts. */
#if CONFIG_ISLAND_TRACE_PRE_BYTES < 64 || CONFIG_ISLAND_TRACE_SPIN_KEEP < 1
#error "CONFIG_ISLAND_TRACE_PRE_BYTES must be >= 64 and CONFIG_ISLAND_TRACE_SPIN_KEEP >= 1"
#endif
#define ISLAND_TRACE_HALF (CONFIG_ISLAND_TRACE_PRE_BYTES / 2)
#define ISLAND_TRACE_MK_LEN (sizeof(uint32_t) + sizeof(island_trace_evid_t) + sizeof(uint16_t) + sizeof(uint32_t))
#define ISLAND_TRACE_HB_LEN (sizeof(uint32_t) + sizeof(island_trace_evid_t) + 2 * sizeof(uint32_t))

static const uint8_t island_trace_policy[ISLAND_TRACE_MARKER_COUNT + 1] = ISLAND_TRACE_POLICY_TABLE;
static uint8_t island_trace_pre[2][ISLAND_TRACE_HALF];
static uint16_t island_trace_pre_len[2];
static uint8_t island_trace_pre_cur;
static uint32_t island_trace_last_arg[ISLAND_TRACE_MARKER_COUNT + 1];
static uint8_t island_trace_seen[ISLAND_TRACE_MARKER_COUNT + 1]; /* CHANGE/SPIN: a value is recorded */
static uint8_t island_trace_skip[ISLAND_TRACE_MARKER_COUNT + 1]; /* SPIN_ENTRY: its EXIT is dropped */
static uint16_t island_trace_spins[ISLAND_TRACE_MARKER_COUNT + 1]; /* SPIN_ENTRY: dropped since last kept */
static bool island_trace_armed;

/* Readable by name over SWD / the QEMU monitor (tools/timeline/readout.py). */
#ifdef __cplusplus
extern "C" {
#endif
volatile uint32_t island_trace_triggered;          /* 0 until the trigger */
volatile uint32_t island_trace_trigger_uptime_ms;
volatile uint32_t island_trace_filtered;           /* markers the record policy dropped */
volatile uint32_t island_trace_pre_lost;           /* pre-trigger records not flushed */
volatile uint32_t island_trace_pre_n;              /* pre-trigger records written to the ring */
#ifdef __cplusplus
}
#endif

/* Append one packed record to the ring (the caller holds the lock). */
static void island_trace_pre_put(const uint8_t *rec, uint16_t len)
{
	uint8_t c = island_trace_pre_cur;

	if (island_trace_pre_len[c] + len > ISLAND_TRACE_HALF) {
		c ^= 1u;
		island_trace_pre_cur = c;
		island_trace_pre_len[c] = 0u;
	}
	memcpy(&island_trace_pre[c][island_trace_pre_len[c]], rec, len);
	island_trace_pre_len[c] = (uint16_t)(island_trace_pre_len[c] + len);
	island_trace_pre_n = island_trace_pre_n + 1u;
}

static void island_trace_pack_marker(uint8_t *pkt, uint32_t ts, uint16_t marker, uint32_t arg)
{
	const island_trace_evid_t id = (island_trace_evid_t)ISLAND_TRACE_EV_MARKER;

	memcpy(pkt, &ts, sizeof(ts));
	memcpy(pkt + sizeof(ts), &id, sizeof(id));
	memcpy(pkt + sizeof(ts) + sizeof(id), &marker, sizeof(marker));
	memcpy(pkt + sizeof(ts) + sizeof(id) + sizeof(marker), &arg, sizeof(arg));
}

/* The record policy. Called under the lock, for every marker. */
static bool island_trace_keep(uint16_t m, uint32_t arg)
{
	if (m == 0u || m > ISLAND_TRACE_MARKER_COUNT) {
		return true;
	}
	switch (island_trace_policy[m]) {
	case ISLAND_TRACE_REC_CHANGE:
		if (island_trace_seen[m] && island_trace_last_arg[m] == arg) {
			return false;
		}
		island_trace_seen[m] = 1u;
		island_trace_last_arg[m] = arg;
		return true;
	case ISLAND_TRACE_REC_SPIN_ENTRY: {
		const bool keep = !island_trace_seen[m] || island_trace_last_arg[m] != arg ||
				  island_trace_spins[m] + 1u >= CONFIG_ISLAND_TRACE_SPIN_KEEP;

		island_trace_seen[m] = 1u;
		island_trace_last_arg[m] = arg;
		island_trace_spins[m] = keep ? 0u : (uint16_t)(island_trace_spins[m] + 1u);
		island_trace_skip[m] = keep ? 0u : 1u;
		return keep;
	}
	case ISLAND_TRACE_REC_SPIN_EXIT:
		/* gen_markers.py numbers a path's EXIT right after its ENTRY */
		return !island_trace_skip[m - 1u];
	default: /* ISLAND_TRACE_REC_EVERY */
		return true;
	}
}

/* The trigger: the ring's records from the last pre_ms, oldest first, then
 * the TRIGGER record; from here on records go straight to the stream. */
static uint16_t island_trace_rec_len(const uint8_t *rec)
{
	island_trace_evid_t id;

	memcpy(&id, rec + sizeof(uint32_t), sizeof(id));
	return (uint16_t)(id == ISLAND_TRACE_EV_HEARTBEAT ? ISLAND_TRACE_HB_LEN : ISLAND_TRACE_MK_LEN);
}

static void island_trace_fire(uint32_t now, uint16_t m)
{
	const uint8_t cur = island_trace_pre_cur;
	const uint8_t old = cur ^ 1u;
	const uint64_t pre_ns = (uint64_t)CONFIG_ISLAND_TRACE_PRE_MS * 1000000u;
	const uint8_t *seg[2] = {island_trace_pre[old], island_trace_pre[cur]};
	const uint16_t seg_len[2] = {island_trace_pre_len[old], island_trace_pre_len[cur]};
	uint64_t rel = 0u;
	uint64_t now_rel;
	uint32_t prev = 0u;
	bool have = false;
	uint32_t kept = 0u;

	/* A record's age cannot be `now - ts` in u32: the stamp wraps every
	 * 4.29 s and the older half can reach further back than that (at the
	 * pre-trigger rate a half lasts about 3 s). The ring is in time order and
	 * a heartbeat enters it every 100 ms, so consecutive stamps are close:
	 * sum their u32 differences into a 64-bit time since the oldest record
	 * (pass 1), then keep the records within pre_ms of `now` (pass 2). */
	for (int h = 0; h < 2; h++) {
		for (uint16_t off = 0u; off < seg_len[h]; off = (uint16_t)(off + island_trace_rec_len(seg[h] + off))) {
			uint32_t ts;

			memcpy(&ts, seg[h] + off, sizeof(ts));
			rel += have ? (uint32_t)(ts - prev) : 0u;
			prev = ts;
			have = true;
		}
	}
	now_rel = have ? rel + (uint32_t)(now - prev) : 0u;
	rel = 0u;
	have = false;
	for (int h = 0; h < 2; h++) {
		uint16_t start = seg_len[h];

		for (uint16_t off = 0u; off < seg_len[h]; off = (uint16_t)(off + island_trace_rec_len(seg[h] + off))) {
			uint32_t ts;

			memcpy(&ts, seg[h] + off, sizeof(ts));
			rel += have ? (uint32_t)(ts - prev) : 0u;
			prev = ts;
			have = true;
			if (start == seg_len[h] && now_rel - rel <= pre_ns) {
				start = off;
			}
			if (start != seg_len[h]) {
				kept++;
			}
		}
		if (start < seg_len[h]) {
			tracing_format_raw_data((uint8_t *)seg[h] + start, (uint32_t)(seg_len[h] - start));
		}
	}
	island_trace_pre_lost = island_trace_pre_n - kept;
	{
		const island_trace_evid_t id = (island_trace_evid_t)ISLAND_TRACE_EV_TRIGGER;
		const uint16_t f16[4] = {m, (uint16_t)CONFIG_ISLAND_TRACE_PRE_MS, (uint16_t)kept,
					 (uint16_t)CONFIG_ISLAND_TRACE_SPIN_KEEP};
		const uint32_t f32[2] = {island_trace_pre_lost, island_trace_filtered};
		uint8_t pkt[sizeof(uint32_t) + sizeof(island_trace_evid_t) + sizeof(f16) + sizeof(f32)];

		memcpy(pkt, &now, sizeof(now));
		memcpy(pkt + sizeof(now), &id, sizeof(id));
		memcpy(pkt + sizeof(now) + sizeof(id), f16, sizeof(f16));
		memcpy(pkt + sizeof(now) + sizeof(id) + sizeof(f16), f32, sizeof(f32));
		tracing_format_raw_data(pkt, sizeof(pkt));
	}
	/* The first of every CHANGE and SPIN marker after the trigger is kept:
	 * "the first X after the fault" must not depend on what came before. */
	memset(island_trace_seen, 0, sizeof(island_trace_seen));
	memset(island_trace_spins, 0, sizeof(island_trace_spins));
	island_trace_trigger_uptime_ms = k_uptime_get_32();
	island_trace_triggered = 1u;
}

void island_trace_marker_windowed(uint16_t marker, uint32_t arg)
{
#if ISLAND_TRACE_SELF_COST
	const uint32_t c0 = ISLAND_TRACE_DWT_CYCCNT;
#endif
	const unsigned int key = irq_lock();
	const uint32_t ts = island_trace_ts();

	if (!island_trace_triggered) {
		if (marker == ISLAND_TRACE_ARM_MARKER && arg != 0u) {
			island_trace_armed = true;
		}
		/* phase9-W4: a stored contract violation opens the window too, so
		 * its four records, and the callbacks it judged (the pre-trigger
		 * history), are in the buffer whenever it happens. */
		if ((island_trace_armed && marker == ISLAND_TRACE_TRIGGER_MARKER) ||
		    marker == ISLAND_MK_NROS_VIOLATION) {
			island_trace_fire(ts, marker);
		}
	}
	if (!island_trace_keep(marker, arg)) {
		island_trace_filtered = island_trace_filtered + 1u;
	} else if (island_trace_triggered) {
		island_trace_put_marker(ts, marker, arg);
	} else {
		uint8_t pkt[ISLAND_TRACE_MK_LEN];

		island_trace_pack_marker(pkt, ts, marker, arg);
		island_trace_pre_put(pkt, (uint16_t)sizeof(pkt));
	}
#if ISLAND_TRACE_SELF_COST
	island_trace_cost_note(ISLAND_TRACE_DWT_CYCCNT - c0);
#endif
	irq_unlock(key);
}
#endif /* ISLAND_TRACE_WINDOW */

static void island_trace_heartbeat(struct k_timer *timer)
{
	(void)timer;
	const unsigned int key = irq_lock();
	const uint32_t ts = island_trace_ts();
	const uint32_t seq = island_trace_hb_seq;
	const uint32_t up = k_uptime_get_32();

	island_trace_hb_seq = seq + 1u;
	island_trace_hb_last_uptime_ms = up;
#if ISLAND_TRACE_WINDOW
	if (!island_trace_triggered) {
		const island_trace_evid_t id = (island_trace_evid_t)ISLAND_TRACE_EV_HEARTBEAT;
		uint8_t pkt[ISLAND_TRACE_HB_LEN];

		memcpy(pkt, &ts, sizeof(ts));
		memcpy(pkt + sizeof(ts), &id, sizeof(id));
		memcpy(pkt + sizeof(ts) + sizeof(id), &seq, sizeof(seq));
		memcpy(pkt + sizeof(ts) + sizeof(id) + sizeof(seq), &up, sizeof(up));
		island_trace_pre_put(pkt, (uint16_t)sizeof(pkt));
		irq_unlock(key);
		return;
	}
#endif
	island_trace_put_heartbeat(ts, seq, up);
	irq_unlock(key);
}

static int island_trace_start(void)
{
	const island_trace_evid_t id = (island_trace_evid_t)ISLAND_TRACE_EV_PROVENANCE;
	const uint16_t len = (uint16_t)(sizeof(island_trace_provenance) - 1u);
	uint8_t hdr[sizeof(uint32_t) + sizeof(island_trace_evid_t) + sizeof(uint16_t)];
	const unsigned int key = irq_lock();
	const uint32_t ts = island_trace_ts();
	uint8_t *p = hdr;

	/* Header and string as two writes under the one lock (the lock nests):
	 * the backend appends them back to back, and no static staging copy of
	 * the string is needed (it cost 776 B of RAM, docs/tracing.md sec. 6). */
	memcpy(p, &ts, sizeof(ts));
	p += sizeof(ts);
	memcpy(p, &id, sizeof(id));
	p += sizeof(id);
	memcpy(p, &len, sizeof(len));
	tracing_format_raw_data(hdr, sizeof(hdr));
	tracing_format_raw_data((uint8_t *)island_trace_provenance, len);
	irq_unlock(key);

#if ISLAND_TRACE_SELF_COST
	/* DEMCR.TRCENA, the DWT lock access register (the M7 has one), CTRL.CYCCNTENA. */
	*(volatile uint32_t *)0xE000EDFCu |= (1u << 24);
	*(volatile uint32_t *)0xE0001FB0u = 0xC5ACCE55u;
	*(volatile uint32_t *)0xE0001000u |= 1u;
	{
		const unsigned int k2 = irq_lock();
		const uint32_t e0 = ISLAND_TRACE_DWT_CYCCNT;

		island_trace_cost_empty = ISLAND_TRACE_DWT_CYCCNT - e0;
		irq_unlock(k2);
	}
#endif
#if defined(CONFIG_NROS_TRACE_CALLBACKS)
	nros_set_trace_sink(island_trace_nros_sink);
#endif
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
#if ISLAND_TRACE_WINDOW
	nsi_print_trace("island_trace: window triggered=%u at uptime %u ms, pre-trigger records %u "
			"(%u not flushed), policy dropped %u markers\n",
			island_trace_triggered, island_trace_trigger_uptime_ms, island_trace_pre_n,
			island_trace_pre_lost, island_trace_filtered);
#endif
}
NATIVE_TASK(island_trace_dump, ON_EXIT, 10);
#endif /* CONFIG_ARCH_POSIX */

#endif /* ISLAND_TRACE_DEFINE_RUNTIME && ISLAND_TRACE_ENABLED */

#endif /* ISLAND_TRACE_H */
