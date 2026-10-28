/*
 * The rung that does not need the executor (phase11-S4,
 * docs/roadmap/phase-11-supervised-budgets.md; CONFIG_ISLAND_SUPERVISOR).
 *
 * A supervised route has a due time. A k_timer is re-armed to the earliest
 * due of the armed routes; its expiry function (ISR) gives a semaphore that a
 * reaction thread, above the spin thread's priority, waits on. The thread
 * judges which route is past its due, records the verdict
 * (SUPERVISOR_DEADLINE) and drives the safe-state output
 * (SUPERVISOR_SAFE_STATE): CAN LED1 (PTE5, gpio-leds node can_led1 of the
 * MR-CANHUBK344 board DTS, active low), standing in for a brake line. It
 * never touches the executor or the zenoh session, which are not
 * thread-safe and may be what is stuck: its action bypasses the stack.
 *
 * SWT0 (CONFIG_ISLAND_SUPERVISOR_SWT): the S32K344's software watchdog is
 * started at the first spin; its first timeout interrupts, and the callback
 * wakes the same thread for the same action, so a hung executor is caught
 * with no route pending.
 *
 * Levels (nano-ros phase-509 I1, RFC-0108 D8). Every thread that spins an
 * executor is a level: a tier today, a preemption level once RFC-0108 lands.
 * Each spin checks its level in, and SWT0 is fed only once every level that
 * has spun has checked in since the last feed, so a level blocked behind a
 * stuck callback starves the watchdog even while another level spins on.
 * With one level that is a feed per spin, as before. Route 1 belongs to one
 * level: the one that hosts mrm_handler, named by nano-ros (phase-509 P7):
 * the generated NROS_ENTRY_LEVEL_OF_MRM_HANDLER against the level the spin
 * runs (spin_hook.c: the adopted level's nros_cpp_spin_once, a spawned
 * level's nros_cpp_level_spin_once; since P9b every level works on the core's
 * one executor, so the executor cannot say). Only that level arms
 * or clears it, and its executor is the one whose route cells the reaction
 * thread reads; a level with no supervised rows can no longer disarm the
 * route another level armed. Whether every level is alive is nano-ros's
 * aggregate too (nros_cpp_levels_take_alive): every executor spin checks its
 * level in, and the feed takes the round only once all of them have. The feed and gap statistics are
 * written under the lock, since several threads write them. The second
 * consecutive timeout resets the MCU; once the output is latched the
 * reaction thread feeds SWT0 itself, leaving the reset to a reaction thread
 * that cannot run (a reset would also release the output).
 *
 * Who arms a route. Until nano-ros carries a deadline-armed route monitor
 * with a reaction hook (phase-11 S3), the MRM handler arms its one
 * supervised route itself (mrm_handler_core.cpp): every take of the
 * availability sets the due of the hpc_loss reaction to take + max_age +
 * call_mrm, and the call_mrm EXIT of a tick that saw the loss clears it.
 *
 * The direct emergency path (phase11-S6, decision 2). Driving the output
 * is not the emergency stop by itself: the vehicle brakes on the island's
 * emergency state and command. So once the output is latched the thread also
 * calls each registered direct function (island_supervisor_set_direct): the
 * handler's publishes mrm_state MRM_OPERATING / EMERGENCY_STOP and the hazard
 * lights, the emergency operator's publishes its braking command, at once and
 * then every CONFIG_ISLAND_SUPERVISOR_DIRECT_PERIOD_MS (the operator's own
 * 30 Hz), until that component's executor path reports the emergency running
 * (island_supervisor_handover). Why this is safe against the spin thread,
 * which may be the one stuck (in the callback that owns the handler's state):
 *   - the direct functions read and write only messages they own, never the
 *     component's spin-thread state, and use only publishers built at
 *     construction, which live as long as the image;
 *   - a publish goes to zenoh-pico, built with Z_FEATURE_MULTI_THREAD
 *     (CONFIG_NROS_ZENOH_MULTI_THREAD=y), whose transport serialises
 *     writers under its tx mutex; a k_mutex inherits priority, so a spin
 *     thread inside a publish when the deadline fires finishes it first;
 *   - no service call, no executor, no take: nothing that dispatches;
 *   - the handler reads island_supervisor_latched() at every tick and holds
 *     the emergency stop from then on, so a spin thread that resumes (an
 *     overrun rather than a stall) enters the same state through its normal
 *     path, and hands over; a stall that never ends leaves the direct path
 *     publishing until reset.
 * A spin thread that resumes after an overrun may finish the tick it was in
 * with the state it had computed before the latch; the next tick reads the
 * latch.
 *
 * Route 1 at its expiry (the late notice, rtss-work-2026-demo:carla-island-demo.md). The k_timer
 * is armed after every spin from the executor's earliest pending due, but the
 * route is answered when the dispatch that publishes its output ENDS, inside
 * the spin: a spin that answered in time and then ran past the due used to
 * find route 1 still armed here and latched, though the executor judged it on
 * time. So at the expiry the thread asks the executor's own route cells
 * (nano-ros RouteWatch, phase-503 W7: atomics the executor clears at the
 * answer, on its microsecond clock; read from this thread, never touching the
 * executor): a take still unanswered at or after its deadline is the miss,
 * judged at the same instant as before; an answered route is not; a later
 * take re-arms the timer to its own due. An answer between the executor's due
 * and the timer's (at most 1 ms, the rounding up) reads as answered here, and
 * the executor judged it overdue at completion and called the reaction hook,
 * which latches.
 *
 * Route 2 (phase11-S6, decision 4): the comfortable stop's standstill. Its
 * due is the comfortable call + settle + response at the entry speed + how
 * late the island sees a standstill (a kinematic_state period + the link); at
 * the due the thread judges the speed the handler last noted from
 * kinematic_state (island_supervisor_note_speed): fresh and below 1 mm/s is
 * standstill and the route is met; otherwise the comfortable stop failed
 * and the output is latched, which commands the emergency stop as above.
 *
 * Everything is readable by name over SWD (island_supervisor_record,
 * tools/board/violations.py supervisor).
 */
