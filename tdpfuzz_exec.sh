#!/bin/bash

# 检查参数数量
if [ $# -ne 5 ]; then
    echo "Usage: $0 <image_name> <test_number> <data_path> <fuzzer_name> <test_object>"
    exit 1
fi

IMAGE_NAME=$1
TEST_NUMBER=$2
DATA_PATH=$3
FUZZER_NAME=$4
TEST_OBJECT=$5

# 验证 fuzzer_name
case $FUZZER_NAME in
    tdpfuzzer.tdpfuzzer|tdpfuzzer.tdpfuzzer_noss|tdpfuzzer.tdpfuzzer_nosm)
        ;;
    *)
        echo "Invalid fuzzer_name: $FUZZER_NAME. Must be one of: tdpfuzzer.tdpfuzzer, tdpfuzzer.tdpfuzzer_noss, tdpfuzzer.tdpfuzzer_nosm"
        exit 1
        ;;
esac

# 验证 test_object
case $TEST_OBJECT in
    live555|exim|forkeddaapd|kamailio|proftpd|pureftpd)
        ;;
    *)
        echo "Invalid test_object: $TEST_OBJECT. Must be one of: live555, exim, forkeddaapd, kamailio, proftpd, pureftpd"
        exit 1
        ;;
esac

# 打印所有参数
echo "Image Name: $IMAGE_NAME"
echo "Test Number: $TEST_NUMBER"
echo "Data Path: $DATA_PATH"
echo "Fuzzer Name: $FUZZER_NAME"
echo "Test Object: $TEST_OBJECT"

# 验证 DATA_PATH 是否存在，如果不存在则创建
if [ ! -d "$DATA_PATH" ]; then
    mkdir -p "$DATA_PATH"
    echo "Created data directory: $DATA_PATH"
fi

# 构建容器名称（替换冒号为下划线以避免无效字符）
CONTAINER_NAME="tdpfuzz_${TEST_OBJECT}_${IMAGE_NAME//:/_}_${TEST_NUMBER}"

# 启动 Docker 容器并运行命令（detached 模式）
DOCKER_CMD="docker run -d --add-host=host.docker.internal:host-gateway -v /tmp/host:/tmp/host -v /var/run/docker.sock:/var/run/docker.sock --name \"$CONTAINER_NAME\" --entrypoint /bin/bash \"$IMAGE_NAME\" -c \"cd /home/appuser/elmfuzz && ELMFUZZ_RUNDIR=preset/${TEST_OBJECT} /home/appuser/miniconda3/envs/py310/bin/python /home/appuser/elmfuzz/cli/main.py tdnet -T ${FUZZER_NAME} ${TEST_OBJECT} -n 5\""
echo "Executing Docker command: $DOCKER_CMD"
CONTAINER_ID=$(eval "$DOCKER_CMD")

# 输出容器 ID
echo "Container ID: $CONTAINER_ID"

# 等待容器结束
EXIT_CODE=$(docker wait "$CONTAINER_ID")

# 判断容器是否正常结束
if [ "$EXIT_CODE" -eq 0 ]; then
    echo "Docker container finished successfully."
    
