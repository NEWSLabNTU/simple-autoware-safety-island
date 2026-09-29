#!/usr/bin/env bash
# the W10 gate: 5 cold joins (inputs flowing 20 s before the reset), 10 min soak after each;
# runs 1-3 add a mid-run reset at +600 s, then another 10 min soak.
S="$(cd "$(dirname "$0")" && pwd)"; W="$(dirname "$S")"
ELF=${ELF:?set ELF to the image under test}; P=${P:-gate}
for k in 1 2 3 4 5; do
  nmid=0; [ $k -le 3 ] && nmid=1
  "$S/${GATE:-gate.sh}" $P-$k "$ELF" 600 $nmid > "$W/runs/$P-$k.out" 2>&1
  EXPECT=${EXPECT:-mrm_state,emergency_control_cmd,emergency_gear_cmd,emergency_hazard,emergency_turn} python3 "$S/analyze.py" "$W/runs/$P-$k" > "$W/runs/$P-$k.verdict" 2>&1
  sleep 5
done
echo GATE-ALL-DONE
