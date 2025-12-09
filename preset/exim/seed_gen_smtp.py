import os
import glob
import re
import argparse
import sys

# Standard SMTP Commands (RFC 5321 and extensions)
KNOWN_SMTP_COMMANDS = {
    # Session Initiation
    "HELO": b"HELO localhost\r\n",
    "EHLO": b"EHLO localhost\r\n",
    
    # Authentication & Security
    "AUTH": b"AUTH PLAIN\r\n",
    "STARTTLS": b"STARTTLS\r\n",
    
    # Mail Transaction
    "MAIL": b"MAIL FROM:<sender@example.com>\r\n",
    "RCPT": b"RCPT TO:<recipient@example.com>\r\n",
    "DATA": b"DATA\r\nSubject: Test\r\n\r\nBody\r\n.\r\n",
    "BDAT": b"BDAT 10 LAST\r\nHelloBDAT\r\n",
    
    # Reset & Verify
    "RSET": b"RSET\r\n",
    "VRFY": b"VRFY user\r\n",
    "EXPN": b"EXPN list\r\n",
    
    # Info & Control
    "HELP": b"HELP\r\n",
    "NOOP": b"NOOP\r\n",
    "QUIT": b"QUIT\r\n",
}

# Logical order for SMTP methods to maximize state transitions
SMTP_METHOD_ORDER = [
    "EHLO", "HELO", "STARTTLS", "AUTH",
    "MAIL", "RCPT", "DATA", "BDAT",
    "RSET", "VRFY", "EXPN", "HELP", "NOOP",
    "QUIT"
]

