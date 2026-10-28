/*
 * A failing assert, recorded where SWD can read it (phase9-C4).
 *
 * The board's console (lpuart0) is not wired, so an assert's printed line is
 * lost even when it prints. This overrides Zephyr's weak assert_post_action()
 * (lib/os/assert.c): the first failing assert writes its file, line, uptime and
 * context into `island_assert_record`, then panics as Zephyr's would. The
 * SWD readout (tools/board/readout.py, assert.txt) decodes it; the file
 * pointer is a string in flash, resolved from the ELF.
 *
 * An assert that fires while the first one is being handled (the fault path
 * asserting on its own printing, the recursion phase9-C4 found) is recorded in
 * the `nested_*` fields and halts on the spot: the first record is the one
 * that matters, and a second k_panic() from inside the fatal handler only
 * escalates to a fault that loses it.
 *
 * Cost: one 32 B record in .bss (the app library's .bss is in DTCM,
 * CMakeLists.txt) and one small function in flash.
 */
#include <stdint.h>
#include <zephyr/arch/cpu.h>
#include <zephyr/fatal.h>
#include <zephyr/init.h>
#include <zephyr/kernel.h>
#include <zephyr/sys/__assert.h>
#if defined(CONFIG_ISLAND_DEBUG_FORCE_ASSERT_LOCKED)
#include <zephyr/shell/shell.h>
#include <zephyr/shell/shell_uart.h>
#endif

#define ISLAND_ASSERT_MAGIC 0x54525341u /* "ASRT" little-endian */

/* Layout read by tools/board/readout.py (ASSERT_FIELDS); all 32-bit. */
struct island_assert_record {
	uint32_t magic;       /* ISLAND_ASSERT_MAGIC once a record is written */
	uint32_t count;       /* failing asserts seen, nested ones included */
	const char *file;     /* __FILE__ of the first */
	uint32_t line;        /* __LINE__ of the first */
	uint32_t uptime_ms;   /* k_uptime_get_32() at the first */
	uint32_t in_isr;      /* 1: the first fired in an ISR or exception */
	const char *nested_file; /* the first assert that fired while handling it */
	uint32_t nested_line;
};

volatile struct island_assert_record island_assert_record;

void assert_post_action(const char *file, unsigned int line)
{
	unsigned int key = irq_lock();
	uint32_t n = island_assert_record.count + 1U;

	island_assert_record.count = n;
	if (n == 1U) {
		island_assert_record.file = file;
		island_assert_record.line = line;
		island_assert_record.uptime_ms = k_uptime_get_32();
		island_assert_record.in_isr = k_is_in_isr() ? 1U : 0U;
		__DMB();
		island_assert_record.magic = ISLAND_ASSERT_MAGIC;
	} else {
		if (island_assert_record.nested_file == NULL) {
			island_assert_record.nested_file = file;
			island_assert_record.nested_line = line;
		}
		k_fatal_halt(K_ERR_KERNEL_PANIC);
	}
	irq_unlock(key);
	k_panic();
	CODE_UNREACHABLE;
}

#if CONFIG_ISLAND_DEBUG_FORCE_ASSERT_MS > 0
/* Test only: one failing __ASSERT this long after boot (phase9-C4's gate). */
static volatile int island_debug_assert_holds;

static void island_debug_assert(void)
{
#if defined(CONFIG_ISLAND_DEBUG_FORCE_ASSERT_LOCKED)
	/* The I16 condition: interrupts locked and the shell's lock held
	 * elsewhere, so an immediate-mode print of the assert has to pend. */
	const struct shell *sh = shell_backend_uart_get_ptr();

	(void)k_sem_take(&sh->ctx->lock_sem, K_FOREVER);
	unsigned int key = irq_lock();
#endif
	__ASSERT(island_debug_assert_holds, "forced by CONFIG_ISLAND_DEBUG_FORCE_ASSERT_MS");
#if defined(CONFIG_ISLAND_DEBUG_FORCE_ASSERT_LOCKED)
	irq_unlock(key);
#endif
}

#if defined(CONFIG_ISLAND_DEBUG_FORCE_ASSERT_ISR)
static void island_debug_assert_timer(struct k_timer *t)
{
	ARG_UNUSED(t);
	island_debug_assert();
}
K_TIMER_DEFINE(island_debug_assert_tm, island_debug_assert_timer, NULL);
#else
static void island_debug_assert_work(struct k_work *w)
{
	ARG_UNUSED(w);
	island_debug_assert();
}
K_WORK_DELAYABLE_DEFINE(island_debug_assert_dw, island_debug_assert_work);
#endif

static int island_debug_assert_arm(void)
{
#if defined(CONFIG_ISLAND_DEBUG_FORCE_ASSERT_ISR)
	k_timer_start(&island_debug_assert_tm, K_MSEC(CONFIG_ISLAND_DEBUG_FORCE_ASSERT_MS), K_NO_WAIT);
#else
	k_work_schedule(&island_debug_assert_dw, K_MSEC(CONFIG_ISLAND_DEBUG_FORCE_ASSERT_MS));
#endif
	return 0;
}
SYS_INIT(island_debug_assert_arm, APPLICATION, 99);
#endif
