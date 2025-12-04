
import os
import requests
import json

def verify_glm_token():
    # 首先尝试从环境变量获取
    glm_api_key = os.getenv('GLM_API_KEY')

    # 如果环境变量不存在，尝试从配置文件读取
    if not glm_api_key:
        token_paths = [
            os.path.expanduser("~/.config/glm/token"),
            "/home/appuser/.config/glm/token",
        ]

        for token_path in token_paths:
            if os.path.exists(token_path):
                with open(token_path, "r") as f:
                    glm_api_key = f.read().strip()
                break

    if not glm_api_key:
        print("错误: 未找到GLM API密钥")
        print("请通过以下方式之一设置API密钥:")
        print("1. 设置环境变量: set GLM_API_KEY=your_api_key_here")
        print("2. 创建配置文件: ~/.config/glm/token")
        return False

    print(f"找到API密钥: {glm_api_key[:10]}...{glm_api_key[-10:]}")
    print(f"API密钥长度: {len(glm_api_key)} 字符")

    # 尝试使用API密钥进行一个简单的请求
    url = "https://open.bigmodel.cn/api/paas/v4/chat/completions"
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {glm_api_key}"
    }

    # 根据智谱API文档构建请求
    data = {
        "model": "glm-4-flash",  # 使用快速模型进行测试
        "messages": [
            {"role": "user", "content": "请回答: 1+1等于多少?"}
        ],
        "temperature": 0.7,
        "top_p": 0.9,
        "max_tokens": 50
    }

    print("\n正在验证API密钥...")
    print(f"请求URL: {url}")
    print(f"请求模型: {data['model']}")

    try:
        response = requests.post(url, headers=headers, json=data, timeout=30)
        print(f"响应状态码: {response.status_code}")

        if response.status_code == 200:
            print("✓ API密钥验证成功!")
            result = response.json()

            # 提取并显示响应内容
            if "choices" in result and len(result["choices"]) > 0:
                content = result["choices"][0]["message"]["content"]
                print(f"✓ API响应内容: {content}")
            else:
                print("✓ API响应成功，但格式异常:")
                print(json.dumps(result, indent=2, ensure_ascii=False))

            return True
        else:
            print("✗ API请求失败")
            print(f"状态码: {response.status_code}")

            # 尝试解析错误信息
            try:
                error_data = response.json()
                print("错误详情:")
                print(json.dumps(error_data, indent=2, ensure_ascii=False))

                # 根据错误代码提供具体建议
                if "error" in error_data and "code" in error_data["error"]:
                    error_code = error_data["error"]["code"]
                    error_message = error_data["error"]["message"]

                    print(f"\n错误代码: {error_code}")
                    print(f"错误消息: {error_message}")

                    # 根据错误代码提供具体解决方案
                    error_solutions = {
                        "1000": "身份验证失败 - 请检查API密钥是否正确，或重新获取API密钥",
                        "1001": "参数错误 - 请检查请求参数是否符合API文档要求",
                        "1002": "请求频率过高 - 请降低请求频率，添加适当的延迟",
                        "1003": "模型不存在 - 请检查模型名称是否正确",
                        "1004": "余额不足 - 请检查账户余额，或充值后重试",
                        "1005": "内容安全检查失败 - 请检查请求内容是否包含敏感信息",
                        "401": "未授权 - API密钥缺失或无效，请检查密钥设置",
                        "429": "请求过多 - 超出API调用频率限制，请稍后重试"
                    }

                    if str(error_code) in error_solutions:
                        print(f"\n解决方案: {error_solutions[str(error_code)]}")

            except json.JSONDecodeError:
                print(f"原始错误响应: {response.text}")

            return False

    except requests.exceptions.Timeout:
        print("✗ 请求超时 - 可能是网络问题或服务器响应缓慢")
        return False
    except requests.exceptions.ConnectionError:
        print("✗ 连接错误 - 请检查网络连接是否正常")
        return False
    except Exception as e:
        print(f"✗ 请求过程中发生异常: {str(e)}")
        return False

def check_alternative_endpoints():
    """检查可用的智谱API端点"""
    print("\n检查可用的智谱API端点...")

    endpoints = [
        "https://open.bigmodel.cn/api/paas/v4/chat/completions",
        "https://api.chatglm.com/api/paas/v4/chat/completions"
    ]

    for endpoint in endpoints:
        print(f"尝试连接端点: {endpoint}")
        try:
            # 只尝试连接，不发送完整请求
            response = requests.head(endpoint, timeout=5)
            print(f"端点响应状态: {response.status_code}")
        except Exception as e:
            print(f"连接端点失败: {str(e)}")

if __name__ == "__main__":
    print("智谱AI API密钥验证工具")
    print("=" * 50)

    success = verify_glm_token()

    if not success:
        print("\n尝试检查其他可能的API端点...")
        check_alternative_endpoints()

        print("\n如果问题仍然存在，请:")
        print("1. 确认API密钥是否正确")
        print("2. 检查账户余额是否充足")
        print("3. 访问 https://open.bigmodel.cn/ 查看最新API文档")
        print("4. 联系智谱AI技术支持获取帮助")

