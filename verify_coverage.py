import json
import os

def load_cov_json(filepath):
    with open(filepath, 'r') as f:
        data = json.load(f)
    edges = set()
    for seed_name, edge_list in data.items():
        for item in edge_list:
            # Format is "edge_id:count"
            edge_id = item.split(':')[0]
            edges.add(edge_id)
    return edges

def load_selected_elites(filepath):
    with open(filepath, 'r') as f:
        data = json.load(f)
    
    edges = set()
    # Structure: gen -> state -> filename -> [edge_ids]
    for gen, states in data.items():
        for state, files in states.items():
            for filename, edge_list in files.items():
                edges.update(edge_list)
    return edges

def main():
    base_dir = '/home/appuser/elmfuzz/preset/live555/gen1/aflnetout'
    cov_files = ['cov_0001.json', 'cov_0002.json']
    
    total_edges = set()
    for cf in cov_files:
        path = os.path.join(base_dir, cf)
        print(f"Loading {path}...")
        file_edges = load_cov_json(path)
        print(f"  Found {len(file_edges)} unique edges in {cf}")
        total_edges.update(file_edges)
    
    print(f"Total unique edges in seed set: {len(total_edges)}")
    
    selected_path = '/home/appuser/elmfuzz/selected_elites.json'
    print(f"Loading {selected_path}...")
    selected_edges = load_selected_elites(selected_path)
    print(f"Total unique edges in selected elites: {len(selected_edges)}")
    
    missing_edges = total_edges - selected_edges
    
    if not missing_edges:
        print("SUCCESS: Selected seeds cover ALL edges in the seed set.")
    else:
        print(f"FAILURE: {len(missing_edges)} edges are NOT covered by the selected seeds.")
        # print(f"Missing edges: {missing_edges}")

if __name__ == '__main__':
    main()
