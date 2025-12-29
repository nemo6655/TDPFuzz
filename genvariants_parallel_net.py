#!/usr/bin/env python3

import json
import random
import os
import sys
import time
import signal
import sys
from typing import List, Optional, Dict
from argparse import ArgumentParser
import requests
from concurrent.futures import ThreadPoolExecutor, as_completed
import autopep8
import textwrap
import re


# 全局变量，用于跟踪中断状态
interrupted = False

# 全局变量用于缓存API密钥，避免重复读取
_cached_glm_api_key = None

def signal_handler(sig, frame):
    """处理Ctrl+C中断信号"""
    global interrupted
    print("\n\n收到中断信号，正在停止程序...", file=sys.stderr)
    interrupted = True


def get_glm_api_key():
    """获取GLM API密钥，使用全局缓存避免重复读取"""
    global _cached_glm_api_key

    # 如果已经缓存，直接返回
    if _cached_glm_api_key:
        return _cached_glm_api_key

    # 首先尝试从环境变量获取
    glm_api_key = os.getenv('GLM_API_KEY')

    # 如果环境变量不存在，尝试从配置文件读取
    if not glm_api_key:
        token_paths = [
            "/home/appuser/.config/glm/token",  # 容器内appuser配置
            os.path.expanduser("~/.config/glm/token"),  # 用户级配置
        ]

        for token_path in token_paths:
            if os.path.exists(token_path):
                with open(token_path, "r") as f:
                    glm_api_key = f.read().strip()
                break

    if not glm_api_key:
        raise ValueError("GLM API Key not found in environment variables or config files")

    # 缓存API密钥
    _cached_glm_api_key = glm_api_key
    return glm_api_key

def get_endpoints() -> Dict[str, str]:
    result = dict()
    # Try to get endpoints from environment variable first
    endpoints_env = os.getenv('ENDPOINTS')
    if endpoints_env:
        endpoint_list = endpoints_env.split(' ')  # type: ignore
        for endpoint_pair in endpoint_list:
            (model, endpoint) = endpoint_pair.split(':', 1)
            result[model] = endpoint
        return result

    # 如果没有环境变量，添加默认的智谱API端点
    result['glm-4.6'] = 'https://open.bigmodel.cn/api/paas/v4/chat/completions'  # 最新模型
    result['glm-4.5-flash'] = 'https://open.bigmodel.cn/api/paas/v4/chat/completions'  # 快速模型
    result['glm-4.5-air'] = 'https://open.bigmodel.cn/api/paas/v4/chat/completions'  # 轻量模型
    result['glm-4-flash'] = 'https://open.bigmodel.cn/api/paas/v4/chat/completions'
    result['glm-4'] = 'https://open.bigmodel.cn/api/paas/v4/chat/completions'
    result['glm-4-air'] = 'https://open.bigmodel.cn/api/paas/v4/chat/completions'
    result['glm-4-airx'] = 'https://open.bigmodel.cn/api/paas/v4/chat/completions'
    result['glm-4-long'] = 'https://open.bigmodel.cn/api/paas/v4/chat/completions'
    result['glm-3-turbo'] = 'https://open.bigmodel.cn/api/paas/v4/chat/completions'

    # If not in environment, try to get from config file
    try:
        import sys
        sys.path.insert(0, '.')
        from elmconfig import ELMFuzzConfig
        import argparse

        # Create a config parser
        config = ELMFuzzConfig(prog='genvariants_parallel')

        # Parse args to get config file
        parser = argparse.ArgumentParser()
        parser.add_argument('--config', type=str, default=None)
        args, _ = parser.parse_known_args()

        if args.config:
            # Load the config file
            conf = config.yaml.load(open(args.config).read())
            if 'model' in conf and 'endpoints' in conf['model']:
                for endpoint_pair in conf['model']['endpoints']:
                    if ':' in endpoint_pair:
                        (model, endpoint) = endpoint_pair.split(':', 1)
                        result[model] = endpoint
    except Exception as e:
        print(f"Warning: Could not load endpoints from config file: {e}", file=sys.stderr)

    return result


def model_info(model_name: str, endpoint: str):
    """Get information about the model."""
    # 检查是否是GLM模型
    if model_name and model_name.startswith('glm'):
        # GLM模型没有/info端点，返回模型名称
        return {'model_id': model_name}
    else:
        # 其他模型使用标准的/info端点
        return requests.get(f'{endpoint}/info').json()

def generate_completion(
        prompt,
        endpoint,
        model_name,
        temperature=0.2,
        max_new_tokens=1200,
        repetition_penalty=1.1,
        stop=None
):
    """Generate a completion of the prompt."""
    if model_name and model_name.startswith('glm'):
        return generate_completion_glm(prompt, endpoint, model_name, temperature, max_new_tokens, repetition_penalty, stop)
    else:
        return generate_completion_tgi(prompt, endpoint, temperature, max_new_tokens, repetition_penalty, stop)


def generate_completion_tgi(
        prompt,
        endpoint,
        temperature=0.2,
        max_new_tokens=1200,
        repetition_penalty=1.1,
        stop=None,
):
    """Generate a completion of the prompt."""
    data = {
        'inputs': prompt,
        'parameters': {
            'temperature': temperature,
            'max_new_tokens': max_new_tokens,
            'do_sample': True,
            'repetition_penalty': repetition_penalty,
            'details': True, # So we get the finish_reason
        },
    }
    if stop is not None:
        data['parameters']['stop'] = stop
    # 增加超时时间
    response = requests.post(f'{endpoint}/generate', json=data, timeout=60)
    return response.json()

