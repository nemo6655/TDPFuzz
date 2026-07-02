#!/bin/bash
# RQ2 Continuation Experiment
# Validate fuzzing-strength preservation of seed selection.
# From gen1 checkpoint, run gen2 with 8 pools:
#   pools 0000-0003: elite seeds  (selected)
#   pools 0004-0007: all seeds    (full queue)
# No LLM mutation, 6h AFL.
# Then compare gcov coverage: gen1 baseline vs gen2 elite vs full.
#
# Usage: ./rq2_experiment.sh <target>
#   where <target> is one of: live555 exim forkeddaapd kamailio proftpd pureftpd

set -euo pipefail

TARGET="${1:?Usage: $0 <target>}"
case $TARGET in
    live555|exim|forkeddaapd|kamailio|proftpd|pureftpd) ;;
    *) echo "Invalid target: $TARGET"; exit 1 ;;
esac

IMAGE_NAME="tdpfuzz:rq2-experiment"
CONTAINER_NAME="tdpfuzz_rq2_${TARGET}_1"
EVAL_DIR="/home/pzst/LLM-PROTOCOL-FUZZ/TDPFuzz/evaluation/rq2/${TARGET}"
TIMESTAMP=$(date +%Y%m%d_%H%M%S)

echo "============================================"
echo "RQ2 Continuation Experiment"
echo "============================================"
echo "Target:     $TARGET"
echo "Image:      $IMAGE_NAME"
echo "Container:  $CONTAINER_NAME"
echo "Eval dir:   $EVAL_DIR"
echo "Started at: $TIMESTAMP"
echo ""

mkdir -p "$EVAL_DIR"

# ============================================================
# Phase 1: Run gen0-gen3 experiment inside container
# ============================================================
echo "[$(date '+%H:%M:%S')] Phase 1: Starting experiment container..."
echo "  EXPERIMENT_GEN=gen2, NUM_GENERATIONS=2"

docker run -d \
    --add-host=host.docker.internal:host-gateway \
    -v /tmp/host:/tmp/host \
    -v /var/run/docker.sock:/var/run/docker.sock \
    --name "$CONTAINER_NAME" \
    --entrypoint /bin/bash \
    "$IMAGE_NAME" \
    -c "cd /home/appuser/elmfuzz && TDPFUZZ_FORBIDDEN=NOSM EXPERIMENT_GEN=gen2 SELECTION_STRATEGY=lattice REPROUDCE_MODE=true NUM_GENERATIONS=2 ELMFUZZ_RUNDIR=preset/${TARGET} /home/appuser/elmfuzz/all_gen_net.sh preset/${TARGET}"

echo "  Container ID: $(docker ps -qf name=${CONTAINER_NAME})"
echo ""

# ============================================================
# Phase 2: Wait for container to finish
# ============================================================
echo "[$(date '+%H:%M:%S')] Phase 2: Waiting for experiment to complete..."
docker wait "$CONTAINER_NAME"
EXIT_CODE=$?

# Save docker logs
docker logs "$CONTAINER_NAME" > "$EVAL_DIR/experiment_${TIMESTAMP}.log" 2>&1
echo "  Exit code: $EXIT_CODE"
echo "  Logs saved to: $EVAL_DIR/experiment_${TIMESTAMP}.log"

if [ "$EXIT_CODE" -ne 0 ]; then
    echo "ERROR: Container exited with non-zero code. Check logs."
    docker rm "$CONTAINER_NAME" > /dev/null 2>&1
    exit 1
fi
echo ""

# ============================================================
# Phase 3: Archive results from evaluation directory
# ============================================================
echo "[$(date '+%H:%M:%S')] Phase 3: Archiving results..."
docker cp "$CONTAINER_NAME":/home/appuser/elmfuzz/evaluation "$EVAL_DIR"/ 2>/dev/null || true
TAR_FILE=$(find "$EVAL_DIR/evaluation" -name "*.tar.xz" 2>/dev/null | head -1)

if [ -z "$TAR_FILE" ]; then
    echo "  WARN: No tar.xz found, trying direct copy from preset..."
    # Results might be in the preset directory directly
    docker cp "$CONTAINER_NAME":/home/appuser/elmfuzz/preset/${TARGET} "$EVAL_DIR"/preset_${TARGET} 2>/dev/null || true
fi

if [ -n "$TAR_FILE" ]; then
    cp "$TAR_FILE" "$EVAL_DIR/rq2_${TARGET}.tar.xz"
    echo "  Copied: $EVAL_DIR/rq2_${TARGET}.tar.xz"
    tar -xf "$TAR_FILE" -C "$EVAL_DIR" 2>/dev/null || true
fi

# ============================================================
# Phase 4: Extract replayable-queues for gcov
# ============================================================
echo "[$(date '+%H:%M:%S')] Phase 4: Extracting replayable-queues..."

