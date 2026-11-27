# fault_lib.sh: shared fault delivery, sourced by the fault scripts in this folder.
#
# Fault types: cpu, mem (relative to the container's own limits), delay, loss (tc netem in the
# pod sandbox's network namespace, driven from a per-node debug pod), podkill and diskio.
# Every fault is self-limiting: it stops at its own deadline even if the kubectl session that
# started it dies, so an interrupted run cannot leave a fault behind.
#
# Required: kubectl pointing at the cluster (KUBE_CONTEXT selects a context), NAMESPACE set by
# the caller. Network faults also need the per-node debug pods of setup_debug_pods.sh.
#
# env: DURATION (300) MEM_FRAC (0.40) DELAY_MS (200) DELAY_JITTER_MS (50) LOSS_PCT (30)
#      PODKILL_INTERVAL_S (30) DISKIO_BS (1M) DISKIO_COUNT (64)
#      DEBUG_PODS_FILE (./debug_pods.txt: lines "<node>:<debug-pod>")
#      BUSYBOX_URL (static busybox used inside distroless containers)
#      FAULT_DEBUG (set to keep the delivery output in ./fault_<case>_<svc>.log)
set -u

DURATION=${DURATION:-300}
MEM_FRAC=${MEM_FRAC:-0.40}
DELAY_MS=${DELAY_MS:-200}
DELAY_JITTER_MS=${DELAY_JITTER_MS:-50}
LOSS_PCT=${LOSS_PCT:-30}
PODKILL_INTERVAL_S=${PODKILL_INTERVAL_S:-30}
DISKIO_BS=${DISKIO_BS:-1M}
DISKIO_COUNT=${DISKIO_COUNT:-64}
DEBUG_PODS_FILE=${DEBUG_PODS_FILE:-./debug_pods.txt}
BUSYBOX_URL=${BUSYBOX_URL:-https://busybox.net/downloads/binaries/1.35.0-x86_64-linux-musl/busybox}
CASE_ID=${CASE_ID:-case}

kc() { if [ -n "${KUBE_CONTEXT:-}" ]; then kubectl --context "$KUBE_CONTEXT" "$@"; else kubectl "$@"; fi; }

# --- resolution: try every common label scheme --------------------------------------------------
LABEL_KEYS="app name app.kubernetes.io/component io.kompose.service app.kubernetes.io/name"

resolve_pod() {
  local svc=$1 pod key
  for key in $LABEL_KEYS; do
    pod=$(kc get pod -n "$NAMESPACE" -l "$key=$svc" \
          -o jsonpath='{.items[?(@.status.phase=="Running")].metadata.name}' 2>/dev/null | awk '{print $1}')
    [ -n "$pod" ] && { echo "$pod"; return 0; }
  done
  return 1
}

# The application container is the one not injected by the mesh.
detect_container() {
  local pod=$1
  kc get pod -n "$NAMESPACE" "$pod" -o jsonpath='{.spec.containers[*].name}' 2>/dev/null \
    | tr ' ' '\n' | grep -vE '^(istio-proxy|istio-init|linkerd-proxy)$' | head -1
}

has_shell() {
  local pod=$1 c=$2
  kc exec -n "$NAMESPACE" "$pod" -c "$c" -- sh -c 'exit 0' >/dev/null 2>&1
}

# --- limits: cpu and mem faults are defined relative to them --------------------------------------
mem_limit_mb() {
  local pod=$1 c=$2 v
  v=$(kc get pod -n "$NAMESPACE" "$pod" -o jsonpath="{.spec.containers[?(@.name=='$c')].resources.limits.memory}" 2>/dev/null)
  [ -z "$v" ] && { echo 0; return; }
  case "$v" in
    *Gi) echo $(( ${v%Gi} * 1024 )) ;;
    *Mi) echo "${v%Mi}" ;;
    *G)  echo $(( ${v%G} * 1000 )) ;;
    *M)  echo "${v%M}" ;;
    *)   echo $(( v / 1048576 )) ;;
  esac
}

cpu_limit_milli() {
  local pod=$1 c=$2 v
  v=$(kc get pod -n "$NAMESPACE" "$pod" -o jsonpath="{.spec.containers[?(@.name=='$c')].resources.limits.cpu}" 2>/dev/null)
  [ -z "$v" ] && { echo 0; return; }
  case "$v" in
    *m) echo "${v%m}" ;;
    *)  echo $(( v * 1000 )) ;;
  esac
}

