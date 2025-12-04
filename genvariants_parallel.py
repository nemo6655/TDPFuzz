#!/usr/bin/env python3

import json
import random
import os
from typing import List, Optional, Dict
from argparse import ArgumentParser
import requests
from concurrent.futures import ThreadPoolExecutor, as_completed

def get_endpoints() -> Dict[str, str]:
    result = dict()
    # Try to get endpoints from environment variable first
    endpoints_env = os.getenv('ENDPOINTS')
    if endpoints_env:
        endpoint_list = endpoints_env.split(' ') # type: ignore
        for endpoint_pair in endpoint_list:
            (model, endpoint) = endpoint_pair.split(':', 1)
            result[model] = endpoint
        return result
    
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
    return requests.post(f'{endpoint}/generate', json=data).json()

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
    # 首先尝试从环境变量获取
    glm_api_key = os.getenv('GLM_API_KEY')

    # 如果环境变量不存在，尝试从配置文件读取，与Hugging Face token的处理方式一致
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

    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {glm_api_key}"
    }

    data = {
        "model": model_name,
        "messages": [
            {"role": "user", "content": prompt}
        ],
        "temperature": temperature,
        "max_tokens": max_new_tokens,
    }

    if stop is not None:
        data["stop"] = stop

    response = requests.post(
        endpoint,
        headers=headers,
        json=data,
        timeout=30
    )

    if response.status_code == 200:
        result = response.json()
        # 转换为与TGI兼容的格式
        if "choices" in result and len(result["choices"]) > 0:
            return {
                "generated_text": result["choices"][0]["message"]["content"],
                "details": {
                    "finish_reason": result["choices"][0].get("finish_reason", "unknown")
                }
            }

    # 如果出错，返回错误信息
    return {
        "error": f"GLM API error: {response.status_code} - {response.text}"
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

infilling_prompt = None

def continue_completion(text: str) -> tuple[str, str]:
    text_lines = text.split('\n')
    # Pick a random line number to cut at
    cut_line = len(text_lines)
    prompt_text = '\n'.join(text_lines[:cut_line])
    real_completion = ''
    return prompt_text, real_completion

def random_completion(text: str, start_line: int = 1) -> tuple[str,str]:
    """Generate a completion of the text starting from a random line.
    Always include at least 1 line to avoid an empty prompt."""
    text_lines = text.split('\n')
    # Pick a random line number to cut at
    cut_line = len(text_lines) - 2 if start_line + 1 >= len(text_lines) - 1 else random.randint(start_line + 1, len(text_lines) - 1)
    prompt_text = '\n'.join(text_lines[:cut_line])
    real_completion = '\n'.join(text_lines[cut_line:])
    return prompt_text, real_completion

def random_fim(text: str, start_line: int = 1) -> tuple[str,str,str]:
    """Fill in the middle of the text with a random completion."""
    text_lines = text.split('\n')
    # Random start and end lines. Make sure we always have at least
    # one line in each section.
    fim_start_line = len(text_lines) - 3 if start_line + 1 >= len(text_lines) - 2 else random.randint(start_line + 1, len(text_lines) - 2)
    fim_end_line = random.randint(fim_start_line + 1, len(text_lines) - 1)
    prefix_text = '\n'.join(text_lines[:fim_start_line]) + '\n'
    suffix_text = '\n'.join(text_lines[fim_end_line:])
    real_middle = '\n'.join(text_lines[fim_start_line:fim_end_line])
    return prefix_text, suffix_text, real_middle

def random_crossover(text1: str, text2: str, start_line: int = 1) -> tuple[str,str]:
    """Generate a splice of two texts."""

    text_lines1 = text1.split('\n')
    text_lines2 = text2.split('\n')

    common_prefix = 0
    for i in range(min(len(text_lines1), len(text_lines2))):
        if text_lines1[i] != text_lines2[i]:
            common_prefix = i - 1
            break
    
    cut_line1 = len(text_lines1) - 2 if start_line + 1 >= len(text_lines1) -1 else random.randint(start_line + 1, len(text_lines1) - 1)

    may_overlap = min(cut_line1 - 1, common_prefix)

    cut_line2_start = max(may_overlap, start_line)
    
    cut_line2 = len(text_lines2) - 2 if cut_line2_start + 1 >= len(text_lines2) - 1 else random.randint(cut_line2_start + 1, len(text_lines2) - 1)
    prefix = '\n'.join(text_lines1[:cut_line1])
    suffix = '\n'.join(text_lines2[cut_line2:])
    return prefix, suffix

# SRCS = [
#     '/home/moyix/git/gifdec/gifdec.c',
# ]
# def random_snippet(text: str, start_line: int = 1) -> [str,str]:
#     """Include commented out code from the parser code."""
#     parser_chunks = open(random.choice(SRCS)).read().split('\n\n')

#     "# NOTE: the corresponding parser code in C is:\n#\n"

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

def generate_variant(i, generators, model, endpoint, filename, args):
    # Pick a random generator
    generator = random.choice(generators)
    if generator == 'infilled':
        prefix, suffix, orig = random_fim(open(filename).read(), args.start_line)
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
        suffix = ''
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
        endpoint,
        model,
        stop=stop,
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
    # Write output to file
    with open(out_path, 'w') as f:
        f.write(prefix)
        f.write(text)
        f.write(suffix)

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

def main():
    global infilling_prompt
    import sys
    from elmconfig import ELMFuzzConfig
    config = ELMFuzzConfig(parents={'genvariants_parallel': make_parser()})
    init_parser(config)
    args = config.parse_args()

    try:
        access_info = on_nsf_access()
        endpoint = args.model.endpoints[args.model_name] if access_info is None else access_info['endpoint']
    except KeyError:
        print(f'WARNING: no endpoint for model {args.model_name}', file=sys.stderr)
        return

    info = model_info(args.model_name, endpoint)
    model = info['model_id']
    if model != args.model_name:
        print(f'WARNING: Expected model {args.model_name}, but {endpoint} is actually {model}', file=sys.stderr)

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
    if not args.no_completion or 'complete' not in forbidden:
        generators += ['complete']
    if not args.no_fim or 'infilled' not in forbidden:
        generators += ['infilled']
    if not args.no_splice or 'lmsplice' not in forbidden:
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
            future = executor.submit(generate_variant, i, generators, model, endpoint, filename, args)
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
    access_info = on_nsf_access()
    if access_info is None:
        endpoints = get_endpoints()
        if endpoints and endpoints.get('codellama/CodeLlama-13b-hf'):
            endpoint = endpoints['codellama/CodeLlama-13b-hf']
        elif endpoints and endpoints.get('glm-4.5-flash'):  # 暂时不考虑不同glm模型兼容
            endpoint = endpoints['glm-4.5-flash']
        else:
            endpoint = endpoints['codellama/CodeLlama-13b-hf']
    else:
        endpoint = access_info['endpoint']
    print(endpoint)
    main()
