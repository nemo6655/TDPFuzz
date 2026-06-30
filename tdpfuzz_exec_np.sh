#!/bin/bash
# NP ablation test: single state pool (TDPFUZZ_FORBIDDEN=NP), 5 generations.
# Usage:
#   ./tdpfuzz_exec_np.sh <test_number> <data_path> <test_object>                        # standalone
#   ./tdpfuzz_exec_np.sh <test_number> <data_path> <test_object> --chain <signal_dir>   # signal next when last AFL starts
#   ./tdpfuzz_exec_np.sh <test_number> <data_path> <test_object> --wait <signal_file>   # wait for previous target

set -euo pipefail

SIGNAL_DIR=""
WAIT_FILE=""

# Parse optional flags
while [[ $# -gt 3 ]]; do
    case "$4" in
        --chain) SIGNAL_DIR="$5"; shift 2 ;;
        --wait)  WAIT_FILE="$5"; shift 2 ;;
        *) echo "Unknown option: $4"; exit 1 ;;
    esac
done

if [ $# -ne 3 ]; then
    echo "Usage: $0 <test_number> <data_path> <test_object> [--chain <signal_dir>] [--wait <signal_file>]"
    exit 1
fi

TEST_NUMBER=$1
DATA_PATH=$2
TEST_OBJECT=$3
IMAGE_NAME="tdpfuzztest_np:latest"
FUZZER_NAME="tdpfuzzer_np"
NUM_GENS=5
FINAL_GEN="gen5"
# NP runs 6 AFL passes: gen0..gen5. The 6th means last AFL started, TGI free.
LAST_AFL_COUNT=6

case $TEST_OBJECT in
    live555|exim|forkeddaapd|kamailio|proftpd|pureftpd) ;;
    *)  echo "Invalid test_object: $TEST_OBJECT"; exit 1 ;;
esac

# --- Wait for previous target's signal ---
if [ -n "$WAIT_FILE" ]; then
    echo "[$(date '+%H:%M:%S')] Waiting for signal: $WAIT_FILE"
    while [ ! -f "$WAIT_FILE" ]; do
        sleep 30
    done
    echo "[$(date '+%H:%M:%S')] Signal received, starting..."
fi

echo "=== NP Test ==="
echo "Image:      $IMAGE_NAME"
echo "Target:     $TEST_OBJECT  (#$TEST_NUMBER)"
echo "Data Path:  $DATA_PATH"
echo "Generations: $NUM_GENS (final AFL: $FINAL_GEN)"
[ -n "$SIGNAL_DIR" ] && echo "Chain:      will signal $SIGNAL_DIR after last AFL starts"

mkdir -p "$DATA_PATH"

CONTAINER_NAME="tdpfuzz_np_${TEST_OBJECT}_${TEST_NUMBER}"
DOCKER_CMD="docker run -d --add-host=host.docker.internal:host-gateway -v /tmp/host:/tmp/host -v /var/run/docker.sock:/var/run/docker.sock --name \"$CONTAINER_NAME\" --entrypoint /bin/bash \"$IMAGE_NAME\" -c \"cd /home/appuser/elmfuzz && TDPFUZZ_FORBIDDEN=NP SELECTION_STRATEGY=lattice REPROUDCE_MODE=true ELMFUZZ_RUNDIR=preset/${TEST_OBJECT} /home/appuser/elmfuzz/all_gen_net.sh preset/${TEST_OBJECT}\""
echo "Executing: $DOCKER_CMD"
CONTAINER_ID=$(eval "$DOCKER_CMD")
echo "Container ID: $CONTAINER_ID"

# Stream logs in background, count "Collecting coverage" to detect last AFL start
if [ -n "$SIGNAL_DIR" ]; then
    mkdir -p "$SIGNAL_DIR"
    SIGNAL_FILE="${SIGNAL_DIR}/${TEST_OBJECT}_last_afl.stamp"

    docker logs -f "$CONTAINER_ID" 2>&1 | while IFS= read -r line; do
        echo "$line"
        if [[ "$line" == *"Collecting coverage of the generators"* ]]; then
            CNT_FILE="${SIGNAL_DIR}/.counter_${TEST_OBJECT}"
            cnt=$(cat "$CNT_FILE" 2>/dev/null || echo 0)
            cnt=$((cnt + 1))
            echo "$cnt" > "$CNT_FILE"
            if [ "$cnt" -ge "$LAST_AFL_COUNT" ] && [ ! -f "$SIGNAL_FILE" ]; then
                touch "$SIGNAL_FILE"
                echo "[$(date '+%H:%M:%S')] *** Last AFL generation started (count=$cnt), TGI free. Signalled $SIGNAL_FILE ***"
            fi
        fi
    done &
    LOG_PID=$!
    # Wait for container
    docker wait "$CONTAINER_ID" > /dev/null
    wait $LOG_PID 2>/dev/null || true
else
    # Simple mode: just stream logs and wait
    docker logs -f "$CONTAINER_ID" 2>&1 &
    LOG_PID=$!
    docker wait "$CONTAINER_ID" > /dev/null
    wait $LOG_PID 2>/dev/null || true
fi

EXIT_CODE=$(docker inspect "$CONTAINER_ID" --format '{{.State.ExitCode}}')
if [ "$EXIT_CODE" -ne 0 ]; then
    echo "Container exited with error code: $EXIT_CODE"
    docker logs "$CONTAINER_ID" 2>&1 | tail -50
    exit 1
fi

echo "Container finished successfully."

# --- Post-processing: extract results ---
CURRENT_DATE=$(date +%Y%m%d)
TMP_DIR="/tmp/tdpfuzz_np_eval_${CURRENT_DATE}_${TEST_OBJECT}_${TEST_NUMBER}"
mkdir -p "$TMP_DIR"

