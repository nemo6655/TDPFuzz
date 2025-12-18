import os
import glob
import re
import argparse
import sys

# Standard SIP Methods (RFC 3261 and extensions)
KNOWN_SIP_COMMANDS = {
    "INVITE": b"INVITE sip:33@127.0.0.1:5060 SIP/2.0\r\nVia: SIP/2.0/UDP 127.0.0.1:5061;branch=z9hG4bK-670-1-2\r\nFrom: sipp <sip:30@127.0.0.1>;tag=1\r\nTo: <sip:33@127.0.0.1:5060>\r\nCall-ID: 1-670@127.0.0.1\r\nCSeq: 2 INVITE\r\nContact: sip:30@127.0.0.1:5061\r\nMax-Forwards: 100\r\nContent-Type: application/sdp\r\nContent-Length: 129\r\n\r\nv=0\r\no=user1 53655765 2353687637 IN IP4 127.0.0.1\r\ns=-\r\nc=IN IP4 127.0.0.1\r\nt=0 0\r\nm=audio 6000 RTP/AVP 8\r\na=rtpmap:8 PCMA/8000\r\n",
    "ACK": b"ACK sip:33@127.0.0.1:5068;ob SIP/2.0\r\nVia: SIP/2.0/UDP 127.0.0.1:5061;branch=z9hG4bK-670-1-7\r\nFrom: <sip:30@127.0.0.1>;tag=1\r\nTo: <sip:33@127.0.0.1>;tag=02cV-oIOVhYnZS3wEzeDPLO.u9i61mwV\r\nRoute: <sip:127.0.0.1;lr>\r\nCall-ID: 1-670@127.0.0.1\r\nCSeq: 2 ACK\r\nContact: sip:30@127.0.0.1:5061\r\nMax-Forwards: 100\r\nContent-Length: 0\r\n\r\n",
    "BYE": b"BYE sip:33@127.0.0.1:5068;ob SIP/2.0\r\nVia: SIP/2.0/UDP 127.0.0.1:5061;branch=z9hG4bK-670-1-9\r\nFrom: <sip:30@127.0.0.1>;tag=1\r\nTo: <sip:33@127.0.0.1>;tag=02cV-oIOVhYnZS3wEzeDPLO.u9i61mwV\r\nRoute: <sip:127.0.0.1;lr>\r\nCall-ID: 1-670@127.0.0.1\r\nCSeq: 3 BYE\r\nContact: sip:sipp@127.0.0.1:5061\r\nMax-Forwards: 100\r\nContent-Length: 0\r\n\r\n",
    "CANCEL": b"CANCEL sip:33@127.0.0.1:5060 SIP/2.0\r\nVia: SIP/2.0/UDP 127.0.0.1:5061;branch=z9hG4bK-670-1-2\r\nFrom: sipp <sip:30@127.0.0.1>;tag=1\r\nTo: <sip:33@127.0.0.1:5060>\r\nCall-ID: 1-670@127.0.0.1\r\nCSeq: 2 CANCEL\r\nMax-Forwards: 100\r\nContent-Length: 0\r\n\r\n",
    "REGISTER": b"REGISTER sip:127.0.0.1 SIP/2.0\r\nVia: SIP/2.0/UDP 127.0.0.1:5061;branch=z9hG4bK-670-1-0\r\nFrom: <sip:30@127.0.0.1>;tag=1\r\nTo: <sip:30@127.0.0.1>\r\nCall-ID: 1-670@127.0.0.1\r\nCSeq: 1 REGISTER\r\nContact: sip:30@127.0.0.1:5061\r\nMax-Forwards: 100\r\nExpires: 120\r\nUser-Agent: SIPp/Win32\r\nContent-Length: 0\r\n\r\n",
    "REGISTER_AUTH": b"REGISTER sip:127.0.0.1 SIP/2.0\r\nVia: SIP/2.0/UDP 127.0.0.1:5061;branch=z9hG4bK-670-1-1\r\nFrom: <sip:30@127.0.0.1>;tag=1\r\nTo: <sip:30@127.0.0.1>\r\nCall-ID: 1-670@127.0.0.1\r\nCSeq: 2 REGISTER\r\nContact: sip:30@127.0.0.1:5061\r\nAuthorization: Digest username=\"30\", realm=\"127.0.0.1\", nonce=\"4b4b4b4b\", uri=\"sip:127.0.0.1\", response=\"6629fae49393a05397450978507c4ef1\", algorithm=MD5\r\nMax-Forwards: 100\r\nExpires: 120\r\nUser-Agent: SIPp/Win32\r\nContent-Length: 0\r\n\r\n",
    "OPTIONS": b"OPTIONS sip:33@127.0.0.1:5060 SIP/2.0\r\nVia: SIP/2.0/UDP 127.0.0.1:5061;branch=z9hG4bK-670-1-8\r\nFrom: <sip:30@127.0.0.1>;tag=1\r\nTo: <sip:33@127.0.0.1>\r\nCall-ID: 1-670@127.0.0.1\r\nCSeq: 1 OPTIONS\r\nMax-Forwards: 100\r\nContent-Length: 0\r\n\r\n",
    "INFO": b"INFO sip:33@127.0.0.1:5060 SIP/2.0\r\nVia: SIP/2.0/UDP 127.0.0.1:5061;branch=z9hG4bK-670-1-9\r\nFrom: <sip:30@127.0.0.1>;tag=1\r\nTo: <sip:33@127.0.0.1>;tag=02cV-oIOVhYnZS3wEzeDPLO.u9i61mwV\r\nCall-ID: 1-670@127.0.0.1\r\nCSeq: 3 INFO\r\nMax-Forwards: 100\r\nContent-Type: application/dtmf-relay\r\nContent-Length: 0\r\n\r\n",
    "PRACK": b"PRACK sip:33@127.0.0.1:5060 SIP/2.0\r\nVia: SIP/2.0/UDP 127.0.0.1:5061;branch=z9hG4bK-670-1-10\r\nFrom: <sip:30@127.0.0.1>;tag=1\r\nTo: <sip:33@127.0.0.1>;tag=02cV-oIOVhYnZS3wEzeDPLO.u9i61mwV\r\nCall-ID: 1-670@127.0.0.1\r\nCSeq: 4 PRACK\r\nRAck: 1 1 INVITE\r\nMax-Forwards: 100\r\nContent-Length: 0\r\n\r\n",
    "SUBSCRIBE": b"SUBSCRIBE sip:33@127.0.0.1:5060 SIP/2.0\r\nVia: SIP/2.0/UDP 127.0.0.1:5061;branch=z9hG4bK-670-1-11\r\nFrom: <sip:30@127.0.0.1>;tag=1\r\nTo: <sip:33@127.0.0.1>\r\nCall-ID: 1-670@127.0.0.1\r\nCSeq: 1 SUBSCRIBE\r\nEvent: presence\r\nExpires: 600\r\nContact: <sip:30@127.0.0.1:5061>\r\nMax-Forwards: 100\r\nContent-Length: 0\r\n\r\n",
    "NOTIFY": b"NOTIFY sip:30@127.0.0.1:5061 SIP/2.0\r\nVia: SIP/2.0/UDP 127.0.0.1:5060;branch=z9hG4bK-670-1-12\r\nFrom: <sip:33@127.0.0.1>;tag=2\r\nTo: <sip:30@127.0.0.1>;tag=1\r\nCall-ID: 1-670@127.0.0.1\r\nCSeq: 1 NOTIFY\r\nEvent: presence\r\nSubscription-State: active\r\nMax-Forwards: 100\r\nContent-Type: application/pidf+xml\r\nContent-Length: 0\r\n\r\n",
    "PUBLISH": b"PUBLISH sip:33@127.0.0.1:5060 SIP/2.0\r\nVia: SIP/2.0/UDP 127.0.0.1:5061;branch=z9hG4bK-670-1-13\r\nFrom: <sip:30@127.0.0.1>;tag=1\r\nTo: <sip:33@127.0.0.1>\r\nCall-ID: 1-670@127.0.0.1\r\nCSeq: 1 PUBLISH\r\nEvent: presence\r\nExpires: 600\r\nMax-Forwards: 100\r\nContent-Type: application/pidf+xml\r\nContent-Length: 0\r\n\r\n",
    "MESSAGE": b"MESSAGE sip:30@127.0.0.1:5060 SIP/2.0\r\nVia: SIP/2.0/UDP 127.0.0.1:5061;branch=z9hG4bK-670-1-14\r\nFrom: <sip:30@127.0.0.1>;tag=1\r\nTo: <sip:30@127.0.0.1>\r\nCall-ID: 1-670@127.0.0.1\r\nCSeq: 1 MESSAGE\r\nMax-Forwards: 100\r\nContent-Type: text/plain\r\nContent-Length: 5\r\n\r\nHello",
    "REFER": b"REFER sip:33@127.0.0.1:5060 SIP/2.0\r\nVia: SIP/2.0/UDP 127.0.0.1:5061;branch=z9hG4bK-670-1-15\r\nFrom: <sip:30@127.0.0.1>;tag=1\r\nTo: <sip:33@127.0.0.1>;tag=02cV-oIOVhYnZS3wEzeDPLO.u9i61mwV\r\nCall-ID: 1-670@127.0.0.1\r\nCSeq: 5 REFER\r\nRefer-To: <sip:other@127.0.0.1>\r\nMax-Forwards: 100\r\nContent-Length: 0\r\n\r\n",
    "UPDATE": b"UPDATE sip:33@127.0.0.1:5060 SIP/2.0\r\nVia: SIP/2.0/UDP 127.0.0.1:5061;branch=z9hG4bK-670-1-16\r\nFrom: <sip:30@127.0.0.1>;tag=1\r\nTo: <sip:33@127.0.0.1>;tag=02cV-oIOVhYnZS3wEzeDPLO.u9i61mwV\r\nCall-ID: 1-670@127.0.0.1\r\nCSeq: 6 UPDATE\r\nMax-Forwards: 100\r\nContent-Length: 0\r\n\r\n",
}

