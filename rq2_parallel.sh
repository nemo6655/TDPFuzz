#!/bin/bash
# RQ2 Experiment Runner with concurrency control
# No LLM mutation — TGI not needed, but each target uses up to 8 CPUs (gen2).
#
# Usage: ./rq2_parallel.sh [-j N] [target1 target2 ...]
#   -j N    Max concurrent targets (default: 2)
#   Default targets: exim forkeddaapd kamailio proftpd pureftpd

set -euo pipefail

MAX_JOBS=2
TARGETS=()

while [[ $# -gt 0 ]]; do
    case "$1" in
        -j) MAX_JOBS="$2"; shift 2 ;;
        *) TARGETS+=("$1"); shift ;;
    esac
done

if [ ${#TARGETS[@]} -eq 0 ]; then
    TARGETS=(exim forkeddaapd kamailio proftpd pureftpd)
fi

TIMESTAMP=$(date +%Y%m%d_%H%M%S)
RESULTS_DIR="/home/pzst/LLM-PROTOCOL-FUZZ/TDPFuzz/evaluation/rq2"

echo "============================================"
echo "RQ2 Experiment Runner"
echo "============================================"
echo "Targets:    ${TARGETS[*]}"
echo "Max jobs:   $MAX_JOBS"
echo "Started at: $TIMESTAMP"
echo "Results:    $RESULTS_DIR"
echo ""

declare -A LOGS
FAILED=()
RUNNING=0

for target in "${TARGETS[@]}"; do
    case $target in
        live555|exim|forkeddaapd|kamailio|proftpd|pureftpd) ;;
        *) echo "WARN: Skipping invalid target: $target"; continue ;;
    esac

    # Wait if we've reached max concurrent jobs
    while [ $RUNNING -ge $MAX_JOBS ]; do
        if wait -n 2>/dev/null; then
            RUNNING=$((RUNNING - 1))
        else
            RUNNING=$((RUNNING - 1))
            # capture which one failed — we'll report at the end
        fi
    done

    LOGFILE="${RESULTS_DIR}/${target}/rq2_${target}_${TIMESTAMP}.log"
    mkdir -p "${RESULTS_DIR}/${target}"

    echo "[$(date '+%H:%M:%S')] Starting $target (log: $LOGFILE)..."
    ./rq2_experiment.sh "$target" > "$LOGFILE" 2>&1 &
    LOGS[$target]="$LOGFILE"
    RUNNING=$((RUNNING + 1))
done

echo ""
echo "All jobs launched. Waiting for remaining to complete..."
echo ""

# Wait for remaining jobs
while [ $RUNNING -gt 0 ]; do
    if wait -n 2>/dev/null; then
        RUNNING=$((RUNNING - 1))
    else
        RUNNING=$((RUNNING - 1))
    fi
done

# Collect results
for target in "${TARGETS[@]}"; do
    logfile="${LOGS[$target]:-}"
    if [ -f "$logfile" ] && grep -q "RQ2 Experiment Complete" "$logfile" 2>/dev/null; then
        echo "[$(date '+%H:%M:%S')] $target: OK"
    else
        echo "[$(date '+%H:%M:%S')] $target: FAILED"
        FAILED+=("$target")
    fi
done

echo ""
echo "============================================"
echo "Coverage Summary"
echo "============================================"

for target in "${TARGETS[@]}"; do
    logfile="${LOGS[$target]:-}"
    echo ""
    echo "--- $target ---"
    if [ -f "$logfile" ]; then
        grep -A 10 "Phase 6: Coverage Comparison" "$logfile" 2>/dev/null || echo "  (not found)"
    else
        echo "  (log missing)"
    fi
done

if [ ${#FAILED[@]} -gt 0 ]; then
    echo ""
    echo "FAILED: ${FAILED[*]}"
    exit 1
fi

echo ""
echo "All targets completed."
