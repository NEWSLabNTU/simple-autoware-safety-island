/*
 * Host test of the spin-latency diagnostic's recorder (issue #14):
 * src/safety_island_tracing/include/island_spin_diag.h, against a fake
 * 1 MHz clock and fake threads (tests/spin_diag/zephyr/kernel.h). Two
 * executor levels with different park bounds interleave; lateness must be
 * each interval's run past its own park bound, per level.
 *
 *   test_spin_diag [blob]   writes island_spin_diag's bytes to <blob>, which
 *                           `spin_diag.py selftest <blob>` decodes
 *
 * `just supervisor-test`; CI runs it too (.github/workflows/check.yml).
 */
#include <stdio.h>

#include "zephyr/kernel.h"

uint32_t fake_now;
uint64_t fake_idle;
struct k_thread *fake_cur;
struct k_thread *fake_threads[8];
unsigned fake_nthreads;
int fake_sched_locked;
volatile uint32_t _z_zephyr_serial_isr_cycles;
volatile uint32_t _z_zephyr_serial_isr_calls;

#include "../../src/safety_island_tracing/include/island_spin_diag.h"

static int fails;

#define CHECK(cond)                                                                  \
	do {                                                                         \
		if (!(cond)) {                                                       \
			printf("FAIL %s:%d: %s\n", __FILE__, __LINE__, #cond);       \
			fails++;                                                     \
		}                                                                    \
	} while (0)

static struct k_thread ta = {"derived-a", 5, 0};
static struct k_thread tb = {"derived-b", 8, 0};
static struct k_thread tc = {"zpico_rx", 3, 0};

static void at(uint32_t t, struct k_thread *th)
{
	CHECK(t >= fake_now);
	fake_now = t;
	fake_cur = th;
}

static void ph(uint32_t t, struct k_thread *th, uint32_t phase, uint32_t value)
{
	at(t, th);
	island_spin_diag_event(40u, phase | (value << 8));
}

static void ev(uint32_t t, struct k_thread *th, uint32_t id, uint32_t arg)
{
	at(t, th);
	island_spin_diag_event(id, arg);
}

int main(int argc, char **argv)
{
	fake_threads[0] = &ta;
	fake_threads[1] = &tb;
	fake_threads[2] = &tc;
	fake_nthreads = 3;

	/* a non-level thread's events before any level are ignored */
	ev(0, &tc, 18u, 1u);
	CHECK(island_spin_diag.nlev == 0u);

	/* A1: bound 30 ms, interval 31 ms -> 1 ms late */
	ph(0, &ta, 0, 0);
	ph(100, &ta, 1, 30000);
	/* B1: bound 85 ms, interval 86 ms -> 1 ms late */
	ph(1000, &tb, 0, 0);
	ph(1100, &tb, 1, 85000);
	ph(30100, &ta, 2, 0);
	ev(30200, &ta, 18u, 7u);
	ev(30700, &ta, 19u, 7u);
	ph(30800, &ta, 3, 0);
	ph(30900, &ta, 4, 0);
	/* A2: bound 29 ms, interval 32.6 ms -> 3.6 ms late (in the ring) */
	ph(31000, &ta, 0, 0);
	ph(31100, &ta, 1, 29000);
	/* a non-level thread waits 2 ms on a lock: every level's record */
	at(40000, &tc);
	island_diag_lock_wait((void *)0, 2000u, (void *)0);
	tc.exec += 1500;
	ph(60100, &ta, 2, 0);
	ev(60200, &ta, 18u, 9u);
	ev(60250, &ta, 25u, 0u);
	at(62000, &ta);
	island_diag_lock_wait((void *)0, 500u, (void *)0);
	ev(63400, &ta, 19u, 9u);
	ph(63500, &ta, 3, 0);
	ph(63600, &ta, 4, 0);
	/* A3: bound 30 ms, woken early, interval 7 ms -> 0 late */
	ph(63600, &ta, 0, 0);
	ph(63700, &ta, 1, 30000);
	ph(70000, &ta, 2, 0);
	ph(70400, &ta, 3, 1);
	ph(70500, &ta, 4, 1);
	ph(70600, &ta, 0, 0);
	ph(86100, &tb, 2, 0);
	ph(86400, &tb, 3, 1);
	ph(86500, &tb, 4, 1);
	/* B2: no phase 1 -> no bound, not judged */
	ph(87000, &tb, 0, 0);
	ph(87500, &tb, 3, 1);
	ph(87600, &tb, 4, 1);
	ph(88000, &tb, 0, 0);

	volatile struct island_spin_diag_t *d = &island_spin_diag;
	volatile struct sd_level *a = &d->lev[0], *b = &d->lev[1];

	CHECK(fake_sched_locked == 0);
	CHECK(d->magic == SD_MAGIC);
	CHECK(d->nlev == 2u);
	CHECK(d->lev_dropped == 0u);
	CHECK(a->tid == (uint32_t)(uintptr_t)&ta);
	CHECK(b->prio == 8u);
	CHECK(a->spins == 3u && a->nobound == 0u && a->late == 1u);
	CHECK(a->max_late_us == 3600u);
	CHECK(a->hist[0] == 1u && a->hist[1] == 1u && a->hist[3] == 1u);
	CHECK(a->bound_min_us == 29000u && a->bound_max_us == 30000u);
	CHECK(a->interval_max_us == 32600u);
	CHECK(b->spins == 2u && b->nobound == 1u && b->late == 0u);
	CHECK(b->max_late_us == 1000u && b->hist[1] == 1u);
	CHECK(b->bound_min_us == 85000u && b->bound_max_us == 85000u);
	CHECK(d->ring_next == 1u);
	volatile struct sd_rec *r = &d->ring[0];
	CHECK(r->level == 0u && r->late_us == 3600u && r->interval_us == 32600u);
	CHECK(r->park_bound_us == 29000u);
	CHECK(r->seg_wall[1] == 29000u && r->seg_wall[2] == 3400u);
	CHECK(r->ncb == 1u && r->ntake == 1u && r->cb_slot == 9u && r->cb_wall_us == 3200u);
	CHECK(r->lk_main_n == 1u && r->lk_main_us == 500u);
	CHECK(r->lk_oth_n == 1u && r->lk_oth_us == 2000u);
	CHECK(r->top_tid[0] == (uint32_t)(uintptr_t)&tc && r->top_us[0] == 1500u);
	CHECK(a->worst.late_us == 3600u);
	CHECK(b->worst.late_us == 1000u && b->worst.level == 1u);

	if (argc > 1) {
		FILE *f = fopen(argv[1], "wb");

		if (f == NULL || fwrite((const void *)d, sizeof(*d), 1, f) != 1) {
			printf("FAIL: cannot write %s\n", argv[1]);
			fails++;
		}
		if (f != NULL) {
			fclose(f);
		}
	}
	printf("spin_diag recorder: %s (struct %zu B, per-level work %zu B)\n",
	       fails ? "FAILED" : "OK", sizeof(struct island_spin_diag_t), sizeof(struct sd_work));
	return fails ? 1 : 0;
}