#include <stdbool.h>
#include <stdint.h>
#include <string.h>
#include <zephyr/device.h>
#include <zephyr/drivers/gpio.h>
#include <zephyr/init.h>
#include <zephyr/kernel.h>
#include <zephyr/spinlock.h>
#if defined(CONFIG_ISLAND_SUPERVISOR_SWT)
#include <zephyr/drivers/watchdog.h>
#endif

#include <rclcpp/detail/nros_cpp_ffi.h>

#include "../../safety_island_tracing/include/island_trace.h"
#include "island_supervisor.h"

/*
 * phase13-D4: the reaction thread's priority comes from the priority plan the
 * executor's tier was allocated from (nano-ros RFC-0079; the header is written
 * beside the generated entry by `nros codegen entry`). The contract supervises
 * mrm_handler/call_mrm, so nano-ros reserves a priority above the transport
 * band for the supervisor of that deadline:
 * NROS_PRIORITY_PLAN_SUPERVISOR_PRIORITY. A level goes above the transport
 * only when a tier names it (`above = "transport"`, nano-ros #1967); the
 * levels are derived (no tier table), so on this image: mrm_handler's level
 * 5, the operators' 7 and 8 in pool.app, transport 4, reaction 3.
 */
#include <nros_priority_plan.h>

#if !NROS_PRIORITY_PLAN_FROM_IMAGE
#error "the priority plan is the Kconfig projection, not this image's (no --dotconfig)"
#endif
#if !NROS_PRIORITY_PLAN_SMALLER_IS_URGENT
#error "the supervisor's arithmetic assumes Zephyr's smaller-is-urgent priorities"
#endif
/* nano-ros phase-509 P7: the level that hosts the supervised node owns route 1. */
#if !defined(NROS_ENTRY_LEVEL_OF_MRM_HANDLER)
#error "nros_priority_plan.h names no level for mrm_handler (nano-ros phase-509 P7)"
#endif
/* The handler's level is the most urgent one (level 0), so the plan's most
 * urgent priority is the one the record checks its thread against. */
#if NROS_ENTRY_LEVEL_OF_MRM_HANDLER != 0
#error "mrm_handler is not on the most urgent level: prio_plan_tier would name another level"
#endif
#if NROS_ENTRY_TIER_COUNT < 1
#error "the entry runs no tier: the executor's priority is not from the plan"
#endif
#ifndef NROS_PRIORITY_PLAN_SUPERVISOR_PRIORITY
#error "the plan reserves no supervisor priority: no supervised deadline was allocated above the transport"
#endif
#define ISLAND_SUPERVISOR_PRIORITY NROS_PRIORITY_PLAN_SUPERVISOR_PRIORITY
BUILD_ASSERT(ISLAND_SUPERVISOR_PRIORITY < NROS_ENTRY_TIERS_MOST_URGENT_PRIORITY,
	     "the reaction thread must run above every executor tier");
BUILD_ASSERT(ISLAND_SUPERVISOR_PRIORITY < NROS_PRIORITY_PLAN_RESERVED_TRANSPORT_LO,
	     "the reaction thread must run above the transport band");
BUILD_ASSERT(ISLAND_SUPERVISOR_PRIORITY < CONFIG_MAIN_THREAD_PRIORITY,
	     "the reaction thread must run above registration");
BUILD_ASSERT(ISLAND_SUPERVISOR_PRIORITY >= 0, "the reaction thread stays preemptible");

#define ISLAND_SUPERVISOR_MAGIC 0x56505553u /* "SUPV" little-endian */

/* Layout read by tools/board/violations.py; all 32-bit. */
struct island_supervisor_route {
	uint32_t armed;      /* 1 while a due is pending */
	uint32_t due_ms;     /* uptime ms of the current due */
	uint32_t arms;       /* arm calls, all time */
	uint32_t dones;      /* done calls that found the route armed */
	uint32_t fired;      /* deadline verdicts */
	uint32_t fire_due_ms;      /* the due of the first verdict */
	uint32_t fire_verdict_us;  /* the first verdict's uptime, us (low 32) */
};

struct island_supervisor_direct {
	uint32_t registered;         /* a function is set */
	uint32_t calls;              /* direct-path calls */
	uint32_t first_uptime_us;    /* the first one, us (low 32) */
	uint32_t handover;           /* the executor path took over */
	uint32_t handover_uptime_ms; /* when */
};

