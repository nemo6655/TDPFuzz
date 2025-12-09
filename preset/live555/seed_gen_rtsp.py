import os
import glob
import re
import argparse
import sys

KNOWN_RTSP_COMMANDS = {
    "OPTIONS": b"OPTIONS rtsp://127.0.0.1:8554/wavAudioTest RTSP/1.0\r\nCSeq: 1\r\nUser-Agent: ./testRTSPClient (LIVE555 Streaming Media v2018.08.28)\r\n\r\n",
    "DESCRIBE": b"DESCRIBE rtsp://127.0.0.1:8554/wavAudioTest RTSP/1.0\r\nCSeq: 2\r\nUser-Agent: ./testRTSPClient (LIVE555 Streaming Media v2018.08.28)\r\nAccept: application/sdp\r\n\r\n",
    "SETUP": b"SETUP rtsp://127.0.0.1:8554/wavAudioTest/track1 RTSP/1.0\r\nCSeq: 3\r\nUser-Agent: ./testRTSPClient (LIVE555 Streaming Media v2018.08.28)\r\nTransport: RTP/AVP;unicast;client_port=8000-8001\r\n\r\n",
    "PLAY": b"PLAY rtsp://127.0.0.1:8554/wavAudioTest/ RTSP/1.0\r\nCSeq: 4\r\nUser-Agent: ./testRTSPClient (LIVE555 Streaming Media v2018.08.28)\r\nSession: 12345678\r\nRange: npt=0.000-\r\n\r\n",
    "PAUSE": b"PAUSE rtsp://127.0.0.1:8554/wavAudioTest/ RTSP/1.0\r\nCSeq: 5\r\nUser-Agent: ./testRTSPClient (LIVE555 Streaming Media v2018.08.28)\r\nSession: 12345678\r\n\r\n",
    "TEARDOWN": b"TEARDOWN rtsp://127.0.0.1:8554/wavAudioTest/ RTSP/1.0\r\nCSeq: 6\r\nUser-Agent: ./testRTSPClient (LIVE555 Streaming Media v2018.08.28)\r\nSession: 12345678\r\n\r\n",
    "GET_PARAMETER": b"GET_PARAMETER rtsp://127.0.0.1:8554/wavAudioTest/ RTSP/1.0\r\nCSeq: 7\r\nUser-Agent: ./testRTSPClient (LIVE555 Streaming Media v2018.08.28)\r\nSession: 12345678\r\n\r\n",
    "SET_PARAMETER": b"SET_PARAMETER rtsp://127.0.0.1:8554/wavAudioTest/ RTSP/1.0\r\nCSeq: 8\r\nUser-Agent: ./testRTSPClient (LIVE555 Streaming Media v2018.08.28)\r\nSession: 12345678\r\nContent-Length: 20\r\n\r\nparam: value",
    "ANNOUNCE": b"ANNOUNCE rtsp://127.0.0.1:8554/wavAudioTest/ RTSP/1.0\r\nCSeq: 9\r\nUser-Agent: ./testRTSPClient (LIVE555 Streaming Media v2018.08.28)\r\nContent-Type: application/sdp\r\nContent-Length: 20\r\n\r\nv=0\r\no=- 0 0 IN IP4 127.0.0.1\r\ns=No Name\r\nc=IN IP4 127.0.0.1\r\nt=0 0\r\na=tool:libavformat 58.29.100\r\nm=audio 0 RTP/AVP 10\r\nb=AS:128\r\n",
    "RECORD": b"RECORD rtsp://127.0.0.1:8554/wavAudioTest/ RTSP/1.0\r\nCSeq: 10\r\nUser-Agent: ./testRTSPClient (LIVE555 Streaming Media v2018.08.28)\r\nSession: 12345678\r\nRange: npt=0.000-\r\n\r\n",
    "REDIRECT": b"REDIRECT rtsp://127.0.0.1:8554/wavAudioTest/ RTSP/1.0\r\nCSeq: 11\r\nUser-Agent: ./testRTSPClient (LIVE555 Streaming Media v2018.08.28)\r\nLocation: rtsp://127.0.0.1:8554/wavAudioTestNew/\r\n\r\n",
}