def generate_completion_glm(
        prompt,
        endpoint,
        model_name,
        temperature=0.2,
        max_new_tokens=1200,
        repetition_penalty=1.1,
        stop=None
):
    """Generate a completion of the prompt using GLM API."""
    try:
        # 获取API密钥
        glm_api_key = get_glm_api_key()

        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {glm_api_key}"
        }

        # 优化数据结构，减少不必要的字段
        data = {
            "model": model_name,
            "messages": [
                {"role": "user", "content": prompt}
            ],
            "temperature": temperature,
            "max_tokens": max_new_tokens,
        }

        # 只有在必要时才添加stop参数
        if stop is not None:
            data["stop"] = stop

        # 优化重试机制，使用指数退避策略
        max_retries = 3
        base_delay = 2  # 基础延迟时间（秒）
        timeout = 60 * 30    # 超时时间
        response = None

        for attempt in range(max_retries):
            # 检查是否收到中断信号
            global interrupted
            if interrupted:
                print("收到中断信号，停止API请求...", file=sys.stderr)
                return {
                    "error": "Interrupted by user"
                }

            try:
                # 使用自适应超时机制，初始使用60秒超时
                # 初始超时时间设为60秒，给API足够的处理时间
                initial_short_timeout = min(60, timeout)  # 初始60秒超时，但不超过总超时时间

                # 计算最大尝试次数，确保有足够的中断检查点
                # 由于初始超时时间较长，设置较少的尝试次数
                min_attempts = 1  # 至少尝试1次
                max_attempts = max(min_attempts, 2)  # 最多尝试2次

                response = None
                cumulative_time = 0  # 累计已用时间

                for req_attempt in range(max_attempts):
                    # 检查是否收到中断信号
                    if interrupted:
                        print("收到中断信号，停止API请求...", file=sys.stderr)
                        return {
                            "error": "Interrupted by user"
                        }

                    # 直接使用初始超时时间（60秒），不再逐渐增加
                    short_timeout = initial_short_timeout

                    # 确保不超过剩余的总超时时间
                    remaining_time = timeout - cumulative_time
                    short_timeout = min(short_timeout, remaining_time)

                    # 如果剩余时间不足，直接抛出超时异常
                    if cumulative_time >= timeout:
                        raise requests.exceptions.ReadTimeout(f"Request timed out after {timeout} seconds")

                    try:
                        # 在发送请求前添加短暂延迟，避免触发API并发限制
                        time.sleep(0.5)  # 添加500毫秒延迟

                        # 发送请求，使用当前计算的超时时间
                        start_time = time.time()
                        response = requests.post(
                            endpoint,
                            headers=headers,
                            json=data,
                            timeout=short_timeout
                        )
                        break  # 请求成功，跳出循环
                    except requests.exceptions.Timeout:
                        # 记录已用时间
                        request_time = time.time() - start_time
                        cumulative_time += request_time

                        # 打印超时信息，帮助用户了解请求状态
                        print(f"请求超时 ({short_timeout}s)，累计等待时间: {cumulative_time:.1f}s/{timeout}s，正在重试...", file=sys.stderr)

                        # 如果不是最后一次尝试，继续
                        if req_attempt < max_attempts - 1 and cumulative_time < timeout:
                            continue
                        else:
                            # 最后一次尝试或已超过总超时时间，抛出超时异常
                            raise requests.exceptions.ReadTimeout(f"Request timed out after {timeout} seconds")

                # 检查响应状态码
                if response.status_code == 200:
                    # 解析响应
                    result = response.json()
                    # 转换为与TGI兼容的格式
                    if "choices" in result and len(result["choices"]) > 0:
                        # 记录调用成功状态和tokens消耗
                        usage_info = result.get("usage", {})
                        prompt_tokens = usage_info.get("prompt_tokens", 0)
                        completion_tokens = usage_info.get("completion_tokens", 0)
                        total_tokens = usage_info.get("total_tokens", 0)

                        print(f"智谱AI调用成功 - 模型: {model_name}, "
                              f"提示词tokens: {prompt_tokens}, "
                              f"生成tokens: {completion_tokens}, "
                              f"总tokens: {total_tokens}, "
                              f"完成原因: {result['choices'][0].get('finish_reason', 'unknown')}", 
                              flush=True, file=sys.stderr)

                        return {
                            "generated_text": result["choices"][0]["message"]["content"],
                            "details": {
                                "finish_reason": result["choices"][0].get("finish_reason", "unknown"),
                                "prompt_tokens": prompt_tokens,
                                "completion_tokens": completion_tokens,
                                "total_tokens": total_tokens
                            }
                        }
                elif response.status_code == 429:
                    # 遇到429错误，使用指数退避策略
                    delay = min(30, base_delay * (2 ** attempt))  # 指数增长，最多30秒
                    print(f"智谱AI调用失败 - 模型: {model_name}, 状态码: {response.status_code}, 错误: API并发限制 (429)，等待 {delay} 秒后重试...", file=sys.stderr)

                    # 在等待期间检查中断信号
                    for i in range(int(delay)):
                        if interrupted:
                            print("收到中断信号，停止等待重试...", file=sys.stderr)
                            return {
                                "error": "Interrupted by user"
                            }
                        time.sleep(1)
                    if attempt < max_retries - 1:
                        print(f"正在重试 ({attempt + 1}/{max_retries})...", file=sys.stderr)
                        continue
                    else:
                        # 最后一次尝试失败，返回错误信息
                        return {
                            "error": f"GLM API rate limit error after {max_retries} attempts: {response.status_code} - {response.text}"
                        }
                else:
                    print(f"智谱AI调用失败 - 模型: {model_name}, 状态码: {response.status_code}, 响应内容: {response.text[:100]}...", file=sys.stderr)
                    if attempt < max_retries - 1:
                        print(f"正在重试 ({attempt + 1}/{max_retries})...", file=sys.stderr)
                        continue
                    else:
                        # 最后一次尝试失败，返回错误信息
                        return {
                            "error": f"GLM API error after {max_retries} attempts: {response.status_code} - {response.text}"
                        }
            except (requests.exceptions.ReadTimeout, requests.exceptions.ConnectionError, requests.exceptions.RequestException) as e:
                if attempt < max_retries - 1:  # 如果不是最后一次尝试
                    delay = min(30, base_delay * (2 ** attempt))  # 指数退避
                    print(f"智谱AI调用失败 - 模型: {model_name}, 异常: {str(e)}, 等待 {delay} 秒后重试 ({attempt + 1}/{max_retries})...", file=sys.stderr)

                    # 在等待期间检查中断信号
                    for i in range(int(delay)):
                        if interrupted:
                            print("收到中断信号，停止等待重试...", file=sys.stderr)
                            return {
                                "error": "Interrupted by user"
                            }
                        time.sleep(1)
                    continue
                else:
                    # 最后一次尝试失败，返回错误信息
                    return {
                        "error": f"GLM API request failed after {max_retries} attempts: {str(e)}"
                    }

        # 如果所有重试都失败，返回错误信息
        error_msg = f"GLM API error: {response.status_code} - {response.text}"

        # 检查是否是429错误（并发限制）
        if response and response.status_code == 429:
            print(f"智谱AI调用最终失败 - 模型: {model_name}, API并发限制错误 (429): {response.text}", file=sys.stderr)

        return {
            "error": error_msg
        }
    except Exception as e:
        # 捕获所有其他异常
        return {
            "error": f"GLM API call failed: {str(e)}"
        }

def infilling_prompt_llama(
    pre: str,
    suf: str,
) -> str:
    """
    Format an infilling problem for Code Llama.
    If `suffix_first` is set, format in suffix-prefix-middle format.
    """
    return f'<PRE> {pre} <SUF>{suf} <MID>'

def infilling_prompt_qwen(
    pre: str,
    suf: str,
) -> str:
    """
    Format an infilling problem for Qwen.
    """
    return f'<|fim_prefix|>{pre}<|fim_suffix|>{suf}<|fim_middle|>'

