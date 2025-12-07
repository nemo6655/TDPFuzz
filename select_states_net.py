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

def get_seed_map(base_dir):
    """
    Returns a dictionary mapping seed prefixes (e.g., id:000001) to full paths.
    Scans both base_dir and base_dir/queue.
    """
    seed_map = {}
    
    dirs_to_check = [base_dir]
    queue_dir = os.path.join(base_dir, 'queue')
    if os.path.exists(queue_dir):
        dirs_to_check.append(queue_dir)
        
    for d in dirs_to_check:
        if os.path.exists(d):
            try:
                for f in os.listdir(d):
                    full_path = os.path.join(d, f)
                    if os.path.isfile(full_path):
                        # prefix is usually id:xxxxxx
                        prefix = f.split(',')[0]
                        # If duplicate prefixes exist, last one wins (should be fine for this purpose)
                        seed_map[prefix] = full_path
            except OSError:
                pass
    return seed_map



def resolve_gen_dir(elmfuzz_rundir, gen_name):
    """
    Resolves the directory name for a generation (e.g., '1' -> 'gen1' or '1').
    """
    if os.path.exists(os.path.join(elmfuzz_rundir, gen_name)):
        return gen_name
    
    if not gen_name.startswith('gen'):
        candidate = 'gen' + gen_name
        if os.path.exists(os.path.join(elmfuzz_rundir, candidate)):
            return candidate
            
    return gen_name # Default fallback

