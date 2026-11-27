#!/bin/bash
# load_surge.sh: a load surge with no faulty component (E3 and E4 "Unresolved" slots).
#
# Scales the application's own load-generator deployment by SURGE_FACTOR for DURATION seconds and
# then restores the recorded replica count (also on exit, so an interrupted surge cannot leave the
# load raised). Nothing else is touched. The paper used factors 8 (Online Boutique, OpenTelemetry
# Demo), 16 (DeathStarBench) and 24 (Sock Shop), chosen by logged pilots.
#
# usage: load_surge.sh <namespace> <loadgen_deployment> <case_id> <events_jsonl>
# env:   DURATION (300)  SURGE_FACTOR (8)  KUBE_CONTEXT (optional)
set -u
NS=$1
DEP=$2
CASE_ID=$3
EVENTS=$4
DURATION=${DURATION:-300}
SURGE_FACTOR=${SURGE_FACTOR:-8}
kc() { if [ -n "${KUBE_CONTEXT:-}" ]; then kubectl --context "$KUBE_CONTEXT" "$@"; else kubectl "$@"; fi; }

base=$(kc get deploy -n "$NS" "$DEP" -o jsonpath='{.spec.replicas}')
target=$(( base * SURGE_FACTOR ))
restore() { kc scale deploy -n "$NS" "$DEP" --replicas="$base" >/dev/null 2>&1; }
trap restore EXIT
t0=$(date +%s)
if ! kc scale deploy -n "$NS" "$DEP" --replicas="$target" >/dev/null; then
  echo "{\"case_id\": \"$CASE_ID\", \"namespace\": \"$NS\", \"kind\": \"load_surge\", \"fired\": false, \"t_fire\": $t0}" >> "$EVENTS"
  exit 1
fi
echo "{\"case_id\": \"$CASE_ID\", \"namespace\": \"$NS\", \"service\": \"\", \"kind\": \"load_surge\", \"loadgen\": \"$DEP\", \"replicas_base\": $base, \"replicas_surge\": $target, \"fired\": true, \"t_fire\": $t0, \"t_end\": $((t0 + DURATION))}" >> "$EVENTS"
echo "[$t0] surge $NS/$DEP $base -> $target for ${DURATION}s"
sleep "$DURATION"
restore
trap - EXIT
echo "[$(date +%s)] restored $NS/$DEP to $base"