get_container_id() {
  kc get pod -n "$NAMESPACE" "$1" \
    -o jsonpath="{.status.containerStatuses[?(@.name=='$2')].containerID}" | sed 's|containerd://||'
}

# (debug-pod, container-id, host-pid) route to reach a container from outside it.
resolve_debug_route() {
  local pod=$1 container=$2 node dbg cid cpid
  node=$(kc get pod -n "$NAMESPACE" "$pod" -o jsonpath='{.spec.nodeName}')
  dbg=$(grep "^${node}:" "$DEBUG_PODS_FILE" 2>/dev/null | tail -1 | cut -d: -f2)
  [ -z "$dbg" ] && return 1
  cid=$(get_container_id "$pod" "$container")
  cpid=$(kc exec "$dbg" -- chroot /host crictl inspect --output go-template --template '{{.info.pid}}' "$cid" 2>/dev/null | tr -d '\r')
  [ -z "$cpid" ] && return 1
  echo "${dbg}|${cid}|${cpid}"
}

# The pod sandbox owns the network namespace and outlives application-container restarts, so it is
# the handle for network faults (a rule addressed through a restarted container's pid would never
# be removed). Echoes "dbg|sandbox-id|sandbox-pid".
resolve_netns_route() {
  local pod=$1 node dbg ids sid spid count
  node=$(kc get pod -n "$NAMESPACE" "$pod" -o jsonpath='{.spec.nodeName}')
  dbg=$(grep "^${node}:" "$DEBUG_PODS_FILE" 2>/dev/null | tail -1 | cut -d: -f2)
  [ -z "$dbg" ] && return 1
  ids=$(kc exec "$dbg" -- chroot /host crictl pods --namespace "$NAMESPACE" \
        --name "$pod" --state Ready -q 2>/dev/null | tr -d '\r' | sed '/^$/d')
  count=$(printf '%s' "$ids" | grep -c . || true)
  [ "$count" -ne 1 ] && { echo "ERROR: expected 1 ready sandbox for $pod, found $count" >&2; return 1; }
  sid=$(printf '%s' "$ids" | head -1)
  spid=$(kc exec "$dbg" -- chroot /host crictl inspectp --output go-template \
         --template '{{.info.pid}}' "$sid" 2>/dev/null | tr -d '\r')
  case "$spid" in ''|*[!0-9]*) return 1 ;; esac
  [ "$spid" -le 1 ] && return 1
  echo "${dbg}|${sid}|${spid}"
}

# Network faults: netem on a prio band of the pod's eth0, entered from the debug pod with nsenter
# (no shell or capability needed in the target). Kubelet-probe and Envoy metrics ports (15020,
# 15021, 15090) bypass netem so the fault neither restarts the pod nor drops its own metrics.
# Self-limiting: add, sleep DURATION, delete, all in one backgrounded exec.
fire_network_fault() {
  local svc=$1 fault=$2 container=$3
  local pod; pod=$(resolve_pod "$svc") || { echo "ERROR: no Running pod for '$svc' in $NAMESPACE"; return 1; }
  [ -z "$container" ] && container=$(detect_container "$pod")
  [ -z "$container" ] && { echo "ERROR: could not detect app container in $pod"; return 1; }
  local route dbg cid cpid
  route=$(resolve_netns_route "$pod") || { echo "ERROR: no sandbox netns route for $svc (run setup_debug_pods.sh)"; return 1; }
  IFS='|' read -r dbg cid cpid <<< "$route"
  local netem_args
  if [ "$fault" = "delay" ]; then
    netem_args="delay ${DELAY_MS}ms ${DELAY_JITTER_MS}ms distribution normal"
  else
    netem_args="loss ${LOSS_PCT}%"
  fi
  echo "  [$svc/$container] network fault: ${fault} (${netem_args}) via debug pod, pid=${cpid}"
  local ns_cmd="nsenter --net=/proc/${cpid}/ns/net --"
  local setup="${ns_cmd} tc qdisc replace dev eth0 root handle 1: prio bands 3 priomap 2 2 2 2 2 2 2 2 2 2 2 2 2 2 2 2"
  setup="${setup}; ${ns_cmd} tc qdisc replace dev eth0 parent 1:3 handle 30: netem ${netem_args}"
  local port
  for port in 15020 15021 15090; do
    setup="${setup}; ${ns_cmd} tc filter add dev eth0 protocol ip parent 1: prio 1 u32 match ip protocol 6 0xff match ip sport ${port} 0xffff flowid 1:1"
  done
  kc exec "$dbg" -- chroot /host sh -c \
    "${setup}; sleep ${DURATION}; ${ns_cmd} tc qdisc del dev eth0 root" >/dev/null 2>&1 &
}