find_rq_dir() {
    # Find replayable-queue files under a gen/aflnetout path
    local gen="$1"
    local pool="$2"
    find "$EVAL_DIR" -type d -path "*/${gen}/aflnetout" 2>/dev/null | head -1
}

extract_pools() {
    local gen_dir="$1"
    local out_dir="$2"
    shift 2
    local pools=("$@")
    mkdir -p "$out_dir"
    cd "$gen_dir"
    for pool in "${pools[@]}"; do
        local tar_file="aflnetout_${pool}.tar.gz"
        if [ -f "$tar_file" ]; then
            tar -xzf "$tar_file" -C "$out_dir" --strip-components=1 --transform 's/queue/replayable-queue/' --wildcards "*/queue" 2>/dev/null || true
        fi
    done
    cd - > /dev/null
}

# Find gen1 (baseline) and gen2 (experiment) aflnetout directories
GEN1_DIR=$(find "$EVAL_DIR" -type d -path "*/gen1/aflnetout" 2>/dev/null | head -1)
GEN2_DIR=$(find "$EVAL_DIR" -type d -path "*/gen2/aflnetout" 2>/dev/null | head -1)

if [ -z "$GEN1_DIR" ] || [ -z "$GEN2_DIR" ]; then
    echo "ERROR: Could not find gen1 or gen2 aflnetout directory."
    echo "  gen1: ${GEN1_DIR:-NOT FOUND}"
    echo "  gen2: ${GEN2_DIR:-NOT FOUND}"
    docker rm "$CONTAINER_NAME" > /dev/null 2>&1
    exit 1
fi

echo "  gen1 baseline dir: $GEN1_DIR"
echo "  gen2 experiment dir: $GEN2_DIR"

# --- Gen1 baseline: merge pools 0000-0003 ---
GEN1_BASELINE="$EVAL_DIR/rq2_gen1_baseline"
extract_pools "$GEN1_DIR" "$GEN1_BASELINE" "0000" "0001" "0002" "0003"
echo "  Gen1 baseline: $(find "$GEN1_BASELINE" -type f 2>/dev/null | wc -l) seeds"

# --- Gen2 elite: merge pools 0000-0003 ---
GEN2_ELITE="$EVAL_DIR/rq2_gen2_elite"
extract_pools "$GEN2_DIR" "$GEN2_ELITE" "0000" "0001" "0002" "0003"
echo "  Gen2 elite: $(find "$GEN2_ELITE" -type f 2>/dev/null | wc -l) seeds"

# --- Gen2 full: merge pools 0004-0007 ---
GEN2_FULL="$EVAL_DIR/rq2_gen2_full"
extract_pools "$GEN2_DIR" "$GEN2_FULL" "0004" "0005" "0006" "0007"
echo "  Gen2 full: $(find "$GEN2_FULL" -type f 2>/dev/null | wc -l) seeds"

# ============================================================
# Phase 5: Run gcov coverage
# ============================================================
echo "[$(date '+%H:%M:%S')] Phase 5: Running gcov coverage..."

