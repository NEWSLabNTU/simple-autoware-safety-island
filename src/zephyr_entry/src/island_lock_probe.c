/*
 * The executor lock's price on target (nano-ros phase-509 I4; RFC-0108,
 * "Lock cost" and "Blocking bound", which defer both numbers to the island).
 * A measurement image only (CONFIG_ISLAND_LOCK_PROBE, off in the gate image).
 *
 * 1. Lock cost: at boot, before any level exists, N uncontended pairs of
 *    k_mutex_lock/unlock, the nested (recursive) pair taken while the mutex
 *    is already held, and the pair through the entries the runner installs
 *    on the executor (nros_platform_mutex_rec_lock/_unlock, the port's
 *    recursive priority-inheriting mutex over a k_mutex). DWT cycles, the
 *    empty measurement subtracted.
 *
 * 2. L_max: the runner installs the lock with nros_cpp_executor_set_lock
 *    (zephyr_run_tiers.c); that call is wrapped (-Wl,--wrap) and the lock and
 *    unlock it installs are timed. Per holding thread: how many outermost
 *    holds, the longest (overall and from CONFIG_ISLAND_LOCK_PROBE_STEADY_MS
 *    on, past bring-up), a histogram, and the longest wait to acquire. The
 *    state is written only while the lock is held, so it needs no lock of
 *    its own.
 *
 * 3. Stack high-water: a thread at the least urgent application priority
 *    runs the thread analyzer (CONFIG_INIT_STACKS paint) every second and
 *    keeps each thread's largest use.
 *
 * 4. A spawned level's worker frame (nano-ros issue 2065): the supervisor's
 *    wrapper of nros_cpp_level_spin_once (spin_hook.c, -Wl,--wrap) calls
 *    island_lock_probe_level_pass() first on every pass. On a level thread's
 *    first pass, before it runs, the stack's paint high-water is the SETUP
 *    peak (nros_cpp_level_open, the level's node setup, the next level's
 *    spawn; no callback has run yet). The wrapper then repaints the stack
 *    below its own frame (less LP_REPAINT_MARGIN for an exception frame), so
 *    the high-water the scan thread reads from then on is the STEADY peak:
 *    the passes alone, spin_once plus the member callbacks it dispatches.
 *    The level's stack table row in 3 is then the larger of the two, as
 *    scanned.
 *
 * Read over SWD after the run (island_lock_probe_record; the decoder is
 * tools/board/lock_probe.py).
 */
#include <stdbool.h>
#include <stdint.h>
#include <string.h>
#include <zephyr/kernel.h>
#include <zephyr/init.h>
#include <zephyr/debug/thread_analyzer.h>
#include <cmsis_core.h>

#define LP_MAGIC 0x4C4B5052u /* "LKPR" */
#define LP_HOLDERS 4
#define LP_STACKS 16
#define LP_BUCKETS 8
#define LP_BENCH_N 1000u
#define LP_LEVELS 4
#define LP_REPAINT_MARGIN 256u

/* histogram edges, us: [0,2) [2,5) [5,10) [10,50) [50,100) [100,500) [500,1000) [1000,) */
static const uint32_t lp_edge_us[LP_BUCKETS - 1] = {2u, 5u, 10u, 50u, 100u, 500u, 1000u};

struct lp_bench {
	uint32_t min_cyc;
	uint32_t avg_cyc;
	uint32_t max_cyc;
};

struct lp_holder {
	uint32_t tid;
	int32_t prio;
	char name[16];
	uint32_t holds;
	uint32_t hold_max_cyc;
	uint32_t hold_max_uptime_ms;
	uint32_t steady_hold_max_cyc;
	uint32_t steady_hold_max_uptime_ms;
	uint32_t hold_sum_lo;
	uint32_t hold_sum_hi;
	uint32_t wait_max_cyc;
	uint32_t steady_wait_max_cyc;
	uint32_t waits_over_5us;
	uint32_t bucket[LP_BUCKETS];
};

struct lp_stack {
	char name[16];
	uint32_t size;
	uint32_t used_max;
};

struct lp_level {
	uint32_t tid;
	char name[16];
	uint32_t size;
	uint32_t setup_used;  /* high-water at the first pass's entry */
	uint32_t entry_depth; /* stack in use at the wrapper's entry (SP) */
	uint32_t steady_used; /* high-water of the repainted stack, passes only */
	uint32_t passes;
	uint32_t steady_scans;
};

