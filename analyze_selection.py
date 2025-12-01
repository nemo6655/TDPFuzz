import json
import os
import statistics
import sys

BASE_DIR = '/home/appuser/elmfuzz/preset/live555/gen1/aflnetout'
COV_FILE = 'coverage.json'
ELITES_FILE = 'selected_elites.json'

def get_file_size(state, filename):
    # Try queue first
    p1 = os.path.join(BASE_DIR, state, 'queue', filename)
    if os.path.exists(p1): return os.path.getsize(p1)
    # Try root of state dir
    p2 = os.path.join(BASE_DIR, state, filename)
    if os.path.exists(p2): return os.path.getsize(p2)
    return 0

def extract_transitions(state_str):
    # state_str example: "0-404-405"
    if not state_str: return set()
    states = state_str.split('-')
    transitions = set()
    for i in range(len(states) - 1):
        transitions.add(f"{states[i]}->{states[i+1]}")
    return transitions

def parse_key(key):
    # Returns (filename, transition_str)
    if ':state:' in key:
        parts = key.split(':state:', 1)
        return parts[0], parts[1]
    return key, ""

def analyze(name, items):
    sizes = []
    all_edges = set()
    all_transitions = set()
    all_paths = set()
    
    print(f"Analyzing {name} ({len(items)} seeds)...")
    
    for item in items:
        state = item['state']
        full_key = item['key']
        edges = item['edges']
        
        filename, trans_str = parse_key(full_key)
        
        # Size
        sz = get_file_size(state, filename)
        if sz > 0:
            sizes.append(sz)
        
        # Edges
        # Edges in json might be "id:count" or just "id"
        # Check format
        clean_edges = set()
        for e in edges:
            if ':' in e:
                clean_edges.add(e.split(':')[0])
            else:
                clean_edges.add(e)
        all_edges.update(clean_edges)
        
        # Transitions
        if trans_str:
            all_paths.add(trans_str)
            all_transitions.update(extract_transitions(trans_str))

    avg_size = statistics.mean(sizes) if sizes else 0
    
    print(f"  Count: {len(sizes)}")
    print(f"  Average Size: {avg_size:.2f} bytes")
    print(f"  Total Unique Edges: {len(all_edges)}")
    print(f"  Total Unique Transitions: {len(all_transitions)}")
    print(f"  Total Unique Paths: {len(all_paths)}")
    return avg_size, len(all_edges), len(all_transitions)

def main():
    # 1. Load All Seeds from coverage.json
    print("Loading coverage.json...")
    with open(COV_FILE, 'r') as f:
        cov_data = json.load(f)
    
    all_seeds = []
    # Handle nested structure Gen -> State -> Key -> Edges
    # Or flat structure
    first_val = next(iter(cov_data.values()))
    if isinstance(first_val, dict):
        for gen, states in cov_data.items():
            for state, files in states.items():
                for key, edges in files.items():
                    all_seeds.append({'state': state, 'key': key, 'edges': edges})
    else:
        # Flat structure
        for key, edges in cov_data.items():
            # key format: STATE:FILENAME...
            if ':' in key:
                state = key.split(':', 1)[0]
                # Remove state prefix from key for consistency if needed, 
                # but parse_key handles the suffix. 
                # The key in flat structure usually includes state prefix.
                # Let's strip it to match nested format keys which usually don't have state prefix?
                # Actually, let's just pass the full key and handle state extraction carefully.
                # Wait, in flat structure key is "0001:id:..."
                # In nested structure key is "id:..."
                # Let's normalize key to "id:..."
                real_key = key.split(':', 1)[1]
                all_seeds.append({'state': state, 'key': real_key, 'edges': edges})

    # 2. Load Selected Elites
    print("Loading selected_elites.json...")
    with open(ELITES_FILE, 'r') as f:
        elite_data = json.load(f)
        
    selected_seeds = []
    for gen, states in elite_data.items():
        for state, files in states.items():
            for key, edges in files.items():
                selected_seeds.append({'state': state, 'key': key, 'edges': edges})

    # 3. Analyze
    print("\n--- Statistics Before Selection (All Seeds) ---")
    avg_before, edges_before, trans_before = analyze("All Seeds", all_seeds)
    
    print("\n--- Statistics After Selection (Selected Elites) ---")
    avg_after, edges_after, trans_after = analyze("Selected Elites", selected_seeds)
    
    print("\n--- Comparison ---")
    print(f"Size Reduction: {avg_before:.2f} -> {avg_after:.2f} bytes ({(avg_after/avg_before)*100:.1f}%)")
    print(f"Edge Coverage Retention: {edges_after}/{edges_before} ({(edges_after/edges_before)*100:.1f}%)")
    print(f"Transition Coverage Retention: {trans_after}/{trans_before} ({(trans_after/trans_before)*100:.1f}%)")

if __name__ == '__main__':
    main()