def infilling_prompt_starcoder(
    pre: str,
    suf: str,
) -> str:
    """
    Format an infilling problem for StarCoder
    If `suffix_first` is set, format in suffix-prefix-middle format.
    """
    return f'<fim_prefix>{pre}<fim_suffix>{suf}<fim_middle>'

def infilling_prompt_glm(
    pre: str,
    suf: str,
) -> str:
    """
    Format an infilling problem for GLM.
    """
    return f'<|fim_prefix|>{pre}<|fim_suffix|>{suf}<|fim_middle|>'



def get_mutable_limit(text: str) -> int:
    """
    Find the line number where the first function ending with '_gen' is defined.
    Returns the total number of lines if no such function is found.
    """
    lines = text.split('\n')
    for i, line in enumerate(lines):
        # Match 'def function_name_gen(' or 'def function_name_gen ('
        # Updated to match __rtsp_gen__ style as well
        # Also ensure it's not a one-line function like 'def foo(): return bar'
        if re.match(r'^\s*def\s+(?:__)?\w+_gen(?:__)?\s*\(', line) and not re.search(r'\):\s*return', line):
            return i
    return len(lines)

def continue_completion(text: str) -> tuple[str, str]:
    text_lines = text.split('\n')
    limit = get_mutable_limit(text)
    # Pick a random line number to cut at, respecting the limit
    cut_line = limit if limit < len(text_lines) else len(text_lines)
    prompt_text = '\n'.join(text_lines[:cut_line])
    real_completion = ''
    return prompt_text, real_completion

def random_completion(text: str, start_line: int = 1) -> tuple[str,str]:
    """Generate a completion of the text starting from a random line.
    Always include at least 1 line to avoid an empty prompt."""
    text_lines = text.split('\n')
    limit = get_mutable_limit(text)
    
    # Ensure we don't go past the limit
    effective_len = min(len(text_lines), limit)
    
    # Pick a random line number to cut at
    cut_line = effective_len - 2 if start_line + 1 >= effective_len - 1 else random.randint(start_line + 1, effective_len - 1)
    prompt_text = '\n'.join(text_lines[:cut_line])
    # The completion should ideally not include the protected part, but here we just return the rest of the file as "real_completion"
    # However, for generation, we only care about the prompt.
    # If we want to preserve the suffix (protected part), we should handle it in generate_variant
    real_completion = '\n'.join(text_lines[cut_line:])
    return prompt_text, real_completion

def random_fim(text: str, start_line: int = 1) -> tuple[str,str,str]:
    """Fill in the middle of the text with a random completion."""
    text_lines = text.split('\n')
    limit = get_mutable_limit(text)
    
    # Ensure we don't go past the limit
    effective_len = min(len(text_lines), limit)
    
    # Random start and end lines. Make sure we always have at least
    # one line in each section.
    fim_start_line = effective_len - 3 if start_line + 1 >= effective_len - 2 else random.randint(start_line + 1, effective_len - 2)
    fim_end_line = random.randint(fim_start_line + 1, effective_len - 1)
    
    prefix_text = '\n'.join(text_lines[:fim_start_line]) + '\n'
    # Suffix includes the rest of the mutable part AND the protected part
    suffix_text = '\n'.join(text_lines[fim_end_line:])
    real_middle = '\n'.join(text_lines[fim_start_line:fim_end_line])
    return prefix_text, suffix_text, real_middle

def random_crossover(text1: str, text2: str, start_line: int = 1) -> tuple[str,str]:
    """Generate a splice of two texts."""

    text_lines1 = text1.split('\n')
    text_lines2 = text2.split('\n')
    
    limit1 = get_mutable_limit(text1)
    limit2 = get_mutable_limit(text2)
    
    effective_len1 = min(len(text_lines1), limit1)
    effective_len2 = min(len(text_lines2), limit2)

    common_prefix = 0
    for i in range(min(effective_len1, effective_len2)):
        if text_lines1[i] != text_lines2[i]:
            common_prefix = i - 1
            break
    
    cut_line1 = effective_len1 - 2 if start_line + 1 >= effective_len1 -1 else random.randint(start_line + 1, effective_len1 - 1)

    may_overlap = min(cut_line1 - 1, common_prefix)

    cut_line2_start = max(may_overlap, start_line)
    
    cut_line2 = effective_len2 - 2 if cut_line2_start + 1 >= effective_len2 - 1 else random.randint(cut_line2_start + 1, effective_len2 - 1)
    prefix = '\n'.join(text_lines1[:cut_line1])
    # Suffix includes the rest of text2, including any protected part
    suffix = '\n'.join(text_lines2[cut_line2:])
    return prefix, suffix

# SRCS = [
#     '/home/moyix/git/gifdec/gifdec.c',
# ]
# def random_snippet(text: str, start_line: int = 1) -> [str,str]:
#     """Include commented out code from the parser code."""
#     parser_chunks = open(random.choice(SRCS)).read().split('\n\n')

#     "# NOTE: the corresponding parser code in C is:\n#\n"

def clean_markdown(text):
    lines = text.split('\n')
    if lines and lines[0].strip().startswith('```'):
        lines = lines[1:]
    if lines and lines[-1].strip().startswith('```'):
        lines = lines[:-1]
    return '\n'.join(lines)

def fix_unclosed_strings(text):
    quote_char = None
    escaped = False
    for char in text:
        if escaped:
            escaped = False
            continue
        if char == '\\':
            escaped = True
            continue
        if quote_char:
            if char == quote_char:
                quote_char = None
        else:
            if char in '"\'':
                quote_char = char
    
    if quote_char:
        text += quote_char
    return text

def fix_indentation(prefix, text):
    lines = text.split('\n')
    if not lines:
        return text
        
    prefix_lines = prefix.split('\n')
    last_prefix_line = prefix_lines[-1] if prefix_lines else ""
    
    should_indent = last_prefix_line.strip().endswith(':')
    
    # Find first non-empty line to check indentation
    first_non_empty_idx = -1
    for i, line in enumerate(lines):
        if line.strip():
            first_non_empty_idx = i
            break
            
    if first_non_empty_idx == -1:
        return text
        
    first_line = lines[first_non_empty_idx]
    first_line_indent = len(first_line) - len(first_line.lstrip())
    
    if should_indent and first_line_indent == 0:
        return '\n'.join(['    ' + line for line in lines])
    elif not should_indent and first_line_indent > 0:
        return textwrap.dedent(text)
        
    return text

def check_and_fix_balance(text):
    stack = []
    mapping = {')': '(', ']': '[', '}': '{'}
    reverse_mapping = {'(': ')', '[': ']', '{': '}'}
    
    for char in text:
        if char in '([{':
            stack.append(char)
        elif char in ')]}':
            if stack and stack[-1] == mapping[char]:
                stack.pop()
            else:
                pass 
    
    suffix = ""
    while stack:
        opener = stack.pop()
        suffix += reverse_mapping[opener]
    return text + suffix

