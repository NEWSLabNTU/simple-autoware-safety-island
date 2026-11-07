/* DIAG (spin latency, phase9 spin-latency unit). Included once, by
 * island_trace.h inside the runtime TU, when CONFIG_ISLAND_SPIN_DIAG is on.
 *
 * Breaks every spin_once-to-spin_once interval of each executor thread (a
 * "level": one executor per derived sched task) into the five segments
 * nano-ros marks with event 40 (phase | value << 8):
 *   S0 entry -> before the wait, S1 the wait + drive_io, S2 dispatch,
 *   S3 post-dispatch rules, S4 return -> next entry (the caller's loop),
 * and charges each segment's wall time to: the level's own thread, the idle
 * thread, and the rest (other threads; ISRs are charged to whichever thread
 * they interrupted, so the serial ISR is counted on its own). Contended
 * zenoh-pico lock waits arrive through island_diag_lock_wait (weak in
 * nano-ros's Zephyr system layer and the serial TX path).
 *
 * Lateness is per interval, against that interval's own park bound (the
 * value of phase 1: the time the pass planned to wait for its next wake):
 *   late = interval - park_bound   (0 when the interval ran shorter)
 * so an idle interval of a 100 ms level that parks 85 ms and returns 1 ms
 * after its wake reads 1 ms late, whatever the level's period. An interval
 * with no phase 1 (a pass that did not reach the park) has no bound; it is
 * counted (nobound) and not judged.
 *
 * Every thread that emits phase 0 is followed, up to SD_LEVELS (in the
 * order they first spin; more are counted in lev_dropped). Each level has
 * its own counts, histogram, segment maxima and worst record; the ring of
 * late records is shared and every record names its level.
 *
 * Read over SWD by symbol (tools/board/spin_diag.py): the struct is plain
 * u32 words, and its header carries the dimensions the decoder needs. */
#ifndef ISLAND_SPIN_DIAG_H
#define ISLAND_SPIN_DIAG_H

#include <zephyr/kernel.h>
#include <string.h>

#define SD_MAGIC 0x32474453u /* 'SDG2' */
#define SD_LEVELS 4u
#define SD_BINS 40u
#define SD_RING 48u
#define SD_LATE_US 2000u
#define SD_THREADS 16u
#define SD_SEGS 5u
#define SD_NO_BOUND 0xFFFFFFFFu

#ifdef __cplusplus
extern "C" {
#endif
/* The serial ISR's time and calls: zenoh-pico's own counters
 * (CONFIG_NROS_ZENOH_SERIAL_ISR_STATS, nano-ros phase-474 I13). */
extern volatile uint32_t _z_zephyr_serial_isr_cycles;
extern volatile uint32_t _z_zephyr_serial_isr_calls;
#define _z_diag_isr_cycles _z_zephyr_serial_isr_cycles
#define _z_diag_isr_count _z_zephyr_serial_isr_calls
#ifdef __cplusplus
}
#endif

struct sd_rec {
	uint32_t uptime_ms;
	uint32_t interval_us;
	uint32_t seg_wall[SD_SEGS];
	uint32_t seg_main[SD_SEGS];
	uint32_t seg_idle[SD_SEGS];
	uint32_t park_bound_us; /* SD_NO_BOUND: no phase 1 in this interval */
	uint32_t idle_path;
	uint32_t ncb;
	uint32_t ntake;
	uint32_t cb_slot;
	uint32_t cb_wall_us;
	uint32_t cb_main_us;
	uint32_t cb_idle_us;
	uint32_t cb_off_us;
	uint32_t lk_main_n;
	uint32_t lk_main_us;
	uint32_t lk_main_max_us;
	uint32_t lk_main_max_ra;
	uint32_t lk_main_max_m;
	uint32_t lk_oth_n;
	uint32_t lk_oth_us;
	uint32_t lk_oth_max_us;
	uint32_t lk_oth_max_ra;
	uint32_t isr_us;
	uint32_t isr_n;
	uint32_t top_tid[3];
	uint32_t top_us[3];
	uint32_t cb_isr_us; /* serial ISR time inside the longest callback */
	uint32_t cb_isr_n;
	uint32_t level;   /* index into island_spin_diag.lev */
	uint32_t late_us; /* interval - park bound, 0 if shorter */
};

struct sd_thr {
	uint32_t tid;
	uint32_t prio;
	char name[16];
};

struct sd_level {
	uint32_t tid;
	uint32_t prio;
	char name[16];
	uint32_t spins;   /* intervals closed */
	uint32_t nobound; /* of them, with no park bound (not judged) */
	uint32_t late;    /* judged intervals at or over SD_LATE_US late */
	uint32_t max_late_us;
	uint32_t bound_min_us; /* park bounds of the judged intervals */
	uint32_t bound_max_us;
	uint32_t interval_max_us;
	uint32_t hist[SD_BINS]; /* lateness in ms bins, last bin = more */
	uint32_t seg_max_wall[SD_SEGS];
	struct sd_rec worst;
};