struct island_lock_probe {
	uint32_t magic;
	uint32_t cyc_per_sec;
	uint32_t bench_n;
	uint32_t empty_cyc;          /* the DWT read pair, subtracted below */
	struct lp_bench kmutex_pair;  /* k_mutex_lock + unlock, uncontended */
	struct lp_bench kmutex_nested; /* the same pair while already held */
	struct lp_bench rec_pair;     /* nros_platform_mutex_rec_lock + unlock */
	struct lp_bench exec_pair;    /* nros_zephyr_exec_lock + unlock (nano-ros P10), 0 if absent */
	uint32_t installed;           /* the executor's lock was wrapped */
	uint32_t holder_overflow;     /* holds by a thread past LP_HOLDERS */
	uint32_t depth_errors;        /* unlock at depth 0 */
	uint32_t steady_ms;
	uint32_t stack_scans;
	struct lp_holder holder[LP_HOLDERS];
	struct lp_stack stack[LP_STACKS];
	uint32_t level_magic; /* LP_LEVEL_MAGIC once section 4 is in the image */
	struct lp_level level[LP_LEVELS];
};

#define LP_LEVEL_MAGIC 0x4C564C46u /* "LVLF" */

struct island_lock_probe island_lock_probe_record;

static inline uint32_t cyc(void)
{
	return DWT->CYCCNT;
}

static void lp_dwt_on(void)
{
	DCB->DEMCR |= DCB_DEMCR_TRCENA_Msk;
#if defined(DWT_LSR_Present_Msk)
	DWT->LAR = 0xC5ACCE55u;
#endif
	DWT->CTRL |= DWT_CTRL_CYCCNTENA_Msk;
}

/* ---- 1. lock cost ---------------------------------------------------- */

extern int8_t nros_platform_mutex_rec_init(void *m);
extern int8_t nros_platform_mutex_rec_lock(void *m);
extern int8_t nros_platform_mutex_rec_unlock(void *m);
extern size_t nros_platform_mutex_rec_storage_size(void);
/* nano-ros phase-509 P10: the runner's own executor lock (a bare k_mutex);
 * weak, so an older nano-ros links and benches nothing. */
extern size_t nros_zephyr_exec_lock_size(void) __attribute__((weak));
extern int8_t nros_zephyr_exec_lock_init(void *m) __attribute__((weak));
extern int8_t nros_zephyr_exec_lock(void *m) __attribute__((weak));
extern int8_t nros_zephyr_exec_unlock(void *m) __attribute__((weak));
static uint64_t lp_exec_storage[64u / 8u];

static uint64_t lp_rec_storage[256u / 8u];
static struct k_mutex lp_mutex;

static void lp_fold(struct lp_bench *b, uint32_t d, uint64_t *sum)
{
	if (d < b->min_cyc) {
		b->min_cyc = d;
	}
	if (d > b->max_cyc) {
		b->max_cyc = d;
	}
	*sum += d;
}

static uint32_t lp_net(uint32_t d, uint32_t empty)
{
	return d > empty ? d - empty : 0u;
}

static int island_lock_probe_bench(void)
{
	struct island_lock_probe *r = &island_lock_probe_record;
	uint32_t empty = UINT32_MAX;
	uint64_t s1 = 0, s2 = 0, s3 = 0, s4 = 0;

	lp_dwt_on();
	r->cyc_per_sec = (uint32_t)sys_clock_hw_cycles_per_sec();
	r->bench_n = LP_BENCH_N;
	r->steady_ms = CONFIG_ISLAND_LOCK_PROBE_STEADY_MS;
	r->kmutex_pair.min_cyc = r->kmutex_nested.min_cyc = r->rec_pair.min_cyc = UINT32_MAX;
	r->exec_pair.min_cyc = UINT32_MAX;

	for (uint32_t i = 0; i < LP_BENCH_N; i++) {
		const uint32_t t0 = cyc();
		const uint32_t t1 = cyc();

		if (t1 - t0 < empty) {
			empty = t1 - t0;
		}
	}
	r->empty_cyc = empty;

	k_mutex_init(&lp_mutex);
	for (uint32_t i = 0; i < LP_BENCH_N; i++) {
		const uint32_t t0 = cyc();

		(void)k_mutex_lock(&lp_mutex, K_FOREVER);
		(void)k_mutex_unlock(&lp_mutex);
		lp_fold(&r->kmutex_pair, lp_net(cyc() - t0, empty), &s1);
	}
	(void)k_mutex_lock(&lp_mutex, K_FOREVER);
	for (uint32_t i = 0; i < LP_BENCH_N; i++) {
		const uint32_t t0 = cyc();

		(void)k_mutex_lock(&lp_mutex, K_FOREVER);
		(void)k_mutex_unlock(&lp_mutex);
		lp_fold(&r->kmutex_nested, lp_net(cyc() - t0, empty), &s2);
	}
	(void)k_mutex_unlock(&lp_mutex);

	if (nros_platform_mutex_rec_storage_size() <= sizeof(lp_rec_storage) &&
	    nros_platform_mutex_rec_init(lp_rec_storage) == 0) {
		for (uint32_t i = 0; i < LP_BENCH_N; i++) {
			const uint32_t t0 = cyc();

			(void)nros_platform_mutex_rec_lock(lp_rec_storage);
			(void)nros_platform_mutex_rec_unlock(lp_rec_storage);
			lp_fold(&r->rec_pair, lp_net(cyc() - t0, empty), &s3);
		}
	}
	if (nros_zephyr_exec_lock_size != NULL &&
	    nros_zephyr_exec_lock_size() <= sizeof(lp_exec_storage) &&
	    nros_zephyr_exec_lock_init(lp_exec_storage) == 0) {
		for (uint32_t i = 0; i < LP_BENCH_N; i++) {
			const uint32_t t0 = cyc();

			(void)nros_zephyr_exec_lock(lp_exec_storage);
			(void)nros_zephyr_exec_unlock(lp_exec_storage);
			lp_fold(&r->exec_pair, lp_net(cyc() - t0, empty), &s4);
		}
		r->exec_pair.avg_cyc = (uint32_t)(s4 / LP_BENCH_N);
	} else {
		r->exec_pair.min_cyc = 0u;
	}
	r->kmutex_pair.avg_cyc = (uint32_t)(s1 / LP_BENCH_N);
	r->kmutex_nested.avg_cyc = (uint32_t)(s2 / LP_BENCH_N);
	r->rec_pair.avg_cyc = (uint32_t)(s3 / LP_BENCH_N);
	r->magic = LP_MAGIC;
	return 0;
}

