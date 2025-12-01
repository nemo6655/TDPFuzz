import json
import os

COV_FILE = 'coverage.json'
ELITES_FILE = 'selected_elites.json'

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

def main():
    # 1. Load All Seeds
    with open(COV_FILE, 'r') as f:
        cov_data = json.load(f)
    
    all_seeds_transitions = {} # key -> set of transitions
    all_transitions_set = set()

    if not cov_data:
        print("Coverage file is empty.")
        return

    first_val = next(iter(cov_data.values()))
    if isinstance(first_val, dict):
        for gen, states in cov_data.items():
            for state, files in states.items():
                for key, edges in files.items():
                    _, trans_str = parse_key(key)
                    trans = extract_transitions(trans_str)
                    all_seeds_transitions[key] = trans
                    all_transitions_set.update(trans)
    else:
        for key, edges in cov_data.items():
            _, trans_str = parse_key(key)
            trans = extract_transitions(trans_str)
            all_seeds_transitions[key] = trans
            all_transitions_set.update(trans)

    # 2. Load Selected Elites
    with open(ELITES_FILE, 'r') as f:
        elite_data = json.load(f)
        
    selected_transitions_set = set()
    for gen, states in elite_data.items():
        for state, files in states.items():
            for key, edges in files.items():
                _, trans_str = parse_key(key)
                selected_transitions_set.update(extract_transitions(trans_str))

    # 3. Find Missing
    missing_transitions = all_transitions_set - selected_transitions_set
    
    print(f"Total Unique Transitions in All Seeds: {len(all_transitions_set)}")
    print(f"Total Unique Transitions in Selected Elites: {len(selected_transitions_set)}")
    print(f"Missing Transitions Count: {len(missing_transitions)}")
    
    if missing_transitions:
        print("\nMissing Transitions:")
        for t in sorted(missing_transitions):
            print(f"  {t}")
            
        # Find seeds containing these
        seeds_with_missing = []
        for key, trans in all_seeds_transitions.items():
            if not trans.isdisjoint(missing_transitions):
                seeds_with_missing.append(key)
        
        print(f"\nNumber of seeds containing at least one missing transition: {len(seeds_with_missing)}")
        # print("Seeds:")
        # for s in seeds_with_missing:
        #     print(f"  {s}")

if __name__ == '__main__':
    main()
