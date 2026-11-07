/* Host stand-in for <zephyr/kernel.h>: the few kernel calls island_spin_diag.h
 * makes, driven by tests/spin_diag/test_spin_diag.c (a fake 1 MHz clock, fake
 * threads and their runtime counters). Not a Zephyr emulation. */
#ifndef TEST_FAKE_ZEPHYR_KERNEL_H
#define TEST_FAKE_ZEPHYR_KERNEL_H

#include <stdbool.h>
#include <stdint.h>
#include <stddef.h>

struct k_thread {
	const char *name;
	int prio;
	uint64_t exec;
};
typedef struct k_thread *k_tid_t;
typedef struct {
	uint64_t execution_cycles;
	uint64_t idle_cycles;
} k_thread_runtime_stats_t;
typedef void (*k_thread_user_cb_t)(const struct k_thread *t, void *user);

extern uint32_t fake_now;     /* cycles == us */
extern uint64_t fake_idle;
extern struct k_thread *fake_cur;
extern struct k_thread *fake_threads[];
extern unsigned fake_nthreads;
extern int fake_sched_locked;

static inline uint32_t k_cycle_get_32(void) { return fake_now; }
static inline uint32_t k_uptime_get_32(void) { return fake_now / 1000u; }
static inline uint32_t sys_clock_hw_cycles_per_sec(void) { return 1000000u; }
static inline k_tid_t k_current_get(void) { return fake_cur; }
static inline int k_thread_priority_get(k_tid_t t) { return t->prio; }
static inline const char *k_thread_name_get(k_tid_t t) { return t->name; }
static inline int k_thread_runtime_stats_get(k_tid_t t, k_thread_runtime_stats_t *st)
{
	st->execution_cycles = t->exec;
	st->idle_cycles = 0;
	return 0;
}
static inline int k_thread_runtime_stats_all_get(k_thread_runtime_stats_t *st)
{
	st->execution_cycles = 0;
	st->idle_cycles = fake_idle;
	return 0;
}
static inline void k_thread_foreach_unlocked(k_thread_user_cb_t cb, void *user)
{
	for (unsigned i = 0; i < fake_nthreads; i++) {
		cb(fake_threads[i], user);
	}
}
static inline void k_sched_lock(void) { fake_sched_locked++; }
static inline void k_sched_unlock(void) { fake_sched_locked--; }

#endif
