#!/usr/bin/env python3
"""
测试 GLM 模型生成的脚本，模仿 elfuzz synth 命令
"""

import os
import sys
import subprocess
import shutil
from pathlib import Path

def main():
    # 设置环境变量
    env = os.environ.copy()
    env["SELECTION_STRATEGY"] = "lattice"
    env["ELFUZZ_FORBIDDEN_MUTATORS"] = ""

    # 设置项目根目录
    project_root = Path(__file__).parent
    preset_dir = project_root / "preset" / "jsoncpp"
    initial_variants_dir = preset_dir / "initial" / "variants"
    logs_dir = preset_dir / "initial" / "logs"

    # 确保目录存在
    initial_variants_dir.mkdir(parents=True, exist_ok=True)
    logs_dir.mkdir(parents=True, exist_ok=True)

    # 设置模型配置
    model_name = "glm-4.5-flash"
    endpoint = "https://open.bigmodel.cn/api/paas/v4/chat/completions"

    print(f"使用模型: {model_name}")
    print(f"端点: {endpoint}")

    # 运行 genvariants_parallel.py 生成变体
    cmd = [
        sys.executable,
        str(project_root / "genvariants_parallel.py"),
        "-M", model_name,
        "-O", str(initial_variants_dir),
        "-L", str(logs_dir),
        "-n", "5",
        "-m", "50",
        "-t", "0.1",
        str(preset_dir / "seed_genjson.py")
    ]

    print(f"执行命令: {' '.join(cmd)}")

    try:
        # 设置 ENDPOINTS 环境变量
        env["ENDPOINTS"] = f"{model_name}:{endpoint}"

        # 执行命令
        result = subprocess.run(cmd, env=env, cwd=project_root, check=True, 
                              capture_output=True, text=True)

        print("命令执行成功!")
        print("输出:")
        print(result.stdout)

        # 列出生成的文件
        print("生成的变体文件:")
        for file in initial_variants_dir.glob("*.py"):
            print(f"  {file.name}")

        print("生成的日志文件:")
        for file in logs_dir.glob("*.json"):
            print(f"  {file.name}")

    except subprocess.CalledProcessError as e:
        print(f"命令执行失败，返回码: {e.returncode}")
        print("错误输出:")
        print(e.stderr)
        return 1

    return 0

if __name__ == "__main__":
    sys.exit(main())