def get_smtp_command(payload):
    try:
        # Decode start of payload to find method
        first_line = payload.split(b'\n', 1)[0]
        # SMTP commands are usually the first word, case-insensitive
        method = first_line.split(b' ', 1)[0].decode('utf-8', errors='ignore').upper().strip()
        
        # Handle MAIL FROM and RCPT TO which might be parsed as MAIL or RCPT
        if method == "MAIL": return "MAIL"
        if method == "RCPT": return "RCPT"
        
        # Check if it's a known command
        if method in KNOWN_SMTP_COMMANDS:
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

    # Common smtp_gen function code
    smtp_gen_code =  "def __smtp_gen__(rng, f):\n"
    smtp_gen_code += "    try:\n"
    smtp_gen_code += "        g = globals()\n"
    smtp_gen_code += "        funcs = []\n"
    smtp_gen_code += "        this_lineno = __smtp_gen__.__code__.co_firstlineno\n"
    smtp_gen_code += "        for name, obj in g.items():\n"
    smtp_gen_code += "            if callable(obj) and hasattr(obj, '__module__') and obj.__module__ == __name__:\n"
    smtp_gen_code += "                 if hasattr(obj, '__code__') and obj.__code__.co_firstlineno < this_lineno:\n"
    smtp_gen_code += "                     funcs.append(obj)\n"
    smtp_gen_code += "        funcs.sort(key=lambda f: f.__code__.co_firstlineno)\n"
    smtp_gen_code += "        for i, func in enumerate(funcs):\n"
    smtp_gen_code += "            try:\n"
    smtp_gen_code += "                f.write(func())\n"
    smtp_gen_code += "                # Add separator between requests\n"
    smtp_gen_code += "                if i < len(funcs) - 1:\n"
    smtp_gen_code += "                    f.write(b'\\r\\n')\n"
    smtp_gen_code += "            except Exception:\n"
    smtp_gen_code += "                pass\n"
    smtp_gen_code += "        # Ensure file ends with newline\n"
    smtp_gen_code += "        f.write(b'\\r\\n')\n"
    smtp_gen_code += "    except Exception:\n"
    smtp_gen_code += "        pass\n"

    for file_idx, raw_name in enumerate(raw_files):
        filename = raw_name
        file_stem = os.path.splitext(filename)[0]
        raw_file = os.path.join(seeds_dir, filename)

        with open(raw_file, "rb") as f:
            content = f.read()
        
        # Split by newline (handling \r\n or \n)
        # SMTP is line based, but some commands like DATA have multi-line payload.
        # For simplicity in initial seeds, we assume commands are separated by newlines
        # or we treat the whole file as a sequence if it's complex.
        # However, the previous logic splits by newlines.
        # If we have DATA command, splitting by newline breaks the body.
        # But for initial seeds analysis, we just want to find the commands.
        # Let's stick to splitting by newline for analysis, but for reproduction
        # we might need to be careful.
        # Actually, the previous scripts split by double newline or single newline depending on protocol.
        # SMTP commands are strictly line based ending in CRLF.
        # But DATA body is terminated by CRLF.CRLF.
        # Let's assume input seeds are simple one-command-per-line or properly separated.
        # We'll split by simple newline for now to identify commands.
        
        parts = re.split(b'(?:\r?\n)+', content.strip())
        parts = [p for p in parts if p.strip()]
        
        file_funcs_code = []

        for req_idx, part in enumerate(parts):
            method = get_smtp_command(part)
            if method in KNOWN_SMTP_COMMANDS:
                seen_methods.add(method)
            
            # Function name
            func_name = f"{file_stem}_{req_idx:03d}_{method}"
            # Sanitize function name
            func_name = re.sub(r'[^a-zA-Z0-9_]', '_', func_name)
            
            # Create one-line function
            return_val = repr(part + b'\r\n')
            func_code = f"def {func_name}(): return {return_val}"
            
            file_funcs_code.append(func_code)
            
            # Collect for smtp_all.py
            all_funcs_code_for_all_py.append(func_code)

        # Generate individual seed python file
        py_filename = f"smtp_seeds_{file_stem}.py"
        py_filepath = os.path.join(output_dir, py_filename)
        
        content = "import os\n\n"
        content += "\n".join(file_funcs_code)
        content += "\n\n"
        content += smtp_gen_code
        content += "\n"
        content += "def main():\n"
        content += f'    with open("{filename}", "wb") as f:\n'
        content += '        with open("/dev/urandom", "rb") as rng:\n'
        content += '            __smtp_gen__(rng, f)\n'
        content += "\nif __name__ == '__main__':\n    main()\n"
        
        with open(py_filepath, "w") as f:
            f.write(content)

    # Generate synthetic seeds for missing methods
    missing_methods = set(KNOWN_SMTP_COMMANDS.keys()) - seen_methods
    if missing_methods:
        print(f"Adding synthetic seeds for missing methods: {missing_methods}")
        synthetic_funcs_code = []
        
        # Sort missing methods based on logical protocol order
        sorted_missing = sorted(list(missing_methods), key=lambda m: SMTP_METHOD_ORDER.index(m) if m in SMTP_METHOD_ORDER else 999)
        
        for method in sorted_missing:
            payload = KNOWN_SMTP_COMMANDS[method]
            # Sanitize method name
            safe_method = re.sub(r'[^a-zA-Z0-9_]', '_', method)
            func_name = f"synthetic_000_{safe_method}"
            func_code = f"def {func_name}(): return {repr(payload)}"
            synthetic_funcs_code.append(func_code)
            all_funcs_code_for_all_py.append(func_code)
            
        # Generate synthetic python file
        py_filename = "smtp_seeds_synthetic.py"
        py_filepath = os.path.join(output_dir, py_filename)
        content = "import os\n\n"
        content += "\n".join(synthetic_funcs_code)
        content += "\n\n"
        content += smtp_gen_code
        content += "\n"
        content += "def main():\n"
        content += '    with open("synthetic.raw", "wb") as f:\n'
        content += '        with open("/dev/urandom", "rb") as rng:\n'
        content += '            __smtp_gen__(rng, f)\n'
        content += "\nif __name__ == '__main__':\n    main()\n"
        
        with open(py_filepath, "w") as f:
            f.write(content)

    # Generate smtp_all.py
    smtp_all_path = os.path.join(output_dir, "smtp_all.py")
    
    # Generate ordered functions for all known commands
    all_ordered_funcs = []
    
    # Use SMTP_METHOD_ORDER + any remaining in KNOWN_SMTP_COMMANDS
    ordered_methods = list(SMTP_METHOD_ORDER)
    for cmd in KNOWN_SMTP_COMMANDS:
        if cmd not in ordered_methods:
            ordered_methods.append(cmd)
            
    for i, method in enumerate(ordered_methods):
        if method in KNOWN_SMTP_COMMANDS:
            payload = KNOWN_SMTP_COMMANDS[method]
            # Use a prefix to ensure sorting order in __smtp_gen__
            func_name = f"order_{i:03d}_{method}"
            func_code = f"def {func_name}(): return {repr(payload)}"
            all_ordered_funcs.append(func_code)

    content = "import os\n\n"
    content += "\n".join(all_ordered_funcs)
    content += "\n\n"
    content += smtp_gen_code
    content += "\n"
    content += "def main():\n"
    content += '    with open("smtp_all.raw", "wb") as f:\n'
    content += '        with open("/dev/urandom", "rb") as rng:\n'
    content += '            __smtp_gen__(rng, f)\n'
    content += "\nif __name__ == '__main__':\n    main()\n"

    with open(smtp_all_path, "w") as f:
        f.write(content)

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument('--input_seeds', default='seeds', help='Input seeds directory')
    parser.add_argument('--init_variants', default='initial/variants', help='Output python file directory')
    args = parser.parse_args()
    generate_files(args.input_seeds, args.init_variants)