def new_base(filename: str) -> tuple[str, str]:
    # filename and extension
    base = os.path.basename(filename)
    base, ext = os.path.splitext(base)
    # Get the first occurrence (if any) of ".base_"
    first = base.find('.base_')
    if first == -1:
        return base, ext
    else:
        base = base[:first]
        return base, ext

def generate_variant(i, generators, model, filename, args):
    # Pick a random generator
    generator = random.choice(generators)

    instruction = ""
    # args is actually the config object parsed by ELMFuzzConfig, so it contains all config options
    # protocol_type is a global option, so it should be directly accessible
    if hasattr(args, 'protocol_type') and args.protocol_type != 'none':
        instruction = (
            f"# Context: This is a polished seed file for generating network protocol fuzzing packets for {args.protocol_type}.\n"
            f"# Goal: Analyze the existing {args.protocol_type} protocol request fuzzing functions in the seed file.\n"
            f"# Task: Generate similar protocol fuzzing functions for the {args.protocol_type} protocol.\n"
            f"# Requirements:\n"
            f"# 1. Maintain the same structure, return type, and protocol format.\n"
            f"# 2. Generate diverse requests to cover different protocol states and edge cases.\n"
            f"# 3. Ensure the generated code is syntactically correct Python.\n"
        )

    if generator == 'infilled':
        prefix, suffix, orig = random_fim(open(filename).read(), args.start_line)
        if instruction:
            prefix = instruction + prefix
        prompt = infilling_prompt(prefix, suffix) # type: ignore
        stop = []
    elif generator == 'lmsplice':
        other_files = [f for f in args.files if f != filename]
        if other_files:
            filename2 = random.choice(other_files)
        else:
            filename2 = filename
        prefix, suffix = random_crossover(open(filename).read(), open(filename2).read(), args.start_line)
        orig = ''
        if instruction:
            prefix = instruction + prefix
        prompt = infilling_prompt(prefix, suffix) # type: ignore
        stop = []
    elif generator == 'continue':
        assert False, 'Continue not supported'
        prefix, orig = continue_completion(open(filename).read())
        suffix = ''
        prompt = prefix
        stop = ['\nif', '\nclass', '\nfor', '\nwhile']
    else:
        assert generator == 'complete'
        prefix, orig = random_completion(open(filename).read(), args.start_line)
        # For 'complete', we need to append the protected suffix if it exists
        text_content = open(filename).read()
        limit = get_mutable_limit(text_content)
        text_lines = text_content.split('\n')
        if limit < len(text_lines):
            suffix = '\n'.join(text_lines[limit:])
        else:
            suffix = ''
        
        if instruction:
            prefix = instruction + prefix
        prompt = prefix
        stop = ['\nif', '\nclass', '\nfor', '\nwhile']

    # Prepare metadata up front in case we fail to generate
    # filename and extension
    base, ext = new_base(filename)
    if generator == 'lmsplice':
        base2, _ = new_base(filename2)
    else:
        base2 = base
    # Count lines
    plines = prefix.count('\n')
    slines = suffix.count('\n')
    olines = orig.count('\n')
    # Output filenames
    out_file = f'var_{i:04}.{generator}{ext}'
    out_path = os.path.join(args.output_dir,out_file)
    meta_file = os.path.join(args.log_dir, out_file + '.json')

    res = generate_completion(
        prompt,
        stop=stop,
        endpoint=ENDPOINT,
        model_name=args.model_name,
        **vars(args.gen),
    )
    if 'generated_text' not in res:
        meta = {
            'model': model,
            'prompt': prompt,
            'generator': generator,
            'prompt_lines': plines,
            'orig_lines': olines,
            'gen_lines': 0,
            'suffix_lines': slines,
            'finish_reason': 'err',
            'base': [base] + ([base2] if generator == 'lmsplice' else []),
            'response': res,
        }

        # Write (error) metadata to logdir
        with open(meta_file, 'w') as f:
            f.write(json.dumps(meta))

        return None

    # Fix up the generated text
    text = res['generated_text']
    if 'codellama' in model:
        # CodeLlama tokenizer decoding seems slightly broken in TGI,
        # so we need to remove the ' <EOT>' token manually, and trim the
        # stop sequences.
        text = text.replace(' <EOT>', '')
        for stop_seq in stop:
            if text.endswith(stop_seq):
                text = text[:-len(stop_seq)]
    
    # Apply new fixes
    text = clean_markdown(text)
    text = fix_indentation(prefix, text)
    text = fix_unclosed_strings(text)
    
    # Check balance on prefix + text
    full_text = prefix + text
    balanced_full_text = check_and_fix_balance(full_text)
    added_suffix = balanced_full_text[len(full_text):]
    text += added_suffix
    
    gen_lines = text.count('\n')

    # one of [length, eos_token, stop_sequence]
    finish_reason = res['details']['finish_reason']
    finish_reason = {
        'length': 'len',
        'eos_token': 'eos',
        'stop_sequence': 'stp',
    }[finish_reason]
    meta = {
        'model': model,
        'prompt': prompt,
        'generator': generator,
        'prompt_lines': plines,
        'orig_lines': olines,
        'gen_lines': gen_lines,
        'suffix_lines': slines,
        'finish_reason': finish_reason,
        'base': [base] + ([base2] if generator == 'lmsplice' else []),
        'response': res,
    }
    
    mutable_content = prefix + text
    try:
        mutable_content = autopep8.fix_code(mutable_content)
    except Exception:
        pass

    # Ensure separation if suffix exists
    if suffix and not mutable_content.endswith('\n\n'):
        if mutable_content.endswith('\n'):
            mutable_content += '\n'
        else:
            mutable_content += '\n\n'

    full_content = mutable_content + suffix

    # Write output to file
    with open(out_path, 'w') as f:
        f.write(full_content)

    # Write metadata to logdir
    with open(meta_file, 'w') as f:
        f.write(json.dumps(meta))

    return out_path

def make_parser():
    parser = ArgumentParser(
        description='Use a code model to generate variants of a file.'
    )
    parser.add_argument('files', type=str, nargs='+')
    parser.add_argument('-M', '--model_name', type=str, default='codellama/CodeLlama-13b-hf',
                        help='Model to use for generation')
    parser.add_argument('--no-completion', action='store_true',
                        help='Disable the completion mutator')
    parser.add_argument('--no-fim', action='store_true',
                        help='Disable the FIM (infilling) mutator')
    parser.add_argument('--no-splice', action='store_true',
                        help='Disable the splice mutator')
    parser.add_argument('-n', '--num_variants', type=int, default=1,
                        help='Number of variants to generate for each seed')
    parser.add_argument('-O', '--output_dir', type=str, default='.',
                        help='Directory to write variants to')
    parser.add_argument('-L', '--log_dir', type=str, default='logs',
                        help='Directory to write generation metadata to')
    parser.add_argument('-s', '--start_line', type=int, default=0,
                        help='When making random cuts, always start at this line. ' + \
                        'Allows specifying an immutable region not subject to mutation.')
    parser.add_argument('-j', '--jobs', type=int, default=16,
                        help='Number of inference jobs to run in parallel')
    # Generation params
    parser.add_argument('-t', '--gen.temperature', type=float, default=0.2, help='Generation temperature')
    parser.add_argument('-m', '--gen.max-new-tokens', type=int, default=2048, help='Maximum number of tokens to generate')
    parser.add_argument('-r', '--gen.repetition-penalty', type=float, default=1.1, help='Repetition penalty')
    return parser