/* nano-ros phase-509 I1: one executor level (a thread that spins one). */
struct island_supervisor_level {
	uint32_t spins;          /* this level's spins */
	uint32_t gap_max_us;     /* its longest spin-to-spin gap */
	uint32_t gap_max_at_ms;  /* when it ended */
	int32_t prio;            /* its thread's priority at its first spin */
	uint32_t route_foreign;  /* supervised dues it reported for route 1, not its own */
	char name[16];           /* its thread's name */
	uint32_t nros_level;     /* nano-ros level it spins (P9b), 0xFF unknown */
};

struct island_supervisor_record {
	uint32_t magic;
	uint32_t latched;            /* the safe-state output is driven */
	uint32_t latch_cause;        /* 1 route deadline, 2 SWT0 first timeout */
	uint32_t latch_uptime_us;    /* when it was driven, us (low 32) */
	uint32_t wakes;              /* reaction thread wake-ups */
	uint32_t timer_expiries;     /* k_timer expiry ISR runs */
	uint32_t swt_started;        /* SWT0 running */
	uint32_t swt_timeout_ms;     /* its timeout */
	uint32_t swt_fires;          /* SWT0 first-timeout callbacks */
	uint32_t swt_fire_uptime_us; /* the first one, us (low 32) */
	uint32_t swt_errors;         /* failed install/setup/feed */
	uint32_t spins;              /* spins seen (feeds) */
	uint32_t spin_gap_max_us;    /* longest feed-to-feed gap since the SWT0 start */
	uint32_t spin_gap_max_at_ms; /* when it ended */
	uint32_t gpio_errors;
	uint32_t routes;             /* ISLAND_SUPERVISOR_ROUTES */
	uint32_t hook_calls;         /* nros_app_reaction_hook calls (phase-503) */
	uint32_t hook_last_rule;     /* the last one's rule code */
	struct island_supervisor_route route[ISLAND_SUPERVISOR_ROUTES];
	/* phase11-S6, after the routes so the header keeps its offsets. */
	struct island_supervisor_direct direct[ISLAND_SUPERVISOR_DIRECT_SLOTS];
	uint32_t standstill_met;     /* route 2 dues judged at standstill */
	uint32_t speed_mm_s;         /* the last noted |v| */
	uint32_t speed_at_ms;        /* its uptime */
	/* phase13-D4, after route 2's words so every offset above holds: the
	 * plan this image was built from and what the kernel gave the threads,
	 * taken on the first spin of mrm_handler's level (it has adopted its
	 * priority by then).
	 * Signed values stored as int32. */
	uint32_t prio_taken;           /* 1 once the words below are set */
	int32_t prio_plan_transport_lo;
	int32_t prio_plan_transport_hi;
	int32_t prio_plan_app_lo;
	int32_t prio_plan_app_hi;
	int32_t prio_plan_tier;        /* mrm_handler's level, planned (the most urgent) */
	int32_t prio_plan_reaction;    /* NROS_PRIORITY_PLAN_SUPERVISOR_PRIORITY */
	int32_t prio_spin;             /* mrm_handler's level thread, observed */
	int32_t prio_reaction;         /* the reaction thread, observed */
	uint32_t prio_threads;         /* entries of thread[] filled */
	struct {
		char name[16];
		int32_t prio;
	} thread[ISLAND_SUPERVISOR_PRIO_THREADS];
	/* The late notice, after the threads so every offset above holds: route
	 * 1 judged at its expiry from the executor's route cells. */
	uint32_t watch_ok;              /* 1 once the route watch is filled */
	uint32_t answered_at_expiry;    /* route 1 expiries the watch read answered */
	uint32_t answered_first_due_ms; /* the first one's armed due */
	uint32_t answered_first_us;     /* when it was read, us (low 32) */
	uint32_t later_take_at_expiry;  /* route 1 expiries re-armed to a later take */
	/* nano-ros phase-509 I1, after the late notice so every offset above
	 * holds: the executor levels (one per spinning thread). */
	uint32_t levels;                /* ISLAND_SUPERVISOR_LEVELS */
	uint32_t level_count;           /* level slots taken */
	uint32_t level_overflow;        /* spins from a thread with no slot left */
	uint32_t checkin_mask;          /* levels checked in since the last feed */
	uint32_t feeds;                 /* SWT0 feeds from the spin path */
	uint32_t route_owner;           /* level index + 1 that owns route 1, 0 none */
	/* nano-ros phase-509 P9b: the level that hosts mrm_handler
	 * (NROS_ENTRY_LEVEL_OF_MRM_HANDLER) and the image's level count. */
	uint32_t route_nros_level;
	uint32_t nros_level_count;
	struct island_supervisor_level level[ISLAND_SUPERVISOR_LEVELS];
};

volatile struct island_supervisor_record island_supervisor_record;

static const struct gpio_dt_spec safe_out = GPIO_DT_SPEC_GET(DT_NODELABEL(can_led1), gpios);
static struct k_spinlock lock;
static struct k_timer due_timer;
static K_SEM_DEFINE(wake, 0, 1);
static volatile uint32_t pending_swt;
static volatile uint32_t pending_hook;
static bool due_valid[ISLAND_SUPERVISOR_ROUTES];
static int64_t due_ms[ISLAND_SUPERVISOR_ROUTES];
static island_supervisor_direct_fn direct_fn[ISLAND_SUPERVISOR_DIRECT_SLOTS];
static void *direct_ctx[ISLAND_SUPERVISOR_DIRECT_SLOTS];
static int64_t latch_ms;
/* The executor's route cells, read at route 1's expiry (filled when route 1
 * gets its owner, from the owner's executor, before route 1 is ever armed). */
