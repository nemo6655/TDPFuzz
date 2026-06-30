#!/bin/bash
# Merge replayable-queue from 4 experiment runs for NSFuzz/ChatAFL and run coverage.
# Usage: ./merge_coverage.sh <nsfuzz|chatafl>

set -euo pipefail

FUZZER="$1"
EVAL_DIR="/home/pzst/LLM-PROTOCOL-FUZZ/TDPFuzz/evaluation"
MERGE_DIR="${EVAL_DIR}/${FUZZER}_merge"

TARGETS=(exim forkeddaapd kamailio live555 proftpd pureftpd)

declare -A NSFUZZ_PREFIX=(
    [exim]="nsfuzz_exim_out"
    [forkeddaapd]="nsfuzz_forkeddaapd_out"
    [kamailio]="nsfuzz_kamailio_out"
    [live555]="nsfuzzout"
    [proftpd]="nsfuzz_proftpd_out"
    [pureftpd]="nsfuzz_pureftpd_out"
)

declare -A CHATAFL_PREFIX=(
    [exim]="out-exim-chatafl_zp"
    [forkeddaapd]="out-forked-daapd-chatafl_zp"
    [kamailio]="out-kamailio-chatafl_zp"
    [live555]="out-live555-chatafl_zp"
    [proftpd]="out-proftpd-chatafl_zp"
    [pureftpd]="out-pure-ftpd-chatafl_zp"
)

# ============================================================
# PHASE 1: Extract replayable-queue from all 4 tar.gz
# ============================================================
echo "=========================================="
echo "PHASE 1: Extracting ${FUZZER} replayable-queue"
echo "=========================================="

for TARGET in "${TARGETS[@]}"; do
    if [ "$FUZZER" = "nsfuzz" ]; then
        PREFIX="${NSFUZZ_PREFIX[$TARGET]}"
    else
        PREFIX="${CHATAFL_PREFIX[$TARGET]}"
    fi

    SRC_DIR="${EVAL_DIR}/${FUZZER}/${TARGET}"
    OUT_DIR="${MERGE_DIR}/${TARGET}"
    mkdir -p "$OUT_DIR"

    echo ""
    echo "--- $TARGET ---"

    # Clear previous extraction
    rm -rf "$OUT_DIR/replayable-queue"

    tar_count=0
    seed_count=0
    for tar_file in "$SRC_DIR"/*.tar.gz; do
        if [ ! -f "$tar_file" ]; then
            continue
        fi
        tar_count=$((tar_count + 1))
        echo "  Extracting $(basename $tar_file)..."

        tar -xzf "$tar_file" -C "$OUT_DIR" \
            --wildcards "*/replayable-queue/*" \
            --strip-components=1 2>/dev/null

        # Count files in replayable-queue after each extraction
        if [ -d "$OUT_DIR/replayable-queue" ]; then
            fcount=$(find "$OUT_DIR/replayable-queue" -maxdepth 1 -type f | wc -l)
            echo "    files so far: $fcount"
        fi
    done

    if [ -d "$OUT_DIR/replayable-queue" ]; then
        total=$(find "$OUT_DIR/replayable-queue" -maxdepth 1 -type f | wc -l)
    else
        total=0
    fi
    echo "  $TARGET: $tar_count archives extracted, $total total seeds"
done

echo ""
echo "=========================================="
echo "PHASE 2: Running Coverage for ${FUZZER}"
echo "=========================================="

# Coverage function
run_coverage() {
    local TARGET_NAME=$1
    local INPUT_DIR=$2

    local IMAGE=""
    local CMD=""

    case $TARGET_NAME in
        exim)
            IMAGE="exim:latest"
            CMD="cd /home/ubuntu/experiments/exim-gcov && cp ./src/build-Linux-x86_64/exim /usr/exim/bin/exim && cov_script /home/ubuntu/input/ 25 30 /home/ubuntu/input/cov_merge.csv 1"
            ;;
        live555)
            IMAGE="live555:profuzzbench"
            CMD="cd /home/ubuntu/experiments/live555-cov/testProgs/ && cov_script /home/ubuntu/input/ 8554 30 /home/ubuntu/input/cov_merge.csv 1"
            ;;
        forkeddaapd)
            IMAGE="forked-daapd:latest"
            CMD="sudo /etc/init.d/dbus start && sudo /etc/init.d/avahi-daemon start && sudo /etc/init.d/dbus status && cd /home/ubuntu/experiments/ && cov_script /home/ubuntu/input/ 3689 30 /home/ubuntu/input/cov_merge.csv 1"
            ;;
        kamailio)
            IMAGE="kamailio:latest"
            CMD="cd /home/ubuntu/experiments/ && cov_script /home/ubuntu/input/ 5060 30 /home/ubuntu/input/cov_merge.csv 1"
            ;;
        proftpd)
            IMAGE="proftpd:latest"
            CMD="cd /home/ubuntu/experiments/proftpd-gcov && cov_script /home/ubuntu/input/ 21 30 /home/ubuntu/input/cov_merge.csv 1"
            ;;
        pureftpd)
            IMAGE="pure-ftpd:latest"
            CMD="cd /home/ubuntu/experiments/pure-ftpd-gcov && cov_script /home/ubuntu/input/ 21 30 /home/ubuntu/input/cov_merge.csv 1"
            ;;
        *)
            echo "      Unknown target $TARGET_NAME"
            return 1
            ;;
    esac

    local CONTAINER_NAME="merge_cov_${FUZZER}_${TARGET_NAME}_$(date +%s)"
    echo "    [START] $TARGET_NAME ($CONTAINER_NAME)..."

    docker run -d -it \
        -v "$INPUT_DIR":/home/ubuntu/input/ \
        --name "$CONTAINER_NAME" \
        --entrypoint /bin/bash \
        "$IMAGE" -c "$CMD" > /dev/null

    local EXIT_CODE=$(docker wait "$CONTAINER_NAME" 2>/dev/null)
    docker rm "$CONTAINER_NAME" > /dev/null 2>&1

    if [ -f "$INPUT_DIR/cov_merge.csv" ]; then
        lines=$(wc -l < "$INPUT_DIR/cov_merge.csv")
        echo "    [DONE] $TARGET_NAME: cov_merge.csv ($lines lines)"
    else
        echo "    [FAIL] $TARGET_NAME: no cov_merge.csv generated"
    fi
}

# Run coverage in parallel (max 6 at once)
JOB_COUNT=0
for TARGET in "${TARGETS[@]}"; do
    OUT_DIR="${MERGE_DIR}/${TARGET}"
    if [ ! -d "$OUT_DIR/replayable-queue" ] || [ -z "$(ls -A "$OUT_DIR/replayable-queue" 2>/dev/null)" ]; then
        echo "  [SKIP] $TARGET: no seeds in replayable-queue"
        continue
    fi

    run_coverage "$TARGET" "$OUT_DIR" &
    JOB_COUNT=$((JOB_COUNT + 1))
done

echo "  Waiting for $JOB_COUNT coverage jobs..."
wait
echo "  All coverage jobs for ${FUZZER} finished."

echo ""
echo "=========================================="
echo "${FUZZER} merge complete."
echo "Results: ${MERGE_DIR}/"
echo "=========================================="
