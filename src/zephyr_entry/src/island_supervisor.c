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

#include <nros/nros_cpp_ffi.h>

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
	island_supervisor_record.latch_uptime_us = uptime_us32();
	island_supervisor_record.latch_cause = cause;
	island_supervisor_record.latched = 1u;
	ISLAND_TRACE(ISLAND_MK_SUPERVISOR_SAFE_STATE, cause);
}

static void reaction_thread(void *a, void *b, void *c)
{
	ARG_UNUSED(a);
	ARG_UNUSED(b);
	ARG_UNUSED(c);
	for (;;) {
#if defined(CONFIG_ISLAND_SUPERVISOR_SWT)
		/* Latched: keep SWT0 from its second (reset) timeout. */
		const k_timeout_t wait = (island_supervisor_record.latched && swt_running)
						 ? K_MSEC(CONFIG_ISLAND_SUPERVISOR_SWT_MS / 4)
						 : K_FOREVER;
#else
		const k_timeout_t wait = K_FOREVER;
#endif
		const int got = k_sem_take(&wake, wait);
#if defined(CONFIG_ISLAND_SUPERVISOR_SWT)
		if (island_supervisor_record.latched && swt_running) {
			(void)swt_feed();
		}
#endif
		if (got != 0) {
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
	}
}

K_THREAD_DEFINE(island_supervisor_tid, 1024, reaction_thread, NULL, NULL, NULL,
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
