#!/bin/bash

# Default Paths
BASE_PATH="/home/pzst/LLM-PROTOCOL-FUZZ/TDPFuzz/evaluation/tdpfuzz"
SPCM_PATH="/home/pzst/LLM-PROTOCOL-FUZZ/TDPFuzz/evaluation/SPCM"

# Global Variables
EXEC_COV=false
CLEAN_DIR=false
TARGET=""
TARGET_DIR=""
RUN_DIR_PATH=""
MAX_JOBS=4

export BASE_PATH SPCM_PATH

usage() {
    echo "Usage: $0 -t <target> [-d <target_dir>] [-r <run_dir>] [-c] [-x] [-j <jobs>]"
    echo "  -t  Target name (e.g., exim, live555)"
    echo "  -d  Target directory (default: $BASE_PATH/<target>)"
    echo "  -r  Run directory path (default: auto-detected in <target_dir>/run1)"
    echo "  -c  Execute coverage statistics (starts containers)"
    echo "  -x  Clean SPCM output directory for target before processing"
    echo "  -j  Max parallel jobs (default: 4)"
    exit 1
}

# Parse Arguments
while getopts "t:d:r:cxj:" opt; do
    case $opt in
        t) TARGET=$OPTARG ;;
        d) TARGET_DIR=$OPTARG ;;
        r) RUN_DIR_PATH=$OPTARG ;;
        c) EXEC_COV=true ;;
        x) CLEAN_DIR=true ;;
        j) MAX_JOBS=$OPTARG ;;
        *) usage ;;
    esac
done

# Function to manage job limit
wait_for_jobs() {
    while [ $(jobs -r | wc -l) -ge $MAX_JOBS ]; do
        sleep 1
    done
}


if [ -z "$TARGET" ]; then
    echo "Error: Target is required."
    usage
fi

