#!/bin/bash
# Orchestrate continuation experiments with TGI serialization.
# Chain-launch all 6 targets: each starts when the previous enters its last AFL gen.
# Supports resume: skips completed targets, chains from currently running target.
# Usage: ./run_cont_chain.sh

set -euo pipefail

SIGNAL_DIR="/tmp/tdpfuzz_cont_signal"
EVAL_DIR="/home/pzst/LLM-PROTOCOL-FUZZ/TDPFuzz/evaluation/tdpfuzz_cont"
EXEC_SCRIPT="/home/pzst/LLM-PROTOCOL-FUZZ/TDPFuzz/tdpfuzz_exec_cont.sh"

TARGETS=(live555 exim forkeddaapd kamailio proftpd pureftpd)

# ============================================================
# Helpers
# ============================================================
is_completed() {
    local target=$1
    local data_path="${EVAL_DIR}/${target}"
    local tar_file="${data_path}/tdpfuzzer_cont_${target}_1.tar.xz"
    local cov_file
    cov_file=$(find "$data_path" -name "cov_over_time_${target}_1.csv" 2>/dev/null | head -1)
    if [ -f "$tar_file" ] && [ -n "$cov_file" ] && [ -f "$cov_file" ]; then
        return 0
    fi
    return 1
}

is_running() {
    local target=$1
    local container_name="tdpfuzz_cont_${target}_1"
    if docker ps --format '{{.Names}}' 2>/dev/null | grep -q "^${container_name}$"; then
        return 0
    fi
    # Also check if exec script process is still alive
    if pgrep -f "tdpfuzz_exec_cont.sh.*${target}" > /dev/null 2>&1; then
        return 0
    fi
    return 1
}

# ============================================================
# Scan targets: skip completed, detect running
# ============================================================
echo "============================================"
echo "Continuation Experiment Chain"
echo "============================================"
echo ""

# Count running containers to decide whether to clean signal dir
RUNNING_COUNT=$(docker ps --format '{{.Names}}' 2>/dev/null | grep -c 'tdpfuzz_cont_' || true)
if [ "$RUNNING_COUNT" -eq 0 ]; then
    rm -rf "$SIGNAL_DIR"
    mkdir -p "$SIGNAL_DIR"
fi
mkdir -p "$EVAL_DIR"

PREV=""
FOUND_RUNNING=false

echo "Scanning targets..."
echo ""

for target in "${TARGETS[@]}"; do
    if is_completed "$target"; then
        echo "  [SKIP] $target — already completed"
        continue
    fi

    if is_running "$target"; then
        echo "  [LIVE] $target — currently running, chain will resume from here"
        FOUND_RUNNING=true
        PREV="$target"
        continue
    fi

    # Target is neither completed nor running — needs to be launched
    DATA_PATH="${EVAL_DIR}/${target}"
    ARGS=(1 "$DATA_PATH" "$target" --chain "$SIGNAL_DIR")

    if [ -n "$PREV" ]; then
        ARGS+=(--wait "${SIGNAL_DIR}/${PREV}_last_afl.stamp")
        echo "  [QUEUE] $target — waiting for ${PREV}'s last AFL"
    else
        echo "  [START] $target — first in chain, starts immediately"
    fi

    nohup "$EXEC_SCRIPT" "${ARGS[@]}" > "/tmp/tdpfuzz_cont_${target}.log" 2>&1 &
    echo "    PID: $!"

    PREV="$target"
    sleep 2
done

echo ""
if [ -z "$PREV" ]; then
    echo "All targets already completed. Nothing to do."
else
    echo "Monitor:"
    echo "  tail -f /tmp/tdpfuzz_cont_*.log"
    echo "  ls /tmp/tdpfuzz_cont_signal/"
fi
