/* DIAG (spin latency, phase9 spin-latency unit). Included once, by
 * island_trace.h inside the runtime TU, when CONFIG_ISLAND_SPIN_DIAG is on.
 *
 * Breaks every spin_once-to-spin_once interval of the executor thread into
 * the five segments nano-ros marks with event 40 (phase | value << 8):
 *   S0 entry -> before the wait, S1 the wait + drive_io, S2 dispatch,
 *   S3 post-dispatch rules, S4 return -> next entry (the caller's loop),
 * and charges each segment's wall time to: the spin thread's own execution,
 * the idle thread, and the rest (other threads; ISRs are charged to whichever
 * thread they interrupted, so the serial ISR is counted on its own).
 * Contended zenoh-pico lock waits arrive through island_diag_lock_wait (weak
 * in nano-ros's Zephyr system layer and the serial TX path).
 *
 * Read over SWD by symbol (tools/timeline/spin_diag.py): the struct is
 * plain u32 words. */
#ifndef ISLAND_SPIN_DIAG_H
#define ISLAND_SPIN_DIAG_H

#include <zephyr/kernel.h>
#include <string.h>

#define SD_NOMINAL_US 10000u
#define SD_BINS 40u
#define SD_RING 48u
#define SD_LATE_US 2000u
#define SD_THREADS 16u
#define SD_SEGS 5u

#ifdef __cplusplus
extern "C" {
#endif
extern volatile uint32_t _z_diag_isr_cycles;
extern volatile uint32_t _z_diag_isr_count;
#ifdef __cplusplus
}
#endif

struct sd_rec {
	uint32_t uptime_ms;
	uint32_t interval_us;
	uint32_t seg_wall[SD_SEGS];
	uint32_t seg_main[SD_SEGS];
	uint32_t seg_idle[SD_SEGS];
	uint32_t park_bound_us;
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
};

struct sd_thr {
	uint32_t tid;
	uint32_t prio;
	char name[16];
};

struct island_spin_diag_t {
	uint32_t magic; /* 'SDG1' */
	uint32_t rec_words;
	uint32_t spins;
	uint32_t late; /* intervals at or over SD_LATE_US late */
	uint32_t max_late_us;
	uint32_t hist[SD_BINS]; /* lateness in ms bins, last bin = more */
	uint32_t seg_max_wall[SD_SEGS];
	uint32_t ring_next;
	uint32_t nthr;
	struct sd_thr thr[SD_THREADS];
	struct sd_rec worst;
	struct sd_rec ring[SD_RING];
};

#ifdef __cplusplus
extern "C" {
#endif
volatile struct island_spin_diag_t island_spin_diag;
#ifdef __cplusplus
}
#endif

/* Working state, not read by the host. */
static struct k_thread *sd_spin_thread;
static uint32_t sd_ph_cyc[SD_SEGS + 1]; /* phase 0..4 of the spin under way */
static uint64_t sd_ph_main[SD_SEGS + 1];
static uint64_t sd_ph_idle[SD_SEGS + 1];
static bool sd_have_prev;
static struct sd_rec sd_cur;     /* filled while the spin runs */
static uint64_t sd_thr_prev[SD_THREADS];
static uint64_t sd_thr_now[SD_THREADS];
static uint32_t sd_cb_t0, sd_cb_slot;
static uint64_t sd_cb_main0, sd_cb_idle0;
static uint32_t sd_isr_c0, sd_isr_n0;

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

	if (i < 0) {
		if (island_spin_diag.nthr >= SD_THREADS) {
			return;
		}
		i = (int)island_spin_diag.nthr;
		volatile struct sd_thr *e = &island_spin_diag.thr[i];
		e->tid = tid;
		e->prio = (uint32_t)k_thread_priority_get((k_tid_t)t);
		const char *nm = k_thread_name_get((k_tid_t)t);
		for (uint32_t j = 0; j < sizeof(e->name); j++) {
			e->name[j] = (nm != NULL && j < sizeof(e->name) - 1u) ? nm[j] : 0;
			if (nm != NULL && nm[j] == 0) {
				nm = NULL;
			}
		}
		island_spin_diag.nthr = (uint32_t)i + 1u;
		sd_thr_prev[i] = 0;
	}
	k_thread_runtime_stats_t st;
	k_thread_runtime_stats_get((k_tid_t)t, &st);
	sd_thr_now[i] = st.execution_cycles;
}