static nros_cpp_route_watch_t route_watch;
static volatile bool route_watch_ok;
/* phase-509 I1: the levels, by spinning thread; written under `lock`. */
static k_tid_t level_tid[ISLAND_SUPERVISOR_LEVELS];
static uint32_t level_last_cyc[ISLAND_SUPERVISOR_LEVELS];
static int route_owner = -1; /* the level that owns route 1 */
/* A kinematic_state sample older than this is not a standstill (10 Hz). */
#define STANDSTILL_FRESH_MS 300

#if defined(CONFIG_ISLAND_SUPERVISOR_SWT)
static const struct device *const swt = DEVICE_DT_GET(DT_NODELABEL(swt0));
static volatile bool swt_running;
static volatile bool swt_starting;
static uint32_t last_feed_cyc; /* the last feed; written under `lock` */
#endif

static inline uint32_t uptime_us32(void)
{
#if defined(CONFIG_TIMER_HAS_64BIT_CYCLE_COUNTER)
	return (uint32_t)k_cyc_to_us_floor64(k_cycle_get_64());
#else
	return (uint32_t)(k_uptime_get() * 1000);
#endif
}

/*
 * The uptime ms of an executor due `us` from now, never before the executor's
 * own (take + route_deadline_ms, in us). Was k_uptime_get() + ceil(us / 1000):
 * the floor of now plus the ceiling of the rest falls up to 1 ms BEFORE the
 * executor's due whenever now's sub-ms part exceeds the rest's, so a route
 * answered in its last ms was a verdict here and on time for the executor
 * (w9c-b2, CARLA 2026-10-18). Now: now in us from the cycle counter (the clock
 * the executor's due is on; the kernel tick is 1 ms, so k_uptime_ticks()
 * carries the same floor) plus the rest, rounded up, so the k_timer is at or
 * after the executor's due and at most 1 ms later.
 */
static int64_t executor_due_ms(uint64_t us)
{
#if defined(CONFIG_TIMER_HAS_64BIT_CYCLE_COUNTER)
	const int64_t now_us = (int64_t)k_cyc_to_us_floor64(k_cycle_get_64());
#else
	const int64_t now_us = (k_uptime_get() + 1) * 1000; /* ms clock: assume the tick's end */
#endif

	return (now_us + (int64_t)us + 999) / 1000;
}

#if defined(CONFIG_ISLAND_SUPERVISOR_SWT)
/* The service sequence is two writes; the spin thread and the reaction
 * thread both feed, so neither may split the other's pair. */
static int swt_feed(void)
{
	const unsigned int key = irq_lock();
	const int rc = wdt_feed(swt, 0);

	irq_unlock(key);
	return rc;
}
#endif

#if defined(CONFIG_ISLAND_DEBUG_SPIN_STALL)
/* Test only (Kconfig): a debugger writes non-zero, the next spin never ends. */
volatile uint32_t island_debug_spin_stall;
/* Test only (Kconfig, violations.py late-return): a debugger writes N (ms,
 * 1..100). The next spin that answered route 1 while its due was still ahead
 * holds the spin thread until N ms past that due before the supervisor hears
 * of the spin: a route answered in time by a spin that runs past its due (the
 * late notice, rtss-work-2026-demo:carla-island-demo.md). Once; the word reads 0 when taken. */
volatile uint32_t island_debug_late_return_ms;
#endif

/* The calling thread's level, taking a free slot on its first spin (the lock
 * is held); -1 when every slot is taken. */
static int level_of_locked(k_tid_t self, bool take)
{
	const uint32_t n = island_supervisor_record.level_count;

	for (uint32_t i = 0u; i < n; i++) {
		if (level_tid[i] == self) {
			return (int)i;
		}
	}
	if (!take || n >= ISLAND_SUPERVISOR_LEVELS) {
		return -1;
	}
	level_tid[n] = self;
	island_supervisor_record.level[n].prio = k_thread_priority_get(self);
	const char *name = k_thread_name_get(self);

	if (name != NULL) {
		strncpy((char *)island_supervisor_record.level[n].name, name,
			sizeof(island_supervisor_record.level[n].name) - 1u);
	}
	island_supervisor_record.level_count = n + 1u;
	return (int)n;
}

/* The earliest armed due, or K_FOREVER: the lock is held. */
static void rearm_locked(void)
{
	int64_t earliest = INT64_MAX;

	for (int i = 0; i < ISLAND_SUPERVISOR_ROUTES; i++) {
		if (due_valid[i] && due_ms[i] < earliest) {
			earliest = due_ms[i];
		}
	}
	if (earliest == INT64_MAX) {
		k_timer_stop(&due_timer);
	} else {
		k_timer_start(&due_timer, K_TIMEOUT_ABS_MS(earliest), K_NO_WAIT);
	}
}

