#!/bin/bash
# Orchestrate remaining NP experiments.
# Phase 1: wait for live555 (manual start) to finish, archive results
# Phase 2: wait for exim to enter last AFL gen, then chain-start the remaining 4
# Usage: ./run_np_chain.sh

set -euo pipefail

SIGNAL_DIR="/tmp/tdpfuzz_signal"
EVAL_DIR="/home/pzst/LLM-PROTOCOL-FUZZ/TDPFuzz/evaluation/tdpfuzz_np"
LIVE555_CONTAINER="tdpfuzz_np_test"
EXIM_CONTAINER="tdpfuzz_np_exim_1"
LAST_AFL_COUNT=6  # gen0..gen5 = 6 AFL passes

rm -rf "$SIGNAL_DIR"
mkdir -p "$SIGNAL_DIR" "$EVAL_DIR"

archive_target() {
    local container="$1" target="$2" data_dir="$3"
    echo "[$(date '+%H:%M:%S')] Archiving $target from $container..."

    TMP_DIR="/tmp/tdpfuzz_archive_${target}_$(date +%Y%m%d%H%M%S)"
    mkdir -p "$TMP_DIR"

    docker cp "$container":/home/appuser/elmfuzz/evaluation "$TMP_DIR"/ 2>/dev/null || true
    TAR_FILE=$(find "$TMP_DIR/evaluation" -name "*.tar.xz" 2>/dev/null | head -1)
    if [ -n "$TAR_FILE" ]; then
        mkdir -p "$data_dir"
        cp "$TAR_FILE" "$data_dir/tdpfuzzer_np_${target}_1.tar.xz"
        echo "  [OK] Copied tar.xz"
    else
        echo "  [WARN] No tar.xz found"
    fi
    rm -rf "$TMP_DIR"

    if [ -f "$data_dir/tdpfuzzer_np_${target}_1.tar.xz" ]; then
        tar -xf "$data_dir/tdpfuzzer_np_${target}_1.tar.xz" -C "$data_dir" 2>/dev/null || true
        GEN_DIR=$(find "$data_dir" -type d -path "*/gen5/aflnetout" 2>/dev/null | head -1)
        if [ -n "$GEN_DIR" ]; then
            cd "$GEN_DIR"
            mkdir -p gen5_all
            for f in aflnetout_*.tar.gz; do
                [ -f "$f" ] || continue
                base=$(basename "$f" .tar.gz)
                tar -xzf "$f" -C gen5_all --strip-components=1 "$base/replayable-queue" 2>/dev/null || true
            done
            echo "  [OK] Replayable-queue extracted to gen5_all"

            TEST_OUTPUTS="$GEN_DIR/gen5_all"
            case $target in
                live555)
                    CID=$(docker run -d -it -v "$TEST_OUTPUTS":/home/ubuntu/input/ --entrypoint /bin/bash live555:profuzzbench -c "cd /home/ubuntu/experiments/live555-cov/testProgs/ && cov_script /home/ubuntu/input/ 8554 30 /home/ubuntu/input/cov_over_time_${target}_1.csv 1")
                    docker wait "$CID" > /dev/null 2>&1 ;;
                exim)
                    CID=$(docker run -d -it -v "$TEST_OUTPUTS":/home/ubuntu/input/ --entrypoint /bin/bash exim:latest -c "cd /home/ubuntu/experiments/exim-gcov && cp ./src/build-Linux-x86_64/exim /usr/exim/bin/exim && cov_script /home/ubuntu/input/ 25 30 /home/ubuntu/input/cov_over_time_${target}_1.csv 1")
                    docker wait "$CID" > /dev/null 2>&1 ;;
                forkeddaapd)
                    CID=$(docker run -d -it -v "$TEST_OUTPUTS":/home/ubuntu/input/ --entrypoint /bin/bash forked-daapd:latest -c "sudo /etc/init.d/dbus start && sudo /etc/init.d/avahi-daemon start && sudo /etc/init.d/dbus status && cd /home/ubuntu/experiments/ && cov_script /home/ubuntu/input/ 3689 30 /home/ubuntu/input/cov_over_time_${target}_1.csv 1")
                    docker wait "$CID" > /dev/null 2>&1 ;;
                kamailio)
                    CID=$(docker run -d -it -v "$TEST_OUTPUTS":/home/ubuntu/input/ --entrypoint /bin/bash kamailio:latest -c "cd /home/ubuntu/experiments/ && cov_script /home/ubuntu/input/ 5060 30 /home/ubuntu/input/cov_over_time_${target}_1.csv 1")
                    docker wait "$CID" > /dev/null 2>&1 ;;
                proftpd)
                    CID=$(docker run -d -it -v "$TEST_OUTPUTS":/home/ubuntu/input/ --entrypoint /bin/bash proftpd:latest -c "cd /home/ubuntu/experiments/proftpd-gcov && cov_script /home/ubuntu/input/ 21 30 /home/ubuntu/input/cov_over_time_${target}_1.csv 1")
                    docker wait "$CID" > /dev/null 2>&1 ;;
                pureftpd)
                    CID=$(docker run -d -it -v "$TEST_OUTPUTS":/home/ubuntu/input/ --entrypoint /bin/bash pure-ftpd:latest -c "cd /home/ubuntu/experiments/pure-ftpd-gcov && cov_script /home/ubuntu/input/ 21 30 /home/ubuntu/input/cov_over_time_${target}_1.csv 1")
                    docker wait "$CID" > /dev/null 2>&1 ;;
            esac
            echo "  [OK] Coverage generated"
        else
            echo "  [WARN] No gen5/aflnetout found"
        fi
    fi
}

