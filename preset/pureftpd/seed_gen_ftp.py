import os
import glob
import re
import argparse
import sys

KNOWN_COMMANDS = {
    # Access Control
    "USER": b"USER anonymous",
    "PASS": b"PASS anonymous@",
    "ACCT": b"ACCT account",
    "CWD":  b"CWD /",
    "CDUP": b"CDUP",
    "SMNT": b"SMNT /tmp",
    "QUIT": b"QUIT",
    "REIN": b"REIN",
    # Transfer Parameters
    "PORT": b"PORT 127,0,0,1,4,1",
    "PASV": b"PASV",
    "TYPE": b"TYPE I",
    "STRU": b"STRU F",
    "MODE": b"MODE S",
    # FTP Service
    "RETR": b"RETR file.txt",
    "STOR": b"STOR file.txt",
    "STOU": b"STOU file.txt",
    "APPE": b"APPE file.txt",
    "ALLO": b"ALLO 1024",
    "REST": b"REST 0",
    "RNFR": b"RNFR oldname",
    "RNTO": b"RNTO newname",
    "ABOR": b"ABOR",
    "DELE": b"DELE file.txt",
    "RMD":  b"RMD dir",
    "MKD":  b"MKD dir",
    "PWD":  b"PWD",
    "LIST": b"LIST",
    "NLST": b"NLST",
    "SITE": b"SITE HELP",
    "SYST": b"SYST",
    "STAT": b"STAT",
    "HELP": b"HELP",
    "NOOP": b"NOOP",
    # Extensions
    "FEAT": b"FEAT",
    "OPTS": b"OPTS UTF8 ON",
    "MDTM": b"MDTM 20200101000000 file.txt",
    "SIZE": b"SIZE file.txt",
    "MLST": b"MLST /",
    "MLSD": b"MLSD /",
    # IPv6
    "EPRT": b"EPRT |1|127.0.0.1|1024|",
    "EPSV": b"EPSV",
    # Security
    "AUTH": b"AUTH TLS",
    "PBSZ": b"PBSZ 0",
    "PROT": b"PROT P",
}

# Logical order for FTP methods to maximize state transitions
FTP_METHOD_ORDER = [
    # Authentication
    "USER", "PASS", "ACCT", "AUTH", "PBSZ", "PROT",
    # Negotiation & Settings
    "SYST", "FEAT", "OPTS", "TYPE", "STRU", "MODE",
    # Navigation
    "CWD", "PWD", "CDUP",
    # Connection
    "PORT", "PASV", "EPRT", "EPSV",
    # Listing
    "LIST", "NLST", "MLSD", "MLST",
    # Transfer
    "RETR", "STOR", "APPE", "STOU", "ALLO", "REST",
    # File Ops
    "RNFR", "RNTO", "DELE", "RMD", "MKD", "SIZE", "MDTM",
    # Misc
    "SITE", "HELP", "NOOP", "STAT",
    # Exit
    "QUIT", "ABOR"
]