# Logical order for RTSP methods to maximize state transitions
RTSP_METHOD_ORDER = [
    "OPTIONS", "DESCRIBE", "ANNOUNCE", "SETUP", "PLAY", "RECORD", "PAUSE",
    "GET_PARAMETER", "SET_PARAMETER", "TEARDOWN", "REDIRECT"
]

def get_rtsp_method(payload):
    try:
        # Decode start of payload to find method
        first_line = payload.split(b'\n', 1)[0]
        method = first_line.split(b' ', 1)[0].decode('utf-8', errors='ignore')
        if method.isupper() and method.isalpha():
            return method
    except:
        pass
    return "UNKNOWN"

def generate_files(seeds_dir, output_dir):
    try:
        if not os.path.exists(seeds_dir):
            os.makedirs(seeds_dir)
        if not os.path.exists(output_dir):
            os.makedirs(output_dir)
    except OSError as e:
        print(f"Error creating directories: {e}", file=sys.stderr)
        sys.exit(1)

    # Ensure we process files in a deterministic order
    # Collect all files (filenames only) under the seeds_dir
    all_entries = sorted(glob.glob(os.path.join(seeds_dir, "*")))
    raw_files = [os.path.basename(p) for p in all_entries if os.path.isfile(p)]
    
    all_funcs_code_for_all_py = []
    all_funcs_names_for_all_py = []
    seen_methods = set()

    # Common rtsp_gen function code
    rtsp_gen_code =  "def __rtsp_gen__(rng, f):\n"
    rtsp_gen_code += "    try:\n"
    rtsp_gen_code += "        g = globals()\n"
    rtsp_gen_code += "        funcs = []\n"
    rtsp_gen_code += "        this_lineno = __rtsp_gen__.__code__.co_firstlineno\n"
    rtsp_gen_code += "        for name, obj in g.items():\n"
    rtsp_gen_code += "            if callable(obj) and hasattr(obj, '__module__') and obj.__module__ == __name__:\n"
    rtsp_gen_code += "                 if hasattr(obj, '__code__') and obj.__code__.co_firstlineno < this_lineno:\n"
    rtsp_gen_code += "                     funcs.append(obj)\n"
    rtsp_gen_code += "        funcs.sort(key=lambda f: f.__code__.co_firstlineno)\n"
    rtsp_gen_code += "        for i, func in enumerate(funcs):\n"
    rtsp_gen_code += "            try:\n"
    rtsp_gen_code += "                f.write(func())\n"
    rtsp_gen_code += "                # Add separator between requests\n"
    rtsp_gen_code += "                if i < len(funcs) - 1:\n"
    rtsp_gen_code += "                    f.write(b'\\r\\n\\r\\n')\n"
    rtsp_gen_code += "            except Exception:\n"
    rtsp_gen_code += "                pass\n"
    rtsp_gen_code += "        # Ensure file ends with newline\n"
    rtsp_gen_code += "        f.write(b'\\r\\n\\r\\n')\n"
    rtsp_gen_code += "    except Exception:\n"
    rtsp_gen_code += "        pass\n"

    for file_idx, raw_name in enumerate(raw_files):
        filename = raw_name
        file_stem = os.path.splitext(filename)[0]
        raw_file = os.path.join(seeds_dir, filename)

        with open(raw_file, "rb") as f:
            content = f.read()
        
        # Split by double newline (handling \r\n\r\n or \n\n)
        parts = re.split(b'(?:\r?\n){2,}', content.strip())
        parts = [p for p in parts if p.strip()]
        
        file_funcs_code = []

        for req_idx, part in enumerate(parts):
            method = get_rtsp_method(part)
            seen_methods.add(method)
            
            # Function name
            func_name = f"{file_stem}_{req_idx:03d}_{method}"
            # Sanitize function name
            func_name = re.sub(r'[^a-zA-Z0-9_]', '_', func_name)
            
            # Create one-line function
            func_code = f"def {func_name}(): return {repr(part)}"
            
            file_funcs_code.append(func_code)
            
            # Collect for rtsp_all.py
            all_funcs_code_for_all_py.append(func_code)

        # Generate individual seed python file
        py_filename = f"rtsp_seeds_{file_stem}.py"
        py_filepath = os.path.join(output_dir, py_filename)
        
        content = "import os\n\n"
        content += "\n".join(file_funcs_code)
        content += "\n\n"
        content += rtsp_gen_code
        content += "\n"
        content += "def main():\n"
        content += f'    with open("{filename}", "wb") as f:\n'
        content += '        with open("/dev/urandom", "rb") as rng:\n'
        content += '            __rtsp_gen__(rng, f)\n'
        content += "\nif __name__ == '__main__':\n    main()\n"
        
        with open(py_filepath, "w") as f:
            f.write(content)
        # print(f"Generated {py_filepath}")

    # Generate synthetic seeds for missing methods
    missing_methods = set(KNOWN_RTSP_COMMANDS.keys()) - seen_methods
    if missing_methods:
        print(f"Adding synthetic seeds for missing methods: {missing_methods}")
        synthetic_funcs_code = []
        
        # Sort missing methods based on logical protocol order
        sorted_missing = sorted(list(missing_methods), key=lambda m: RTSP_METHOD_ORDER.index(m) if m in RTSP_METHOD_ORDER else 999)
        
        for method in sorted_missing:
            payload = KNOWN_RTSP_COMMANDS[method]
            func_name = f"synthetic_000_{method}"
            func_code = f"def {func_name}(): return {repr(payload)}"
            synthetic_funcs_code.append(func_code)
            all_funcs_code_for_all_py.append(func_code)
            
        # Generate synthetic python file
        py_filename = "rtsp_seeds_synthetic.py"
        py_filepath = os.path.join(output_dir, py_filename)
        content = "import os\n\n"
        content += "\n".join(synthetic_funcs_code)
        content += "\n\n"
        content += rtsp_gen_code
        content += "\n"
        content += "def main():\n"
        content += '    with open("synthetic.raw", "wb") as f:\n'
        content += '        with open("/dev/urandom", "rb") as rng:\n'
        content += '            __rtsp_gen__(rng, f)\n'
        content += "\nif __name__ == '__main__':\n    main()\n"
        
        with open(py_filepath, "w") as f:
            f.write(content)

    # Generate rtsp_all.py
    rtsp_all_path = os.path.join(output_dir, "rtsp_all.py")
    
    # Generate ordered functions for all known commands
    all_ordered_funcs = []
    
    # Use RTSP_METHOD_ORDER + any remaining in KNOWN_RTSP_COMMANDS
    ordered_methods = list(RTSP_METHOD_ORDER)
    for cmd in KNOWN_RTSP_COMMANDS:
        if cmd not in ordered_methods:
            ordered_methods.append(cmd)
            
    for i, method in enumerate(ordered_methods):
        if method in KNOWN_RTSP_COMMANDS:
            payload = KNOWN_RTSP_COMMANDS[method]
            # Use a prefix to ensure sorting order in __rtsp_gen__
            func_name = f"order_{i:03d}_{method}"
            func_code = f"def {func_name}(): return {repr(payload)}"
            all_ordered_funcs.append(func_code)

    content = "import os\n\n"
    content += "\n".join(all_ordered_funcs)
    content += "\n\n"
    content += rtsp_gen_code
    content += "\n"
    content += "def main():\n"
    content += '    with open("rtsp_all.raw", "wb") as f:\n'
    content += '        with open("/dev/urandom", "rb") as rng:\n'
    content += '            __rtsp_gen__(rng, f)\n'
    content += "\nif __name__ == '__main__':\n    main()\n"

    with open(rtsp_all_path, "w") as f:
        f.write(content)
    # print(f"Generated {rtsp_all_path}")

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument('--input_seeds', default='seeds', help='Input seeds directory')
    parser.add_argument('--init_variants', default='initial/variants', help='Output python file directory')
    args = parser.parse_args()
    generate_files(args.input_seeds, args.init_variants)
