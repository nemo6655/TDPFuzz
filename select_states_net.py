import click
import json
import os
import shutil
import subprocess
import sys
import math

def get_state_pools():
    try:
        # Call elmconfig.py to get the state pools
        script_dir = os.path.dirname(os.path.abspath(__file__))
        elmconfig_path = os.path.join(script_dir, 'elmconfig.py')
        
        result = subprocess.run(
            [sys.executable, elmconfig_path, 'get', 'run.state_pools'],
            capture_output=True, text=True, check=True
        )
        # Output should be space-separated list
        pools = result.stdout.strip().split()
        return pools
    except Exception as e:
        print(f"Error getting state pools: {e}", file=sys.stderr)
        return []

def find_seed_path(base_dir, seed_prefix):
    """
    Finds a file in base_dir (or base_dir/queue) that starts with seed_prefix.
    """
    # Check direct directory
    if os.path.exists(base_dir):
        for f in os.listdir(base_dir):
            if f.startswith(seed_prefix):
                return os.path.join(base_dir, f)
    
    # Check queue directory
    queue_dir = os.path.join(base_dir, 'queue')
    if os.path.exists(queue_dir):
        for f in os.listdir(queue_dir):
            if f.startswith(seed_prefix):
                return os.path.join(queue_dir, f)
                
    return None

def get_transitions(state_str):
    """
    Parses a state string (e.g., "0-200-201") into a set of transitions.
    Handles 'end-at-' by truncating the sequence before it.
    """
    if not state_str:
        return set()
    
    end_at_index = state_str.find('end-at-')
    if end_at_index != -1:
        clean_str = state_str[:end_at_index]
        if clean_str.endswith('-'):
            clean_str = clean_str[:-1]
    else:
        clean_str = state_str

    parts = clean_str.split('-')
    states = [p for p in parts if p]
    
    transitions = set()
    for i in range(len(states) - 1):
        transitions.add((states[i], states[i+1]))
    
    return transitions

def extract_state_string(filename):
    """
    Extracts the state string from a filename key.
    Format: seed_name:state:transition_info
    """
    if ':state:' in filename:
        try:
            return filename.split(':state:')[1]
        except IndexError:
            return None
    return None

