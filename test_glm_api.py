#!/usr/bin/env python3

import os
import sys
import requests
import json


def get_glm_token():
    """从配置文件读取 GLM API token"""
    token_path = "/home/appuser/.config/glm/token"
    if not os.path.exists(token_path):
        # 尝试从 Windows 路径读取
        token_path = os.path.expanduser("~/.config/glm/token")

    if not os.path.exists(token_path):
        print("错误: 未找到 GLM API token 配置文件")
        print("请先使用以下命令配置 token:")
        print("elfuzz config --set glm.api_key YOUR_API_KEY_HERE")
        return None

    try:
        with open(token_path, "r") as f:
            token = f.read().strip()
        return token
    except Exception as e:
        print(f"读取 token 时出错: {e}")
        return None


def test_glm_api(token):
    """测试 GLM API 连通性"""
    url = "https://open.bigmodel.cn/api/paas/v4/chat/completions"
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json"
    }

    data = {
        "model": "glm-4.5-flash",
        "messages": [{"role": "user", "content": "你好，请回复一个简单的问候语。"}],
        "temperature": 0.7,
        "max_tokens": 100
    }

    try:
        print("正在测试 GLM-4.5-flash API 连通性...")
        response = requests.post(url, headers=headers, json=data, timeout=10)

        if response.status_code == 200:
            result = response.json()
            if "choices" in result and len(result["choices"]) > 0:
                reply = result["choices"][0]["message"]["content"]
                print("API 调用成功!")
                print(f"模型回复: {reply}")
                return True
            else:
                print("API 调用成功但返回格式异常:")
                print(json.dumps(result, indent=2, ensure_ascii=False))
                return False
        else:
            print(f"API 调用失败，状态码: {response.status_code}")
            print(f"错误信息: {response.text}")
            return False
    except requests.exceptions.RequestException as e:
        print(f"请求异常: {e}")
        return False
    except Exception as e:
        print(f"未知错误: {e}")
        return False


def main():
    print("=== GLM-4.5-Flash API 连通性测试 ===")

    # 获取 token
    token = get_glm_token()
    if not token:
        sys.exit(1)

    # 测试 API
    success = test_glm_api(token)

    if success:
        print("\n✅ 测试通过，GLM-4.5-Flash API 可正常使用")
        sys.exit(0)
    else:
        print("\n❌ 测试失败，请检查配置和网络连接")
        sys.exit(1)


if __name__ == "__main__":
    main()