# 获取当前日期
    CURRENT_DATE=$(date +%Y%m%d)

    # 创建临时目录
    TMP_DIR="/tmp/tdpfuzz_eval_${CURRENT_DATE}_${TEST_OBJECT}_${TEST_NUMBER}"
    mkdir -p "$TMP_DIR"
    
    # 从容器复制 evaluation 目录
    docker cp "$CONTAINER_ID":/home/appuser/elmfuzz/evaluation "$TMP_DIR"/
    docker logs -f "$CONTAINER_ID" > "$DATA_PATH/docker_logs.txt"
    # 查找 tar.gz 文件
    TAR_FILE=$(find "$TMP_DIR/evaluation" -name "*.tar.xz" | head -1)
    
    if [ -n "$TAR_FILE" ]; then
        # 复制并重命名文件到 DATA_PATH
        cp "$TAR_FILE" "$DATA_PATH/${FUZZER_NAME}_${TEST_OBJECT}_${TEST_NUMBER}.tar.xz"
        echo "File copied to $DATA_PATH/${FUZZER_NAME}_${TEST_OBJECT}_${TEST_NUMBER}.tar.xz"
    else
        echo "No tar.xz file found in the container's evaluation directory."
    fi
    
    # 清理临时目录
    rm -rf "$TMP_DIR"
    
    # 解压 tar.xz 文件到 DATA_PATH
    tar -xf "$DATA_PATH/${FUZZER_NAME}_${TEST_OBJECT}_${TEST_NUMBER}.tar.xz" -C "$DATA_PATH"
    
    # 查找 gen5/aflnetout 目录
    GEN5_AFLNETOUT_DIR=$(find "$DATA_PATH" -type d -path "*/gen5/aflnetout" | head -1)
    
    if [ -n "$GEN5_AFLNETOUT_DIR" ]; then
        cd "$GEN5_AFLNETOUT_DIR"
        mkdir -p gen5_all
        for file in aflnetout_*.tar.gz; do
            if [ -f "$file" ]; then
                base=$(basename "$file" .tar.gz)
                tar -xzf "$file" -C gen5_all --strip-components=1 "$base/replayable-queue"
            fi
        done
        echo "Extraction completed in $GEN5_AFLNETOUT_DIR/gen5_all"
    else
        echo "gen5/aflnetout directory not found."
    fi
    TEST_OUTPUTS="$GEN5_AFLNETOUT_DIR/gen5_all"

    # 生成目标覆盖率文件
    case $TEST_OBJECT in
        exim)
            DOCKER_CMD="docker run -d -it -v \"$TEST_OUTPUTS\":/home/ubuntu/input/ --entrypoint /bin/bash exim:latest -c \"cd /home/ubuntu/experiments/exim-gcov && cp ./src/build-Linux-x86_64/exim /usr/exim/bin/exim && cov_script /home/ubuntu/input/ 25 30 /home/ubuntu/input/cov_over_time_${TEST_OBJECT}_${TEST_NUMBER}.csv 1\""
            echo "Executing Docker command: $DOCKER_CMD"
            CONTAINER_ID=$(eval "$DOCKER_CMD")
            echo "Container ID: $CONTAINER_ID"
            EXIT_CODE=$(docker wait "$CONTAINER_ID")
            ;;
        live555)
            DOCKER_CMD="docker run -d -it -v \"$TEST_OUTPUTS\":/home/ubuntu/input/ --entrypoint /bin/bash live555:profuzzbench -c \"cd /home/ubuntu/experiments/live555-cov/testProgs/ && cov_script /home/ubuntu/input/ 8554 30 /home/ubuntu/input/cov_over_time_${TEST_OBJECT}_${TEST_NUMBER}.csv 1\""
            echo "Executing Docker command: $DOCKER_CMD"
            CONTAINER_ID=$(eval "$DOCKER_CMD")
            echo "Container ID: $CONTAINER_ID"
            EXIT_CODE=$(docker wait "$CONTAINER_ID")
            ;;
        forkeddaapd)
            # sudo /etc/init.d/dbus start
            # sudo /etc/init.d/avahi-daemon start
            # sudo /etc/init.d/dbus status
            DOCKER_CMD="docker run -dit -v \"$TEST_OUTPUTS\":/home/ubuntu/input/ --entrypoint /bin/bash forked-daapd:latest -c \"sudo /etc/init.d/dbus start && sudo /etc/init.d/avahi-daemon start && sudo /etc/init.d/dbus status && cd /home/ubuntu/experiments/ && cov_script /home/ubuntu/input/ 3689 30 /home/ubuntu/input/cov_over_time_$TEST_OBJECT.csv 1\""
            CONTAINER_ID=$(eval "$DOCKER_CMD")
            echo "Container ID: $CONTAINER_ID"
            EXIT_CODE=$(docker wait "$CONTAINER_ID")
            ;;
        kamailio)
            DOCKER_CMD="docker run -d -it -v \"$TEST_OUTPUTS\":/home/ubuntu/input/ --entrypoint /bin/bash kamailio:latest -c \"cd /home/ubuntu/experiments/ && cov_script /home/ubuntu/input/ 5060 30 /home/ubuntu/input/cov_over_time_${TEST_OBJECT}_${TEST_NUMBER}.csv 1\""
            echo "Executing Docker command: $DOCKER_CMD"
            CONTAINER_ID=$(eval "$DOCKER_CMD")
            echo "Container ID: $CONTAINER_ID"
            EXIT_CODE=$(docker wait "$CONTAINER_ID")
            ;;
        proftpd)
            DOCKER_CMD="docker run -d -it -v \"$TEST_OUTPUTS\":/home/ubuntu/input/ --entrypoint /bin/bash proftpd:latest -c \"cd /home/ubuntu/experiments/proftpd-gcov && cov_script /home/ubuntu/input/ 21 30 /home/ubuntu/input/cov_over_time_${TEST_OBJECT}_${TEST_NUMBER}.csv 1\""
            echo "Executing Docker command: $DOCKER_CMD"
            CONTAINER_ID=$(eval "$DOCKER_CMD")
            echo "Container ID: $CONTAINER_ID"
            EXIT_CODE=$(docker wait "$CONTAINER_ID")
            ;;
        pureftpd)
            DOCKER_CMD="docker run -d -it -v \"$TEST_OUTPUTS\":/home/ubuntu/input/ --entrypoint /bin/bash pure-ftpd:latest -c \"cd /home/ubuntu/experiments/pure-ftpd-gcov && cov_script /home/ubuntu/input/ 21 30 /home/ubuntu/input/cov_over_time_${TEST_OBJECT}_${TEST_NUMBER}.csv 1\""
            echo "Executing Docker command: $DOCKER_CMD"
            CONTAINER_ID=$(eval "$DOCKER_CMD")
            echo "Container ID: $CONTAINER_ID"
            EXIT_CODE=$(docker wait "$CONTAINER_ID")
            ;;
        *)
            echo "Unknown test_object for coverage generation"
            ;;
    esac

else
    echo "Docker container exited with error code: $EXIT_CODE"
    # 输出容器日志以获取错误原因
    echo "Container logs:"
    docker logs "$CONTAINER_ID"
fi

