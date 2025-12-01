import json
import sys
import os

def get_transitions(state_str):
    """
    Parses a state string (e.g., "0-200-201") into a set of transitions (e.g., {("0", "200"), ("200", "201")}).
    Handles 'end-at-' by truncating the sequence before it, as it represents omitted transitions.
    """
    if not state_str:
        return set()
    
    # Handle end-at- marker: ignore everything from end-at- onwards
    end_at_index = state_str.find('end-at-')
    if end_at_index != -1:
        # Truncate string before 'end-at-'
        # Note: usually preceded by a hyphen, e.g., "A-B-end-at-C"
        # If we cut at index, we might leave a trailing hyphen, strip it.
        clean_str = state_str[:end_at_index]
        if clean_str.endswith('-'):
            clean_str = clean_str[:-1]
    else:
        clean_str = state_str

    parts = clean_str.split('-')
    # Filter out empty strings if any
    states = [p for p in parts if p]
    
    transitions = set()
    for i in range(len(states) - 1):
        transitions.add((states[i], states[i+1]))
    
    return transitions

def extract_state_string(filename):
    """
    Extracts the state string from a filename.
    Expected format: "...:state:0-200-..."
    """
    if ':state:' in filename:
        try:
            return filename.split(':state:')[1]
        except IndexError:
            return None
    return None

def main():
    coverage_file = 'coverage.json'
    selected_file = 'selected_elites.json'
    
    print(f"Loading {coverage_file}...")
    with open(coverage_file, 'r') as f:
        coverage_data = json.load(f)
        
    print(f"Loading {selected_file}...")
    with open(selected_file, 'r') as f:
        selected_data = json.load(f)

    # 1. Collect ALL transitions from coverage.json (The Universe of Transitions)
    # And map each transition to the seeds that cover it
    all_transitions = set()
    transition_to_seeds = {} # (src, dst) -> list of filenames

    total_seeds_scanned = 0
    
    # coverage.json structure: Gen -> State -> Filename -> Edges
    for gen, states in coverage_data.items():
        for state_group, files in states.items():
            for filename in files.keys():
                total_seeds_scanned += 1
                st_str = extract_state_string(filename)
                if st_str:
                    trans = get_transitions(st_str)
                    for t in trans:
                        all_transitions.add(t)
                        if t not in transition_to_seeds:
                            transition_to_seeds[t] = []
                        transition_to_seeds[t].append(filename)

    print(f"Total seeds scanned in coverage.json: {total_seeds_scanned}")
    print(f"Total unique transitions found: {len(all_transitions)}")

    # 2. Collect Covered transitions from selected_elites.json
    covered_transitions = set()
    selected_seeds_count = 0
    
    # selected_elites.json structure: Gen -> State -> Filename -> Edges
    for gen, states in selected_data.items():
        for state_group, files in states.items():
            for filename in files.keys():
                selected_seeds_count += 1
                st_str = extract_state_string(filename)
                if st_str:
                    trans = get_transitions(st_str)
                    covered_transitions.update(trans)

    print(f"Total selected seeds: {selected_seeds_count}")
    print(f"Covered transitions: {len(covered_transitions)}")

    # 3. Determine Missing Transitions
    missing_transitions = all_transitions - covered_transitions
    print(f"Missing transitions: {len(missing_transitions)}")
    
    if missing_transitions:
        print("\n=== Missing Transitions Details ===")
        sorted_missing = sorted(list(missing_transitions))
        
        for t in sorted_missing:
            seeds = transition_to_seeds[t]
            print(f"\nTransition: {t[0]} -> {t[1]}")
            print(f"  Covered by {len(seeds)} seeds in original set.")
            print(f"  Seeds: {seeds}")

if __name__ == '__main__':
    main()