process_target() {
    local TARGET_NAME=$1
    local T_DIR=$2
    local R_DIR=$3

    # Clean Output Directory if requested
    if [ "$CLEAN_DIR" = true ]; then
        local TARGET_OUT_DIR="$SPCM_PATH/$TARGET_NAME"
        if [ -d "$TARGET_OUT_DIR" ]; then
            echo "cleaning output directory: $TARGET_OUT_DIR"
            rm -rf "$TARGET_OUT_DIR"/*
        fi
    fi
    
    echo "Processing $TARGET_NAME..."
    echo "  Target Dir: $T_DIR"

    # Determine Run Directory if not provided
    if [ -z "$R_DIR" ]; then
        RUN_ROOT="$T_DIR/run1"
        if [ ! -d "$RUN_ROOT" ]; then
            echo "  Run dir root not found: $RUN_ROOT"
            return
        fi
        R_DIR=$(find "$RUN_ROOT" -mindepth 1 -maxdepth 1 -type d | head -n 1)
        if [ -z "$R_DIR" ]; then
            echo "  No specific run dir found in $RUN_ROOT"
            return
        fi
    else
        # If R_DIR is provided but doesn't exist locally, try resolving against T_DIR
        if [ ! -d "$R_DIR" ] && [ -d "$T_DIR/$R_DIR" ]; then
             echo "  Resolving relative run directory: $R_DIR -> $T_DIR/$R_DIR"
             R_DIR="$T_DIR/$R_DIR"
        fi
    fi
    
    echo "  Using run dir: $R_DIR"
    
    # PHASE 1: EXTRACTION
    echo "=== PHASE 1: Extracting Seeds ==="
    while read SEED_LOG; do
        GEN_DIR=$(dirname $(dirname "$SEED_LOG"))
        GEN_NAME=$(basename "$GEN_DIR") 
        GENS_ROOT=$(dirname "$GEN_DIR")

        # Output directory
        OUT_DIR="$SPCM_PATH/$TARGET_NAME/$GEN_NAME"
        REPLAYABLE_ELITES_DIR="$OUT_DIR/replayable_elites"
        REPLAYABLE_ALL_DIR="$OUT_DIR/replayable_all"
        
        # Create replayable-queue subdirectories
        REPLAYABLE_ELITES_QUEUE="$REPLAYABLE_ELITES_DIR/replayable-queue"
        REPLAYABLE_ALL_QUEUE="$REPLAYABLE_ALL_DIR/replayable-queue"
        
        mkdir -p "$REPLAYABLE_ELITES_QUEUE"
        mkdir -p "$REPLAYABLE_ALL_QUEUE"
        
        echo "    Extracting for $GEN_NAME..."
        
        # 1. Extract ALL seeds
        AFLNETOUT_DIR="$GEN_DIR/aflnetout"
        if [ -d "$AFLNETOUT_DIR" ]; then
            # echo "      Extracting all seeds..."
            for TAR_FILE in "$AFLNETOUT_DIR"/aflnetout_*.tar.gz; do
                if [ -f "$TAR_FILE" ]; then
                    tar -xzf "$TAR_FILE" -C "$REPLAYABLE_ALL_QUEUE" --wildcards "*/replayable-queue/*" --strip-components=2 2>/dev/null
                fi
            done
        else
            echo "      [WARN] aflnetout directory missing: $AFLNETOUT_DIR"
        fi
        
        # 2. Extract ELITE seeds
        while read line; do
            if [[ "$line" == "ILP"* ]] || [[ -z "$line" ]]; then continue; fi
            PREFIX=$(echo "$line" | cut -d'/' -f1)
            REMAINDER=$(echo "$line" | cut -d'/' -f2-)
            FILENAME=$(echo "$REMAINDER" | sed 's/: [0-9]* edges.*//')
            SRC_GEN=$(echo "$PREFIX" | cut -d'-' -f1)
            SRC_INSTANCE=$(echo "$PREFIX" | cut -d'-' -f2)
            TAR_FILE="$GENS_ROOT/$SRC_GEN/aflnetout/aflnetout_$SRC_INSTANCE.tar.gz"
            
            if [ -f "$TAR_FILE" ]; then
                # Check if file exists in tar before extracting (optional, but safer to check result)
                tar -xzf "$TAR_FILE" -C "$REPLAYABLE_ELITES_QUEUE" --wildcards "*/replayable-queue/$FILENAME" --strip-components=2 2>/dev/null
                
                # Verification: Check if the file was actually extracted
                if [ ! -f "$REPLAYABLE_ELITES_QUEUE/$FILENAME" ]; then
                     echo "[MISSING] $GEN_NAME: $line (Expected from $TAR_FILE)" >> "$SPCM_PATH/$TARGET_NAME/missing_seeds.log"
                fi
            else
                echo "[MISSING_TAR] $GEN_NAME: Tar file not found $TAR_FILE" >> "$SPCM_PATH/$TARGET_NAME/missing_seeds.log"
            fi
        done < "$SEED_LOG"
        
        echo "      Extracted seeds for $GEN_NAME."
    done < <(find "$R_DIR" -type f -name "seeds.log" | sort)

    # PHASE 2: COVERAGE
    if [ "$EXEC_COV" = true ]; then
        echo "=== PHASE 2: Calculating Coverage ==="
        while read SEED_LOG; do
            GEN_DIR=$(dirname $(dirname "$SEED_LOG"))
            GEN_NAME=$(basename "$GEN_DIR") 
            OUT_DIR="$SPCM_PATH/$TARGET_NAME/$GEN_NAME"
            REPLAYABLE_ELITES_DIR="$OUT_DIR/replayable_elites"
            REPLAYABLE_ALL_DIR="$OUT_DIR/replayable_all"

            echo "    Submitting coverage tasks for $GEN_NAME..."

            # Special optimization for gen5 (Final generation):
            # If gen5/aflnetout/gen5_all/cov_over_time_TARGET.csv exists, use it directly as cov_all.csv
            # The exact filename depends on target, e.g., cov_over_time_exim.csv
            
            # Check for pre-calculated coverage file in gen5
            PRE_CALC_CSV=""
            if [[ "$GEN_NAME" == "gen5" ]]; then
                 # Try to find the csv pattern
                 # Assuming path: RUN_DIR/gen5/aflnetout/gen5_all/cov_over_time_*.csv
                 PRE_CALC_CSV=$(find "$GEN_DIR/aflnetout/gen5_all" -name "cov_over_time_*.csv" 2>/dev/null | head -n 1)
            fi
            
            if [[ -n "$PRE_CALC_CSV" && -f "$PRE_CALC_CSV" ]]; then
                 echo "      [INFO] Using pre-calculated coverage for gen5: $PRE_CALC_CSV"
                 cp "$PRE_CALC_CSV" "$OUT_DIR/cov_all.csv"
            else
                # Default calculation
                # Check for seeds inside the replayable-queue subdirectory
                if [ "$(ls -A "$REPLAYABLE_ALL_DIR/replayable-queue" 2>/dev/null)" ]; then
                    wait_for_jobs
                    # Pass the parent directory (REPLAYABLE_ALL_DIR) which CONTAINS replayable-queue
                    run_coverage "$TARGET_NAME" "$REPLAYABLE_ALL_DIR" "cov_all.csv" &
                fi
            fi
            
            # Check for seeds inside the replayable-queue subdirectory
            if [ "$(ls -A "$REPLAYABLE_ELITES_DIR/replayable-queue" 2>/dev/null)" ]; then
                wait_for_jobs
                # Pass the parent directory (REPLAYABLE_ELITES_DIR) which CONTAINS replayable-queue
                run_coverage "$TARGET_NAME" "$REPLAYABLE_ELITES_DIR" "cov_elites.csv" &
            fi
        done < <(find "$R_DIR" -type f -name "seeds.log" | sort)
    
        echo "  Waiting for coverage jobs to complete..."
        wait
        echo "  All coverage jobs for $TARGET_NAME finished."
    fi
}