struct island_spin_diag_t {
	uint32_t magic;
	uint32_t rec_words;
	uint32_t lev_words;
	uint32_t dims;    /* SD_LEVELS | SD_BINS << 8 | SD_RING << 16 | SD_THREADS << 24 */
	uint32_t late_us; /* SD_LATE_US */
	uint32_t nlev;
	uint32_t lev_dropped; /* phase-0 threads past SD_LEVELS */
	uint32_t ring_next;
	uint32_t nthr;
	struct sd_level lev[SD_LEVELS];
	struct sd_thr thr[SD_THREADS];
	struct sd_rec ring[SD_RING];
};

#ifdef __cplusplus
extern "C" {
#endif
volatile struct island_spin_diag_t island_spin_diag;
#ifdef __cplusplus
}
#endif

/* Working state of one level, touched only by its own thread (the "other"
 * lock waits excepted, racy by design). Not read by the host. */
struct sd_work {
	struct k_thread *thread;
	uint32_t ph_cyc[SD_SEGS + 1]; /* phase 0..4 of the spin under way */
	uint64_t ph_main[SD_SEGS + 1];
	uint64_t ph_idle[SD_SEGS + 1];
	bool have_prev;
	bool have_bound;
	struct sd_rec cur; /* filled while the spin runs */
	uint64_t thr_prev[SD_THREADS];
	uint32_t cb_t0, cb_slot;
	uint64_t cb_main0, cb_idle0;
	uint32_t isr_c0, isr_n0;
	uint32_t cb_isr_c0, cb_isr_n0;
};

static struct sd_work sd_lv[SD_LEVELS];
static uint64_t sd_thr_now[SD_THREADS]; /* scratch, under k_sched_lock */

static inline uint32_t sd_us(uint32_t cyc)
{
	return (uint32_t)(((uint64_t)cyc * 1000000u) / (uint64_t)sys_clock_hw_cycles_per_sec());
}

static inline uint32_t sd_us64(uint64_t cyc)
{
	return (uint32_t)((cyc * 1000000u) / (uint64_t)sys_clock_hw_cycles_per_sec());
}

static inline uint64_t sd_main_cyc(void)
{
	k_thread_runtime_stats_t st;

	k_thread_runtime_stats_get(k_current_get(), &st);
	return st.execution_cycles;
}

static inline uint64_t sd_idle_cyc(void)
{
	k_thread_runtime_stats_t st;

	k_thread_runtime_stats_all_get(&st);
	return st.idle_cycles;
}

static void sd_copy_name(volatile char *dst, const char *nm)
{
	for (uint32_t j = 0; j < 16u; j++) {
		dst[j] = (nm != NULL && j < 15u) ? nm[j] : 0;
		if (nm != NULL && nm[j] == 0) {
			nm = NULL;
		}
	}
}

/* The level of a thread, NULL if it is not one. */
static inline struct sd_work *sd_work_of(struct k_thread *t)
{
	uint32_t n = island_spin_diag.nlev;

	for (uint32_t i = 0; i < n; i++) {
		if (sd_lv[i].thread == t) {
			return &sd_lv[i];
		}
	}
	return NULL;
}

static struct sd_work *sd_register(struct k_thread *t)
{
	struct sd_work *w = NULL;

	k_sched_lock();
	if (island_spin_diag.magic != SD_MAGIC) {
		island_spin_diag.rec_words = sizeof(struct sd_rec) / 4u;
		island_spin_diag.lev_words = sizeof(struct sd_level) / 4u;
		island_spin_diag.dims = SD_LEVELS | (SD_BINS << 8) | (SD_RING << 16) | (SD_THREADS << 24);
		island_spin_diag.late_us = SD_LATE_US;
		island_spin_diag.magic = SD_MAGIC;
	}
	uint32_t i = island_spin_diag.nlev;

	if (i < SD_LEVELS) {
		volatile struct sd_level *l = &island_spin_diag.lev[i];

		w = &sd_lv[i];
		w->thread = t;
		l->tid = (uint32_t)(uintptr_t)t;
		l->prio = (uint32_t)k_thread_priority_get((k_tid_t)t);
		sd_copy_name(l->name, k_thread_name_get((k_tid_t)t));
		l->bound_min_us = SD_NO_BOUND;
		island_spin_diag.nlev = i + 1u;
	} else {
		island_spin_diag.lev_dropped++;
	}
	k_sched_unlock();
	return w;
}