def select_states_noss(cov_file, elites_file, gen, elmfuzz_rundir):
    print(f"Loading coverage file: {cov_file}")
    with open(cov_file, 'r') as f:
        cov_data = json.load(f)
    
    print(f"Loading elites file: {elites_file}")
    with open(elites_file, 'r') as f:
        elites_data = json.load(f)

    # Cache for seed maps: (gen_dir_name, pool) -> seed_map
    seed_map_cache = {} 

    def get_cached_seed_path(gen_dir, pool, seed_prefix):
        key = (gen_dir, pool)
        if key not in seed_map_cache:
             base_dir = os.path.join(elmfuzz_rundir, gen_dir, 'aflnetout', pool)
             seed_map_cache[key] = get_seed_map(base_dir)
        return seed_map_cache[key].get(seed_prefix)

    # 1. Copy Elite Seeds to 0000
    dest_0000 = os.path.join(elmfuzz_rundir, gen, 'seeds', '0000')
    os.makedirs(dest_0000, exist_ok=True)
    
    elite_seeds_copied = []

    # elites_data structure: prev_gen -> state_pool -> filename -> edges
    for prev_gen, states in elites_data.items():
        gen_dir_name = resolve_gen_dir(elmfuzz_rundir, prev_gen)

        for state_pool, files in states.items():
            for filename_key in files.keys():
                # filename_key format: seed_name:state:transition_info
                if ':state:' in filename_key:
                    seed_name_full = filename_key.split(':state:')[0]
                else:
                    seed_name_full = filename_key
                
                seed_id_prefix = seed_name_full.split(',')[0]
                
                src_path = get_cached_seed_path(gen_dir_name, state_pool, seed_id_prefix)
                
                if src_path:
                    shutil.copy(src_path, dest_0000)
                    elite_seeds_copied.append(seed_name_full)
                else:
                    print(f"Warning: Elite seed not found: {seed_name_full} (prefix {seed_id_prefix}) in {state_pool}", file=sys.stderr)

    print(f"Copied {len(elite_seeds_copied)} elite seeds to {dest_0000}")

    # 2. Identify Missing Transitions and Copy to respective pools
    dest_0001 = os.path.join(elmfuzz_rundir, gen, 'seeds', '0001')
    os.makedirs(dest_0001, exist_ok=True)

    # Calculate generation string for JSON lookup (e.g., gen2 -> 1)
    try:
        gen_num = int(gen.replace('gen', '')) - 1
        gen_str = str(gen_num)
    except ValueError:
        print(f"Error: Could not parse generation number from {gen}", file=sys.stderr)
        sys.exit(1)

    # Collect covered transitions from elites
    covered_transitions = set()
    if gen_str in elites_data:
        for state, seeds in elites_data[gen_str].items():
            for seed_name, val in seeds.items():
                edges = []
                if isinstance(val, list) and len(val) == 2:
                    edges = val[0]
                elif isinstance(val, dict) and 'edges' in val:
                    edges = val['edges']
                
                for e in edges:
                    if isinstance(e, str) and e.startswith('__TRANS_'):
                        covered_transitions.add(e)

    # Extract all transitions from coverage and map them to seeds
    all_transitions = set()
    transition_to_seeds = {} # Map transition -> list of seed paths

    if gen_str in cov_data:
        gen_dir_name = resolve_gen_dir(elmfuzz_rundir, gen_str)
        
        for job, seeds in cov_data[gen_str].items():
            for seed_name, state_data in seeds.items():
                if isinstance(state_data, dict):
                    # Resolve seed path once per seed
                    seed_id_prefix = seed_name.split(',')[0]
                    src_path = get_cached_seed_path(gen_dir_name, job, seed_id_prefix)
                    
                    if src_path:
                        for state, edges in state_data.items():
                            parts = state.split('-')
                            if len(parts) > 1:
                                for i in range(len(parts) - 1):
                                    src = parts[i]
                                    dst = parts[i+1]
                                    trans = f"__TRANS_{src}_{dst}__"
                                    all_transitions.add(trans)
                                    
                                    if trans not in transition_to_seeds:
                                        transition_to_seeds[trans] = []
                                    # Avoid duplicates if possible, or just append
                                    transition_to_seeds[trans].append(src_path)

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
    if missing_seeds_copied > 0:
        target_pools = [p for p in state_pools if p not in ['0000', '0001']]
    else:
        target_pools = [p for p in state_pools if p not in ['0000']]
    
    distribution_results = {}

    if target_pools:
        # Get list of seeds in 0000 (the elites)
        seeds_in_0000 = [os.path.join(dest_0000, f) for f in os.listdir(dest_0000) if os.path.isfile(os.path.join(dest_0000, f))]
        num_seeds = len(seeds_in_0000)
        num_targets = len(target_pools)
        
        if num_seeds > 0:
            print(f"Distributing {num_seeds} seeds from 0000 to {num_targets} pools: {target_pools}")
            
            # Average distribution (splitting the set)
            chunk_size = math.ceil(num_seeds / num_targets)
            
            for i, pool in enumerate(target_pools):
                dest_pool = os.path.join(elmfuzz_rundir, gen, 'seeds', pool)
                os.makedirs(dest_pool, exist_ok=True)
                
                start_idx = i * chunk_size
                end_idx = min((i + 1) * chunk_size, num_seeds)
                
                chunk = seeds_in_0000[start_idx:end_idx]
                distribution_results[pool] = [os.path.basename(s) for s in chunk]
                
                if not chunk:
                    print(f"  Pool {pool}: No seeds assigned (ran out of seeds).")
                    continue

                for seed_path in chunk:
                    shutil.copy(seed_path, dest_pool)
                    
                print(f"  Pool {pool}: Copied {len(chunk)} seeds.")
        else:
            print("No seeds in 0000 to distribute.")
    else:
        print("No other state pools to distribute to.")

    # 4. Write selection results to log file
    log_dir = os.path.join(elmfuzz_rundir, gen, 'logs')
    os.makedirs(log_dir, exist_ok=True)
    state_log_path = os.path.join(log_dir, 'state.log')
    
    with open(state_log_path, 'a') as f:
        f.write(f"\n=== Generation {gen} (NOSS) ===\n")
        f.write("Pool 0000 (Elites):\n")
        for seed in sorted(elite_seeds_copied):
            f.write(f"{seed}\n")
            
        f.write("\nPool 0001 (Missing Transitions):\n")
        for seed_path in sorted(seeds_to_copy_for_missing):
            f.write(f"{os.path.basename(seed_path)}\n")
            
        f.write("\nDistribution:\n")
        if distribution_results:
            for pool, seeds in sorted(distribution_results.items()):
                f.write(f"Pool {pool}:\n")
                for s in sorted(seeds):
                    f.write(f"{s}\n")
        else:
            f.write("No distribution performed.\n")