run_coverage() {
    local TARGET_NAME=$1
    local INPUT_DIR=$2 
    local OUTPUT_FILE=$3 
    
    echo "    [START] Coverage for $TARGET_NAME ($OUTPUT_FILE) ..."
    
    local IMAGE=""
    local CMD=""

    case $TARGET_NAME in
        exim)
            IMAGE="exim:latest"
            CMD="cd /home/ubuntu/experiments/exim-gcov && cp ./src/build-Linux-x86_64/exim /usr/exim/bin/exim && cov_script /home/ubuntu/input/ 25 30 /home/ubuntu/input/$OUTPUT_FILE 1"
            ;;
        live555)
            IMAGE="live555:profuzzbench"
            CMD="cd /home/ubuntu/experiments/live555-cov/testProgs/ && cov_script /home/ubuntu/input/ 8554 30 /home/ubuntu/input/$OUTPUT_FILE 1"
            ;;
        forkeddaapd)
            IMAGE="forked-daapd:latest"
            CMD="sudo /etc/init.d/dbus start && sudo /etc/init.d/avahi-daemon start && sudo /etc/init.d/dbus status && cd /home/ubuntu/experiments/ && cov_script /home/ubuntu/input/ 3689 30 /home/ubuntu/input/$OUTPUT_FILE 1"
            ;;
        kamailio)
            IMAGE="kamailio:latest"
            CMD="cd /home/ubuntu/experiments/ && cov_script /home/ubuntu/input/ 5060 30 /home/ubuntu/input/$OUTPUT_FILE 1"
            ;;
        proftpd)
            IMAGE="proftpd:latest"
            CMD="cd /home/ubuntu/experiments/proftpd-gcov && cov_script /home/ubuntu/input/ 21 30 /home/ubuntu/input/$OUTPUT_FILE 1"
            ;;
        pureftpd)
            IMAGE="pure-ftpd:latest"
            CMD="cd /home/ubuntu/experiments/pure-ftpd-gcov && cov_script /home/ubuntu/input/ 21 30 /home/ubuntu/input/$OUTPUT_FILE 1"
            ;;
        *)
            echo "      Unknown target $TARGET_NAME"
            return
            ;;
    esac
    
    local CONTAINER_NAME="spcm_cov_${TARGET_NAME}_$(date +%s%N)_$RANDOM"
    local DOCKER_CMD="docker run -d -it -v \"$INPUT_DIR\":/home/ubuntu/input/ --name \"$CONTAINER_NAME\" --entrypoint /bin/bash $IMAGE -c \"$CMD\""
    
    local CONTAINER_ID=$(eval "$DOCKER_CMD")
    
    if [ -n "$CONTAINER_ID" ]; then
        docker wait "$CONTAINER_ID" >/dev/null 2>&1
        docker rm "$CONTAINER_ID" >/dev/null 2>&1
    fi
    
    if [ -f "$INPUT_DIR/$OUTPUT_FILE" ]; then
        mv "$INPUT_DIR/$OUTPUT_FILE" "$(dirname "$INPUT_DIR")/$OUTPUT_FILE"
        echo "    [DONE] $(dirname "$INPUT_DIR")/$OUTPUT_FILE"
    else
        echo "    [FAIL] Failed to generate $OUTPUT_FILE in $(dirname "$INPUT_DIR")"
    fi
}

# Resolve defaults
if [ -z "$TARGET_DIR" ]; then
    TARGET_DIR="$BASE_PATH/$TARGET"
fi

# Main execution
process_target "$TARGET" "$TARGET_DIR" "$RUN_DIR_PATH"
