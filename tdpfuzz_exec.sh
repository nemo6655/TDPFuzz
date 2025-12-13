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
CONTAINER_NAME="tdpfuzz${TEST_NUMBER}${IMAGE_NAME//:/_}"

# 启动 Docker 容器并运行命令（detached 模式）
DOCKER_CMD="docker run -d --cpus 8 --add-host=host.docker.internal:host-gateway -v /tmp/host:/tmp/host -v /var/run/docker.sock:/var/run/docker.sock --name \"$CONTAINER_NAME\" --entrypoint /bin/bash \"$IMAGE_NAME\" -c \"cd /home/appuser/elmfuzz && ELMFUZZ_RUNDIR=preset/${TEST_OBJECT} /home/appuser/miniconda3/envs/py310/bin/python /home/appuser/elmfuzz/cli/main.py tdnet -T ${FUZZER_NAME} ${TEST_OBJECT} -n 5\""
echo "Executing Docker command: $DOCKER_CMD"
CONTAINER_ID=$(eval "$DOCKER_CMD")

# 输出容器 ID
echo "Container ID: $CONTAINER_ID"

# 等待容器结束
EXIT_CODE=$(docker wait "$CONTAINER_ID")

# 判断容器是否正常结束
if [ "$EXIT_CODE" -eq 0 ]; then
    echo "Docker container finished successfully."
    
    # 创建临时目录
    TMP_DIR="/tmp/tdpfuzz_eval_$TEST_NUMBER"
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
    # rm -rf "$TMP_DIR"
else
    echo "Docker container exited with error code: $EXIT_CODE"
    # 输出容器日志以获取错误原因
    echo "Container logs:"
    docker logs "$CONTAINER_ID"
fi