static int sd_thr_index(uint32_t tid)
{
	for (uint32_t i = 0; i < island_spin_diag.nthr; i++) {
		if (island_spin_diag.thr[i].tid == tid) {
			return (int)i;
		}
	}
	return -1;
}

static void sd_thread_cb(const struct k_thread *t, void *user)
{
	(void)user;
	uint32_t tid = (uint32_t)(uintptr_t)t;
	int i = sd_thr_index(tid);
	k_thread_runtime_stats_t st;

	k_thread_runtime_stats_get((k_tid_t)t, &st);
	if (i < 0) {
		if (island_spin_diag.nthr >= SD_THREADS) {
			return;
		}
		i = (int)island_spin_diag.nthr;
		volatile struct sd_thr *e = &island_spin_diag.thr[i];
		e->tid = tid;
		e->prio = (uint32_t)k_thread_priority_get((k_tid_t)t);
		sd_copy_name(e->name, k_thread_name_get((k_tid_t)t));
		island_spin_diag.nthr = (uint32_t)i + 1u;
		/* A thread first seen now starts every level's delta from here. */
		for (uint32_t l = 0; l < SD_LEVELS; l++) {
			sd_lv[l].thr_prev[i] = st.execution_cycles;
		}
	}
	sd_thr_now[i] = st.execution_cycles;
}

static void sd_close_interval(struct sd_work *w, uint32_t now_cyc)
{
	struct sd_rec *c = &w->cur;
	uint32_t li = (uint32_t)(w - sd_lv);
	volatile struct sd_level *l = &island_spin_diag.lev[li];
	uint32_t interval_us = sd_us(now_cyc - w->ph_cyc[0]);

	/* The thread table, the scratch and the ring are shared by the levels:
	 * no other level may run until this interval is filed. */
	k_sched_lock();
	for (uint32_t i = 0; i < SD_THREADS; i++) {
		sd_thr_now[i] = w->thr_prev[i];
	}
	k_thread_foreach_unlocked(sd_thread_cb, NULL);
	c->level = li;
	c->interval_us = interval_us;
	c->uptime_ms = k_uptime_get_32();
	c->isr_us = sd_us(_z_diag_isr_cycles - w->isr_c0);
	c->isr_n = _z_diag_isr_count - w->isr_n0;
	uint32_t spin_tid = (uint32_t)(uintptr_t)w->thread;
	for (uint32_t k = 0; k < 3u; k++) {
		c->top_tid[k] = 0;
		c->top_us[k] = 0;
	}
	for (uint32_t i = 0; i < island_spin_diag.nthr; i++) {
		uint32_t tid = island_spin_diag.thr[i].tid;
		uint32_t d = sd_us64(sd_thr_now[i] - w->thr_prev[i]);
		w->thr_prev[i] = sd_thr_now[i];
		if (tid == spin_tid) {
			continue;
		}
		for (uint32_t k = 0; k < 3u; k++) {
			if (d > c->top_us[k]) {
				for (uint32_t m = 2u; m > k; m--) {
					c->top_us[m] = c->top_us[m - 1u];
					c->top_tid[m] = c->top_tid[m - 1u];
				}
				c->top_us[k] = d;
				c->top_tid[k] = tid;
				break;
			}
		}
	}
	l->spins++;
	if (interval_us > l->interval_max_us) {
		l->interval_max_us = interval_us;
	}
	for (uint32_t s = 0; s < SD_SEGS; s++) {
		if (c->seg_wall[s] > l->seg_max_wall[s]) {
			l->seg_max_wall[s] = c->seg_wall[s];
		}
	}
	if (!w->have_bound) {
		c->park_bound_us = SD_NO_BOUND;
		c->late_us = 0;
		l->nobound++;
		k_sched_unlock();
		return;
	}
	uint32_t bound = c->park_bound_us;
	uint32_t late = interval_us > bound ? interval_us - bound : 0u;
	uint32_t bin = late / 1000u;

	c->late_us = late;
	if (bound < l->bound_min_us) {
		l->bound_min_us = bound;
	}
	if (bound > l->bound_max_us) {
		l->bound_max_us = bound;
	}
	if (bin >= SD_BINS) {
		bin = SD_BINS - 1u;
	}
	l->hist[bin]++;
	if (late >= SD_LATE_US) {
		l->late++;
		uint32_t r = island_spin_diag.ring_next % SD_RING;
		memcpy((void *)&island_spin_diag.ring[r], c, sizeof(*c));
		island_spin_diag.ring_next++;
	}
	if (late > l->max_late_us) {
		l->max_late_us = late;
		memcpy((void *)&l->worst, c, sizeof(*c));
	}
	k_sched_unlock();
}

