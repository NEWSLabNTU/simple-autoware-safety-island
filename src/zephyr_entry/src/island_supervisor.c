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
 * started at the first spin and fed at the start of every spin; its first
 * timeout interrupts, and the callback wakes the same thread for the same
 * action, so a hung executor is caught with no route pending. The second
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
 * Route 2 (phase11-S6, decision 4): the comfortable stop's standstill. Its
 * due is the comfortable call + settle + response at the entry speed + how
 * late the island sees a standstill (a kinematic_state period + the link); at
 * the due the thread judges the speed the handler last noted from
 * kinematic_state (island_supervisor_note_speed): fresh and below 1 mm/s is
 * standstill and the route is met; otherwise the comfortable stop failed
 * and the output is latched, which commands the emergency stop as above.
 *
 * Everything is readable by name over SWD (island_supervisor_record,
 * tools/timeline/violations.py supervisor).
 */
#include <stdbool.h>
#include <stdint.h>
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

#if defined(CONFIG_ISLAND_SPIN_RAISE)
BUILD_ASSERT(CONFIG_ISLAND_SUPERVISOR_THREAD_PRIORITY < CONFIG_ISLAND_SPIN_THREAD_PRIORITY,
	     "the reaction thread must run above the spin thread");
#else
BUILD_ASSERT(CONFIG_ISLAND_SUPERVISOR_THREAD_PRIORITY < CONFIG_MAIN_THREAD_PRIORITY,
	     "the reaction thread must run above the spin thread");
#endif

#define ISLAND_SUPERVISOR_MAGIC 0x56505553u /* "SUPV" little-endian */

/* Layout read by tools/timeline/violations.py; all 32-bit. */
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
/* A kinematic_state sample older than this is not a standstill (10 Hz). */
#define STANDSTILL_FRESH_MS 300

#if defined(CONFIG_ISLAND_SUPERVISOR_SWT)
static const struct device *const swt = DEVICE_DT_GET(DT_NODELABEL(swt0));
static bool swt_running;
static uint32_t last_feed_cyc;
#endif

static inline uint32_t uptime_us32(void)
{
#if defined(CONFIG_TIMER_HAS_64BIT_CYCLE_COUNTER)
	return (uint32_t)k_cyc_to_us_floor64(k_cycle_get_64());
#else
	return (uint32_t)(k_uptime_get() * 1000);
#endif
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
#endif

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

		const int64_t now = k_uptime_get();
		uint32_t fired_routes = 0u;
		k_spinlock_key_t key = k_spin_lock(&lock);

		for (int i = 0; i < ISLAND_SUPERVISOR_ROUTES; i++) {
			if (due_valid[i] && due_ms[i] <= now) {
				volatile struct island_supervisor_route *r = &island_supervisor_record.route[i];

				due_valid[i] = false;
				r->armed = 0u;
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
		CONFIG_ISLAND_SUPERVISOR_THREAD_PRIORITY, 0, 0);

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

void island_supervisor_spin_after(void *executor)
{
	uint64_t us = UINT64_MAX;

	if (executor == NULL || nros_cpp_executor_route_next_due_us(executor, &us) != NROS_CPP_RET_OK ||
	    us == UINT64_MAX) {
		if (due_valid[ISLAND_SUPERVISOR_ROUTE_EXECUTOR]) {
			island_supervisor_done(ISLAND_SUPERVISOR_ROUTE_EXECUTOR);
		}
		return;
	}
	island_supervisor_arm(ISLAND_SUPERVISOR_ROUTE_EXECUTOR,
			      k_uptime_get() + (int64_t)((us + 999u) / 1000u));
}

void island_supervisor_spin(void)
{
#if defined(CONFIG_ISLAND_DEBUG_SPIN_STALL)
	if (island_debug_spin_stall != 0u) {
		ISLAND_TRACE(ISLAND_MK_SUPERVISOR_INJECT, 0xFFFFFFFEu);
		for (;;) {
			k_busy_wait(1000000);
		}
	}
#endif
#if defined(CONFIG_ISLAND_SUPERVISOR_SWT)
	const uint32_t now = k_cycle_get_32();

	if (!swt_running) {
		if (island_supervisor_record.swt_errors != 0u) {
			return; /* gave up once; the record says so */
		}
		const struct wdt_timeout_cfg cfg = {
			.window = {.min = 0U, .max = CONFIG_ISLAND_SUPERVISOR_SWT_MS},
			.callback = swt_first_timeout,
			.flags = WDT_FLAG_RESET_SOC,
		};

		if (!device_is_ready(swt) || wdt_install_timeout(swt, &cfg) < 0 ||
		    wdt_setup(swt, WDT_OPT_PAUSE_HALTED_BY_DBG) != 0) {
			island_supervisor_record.swt_errors++;
			return;
		}
		swt_running = true;
		island_supervisor_record.swt_started = 1u;
		island_supervisor_record.swt_timeout_ms = CONFIG_ISLAND_SUPERVISOR_SWT_MS;
		last_feed_cyc = now;
	} else {
		const uint32_t gap = (uint32_t)k_cyc_to_us_floor64(now - last_feed_cyc);

		if (gap > island_supervisor_record.spin_gap_max_us) {
			island_supervisor_record.spin_gap_max_us = gap;
			island_supervisor_record.spin_gap_max_at_ms = k_uptime_get_32();
		}
		last_feed_cyc = now;
		if (swt_feed() != 0) {
			island_supervisor_record.swt_errors++;
		}
	}
#endif
	island_supervisor_record.spins++;
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
	island_supervisor_record.magic = ISLAND_SUPERVISOR_MAGIC;
	return 0;
}
SYS_INIT(island_supervisor_init, APPLICATION, 91);
