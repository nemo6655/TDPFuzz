import os
import glob
import re
import argparse
import sys

# DAAP (DMAP) and JSON API Commands
KNOWN_DAAP_COMMANDS = {
    # DAAP Protocol (DMAP)
    "SERVER-INFO": b"GET /server-info HTTP/1.1\r\nHost: 127.0.0.1\r\nViewer-Only-Client: 1\r\n\r\n",
    "CONTENT-CODES": b"GET /content-codes HTTP/1.1\r\nHost: 127.0.0.1\r\n\r\n",
    "LOGIN": b"GET /login HTTP/1.1\r\nHost: 127.0.0.1\r\n\r\n",
    "UPDATE": b"GET /update?session-id=1&revision-number=1 HTTP/1.1\r\nHost: 127.0.0.1\r\n\r\n",
    "DATABASES": b"GET /databases?session-id=1&revision-number=1 HTTP/1.1\r\nHost: 127.0.0.1\r\n\r\n",
    "DATABASE-ITEMS": b"GET /databases/1/items?session-id=1&revision-number=1 HTTP/1.1\r\nHost: 127.0.0.1\r\n\r\n",
    "DATABASE-CONTAINERS": b"GET /databases/1/containers?session-id=1&revision-number=1 HTTP/1.1\r\nHost: 127.0.0.1\r\n\r\n",
    "RESOLVE": b"GET /resolve?session-id=1&revision-number=1&path=/ HTTP/1.1\r\nHost: 127.0.0.1\r\n\r\n",
    
    # JSON API (forked-daapd specific)
    "API-CONFIG": b"GET /api/config HTTP/1.1\r\nHost: 127.0.0.1\r\n\r\n",
    "API-LIBRARY": b"GET /api/library/artists HTTP/1.1\r\nHost: 127.0.0.1\r\n\r\n",
    "API-PLAYBACK": b"PUT /api/player/play HTTP/1.1\r\nHost: 127.0.0.1\r\nContent-Length: 0\r\n\r\n",
    "API-QUEUE": b"GET /api/queue HTTP/1.1\r\nHost: 127.0.0.1\r\n\r\n",
    "API-OUTPUTS": b"GET /api/outputs HTTP/1.1\r\nHost: 127.0.0.1\r\n\r\n",
}

# Logical order for DAAP methods to maximize state transitions
DAAP_METHOD_ORDER = [
    "SERVER-INFO", "CONTENT-CODES", "LOGIN", "UPDATE", 
    "DATABASES", "DATABASE-ITEMS", "DATABASE-CONTAINERS", "RESOLVE",
    "API-CONFIG", "API-OUTPUTS", "API-LIBRARY", "API-QUEUE", "API-PLAYBACK",
]

