/*
 * The supervisor's standstill verdicts, as pure functions (phase15-S2).
 *
 * island_supervisor.c calls these on the reaction thread at a route's due;
 * tests/supervisor/test_judge.c runs them on the host (`just
 * supervisor-test`). No Zephyr header: everything comes in as arguments.
 */
#ifndef ISLAND_SUPERVISOR_JUDGE_H
#define ISLAND_SUPERVISOR_JUDGE_H

#include <stdbool.h>
#include <stdint.h>

/* A kinematic_state sample older than this is not a standstill (10 Hz: three
 * periods). */
#define ISLAND_STANDSTILL_FRESH_MS 300u

/* The vehicle is at standstill now, by a fresh sample: one was noted
 * (at_ms != 0), at most `fresh_ms` before `now_ms` (uptime, wrapping), and
 * its |v| reads 0 mm/s (isStopped()'s < 0.001 m/s). A missing or stale sample
 * is not a standstill: the island cannot see one. */
static inline bool island_judge_standstill(uint32_t now_ms, uint32_t speed_mm_s, uint32_t at_ms,
					   uint32_t fresh_ms)
{
	return at_ms != 0u && (uint32_t)(now_ms - at_ms) <= fresh_ms && speed_mm_s == 0u;
}

/* The sample is there but too old to judge by (a link or localization gap). */
static inline bool island_judge_stale(uint32_t now_ms, uint32_t at_ms, uint32_t fresh_ms)
{
	return at_ms == 0u || (uint32_t)(now_ms - at_ms) > fresh_ms;
}

/* Route 3's stage: what its armed due supervises. */
#define ISLAND_FLOOR_IDLE 0u
#define ISLAND_FLOOR_OPERATOR 1u /* the handler's emergency call: the operator's settle */
#define ISLAND_FLOOR_DIRECT 2u   /* route 3's own latch: the direct path's settle */

enum island_floor_verdict {
	ISLAND_FLOOR_MET = 0,      /* at standstill: disarm */
	ISLAND_FLOOR_LATCH,        /* latch the output, the direct path brakes; re-arm (DIRECT) */
	ISLAND_FLOOR_VEHICLE_FAULT /* a braking command ran a whole settle and the vehicle still moves */
};

/* Route 3 at its due. Not stopped: if the output is not latched yet the
 * command never took effect on the island's side (the operate request lost,
 * or the operator's tick not running), and the direct path is the answer.
 * If it is latched already, something has been publishing the braking
 * command (the direct path, or the operator after its handover) for at least
 * a settle, or this is the direct path's own due: the island cannot brake
 * harder than its command, so the fault is the vehicle's. */
static inline enum island_floor_verdict island_judge_floor(bool standstill, bool latched, uint32_t stage)
{
	if (standstill) {
		return ISLAND_FLOOR_MET;
	}
	if (!latched && stage != ISLAND_FLOOR_DIRECT) {
		return ISLAND_FLOOR_LATCH;
	}
	return ISLAND_FLOOR_VEHICLE_FAULT;
}

#endif /* ISLAND_SUPERVISOR_JUDGE_H */
