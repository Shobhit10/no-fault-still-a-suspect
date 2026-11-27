#!/bin/bash
# net_delay.sh: one single-service network delay (E4 fault).
#
# tc netem adds DELAY_MS +- DELAY_JITTER_MS (normal distribution) to every outgoing packet of the
# service's pod for DURATION seconds (fault_lib.sh fire_network_fault). Because the delivery returns
# before the rule is known to be in place, the qdisc is read back from the pod's network namespace a
# few seconds later; an event whose rule cannot be confirmed is logged as not fired. The paper used
# 150 +- 50 ms for 300 s (the weakest pilot setting with user impact at every target).
#
# usage: net_delay.sh <namespace> <service> <case_id> <events_jsonl>
# env:   DURATION (300)  DELAY_MS (150)  DELAY_JITTER_MS (50)  DEBUG_PODS_FILE  KUBE_CONTEXT
set -u
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
NAMESPACE=$1
SVC=$2
CASE_ID=$3
EVENTS=$4
DELAY_MS=${DELAY_MS:-150}
DELAY_JITTER_MS=${DELAY_JITTER_MS:-50}
source "$HERE/fault_lib.sh"

log_event() {  # fired verified t_fire reason
  echo "{\"case_id\": \"$CASE_ID\", \"namespace\": \"$NAMESPACE\", \"service\": \"$SVC\", \"kind\": \"net_delay\", \"delay_ms\": $DELAY_MS, \"jitter_ms\": $DELAY_JITTER_MS, \"fired\": $1, \"verified\": $2, \"t_fire\": $3, \"t_end\": $(( $3 + DURATION )), \"reason\": \"$4\"}" >> "$EVENTS"
}

ok=0
for attempt in 1 2 3; do
  if fire_network_fault "$SVC" delay ""; then ok=1; break; fi
  echo "  attempt $attempt failed for $NAMESPACE/$SVC; retrying in 5 s"
  sleep 5
done
t0=$(date +%s)
if [ "$ok" -ne 1 ]; then log_event false false "$t0" "fire_failed"; exit 1; fi

sleep 4
pod=$(resolve_pod "$SVC")
route=$(resolve_netns_route "$pod") || route=""
verified=false
if [ -n "$route" ]; then
  IFS='|' read -r dbg sid spid <<< "$route"
  if kc exec "$dbg" -- chroot /host nsenter --net=/proc/${spid}/ns/net -- tc qdisc show dev eth0 2>/dev/null \
       | grep -q "netem.*delay"; then
    verified=true
  fi
fi
if [ "$verified" != true ]; then log_event false false "$t0" "netem_not_confirmed"; exit 1; fi
log_event true true "$t0" ""
echo "[$t0] fired delay ${DELAY_MS}ms+-${DELAY_JITTER_MS}ms on $NAMESPACE/$SVC for ${DURATION}s (verified)"
