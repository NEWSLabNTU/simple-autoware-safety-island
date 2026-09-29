#!/usr/bin/env bash
# offsets.sh ELF > offsets.json : struct offsets the poller needs, asked of gdb (never hand-copied)
elf=$1
GDB=/home/aeon/.nros/sdk/arm-none-eabi-gcc/13.2-nros4/bin/arm-none-eabi-gdb
[ -x "$GDB" ] || GDB=$(ls /home/aeon/.nros/sdk/zephyr-sdk-*/*/zephyr-sdk-*/gnu/arm-zephyr-eabi/bin/arm-zephyr-eabi-gdb 2>/dev/null | head -1)
$GDB -batch -nx "$elf" \
  -ex 'printf "{\n"' \
  -ex 'printf "\"subs_off\": %d,\n", (int)&((struct zpico_session*)0)->subscribers' \
  -ex 'printf "\"sub_size\": %d,\n", (int)sizeof(((struct zpico_session*)0)->subscribers[0])' \
  -ex 'printf "\"sub_n\": %d,\n", (int)(sizeof(((struct zpico_session*)0)->subscribers)/sizeof(((struct zpico_session*)0)->subscribers[0]))' \
  -ex 'printf "\"sub_ring_off\": %d,\n", (int)&((struct zpico_session*)0)->subscribers[0].ring' \
  -ex 'printf "\"sub_active_off\": %d,\n", (int)&((struct zpico_session*)0)->subscribers[0].active' \
  -ex 'printf "\"ring_tail_off\": %d,\n", (int)&((zpico_ring_desc_t*)0)->tail' \
  -ex 'printf "\"ring_head_off\": %d,\n", (int)&((zpico_ring_desc_t*)0)->head' \
  -ex 'printf "\"sess_size\": %d,\n", (int)sizeof(struct zpico_session)' \
  -ex 'printf "\"th_prio\": %d,\n", (int)&((struct k_thread*)0)->base.prio' \
  -ex 'printf "\"th_state\": %d,\n", (int)&((struct k_thread*)0)->base.thread_state' \
  -ex 'printf "\"th_usage\": %d,\n", (int)&((struct k_thread*)0)->base.usage.total' \
  -ex 'printf "\"th_next\": %d,\n", (int)&((struct k_thread*)0)->next_thread' \
  -ex 'printf "\"th_name\": %d,\n", (int)&((struct k_thread*)0)->name' \
  -ex 'printf "\"th_entry\": %d,\n", (int)&((struct k_thread*)0)->entry.pEntry' \
  -ex 'printf "\"k_threads\": %d,\n", (int)&((struct z_kernel*)0)->threads' \
  -ex 'printf "\"k_usage\": %d\n", (int)&((struct z_kernel*)0)->usage.total' \
  -ex 'printf "}\n"' 2>&1
