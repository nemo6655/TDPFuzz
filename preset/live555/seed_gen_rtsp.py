import os
import glob
import re
import argparse
import sys

KNOWN_RTSP_COMMANDS = {
    "OPTIONS": b"OPTIONS rtsp://127.0.0.1:8554/wavAudioTest RTSP/1.0\r\nCSeq: 1\r\nUser-Agent: ./testRTSPClient (LIVE555 Streaming Media v2018.08.28)\r\n\r\n",
    "DESCRIBE": b"DESCRIBE rtsp://127.0.0.1:8554/wavAudioTest RTSP/1.0\r\nCSeq: 2\r\nUser-Agent: ./testRTSPClient (LIVE555 Streaming Media v2018.08.28)\r\nAccept: application/sdp\r\n\r\n",
    "SETUP": b"SETUP rtsp://127.0.0.1:8554/wavAudioTest/track1 RTSP/1.0\r\nCSeq: 3\r\nUser-Agent: ./testRTSPClient (LIVE555 Streaming Media v2018.08.28)\r\nTransport: RTP/AVP;unicast;client_port=37952-37953\r\n\r\n",
    "SETUP_TCP": b"SETUP rtsp://127.0.0.1:8554/wavAudioTest/track1 RTSP/1.0\r\nCSeq: 3\r\nUser-Agent: ./testRTSPClient (LIVE555 Streaming Media v2018.08.28)\r\nTransport: RTP/AVP/TCP;unicast;interleaved=0-1\r\n\r\n",
    "SETUP_MULTICAST": b"SETUP rtsp://127.0.0.1:8554/wavAudioTest/track1 RTSP/1.0\r\nCSeq: 3\r\nUser-Agent: ./testRTSPClient (LIVE555 Streaming Media v2018.08.28)\r\nTransport: RTP/AVP;multicast;ttl=127\r\n\r\n",
    
    # AC3 Audio Test
    "DESCRIBE_AC3": b"DESCRIBE rtsp://127.0.0.1:8554/ac3AudioTest RTSP/1.0\r\nCSeq: 2\r\nUser-Agent: ./testRTSPClient (LIVE555 Streaming Media v2018.08.28)\r\nAccept: application/sdp\r\n\r\n",
    "SETUP_AC3": b"SETUP rtsp://127.0.0.1:8554/ac3AudioTest/track1 RTSP/1.0\r\nCSeq: 3\r\nUser-Agent: ./testRTSPClient (LIVE555 Streaming Media v2018.08.28)\r\nTransport: RTP/AVP;unicast;client_port=37954-37955\r\n\r\n",
    "PLAY_AC3": b"PLAY rtsp://127.0.0.1:8554/ac3AudioTest/ RTSP/1.0\r\nCSeq: 4\r\nUser-Agent: ./testRTSPClient (LIVE555 Streaming Media v2018.08.28)\r\nSession: 000022B8\r\nRange: npt=0.000-\r\n\r\n",
    "TEARDOWN_AC3": b"TEARDOWN rtsp://127.0.0.1:8554/ac3AudioTest/ RTSP/1.0\r\nCSeq: 6\r\nUser-Agent: ./testRTSPClient (LIVE555 Streaming Media v2018.08.28)\r\nSession: 000022B8\r\n\r\n",

    # Matroska File Test
    "DESCRIBE_MKV": b"DESCRIBE rtsp://127.0.0.1:8554/matroskaFileTest RTSP/1.0\r\nCSeq: 2\r\nUser-Agent: ./testRTSPClient (LIVE555 Streaming Media v2018.08.28)\r\nAccept: application/sdp\r\n\r\n",
    "SETUP_MKV": b"SETUP rtsp://127.0.0.1:8554/matroskaFileTest/track1 RTSP/1.0\r\nCSeq: 3\r\nUser-Agent: ./testRTSPClient (LIVE555 Streaming Media v2018.08.28)\r\nTransport: RTP/AVP;unicast;client_port=37956-37957\r\n\r\n",
    "PLAY_MKV": b"PLAY rtsp://127.0.0.1:8554/matroskaFileTest/ RTSP/1.0\r\nCSeq: 4\r\nUser-Agent: ./testRTSPClient (LIVE555 Streaming Media v2018.08.28)\r\nSession: 000022B8\r\nRange: npt=0.000-\r\n\r\n",
    "TEARDOWN_MKV": b"TEARDOWN rtsp://127.0.0.1:8554/matroskaFileTest/ RTSP/1.0\r\nCSeq: 6\r\nUser-Agent: ./testRTSPClient (LIVE555 Streaming Media v2018.08.28)\r\nSession: 000022B8\r\n\r\n",

    # WebM File Test
    "DESCRIBE_WEBM": b"DESCRIBE rtsp://127.0.0.1:8554/webmFileTest RTSP/1.0\r\nCSeq: 2\r\nUser-Agent: ./testRTSPClient (LIVE555 Streaming Media v2018.08.28)\r\nAccept: application/sdp\r\n\r\n",
    "SETUP_WEBM": b"SETUP rtsp://127.0.0.1:8554/webmFileTest/track1 RTSP/1.0\r\nCSeq: 3\r\nUser-Agent: ./testRTSPClient (LIVE555 Streaming Media v2018.08.28)\r\nTransport: RTP/AVP;unicast;client_port=37958-37959\r\n\r\n",
    "PLAY_WEBM": b"PLAY rtsp://127.0.0.1:8554/webmFileTest/ RTSP/1.0\r\nCSeq: 4\r\nUser-Agent: ./testRTSPClient (LIVE555 Streaming Media v2018.08.28)\r\nSession: 000022B8\r\nRange: npt=0.000-\r\n\r\n",
    "TEARDOWN_WEBM": b"TEARDOWN rtsp://127.0.0.1:8554/webmFileTest/ RTSP/1.0\r\nCSeq: 6\r\nUser-Agent: ./testRTSPClient (LIVE555 Streaming Media v2018.08.28)\r\nSession: 000022B8\r\n\r\n",

    "PLAY": b"PLAY rtsp://127.0.0.1:8554/wavAudioTest/ RTSP/1.0\r\nCSeq: 4\r\nUser-Agent: ./testRTSPClient (LIVE555 Streaming Media v2018.08.28)\r\nSession: 000022B8\r\nRange: npt=0.000-\r\n\r\n",
    "PLAY_SCALE": b"PLAY rtsp://127.0.0.1:8554/wavAudioTest/ RTSP/1.0\r\nCSeq: 5\r\nUser-Agent: ./testRTSPClient (LIVE555 Streaming Media v2018.08.28)\r\nSession: 000022B8\r\nScale: 2.0\r\n\r\n",
    "PAUSE": b"PAUSE rtsp://127.0.0.1:8554/wavAudioTest/ RTSP/1.0\r\nCSeq: 5\r\nUser-Agent: ./testRTSPClient (LIVE555 Streaming Media v2018.08.28)\r\nSession: 000022B8\r\n\r\n",
    "TEARDOWN": b"TEARDOWN rtsp://127.0.0.1:8554/wavAudioTest/ RTSP/1.0\r\nCSeq: 6\r\nUser-Agent: ./testRTSPClient (LIVE555 Streaming Media v2018.08.28)\r\nSession: 000022B8\r\n\r\n",
    "GET_PARAMETER": b"GET_PARAMETER rtsp://127.0.0.1:8554/wavAudioTest/ RTSP/1.0\r\nCSeq: 7\r\nUser-Agent: ./testRTSPClient (LIVE555 Streaming Media v2018.08.28)\r\nSession: 000022B8\r\n\r\n",
    "SET_PARAMETER": b"SET_PARAMETER rtsp://127.0.0.1:8554/wavAudioTest/ RTSP/1.0\r\nCSeq: 8\r\nUser-Agent: ./testRTSPClient (LIVE555 Streaming Media v2018.08.28)\r\nSession: 000022B8\r\nContent-Type: text/parameters\r\nContent-Length: 12\r\n\r\nparam: value",
    "ANNOUNCE": b"ANNOUNCE rtsp://127.0.0.1:8554/wavAudioTest/ RTSP/1.0\r\nCSeq: 9\r\nUser-Agent: ./testRTSPClient (LIVE555 Streaming Media v2018.08.28)\r\nContent-Type: application/sdp\r\nContent-Length: 20\r\n\r\nv=0\r\no=- 0 0 IN IP4 127.0.0.1\r\ns=No Name\r\nc=IN IP4 127.0.0.1\r\nt=0 0\r\na=tool:libavformat 58.29.100\r\nm=audio 0 RTP/AVP 10\r\nb=AS:128\r\n",
    "RECORD": b"RECORD rtsp://127.0.0.1:8554/wavAudioTest/ RTSP/1.0\r\nCSeq: 10\r\nUser-Agent: ./testRTSPClient (LIVE555 Streaming Media v2018.08.28)\r\nSession: 000022B8\r\nRange: npt=0.000-\r\n\r\n",
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
        py_filename = "rtsp_synthetic.py"
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

    # Generate valid business flow seeds
    RTSP_FLOWS = {
        "play_teardown": ["OPTIONS", "DESCRIBE", "SETUP", "PLAY", "TEARDOWN"],
        "play_tcp": ["OPTIONS", "DESCRIBE", "SETUP_TCP", "PLAY", "TEARDOWN"],
        "play_ac3": ["OPTIONS", "DESCRIBE_AC3", "SETUP_AC3", "PLAY_AC3", "TEARDOWN_AC3"],
        "play_mkv": ["OPTIONS", "DESCRIBE_MKV", "SETUP_MKV", "PLAY_MKV", "TEARDOWN_MKV"],
        "play_webm": ["OPTIONS", "DESCRIBE_WEBM", "SETUP_WEBM", "PLAY_WEBM", "TEARDOWN_WEBM"],
        "pause_play": ["OPTIONS", "DESCRIBE", "SETUP", "PLAY", "PAUSE", "PLAY", "TEARDOWN"],
        "fast_forward": ["OPTIONS", "DESCRIBE", "SETUP", "PLAY", "PLAY_SCALE", "TEARDOWN"],
        "multicast_stream": ["OPTIONS", "DESCRIBE", "SETUP_MULTICAST", "PLAY", "TEARDOWN"],
        "record": ["OPTIONS", "ANNOUNCE", "SETUP", "RECORD", "TEARDOWN"],
        "get_set_param": ["OPTIONS", "DESCRIBE", "SETUP", "GET_PARAMETER", "SET_PARAMETER", "TEARDOWN"],
        "redirect": ["OPTIONS", "DESCRIBE", "REDIRECT"]
    }

    for flow_name, methods in RTSP_FLOWS.items():
        flow_funcs_code = []
        for i, method in enumerate(methods):
            if method in KNOWN_RTSP_COMMANDS:
                payload = KNOWN_RTSP_COMMANDS[method]
                func_name = f"flow_{i:03d}_{method}"
                func_code = f"def {func_name}(): return {repr(payload)}"
                flow_funcs_code.append(func_code)
        
        if not flow_funcs_code:
            continue

        py_filename = f"rtsp_flow_{flow_name}.py"
        py_filepath = os.path.join(output_dir, py_filename)
        
        content = "import os\n\n"
        content += "\n".join(flow_funcs_code)
        content += "\n\n"
        content += rtsp_gen_code
        content += "\n"
        content += "def main():\n"
        content += f'    with open("{flow_name}.raw", "wb") as f:\n'
        content += '        with open("/dev/urandom", "rb") as rng:\n'
        content += '            __rtsp_gen__(rng, f)\n'
        content += "\nif __name__ == '__main__':\n    main()\n"

        with open(py_filepath, "w") as f:
            f.write(content)
        # print(f"Generated {py_filepath}")

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument('--input_seeds', default='seeds', help='Input seeds directory')
    parser.add_argument('--init_variants', default='initial/variants', help='Output python file directory')
    args = parser.parse_args()
    generate_files(args.input_seeds, args.init_variants)
