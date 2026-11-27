#!/bin/bash
# setup_debug_pods.sh: one privileged node-debug pod per node that hosts pods of NAMESPACE.
#
# Network faults (net_delay.sh) and faults on distroless containers enter the target's network
# namespace or filesystem from such a pod. The registry DEBUG_PODS_FILE (lines "<node>:<pod>") is
# rebuilt on every run, so a stale entry never points at a removed pod.
#
# usage: setup_debug_pods.sh <namespace>
# env:   DEBUG_PODS_FILE (./debug_pods.txt)  DEBUG_IMAGE (nicolaka/netshoot)  KUBE_CONTEXT
set -u
NS=${1:?namespace}
REG=${DEBUG_PODS_FILE:-./debug_pods.txt}
IMAGE=${DEBUG_IMAGE:-nicolaka/netshoot}
kc() { if [ -n "${KUBE_CONTEXT:-}" ]; then kubectl --context "$KUBE_CONTEXT" "$@"; else kubectl "$@"; fi; }

NODES=$(kc get pods -n "$NS" -o jsonpath='{.items[*].spec.nodeName}' | tr ' ' '\n' | sort -u | grep -v '^$')
echo "nodes hosting $NS pods:"; echo "$NODES" | sed 's/^/  /'
[ -f "$REG" ] && cp -a "$REG" "$REG.previous"
: > "$REG"
for NODE in $NODES; do
  existing=$(kc get pods -o wide --no-headers 2>/dev/null \
    | grep node-debugger | grep " $NODE " | grep Running | awk '{print $1}' | tail -1)
  if [ -n "$existing" ]; then
    echo "$NODE: reusing $existing"; echo "$NODE:$existing" >> "$REG"; continue
  fi
  kc debug "node/$NODE" --image="$IMAGE" --profile=sysadmin -- sleep 999999 >/dev/null 2>&1 &
  pod=""
  for _ in $(seq 1 30); do
    sleep 3
    pod=$(kc get pods --sort-by=.metadata.creationTimestamp -o wide --no-headers 2>/dev/null \
      | grep node-debugger | grep " $NODE " | grep Running | awk '{print $1}' | tail -1)
    [ -n "$pod" ] && break
  done
  if [ -z "$pod" ]; then echo "$NODE: ERROR debug pod did not reach Running"; continue; fi
  echo "$NODE: created $pod"; echo "$NODE:$pod" >> "$REG"
done
echo "registry $REG:"; cat "$REG"