void island_supervisor_arm(uint32_t route, int64_t due)
{
	if (route >= ISLAND_SUPERVISOR_ROUTES) {
		return;
	}
	k_spinlock_key_t key = k_spin_lock(&lock);

	due_valid[route] = true;
	due_ms[route] = due;
	island_supervisor_record.route[route].armed = 1u;
	island_supervisor_record.route[route].due_ms = (uint32_t)due;
	island_supervisor_record.route[route].arms++;
	rearm_locked();
	k_spin_unlock(&lock, key);
}

void island_supervisor_done(uint32_t route)
{
	if (route >= ISLAND_SUPERVISOR_ROUTES) {
		return;
	}
	k_spinlock_key_t key = k_spin_lock(&lock);

	if (due_valid[route]) {
		due_valid[route] = false;
		island_supervisor_record.route[route].armed = 0u;
		island_supervisor_record.route[route].dones++;
		rearm_locked();
	}
	k_spin_unlock(&lock, key);
}

static void due_expiry(struct k_timer *t)
{
	ARG_UNUSED(t);
	island_supervisor_record.timer_expiries++;
	k_sem_give(&wake);
}

#if defined(CONFIG_ISLAND_SUPERVISOR_SWT)
static void swt_first_timeout(const struct device *dev, int channel_id)
{
	ARG_UNUSED(dev);
	ARG_UNUSED(channel_id);
	if (island_supervisor_record.swt_fires++ == 0u) {
		island_supervisor_record.swt_fire_uptime_us = uptime_us32();
	}
	pending_swt = 1u;
	k_sem_give(&wake);
}
#endif

/* The fallback: drive the output, once; the record says when and why. */
static void safe_state(uint32_t cause)
{
	if (island_supervisor_record.latched) {
		return;
	}
	const struct gpio_driver_api *api = (const struct gpio_driver_api *)safe_out.port->api;
	const bool low = (safe_out.dt_flags & GPIO_ACTIVE_LOW) != 0U;
	/* Raw port write, as island_led.c does: no CTF gpio event, no driver lock. */
	const int rc = low ? api->port_clear_bits_raw(safe_out.port, BIT(safe_out.pin))
			   : api->port_set_bits_raw(safe_out.port, BIT(safe_out.pin));

	if (rc != 0) {
		island_supervisor_record.gpio_errors++;
	}
	latch_ms = k_uptime_get();
	island_supervisor_record.latch_uptime_us = uptime_us32();
	island_supervisor_record.latch_cause = cause;
	island_supervisor_record.latched = 1u;
	ISLAND_TRACE(ISLAND_MK_SUPERVISOR_SAFE_STATE, cause);
}

/* Route 2's due: the comfortable stop failed unless the vehicle is at
 * standstill now, by a fresh sample. */
static bool standstill_now(int64_t now)
{
	const uint32_t at = island_supervisor_record.speed_at_ms;

	return at != 0u && (uint32_t)now - at <= STANDSTILL_FRESH_MS &&
	       island_supervisor_record.speed_mm_s == 0u;
}

/* Every slot not yet handed over, once per call; true while one remains. */
static bool direct_pending(void)
{
	for (int i = 0; i < ISLAND_SUPERVISOR_DIRECT_SLOTS; i++) {
		if (direct_fn[i] != NULL && !island_supervisor_record.direct[i].handover) {
			return true;
		}
	}
	return false;
}

static void direct_publish(void)
{
	const int64_t now = k_uptime_get();

	for (int i = 0; i < ISLAND_SUPERVISOR_DIRECT_SLOTS; i++) {
		volatile struct island_supervisor_direct *d = &island_supervisor_record.direct[i];

		if (direct_fn[i] == NULL || d->handover) {
			continue;
		}
		const uint32_t seq = d->calls;

		if (seq == 0u) {
			d->first_uptime_us = uptime_us32();
		}
		d->calls = seq + 1u;
		ISLAND_TRACE(ISLAND_MK_SUPERVISOR_DIRECT, ((uint32_t)i << 28) | (seq & 0x0FFFFFFFu));
		direct_fn[i](direct_ctx[i], seq, (uint32_t)(now - latch_ms));
	}
}

