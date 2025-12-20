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
    "AUTH": b"AUTH PLAIN AHVidW50dQB1YnVudHU=\r\n", # \0ubuntu\0ubuntu
    "AUTH_LOGIN": b"AUTH LOGIN\r\n",
    "AUTH_USER_B64": b"dWJ1bnR1\r\n", # ubuntu
    "AUTH_PASS_B64": b"dWJ1bnR1\r\n", # ubuntu
    "STARTTLS": b"STARTTLS\r\n",
    
    # Mail Transaction
    "MAIL": b"MAIL FROM:<ubuntu@ubuntu>\r\n",
    "MAIL_SIZE": b"MAIL FROM:<ubuntu@ubuntu> SIZE=10240\r\n",
    "MAIL_BODY": b"MAIL FROM:<ubuntu@ubuntu> BODY=8BITMIME\r\n",
    "RCPT": b"RCPT TO:<ubuntu@ubuntu>\r\n",
    "RCPT_NOTIFY": b"RCPT TO:<ubuntu@ubuntu> NOTIFY=SUCCESS,FAILURE\r\n",
    "DATA": b"DATA\r\nFrom: ubuntu@ubuntu\r\nTo: ubuntu@ubuntu\r\nSubject: Fuzzing Test\r\nDate: Mon, 20 Dec 2025 10:00:00 +0000\r\nMessage-ID: <1234@ubuntu>\r\nX-Mailer: TDPFuzz\r\n\r\nThis is a test body for fuzzing.\r\nIt has multiple lines.\r\n.\r\n",
    "BDAT": b"BDAT 11 LAST\r\nHelloBDAT\r\n",
    "BDAT_CHUNK": b"BDAT 5\r\nChunk\r\n",
    "BDAT_LAST": b"BDAT 6 LAST\r\nFinish\r\n",
    
    # Pipelining
    "PIPE_MAIL_RCPT": b"MAIL FROM:<ubuntu@ubuntu>\r\nRCPT TO:<ubuntu@ubuntu>\r\n",

    # Reset & Verify
    "RSET": b"RSET\r\n",
    "VRFY": b"VRFY ubuntu\r\n",
    "EXPN": b"EXPN ubuntu\r\n",
    
    # Info & Control
    "HELP": b"HELP\r\n",
    "NOOP": b"NOOP\r\n",
    "ETRN": b"ETRN example.com\r\n",
    "QUIT": b"QUIT\r\n",
}

# Logical order for SMTP methods to maximize state transitions
SMTP_METHOD_ORDER = [
    "EHLO", "HELO", "STARTTLS", "AUTH", "AUTH_LOGIN",
    "MAIL", "MAIL_SIZE", "MAIL_BODY", "PIPE_MAIL_RCPT",
    "RCPT", "RCPT_NOTIFY",
    "DATA", "BDAT", "BDAT_CHUNK", "BDAT_LAST",
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
    smtp_gen_code += "                # No separator between requests for SMTP\n"
    smtp_gen_code += "            except Exception:\n"
    smtp_gen_code += "                pass\n"
    smtp_gen_code += "        # No need for extra newline at end\n"
    smtp_gen_code += "    except Exception:\n"
    smtp_gen_code += "        pass\n"

    for file_idx, raw_name in enumerate(raw_files):
        filename = raw_name
        file_stem = os.path.splitext(filename)[0]
        raw_file = os.path.join(seeds_dir, filename)

        with open(raw_file, "rb") as f:
            content = f.read()
        

        
        # Handle DATA command specially to preserve body
        # Split by CRLF.CRLF first to isolate DATA blocks if possible, but standard seeds might not be formatted perfectly.
        # A robust way is to iterate line by line and detect DATA state.
        
        parts = []
        current_part = b""
        in_data = False
        
        lines = re.split(b'(\r?\n)', content.strip())
        # re.split with capturing group returns delimiters.
        # lines will be [line1, delim1, line2, delim2, ...]
        
        for i in range(0, len(lines), 2):
            line = lines[i]
            delim = lines[i+1] if i+1 < len(lines) else b""
            
            if not line and not delim: continue
            
            full_line = line + delim
            
            if in_data:
                current_part += full_line
                if line.strip() == b".":
                    in_data = False
                    parts.append(current_part)
                    current_part = b""
            else:
                # Check if this line is a DATA command
                cmd = get_smtp_command(line)
                if cmd == "DATA":
                    in_data = True
                    current_part += full_line
                else:
                    # Normal command, add as separate part
                    if current_part:
                        # Should not happen if logic is correct for non-DATA
                        parts.append(current_part)
                        current_part = b""
                    parts.append(full_line)
        
        if current_part:
            parts.append(current_part)

        # Filter empty parts
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
            # Ensure part ends with CRLF if it doesn't (though our split logic preserves delims)
            if not part.endswith(b'\n'):
                part += b'\r\n'
                
            return_val = repr(part)
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
        py_filename = "smtp_synthetic.py"
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

    # Generate valid business flow seeds
    SMTP_FLOWS = {
        "send_mail": ["EHLO", "MAIL", "RCPT", "DATA", "QUIT"],
        "auth_plain_send": ["EHLO", "AUTH", "MAIL", "RCPT", "DATA", "QUIT"],
        "auth_login_send": ["EHLO", "AUTH_LOGIN", "AUTH_USER_B64", "AUTH_PASS_B64", "MAIL", "RCPT", "DATA", "QUIT"],
        "starttls": ["EHLO", "STARTTLS", "EHLO", "QUIT"],
        "verify": ["EHLO", "VRFY", "EXPN", "QUIT"],
        "help_noop": ["EHLO", "HELP", "NOOP", "QUIT"],
        "bdat": ["EHLO", "MAIL", "RCPT", "BDAT", "QUIT"],
        "chunking": ["EHLO", "MAIL", "RCPT", "BDAT_CHUNK", "BDAT_LAST", "QUIT"],
        "pipelining": ["EHLO", "PIPE_MAIL_RCPT", "DATA", "QUIT"],
        "params_test": ["EHLO", "MAIL_SIZE", "RCPT_NOTIFY", "DATA", "QUIT"],
        "reset": ["EHLO", "MAIL", "RSET", "QUIT"],
        "reset_transaction": ["EHLO", "MAIL", "RCPT", "RSET", "MAIL", "RCPT", "DATA", "QUIT"],
        "etrn": ["EHLO", "ETRN", "QUIT"]
    }

    for flow_name, methods in SMTP_FLOWS.items():
        flow_funcs_code = []
        for i, method in enumerate(methods):
            if method in KNOWN_SMTP_COMMANDS:
                payload = KNOWN_SMTP_COMMANDS[method]
                func_name = f"flow_{i:03d}_{method}"
                func_code = f"def {func_name}(): return {repr(payload)}"
                flow_funcs_code.append(func_code)
        
        if not flow_funcs_code:
            continue

        py_filename = f"smtp_flow_{flow_name}.py"
        py_filepath = os.path.join(output_dir, py_filename)
        
        content = "import os\n\n"
        content += "\n".join(flow_funcs_code)
        content += "\n\n"
        content += smtp_gen_code
        content += "\n"
        content += "def main():\n"
        content += f'    with open("{flow_name}.raw", "wb") as f:\n'
        content += '        with open("/dev/urandom", "rb") as rng:\n'
        content += '            __smtp_gen__(rng, f)\n'
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
