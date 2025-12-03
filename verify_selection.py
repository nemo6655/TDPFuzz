import json
import sys
import os

ELMFUZZ_RUNDIR = "/home/appuser/elmfuzz/test_gen1"
GENERATION = ""

def extract_state_pseudo_edges(filename: str) -> set[str]:
    pseudo_edges = set()
    if ':state:' in filename:
        try:
            state_part = filename.split(':state:', 1)[1]
            if 'end-at-' in state_part:
                state_part = state_part.split('end-at-', 1)[0]
                if state_part.endswith('-'):
                    state_part = state_part[:-1]
            
            states = state_part.split('-')
            states = [s for s in states if s.isdigit()]
            
            if len(states) >= 2:
                for i in range(len(states) - 1):
                    pseudo_edges.add(f"__TRANS_{states[i]}_{states[i+1]}__")
        except Exception:
            pass
    return pseudo_edges

def check_file_exists(state, filename):
    if ':state:' in filename:
        real_filename = filename.split(':state:', 1)[0]
    else:
        real_filename = filename

    # Improved file finding logic
    candidates = [
        os.path.join(ELMFUZZ_RUNDIR, GENERATION, 'aflnetout', state, 'queue', real_filename),
        os.path.join(ELMFUZZ_RUNDIR, GENERATION, 'aflnetout', state, real_filename),
        os.path.join(ELMFUZZ_RUNDIR, 'aflnetout', state, 'queue', real_filename),
        os.path.join(ELMFUZZ_RUNDIR, 'aflnetout', state, real_filename)
    ]
    
    for p in candidates:
        if os.path.exists(p):
            return True
            
    # Search in all aflnetout subdirectories
    if not hasattr(check_file_exists, 'aflnet_dirs_cache'):
        check_file_exists.aflnet_dirs_cache = []
        possible_roots = [
            os.path.join(ELMFUZZ_RUNDIR, GENERATION, 'aflnetout'),
            os.path.join(ELMFUZZ_RUNDIR, 'aflnetout')
        ]
        for root in possible_roots:
            if os.path.exists(root):
                try:
                    for d in os.listdir(root):
                        full_d = os.path.join(root, d)
                        if os.path.isdir(full_d):
                            check_file_exists.aflnet_dirs_cache.append(full_d)
                            queue_d = os.path.join(full_d, 'queue')
                            if os.path.isdir(queue_d):
                                check_file_exists.aflnet_dirs_cache.append(queue_d)
                except OSError:
                    pass

    for d in check_file_exists.aflnet_dirs_cache:
        p = os.path.join(d, real_filename)
        if os.path.exists(p):
            return True
        if real_filename.startswith("id:"):
             seed_id = real_filename.split(',')[0]
             try:
                 for f in os.listdir(d):
                     if f.startswith(seed_id + ","):
                         return True
             except OSError:
                 pass
                 
    return False

def verify_coverage(coverage_file, elite_file):
    print(f"Verifying coverage...")
    print(f"Coverage File: {coverage_file}")
    print(f"Elite File: {elite_file}")

    # 1. Load Coverage File (The Universe)
    with open(coverage_file, 'r') as f:
        coverage_raw = json.loads(f.read())

    universe_edges = set()
    missing_files_count = 0
    
    first_val = next(iter(coverage_raw.values()))
    if isinstance(first_val, dict):
        for gen, states in coverage_raw.items():
            for state, files in states.items():
                for filename, edges_list in files.items():
                    if not check_file_exists(state, filename):
                        missing_files_count += 1
                        continue
                        
                    # Add standard edges
                    for e in edges_list:
                        universe_edges.add(e.split(':')[0])
                    # Add pseudo edges
                    universe_edges.update(extract_state_pseudo_edges(filename))
    else:
        pass

    print(f"Universe size (Total unique edges + transitions in EXISTING files): {len(universe_edges)}")
    
    universe_trans = [e for e in universe_edges if e.startswith("__TRANS_")]
    print(f"  - Universe Transitions: {len(universe_trans)}")
    print(f"  - Universe Normal Edges: {len(universe_edges) - len(universe_trans)}")

    print(f"Skipped {missing_files_count} files because they were not found on disk.")

    # 2. Load Elite File (The Selection)
    with open(elite_file, 'r') as f:
        elites_raw = json.loads(f.read())

    selected_edges = set()
    
    for gen, states in elites_raw.items():
        for state, files in states.items():
            for filename, val in files.items():
                edges_list = val[0]
                selected_edges.update(edges_list)

    print(f"Selected edges size (Union of edges in selected seeds): {len(selected_edges)}")
    selected_trans = [e for e in selected_edges if e.startswith("__TRANS_")]
    print(f"  - Selected Transitions: {len(selected_trans)}")

    # 3. Verify
    missing = universe_edges - selected_edges
    
    if not missing:
        print("SUCCESS: All edges and state transitions in coverage.json (that exist on disk) are covered.")
    else:
        print(f"FAILURE: {len(missing)} edges/transitions are NOT covered!")
        print("Missing examples:")
        for m in list(missing)[:10]:
            print(f" - {m}")
        
        missing_trans = [m for m in missing if m.startswith("__TRANS_")]
        print(f"Missing Transitions: {len(missing_trans)}")
        print(f"Missing Normal Edges: {len(missing) - len(missing_trans)}")

if __name__ == "__main__":
    verify_coverage(
        "/home/appuser/elmfuzz/test_gen1/logs/coverage.json",
        "/tmp/elites_test_100.json"
    )
