import json
import sys

def load_coverage(cov_file):
    with open(cov_file, 'r') as f:
        data = json.load(f)
    
    all_edges = set()
    all_transitions = set()
    
    # Handle new format: gen -> job -> seed -> state_info -> edges
    # Or old format: gen -> job -> seed -> edges
    
    for gen, jobs in data.items():
        for job, seeds in jobs.items():
            for seed, val in seeds.items():
                if isinstance(val, dict):
                    for state_str, edges in val.items():
                        all_edges.update(edges)
                        if state_str != "unknown":
                            all_transitions.update(get_transitions(state_str))
                elif isinstance(val, list):
                    all_edges.update(val)
                    # Try to extract from filename if possible (legacy)
                    if ':state:' in seed:
                        try:
                            state_str = seed.split(':state:', 1)[1]
                            all_transitions.update(get_transitions(state_str))
                        except:
                            pass
                            
    return all_edges, all_transitions

def get_transitions(state_str):
    pseudo_edges = set()
    if not state_str or state_str == "unknown":
        return pseudo_edges
    try:
        if 'end-at-' in state_str:
            state_str = state_str.split('end-at-', 1)[0]
            if state_str.endswith('-'):
                state_str = state_str[:-1]
        states = [s for s in state_str.split('-') if s.isdigit()]
        if len(states) >= 2:
            for i in range(len(states) - 1):
                pseudo_edges.add(f"__TRANS_{states[i]}_{states[i+1]}__")
    except:
        pass
    return pseudo_edges

def load_elites(elite_file):
    with open(elite_file, 'r') as f:
        data = json.load(f)
    
    covered_edges = set()
    covered_transitions = set()
    
    # Format: gen -> state -> seed -> [edges, size]
    for gen, states in data.items():
        for state, seeds in states.items():
            for seed, info in seeds.items():
                edges = info[0]
                covered_edges.update(edges)
                
                # Extract transitions from edges (pseudo-edges)
                for e in edges:
                    if e.startswith('__TRANS_'):
                        covered_transitions.add(e)
                        
    return covered_edges, covered_transitions

def main():
    cov_file = '/home/appuser/elmfuzz/test_aflnet_state/coverage.json'
    elite_file_greedy = '/home/appuser/elmfuzz/test_aflnet_state/elites_100.json'
    elite_file_ilp = '/home/appuser/elmfuzz/test_aflnet_state/elites_u_100.json'
    
    print("Loading full coverage...")
    full_edges, full_transitions = load_coverage(cov_file)
    print(f"Total Unique Edges: {len(full_edges)}")
    print(f"Total Unique Transitions: {len(full_transitions)}")
    print("-" * 30)
    
    print("Analyzing Greedy Selection (elites_100.json)...")
    greedy_edges, greedy_transitions = load_elites(elite_file_greedy)
    print(f"Covered Edges: {len(greedy_edges)} ({len(greedy_edges)/len(full_edges)*100:.2f}%)")
    print(f"Covered Transitions: {len(greedy_transitions)} ({len(greedy_transitions)/len(full_transitions)*100:.2f}%)")
    
    missing_greedy_edges = full_edges - greedy_edges
    missing_greedy_trans = full_transitions - greedy_transitions
    if missing_greedy_edges:
        print(f"Missing Edges: {len(missing_greedy_edges)}")
    if missing_greedy_trans:
        print(f"Missing Transitions: {len(missing_greedy_trans)}")
        
    print("-" * 30)
    
    print("Analyzing ILP Selection (elites_u_100.json)...")
    ilp_edges, ilp_transitions = load_elites(elite_file_ilp)
    print(f"Covered Edges: {len(ilp_edges)} ({len(ilp_edges)/len(full_edges)*100:.2f}%)")
    print(f"Covered Transitions: {len(ilp_transitions)} ({len(ilp_transitions)/len(full_transitions)*100:.2f}%)")
    
    missing_ilp_edges = full_edges - ilp_edges
    missing_ilp_trans = full_transitions - ilp_transitions
    if missing_ilp_edges:
        print(f"Missing Edges: {len(missing_ilp_edges)}")
    if missing_ilp_trans:
        print(f"Missing Transitions: {len(missing_ilp_trans)}")

if __name__ == '__main__':
    main()
