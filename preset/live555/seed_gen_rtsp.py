import os
import glob
import re
import argparse
import sys

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
        print(f"Generated {py_filepath}")

    # Generate rtsp_all.py
    rtsp_all_path = os.path.join(output_dir, "rtsp_all.py")
    content = "import os\n\n"
    content += "\n".join(all_funcs_code_for_all_py)
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