def get_ftp_method(payload):
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

    # Common ftp_gen function code
    ftp_gen_code =  "def __ftp_gen__(rng, f):\n"
    ftp_gen_code += "    try:\n"
    ftp_gen_code += "        g = globals()\n"
    ftp_gen_code += "        funcs = []\n"
    ftp_gen_code += "        this_lineno = __ftp_gen__.__code__.co_firstlineno\n"
    ftp_gen_code += "        for name, obj in g.items():\n"
    ftp_gen_code += "            if callable(obj) and hasattr(obj, '__module__') and obj.__module__ == __name__:\n"
    ftp_gen_code += "                 if hasattr(obj, '__code__') and obj.__code__.co_firstlineno < this_lineno:\n"
    ftp_gen_code += "                     funcs.append(obj)\n"
    ftp_gen_code += "        funcs.sort(key=lambda f: f.__code__.co_firstlineno)\n"
    ftp_gen_code += "        for i, func in enumerate(funcs):\n"
    ftp_gen_code += "            try:\n"
    ftp_gen_code += "                f.write(func())\n"
    ftp_gen_code += "                # Add separator between requests\n"
    ftp_gen_code += "                if i < len(funcs) - 1:\n"
    ftp_gen_code += "                    f.write(b'\\r\\n')\n"
    ftp_gen_code += "            except Exception:\n"
    ftp_gen_code += "                pass\n"
    ftp_gen_code += "        # Ensure file ends with newline\n"
    ftp_gen_code += "        f.write(b'\\r\\n')\n"
    ftp_gen_code += "    except Exception:\n"
    ftp_gen_code += "        pass\n"

    for file_idx, raw_name in enumerate(raw_files):
        filename = raw_name
        file_stem = os.path.splitext(filename)[0]
        raw_file = os.path.join(seeds_dir, filename)

        with open(raw_file, "rb") as f:
            content = f.read()
        
        # Split by newline (handling \r\n or \n)
        parts = re.split(b'(?:\r?\n)+', content.strip())
        parts = [p for p in parts if p.strip()]
        
        file_funcs_code = []

        for req_idx, part in enumerate(parts):
            method = get_ftp_method(part)
            seen_methods.add(method)
            
            # Function name
            func_name = f"{file_stem}_{req_idx:03d}_{method}"
            # Sanitize function name
            func_name = re.sub(r'[^a-zA-Z0-9_]', '_', func_name)
            
            # Create one-line function
            func_code = f"def {func_name}(): return {repr(part)}"
            
            file_funcs_code.append(func_code)
            
            # Collect for ftp_all.py
            all_funcs_code_for_all_py.append(func_code)

        # Generate individual seed python file
        py_filename = f"ftp_seeds_{file_stem}.py"
        py_filepath = os.path.join(output_dir, py_filename)
        
        content = "import os\n\n"
        content += "\n".join(file_funcs_code)
        content += "\n\n"
        content += ftp_gen_code
        content += "\n"
        content += "def main():\n"
        content += f'    with open("{filename}", "wb") as f:\n'
        content += '        with open("/dev/urandom", "rb") as rng:\n'
        content += '            __ftp_gen__(rng, f)\n'
        content += "\nif __name__ == '__main__':\n    main()\n"
        
        with open(py_filepath, "w") as f:
            f.write(content)
        # print(f"Generated {py_filepath}")

    # Generate synthetic seeds for missing methods
    missing_methods = set(KNOWN_COMMANDS.keys()) - seen_methods
    if missing_methods:
        print(f"Adding synthetic seeds for missing methods: {missing_methods}")
        synthetic_funcs_code = []
        
        # Sort missing methods based on logical protocol order
        sorted_missing = sorted(list(missing_methods), key=lambda m: FTP_METHOD_ORDER.index(m) if m in FTP_METHOD_ORDER else 999)
        
        for method in sorted_missing:
            payload = KNOWN_COMMANDS[method]
            func_name = f"synthetic_000_{method}"
            func_code = f"def {func_name}(): return {repr(payload)}"
            synthetic_funcs_code.append(func_code)
            all_funcs_code_for_all_py.append(func_code)
            
        # Generate synthetic python file
        py_filename = "ftp_seeds_synthetic.py"
        py_filepath = os.path.join(output_dir, py_filename)
        content = "import os\n\n"
        content += "\n".join(synthetic_funcs_code)
        content += "\n\n"
        content += ftp_gen_code
        content += "\n"
        content += "def main():\n"
        content += '    with open("synthetic.raw", "wb") as f:\n'
        content += '        with open("/dev/urandom", "rb") as rng:\n'
        content += '            __ftp_gen__(rng, f)\n'
        content += "\nif __name__ == '__main__':\n    main()\n"
        
        with open(py_filepath, "w") as f:
            f.write(content)

    # Generate ftp_all.py
    ftp_all_path = os.path.join(output_dir, "ftp_all.py")
    
    # Generate ordered functions for all known commands
    all_ordered_funcs = []
    
    # Use FTP_METHOD_ORDER + any remaining in KNOWN_COMMANDS
    ordered_methods = list(FTP_METHOD_ORDER)
    for cmd in KNOWN_COMMANDS:
        if cmd not in ordered_methods:
            ordered_methods.append(cmd)
            
    for i, method in enumerate(ordered_methods):
        if method in KNOWN_COMMANDS:
            payload = KNOWN_COMMANDS[method]
            # Use a prefix to ensure sorting order in __ftp_gen__
            func_name = f"order_{i:03d}_{method}"
            func_code = f"def {func_name}(): return {repr(payload)}"
            all_ordered_funcs.append(func_code)

    content = "import os\n\n"
    content += "\n".join(all_ordered_funcs)
    content += "\n\n"
    content += ftp_gen_code
    content += "\n"
    content += "def main():\n"
    content += '    with open("ftp_all.raw", "wb") as f:\n'
    content += '        with open("/dev/urandom", "rb") as rng:\n'
    content += '            __ftp_gen__(rng, f)\n'
    content += "\nif __name__ == '__main__':\n    main()\n"

    with open(ftp_all_path, "w") as f:
        f.write(content)
    # print(f"Generated {ftp_all_path}")

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument('--input_seeds', default='seeds', help='Input seeds directory')
    parser.add_argument('--init_variants', default='initial/variants', help='Output python file directory')
    args = parser.parse_args()
    generate_files(args.input_seeds, args.init_variants)