run_gcov() {
    local label="$1"
    local seeds_dir="$2"
    local output="$3"

    if [ ! -d "$seeds_dir" ] || [ -z "$(ls -A "$seeds_dir" 2>/dev/null)" ]; then
        echo "  $label: SKIP (no seeds)"
        return
    fi

    local cov_container="${CONTAINER_NAME}_gcov_${label}"
    local input_dir="$(realpath "$seeds_dir")"
    local output_csv="${input_dir}/cov_over_time_${TARGET}_${label}.csv"

    # Ensure gcov image is tagged (it was built as tdpfuzz/$TARGET by prepare_fuzzbench_net.py)
    docker tag "tdpfuzz/${TARGET}:latest" "live555:profuzzbench" 2>/dev/null || true

    case $TARGET in
        live555)
            docker run -d -it --name "$cov_container" \
                -v "$input_dir":/home/ubuntu/input/ \
                --entrypoint /bin/bash live555:profuzzbench \
                -c "cd /home/ubuntu/experiments/live555-cov/testProgs/ && cov_script /home/ubuntu/input/ 8554 30 /home/ubuntu/input/cov_over_time_${TARGET}_${label}.csv 1" \
                > /dev/null 2>&1
            ;;
        exim)
            docker run -d -it --name "$cov_container" \
                -v "$input_dir":/home/ubuntu/input/ \
                --entrypoint /bin/bash exim:latest \
                -c "cd /home/ubuntu/experiments/exim-gcov && cp ./src/build-Linux-x86_64/exim /usr/exim/bin/exim && cov_script /home/ubuntu/input/ 25 30 /home/ubuntu/input/cov_over_time_${TARGET}_${label}.csv 1" \
                > /dev/null 2>&1
            ;;
        forkeddaapd)
            docker run -d -it --name "$cov_container" \
                -v "$input_dir":/home/ubuntu/input/ \
                --entrypoint /bin/bash forked-daapd:latest \
                -c "sudo /etc/init.d/dbus start && sudo /etc/init.d/avahi-daemon start && sudo /etc/init.d/dbus status && cd /home/ubuntu/experiments/ && cov_script /home/ubuntu/input/ 3689 30 /home/ubuntu/input/cov_over_time_${TARGET}_${label}.csv 1" \
                > /dev/null 2>&1
            ;;
        kamailio)
            docker run -d -it --name "$cov_container" \
                -v "$input_dir":/home/ubuntu/input/ \
                --entrypoint /bin/bash kamailio:latest \
                -c "cd /home/ubuntu/experiments/ && cov_script /home/ubuntu/input/ 5060 30 /home/ubuntu/input/cov_over_time_${TARGET}_${label}.csv 1" \
                > /dev/null 2>&1
            ;;
        proftpd)
            docker run -d -it --name "$cov_container" \
                -v "$input_dir":/home/ubuntu/input/ \
                --entrypoint /bin/bash proftpd:latest \
                -c "cd /home/ubuntu/experiments/proftpd-gcov && cov_script /home/ubuntu/input/ 21 30 /home/ubuntu/input/cov_over_time_${TARGET}_${label}.csv 1" \
                > /dev/null 2>&1
            ;;
        pureftpd)
            docker run -d -it --name "$cov_container" \
                -v "$input_dir":/home/ubuntu/input/ \
                --entrypoint /bin/bash pure-ftpd:latest \
                -c "cd /home/ubuntu/experiments/pure-ftpd-gcov && cov_script /home/ubuntu/input/ 21 30 /home/ubuntu/input/cov_over_time_${TARGET}_${label}.csv 1" \
                > /dev/null 2>&1
            ;;
    esac

    docker wait "$cov_container" > /dev/null 2>&1 || true
    docker rm "$cov_container" > /dev/null 2>&1 || true

    if [ -f "$output_csv" ]; then
        echo "  $label: OK ($(wc -l < "$output_csv") lines)"
    else
        echo "  $label: WARN (csv not found)"
    fi
}

run_gcov "baseline" "$GEN1_BASELINE" ""
run_gcov "elite"   "$GEN2_ELITE"   ""
run_gcov "full"    "$GEN2_FULL"    ""

# ============================================================
# Phase 6: Compare results
# ============================================================
echo ""
echo "============================================"
echo "Phase 6: Coverage Comparison"
echo "============================================"

BASELINE_CSV=$(find "$GEN1_BASELINE" -name "cov_over_time_*.csv" 2>/dev/null | head -1)
ELITE_CSV=$(find "$GEN2_ELITE" -name "cov_over_time_*.csv" 2>/dev/null | head -1)
FULL_CSV=$(find "$GEN2_FULL" -name "cov_over_time_*.csv" 2>/dev/null | head -1)

get_final_cov() {
    local csv="$1"
    if [ -f "$csv" ]; then
        tail -1 "$csv" | cut -d',' -f2
    else
        echo "N/A"
    fi
}

BASELINE_COV=$(get_final_cov "$BASELINE_CSV")
ELITE_COV=$(get_final_cov "$ELITE_CSV")
FULL_COV=$(get_final_cov "$FULL_CSV")

echo "Target:           $TARGET"
echo "Gen1 baseline:    $BASELINE_COV edges  ($(find "$GEN1_BASELINE" -type f | wc -l) seeds)"
echo "Gen2 elite:       $ELITE_COV edges  ($(find "$GEN2_ELITE" -type f | wc -l) seeds)"
echo "Gen2 full:        $FULL_COV edges  ($(find "$GEN2_FULL" -type f | wc -l) seeds)"

if [ "$BASELINE_COV" != "N/A" ] && [ "$ELITE_COV" != "N/A" ] && [ "$FULL_COV" != "N/A" ]; then
    ELITE_GAIN=$(echo "$ELITE_COV - $BASELINE_COV" | bc 2>/dev/null || echo "N/A")
    FULL_GAIN=$(echo "$FULL_COV - $BASELINE_COV" | bc 2>/dev/null || echo "N/A")
    echo ""
    echo "Elite gain:       +$ELITE_GAIN edges"
    echo "Full gain:        +$FULL_GAIN edges"
    if [ "$ELITE_GAIN" != "N/A" ] && [ "$FULL_GAIN" != "N/A" ]; then
        RATIO=$(echo "scale=2; $ELITE_GAIN / $FULL_GAIN * 100" | bc 2>/dev/null || echo "N/A")
        echo "Elite/Full ratio: ${RATIO}%"
    fi
fi

# ============================================================
# Cleanup
# ============================================================
echo ""
echo "[$(date '+%H:%M:%S')] Cleaning up..."
docker rm "$CONTAINER_NAME" > /dev/null 2>&1 || true
echo "Container removed."

echo ""
echo "============================================"
echo "RQ2 Experiment Complete: $TARGET"
echo "Results: $EVAL_DIR"
echo "============================================"