def select_states_ss(cov_file, elites_file, gen, elmfuzz_rundir):
    print(f"Loading coverage file: {cov_file}")
    with open(cov_file, 'r') as f:
        cov_data = json.load(f)
    
    print(f"Loading elites file: {elites_file}")
    with open(elites_file, 'r') as f:
        elites_data = json.load(f)

    # Cache for seed maps: (gen_dir_name, pool) -> seed_map
    seed_map_cache = {} 

    def get_cached_seed_path(gen_dir, pool, seed_prefix):
        key = (gen_dir, pool)
        if key not in seed_map_cache:
             base_dir = os.path.join(elmfuzz_rundir, gen_dir, 'aflnetout', pool)
             seed_map_cache[key] = get_seed_map(base_dir)
        return seed_map_cache[key].get(seed_prefix)

    # 1. Identify and Copy Elite Seeds (Pool 0000)
    dest_0000 = os.path.join(elmfuzz_rundir, gen, 'seeds', '0000')
    os.makedirs(dest_0000, exist_ok=True)
    
    elite_seeds_info = [] # List of {'path': str, 'transitions': set(), 'name': str}
    
    # Parse Elites
    for prev_gen, states in elites_data.items():
        gen_dir_name = resolve_gen_dir(elmfuzz_rundir, prev_gen)
        for state_pool, files in states.items():
            for filename_key, val in files.items():
                # Extract seed info
                if ':state:' in filename_key:
                    seed_name_full = filename_key.split(':state:')[0]
                else:
                    seed_name_full = filename_key
                seed_id_prefix = seed_name_full.split(',')[0]
                
                src_path = get_cached_seed_path(gen_dir_name, state_pool, seed_id_prefix)
                
                if src_path:
                    # Extract transitions for this elite seed
                    transitions = set()
                    edges = []
                    if isinstance(val, list) and len(val) == 2:
                        edges = val[0]
                    elif isinstance(val, dict) and 'edges' in val:
                        edges = val['edges']
                    
                    for e in edges:
                        if isinstance(e, str) and e.startswith('__TRANS_'):
                            transitions.add(e)
                            
                    elite_seeds_info.append({
                        'path': src_path,
                        'name': seed_name_full,
                        'transitions': transitions
                    })
                    
                    shutil.copy(src_path, dest_0000)
                else:
                    print(f"Warning: Elite seed not found: {seed_name_full} (prefix {seed_id_prefix}) in {state_pool}", file=sys.stderr)

    print(f"Copied {len(elite_seeds_info)} elite seeds to {dest_0000}")

    # 2. Analyze Transitions (Global vs Elite)
    elite_covered_transitions = set()
    transition_counts = {} # transition -> count in elites
    
    for seed in elite_seeds_info:
        for t in seed['transitions']:
            elite_covered_transitions.add(t)
            transition_counts[t] = transition_counts.get(t, 0) + 1

    # Parse Coverage Data to find missing transitions
    # We need to map transitions to candidate seeds (path, size)
    missing_transition_candidates = {} # transition -> list of {'path': str, 'size': int}
    
    # Calculate generation string
    try:
        gen_num = int(gen.replace('gen', '')) - 1
        gen_str = str(gen_num)
    except ValueError:
        gen_str = "0" # Fallback

    if gen_str in cov_data:
        gen_dir_name = resolve_gen_dir(elmfuzz_rundir, gen_str)
        for job, seeds in cov_data[gen_str].items():
            for seed_name, state_data in seeds.items():
                if isinstance(state_data, dict):
                    seed_id_prefix = seed_name.split(',')[0]
                    src_path = get_cached_seed_path(gen_dir_name, job, seed_id_prefix)
                    
                    if src_path:
                        try:
                            size = os.path.getsize(src_path)
                        except OSError:
                            size = float('inf')

                        # Extract transitions for this seed
                        seed_transitions = set()
                        for state, edges in state_data.items():
                            parts = state.split('-')
                            if len(parts) > 1:
                                for i in range(len(parts) - 1):
                                    src = parts[i]
                                    dst = parts[i+1]
                                    trans = f"__TRANS_{src}_{dst}__"
                                    seed_transitions.add(trans)
                        
                        # Check if any are missing from elites
                        for t in seed_transitions:
                            if t not in elite_covered_transitions:
                                if t not in missing_transition_candidates:
                                    missing_transition_candidates[t] = []
                                missing_transition_candidates[t].append({'path': src_path, 'size': size})

    # 3. Determine Distribution Strategy
    state_pools = get_state_pools()
    # Filter out 0000
    all_target_pools = sorted([p for p in state_pools if p != '0000'])
    
    seeds_to_rescue = set()
    for t, candidates in missing_transition_candidates.items():
        # Pick smallest
        best_candidate = min(candidates, key=lambda x: x['size'])
        seeds_to_rescue.add(best_candidate['path'])

    dist_pools = []
    
    if seeds_to_rescue:
        # Case A: Missing transitions exist -> 0001 gets rescue seeds
        dest_0001 = os.path.join(elmfuzz_rundir, gen, 'seeds', '0001')
        os.makedirs(dest_0001, exist_ok=True)
        for src_path in seeds_to_rescue:
            shutil.copy(src_path, dest_0001)
        print(f"Copied {len(seeds_to_rescue)} seeds covering {len(missing_transition_candidates)} missing transitions to 0001")
        
        # Distribute elites to remaining pools
        dist_pools = [p for p in all_target_pools if p != '0001']
    else:
        # Case B: No missing transitions -> 0001 joins distribution
        print("No missing transitions found. 0001 joins the distribution pool.")
        dist_pools = all_target_pools

    # 4. Distribute Elites to Target Pools (Sorted by Rarity)
    if dist_pools:
        # Calculate Rarity Score for each Elite Seed
        # Score = Sum(1 / count) for each transition
        # Higher score = More rare (fewer counts)
        for seed in elite_seeds_info:
            score = 0
            for t in seed['transitions']:
                count = transition_counts.get(t, 1)
                score += 1.0 / count
            seed['score'] = score
            
        # Sort by score descending (most rare/unique first)
        sorted_elites = sorted(elite_seeds_info, key=lambda x: x['score'], reverse=True)
        
        num_pools = len(dist_pools)
        num_seeds = len(sorted_elites)
        
        print(f"Distributing {num_seeds} elite seeds to {num_pools} pools: {dist_pools}")
        
        # Split into chunks (Slicing instead of Round Robin)
        chunk_size = math.ceil(num_seeds / num_pools)
        
        for i, pool in enumerate(dist_pools):
            start_idx = i * chunk_size
            end_idx = min((i + 1) * chunk_size, num_seeds)
            
            chunk = sorted_elites[start_idx:end_idx]
            
            dest_pool = os.path.join(elmfuzz_rundir, gen, 'seeds', pool)
            os.makedirs(dest_pool, exist_ok=True)
            
            for s in chunk:
                shutil.copy(s['path'], dest_pool)
            
            print(f"  Pool {pool}: Copied {len(chunk)} seeds (Rarity Rank {i+1}/{num_pools}).")
            
    else:
        print("No other state pools to distribute to.")

@click.command()
@click.option('--cov_file', '-c', type=click.Path(exists=True), required=True, help='Previous generation coverage file')
@click.option('--elites_file', '-e', type=click.Path(exists=True), required=True, help='Current generation elite seeds file')
@click.option('--gen', '-g', type=str, required=True, help='Next generation name')
@click.option('--noss', is_flag=True, default=False, help='Use current state selection algorithm')
@click.option('--ss', '-ss', is_flag=True, default=False, help='Use new state selection algorithm')
def main(cov_file, elites_file, gen, noss, ss):
    elmfuzz_rundir = os.environ.get('ELMFUZZ_RUNDIR')
    if not elmfuzz_rundir:
        print("Error: ELMFuzz_RUNDIR environment variable not set.", file=sys.stderr)
        sys.exit(1)

    if ss:
        select_states_ss(cov_file, elites_file, gen, elmfuzz_rundir)
    else:
        # Default to noss if not specified or if noss is specified
        select_states_noss(cov_file, elites_file, gen, elmfuzz_rundir)

if __name__ == '__main__':
    main()
