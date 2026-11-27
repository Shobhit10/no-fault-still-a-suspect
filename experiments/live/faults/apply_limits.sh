#!/bin/bash
# apply_limits.sh: give every fault-targetable deployment of a namespace the same CPU and memory
# limits, so that a fault defined relative to the limits (concurrent_faults.sh) is the same share
# of capacity on every application.
#
# The defaults (1000m CPU, 1536Mi memory; requests 100m / 512Mi) were derived for the studied
# applications from measured peak usage: the memory limit L must clear peak working set plus the
# fault fill (MEM_FRAC = 0.40 of L), and 1 core lets the CPU fault saturate exactly one limit.
# Re-derive them for other applications. Backends and infrastructure are skipped.
#
# usage: apply_limits.sh <namespace> [cpu_limit] [mem_limit] [--dry-run]
# env:   SKIP_RE (regex of deployments to skip)  KUBE_CONTEXT
set -u
NS=${1:?namespace}
CPU=${2:-1000m}
MEM=${3:-1536Mi}
DRY=${4:-}
SKIP_RE=${SKIP_RE:-'mongodb|memcached|consul|jaeger|mysql|nacos|rabbitmq|-db$|db-|loadgen|redis|zookeeper|kafka|prometheus|grafana|opensearch|valkey'}
kc() { if [ -n "${KUBE_CONTEXT:-}" ]; then kubectl --context "$KUBE_CONTEXT" "$@"; else kubectl "$@"; fi; }

echo "=== $NS: uniform limits cpu=$CPU mem=$MEM ${DRY} ==="
changed=0; skipped=0
for d in $(kc get deploy -n "$NS" -o jsonpath='{.items[*].metadata.name}' 2>/dev/null); do
  if echo "$d" | grep -qE "$SKIP_RE"; then skipped=$((skipped+1)); continue; fi
  if [ "$DRY" = "--dry-run" ]; then echo "  would set $d"; continue; fi
  kc patch deploy "$d" -n "$NS" --type=json -p "[
    {\"op\":\"add\",\"path\":\"/spec/template/spec/containers/0/resources\",\"value\":{
       \"limits\":{\"cpu\":\"$CPU\",\"memory\":\"$MEM\"},
       \"requests\":{\"cpu\":\"100m\",\"memory\":\"512Mi\"}}}]" >/dev/null 2>&1 \
    && { echo "  $d -> $CPU/$MEM"; changed=$((changed+1)); } || echo "  $d PATCH FAILED"
done
echo "changed=$changed skipped=$skipped"