# Pod kill: force-delete the pod every PODKILL_INTERVAL_S for DURATION (Kubernetes API only).
fire_podkill_fault() {
  local svc=$1
  local pod; pod=$(resolve_pod "$svc") || { echo "ERROR: no Running pod for '$svc' in $NAMESPACE"; return 1; }
  echo "  [$svc] pod kill every ${PODKILL_INTERVAL_S}s for ${DURATION}s (starting $pod)"
  (
    end=$(( $(date +%s) + DURATION ))
    while [ "$(date +%s)" -lt "$end" ]; do
      p=$(resolve_pod "$svc")
      [ -n "$p" ] && kc delete pod -n "$NAMESPACE" "$p" --grace-period=0 --force >/dev/null 2>&1
      sleep "$PODKILL_INTERVAL_S"
    done
  ) &
}

# Install a static busybox into the writable /faultmem volume of a distroless container.
install_busybox() {
  local dbg=$1 cpid=$2
  kc exec "$dbg" -- chroot /host sh -c \
    "[ -x /proc/${cpid}/root/faultmem/busybox ] || (curl -sL ${BUSYBOX_URL} -o /proc/${cpid}/root/faultmem/busybox && chmod +x /proc/${cpid}/root/faultmem/busybox)" >/dev/null 2>&1
}

# Disk I/O: repeated dd with fdatasync to a disk-backed /faultdisk volume (add_fault_volume.sh).
fire_diskio_fault() {
  local svc=$1 container=${2:-}
  local pod; pod=$(resolve_pod "$svc") || { echo "ERROR: no Running pod for '$svc' in $NAMESPACE"; return 1; }
  [ -z "$container" ] && container=$(detect_container "$pod")
  [ -z "$container" ] && { echo "ERROR: could not detect app container in $pod"; return 1; }
  local distro=0 BB="" dbg cid
  has_shell "$pod" "$container" || distro=1
  local dir=/faultdisk mounted
  mounted=$(kc get pod -n "$NAMESPACE" "$pod" \
    -o jsonpath="{.spec.containers[?(@.name=='$container')].volumeMounts[?(@.name=='faultdisk')].mountPath}" 2>/dev/null)
  if [ -z "$mounted" ]; then
    dir=/tmp
    echo "  WARN: /faultdisk not mounted on $svc -> /tmp, disk fault magnitude uncontrolled"
  fi
  if [ "$distro" -eq 1 ]; then
    local route cpid
    route=$(resolve_debug_route "$pod" "$container") || { echo "ERROR: $svc is distroless and has no debug-pod route"; return 1; }
    IFS='|' read -r dbg cid cpid <<< "$route"
    install_busybox "$dbg" "$cpid"
    BB="/faultmem/busybox "
  fi
  local sh_cmd="end=\$(( \$(${BB}date +%s) + ${DURATION} )); while [ \$(${BB}date +%s) -lt \$end ]; do ${BB}dd if=/dev/zero of=${dir}/diskfill_${CASE_ID} bs=${DISKIO_BS} count=${DISKIO_COUNT} conv=fdatasync 2>/dev/null; done; ${BB}rm -f ${dir}/diskfill_${CASE_ID}"
  echo "  [$svc/$container] disk I/O fault to ${dir} for ${DURATION}s"
  if [ "$distro" -eq 0 ]; then
    kc exec -n "$NAMESPACE" "$pod" -c "$container" -- sh -c "$sh_cmd" >/dev/null 2>&1 &
  else
    kc exec "$dbg" -- chroot /host crictl exec "$cid" /faultmem/busybox sh -c "$sh_cmd" >/dev/null 2>&1 &
  fi
}