@click.command()
@click.option('--cov_file', '-c', type=click.Path(exists=True), required=True, help='Previous generation coverage file')
@click.option('--elites_file', '-e', type=click.Path(exists=True), required=True, help='Current generation elite seeds file')
@click.option('--gen', '-g', type=str, required=True, help='Next generation name')
def main(cov_file, elites_file, gen):
    elmfuzz_rundir = os.environ.get('ELMFUZZ_RUNDIR')
    if not elmfuzz_rundir:
        print("Error: ELMFuzz_RUNDIR environment variable not set.", file=sys.stderr)
        sys.exit(1)

    print(f"Loading coverage file: {cov_file}")
    with open(cov_file, 'r') as f:
        cov_data = json.load(f)
    
    print(f"Loading elites file: {elites_file}")
    with open(elites_file, 'r') as f:
        elites_data = json.load(f)

    # 1. Copy Elite Seeds to 0000
    dest_0000 = os.path.join(elmfuzz_rundir, gen, 'seeds', '0000')
    os.makedirs(dest_0000, exist_ok=True)
    
    elite_seeds_copied = []

    # elites_data structure: prev_gen -> state_pool -> filename -> edges
    for prev_gen, states in elites_data.items():
        # Normalize generation name to match directory structure
        gen_dir_name = prev_gen
        if not os.path.exists(os.path.join(elmfuzz_rundir, gen_dir_name)):
            if not gen_dir_name.startswith('gen'):
                candidate = 'gen' + gen_dir_name
                if os.path.exists(os.path.join(elmfuzz_rundir, candidate)):
                    gen_dir_name = candidate

        for state_pool, files in states.items():
            for filename_key in files.keys():
                # filename_key format: seed_name:state:transition_info
                if ':state:' in filename_key:
                    seed_name_full = filename_key.split(':state:')[0]
                else:
                    seed_name_full = filename_key
                
                # Extract ID for fuzzy search
                # seed_name_full usually looks like "id:000317,src:..."
                # We want "id:000317"
                seed_id_prefix = seed_name_full.split(',')[0]
                
                # Source path construction
                base_dir = os.path.join(elmfuzz_rundir, gen_dir_name, 'aflnetout', state_pool)
                src_path = find_seed_path(base_dir, seed_id_prefix)
                
                if src_path:
                    shutil.copy(src_path, dest_0000)
                    elite_seeds_copied.append(seed_name_full)
                else:
                    print(f"Warning: Elite seed not found: {seed_name_full} (prefix {seed_id_prefix}) in {state_pool}", file=sys.stderr)

    print(f"Copied {len(elite_seeds_copied)} elite seeds to {dest_0000}")

    # 2. Identify Missing Transitions and Copy to respective pools
    dest_0001 = os.path.join(elmfuzz_rundir, gen, 'seeds', '0001')
    os.makedirs(dest_0001, exist_ok=True)

    # Collect covered transitions from elites
    covered_transitions = set()
    for prev_gen, states in elites_data.items():
        for state_pool, files in states.items():
            for filename_key in files.keys():
                st_str = extract_state_string(filename_key)
                if st_str:
                    covered_transitions.update(get_transitions(st_str))

    # Collect all transitions and map to seeds from coverage file
    all_transitions = set()
    transition_to_seeds = {} # (src, dst) -> list of src_path

    for prev_gen, states in cov_data.items():
        # Normalize generation name to match directory structure
        gen_dir_name = prev_gen
        if not os.path.exists(os.path.join(elmfuzz_rundir, gen_dir_name)):
            if not gen_dir_name.startswith('gen'):
                candidate = 'gen' + gen_dir_name
                if os.path.exists(os.path.join(elmfuzz_rundir, candidate)):
                    gen_dir_name = candidate

        for state_pool, files in states.items():
            for filename_key in files.keys():
                st_str = extract_state_string(filename_key)
                if st_str:
                    trans = get_transitions(st_str)
                    
                    if ':state:' in filename_key:
                        seed_name_full = filename_key.split(':state:')[0]
                    else:
                        seed_name_full = filename_key
                        
                    seed_id_prefix = seed_name_full.split(',')[0]
                    
                    # Find path
                    base_dir = os.path.join(elmfuzz_rundir, gen_dir_name, 'aflnetout', state_pool)
                    src_path = find_seed_path(base_dir, seed_id_prefix)
                    
                    if src_path:
                        for t in trans:
                            all_transitions.add(t)
                            if t not in transition_to_seeds:
                                transition_to_seeds[t] = []
                            transition_to_seeds[t].append(src_path)

    missing_transitions = all_transitions - covered_transitions
    print(f"Found {len(missing_transitions)} missing transitions.")

    missing_seeds_copied = 0
    seeds_to_copy_for_missing = set() # Set of src_path
    
    for t in missing_transitions:
        candidates = transition_to_seeds.get(t)
        if candidates:
            # Add all candidates covering this missing transition
            seeds_to_copy_for_missing.update(candidates)
    
    for src_path in seeds_to_copy_for_missing:
        # Copy to gen/seeds/0001
        shutil.copy(src_path, dest_0001)
        missing_seeds_copied += 1
        
    print(f"Copied {missing_seeds_copied} seeds covering missing transitions to {dest_0001}")

    # 3. Distribute to other pools
    state_pools = get_state_pools()
    # Filter out 0000 and 0001
    target_pools = [p for p in state_pools if p not in ['0000', '0001']]
    
    if not target_pools:
        print("No other state pools to distribute to.")
        return

    # Get list of seeds in 0000 (the elites)
    seeds_in_0000 = [os.path.join(dest_0000, f) for f in os.listdir(dest_0000) if os.path.isfile(os.path.join(dest_0000, f))]
    num_seeds = len(seeds_in_0000)
    num_targets = len(target_pools)
    
    if num_seeds == 0:
        print("No seeds in 0000 to distribute.")
        return

    print(f"Distributing {num_seeds} seeds from 0000 to {num_targets} pools: {target_pools}")
    
    # Average distribution (splitting the set)
    chunk_size = math.ceil(num_seeds / num_targets)
    
    for i, pool in enumerate(target_pools):
        dest_pool = os.path.join(elmfuzz_rundir, gen, 'seeds', pool)
        os.makedirs(dest_pool, exist_ok=True)
        
        start_idx = i * chunk_size
        end_idx = min((i + 1) * chunk_size, num_seeds)
        
        chunk = seeds_in_0000[start_idx:end_idx]
        
        if not chunk:
            print(f"  Pool {pool}: No seeds assigned (ran out of seeds).")
            continue

        for seed_path in chunk:
            shutil.copy(seed_path, dest_pool)
            
        print(f"  Pool {pool}: Copied {len(chunk)} seeds.")

if __name__ == '__main__':
    main()