# ============================================================
# Phase 1: Wait for live555 to finish
# ============================================================
echo "============================================"
echo "Phase 1: Waiting for live555 ($LIVE555_CONTAINER)"
echo "============================================"

if docker ps --format '{{.Names}}' | grep -q "^${LIVE555_CONTAINER}$"; then
    echo "[$(date '+%H:%M:%S')] live555 still running, waiting..."
    docker wait "$LIVE555_CONTAINER" > /dev/null
    echo "[$(date '+%H:%M:%S')] live555 finished."
else
    echo "live555 container not running."
fi

archive_target "$LIVE555_CONTAINER" "live555" "${EVAL_DIR}/live555"
docker rm "$LIVE555_CONTAINER" > /dev/null 2>&1 || true

# ============================================================
# Phase 2: Monitor exim, chain-start remaining targets
# ============================================================
echo ""
echo "============================================"
echo "Phase 2: Monitoring exim for last AFL gen"
echo "============================================"

# Check if exim is still running
if ! docker ps --format '{{.Names}}' | grep -q "^${EXIM_CONTAINER}$"; then
    echo "[$(date '+%H:%M:%S')] exim already finished."
    archive_target "$EXIM_CONTAINER" "exim" "${EVAL_DIR}/exim"
    docker rm "$EXIM_CONTAINER" > /dev/null 2>&1 || true
fi

# Monitor exim logs for last AFL start
if docker ps --format '{{.Names}}' | grep -q "^${EXIM_CONTAINER}$"; then
    echo "[$(date '+%H:%M:%S')] Tailing exim logs, waiting for last AFL (count=$LAST_AFL_COUNT)..."
    # Count from existing logs first
    existing=$(docker logs "$EXIM_CONTAINER" 2>&1 | grep -c "Collecting coverage of the generators" || true)
    echo "  Starting count: $existing"

    # Stream new logs
    docker logs -f "$EXIM_CONTAINER" 2>&1 | while IFS= read -r line; do
        if [[ "$line" == *"Collecting coverage of the generators"* ]]; then
            existing=$((existing + 1))
            if [ "$existing" -ge "$LAST_AFL_COUNT" ] && [ ! -f "${SIGNAL_DIR}/exim_last_afl.stamp" ]; then
                touch "${SIGNAL_DIR}/exim_last_afl.stamp"
                echo "[$(date '+%H:%M:%S')] *** exim last AFL started (count=$existing), launching chain ***"
            fi
        fi
    done &
    MONITOR_PID=$!

    # Wait for the stamp file to appear, then launch chain
    echo "[$(date '+%H:%M:%S')] Waiting for exim's last AFL signal..."
    while [ ! -f "${SIGNAL_DIR}/exim_last_afl.stamp" ]; do
        sleep 10
    done
    kill $MONITOR_PID 2>/dev/null || true
else
    # exim not running, just create the signal
    touch "${SIGNAL_DIR}/exim_last_afl.stamp"
fi

# ============================================================
# Phase 3: Chain-launch remaining 4 targets
# ============================================================
echo ""
echo "============================================"
echo "Phase 3: Launching forkeddaapd → kamailio → proftpd → pureftpd"
echo "============================================"

TARGETS=(forkeddaapd kamailio proftpd pureftpd)
PREV=""

for target in "${TARGETS[@]}"; do
    DATA_PATH="${EVAL_DIR}/${target}"
    ARGS=(1 "$DATA_PATH" "$target" --chain "$SIGNAL_DIR")

    if [ -n "$PREV" ]; then
        ARGS+=(--wait "${SIGNAL_DIR}/${PREV}_last_afl.stamp")
    else
        # First in chain: wait for exim's signal (or start immediately if already signalled)
        ARGS+=(--wait "${SIGNAL_DIR}/exim_last_afl.stamp")
    fi

    echo "[$(date '+%H:%M:%S')] Launching $target..."
    nohup /home/pzst/LLM-PROTOCOL-FUZZ/TDPFuzz/tdpfuzz_exec_np.sh "${ARGS[@]}" > "/tmp/tdpfuzz_np_${target}.log" 2>&1 &
    echo "  PID: $!  (waiting on: ${ARGS[${#ARGS[@]}-1]})"
    PREV="$target"
    sleep 2
done

echo ""
echo "All targets queued. Monitor:"
echo "  tail -f /tmp/tdpfuzz_np_*.log"
echo "  ls /tmp/tdpfuzz_signal/"