# cpu: ceil(limit / 1000) self-limiting busy loops (cpu_limit_milli may be overridden by the
#      caller, e.g. cpu_hog.sh, to set the number of loops directly);
# mem: MEM_FRAC of the memory limit written to the memory-backed /faultmem volume.
fire_fault() {
  local svc=$1 fault=$2 container=$3
  case "$fault" in
    delay|loss) fire_network_fault "$svc" "$fault" "$container"; return $? ;;
    podkill|crash) fire_podkill_fault "$svc"; return $? ;;
    diskio|disk) fire_diskio_fault "$svc" "$container"; return $? ;;
  esac
  local pod; pod=$(resolve_pod "$svc") || { echo "ERROR: no Running pod for '$svc' in $NAMESPACE"; return 1; }
  [ -z "$container" ] && container=$(detect_container "$pod")
  [ -z "$container" ] && { echo "ERROR: could not detect app container in $pod"; return 1; }
  local mlim clim loops fill
  mlim=$(mem_limit_mb "$pod" "$container")
  clim=$(cpu_limit_milli "$pod" "$container")
  if [ "$mlim" -eq 0 ] || [ "$clim" -eq 0 ]; then
    echo "WARN: $svc/$container has no cpu and/or memory limit; the fault is not relative to capacity (see apply_limits.sh)"
  fi
  [ "$mlim" -eq 0 ] && mlim=512
  [ "$clim" -eq 0 ] && clim=1000
  fill=$(awk -v m="$mlim" -v f="$MEM_FRAC" 'BEGIN{printf "%d", m*f}')
  loops=$(awk -v c="$clim" 'BEGIN{n=int((c+999)/1000); print (n<1)?1:n}')
  echo "  [$svc/$container] limits: cpu=${clim}m mem=${mlim}Mi -> fault: ${fault} (fill=${fill}MB, loops=${loops})"
  local distro=0 BB="" dbg cid
  has_shell "$pod" "$container" || distro=1
  if [ "$distro" -eq 1 ]; then
    local route cpid
    route=$(resolve_debug_route "$pod" "$container") || { echo "ERROR: $svc is distroless and has no debug-pod route"; return 1; }
    IFS='|' read -r dbg cid cpid <<< "$route"
    install_busybox "$dbg" "$cpid"
    BB="/faultmem/busybox "
  fi
  # remove leftover fill files of an earlier case (files only; never kill processes by pattern)
  local reap="${BB}rm -f /faultmem/fill_* /dev/shm/fill_* 2>/dev/null; true"
  local sh_cmd
  if [ "$fault" = "cpu" ]; then
    sh_cmd="${reap}; end=\$(( \$(${BB}date +%s) + ${DURATION} )); for i in \$(${BB}seq 1 ${loops}); do ( while [ \$(${BB}date +%s) -lt \$end ]; do n=0; while [ \$n -lt 200000 ]; do n=\$((n+1)); done; done ) & done; wait"
  else
    # /dev/shm is capped at 64 MiB by the runtime; /faultmem is a memory-backed emptyDir charged
    # to the container's memory cgroup (add_fault_volume.sh)
    local dir=/faultmem mounted
    mounted=$(kc get pod -n "$NAMESPACE" "$pod" \
      -o jsonpath="{.spec.containers[?(@.name=='$container')].volumeMounts[?(@.name=='faultmem')].mountPath}" 2>/dev/null)
    if [ -z "$mounted" ]; then
      dir=/dev/shm
      echo "  WARN: /faultmem not mounted on $svc -> /dev/shm, fill capped at 60MB"
      fill=$(( fill > 60 ? 60 : fill ))
    fi
    sh_cmd="${reap}; ${BB}dd if=/dev/zero of=${dir}/fill_${CASE_ID} bs=1M count=${fill} 2>/dev/null; ${BB}sleep ${DURATION}; ${BB}rm -f ${dir}/fill_${CASE_ID}"
  fi
  local out=/dev/null
  [ -n "${FAULT_DEBUG:-}" ] && out="./fault_${CASE_ID}_${svc}.log"
  if [ "$distro" -eq 0 ]; then
    kc exec -n "$NAMESPACE" "$pod" -c "$container" -- sh -c "$sh_cmd" >"$out" 2>&1 &
  else
    kc exec "$dbg" -- chroot /host crictl exec "$cid" /faultmem/busybox sh -c "$sh_cmd" >/dev/null 2>&1 &
  fi
}