static void sd_phase(struct sd_work *w, uint32_t phase, uint32_t value)
{
	uint32_t now = k_cycle_get_32();
	uint64_t mc = sd_main_cyc();
	uint64_t ic = sd_idle_cyc();

	if (phase == 0u) {
		if (w->have_prev) {
			/* S4: previous phase 4 -> this entry. */
			w->cur.seg_wall[4] = sd_us(now - w->ph_cyc[4]);
			w->cur.seg_main[4] = sd_us64(mc - w->ph_main[4]);
			w->cur.seg_idle[4] = sd_us64(ic - w->ph_idle[4]);
			sd_close_interval(w, now);
		}
		memset(&w->cur, 0, sizeof(w->cur));
		w->have_bound = false;
		w->isr_c0 = _z_diag_isr_cycles;
		w->isr_n0 = _z_diag_isr_count;
		w->ph_cyc[0] = now;
		w->ph_main[0] = mc;
		w->ph_idle[0] = ic;
		w->have_prev = true;
		return;
	}
	if (phase > 4u || !w->have_prev) {
		return;
	}
	uint32_t s = phase - 1u;

	w->cur.seg_wall[s] = sd_us(now - w->ph_cyc[s]);
	w->cur.seg_main[s] = sd_us64(mc - w->ph_main[s]);
	w->cur.seg_idle[s] = sd_us64(ic - w->ph_idle[s]);
	w->ph_cyc[phase] = now;
	w->ph_main[phase] = mc;
	w->ph_idle[phase] = ic;
	if (phase == 1u) {
		w->cur.park_bound_us = value;
		w->have_bound = true;
	} else if (phase == 3u) {
		w->cur.idle_path = value;
	}
}

static void island_spin_diag_event(uint32_t id, uint32_t arg)
{
	struct k_thread *t = k_current_get();
	struct sd_work *w = sd_work_of(t);

	if (w == NULL) {
		/* A thread becomes a level by its first phase 0. */
		if (id != 40u || (arg & 0xFFu) != 0u) {
			return;
		}
		w = sd_register(t);
		if (w == NULL) {
			return;
		}
	}
	switch (id) {
	case 40u:
		sd_phase(w, arg & 0xFFu, arg >> 8);
		return;
	case 18u:
		w->cb_t0 = k_cycle_get_32();
		w->cb_slot = arg;
		w->cb_main0 = sd_main_cyc();
		w->cb_idle0 = sd_idle_cyc();
		w->cb_isr_c0 = _z_diag_isr_cycles;
		w->cb_isr_n0 = _z_diag_isr_count;
		return;
	case 19u: {
		uint32_t now = k_cycle_get_32();
		uint32_t us = sd_us(now - w->cb_t0);

		w->cur.ncb++;
		if (us >= w->cur.cb_wall_us) {
			w->cur.cb_wall_us = us;
			w->cur.cb_slot = w->cb_slot;
			w->cur.cb_main_us = sd_us64(sd_main_cyc() - w->cb_main0);
			w->cur.cb_idle_us = sd_us64(sd_idle_cyc() - w->cb_idle0);
			w->cur.cb_off_us = sd_us(w->cb_t0 - w->ph_cyc[0]);
			w->cur.cb_isr_us = sd_us(_z_diag_isr_cycles - w->cb_isr_c0);
			w->cur.cb_isr_n = _z_diag_isr_count - w->cb_isr_n0;
		}
		return;
	}
	case 25u:
		w->cur.ntake++;
		return;
	default:
		return;
	}
}

#ifdef __cplusplus
extern "C" {
#endif
void island_diag_lock_wait(void *m, uint32_t cycles, void *ra)
{
	uint32_t us = sd_us(cycles);
	struct sd_work *w = sd_work_of(k_current_get());

	if (w != NULL) {
		w->cur.lk_main_n++;
		w->cur.lk_main_us += us;
		if (us >= w->cur.lk_main_max_us) {
			w->cur.lk_main_max_us = us;
			w->cur.lk_main_max_ra = (uint32_t)(uintptr_t)ra;
			w->cur.lk_main_max_m = (uint32_t)(uintptr_t)m;
		}
		return;
	}
	/* A wait of a thread that is not a level, charged to every level's
	 * interval under way. Racy against the levels' records by design: a
	 * diagnostic. */
	for (uint32_t i = 0; i < island_spin_diag.nlev; i++) {
		struct sd_rec *c = &sd_lv[i].cur;

		c->lk_oth_n++;
		c->lk_oth_us += us;
		if (us >= c->lk_oth_max_us) {
			c->lk_oth_max_us = us;
			c->lk_oth_max_ra = (uint32_t)(uintptr_t)ra;
		}
	}
}
#ifdef __cplusplus
}
#endif

#endif /* ISLAND_SPIN_DIAG_H */