static void reaction_thread(void *a, void *b, void *c)
{
	ARG_UNUSED(a);
	ARG_UNUSED(b);
	ARG_UNUSED(c);
	for (;;) {
		k_timeout_t wait = K_FOREVER;

		if (island_supervisor_record.latched && direct_pending()) {
			wait = K_MSEC(CONFIG_ISLAND_SUPERVISOR_DIRECT_PERIOD_MS);
		}
#if defined(CONFIG_ISLAND_SUPERVISOR_SWT)
		/* Latched: keep SWT0 from its second (reset) timeout. */
		else if (island_supervisor_record.latched && swt_running) {
			wait = K_MSEC(CONFIG_ISLAND_SUPERVISOR_SWT_MS / 4);
		}
#endif
		const int got = k_sem_take(&wake, wait);
#if defined(CONFIG_ISLAND_SUPERVISOR_SWT)
		if (island_supervisor_record.latched && swt_running) {
			(void)swt_feed();
		}
#endif
		if (got != 0) {
			/* The period: the direct path's next publish. */
			if (island_supervisor_record.latched) {
				direct_publish();
			}
			continue;
		}
		island_supervisor_record.wakes++;

		/* Route 1's answer, from the executor's cells, now: 0 = a take
		 * unanswered at or after its deadline (the miss), UINT64_MAX =
		 * answered, else the time to a later take's due. Without a watch
		 * the armed due stands (0). */
		uint64_t route1_left = 0u;

		if (route_watch_ok &&
		    nros_cpp_route_watch_next_due_us(&route_watch, &route1_left) != NROS_CPP_RET_OK) {
			route1_left = 0u;
		}
		const int64_t now = k_uptime_get();
		uint32_t fired_routes = 0u;
		k_spinlock_key_t key = k_spin_lock(&lock);

		for (int i = 0; i < ISLAND_SUPERVISOR_ROUTES; i++) {
			if (due_valid[i] && due_ms[i] <= now) {
				volatile struct island_supervisor_route *r = &island_supervisor_record.route[i];

				due_valid[i] = false;
				r->armed = 0u;
				if (i == ISLAND_SUPERVISOR_ROUTE_EXECUTOR && route1_left == UINT64_MAX) {
					/* answered inside a spin still running: not a miss */
					r->dones++;
					if (island_supervisor_record.answered_at_expiry++ == 0u) {
						island_supervisor_record.answered_first_due_ms = (uint32_t)due_ms[i];
						island_supervisor_record.answered_first_us = uptime_us32();
					}
					continue;
				}
				if (i == ISLAND_SUPERVISOR_ROUTE_EXECUTOR && route1_left != 0u) {
					/* answered, and a later take waits: its own due */
					due_valid[i] = true;
					due_ms[i] = executor_due_ms(route1_left);
					r->armed = 1u;
					r->due_ms = (uint32_t)due_ms[i];
					island_supervisor_record.later_take_at_expiry++;
					continue;
				}
				if (i == ISLAND_SUPERVISOR_ROUTE_COMFORTABLE_STANDSTILL && standstill_now(now)) {
					/* stopped in time: met at the due, not a miss */
					r->dones++;
					island_supervisor_record.standstill_met++;
					continue;
				}
				if (r->fired++ == 0u) {
					r->fire_due_ms = (uint32_t)due_ms[i];
					r->fire_verdict_us = uptime_us32();
				}
				fired_routes |= BIT(i);
				ISLAND_TRACE(ISLAND_MK_SUPERVISOR_DEADLINE,
					     ((uint32_t)i << 28) | ((uint32_t)due_ms[i] & 0x0FFFFFFFu));
			}
		}
		rearm_locked();
		k_spin_unlock(&lock, key);

		const uint32_t was_latched = island_supervisor_record.latched;

		if (fired_routes != 0u) {
			safe_state(ISLAND_SUPERVISOR_CAUSE_ROUTE);
		}
		if (pending_hook != 0u) {
			pending_hook = 0u;
			safe_state(ISLAND_SUPERVISOR_CAUSE_HOOK);
		}
		if (pending_swt != 0u) {
			pending_swt = 0u;
			safe_state(ISLAND_SUPERVISOR_CAUSE_SWT);
		}
		/* The emergency command follows the output at once; later wakes
		 * (another route, a hook call) do not publish out of period. */
		if (!was_latched && island_supervisor_record.latched) {
			direct_publish();
		}
	}
}

K_THREAD_DEFINE(island_supervisor_tid, CONFIG_ISLAND_SUPERVISOR_STACK_SIZE, reaction_thread, NULL, NULL, NULL,
		ISLAND_SUPERVISOR_PRIORITY, 0, 0);

static void prio_thread_cb(const struct k_thread *t, void *user)
{
	ARG_UNUSED(user);
	const uint32_t i = island_supervisor_record.prio_threads;

	if (i >= ISLAND_SUPERVISOR_PRIO_THREADS) {
		return;
	}
	const char *name = k_thread_name_get((k_tid_t)t);

	if (name != NULL) {
		strncpy((char *)island_supervisor_record.thread[i].name, name,
			sizeof(island_supervisor_record.thread[i].name) - 1u);
	}
	island_supervisor_record.thread[i].prio = k_thread_priority_get((k_tid_t)t);
	island_supervisor_record.prio_threads = i + 1u;
}

/* phase13-D4: the plan and the priorities the kernel gave, once. */
static void prio_take(void)
{
	island_supervisor_record.prio_plan_transport_lo = NROS_PRIORITY_PLAN_RESERVED_TRANSPORT_LO;
	island_supervisor_record.prio_plan_transport_hi = NROS_PRIORITY_PLAN_RESERVED_TRANSPORT_HI;
	island_supervisor_record.prio_plan_app_lo = NROS_PRIORITY_PLAN_APP_LO;
	island_supervisor_record.prio_plan_app_hi = NROS_PRIORITY_PLAN_APP_HI;
	island_supervisor_record.prio_plan_tier = NROS_ENTRY_TIERS_MOST_URGENT_PRIORITY;
	island_supervisor_record.prio_plan_reaction = ISLAND_SUPERVISOR_PRIORITY;
	island_supervisor_record.prio_spin = k_thread_priority_get(k_current_get());
	island_supervisor_record.prio_reaction = k_thread_priority_get(island_supervisor_tid);
	island_supervisor_record.prio_threads = 0u;
#if defined(CONFIG_THREAD_MONITOR)
	k_thread_foreach_unlocked(prio_thread_cb, NULL);
#endif
	island_supervisor_record.prio_taken = 1u;
}

