#!/bin/bash
# concurrent_faults.sh: two concurrent faults with a controlled stagger (E1 faulty windows).
#
# The first service gets FAULT_A, the second FAULT_B STAGGER seconds later. CPU faults saturate the
# container's CPU limit (ceil(limit/1000) busy loops); memory faults fill MEM_FRAC of its memory
# limit, so the perturbation is the same share of capacity on every application (apply_limits.sh
# gives every targetable service the same limits). The paper's E1 windows used CPU exhaustion on one
# service and memory pressure on another, with DURATION=300, a 15-s stagger and 30 cases per
# deployment; rankers get the injection time, 90 s into the exported window.
#
# The case is appended to GT_FILE in the ground-truth layout read by export_window.py:
#   <case_id>,<ns>,<svc_a>,<fault_a>,<svc_b>,<fault_b>,<stagger_s>,<start_epoch>
#   <case_id>,end_time,<end_epoch>
#
# usage: concurrent_faults.sh <ns> <svc_a> <fault_a> <svc_b> <fault_b> <stagger_s> <case_id> [container_a] [container_b]
#   fault: cpu | mem | delay | loss | podkill | diskio
# env:   DURATION (300)  MEM_FRAC (0.40)  GT_FILE (ground_truth_<ns>.csv)  KUBE_CONTEXT
set -u
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
NAMESPACE=$1
SVC_A=$2; FAULT_A=$3
SVC_B=$4; FAULT_B=$5
STAGGER=$6
CASE_ID=$7
CONTAINER_A=${8:-}
CONTAINER_B=${9:-}
source "$HERE/fault_lib.sh"
GT_FILE=${GT_FILE:-./ground_truth_${NAMESPACE}.csv}

echo "=== Case: $CASE_ID  (ns=$NAMESPACE, DURATION=${DURATION}s, MEM_FRAC=${MEM_FRAC}) ==="
echo "$SVC_A ($FAULT_A) -> [${STAGGER}s] -> $SVC_B ($FAULT_B)"
START_TIME=$(date +%s)
echo "$CASE_ID,$NAMESPACE,$SVC_A,$FAULT_A,$SVC_B,$FAULT_B,$STAGGER,$START_TIME" >> "$GT_FILE"
fire_fault "$SVC_A" "$FAULT_A" "$CONTAINER_A" || exit 1
echo "[$(date +%s)] fired $SVC_A ($FAULT_A)"
sleep "$STAGGER"
fire_fault "$SVC_B" "$FAULT_B" "$CONTAINER_B" || exit 1
echo "[$(date +%s)] fired $SVC_B ($FAULT_B)"
END_TIME=$((START_TIME + STAGGER + DURATION))
echo "$CASE_ID,end_time,$END_TIME" >> "$GT_FILE"
echo "=== $CASE_ID done. window ${START_TIME}..${END_TIME} (${DURATION}s faults). ==="