docker cp "$CONTAINER_ID":/home/appuser/elmfuzz/evaluation "$TMP_DIR"/ 2>/dev/null || true
docker logs "$CONTAINER_ID" > "$DATA_PATH/docker_logs.txt" 2>/dev/null || true

TAR_FILE=$(find "$TMP_DIR/evaluation" -name "*.tar.xz" 2>/dev/null | head -1)

if [ -n "$TAR_FILE" ]; then
    cp "$TAR_FILE" "$DATA_PATH/${FUZZER_NAME}_${TEST_OBJECT}_${TEST_NUMBER}.tar.xz"
    echo "Copied: $DATA_PATH/${FUZZER_NAME}_${TEST_OBJECT}_${TEST_NUMBER}.tar.xz"
else
    echo "No tar.xz file found in evaluation directory."
fi
rm -rf "$TMP_DIR"

# Extract replayable-queue from final gen and run coverage
if [ -f "$DATA_PATH/${FUZZER_NAME}_${TEST_OBJECT}_${TEST_NUMBER}.tar.xz" ]; then
    tar -xf "$DATA_PATH/${FUZZER_NAME}_${TEST_OBJECT}_${TEST_NUMBER}.tar.xz" -C "$DATA_PATH"

    GEN_DIR=$(find "$DATA_PATH" -type d -path "*/${FINAL_GEN}/aflnetout" 2>/dev/null | head -1)

    if [ -n "$GEN_DIR" ]; then
        cd "$GEN_DIR"
        ALL_DIR="${FINAL_GEN}_all"
        mkdir -p "$ALL_DIR"
        for file in aflnetout_*.tar.gz; do
            if [ -f "$file" ]; then
                base=$(basename "$file" .tar.gz)
                tar -xzf "$file" -C "$ALL_DIR" --strip-components=1 "$base/replayable-queue"
            fi
        done
        echo "Replayable-queue extracted to ${GEN_DIR}/${ALL_DIR}"
    else
        echo "${FINAL_GEN}/aflnetout directory not found."
    fi

    TEST_OUTPUTS="${GEN_DIR}/${ALL_DIR}"

    case $TEST_OBJECT in
        exim)
            CID=$(docker run -d -it -v "$TEST_OUTPUTS":/home/ubuntu/input/ --entrypoint /bin/bash exim:latest -c "cd /home/ubuntu/experiments/exim-gcov && cp ./src/build-Linux-x86_64/exim /usr/exim/bin/exim && cov_script /home/ubuntu/input/ 25 30 /home/ubuntu/input/cov_over_time_${TEST_OBJECT}_${TEST_NUMBER}.csv 1")
            docker wait "$CID" > /dev/null ;;
        live555)
            CID=$(docker run -d -it -v "$TEST_OUTPUTS":/home/ubuntu/input/ --entrypoint /bin/bash live555:profuzzbench -c "cd /home/ubuntu/experiments/live555-cov/testProgs/ && cov_script /home/ubuntu/input/ 8554 30 /home/ubuntu/input/cov_over_time_${TEST_OBJECT}_${TEST_NUMBER}.csv 1")
            docker wait "$CID" > /dev/null ;;
        forkeddaapd)
            CID=$(docker run -d -it -v "$TEST_OUTPUTS":/home/ubuntu/input/ --entrypoint /bin/bash forked-daapd:latest -c "sudo /etc/init.d/dbus start && sudo /etc/init.d/avahi-daemon start && sudo /etc/init.d/dbus status && cd /home/ubuntu/experiments/ && cov_script /home/ubuntu/input/ 3689 30 /home/ubuntu/input/cov_over_time_${TEST_OBJECT}_${TEST_NUMBER}.csv 1")
            docker wait "$CID" > /dev/null ;;
        kamailio)
            CID=$(docker run -d -it -v "$TEST_OUTPUTS":/home/ubuntu/input/ --entrypoint /bin/bash kamailio:latest -c "cd /home/ubuntu/experiments/ && cov_script /home/ubuntu/input/ 5060 30 /home/ubuntu/input/cov_over_time_${TEST_OBJECT}_${TEST_NUMBER}.csv 1")
            docker wait "$CID" > /dev/null ;;
        proftpd)
            CID=$(docker run -d -it -v "$TEST_OUTPUTS":/home/ubuntu/input/ --entrypoint /bin/bash proftpd:latest -c "cd /home/ubuntu/experiments/proftpd-gcov && cov_script /home/ubuntu/input/ 21 30 /home/ubuntu/input/cov_over_time_${TEST_OBJECT}_${TEST_NUMBER}.csv 1")
            docker wait "$CID" > /dev/null ;;
        pureftpd)
            CID=$(docker run -d -it -v "$TEST_OUTPUTS":/home/ubuntu/input/ --entrypoint /bin/bash pure-ftpd:latest -c "cd /home/ubuntu/experiments/pure-ftpd-gcov && cov_script /home/ubuntu/input/ 21 30 /home/ubuntu/input/cov_over_time_${TEST_OBJECT}_${TEST_NUMBER}.csv 1")
            docker wait "$CID" > /dev/null ;;
    esac
    echo "Coverage written to ${TEST_OUTPUTS}/cov_over_time_${TEST_OBJECT}_${TEST_NUMBER}.csv"
fi

docker rm "$CONTAINER_ID" > /dev/null 2>&1
[ -n "$SIGNAL_DIR" ] && rm -f "${SIGNAL_DIR}/.counter_${TEST_OBJECT}"
echo "Done. Container $CONTAINER_ID removed."