/*
 * nano-ros phase-503 (the island's S3): a supervised route row carries a
 * deadline; the executor reports `route-deadline-runtime` and calls this hook
 * on the spin thread (it must not block: it only wakes the reaction thread),
 * and tells the port, after each spin, how far away the earliest pending due
 * is (nros_cpp_executor_route_next_due_us), which arms route 1 here so the
 * k_timer catches a callback that never returns as well. The generated entry
 * installs the hook only when the image has a supervised row; until nano-ros
 * reads `supervise:` from the model, none has, and route 0 (the handler's own
 * arming) is the supervised route.
 */
void nros_app_reaction_hook(const nros_cpp_reaction_event_t *event, void *ctx)
{
	ARG_UNUSED(ctx);
	island_supervisor_record.hook_calls++;
	island_supervisor_record.hook_last_rule = event->rule_code;
	pending_hook = 1u;
	k_sem_give(&wake);
}

#if defined(CONFIG_ISLAND_DEBUG_SPIN_STALL)
static void late_return(void *executor)
{
	const uint32_t n = island_debug_late_return_ms;
	uint64_t us = 0u;

	if (n == 0u || executor == NULL || nros_cpp_executor_route_next_due_us(executor, &us) != NROS_CPP_RET_OK ||
	    us != UINT64_MAX) {
		return; /* nothing asked, or route 1 not answered by this spin */
	}
	k_spinlock_key_t key = k_spin_lock(&lock);
	const bool armed = due_valid[ISLAND_SUPERVISOR_ROUTE_EXECUTOR];
	const int64_t due = due_ms[ISLAND_SUPERVISOR_ROUTE_EXECUTOR];

	k_spin_unlock(&lock, key);
	if (!armed || due <= k_uptime_get()) {
		return;
	}
	island_debug_late_return_ms = 0u;
	ISLAND_TRACE(ISLAND_MK_SUPERVISOR_INJECT, 0xFFFFFFFCu);
	const uint32_t until_us = (uint32_t)((due + (int64_t)(n > 100u ? 100u : n)) * 1000);

	while ((int32_t)(uptime_us32() - until_us) < 0) {
		k_busy_wait(100);
	}
}
#endif

void island_supervisor_spin_after(void *executor, uint8_t nros_level)
{
	uint64_t us = UINT64_MAX;

#if defined(CONFIG_ISLAND_DEBUG_SPIN_STALL)
	late_return(executor);
#endif
	const bool reported = executor != NULL &&
			      nros_cpp_executor_route_next_due_us(executor, &us) == NROS_CPP_RET_OK;
	/* nano-ros phase-509 P9b: every level works on the core's one executor,
	 * so the level is the spin's (spin_hook.c), not the executor's. */
	const bool hosts_handler = nros_level == (uint8_t)NROS_ENTRY_LEVEL_OF_MRM_HANDLER;
	k_spinlock_key_t key = k_spin_lock(&lock);
	const int self = level_of_locked(k_current_get(), false);
	bool take_watch = false;

	/* phase-509 P7: route 1 is owned by the level nano-ros names as
	 * mrm_handler's, from its first spin. */
	if (route_owner < 0 && self >= 0 && hosts_handler) {
		route_owner = self;
		island_supervisor_record.route_owner = (uint32_t)self + 1u;
		take_watch = true;
	}
	if (self < 0 || self != route_owner) {
		if (self >= 0 && reported && us != UINT64_MAX) {
			island_supervisor_record.level[self].route_foreign++;
		}
		k_spin_unlock(&lock, key);
		return;
	}
	k_spin_unlock(&lock, key);
	/* Once, on the owner's thread, before route 1 is first armed: the watch
	 * the reaction thread reads route 1 through at its expiry. */
	if (take_watch && nros_cpp_executor_route_watch(executor, &route_watch) == NROS_CPP_RET_OK) {
		compiler_barrier(); /* the watch is whole before the flag says so */
		route_watch_ok = true;
		island_supervisor_record.watch_ok = 1u;
	}
	if (!reported || us == UINT64_MAX) {
		island_supervisor_done(ISLAND_SUPERVISOR_ROUTE_EXECUTOR);
		return;
	}
	island_supervisor_arm(ISLAND_SUPERVISOR_ROUTE_EXECUTOR, executor_due_ms(us));
}

#if defined(CONFIG_ISLAND_SUPERVISOR_SWT)
/* SWT0's start, once, outside the lock (the driver's setup is not a lock
 * holder's business); true when it runs. */
static bool swt_start(void)
{
	const struct wdt_timeout_cfg cfg = {
		.window = {.min = 0U, .max = CONFIG_ISLAND_SUPERVISOR_SWT_MS},
		.callback = swt_first_timeout,
		.flags = WDT_FLAG_RESET_SOC,
	};

	if (!device_is_ready(swt) || wdt_install_timeout(swt, &cfg) < 0 ||
	    wdt_setup(swt, WDT_OPT_PAUSE_HALTED_BY_DBG) != 0) {
		island_supervisor_record.swt_errors++;
		return false;
	}
	island_supervisor_record.swt_started = 1u;
	island_supervisor_record.swt_timeout_ms = CONFIG_ISLAND_SUPERVISOR_SWT_MS;
	return true;
}
#endif