SYS_INIT(island_lock_probe_bench, APPLICATION, 92);

/* ---- 2. the executor's lock, held ------------------------------------ */

int __real_nros_cpp_executor_set_lock(void *executor, int8_t (*lock)(void *),
				      int8_t (*unlock)(void *), void *ctx);

static int8_t (*lp_real_lock)(void *);
static int8_t (*lp_real_unlock)(void *);
static uint32_t lp_depth;
static uint32_t lp_start;
static struct lp_holder *lp_owner;

static struct lp_holder *lp_holder_of(k_tid_t t)
{
	struct island_lock_probe *r = &island_lock_probe_record;

	for (int i = 0; i < LP_HOLDERS; i++) {
		struct lp_holder *h = &r->holder[i];

		if (h->tid == (uint32_t)(uintptr_t)t) {
			return h;
		}
		if (h->tid == 0u) {
			const char *n = k_thread_name_get(t);

			h->tid = (uint32_t)(uintptr_t)t;
			h->prio = k_thread_priority_get(t);
			if (n != NULL) {
				strncpy(h->name, n, sizeof(h->name) - 1u);
			}
			return h;
		}
	}
	r->holder_overflow++;
	return NULL;
}

static int8_t lp_lock(void *m)
{
	const uint32_t t0 = cyc();
	const int8_t rc = lp_real_lock(m);
	const uint32_t t1 = cyc();

	if (rc != 0) {
		return rc;
	}
	if (lp_depth++ == 0u) {
		struct lp_holder *h = lp_holder_of(k_current_get());
		const uint32_t w = t1 - t0;

		lp_owner = h;
		lp_start = cyc();
		if (h != NULL) {
			/* A thread's name is set after it starts and a level adopts
			 * its priority after its first holds: refresh both. */
			const char *n = k_thread_name_get(k_current_get());

			if (n != NULL && h->name[0] == '\0') {
				strncpy(h->name, n, sizeof(h->name) - 1u);
			}
			h->prio = k_thread_priority_get(k_current_get());
			if (w > h->wait_max_cyc) {
				h->wait_max_cyc = w;
			}
			if (k_uptime_get_32() >= CONFIG_ISLAND_LOCK_PROBE_STEADY_MS &&
			    w > h->steady_wait_max_cyc) {
				h->steady_wait_max_cyc = w;
			}
			if (w > 5u * (island_lock_probe_record.cyc_per_sec / 1000000u)) {
				h->waits_over_5us++;
			}
		}
	}
	return rc;
}

static int8_t lp_unlock(void *m)
{
	if (lp_depth == 0u) {
		island_lock_probe_record.depth_errors++;
	} else if (--lp_depth == 0u && lp_owner != NULL) {
		struct lp_holder *h = lp_owner;
		const uint32_t d = cyc() - lp_start;
		const uint32_t now_ms = k_uptime_get_32();
		const uint32_t per_us = island_lock_probe_record.cyc_per_sec / 1000000u;
		const uint64_t sum = (((uint64_t)h->hold_sum_hi << 32) | h->hold_sum_lo) + d;
		int b = 0;

		h->holds++;
		h->hold_sum_lo = (uint32_t)sum;
		h->hold_sum_hi = (uint32_t)(sum >> 32);
		if (d > h->hold_max_cyc) {
			h->hold_max_cyc = d;
			h->hold_max_uptime_ms = now_ms;
		}
		if (now_ms >= CONFIG_ISLAND_LOCK_PROBE_STEADY_MS && d > h->steady_hold_max_cyc) {
			h->steady_hold_max_cyc = d;
			h->steady_hold_max_uptime_ms = now_ms;
		}
		while (b < LP_BUCKETS - 1 && d >= lp_edge_us[b] * per_us) {
			b++;
		}
		h->bucket[b]++;
		lp_owner = NULL;
	}
	return lp_real_unlock(m);
}