def init_parser(elm):
    # Add a bit of help text to the generation options
    elm.subgroup_help['gen'] = 'Generation parameters'

def set_endpoint(model_name, access_info):
    if access_info is None:
        endpoints = get_endpoints()

        # 检查用户指定的模型是否在可用端点中
        user_model = model_name
        if endpoints and endpoints.get(user_model):
            # 使用用户指定的模型
            endpoint = endpoints[user_model]
        # 如果用户指定的模型不在端点中，尝试使用CodeLlama模型
        elif endpoints and endpoints.get('codellama/CodeLlama-13b-hf'):
            endpoint = endpoints['codellama/CodeLlama-13b-hf']
        # 如果没有CodeLlama，尝试使用最新的智谱模型glm-4.5-flash
        elif endpoints and endpoints.get('glm-4.5-flash'):
            endpoint = endpoints['glm-4.5-flash']
            # 更新模型名称为智谱模型
            model_name = 'glm-4.5-flash'
        # 如果没有glm-4.5-flash，尝试使用glm-4-flash
        elif endpoints and endpoints.get('glm-4-flash'):
            endpoint = endpoints['glm-4-flash']
            # 更新模型名称为智谱模型
            model_name = 'glm-4-flash'
        # 如果以上都没有，尝试使用其他智谱模型
        elif endpoints and any(key.startswith('glm-') for key in endpoints):
            glm_models = [k for k in endpoints.keys() if k.startswith('glm-')]
            endpoint = endpoints[glm_models[0]]
            # 更新模型名称为智谱模型
            model_name = glm_models[0]
        else:
            # 如果都没有，抛出错误
            raise ValueError("No available model endpoints found. Please configure CodeLlama or GLM model endpoints.")
    else:
        endpoint = access_info['endpoint']
    return model_name, endpoint