def get_daap_command(payload):
    try:
        # Decode start of payload to find method and path
        first_line = payload.split(b'\n', 1)[0].decode('utf-8', errors='ignore')
        parts = first_line.split(' ')
        if len(parts) >= 2:
            method = parts[0]
            path = parts[1]
            
            # Normalize path for matching
            if path.startswith('/server-info'): return "SERVER-INFO"
            if path.startswith('/content-codes'): return "CONTENT-CODES"
            if path.startswith('/login'): return "LOGIN"
            if path.startswith('/update'): return "UPDATE"
            if path.startswith('/databases') and 'items' in path: return "DATABASE-ITEMS"
            if path.startswith('/databases') and 'containers' in path: return "DATABASE-CONTAINERS"
            if path.startswith('/databases'): return "DATABASES"
            if path.startswith('/resolve'): return "RESOLVE"
            if path.startswith('/logout'): return "LOGOUT"
            
            if path.startswith('/api/config'): return "API-CONFIG"
            if path.startswith('/api/library'): return "API-LIBRARY"
            if path.startswith('/api/player'): return "API-PLAYBACK"
            if path.startswith('/api/queue'): return "API-QUEUE"
            if path.startswith('/api/outputs'): return "API-OUTPUTS"
            
            # Fallback for other API calls
            if path.startswith('/api/'): return "API-OTHER"
            
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

    # Common daap_gen function code
    daap_gen_code =  "def __daap_gen__(rng, f):\n"
    daap_gen_code += "    try:\n"
    daap_gen_code += "        g = globals()\n"
    daap_gen_code += "        funcs = []\n"
    daap_gen_code += "        this_lineno = __daap_gen__.__code__.co_firstlineno\n"
    daap_gen_code += "        for name, obj in g.items():\n"
    daap_gen_code += "            if callable(obj) and hasattr(obj, '__module__') and obj.__module__ == __name__:\n"
    daap_gen_code += "                 if hasattr(obj, '__code__') and obj.__code__.co_firstlineno < this_lineno:\n"
    daap_gen_code += "                     funcs.append(obj)\n"
    daap_gen_code += "        funcs.sort(key=lambda f: f.__code__.co_firstlineno)\n"
    daap_gen_code += "        for i, func in enumerate(funcs):\n"
    daap_gen_code += "            try:\n"
    daap_gen_code += "                f.write(func())\n"
    daap_gen_code += "                # Add separator between requests\n"
    daap_gen_code += "                if i < len(funcs) - 1:\n"
    daap_gen_code += "                    f.write(b'\\r\\n\\r\\n')\n"
    daap_gen_code += "            except Exception:\n"
    daap_gen_code += "                pass\n"
    daap_gen_code += "        # Ensure file ends with newline\n"
    daap_gen_code += "        f.write(b'\\r\\n\\r\\n')\n"
    daap_gen_code += "    except Exception:\n"
    daap_gen_code += "        pass\n"

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
            method = get_daap_command(part)
            if method in KNOWN_DAAP_COMMANDS:
                seen_methods.add(method)
            
            # Function name
            func_name = f"{file_stem}_{req_idx:03d}_{method}"
            # Sanitize function name
            func_name = re.sub(r'[^a-zA-Z0-9_]', '_', func_name)
            
            # Create one-line function
            func_code = f"def {func_name}(): return {repr(part)}"
            
            file_funcs_code.append(func_code)
            
            # Collect for daap_all.py
            all_funcs_code_for_all_py.append(func_code)

        # Generate individual seed python file
        py_filename = f"daap_seeds_{file_stem}.py"
        py_filepath = os.path.join(output_dir, py_filename)
        
        content = "import os\n\n"
        content += "\n".join(file_funcs_code)
        content += "\n\n"
        content += daap_gen_code
        content += "\n"
        content += "def main():\n"
        content += f'    with open("{filename}", "wb") as f:\n'
        content += '        with open("/dev/urandom", "rb") as rng:\n'
        content += '            __daap_gen__(rng, f)\n'
        content += "\nif __name__ == '__main__':\n    main()\n"
        
        with open(py_filepath, "w") as f:
            f.write(content)
        # print(f"Generated {py_filepath}")

    # Generate synthetic seeds for missing methods
    missing_methods = set(KNOWN_DAAP_COMMANDS.keys()) - seen_methods
    if missing_methods:
        print(f"Adding synthetic seeds for missing methods: {missing_methods}")
        synthetic_funcs_code = []
        
        # Sort missing methods based on logical protocol order
        sorted_missing = sorted(list(missing_methods), key=lambda m: DAAP_METHOD_ORDER.index(m) if m in DAAP_METHOD_ORDER else 999)
        
        for method in sorted_missing:
            payload = KNOWN_DAAP_COMMANDS[method]
            # Sanitize method name for function name (replace - with _)
            safe_method = re.sub(r'[^a-zA-Z0-9_]', '_', method)
            func_name = f"synthetic_000_{safe_method}"
            func_code = f"def {func_name}(): return {repr(payload)}"
            synthetic_funcs_code.append(func_code)
            all_funcs_code_for_all_py.append(func_code)
            
        # Generate synthetic python file
        py_filename = "daap_seeds_synthetic.py"
        py_filepath = os.path.join(output_dir, py_filename)
        content = "import os\n\n"
        content += "\n".join(synthetic_funcs_code)
        content += "\n\n"
        content += daap_gen_code
        content += "\n"
        content += "def main():\n"
        content += '    with open("synthetic.raw", "wb") as f:\n'
        content += '        with open("/dev/urandom", "rb") as rng:\n'
        content += '            __daap_gen__(rng, f)\n'
        content += "\nif __name__ == '__main__':\n    main()\n"
        
        with open(py_filepath, "w") as f:
            f.write(content)

    # # Generate daap_all.py
    # daap_all_path = os.path.join(output_dir, "daap_all.py")
    
    # # Generate ordered functions for all known commands
    # all_ordered_funcs = []
    
    # # Use DAAP_METHOD_ORDER + any remaining in KNOWN_DAAP_COMMANDS
    # ordered_methods = list(DAAP_METHOD_ORDER)
    # for cmd in KNOWN_DAAP_COMMANDS:
    #     if cmd not in ordered_methods:
    #         ordered_methods.append(cmd)
            
    # for i, method in enumerate(ordered_methods):
    #     if method in KNOWN_DAAP_COMMANDS:
    #         payload = KNOWN_DAAP_COMMANDS[method]
    #         # Use a prefix to ensure sorting order in __daap_gen__
    #         func_name = f"order_{i:03d}_{method.replace('-', '_')}"
    #         func_code = f"def {func_name}(): return {repr(payload)}"
    #         all_ordered_funcs.append(func_code)

    # content = "import os\n\n"
    # content += "\n".join(all_ordered_funcs)
    # content += "\n\n"
    # content += daap_gen_code
    # content += "\n"
    # content += "def main():\n"
    # content += '    with open("daap_all.raw", "wb") as f:\n'
    # content += '        with open("/dev/urandom", "rb") as rng:\n'
    # content += '            __daap_gen__(rng, f)\n'
    # content += "\nif __name__ == '__main__':\n    main()\n"

    # with open(daap_all_path, "w") as f:
    #     f.write(content)
    # # print(f"Generated {daap_all_path}")

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument('--input_seeds', default='seeds', help='Input seeds directory')
    parser.add_argument('--init_variants', default='initial/variants', help='Output python file directory')
    args = parser.parse_args()
    generate_files(args.input_seeds, args.init_variants)
