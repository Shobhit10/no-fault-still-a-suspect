#!/bin/bash
# cpu_hog.sh: one single-service CPU hog (E3 fault).
#
# CPU_LOOPS self-limiting busy loops run inside the service's application container for DURATION
# seconds. They compete with the application inside its own CPU quota, so the service is throttled
# and its callers see the delay. The paper used CPU_LOOPS=128 and DURATION=300, chosen by logged
# pilots that were never evaluated.
#
# usage: cpu_hog.sh <namespace> <service> <case_id> <events_jsonl>
# env:   DURATION (300)  CPU_LOOPS (128)  KUBE_CONTEXT (optional)
set -u
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
NAMESPACE=$1
SVC=$2
CASE_ID=$3
EVENTS=$4
CPU_LOOPS=${CPU_LOOPS:-128}
source "$HERE/fault_lib.sh"
# fire_fault starts ceil(limit / 1000) loops; report CPU_LOOPS cores so that it starts CPU_LOOPS
cpu_limit_milli() { echo $(( CPU_LOOPS * 1000 )); }

t0=$(date +%s)
ok=0
for attempt in 1 2 3; do
  if fire_fault "$SVC" cpu ""; then ok=1; break; fi
  echo "  attempt $attempt failed for $NAMESPACE/$SVC; retrying in 5 s"
  sleep 5
done
if [ "$ok" -ne 1 ]; then
  echo "{\"case_id\": \"$CASE_ID\", \"namespace\": \"$NAMESPACE\", \"service\": \"$SVC\", \"kind\": \"cpu_saturation\", \"fired\": false, \"t_fire\": $t0}" >> "$EVENTS"
  exit 1
fi
t0=$(date +%s)
echo "{\"case_id\": \"$CASE_ID\", \"namespace\": \"$NAMESPACE\", \"service\": \"$SVC\", \"kind\": \"cpu_saturation\", \"cpu_loops\": $CPU_LOOPS, \"fired\": true, \"t_fire\": $t0, \"t_end\": $((t0 + DURATION))}" >> "$EVENTS"
echo "[$t0] fired cpu x$CPU_LOOPS on $NAMESPACE/$SVC for ${DURATION}s"
