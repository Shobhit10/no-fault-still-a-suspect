#!/bin/bash
# add_fault_volume.sh: mount fault volumes on every fault-targetable deployment of a namespace.
#
#   /faultmem   memory-backed emptyDir, charged to the container's memory cgroup: the memory
#               fault writes here (the runtime's /dev/shm is capped at 64 MiB, which would silently
#               truncate every memory fault); also holds busybox for distroless containers;
#   /faultdisk  disk-backed emptyDir for the disk I/O fault (--disk).
# Backends and infrastructure (databases, caches, brokers, load generators) are skipped.
#
# usage: add_fault_volume.sh <namespace> [size] [--disk] [--dry-run]
# env:   SKIP_RE (regex of deployments to skip)  KUBE_CONTEXT
set -u
NS=${1:?namespace}
SIZE=${2:-1Gi}
shift $(( $# > 1 ? 2 : 1 ))
DISK=0; DRY=0
for a in "$@"; do
  case "$a" in --disk) DISK=1 ;; --dry-run) DRY=1 ;; esac
done
SKIP_RE=${SKIP_RE:-'mongodb|memcached|consul|jaeger|mysql|nacos|rabbitmq|loadgen|redis|zookeeper|kafka|prometheus|grafana|opensearch|valkey|-db-|db-'}
kc() { if [ -n "${KUBE_CONTEXT:-}" ]; then kubectl --context "$KUBE_CONTEXT" "$@"; else kubectl "$@"; fi; }

if [ "$DISK" -eq 1 ]; then VOL=faultdisk; MOUNT=/faultdisk; MEDIUM=""; else VOL=faultmem; MOUNT=/faultmem; MEDIUM='"medium":"Memory",'; fi
echo "=== $NS: mounting $MOUNT ($SIZE) ==="
changed=0
for d in $(kc get deploy -n "$NS" -o jsonpath='{.items[*].metadata.name}' 2>/dev/null); do
  echo "$d" | grep -qE "$SKIP_RE" && continue
  c=$(kc get deploy "$d" -n "$NS" -o jsonpath='{.spec.template.spec.containers[0].name}' 2>/dev/null)
  [ -z "$c" ] && continue
  if [ "$DRY" -eq 1 ]; then echo "  would patch $d (container $c)"; continue; fi
  kc patch deploy "$d" -n "$NS" --type=strategic -p "{
    \"spec\":{\"template\":{\"spec\":{
      \"volumes\":[{\"name\":\"$VOL\",\"emptyDir\":{${MEDIUM}\"sizeLimit\":\"$SIZE\"}}],
      \"containers\":[{\"name\":\"$c\",\"volumeMounts\":[{\"name\":\"$VOL\",\"mountPath\":\"$MOUNT\"}]}]
    }}}}" >/dev/null 2>&1 && changed=$((changed+1)) || echo "  PATCH FAILED: $d"
done
echo "patched=$changed"