def main():
    global ENDPOINT
    global infilling_prompt
    global interrupted
    from elmconfig import ELMFuzzConfig

    # 注册信号处理器，用于处理Ctrl+C
    signal.signal(signal.SIGINT, signal_handler)

    config = ELMFuzzConfig(prog='genvariants_parallel', parents={'genvariants_parallel': make_parser()})
    init_parser(config)
    args = config.parse_args()

    try:
        access_info = on_nsf_access()
        new_model_name, endpoint = set_endpoint(args.model_name, access_info)
        ENDPOINT = endpoint
        args.model_name = new_model_name
    except KeyError:
        print(f'WARNING: no endpoint for model {args.model_name}, using default: {ENDPOINT}', file=sys.stderr)

    info = model_info(args.model_name, ENDPOINT)
    model = info['model_id']
    if model != args.model_name:
        print(f'WARNING: Expected model {args.model_name}, but {ENDPOINT} is actually {model}', file=sys.stderr)

    if model == 'bigcode/starcoder':
        infilling_prompt = infilling_prompt_starcoder
    elif model in ('codellama/CodeLlama-13b-hf',
                   'codellama/CodeLlama-7b-hf'):
        infilling_prompt = infilling_prompt_llama
    elif model.startswith('Qwen/Qwen2.5-Coder'):
        infilling_prompt = infilling_prompt_qwen
    elif model.startswith('glm-'):
        infilling_prompt = infilling_prompt_glm

    if infilling_prompt is None and not args.no_fim:
        config.parser.error(f'Model {model} does not support FIM')
    if args.no_completion and args.no_fim and args.no_splice:
        config.parser.error(f'Nothing to do')

    os.makedirs(args.output_dir, exist_ok=True)
    os.makedirs(args.log_dir, exist_ok=True)

    forbidden = os.environ.get('ELFUZZ_FORBIDDEN_MUTATORS', '').split(',')
    forbidden = [f.strip() for f in forbidden if f.strip()]

    generators = []
    if not args.no_completion and 'complete' not in forbidden:
        generators += ['complete']
    if not args.no_fim and 'infilled' not in forbidden:
        generators += ['infilled']
    if not args.no_splice and 'lmsplice' not in forbidden:
        generators += ['lmsplice']
    # generators += ['continue']

    # Print the number of variants we'll generate so that the next
    # stage (genoutputs) knows how many to expect.
    print(len(args.files) * args.num_variants, flush=True)

    worklist = []
    i = 0
    for _ in range(args.num_variants):
        for filename in args.files:
            worklist.append((i, filename))
            i += 1
    if model.startswith('glm-'):  # 智谱AI单独控制
        # 使用二分法动态调整并发数
        max_jobs = args.jobs  # 初始最大并发数
        min_jobs = 1  # 最小并发数
        current_jobs = max_jobs  # 当前并发数

        # 检查是否有429错误（并发限制）
        def has_rate_limit_error(futures):
            for future in futures:
                try:
                    # 检查任务是否完成
                    if future.done():
                        try:
                            res = future.result()
                            # 检查结果中是否有429错误
                            if isinstance(res, dict) and "error" in res:
                                error_msg = res.get("error", "")
                                # 检查多种可能的错误码
                                if "1302" in error_msg or "1305" in error_msg or "429" in error_msg or "当前API请求过多" in error_msg:
                                    return True
                        except Exception:
                            pass
                except Exception:
                    pass
            return False

        # 尝试使用当前并发数执行任务
        def try_with_jobs(jobs):
            nonlocal worklist, generators, model, endpoint, args
            global interrupted

            print(f"尝试使用并发数: {jobs}", flush=True, file=sys.stderr)
            with ThreadPoolExecutor(max_workers=jobs) as executor:
                futures = []
                for i, filename in worklist:
                    # 检查是否收到中断信号
                    if interrupted:
                        print("收到中断信号，正在停止任务提交...", file=sys.stderr)
                        break
                    future = executor.submit(generate_variant, i, generators, model, filename, args)
                    futures.append(future)

                # 收集所有生成的文件路径
                generated_files = []

                # 统计成功和失败的任务
                success_count = 0
                failure_count = 0
                rate_limit_hit = False

                # 等待部分任务完成以检查是否有429错误
                completed_count = 0
                check_threshold = min(jobs, len(futures))  # 检查至少等于并发数的任务

                # 使用超时机制，定期检查中断信号
                while futures:
                    # 检查是否收到中断信号
                    if interrupted:
                        print("收到中断信号，正在停止任务...", file=sys.stderr)
                        executor.shutdown(wait=False)
                        return generated_files

                    # 使用短超时等待任务完成
                    done_futures = []
                    try:
                        # 等待最多0.1秒，以便定期检查中断信号
                        for future in as_completed(futures, timeout=0.1):
                            done_futures.append(future)
                            break  # 只处理一个任务，然后重新检查中断信号
                    except:
                        # 超时是正常的，继续循环检查中断信号
                        pass

                    # 处理已完成的任务
                    for future in done_futures:
                        futures.remove(future)
                        try:
                            res = future.result()
                            if res is not None:
                                print(res, flush=True)
                                generated_files.append(res)
                                success_count += 1
                            else:
                                failure_count += 1
                        except Exception as e:
                            print(f"处理任务时发生异常: {str(e)}", file=sys.stderr)
                            failure_count += 1

                        completed_count += 1

                        # 检查是否有429错误
                        if has_rate_limit_error(futures):
                            rate_limit_hit = True
                            print(f"检测到API并发限制错误 (429)", file=sys.stderr)
                            break

                        # 如果已经检查了足够多的任务且没有429错误，继续执行
                        if completed_count >= check_threshold and not rate_limit_hit:
                            # 继续等待剩余任务完成
                            continue

                    # 检查是否有429错误
                    if has_rate_limit_error(futures):
                        rate_limit_hit = True
                        print(f"检测到API并发限制错误 (429)", file=sys.stderr)
                        break

                    # 如果已经检查了足够多的任务且没有429错误，继续执行
                    if completed_count >= check_threshold and not rate_limit_hit:
                        # 继续等待剩余任务完成
                        continue

                # 如果没有遇到429错误，等待所有任务完成
                if not rate_limit_hit:
                    for future in futures:
                        # 检查是否收到中断信号
                        if interrupted:
                            print("收到中断信号，正在停止任务...", file=sys.stderr)
                            executor.shutdown(wait=False)
                            return generated_files

                        if not future.done():
                            try:
                                # 使用超时机制，每秒检查一次中断信号
                                while not future.done():
                                    if interrupted:
                                        print("收到中断信号，正在停止任务...", file=sys.stderr)
                                        executor.shutdown(wait=False)
                                        return generated_files
                                    time.sleep(0.1)  # 短暂休眠，避免CPU占用过高

                                # 任务已完成，获取结果
                                res = future.result()
                                if res is not None:
                                    print(res, flush=True)
                                    generated_files.append(res)
                                    success_count += 1
                                else:
                                    failure_count += 1
                            except Exception as e:
                                print(f"处理任务时发生异常: {str(e)}", file=sys.stderr)
                                failure_count += 1

                # 打印统计信息
                print(f"任务完成: 成功 {success_count}, 失败 {failure_count}", flush=True)

                return generated_files

        # 尝试加载之前保存的最佳并发数
        saved_best_jobs = load_best_jobs(model)
        if saved_best_jobs:
            print(f"从配置文件加载到模型 {model} 的最佳并发数: {saved_best_jobs}", flush=True)
            # 如果保存的最佳并发数小于请求的并发数，使用保存的值作为初始值
            if saved_best_jobs < args.jobs:
                best_jobs = saved_best_jobs
            else:
                best_jobs = 1
        else:
            best_jobs = 1  # 初始最佳并发数

        best_efficiency = 0  # 初始最佳效率（成功数/时间）
        best_success = 0  # 初始成功数

        # 测试阶段：逐步增加并发数，找到效率最高的点
        test_jobs = 1
        test_results = {}  # 记录测试结果：{并发数: (成功率, 效率)}

        # 首先测试几个基础点
        # 对于GLM模型，限制最大并发数为1，避免触发API限制
        if model.startswith('glm-'):
            max_concurrent = min(1, args.jobs)
            test_points = [1]
        else:
            max_concurrent = args.jobs
            test_points = [1, 2, 4, 8]

        # 如果有保存的最佳并发数，优先测试它
        if saved_best_jobs and saved_best_jobs <= max_concurrent and saved_best_jobs not in test_points:
            test_points.insert(0, saved_best_jobs)  # 插入到开头，优先测试

        if max_concurrent < max(test_points):
            test_points = [p for p in test_points if p <= max_concurrent]
            if max_concurrent not in test_points:
                test_points.append(max_concurrent)
        else:
            # 如果max_concurrent很大，添加一些中间点
            if max_concurrent > 8:
                test_points.extend([16, min(32, max_concurrent)])
            test_points = sorted(list(set(test_points)))
            test_points = [p for p in test_points if p <= max_concurrent]

        # 测试各个点
        for jobs in test_points:
            # 检查是否收到中断信号
            if interrupted:
                print("收到中断信号，正在停止测试...", file=sys.stderr)
                break

            print(f"测试并发数: {jobs}", flush=True, file=sys.stderr)
            start_time = time.time()
            generated_files = try_with_jobs(jobs)
            elapsed_time = time.time() - start_time

            # 计算成功数
            success_count = len(generated_files)
            failure_count = len(worklist) - success_count

            # 计算效率（成功数/时间）
            efficiency = success_count / elapsed_time if elapsed_time > 0 else 0
            test_results[jobs] = (success_count, efficiency)

            print(f"并发数 {jobs}: 成功 {success_count}, 效率 {efficiency:.2f}/s, 耗时 {elapsed_time:.2f}s", flush=True,
                  file=sys.stderr)

            # 更新最佳值
            if efficiency > best_efficiency:
                best_jobs = jobs
                best_efficiency = efficiency
                best_success = success_count

            # 如果生成的文件数少于工作列表长度，可能遇到了限制
            if success_count < len(worklist):
                print(f"并发数 {jobs} 可能遇到限制，成功生成 {success_count}/{len(worklist)} 个文件", flush=True)
                # 如果当前测试的并发数大于1，尝试更小的并发数
                if jobs > 1:
                    # 添加更小的测试点
                    smaller_points = []
                    for p in range(1, jobs):
                        if p not in test_points:
                            smaller_points.append(p)
                    # 优先测试接近当前并发数的一半的值
                    smaller_points.sort(key=lambda x: abs(x - jobs // 2))
                    # 限制测试点数量
                    if len(smaller_points) > 3:
                        smaller_points = smaller_points[:3]
                    # 添加到测试点列表
                    test_points.extend(smaller_points)
                    # 重新排序测试点
                    test_points = sorted(list(set(test_points)))
                    # 跳过当前测试点，继续测试更小的点
                    continue
                else:
                    # 如果已经是1，无法再降低，直接退出
                    break

        # 如果测试点太少，或者最佳点在边界，进行精细化测试
        if len(test_points) >= 2 and best_jobs not in [min(test_points), max(test_points)]:
            # 在最佳点周围进行精细化测试
            lower_bound = max(1, best_jobs // 2)
            upper_bound = min(max_concurrent, best_jobs * 2)

            # 生成测试点（包括最佳点周围的点）
            fine_test_points = []
            for i in range(lower_bound, upper_bound + 1):
                if i not in test_points:
                    fine_test_points.append(i)

            # 按照与最佳点的距离排序，优先测试接近最佳点的值
            fine_test_points.sort(key=lambda x: abs(x - best_jobs))

            # 限制精细化测试的点数
            if len(fine_test_points) > 5:
                fine_test_points = fine_test_points[:5]

            for jobs in fine_test_points:
                # 检查是否收到中断信号
                if interrupted:
                    print("收到中断信号，正在停止精细化测试...", file=sys.stderr)
                    break

                print(f"精细化测试并发数: {jobs}", flush=True, file=sys.stderr)
                start_time = time.time()
                generated_files = try_with_jobs(jobs)
                elapsed_time = time.time() - start_time

                # 计算成功数
                success_count = len(generated_files)
                failure_count = len(worklist) - success_count

                # 计算效率
                efficiency = success_count / elapsed_time if elapsed_time > 0 else 0
                test_results[jobs] = (success_count, efficiency)

                print(f"并发数 {jobs}: 成功 {success_count}, 效率 {efficiency:.2f}/s, 耗时 {elapsed_time:.2f}s",
                      flush=True, file=sys.stderr)

                # 更新最佳值
                if efficiency > best_efficiency:
                    best_jobs = jobs
                    best_efficiency = efficiency
                    best_success = success_count

                # 如果生成的文件数少于工作列表长度，可能遇到了限制
                if success_count < len(worklist):
                    print(f"并发数 {jobs} 可能遇到限制，成功生成 {success_count}/{len(worklist)} 个文件", flush=True)
                    break

        # 打印所有测试结果
        print("\n所有测试结果:", flush=True)
        for jobs, (success, efficiency) in sorted(test_results.items()):
            print(f"并发数 {jobs}: 成功 {success}, 效率 {efficiency:.2f}/s", flush=True)

        print(
            f"\n最终使用并发数: {best_jobs}，效率 {best_efficiency:.2f}/s，效率 {best_efficiency:.2f}/s，成功生成 {best_success} 个变体",
            flush=True)

        # 保存找到的最佳并发数
        save_best_jobs(model, best_jobs)

        # 使用最佳并发数重新运行所有任务（如果之前的尝试被中断）
        if best_jobs < args.jobs and not interrupted:
            print(f"使用最佳并发数 {best_jobs} 重新运行所有任务", flush=True)
            generated_files = try_with_jobs(best_jobs)
            for file_path in generated_files:
                print(file_path, flush=True)
    else:
        # pbar = tqdm(total=len(worklist), desc='Generating', unit='variant')
        with ThreadPoolExecutor(max_workers=args.jobs) as executor:
            futures = []
            for i, filename in worklist:
                future = executor.submit(generate_variant, i, generators, model, filename, args)
                # future.add_done_callback(lambda _: pbar.update())
                futures.append(future)
            for future in as_completed(futures):
                res = future.result()
                if res is not None:
                    print(res, flush=True)
        # pbar.close()

def save_best_jobs(model: str, best_jobs: int):
    """保存找到的最佳并发数到文件中，以便下次使用"""
    try:
        # 创建配置目录（如果不存在）
        config_dir = os.path.expanduser("~/.config/tdpfuzz")
        os.makedirs(config_dir, exist_ok=True)

        # 配置文件路径
        config_file = os.path.join(config_dir, "best_jobs.json")

        # 读取现有配置（如果存在）
        config = {}
        if os.path.exists(config_file):
            try:
                with open(config_file, 'r') as f:
                    config = json.load(f)
            except (json.JSONDecodeError, IOError):
                config = {}

        # 更新配置
        config[model] = best_jobs

        # 保存配置
        with open(config_file, 'w') as f:
            json.dump(config, f, indent=2)

        print(f"已保存模型 {model} 的最佳并发数 {best_jobs} 到配置文件", flush=True)
    except Exception as e:
        print(f"保存最佳并发数时出错: {str(e)}", file=sys.stderr)

def validate_function_completeness(code: str) -> bool:
    """验证生成的函数是否完整，特别是generate_json函数"""
    try:
        # 检查代码中是否包含generate_json函数定义
        if "def generate_json" not in code:
            return False

        # 检查函数体是否包含基本逻辑
        # 1. 检查是否有WrappedTextWriter的实例化
        if "WrappedTextWriter(output)" not in code:
            return False

        # 2. 检查是否有WrappedTextReader的实例化
        if "WrappedTextReader(rng)" not in code:
            return False

        # 3. 检查是否有基本的JSON输出逻辑
        # 查找write_utf8调用，确保有输出
        if "write_utf8" not in code:
            return False

        # 4. 检查函数是否有结束标记
        # 确保函数有适当的结束
        lines = code.split('')
        in_function = False
        indent_level = 0
        for line in lines:
            stripped = line.strip()
            if stripped.startswith('def generate_json'):
                in_function = True
                indent_level = len(line) - len(line.lstrip())
            elif in_function and stripped and not line.startswith(' ' * (indent_level + 1)) and not stripped.startswith('#'):
                # 函数已经结束
                break

        # 如果没有找到函数结束，认为不完整
        return True
    except Exception as e:
        print(f"验证函数完整性时发生错误: {e}", file=sys.stderr)
        return False

def complete_incomplete_function(code: str) -> Optional[str]:
    """尝试补全不完整的generate_json函数"""
    try:
        # 检查函数是否定义了但没有实现
        if "def generate_json" in code and "return" not in code:
            lines = code.split('')

            # 找到函数定义行
            func_start = -1
            for i, line in enumerate(lines):
                if "def generate_json" in line:
                    func_start = i
                    break

            if func_start >= 0:
                # 检查函数体是否为空或只有注释
                func_lines = lines[func_start+1:]
                has_code = False
                for line in func_lines:
                    stripped = line.strip()
                    if stripped and not stripped.startswith('#'):
                        has_code = True
                        break

                if not has_code:
                    # 添加基本的JSON生成逻辑
                    basic_impl = [
                        "    # 基本的JSON生成逻辑",
                        "    wrapped_output = WrappedTextWriter(output)",
                        "    wrapped_rng = WrappedTextReader(rng)",
                        "    ",
                        "    # 生成一个简单的JSON对象",
                        "    wrapped_output.write_utf8('{\n')",
                        "    ",
                        "    # 随机决定生成对象或数组",
                        "    choice = int(wrapped_rng.read(1)[0]) % 2",
                        "    if choice == 0:",
                        "        # 生成对象",
                        "        wrapped_output.write_utf8('\"key\": \"value\"\n')",
                        "    else:",
                        "        # 生成数组",
                        "        wrapped_output.write_utf8('\"array\": [1, 2, 3]\n')",
                        "    ",
                        "    wrapped_output.write_utf8('}\n')"
                    ]

                    # 替换空函数体
                    new_lines = lines[:func_start+1] + basic_impl
                    return ''.join(new_lines)

        return None
    except Exception as e:
        print(f"补全函数时发生错误: {e}", file=sys.stderr)
        return None

def fix_syntax_errors(code: str, error: SyntaxError) -> Optional[str]:
    """尝试修复常见的Python语法错误，如果无法修复则使用GLM模型进行智能纠错"""
    try:
        # 首先尝试简单的规则修复
        simple_fix = simple_syntax_fix(code, error)
        if simple_fix:
            return simple_fix

        # 如果简单修复失败，尝试使用GLM模型进行智能纠错
        return ai_syntax_fix(code, error)
    except Exception as e:
        print(f"修复语法错误时发生异常: {e}", file=sys.stderr)
        return None

def simple_syntax_fix(code: str, error: SyntaxError) -> Optional[str]:
    """使用规则修复简单的语法错误"""
    try:
        # 获取错误位置
        error_line = error.lineno
        error_offset = error.offset

        lines = code.split('\n')
        if error_line <= len(lines):
            error_line_content = lines[error_line - 1]

            # 修复常见的语法错误
            # 1. 修复多余的右括号
            if "unexpected EOF while parsing" in str(error) and "')" in error_line_content:
                # 检查是否有多余的右括号
                open_parens = error_line_content.count('(')
                close_parens = error_line_content.count(')')
                if close_parens > open_parens:
                    # 移除多余的右括号
                    fixed_line = error_line_content[:error_offset-1] + error_line_content[error_offset:]
                    lines[error_line - 1] = fixed_line.replace('))', ')')
                    return '\n'.join(lines)

            # 2. 修复缩进错误
            if "unexpected indent" in str(error) or "unindent does not match" in str(error):
                # 尝试修复缩进
                fixed_lines = []
                for i, line in enumerate(lines):
                    if i == error_line - 1:
                        # 修复当前行的缩进
                        stripped = line.lstrip()
                        if stripped:
                            # 使用4空格缩进
                            fixed_lines.append('    ' + stripped)
                        else:
                            fixed_lines.append('')
                    else:
                        fixed_lines.append(line)
                return '\n'.join(fixed_lines)

            # 3. 修复未闭合的字符串
            if "EOL while scanning string literal" in str(error):
                # 尝试闭合字符串
                if error_line <= len(lines):
                    line = lines[error_line - 1]
                    if "'" in line and not line.count("'") % 2 == 0:
                        lines[error_line - 1] = line + "'"
                    elif '"' in line and not line.count('"') % 2 == 0:
                        lines[error_line - 1] = line + '"'
                    return '\n'.join(lines)

            # 4. 修复缺失的冒号
            if "expected ':'" in str(error):
                if error_line <= len(lines):
                    line = lines[error_line - 1]
                    # 在行末添加冒号（如果没有）
                    if not line.rstrip().endswith(':'):
                        lines[error_line - 1] = line.rstrip() + ':'
                        return '\n'.join(lines)

        # 如果无法自动修复，返回None
        return None
    except Exception as e:
        print(f"简单语法修复时发生异常: {e}", file=sys.stderr)
        return None

def ai_syntax_fix(code: str, error: SyntaxError) -> Optional[str]:
    """使用GLM模型进行智能语法纠错"""
    try:
        # 获取端点信息
        endpoints = get_endpoints()
        if not endpoints:
            print("无法获取API端点信息，跳过AI语法修复", file=sys.stderr)
            return None

        # 使用可用的GLM模型，优先使用性能更好的模型
        model_name = None
        endpoint = None
        for model in ['glm-4.6', 'glm-4.5-flash', 'glm-4-flash', 'glm-4', 'glm-3-turbo']:
            if model in endpoints:
                model_name = model
                endpoint = endpoints[model]
                break

        if not model_name or not endpoint:
            print("没有可用的GLM模型，跳过AI语法修复", file=sys.stderr)
            return None

        # 构建纠错提示，使用更明确的指令
        error_msg = str(error)
        prompt = f"""请修复以下Python代码中的语法错误。

错误信息: {error_msg}

```python
{code}
```

要求:
1. 只返回修复后的完整代码，不要包含任何解释或其他文本
2. 确保修复后的代码是有效的Python代码，没有语法错误
3. 保持代码的原始功能和逻辑不变，只修复语法问题
4. 不要添加markdown代码块标记（如```python和```）"""

        # 调用GLM API进行语法纠错，使用优化后的参数
        response = generate_completion_glm(
            prompt=prompt,
            endpoint=endpoint,
            model_name=model_name,
            temperature=0.1,  # 使用较低的温度，确保更稳定的输出
            max_new_tokens=2048
        )

        if 'generated_text' in response:
            fixed_code = response['generated_text'].strip()

            # 尝试提取代码块中的代码（以防模型添加了markdown标记）
            if '```python' in fixed_code and '```' in fixed_code:
                try:
                    start = fixed_code.index('```python') + 9
                    end = fixed_code.rindex('```')
                    fixed_code = fixed_code[start:end].strip()
                except Exception:
                    pass

            # 验证修复后的代码语法是否正确
            try:
                compile(fixed_code, '<string>', 'exec')
                print("使用GLM模型成功修复语法错误", file=sys.stderr)
                return fixed_code
            except SyntaxError as e:
                print(f"GLM模型修复后的代码仍有语法错误: {e}", file=sys.stderr)
                # 如果仍然有语法错误，尝试再次修复
                return None
        else:
            print(f"GLM API返回错误: {response}", file=sys.stderr)
            return None

    except Exception as e:
        print(f"AI语法修复时发生异常: {e}", file=sys.stderr)
        return None

def load_best_jobs(model: str) -> Optional[int]:
    """从配置文件中加载模型的最佳并发数"""
    try:
        # 配置文件路径
        config_file = os.path.expanduser("~/.config/tdpfuzz/best_jobs.json")

        # 检查文件是否存在
        if not os.path.exists(config_file):
            return None

        # 读取配置
        with open(config_file, 'r') as f:
            config = json.load(f)

        # 返回模型的最佳并发数（如果存在）
        return config.get(model)
    except Exception as e:
        print(f"加载最佳并发数时出错: {str(e)}", file=sys.stderr)
        return None

def on_nsf_access() -> dict[str, str] | None:
    if not 'ACCESS_INFO' in os.environ:
        return None
    endpoint = os.environ['ACCESS_INFO']
    return {
        'endpoint': endpoint
    }

if __name__ == '__main__':
    # access_info = on_nsf_access()
    # ENDPOINT = get_endpoints()['codellama/CodeLlama-13b-hf'] if access_info is None else access_info['endpoint']
    main()