void island_supervisor_spin(void *executor, uint8_t nros_level)
{
	ARG_UNUSED(executor);
	if (island_supervisor_record.prio_taken == 0u &&
	    nros_level == (uint8_t)NROS_ENTRY_LEVEL_OF_MRM_HANDLER) {
		prio_take();
	}
#if defined(CONFIG_ISLAND_DEBUG_SPIN_STALL)
	if (island_debug_spin_stall != 0u) {
		ISLAND_TRACE(ISLAND_MK_SUPERVISOR_INJECT, 0xFFFFFFFEu);
		for (;;) {
			k_busy_wait(1000000);
		}
	}
#endif
	const uint32_t now = k_cycle_get_32();
	k_spinlock_key_t key = k_spin_lock(&lock);
	const int self = level_of_locked(k_current_get(), true);

	island_supervisor_record.spins++;
	if (self < 0) {
		/* No slot: this thread cannot check in, so it never feeds; the
		 * levels that have slots still decide. */
		island_supervisor_record.level_overflow++;
		k_spin_unlock(&lock, key);
		return;
	}
	volatile struct island_supervisor_level *lv = &island_supervisor_record.level[self];

	lv->nros_level = nros_level;

	if (lv->spins != 0u) {
		const uint32_t gap = (uint32_t)k_cyc_to_us_floor64(now - level_last_cyc[self]);

		if (gap > lv->gap_max_us) {
			lv->gap_max_us = gap;
			lv->gap_max_at_ms = k_uptime_get_32();
		}
	}
	level_last_cyc[self] = now;
	lv->spins++;
#if defined(CONFIG_ISLAND_SUPERVISOR_SWT)
	if (!swt_running) {
		k_spin_unlock(&lock, key);
		if (island_supervisor_record.swt_errors != 0u || swt_starting) {
			return; /* gave up once (the record says so), or another level is starting it */
		}
		swt_starting = true;
		if (swt_start()) {
			key = k_spin_lock(&lock);
			last_feed_cyc = now;
			island_supervisor_record.checkin_mask = 0u;
			swt_running = true;
			k_spin_unlock(&lock, key);
		}
		return;
	}
	/* The island's own mask stays as the record of which threads spun; the
	 * feed is nano-ros's aggregate (phase-509 P7): every level of the image
	 * checked in since the last feed. */
	island_supervisor_record.checkin_mask |= BIT(self);
	if (nros_cpp_levels_take_alive()) {
		const uint32_t gap = (uint32_t)k_cyc_to_us_floor64(now - last_feed_cyc);

		if (gap > island_supervisor_record.spin_gap_max_us) {
			island_supervisor_record.spin_gap_max_us = gap;
			island_supervisor_record.spin_gap_max_at_ms = k_uptime_get_32();
		}
		last_feed_cyc = now;
		island_supervisor_record.checkin_mask = 0u;
		island_supervisor_record.feeds++;
		if (swt_feed() != 0) {
			island_supervisor_record.swt_errors++;
		}
	}
#endif
	k_spin_unlock(&lock, key);
}

uint32_t island_supervisor_latched(void)
{
	return island_supervisor_record.latched;
}

void island_supervisor_set_direct(uint32_t slot, island_supervisor_direct_fn fn, void *ctx)
{
	if (slot >= ISLAND_SUPERVISOR_DIRECT_SLOTS) {
		return;
	}
	direct_ctx[slot] = ctx;
	direct_fn[slot] = fn;
	island_supervisor_record.direct[slot].registered = 1u;
}

void island_supervisor_handover(uint32_t slot)
{
	if (slot >= ISLAND_SUPERVISOR_DIRECT_SLOTS || !island_supervisor_record.latched ||
	    island_supervisor_record.direct[slot].handover) {
		return;
	}
	island_supervisor_record.direct[slot].handover_uptime_ms = k_uptime_get_32();
	island_supervisor_record.direct[slot].handover = 1u;
	ISLAND_TRACE(ISLAND_MK_SUPERVISOR_HANDOVER, slot);
}

void island_supervisor_note_speed(uint32_t speed_mm_s)
{
	island_supervisor_record.speed_mm_s = speed_mm_s;
	island_supervisor_record.speed_at_ms = k_uptime_get_32();
}

static int island_supervisor_init(void)
{
	if (!gpio_is_ready_dt(&safe_out) || gpio_pin_configure_dt(&safe_out, GPIO_OUTPUT_INACTIVE) != 0) {
		island_supervisor_record.gpio_errors++;
	}
	k_timer_init(&due_timer, due_expiry, NULL);
	island_supervisor_record.routes = ISLAND_SUPERVISOR_ROUTES;
	island_supervisor_record.levels = ISLAND_SUPERVISOR_LEVELS;
	island_supervisor_record.route_nros_level = NROS_ENTRY_LEVEL_OF_MRM_HANDLER;
	island_supervisor_record.nros_level_count = NROS_ENTRY_TIER_COUNT;
	island_supervisor_record.magic = ISLAND_SUPERVISOR_MAGIC;
	return 0;
}
SYS_INIT(island_supervisor_init, APPLICATION, 91);