int __wrap_nros_cpp_executor_set_lock(void *executor, int8_t (*lock)(void *),
				      int8_t (*unlock)(void *), void *ctx)
{
	lp_real_lock = lock;
	lp_real_unlock = unlock;
	island_lock_probe_record.installed = 1u;
	return __real_nros_cpp_executor_set_lock(executor, lp_lock, lp_unlock, ctx);
}

/* ---- 3. stack high-water --------------------------------------------- */

static void lp_stack_cb(struct thread_analyzer_info *info)
{
	struct island_lock_probe *r = &island_lock_probe_record;

	for (int i = 0; i < LP_STACKS; i++) {
		struct lp_stack *s = &r->stack[i];

		if (s->name[0] == '\0') {
			strncpy(s->name, info->name, sizeof(s->name) - 1u);
		} else if (strncmp(s->name, info->name, sizeof(s->name) - 1u) != 0) {
			continue;
		}
		s->size = (uint32_t)info->stack_size;
		if (info->stack_used > s->used_max) {
			s->used_max = (uint32_t)info->stack_used;
		}
		return;
	}
}

/* ---- 4. a spawned level's worker frame (nano-ros issue 2065) -------- */

static struct lp_level *lp_level_of(k_tid_t t, bool *first)
{
	struct island_lock_probe *r = &island_lock_probe_record;

	*first = false;
	for (int i = 0; i < LP_LEVELS; i++) {
		struct lp_level *l = &r->level[i];

		if (l->tid == (uint32_t)(uintptr_t)t) {
			return l;
		}
		if (l->tid == 0u) {
			l->tid = (uint32_t)(uintptr_t)t;
			*first = true;
			return l;
		}
	}
	return NULL;
}

void island_lock_probe_level_pass(void)
{
	bool first;
	k_tid_t self = k_current_get();
	struct lp_level *l = lp_level_of(self, &first);

	if (l != NULL && first) {
		const char *n = k_thread_name_get(self);
		size_t unused = 0;
		uintptr_t sp;
		const uintptr_t start = self->stack_info.start;

		__asm__ volatile("mov %0, sp" : "=r"(sp));
		if (n != NULL) {
			strncpy(l->name, n, sizeof(l->name) - 1u);
		}
		l->size = (uint32_t)self->stack_info.size;
		if (k_thread_stack_space_get(self, &unused) == 0) {
			l->setup_used = l->size - (uint32_t)unused;
		}
		l->entry_depth = (uint32_t)(start + self->stack_info.size - sp);
		/* Repaint below this frame: a plain loop, so nothing it calls
		 * lands in the region it writes; an exception's stacked frame
		 * (at most 104 B with the FPU) lands in the margin. */
		for (volatile uint8_t *p = (volatile uint8_t *)start;
		     (uintptr_t)p < sp - LP_REPAINT_MARGIN; p++) {
			*p = 0xaau;
		}
		island_lock_probe_record.level_magic = LP_LEVEL_MAGIC;
	}
	if (l != NULL) {
		l->passes++;
	}
}

static void lp_level_scan(void)
{
	struct island_lock_probe *r = &island_lock_probe_record;

	for (int i = 0; i < LP_LEVELS; i++) {
		struct lp_level *l = &r->level[i];
		size_t unused = 0;

		if (l->tid == 0u || l->passes == 0u) {
			continue;
		}
		if (k_thread_stack_space_get((k_tid_t)(uintptr_t)l->tid, &unused) == 0 &&
		    l->size - (uint32_t)unused > l->steady_used) {
			l->steady_used = l->size - (uint32_t)unused;
		}
		l->steady_scans++;
	}
}

static void lp_stack_thread(void *a, void *b, void *c)
{
	ARG_UNUSED(a);
	ARG_UNUSED(b);
	ARG_UNUSED(c);
	for (;;) {
		k_sleep(K_MSEC(1000));
		thread_analyzer_run(lp_stack_cb, 0);
		lp_level_scan();
		island_lock_probe_record.stack_scans++;
	}
}

K_THREAD_DEFINE(island_lock_probe_tid, 1024, lp_stack_thread, NULL, NULL, NULL,
		CONFIG_NUM_PREEMPT_PRIORITIES - 2, 0, 0);
