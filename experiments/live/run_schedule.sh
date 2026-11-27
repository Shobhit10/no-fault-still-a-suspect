#!/bin/bash
# run_schedule.sh: fire the locked four-outcome schedule and collect windows as they finish.
#
# Reads <out>/protocol.json (written by four_outcome.py lock). At each slot's event time it fires
# the fault (cpu_hog.sh or net_delay.sh) or the surge (load_surge.sh) in every deployment, or
# records a quiet slot. A slot that cannot be fired within 60 s of its locked time is recorded as
# not fired, never moved. Collection runs in the background, serialised with flock, 8 minutes after
# each slot; labels are written at the end.
#
# usage: run_schedule.sh <out_dir> <config.json>
# env:   PYTHON (python3)  KUBE_CONTEXT  DEBUG_PODS_FILE (network faults)
set -u
OUT=$(cd "$1" && pwd)
CONFIG=$(cd "$(dirname "$2")" && pwd)/$(basename "$2")
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PY=${PYTHON:-python3}
EV=$OUT/events.jsonl
LOG=$OUT/driver.log
SCHED=$OUT/driver_schedule.txt
ARM=$("$PY" -c "import json,sys; print(json.load(open(sys.argv[1]))['arm'])" "$OUT/protocol.json")

"$PY" - "$OUT/protocol.json" > "$SCHED" <<'EOF'
import json, sys
p = json.load(open(sys.argv[1]))
f = p["fault"]
for r in p["schedule"]:
    print(r["event"], r["slot"], r["class"], r["system"], r["target"] or "-", r["case_id"],
          p["surge"]["factor"][r["system"]], p["surge"]["loadgen"][r["system"]],
          f.get("cpu_loops", 0), f.get("delay_ms", 0), f.get("jitter_ms", 0))
EOF
echo "[$(date +%s)] driver start, $(wc -l < "$SCHED") windows" >> "$LOG"

collect_bg() {
  ( sleep 480; flock "$OUT/.collect.lock" "$PY" "$HERE/four_outcome.py" --arm "$ARM" --config "$CONFIG" --out "$OUT" collect >> "$OUT/collect.log" 2>&1 ) &
}

for slot in $(awk '{print $2}' "$SCHED" | sort -n -u); do
  ev=$(awk -v s="$slot" '$2==s{print $1; exit}' "$SCHED")
  now=$(date +%s)
  [ "$ev" -gt "$now" ] && sleep $((ev - now))
  late=$(( $(date +%s) - ev ))
  echo "[$(date +%s)] slot $slot late=${late}s" >> "$LOG"
  pids=()
  while read -r e sl cls sys tgt cid fac lg loops dms jms; do
    if [ "$late" -gt 60 ]; then
      echo "{\"case_id\": \"$cid\", \"kind\": \"$cls\", \"fired\": false, \"reason\": \"late ${late}s\", \"t_fire\": $(date +%s)}" >> "$EV"
      continue
    fi
    ns=$("$PY" -c "import json,sys; print(json.load(open(sys.argv[1]))['systems'][sys.argv[2]]['namespace'])" "$CONFIG" "$sys")
    case $cls in
      LOC)
        if [ "$ARM" = "e3" ]; then
          CASE_ID=$cid DURATION=300 CPU_LOOPS=$loops bash "$HERE/faults/cpu_hog.sh" "$ns" "$tgt" "$cid" "$EV" >> "$LOG" 2>&1 &
        else
          CASE_ID=$cid DURATION=300 DELAY_MS=$dms DELAY_JITTER_MS=$jms bash "$HERE/faults/net_delay.sh" "$ns" "$tgt" "$cid" "$EV" >> "$LOG" 2>&1 &
        fi
        pids+=($!) ;;
      UNR) DURATION=300 SURGE_FACTOR=$fac bash "$HERE/faults/load_surge.sh" "$ns" "$lg" "$cid" "$EV" >> "$LOG" 2>&1 &
           pids+=($!) ;;
      NI)  echo "{\"case_id\": \"$cid\", \"kind\": \"none\", \"fired\": null, \"t_fire\": $(date +%s)}" >> "$EV" ;;
    esac
  done < <(awk -v s="$slot" '$2==s' "$SCHED")
  for p in ${pids[@]+"${pids[@]}"}; do wait "$p"; done
  collect_bg
done
wait
sleep 300
flock "$OUT/.collect.lock" "$PY" "$HERE/four_outcome.py" --arm "$ARM" --config "$CONFIG" --out "$OUT" collect >> "$OUT/collect.log" 2>&1
"$PY" "$HERE/four_outcome.py" --arm "$ARM" --config "$CONFIG" --out "$OUT" label >> "$OUT/collect.log" 2>&1
echo "[$(date +%s)] DRIVER DONE" >> "$LOG"
