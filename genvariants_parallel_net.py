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
        base_delay = 1  # 基础延迟时间（秒）
        timeout = 60    # 超时时间
        response = None

        for attempt in range(max_retries):
            try:
                # 发送请求
                response = requests.post(
                    endpoint,
                    headers=headers,
                    json=data,
                    timeout=timeout
                )

                # 检查响应状态码
                if response.status_code == 200:
                    # 解析响应
                    result = response.json()
                    # 转换为与TGI兼容的格式
                    if "choices" in result and len(result["choices"]) > 0:
                        return {
                            "generated_text": result["choices"][0]["message"]["content"],
                            "details": {
                                "finish_reason": result["choices"][0].get("finish_reason", "unknown")
                            }
                        }
                elif response.status_code == 429:
                    # 遇到429错误，使用指数退避策略
                    delay = min(30, base_delay * (2 ** attempt))  # 指数增长，最多30秒
                    print(f"API并发限制 (429)，等待 {delay} 秒后重试...", file=sys.stderr)
                    time.sleep(delay)
                    if attempt < max_retries - 1:
                        print(f"正在重试 ({attempt + 1}/{max_retries})...", file=sys.stderr)
                        continue
                    else:
                        # 最后一次尝试失败，返回错误信息
                        return {
                            "error": f"GLM API rate limit error after {max_retries} attempts: {response.status_code} - {response.text}"
                        }
                else:
                    print(f"API返回错误状态码: {response.status_code}, 响应内容: {response.text[:100]}...", file=sys.stderr)
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
                    print(f"请求异常: {str(e)}, 等待 {delay} 秒后重试 ({attempt + 1}/{max_retries})...", file=sys.stderr)
                    time.sleep(delay)
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
            print(f"API并发限制错误 (429): {response.text}", file=sys.stderr)

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
