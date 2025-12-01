import click
import json
import sys
import os
import time
from typing import Union, Literal, Optional
import random
from tqdm import tqdm

MODEL = 'CodeLlama-13b-hf'

def superior_than(edge_coverage1: set[str], edge_coverage2: set[str]) -> bool:
    return len(edge_coverage1) > len(edge_coverage2) and ((not edge_coverage2) or edge_coverage2.issubset(edge_coverage1))

def inferior_than(edge_coverage1: set[str], edge_coverage2: set[str]) -> bool:
    return len(edge_coverage1) < len(edge_coverage2) and ((not edge_coverage1) or edge_coverage1.issubset(edge_coverage2))

def equal_to(edge_coverage1: set[str], edge_coverage2: set[str]) -> bool:
    return edge_coverage1 == edge_coverage2

@click.command()
@click.option('--generation', '-g', type=str)
@click.option('--current-covfile', '-c', 'current_covfile', type=click.Path(exists=False), help='Current coverage file')
@click.option('--max-elites', '-n', 'max_elites', type=int)
@click.option('--input-elite-file', '-i', 'input_elite_file', type=click.Path(exists=False), help='Elite seeds file')
@click.option('--output-elite-file', '-o', 'output_elite_file', type=click.File('w'), help='Elite seeds file')
@click.option('--baseline', '-b', type=click.Path(exists=False), default=None)
def main(generation: str, current_covfile, max_elites: int, input_elite_file, output_elite_file, baseline):
    if generation == 'initial':
        coverage_raw = dict()
    else:
        with open(click.format_filename(current_covfile), 'r') as f:
            coverage_raw = json.loads(f.read())
    ELMFUZZ_RUNDIR = os.environ.get('ELMFUZZ_RUNDIR')
    
    if baseline is not None:
        with open(click.format_filename(baseline)) as base_edges_f:
            base_edges: set[str] = set()
            for l in base_edges_f:
                if not l.strip():
                    continue
                base_edges.add(l.strip())
    
    # Reconstruct coverage dict
    # Support both nested (Gen->State->File) and flat (State:File) formats
    coverage: dict[str, dict[str, set[str]]] = {}
    
    if coverage_raw:
        first_val = next(iter(coverage_raw.values()))
        if isinstance(first_val, dict):
            # Nested format: Gen -> State -> Filename -> Edges
            for gen, states in coverage_raw.items():
                for state, files in states.items():
                    if state not in coverage:
                        coverage[state] = {}
                    for filename, edges_list in files.items():
                        edge_set = set(map(lambda x: x.split(':')[0], edges_list))
                        coverage[state][filename] = edge_set
        else:
            # Flat format: "STATE:FILENAME:state:..." or "STATE:FILENAME"
            for full_key, edges_list in coverage_raw.items():
                # Extract state
                if ':' in full_key:
                    state, rest = full_key.split(':', 1)
                else:
                    state = "unknown"
                    rest = full_key
                    
                # Extract filename from rest
                # Keep :state:... suffix as requested
                filename = rest
                    
                if state not in coverage:
                    coverage[state] = {}
                    
                edge_set = set(map(lambda x: x.split(':')[0], edges_list))
                coverage[state][filename] = edge_set
    
    if generation == 'initial' or generation == 'gen0':
        elites = dict()
    else:
        with open(click.format_filename(input_elite_file), 'r') as f:
            elites_raw: dict[str, tuple[list[str], int]] = json.loads(f.read())
            # The edge sets of the elites cannot be a subset of each other
            elites = {key: (set(edges), size) for key, (edges, size) in elites_raw.items()}
    
    start_time = time.time()
    
    elite_filtering_record: dict[frozenset[str], tuple[str, int]] = dict()
    
    for state, seeds in coverage.items():
        for descendant_key, descendant_edges_raw in seeds.items():
            descendant_edges = frozenset(descendant_edges_raw)
            
            # Extract real filename for disk access
            if ':state:' in descendant_key:
                real_filename = descendant_key.split(':state:', 1)[0]
            else:
                real_filename = descendant_key

            path1 = os.path.join(ELMFUZZ_RUNDIR, generation, 'aflnetout', state, 'queue', real_filename)
            path2 = os.path.join(ELMFUZZ_RUNDIR, generation, 'aflnetout', state, real_filename)
            
            if os.path.exists(path1):
                descendant_size = os.path.getsize(path1)
            elif os.path.exists(path2):
                descendant_size = os.path.getsize(path2)
            else:
                continue

            # Use a composite key to ensure uniqueness across states
            unique_key = f"{state}/{descendant_key}"
            
            if descendant_edges in elite_filtering_record:
                record_key, record_size = elite_filtering_record[descendant_edges]
                if descendant_size < record_size:
                    elite_filtering_record[descendant_edges] = (unique_key, descendant_size)
            else:
                elite_filtering_record[descendant_edges] = (unique_key, descendant_size)
    filtered_descendants0: dict[str, tuple[set[str], int]] = dict()
    for descendant_edges, (descendant_key, descendant_size) in elite_filtering_record.items():
        filtered_descendants0[descendant_key] = (set(descendant_edges), descendant_size)

    filtered_descendants: dict[str, tuple[set[str], int]] = dict()
    
    comparison_raw: dict[tuple[str, str], Union[Literal['l'], Literal['r'], Literal['b']]] = dict()
    for elite_key1, (elite_edges1, elite_size1) in filtered_descendants0.items():
        for elite_key2, (elite_edges2, elite_size2) in filtered_descendants0.items():
            if elite_key1 == elite_key2 or (elite_key2, elite_key1) in comparison_raw:
                continue
            else:
                if equal_to(elite_edges1, elite_edges2):
                    if elite_size2 < elite_size1:
                        comparison_raw[(elite_key1, elite_key2)] = 'r'
                    else:
                        comparison_raw[(elite_key1, elite_key2)] = 'l'
                elif superior_than(elite_edges1, elite_edges2):
                    comparison_raw[(elite_key1, elite_key2)] = 'l'
                elif inferior_than(elite_edges1, elite_edges2):
                    comparison_raw[(elite_key1, elite_key2)] = 'r'
                else:
                    comparison_raw[(elite_key1, elite_key2)] = 'b'
                    
    comparison: dict[str, dict[str, Union[Literal['l'], Literal['r'], Literal['b']]]] = dict()
    for (key1, key2), comp in comparison_raw.items():
        if key1 not in comparison:
            comparison[key1] = dict()
        comparison[key1][key2] = comp
    
    selected: set[str] = set()
    for key in filtered_descendants0.keys():
        comps = comparison.get(key, {})
        if not any(comp == 'r' for comp in comps.values()):
            selected.add(key)
    for key in selected:
        filtered_descendants[key] = filtered_descendants0[key]
    
    replace: dict[str, str] = dict()
    newly_added = set()
    failed_descendant = set()
    if not elites:
        newly_added.update(filtered_descendants.keys())
    else:
        for elite_key, (elite_edges, elite_size) in elites.items():
            for descendant_key, (descendant_edges, descendant_size) in filtered_descendants.items():
                if descendant_key in failed_descendant:
                    continue
                if equal_to(descendant_edges, elite_edges):
                    if descendant_size < elite_size:
                        replace[elite_key] = descendant_key
                    else:
                        failed_descendant.add(descendant_key)
                elif superior_than(descendant_edges, elite_edges):
                    replace[elite_key] = descendant_key
                elif inferior_than(descendant_edges, elite_edges):
                    failed_descendant.add(descendant_key)
                else:
                    newly_added.add(descendant_key)
    
    new_elites: dict[str, tuple[list[str], int]] = dict()
    
    for elite_key, (elite_edges, elite_size) in elites.items():
        if elite_key in replace:
            replaced_by = replace[elite_key]
            s, sz = filtered_descendants[replaced_by]
            new_elites[f'{generation}-{replaced_by}'] = (list(s), sz)
        else:
            new_elites[elite_key] = (list(elite_edges), elite_size)
    
    for n in newly_added:
        s, sz = filtered_descendants[n]
        new_elites[f'{generation}-{n}'] = (list(s), sz)

    if baseline is not None:
        max_interesting_edges = 0
        interesting = set()
        for elite_key, (elite_edges, _) in new_elites.items():
            edge_set = set(elite_edges)
            if not inferior_than(edge_set, base_edges):
                interesting.add(elite_key)
                interesting_edges = len(edge_set.difference(base_edges))
                max_interesting_edges = max(max_interesting_edges, interesting_edges)
        if interesting:
            print(f'Found {len(interesting)} interesting elites with max interesting edges {max_interesting_edges}', file=sys.stderr)
    
    THRESHOLD_FACTOR = 1
    if baseline is not None and len(interesting) > THRESHOLD_FACTOR * max_elites:
        print(f'WARNING: The number of interesting elites {len(interesting)} exceeds the limit {max_elites} x {THRESHOLD_FACTOR}', file=sys.stderr)
        
        new_elites_filtering: dict[frozenset[str], tuple[str, int]] = dict()

        for elite_key, (elite_edges_raw, elite_size) in new_elites.items():
            elite_edges = frozenset(set(elite_edges_raw).union(base_edges))
            if elite_edges in new_elites_filtering:
                record_key, record_size = new_elites_filtering[elite_edges]
                if elite_size < record_size:
                    new_elites_filtering[elite_edges] = (elite_key, elite_size)
            else:
                new_elites_filtering[elite_edges] = (elite_key, elite_size)
        
        filtered_new_elites0: dict[str, tuple[set[str], int]] = dict()
        for elite_edges, (elite_key, elite_size) in new_elites_filtering.items():
            filtered_new_elites0[elite_key] = (set(elite_edges), elite_size)
        
        
        comparison_raw: dict[tuple[str, str], Union[Literal['l'], Literal['r'], Literal['b']]] = dict()
        for elite_key1, (elite_edges1_raw, elite_size1) in filtered_new_elites0.items():
            elite_edges1 = elite_edges1_raw.union(base_edges)
            for elite_key2, (elite_edges2_raw, elite_size2) in filtered_new_elites0.items():
                elite_edges2 = elite_edges2_raw.union(base_edges)
                if elite_key1 == elite_key2 or (elite_key2, elite_key1) in comparison_raw:
                    continue
                else:
                    if equal_to(elite_edges1, elite_edges2):
                        if elite_size2 < elite_size1:
                            comparison_raw[(elite_key1, elite_key2)] = 'l'
                        else:
                            comparison_raw[(elite_key1, elite_key2)] = 'r'
                    elif superior_than(elite_edges1, elite_edges2):
                        comparison_raw[(elite_key1, elite_key2)] = 'l'
                    elif inferior_than(elite_edges1, elite_edges2):
                        comparison_raw[(elite_key1, elite_key2)] = 'r'
                    else:
                        comparison_raw[(elite_key1, elite_key2)] = 'b'
                        
        comparison: dict[str, dict[str, Union[Literal['l'], Literal['r'], Literal['b']]]] = dict()
        for (key1, key2), comp in comparison_raw.items():
            if key1 not in comparison:
                comparison[key1] = dict()
            comparison[key1][key2] = comp
        
        selected: set[str] = set()
        for key in filtered_new_elites0.keys():
            comps = comparison.get(key, {})
            if not any(comp == 'r' for comp in comps.values()):
                selected.add(key)
        tmp = dict()
        for s in selected:
            tmp[s] = new_elites[s]
        new_elites = tmp
    
    
    if len(new_elites.items()) > max_elites:
        print(f'WARNING: The number of elites {len(new_elites)} exceeds the limit {max_elites} x {THRESHOLD_FACTOR}', file=sys.stderr)
    
    elite_filtering_record: dict[frozenset[str], tuple[str, int]] = dict()
    
    for state, seeds in coverage.items():
        print(f"DEBUG: State {state} has {len(seeds)} seeds", file=sys.stderr)
        for descendant_key, descendant_edges_raw in seeds.items():
            descendant_edges = frozenset(descendant_edges_raw)
            
            # Extract real filename for disk access
            if ':state:' in descendant_key:
                real_filename = descendant_key.split(':state:', 1)[0]
            else:
                real_filename = descendant_key

            path1 = os.path.join(ELMFUZZ_RUNDIR, generation, 'aflnetout', state, 'queue', real_filename)
            path2 = os.path.join(ELMFUZZ_RUNDIR, generation, 'aflnetout', state, real_filename)
            
            if os.path.exists(path1):
                descendant_size = os.path.getsize(path1)
            elif os.path.exists(path2):
                descendant_size = os.path.getsize(path2)
            else:
                # print(f"DEBUG: File not found: {real_filename}", file=sys.stderr)
                continue

            # Use a composite key to ensure uniqueness across states
            unique_key = f"{state}/{descendant_key}"
            
            if descendant_edges in elite_filtering_record:
                record_key, record_size = elite_filtering_record[descendant_edges]
                if descendant_size < record_size:
                    elite_filtering_record[descendant_edges] = (unique_key, descendant_size)
            else:
                elite_filtering_record[descendant_edges] = (unique_key, descendant_size)
    filtered_descendants0: dict[str, tuple[set[str], int]] = dict()
    for descendant_edges, (descendant_key, descendant_size) in elite_filtering_record.items():
        filtered_descendants0[descendant_key] = (set(descendant_edges), descendant_size)

    print(f"DEBUG: filtered_descendants0 size: {len(filtered_descendants0)}", file=sys.stderr)
    
    filtered_descendants: dict[str, tuple[set[str], int]] = dict()
    
    comparison_raw: dict[tuple[str, str], Union[Literal['l'], Literal['r'], Literal['b']]] = dict()
    for elite_key1, (elite_edges1, elite_size1) in filtered_descendants0.items():
        for elite_key2, (elite_edges2, elite_size2) in filtered_descendants0.items():
            if elite_key1 == elite_key2 or (elite_key2, elite_key1) in comparison_raw:
                continue
            else:
                if equal_to(elite_edges1, elite_edges2):
                    if elite_size2 < elite_size1:
                        comparison_raw[(elite_key1, elite_key2)] = 'r'
                    else:
                        comparison_raw[(elite_key1, elite_key2)] = 'l'
                elif superior_than(elite_edges1, elite_edges2):
                    comparison_raw[(elite_key1, elite_key2)] = 'l'
                elif inferior_than(elite_edges1, elite_edges2):
                    comparison_raw[(elite_key1, elite_key2)] = 'r'
                else:
                    comparison_raw[(elite_key1, elite_key2)] = 'b'
                    
    comparison: dict[str, dict[str, Union[Literal['l'], Literal['r'], Literal['b']]]] = dict()
    for (key1, key2), comp in comparison_raw.items():
        if key1 not in comparison:
            comparison[key1] = dict()
        comparison[key1][key2] = comp
    
    selected: set[str] = set()
    for key in filtered_descendants0.keys():
        comps = comparison.get(key, {})
        if not any(comp == 'r' for comp in comps.values()):
            selected.add(key)
    for key in selected:
        filtered_descendants[key] = filtered_descendants0[key]
    
    replace: dict[str, str] = dict()
    newly_added = set()
    failed_descendant = set()
    if not elites:
        newly_added.update(filtered_descendants.keys())
    else:
        for elite_key, (elite_edges, elite_size) in elites.items():
            for descendant_key, (descendant_edges, descendant_size) in filtered_descendants.items():
                if descendant_key in failed_descendant:
                    continue
                if equal_to(descendant_edges, elite_edges):
                    if descendant_size < elite_size:
                        replace[elite_key] = descendant_key
                    else:
                        failed_descendant.add(descendant_key)
                elif superior_than(descendant_edges, elite_edges):
                    replace[elite_key] = descendant_key
                elif inferior_than(descendant_edges, elite_edges):
                    failed_descendant.add(descendant_key)
                else:
                    newly_added.add(descendant_key)
    
    new_elites: dict[str, tuple[list[str], int]] = dict()
    
    for elite_key, (elite_edges, elite_size) in elites.items():
        if elite_key in replace:
            replaced_by = replace[elite_key]
            s, sz = filtered_descendants[replaced_by]
            new_elites[f'{generation}-{replaced_by}'] = (list(s), sz)
        else:
            new_elites[elite_key] = (list(elite_edges), elite_size)
    
    for n in newly_added:
        s, sz = filtered_descendants[n]
        new_elites[f'{generation}-{n}'] = (list(s), sz)

    if baseline is not None:
        max_interesting_edges = 0
        interesting = set()
        for elite_key, (elite_edges, _) in new_elites.items():
            edge_set = set(elite_edges)
            if not inferior_than(edge_set, base_edges):
                interesting.add(elite_key)
                interesting_edges = len(edge_set.difference(base_edges))
                max_interesting_edges = max(max_interesting_edges, interesting_edges)
        if interesting:
            print(f'Found {len(interesting)} interesting elites with max interesting edges {max_interesting_edges}', file=sys.stderr)
    
    THRESHOLD_FACTOR = 1
    if baseline is not None and len(interesting) > THRESHOLD_FACTOR * max_elites:
        print(f'WARNING: The number of interesting elites {len(interesting)} exceeds the limit {max_elites} x {THRESHOLD_FACTOR}', file=sys.stderr)
        
        new_elites_filtering: dict[frozenset[str], tuple[str, int]] = dict()

        for elite_key, (elite_edges_raw, elite_size) in new_elites.items():
            elite_edges = frozenset(set(elite_edges_raw).union(base_edges))
            if elite_edges in new_elites_filtering:
                record_key, record_size = new_elites_filtering[elite_edges]
                if elite_size < record_size:
                    new_elites_filtering[elite_edges] = (elite_key, elite_size)
            else:
                new_elites_filtering[elite_edges] = (elite_key, elite_size)
        
        filtered_new_elites0: dict[str, tuple[set[str], int]] = dict()
        for elite_edges, (elite_key, elite_size) in new_elites_filtering.items():
            filtered_new_elites0[elite_key] = (set(elite_edges), elite_size)
        
        
        comparison_raw: dict[tuple[str, str], Union[Literal['l'], Literal['r'], Literal['b']]] = dict()
        for elite_key1, (elite_edges1_raw, elite_size1) in filtered_new_elites0.items():
            elite_edges1 = elite_edges1_raw.union(base_edges)
            for elite_key2, (elite_edges2_raw, elite_size2) in filtered_new_elites0.items():
                elite_edges2 = elite_edges2_raw.union(base_edges)
                if elite_key1 == elite_key2 or (elite_key2, elite_key1) in comparison_raw:
                    continue
                else:
                    if equal_to(elite_edges1, elite_edges2):
                        if elite_size2 < elite_size1:
                            comparison_raw[(elite_key1, elite_key2)] = 'l'
                        else:
                            comparison_raw[(elite_key1, elite_key2)] = 'r'
                    elif superior_than(elite_edges1, elite_edges2):
                        comparison_raw[(elite_key1, elite_key2)] = 'l'
                    elif inferior_than(elite_edges1, elite_edges2):
                        comparison_raw[(elite_key1, elite_key2)] = 'r'
                    else:
                        comparison_raw[(elite_key1, elite_key2)] = 'b'
                        
        comparison: dict[str, dict[str, Union[Literal['l'], Literal['r'], Literal['b']]]] = dict()
        for (key1, key2), comp in comparison_raw.items():
            if key1 not in comparison:
                comparison[key1] = dict()
            comparison[key1][key2] = comp
        
        selected: set[str] = set()
        for key in filtered_new_elites0.keys():
            comps = comparison.get(key, {})
            if not any(comp == 'r' for comp in comps.values()):
                selected.add(key)
        tmp = dict()
        for s in selected:
            tmp[s] = new_elites[s]
        new_elites = tmp
    
    
    print(f"DEBUG: new_elites size: {len(new_elites)}", file=sys.stderr)
    
    if len(new_elites.items()) > max_elites:
        if len(new_elites) > THRESHOLD_FACTOR * max_elites:
            print(f'WARNING: The number of elites {len(new_elites)} exceeds the limit {max_elites} x {THRESHOLD_FACTOR}', file=sys.stderr)
            def random_search(set_family: list[tuple[str, set[str], int]], num: int = max_elites, baseline: set[str] = set()) -> list[tuple[str, set[str], int]]:
                from collections import Counter
                
                baseline_edges = set(baseline) if baseline else set()
                TRY_TIMES = 3
                
                candidates_history = []
                
                # Pre-calculate indices to avoid recreating list
                candidate_pool_indices = list(range(len(set_family)))
                
                for _ in tqdm(range(TRY_TIMES), desc='Selecting'):
                    # 1. Initialization
                    selected_indices = random.sample(candidate_pool_indices, num)
                    selected = [set_family[i] for i in selected_indices]
                    
                    edge_counts = Counter()
                    for e in baseline_edges:
                        edge_counts[e] += 1
                    for _, edges, _ in selected:
                        edge_counts.update(edges)
                    
                    current_coverage = len(edge_counts)
                    current_max_size = max(s for _, _, s in selected) if selected else 0
                    
                    selected_keys = {item[0] for item in selected}
                    
                    changed = True
                    
                    # 2. Iterative Optimization
                    while changed:
                        changed = False
                        random.shuffle(candidate_pool_indices)
                        
                        for idx in candidate_pool_indices:
                            new_seed = set_family[idx]
                            new_key, new_edges, new_size = new_seed
                            
                            if new_key in selected_keys:
                                continue
                            
                            # Try to replace each OldSeed in Selected
                            for i in range(num):
                                old_seed = selected[i]
                                old_key, old_edges, old_size = old_seed
                                
                                # --- Delta Calculation ---
                                # Loss: edges in OldSeed that would drop to count 0
                                # (count is 1 AND not in NewSeed)
                                loss = 0
                                for e in old_edges:
                                    if edge_counts[e] == 1 and e not in new_edges:
                                        loss += 1
                                
                                # Gain: edges in NewSeed that are currently count 0
                                gain = 0
                                for e in new_edges:
                                    if edge_counts[e] == 0:
                                        gain += 1
                                
                                new_coverage = current_coverage - loss + gain
                                
                                # New Max Size
                                if old_size == current_max_size:
                                    if new_size >= current_max_size:
                                        new_max_size = new_size
                                    else:
                                        # Scan required
                                        temp_max = 0
                                        for k in range(num):
                                            if k != i:
                                                s_size = selected[k][2]
                                                if s_size > temp_max:
                                                    temp_max = s_size
                                        new_max_size = max(temp_max, new_size)
                                else:
                                    new_max_size = max(current_max_size, new_size)
                                
                                # --- Acceptance Criteria ---
                                is_better = False
                                if new_coverage > current_coverage:
                                    is_better = True
                                elif new_coverage == current_coverage and new_max_size < current_max_size:
                                    is_better = True
                                
                                # --- Update State ---
                                if is_better:
                                    selected[i] = new_seed
                                    selected_keys.remove(old_key)
                                    selected_keys.add(new_key)
                                    
                                    edge_counts.subtract(old_edges)
                                    edge_counts.update(new_edges)
                                    
                                    current_coverage = new_coverage
                                    current_max_size = new_max_size
                                    changed = True
                                    break 
                    
                    candidates_history.append((selected, current_coverage, current_max_size))
                
                candidates_history.sort(key=lambda x: (-x[1], x[2]))
                print(f'Get almost bests: {" ".join(map(lambda x: f"({x[1]}, {x[2]})", candidates_history))}', file=sys.stderr)
                return candidates_history[0][0]
            if baseline is None:
                almost_best = random_search(
                    list(map(lambda item: (item[0], set(item[1][0]), item[1][1]), new_elites.items())),
                )
                tmp = dict()
                for key, edges, size in almost_best:
                    tmp[key] = (list(edges), size)
                new_elites = tmp
            else:
                if len(interesting) < max_elites:
                    interesting_items: list[tuple[str, tuple[list[str], int]]] = list()
                    trivial_items: list[tuple[str, tuple[list[str], int]]] = list()
                    for k, item in new_elites.items():
                        if k in interesting:
                            interesting_items.append((k, item))
                        elif len(interesting) < max_elites:
                            trivial_items.append((k, item))
                    almost_best = random_search(list(map(lambda item: (item[0], set(item[1][0]), item[1][1]), trivial_items)), max_elites - len(interesting))
                    tmp: dict[str, tuple[list[str], int]] = dict()
                    for key, edges, size in almost_best:
                        tmp[key] = (list(edges), size)
                    for item in interesting_items:
                        tmp[item[0]] = item[1]
                    new_elites = tmp
                else:
                    almost_best = random_search(list(map(lambda item: (item[0], set(item[1][0]), item[1][1]), new_elites.items())), max_elites, base_edges)
                    tmp = dict()
                    for key, edges, size in almost_best:
                        tmp[key] = (list(edges), size)
                    new_elites = tmp
        else:
            print(f'WARNING: The number of elites {len(new_elites)} exceeds the limit {max_elites}', file=sys.stderr)
            if baseline is not None:
                interesting_items: list[tuple[str, tuple[list[str], int]]] = list()
                trivial_items: list[tuple[str, tuple[list[str], int]]] = list()
                for k, item in new_elites.items():
                    if k in interesting:
                        interesting_items.append((k, item))
                    elif len(interesting) < max_elites:
                        trivial_items.append((k, item))
                sorted_intrested = sorted(interesting_items, key=lambda item: (-len(set(item[1][0]).union(base_edges)), item[1][1]))
                if len(interesting) >= max_elites:
                    new_elites = dict(sorted_intrested[:max_elites])
                else:
                    sorted_trivial = sorted(trivial_items, key=lambda item: (-len(item[1][0]), item[1][1]))
                    new_elites = dict(sorted_intrested + sorted_trivial[:max_elites - len(sorted_intrested)])
            else:
                new_elites = dict(sorted(new_elites.items(), key=lambda item: (-len(item[1][0]), item[1][1]))[:max_elites])
    if set(new_elites.keys()) != set(elites.keys()):
        print('Elites updated', file=sys.stderr)
    
    end_time = time.time()
    print(f'Selection time: {end_time - start_time:.4f} seconds', file=sys.stderr)
    
    # Reformat output to nested structure: gen -> state -> filename -> edges
    final_output = {}
    for key, (edges, size) in new_elites.items():
        # key format: "generation-state/filename"
        try:
            gen_part, rest = key.split('-', 1)
            if '/' in rest:
                state, filename = rest.split('/', 1)
            else:
                state = "unknown"
                filename = rest
        except ValueError:
             gen_part = "unknown"
             state = "unknown"
             filename = key

        if gen_part not in final_output:
            final_output[gen_part] = {}
        if state not in final_output[gen_part]:
            final_output[gen_part][state] = {}
        
        final_output[gen_part][state][filename] = edges
        
    output_elite_file.write(json.dumps(final_output))
    
    for elite_key, (elite_edges, _) in sorted(new_elites.items(), key=lambda item: (len(item[1][0]), -item[1][1])):
        try:
            # Try to split by '-' first (legacy format: gen-generator)
            parts = elite_key.split('-')
            if len(parts) >= 2:
                gen = parts[0]
                # The rest might contain state/generator
                rest = '-'.join(parts[1:])
                if '/' in rest:
                    state, generator = rest.split('/', 1)
                else:
                    state = MODEL
                    generator = rest
            else:
                # Fallback
                gen = generation
                state = MODEL
                generator = elite_key
        except:
            print(f'DEBUG: elite_key = {elite_key}', file=sys.stderr, flush=True)
            raise
        print(f'{len(elite_edges)} {gen} {state} {generator}', flush=True)
    
if __name__ == '__main__':
    main()