# Logical order for SIP methods to maximize state transitions
# 1. Registration & Presence
# 2. Standalone Messages
# 3. Session Setup (INVITE)
# 4. Session Manipulation (ACK, INFO, etc.)
# 5. Session Teardown (BYE)
METHOD_ORDER = [
    "REGISTER", "SUBSCRIBE", "PUBLISH", "NOTIFY", "OPTIONS", "MESSAGE", # Non-session / Setup
    "INVITE", "PRACK", "ACK", "UPDATE", "INFO", "REFER", "CANCEL",      # Active Session
    "BYE"                                                               # Teardown
]

def get_sip_method(payload):
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

    # Common sip_gen function code
    sip_gen_code =  "def __sip_gen__(rng, f):\n"
    sip_gen_code += "    try:\n"
    sip_gen_code += "        g = globals()\n"
    sip_gen_code += "        funcs = []\n"
    sip_gen_code += "        this_lineno = __sip_gen__.__code__.co_firstlineno\n"
    sip_gen_code += "        for name, obj in g.items():\n"
    sip_gen_code += "            if callable(obj) and hasattr(obj, '__module__') and obj.__module__ == __name__:\n"
    sip_gen_code += "                 if hasattr(obj, '__code__') and obj.__code__.co_firstlineno < this_lineno:\n"
    sip_gen_code += "                     funcs.append(obj)\n"
    sip_gen_code += "        funcs.sort(key=lambda f: f.__code__.co_firstlineno)\n"
    sip_gen_code += "        for i, func in enumerate(funcs):\n"
    sip_gen_code += "            try:\n"
    sip_gen_code += "                f.write(func())\n"
    sip_gen_code += "                # Add separator between requests\n"
    sip_gen_code += "                if i < len(funcs) - 1:\n"
    sip_gen_code += "                    f.write(b'\\r\\n\\r\\n')\n"
    sip_gen_code += "            except Exception:\n"
    sip_gen_code += "                pass\n"
    sip_gen_code += "        # Ensure file ends with newline\n"
    sip_gen_code += "        f.write(b'\\r\\n\\r\\n')\n"
    sip_gen_code += "    except Exception:\n"
    sip_gen_code += "        pass\n"

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
            method = get_sip_method(part)
            seen_methods.add(method)
            
            # Function name
            func_name = f"{file_stem}_{req_idx:03d}_{method}"
            # Sanitize function name
            func_name = re.sub(r'[^a-zA-Z0-9_]', '_', func_name)
            
            # Create one-line function
            func_code = f"def {func_name}(): return {repr(part)}"
            
            file_funcs_code.append(func_code)
            
            # Collect for sip_all.py
            all_funcs_code_for_all_py.append(func_code)

        # Generate individual seed python file
        py_filename = f"sip_seeds_{file_stem}.py"
        py_filepath = os.path.join(output_dir, py_filename)
        
        content = "import os\n\n"
        content += "\n".join(file_funcs_code)
        content += "\n\n"
        content += sip_gen_code
        content += "\n"
        content += "def main():\n"
        content += f'    with open("{filename}", "wb") as f:\n'
        content += '        with open("/dev/urandom", "rb") as rng:\n'
        content += '            __sip_gen__(rng, f)\n'
        content += "\nif __name__ == '__main__':\n    main()\n"
        
        with open(py_filepath, "w") as f:
            f.write(content)
        # print(f"Generated {py_filepath}")

    # Generate synthetic seeds for missing methods
    missing_methods = set(KNOWN_SIP_COMMANDS.keys()) - seen_methods
    if missing_methods:
        print(f"Adding synthetic seeds for missing methods: {missing_methods}")
        synthetic_funcs_code = []
        
        # Sort missing methods based on logical protocol order
        sorted_missing = sorted(list(missing_methods), key=lambda m: METHOD_ORDER.index(m) if m in METHOD_ORDER else 999)
        
        for method in sorted_missing:
            payload = KNOWN_SIP_COMMANDS[method]
            func_name = f"synthetic_000_{method}"
            func_code = f"def {func_name}(): return {repr(payload)}"
            synthetic_funcs_code.append(func_code)
            all_funcs_code_for_all_py.append(func_code)
            
        # Generate synthetic python file
        py_filename = "sip_seeds_synthetic.py"
        py_filepath = os.path.join(output_dir, py_filename)
        content = "import os\n\n"
        content += "\n".join(synthetic_funcs_code)
        content += "\n\n"
        content += sip_gen_code
        content += "\n"
        content += "def main():\n"
        content += '    with open("synthetic.raw", "wb") as f:\n'
        content += '        with open("/dev/urandom", "rb") as rng:\n'
        content += '            __sip_gen__(rng, f)\n'
        content += "\nif __name__ == '__main__':\n    main()\n"
        
        with open(py_filepath, "w") as f:
            f.write(content)

    # Generate valid business flow seeds
    SIP_FLOWS = {
        "register": ["REGISTER"],
        "register_auth": ["REGISTER", "REGISTER_AUTH"],
        "invite_ack_bye": ["INVITE", "ACK", "BYE"],
        "invite_cancel": ["INVITE", "CANCEL"],
        "options": ["OPTIONS"],
        "subscribe_notify": ["SUBSCRIBE", "NOTIFY"],
        "message": ["MESSAGE"],
        "refer": ["INVITE", "ACK", "REFER", "BYE"],
        "info": ["INVITE", "ACK", "INFO", "BYE"],
        "update": ["INVITE", "UPDATE", "ACK", "BYE"]
    }

    for flow_name, methods in SIP_FLOWS.items():
        flow_funcs_code = []
        for i, method in enumerate(methods):
            if method in KNOWN_SIP_COMMANDS:
                payload = KNOWN_SIP_COMMANDS[method]
                func_name = f"flow_{i:03d}_{method}"
                func_code = f"def {func_name}(): return {repr(payload)}"
                flow_funcs_code.append(func_code)
        
        if not flow_funcs_code:
            continue

        py_filename = f"sip_flow_{flow_name}.py"
        py_filepath = os.path.join(output_dir, py_filename)
        
        content = "import os\n\n"
        content += "\n".join(flow_funcs_code)
        content += "\n\n"
        content += sip_gen_code
        content += "\n"
        content += "def main():\n"
        content += f'    with open("{flow_name}.raw", "wb") as f:\n'
        content += '        with open("/dev/urandom", "rb") as rng:\n'
        content += '            __sip_gen__(rng, f)\n'
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