static void sd_close_interval(uint32_t now_cyc)
{
	/* Per-thread deltas over the interval just closed. */
	for (uint32_t i = 0; i < SD_THREADS; i++) {
		sd_thr_now[i] = sd_thr_prev[i];
	}
	k_thread_foreach_unlocked(sd_thread_cb, NULL);
	uint32_t interval_us = sd_us(now_cyc - sd_ph_cyc[0]);

	sd_cur.interval_us = interval_us;
	sd_cur.uptime_ms = k_uptime_get_32();
	sd_cur.isr_us = sd_us(_z_diag_isr_cycles - sd_isr_c0);
	sd_cur.isr_n = _z_diag_isr_count - sd_isr_n0;
	uint32_t spin_tid = (uint32_t)(uintptr_t)sd_spin_thread;
	for (uint32_t k = 0; k < 3u; k++) {
		sd_cur.top_tid[k] = 0;
		sd_cur.top_us[k] = 0;
	}
	for (uint32_t i = 0; i < island_spin_diag.nthr; i++) {
		uint32_t tid = island_spin_diag.thr[i].tid;
		uint32_t d = sd_us64(sd_thr_now[i] - sd_thr_prev[i]);
		sd_thr_prev[i] = sd_thr_now[i];
		if (tid == spin_tid) {
			continue;
		}
		for (uint32_t k = 0; k < 3u; k++) {
			if (d > sd_cur.top_us[k]) {
				for (uint32_t m = 2u; m > k; m--) {
					sd_cur.top_us[m] = sd_cur.top_us[m - 1u];
					sd_cur.top_tid[m] = sd_cur.top_tid[m - 1u];
				}
				sd_cur.top_us[k] = d;
				sd_cur.top_tid[k] = tid;
				break;
			}
		}
	}
	uint32_t late = interval_us > SD_NOMINAL_US ? interval_us - SD_NOMINAL_US : 0u;
	uint32_t bin = late / 1000u;

	if (bin >= SD_BINS) {
		bin = SD_BINS - 1u;
	}
	island_spin_diag.hist[bin]++;
	island_spin_diag.spins++;
	for (uint32_t s = 0; s < SD_SEGS; s++) {
		if (sd_cur.seg_wall[s] > island_spin_diag.seg_max_wall[s]) {
			island_spin_diag.seg_max_wall[s] = sd_cur.seg_wall[s];
		}
	}
	if (late >= SD_LATE_US) {
		island_spin_diag.late++;
		uint32_t r = island_spin_diag.ring_next % SD_RING;
		memcpy((void *)&island_spin_diag.ring[r], &sd_cur, sizeof(sd_cur));
		island_spin_diag.ring_next++;
	}
	if (late > island_spin_diag.max_late_us) {
		island_spin_diag.max_late_us = late;
		memcpy((void *)&island_spin_diag.worst, &sd_cur, sizeof(sd_cur));
	}
}

static void sd_phase(uint32_t phase, uint32_t value)
{
	uint32_t now = k_cycle_get_32();
	uint64_t mc = sd_main_cyc();
	uint64_t ic = sd_idle_cyc();

	if (phase == 0u) {
		if (sd_spin_thread == NULL) {
			sd_spin_thread = k_current_get();
			island_spin_diag.magic = 0x31474453u;
			island_spin_diag.rec_words = sizeof(struct sd_rec) / 4u;
		}
		if (sd_have_prev) {
			/* S4: previous phase 4 -> this entry. */
			sd_cur.seg_wall[4] = sd_us(now - sd_ph_cyc[4]);
			sd_cur.seg_main[4] = sd_us64(mc - sd_ph_main[4]);
			sd_cur.seg_idle[4] = sd_us64(ic - sd_ph_idle[4]);
			sd_close_interval(now);
		}
		memset(&sd_cur, 0, sizeof(sd_cur));
		sd_isr_c0 = _z_diag_isr_cycles;
		sd_isr_n0 = _z_diag_isr_count;
		sd_ph_cyc[0] = now;
		sd_ph_main[0] = mc;
		sd_ph_idle[0] = ic;
		sd_have_prev = true;
		return;
	}
	if (phase > 4u || !sd_have_prev) {
		return;
	}
	uint32_t s = phase - 1u;

	sd_cur.seg_wall[s] = sd_us(now - sd_ph_cyc[s]);
	sd_cur.seg_main[s] = sd_us64(mc - sd_ph_main[s]);
	sd_cur.seg_idle[s] = sd_us64(ic - sd_ph_idle[s]);
	sd_ph_cyc[phase] = now;
	sd_ph_main[phase] = mc;
	sd_ph_idle[phase] = ic;
	if (phase == 1u) {
		sd_cur.park_bound_us = value;
	} else if (phase == 3u) {
		sd_cur.idle_path = value;
	}
}

static void island_spin_diag_event(uint32_t id, uint32_t arg)
{
	if (sd_spin_thread != NULL && k_current_get() != sd_spin_thread) {
		return;
	}
	switch (id) {
	case 40u:
		sd_phase(arg & 0xFFu, arg >> 8);
		return;
	case 18u:
		sd_cb_t0 = k_cycle_get_32();
		sd_cb_slot = arg;
		sd_cb_main0 = sd_main_cyc();
		sd_cb_idle0 = sd_idle_cyc();
		return;
	case 19u: {
		uint32_t now = k_cycle_get_32();
		uint32_t w = sd_us(now - sd_cb_t0);

		sd_cur.ncb++;
		if (w >= sd_cur.cb_wall_us) {
			sd_cur.cb_wall_us = w;
			sd_cur.cb_slot = sd_cb_slot;
			sd_cur.cb_main_us = sd_us64(sd_main_cyc() - sd_cb_main0);
			sd_cur.cb_idle_us = sd_us64(sd_idle_cyc() - sd_cb_idle0);
			sd_cur.cb_off_us = sd_us(sd_cb_t0 - sd_ph_cyc[0]);
		}
		return;
	}
	case 25u:
		sd_cur.ntake++;
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

	if (sd_spin_thread != NULL && k_current_get() == sd_spin_thread) {
		sd_cur.lk_main_n++;
		sd_cur.lk_main_us += us;
		if (us >= sd_cur.lk_main_max_us) {
			sd_cur.lk_main_max_us = us;
			sd_cur.lk_main_max_ra = (uint32_t)(uintptr_t)ra;
			sd_cur.lk_main_max_m = (uint32_t)(uintptr_t)m;
		}
	} else {
		/* Racy against the spin thread's record by design: a diagnostic. */
		sd_cur.lk_oth_n++;
		sd_cur.lk_oth_us += us;
		if (us >= sd_cur.lk_oth_max_us) {
			sd_cur.lk_oth_max_us = us;
			sd_cur.lk_oth_max_ra = (uint32_t)(uintptr_t)ra;
		}
	}
}
#ifdef __cplusplus
}
#endif

#endif /* ISLAND_SPIN_DIAG_H */
