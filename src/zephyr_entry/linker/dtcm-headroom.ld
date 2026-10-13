/*
 * phase9-C10: DTCM headroom guard. The link fails when less than 8 KiB of
 * DTCM is left. __dtcm_end closes Zephyr's own .dtcm_* sections, which follow
 * the relocated .dtcm_bss_reloc; __DTCM_end closes the devicetree
 * memory-region section named DTCM. Both are counted so neither path can eat
 * the margin unseen. Why 8 KiB: see src/zephyr_entry/CMakeLists.txt.
 */
ASSERT(ORIGIN(DTCM) + LENGTH(DTCM) - MAX(__dtcm_end, __DTCM_end) >= 8192,
       "island: DTCM has less than 8 KiB free (phase9-C10 headroom guard)")
