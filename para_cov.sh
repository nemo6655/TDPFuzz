#!/bin/bash

# 检查参数数量
if [ $# -ne 2 ]; then
    echo "Usage: $0 <test_object> <data_dir>"
    exit 1
fi

TEST_OBJECT=$1
DATA_DIR=$2

# 验证 test_object
case $TEST_OBJECT in
    live555|exim|forkeddaapd|kamailio|proftpd|pureftpd)
        ;;
    *)
        echo "Invalid test_object: $TEST_OBJECT. Must be one of: live555, exim, forkeddaapd, kamailio, proftpd, pureftpd"
        exit 1
        ;;
esac

# 验证 DATA_DIR
if [ ! -d "$DATA_DIR" ]; then
    echo "Data directory not found: $DATA_DIR"
    exit 1
fi

# 获取绝对路径
abspath() {
    cd "$1" && pwd
}

DATA_DIR=$(abspath "$DATA_DIR")
MERGED_COV_DIR="$DATA_DIR/merged-cov"
REPLAYABLE_QUEUE_DIR="$MERGED_COV_DIR/replayable-queue"

echo "Test Object: $TEST_OBJECT"
echo "Data Directory: $DATA_DIR"
echo "Merged Cov Directory: $MERGED_COV_DIR"

# 创建目录
mkdir -p "$REPLAYABLE_QUEUE_DIR"

# 提取文件
echo "Extracting files..."
count=0

# 遍历压缩文件 (支持 .tar.gz 和 .tar.xz)
# 为了确保在没找到文件时不报错，使用 nullglob (bash特性) 或者简单的检查
shopt -s nullglob
files=("$DATA_DIR"/*.tar.gz "$DATA_DIR"/*.tar.xz)
shopt -u nullglob

if [ ${#files[@]} -eq 0 ]; then
    echo "No compressed files found in $DATA_DIR"
    exit 1
fi

for file in "${files[@]}"; do
    if [ -f "$file" ]; then
        echo "Processing $file..."
        filename=$(basename "$file")
        
        # 创建临时目录
        TEMP_EXTRACT_DIR="$DATA_DIR/temp_extract_$count"
        mkdir -p "$TEMP_EXTRACT_DIR"
        
        # 提取文件
        # 尝试查找并提取 replayable-queue 目录
        if tar -tf "$file" | grep -q "replayable-queue"; then
             tar -xf "$file" -C "$TEMP_EXTRACT_DIR"
             
             # 找到提取出的 replayable-queue 目录 (处理可能的嵌套结构)
             FOUND_QUEUE=$(find "$TEMP_EXTRACT_DIR" -type d -name "replayable-queue" | head -1)
             
             if [ -n "$FOUND_QUEUE" ]; then
                 echo "Found queue at $FOUND_QUEUE"
                 # 直接复制到 REPLAYABLE_QUEUE_DIR (忽略文件名冲突覆盖)
                 echo "Copying to $REPLAYABLE_QUEUE_DIR..."
                 cp "$FOUND_QUEUE"/* "$REPLAYABLE_QUEUE_DIR/"
             else
                 echo "Warning: No replayable-queue directory found in $file"
             fi
        else
             echo "Warning: replayable-queue not found in archive $file"
        fi
        
        # 清理临时目录
        rm -rf "$TEMP_EXTRACT_DIR"
        
        count=$((count + 1))
    fi
done

echo "Extraction completed. Extracted files count: $(ls "$REPLAYABLE_QUEUE_DIR" | wc -l)"

# 生成覆盖率
TEST_OUTPUTS="$MERGED_COV_DIR"
DOCKER_CMD=""

case $TEST_OBJECT in
    exim)
        DOCKER_CMD="docker run --rm -v \"$TEST_OUTPUTS\":/home/ubuntu/input/ --entrypoint /bin/bash exim:latest -c \"cd /home/ubuntu/experiments/exim-gcov && cp ./src/build-Linux-x86_64/exim /usr/exim/bin/exim && cov_script /home/ubuntu/input/ 25 30 /home/ubuntu/input/cov_over_time.csv 1\""
        ;;
    live555)
        DOCKER_CMD="docker run --rm -v \"$TEST_OUTPUTS\":/home/ubuntu/input/ --entrypoint /bin/bash live555:profuzzbench -c \"cd /home/ubuntu/experiments/live555-cov/testProgs/ && cov_script /home/ubuntu/input/ 8554 30 /home/ubuntu/input/cov_over_time.csv 1\""
        ;;
    forkeddaapd)
        DOCKER_CMD="docker run --rm -v \"$TEST_OUTPUTS\":/home/ubuntu/input/ --entrypoint /bin/bash forked-daapd:latest -c \"sudo /etc/init.d/dbus start && sudo /etc/init.d/avahi-daemon start && sudo /etc/init.d/dbus status && cd /home/ubuntu/experiments/ && cov_script /home/ubuntu/input/ 3689 30 /home/ubuntu/input/cov_over_time.csv 1\""
        ;;
    kamailio)
        DOCKER_CMD="docker run --rm -v \"$TEST_OUTPUTS\":/home/ubuntu/input/ --entrypoint /bin/bash kamailio:latest -c \"cd /home/ubuntu/experiments/ && cov_script /home/ubuntu/input/ 5060 30 /home/ubuntu/input/cov_over_time.csv 1\""
        ;;
    proftpd)
        DOCKER_CMD="docker run --rm -v \"$TEST_OUTPUTS\":/home/ubuntu/input/ --entrypoint /bin/bash proftpd:latest -c \"cd /home/ubuntu/experiments/proftpd-gcov && cov_script /home/ubuntu/input/ 21 30 /home/ubuntu/input/cov_over_time.csv 1\""
        ;;
    pureftpd)
        DOCKER_CMD="docker run --rm -v \"$TEST_OUTPUTS\":/home/ubuntu/input/ --entrypoint /bin/bash pure-ftpd:latest -c \"cd /home/ubuntu/experiments/pure-ftpd-gcov && cov_script /home/ubuntu/input/ 21 30 /home/ubuntu/input/cov_over_time.csv 1\""
        ;;
esac

echo "Executing Docker command for coverage generation..."
echo "$DOCKER_CMD"
eval "$DOCKER_CMD"

# 结果处理
if [ -f "$MERGED_COV_DIR/cov_over_time.csv" ]; then
    mv "$MERGED_COV_DIR/cov_over_time.csv" "$DATA_DIR/cov_over_time.csv"
    echo "Success: Coverage file generated at $DATA_DIR/cov_over_time.csv"
else
    echo "Error: Coverage file not found at $MERGED_COV_DIR/cov_over_time.csv"
fi
