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

/* No kinematic_state taken since boot (at_ms == 0): no vehicle has reported
 * to the island yet. The island boots before the vehicle's stack, and an
 * emergency stop its INIT failure raises then has nothing to watch: route 3
 * waits another span at such a due instead of latching on a vehicle it has
 * never seen (phase15-S4: the board latched at boot when the stack took
 * longer than the span to report). A sample that was seen and went stale is
 * judged as before (island_judge_stale: a miss). */
static inline bool island_judge_unseen(uint32_t at_ms)
{
	return at_ms == 0u;
}

/* Route 3's stage: what its armed due supervises. */
#define ISLAND_FLOOR_IDLE 0u
#define ISLAND_FLOOR_OPERATOR 1u /* the handler's emergency call: the operator's settle */
#define ISLAND_FLOOR_DIRECT 2u   /* route 3's own latch: the direct path's settle */

enum island_floor_verdict {
	ISLAND_FLOOR_MET = 0,       /* at standstill: disarm */
	ISLAND_FLOOR_LATCH,         /* latch the output, the direct path brakes; re-arm (DIRECT) */
	ISLAND_FLOOR_VEHICLE_FAULT, /* the island's braking command ran a whole settle and the vehicle still moves */
	ISLAND_FLOOR_WAIT           /* latched, but the island's braking command is younger than a settle:
				     * re-arm at its start + the settle (phase15-S6) */
};

/* Route 3 at its due. Not stopped: if the output is not latched yet the
 * command never took effect on the island's side (the operate request lost,
 * or the operator's tick not running), and the direct path is the answer.
 * If it is latched, the island owns the braking command since `braked_ms`
 * ago: the direct path's start at the latch (followed, after a handover, by
 * the operator continuing the same ramp), or the direct path's resume after
 * an operator that went silent (phase15-S6). Only once that command has run
 * a whole settle (`span_ms`, the emergency settle + the standstill
 * observation) is a vehicle still moving the vehicle's fault: the island
 * cannot brake harder than its command. Before that it is no verdict yet
 * (WAIT): a latch from SWT0 or route 2 shortly before route 3's due, or a
 * resume, has not had its settle (phase15-S6: no false vehicle fault). */
static inline enum island_floor_verdict island_judge_floor(bool standstill, bool latched, uint32_t braked_ms,
							   uint32_t span_ms)
{
	if (standstill) {
		return ISLAND_FLOOR_MET;
	}
	if (!latched) {
		return ISLAND_FLOOR_LATCH;
	}
	if (braked_ms >= span_ms) {
		return ISLAND_FLOOR_VEHICLE_FAULT;
	}
	return ISLAND_FLOOR_WAIT;
}

/* phase15-S6: a slot handed over to its component's executor path reports
 * each tick that publishes the emergency (island_supervisor_handover, at
 * `alive_ms`, uptime ms, wrapping). Silent for `periods` of its own period
 * (`period_ms`) at `now_ms`, its tick is not running: the direct path
 * resumes the slot. */
static inline bool island_judge_resume(uint32_t now_ms, uint32_t alive_ms, uint32_t period_ms, uint32_t periods)
{
	return (uint32_t)(now_ms - alive_ms) >= period_ms * periods;
}

/* phase15-S7: autoware_adapi_v1_msgs/MrmState values the island reports. */
#define ISLAND_MRM_OPERATING 2u
#define ISLAND_MRM_SUCCEEDED 3u
#define ISLAND_MRM_FAILED 4u
#define ISLAND_MRM_EMERGENCY_STOP 2u

/* The state the island's mrm_state carries: MRM_FAILED once route 3 has
 * found the vehicle-side fault (the handler's tick and the direct path's
 * handler slot alike), else the state as computed. The behaviour is not
 * touched: it stays EMERGENCY_STOP under the latch. */
static inline uint16_t island_judge_mrm_state(uint16_t state, bool vehicle_fault)
{
	return vehicle_fault ? (uint16_t)ISLAND_MRM_FAILED : state;
}

/* Autoware 1.5.0's vehicle_cmd_gate (VehicleCmdGate::onMrmState): the
 * emergency command and the emergency hazard lights pass while this holds.
 * Mirrored for the host tests: MRM_FAILED keeps it as long as the behaviour
 * is EMERGENCY_STOP. */
static inline bool island_autoware_gate_emergency(uint16_t state, uint16_t behavior)
{
	return (state == ISLAND_MRM_OPERATING || state == ISLAND_MRM_SUCCEEDED || state == ISLAND_MRM_FAILED) &&
	       behavior == ISLAND_MRM_EMERGENCY_STOP;
}

#endif /* ISLAND_SUPERVISOR_JUDGE_H */
