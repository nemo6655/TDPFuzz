#!/bin/bash
# Monitor merge coverage containers and integrate final results.
# Targets: nsfuzz_merge (6 targets), chatafl_merge (6 targets), aflnet_parallel (6 targets)

set -euo pipefail

EVAL_DIR="/home/pzst/LLM-PROTOCOL-FUZZ/TDPFuzz/evaluation"
OUTPUT_CSV="${EVAL_DIR}/merge_coverage_summary.csv"
CONTAINER_PREFIX="merge_cov_"

echo "============================================"
echo "Monitoring merge coverage containers..."
echo "Started at $(date '+%Y-%m-%d %H:%M:%S')"
echo "============================================"

# Phase 1: Wait for all merge containers to exit (nsfuzz + chatafl + aflnet)
while true; do
    running=$(docker ps --filter "name=${CONTAINER_PREFIX}" --format '{{.Names}}' 2>/dev/null | wc -l)
    if [ "$running" -eq 0 ]; then
        echo ""
        echo "All containers finished at $(date '+%Y-%m-%d %H:%M:%S')"
        break
    fi
    echo "$(date '+%H:%M:%S') Still $running container(s) running..."
    sleep 30
done

echo ""
echo "============================================"
echo "Phase 2: Collecting final coverage values"
echo "============================================"

# Helper: extract final line coverage values from a CSV file
# Outputs: "l_per,l_abs,b_per,b_abs"
get_final_cov() {
    local csv="$1"
    if [ -f "$csv" ] && [ -s "$csv" ]; then
        tail -1 "$csv" | cut -d',' -f2-5
    else
        echo "N/A,N/A,N/A,N/A"
    fi
}

# Helper: get the best coverage file for aflnet_parallel
# Priority: new cov_merge.csv > root cov_over_time.csv > merged-cov/ > merged-cov2/
get_aflnet_cov_file() {
    local target="$1"
    local base="${EVAL_DIR}/aflnet_parallel/${target}"

    # 1) Newly generated cov_merge.csv (from merge_cov_aflnet_* containers)
    if [ -f "${base}/merged-cov/cov_merge.csv" ]; then
        echo "${base}/merged-cov/cov_merge.csv"
    elif [ -f "${base}/out-${target}-para/merged-cov/cov_merge.csv" ]; then
        echo "${base}/out-${target}-para/merged-cov/cov_merge.csv"
    # 2) Fall back to existing cov_over_time.csv
    elif [ -f "${base}/cov_over_time.csv" ]; then
        echo "${base}/cov_over_time.csv"
    elif [ -f "${base}/merged-cov/cov_over_time.csv" ]; then
        echo "${base}/merged-cov/cov_over_time.csv"
    elif [ -f "${base}/merged-cov2/cov_over_time.csv" ]; then
        echo "${base}/merged-cov2/cov_over_time.csv"
    elif [ -f "${base}/out-${target}-para/cov_over_time.csv" ]; then
        echo "${base}/out-${target}-para/cov_over_time.csv"
    else
        find "$base" -name "cov_*.csv" -type f 2>/dev/null | head -1
    fi
}

# Write summary header
echo "target,nsfuzz_l_per,nsfuzz_l_abs,nsfuzz_b_per,nsfuzz_b_abs,chatafl_l_per,chatafl_l_abs,chatafl_b_per,chatafl_b_abs,aflnet_l_per,aflnet_l_abs,aflnet_b_per,aflnet_b_abs" > "$OUTPUT_CSV"

TARGETS=(exim forkeddaapd kamailio live555 proftpd pureftpd)

for TARGET in "${TARGETS[@]}"; do
    echo ""
    echo "--- $TARGET ---"

    # NSFuzz merge
    NSFUZZ_CSV="${EVAL_DIR}/nsfuzz_merge/${TARGET}/cov_merge.csv"
    if [ -f "$NSFUZZ_CSV" ]; then
        NSFUZZ_COV=$(get_final_cov "$NSFUZZ_CSV")
        echo "  nsfuzz:   $NSFUZZ_COV"
    else
        NSFUZZ_COV="MISSING,MISSING,MISSING,MISSING"
        echo "  nsfuzz:   MISSING"
    fi

    # ChatAFL merge
    CHATAFL_CSV="${EVAL_DIR}/chatafl_merge/${TARGET}/cov_merge.csv"
    if [ -f "$CHATAFL_CSV" ]; then
        CHATAFL_COV=$(get_final_cov "$CHATAFL_CSV")
        echo "  chatafl:  $CHATAFL_COV"
    else
        CHATAFL_COV="MISSING,MISSING,MISSING,MISSING"
        echo "  chatafl:  MISSING"
    fi

    # AFLNet parallel
    AFLNET_CSV=$(get_aflnet_cov_file "$TARGET")
    if [ -n "$AFLNET_CSV" ] && [ -f "$AFLNET_CSV" ]; then
        AFLNET_COV=$(get_final_cov "$AFLNET_CSV")
        echo "  aflnet:   $AFLNET_COV  ($(basename $(dirname "$AFLNET_CSV")))"
    else
        AFLNET_COV="MISSING,MISSING,MISSING,MISSING"
        echo "  aflnet:   MISSING"
    fi

    echo "${TARGET},${NSFUZZ_COV},${CHATAFL_COV},${AFLNET_COV}" >> "$OUTPUT_CSV"
done

echo ""
echo "============================================"
echo "Summary written to: $OUTPUT_CSV"
echo "============================================"

# Print final summary table
echo ""
echo "=== FINAL COVERAGE SUMMARY (absolute edges) ==="
printf "%-15s %-18s %-18s %-18s\n" "Target" "NSFuzz(line/br)" "ChatAFL(line/br)" "AFLNet(line/br)"
printf "%-15s %-18s %-18s %-18s\n" "------" "----------------" "----------------" "----------------"

tail -n +2 "$OUTPUT_CSV" | while IFS=',' read -r target n_l_per n_l_abs n_b_per n_b_abs c_l_per c_l_abs c_b_per c_b_abs a_l_per a_l_abs a_b_per a_b_abs; do
    printf "%-15s %-18s %-18s %-18s\n" "$target" "$n_l_abs / $n_b_abs" "$c_l_abs / $c_b_abs" "$a_l_abs / $a_b_abs"
done

echo ""
echo "Done at $(date '+%Y-%m-%d %H:%M:%S')"
