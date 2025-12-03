import click
import json
import sys
import os
import time
from typing import Union, Literal, Optional
import random
from tqdm import tqdm
import heapq

MODEL = 'CodeLlama-13b-hf'

def superior_than(edge_coverage1: set[str], edge_coverage2: set[str]) -> bool:
    return len(edge_coverage1) > len(edge_coverage2) and ((not edge_coverage2) or edge_coverage2.issubset(edge_coverage1))

def inferior_than(edge_coverage1: set[str], edge_coverage2: set[str]) -> bool:
    return len(edge_coverage1) < len(edge_coverage2) and ((not edge_coverage1) or edge_coverage1.issubset(edge_coverage2))

def equal_to(edge_coverage1: set[str], edge_coverage2: set[str]) -> bool:
    return edge_coverage1 == edge_coverage2

def greedy_search(set_family: list[tuple[str, set[str], int]], num: int, baseline: set[str] = set()) -> list[tuple[str, set[str], int]]:
    baseline_edges = set(baseline) if baseline else set()
    current_covered = set(baseline_edges)
    selected = []
    
    # Candidates: list of (key, edges, size)
    remaining = []
    for key, edges, size in set_family:
        remaining.append((key, edges, size))
    
    # CELF (Lazy Greedy) Optimization
    pq = []
    for key, edges, size in remaining:
        gain = len(edges.difference(current_covered))
        # Heap stores (-gain, size, key, edges)
        # We use key as tie breaker for stability
        heapq.heappush(pq, (-gain, size, key, edges))
        
    for _ in tqdm(range(num), desc='Greedy Selecting'):
        if not pq:
            break
            
        while pq:
            neg_gain, size, key, edges = heapq.heappop(pq)
            gain = -neg_gain
            
            # Re-evaluate gain
            real_gain = len(edges.difference(current_covered))
            
            if real_gain == gain:
                # Found the best
                selected.append((key, edges, size))
                current_covered.update(edges)
                break
            else:
                # Push back with updated gain
                heapq.heappush(pq, (-real_gain, size, key, edges))
                
    return selected

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
    coverage: dict[str, dict[str, set[str]]] = {}
    
    if coverage_raw:
        first_val = next(iter(coverage_raw.values()))
        if isinstance(first_val, dict):
            for gen, states in coverage_raw.items():
                for state, files in states.items():
                    if state not in coverage:
                        coverage[state] = {}
                    for filename, edges_list in files.items():
                        edge_set = set(map(lambda x: x.split(':')[0], edges_list))
                        coverage[state][filename] = edge_set
        else:
            for full_key, edges_list in coverage_raw.items():
                if ':' in full_key:
                    state, rest = full_key.split(':', 1)
                else:
                    state = "unknown"
                    rest = full_key
                filename = rest
                if state not in coverage:
                    coverage[state] = {}
                edge_set = set(map(lambda x: x.split(':')[0], edges_list))
                coverage[state][filename] = edge_set
    
    if generation == 'initial' or generation == 'gen0':
        elites = dict()
    else:
        with open(click.format_filename(input_elite_file), 'r') as f:
            elites_raw = json.loads(f.read())

        elites = {}
        if elites_raw:
            first_val = next(iter(elites_raw.values()))
            if isinstance(first_val, dict):
                for gen, states in elites_raw.items():
                    for state, files in states.items():
                        for filename, val in files.items():
                            key = f"{gen}-{state}/{filename}"
                            if isinstance(val, list) and len(val) == 2 and isinstance(val[1], int):
                                edges, size = val
                            else:
                                edges = val
                                size = float('inf')
                            elites[key] = (set(edges), size)
            else:
                elites = {key: (set(edges), size) for key, (edges, size) in elites_raw.items()}
    
    start_time = time.time()
    
    elite_filtering_record: dict[frozenset[str], tuple[str, int]] = dict()
    
    for state, seeds in coverage.items():
        for descendant_key, descendant_edges_raw in seeds.items():
            descendant_edges = frozenset(descendant_edges_raw)
            
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

    # Optimized filtering 1
    sorted_candidates = sorted(
        filtered_descendants0.items(),
        key=lambda x: (len(x[1][0]), -x[1][1]),
        reverse=True
    )

    selected_keys = set()
    kept_edges = [] 

    for key, (edges, size) in sorted_candidates:
        is_inferior = False
        for k_edges in kept_edges:
            if edges.issubset(k_edges):
                is_inferior = True
                break
        
        if not is_inferior:
            selected_keys.add(key)
            kept_edges.append(edges)
            
    filtered_descendants = {k: filtered_descendants0[k] for k in selected_keys}
    
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
        
        # Optimized filtering 2
        sorted_candidates = sorted(
            filtered_new_elites0.items(),
            key=lambda x: (len(x[1][0].union(base_edges)), -x[1][1]),
            reverse=True
        )
        
        selected_keys = set()
        kept_edges = [] 
        
        for key, (edges_raw, size) in sorted_candidates:
            effective_edges = edges_raw.union(base_edges)
            is_inferior = False
            for k_edges in kept_edges:
                if effective_edges.issubset(k_edges):
                    is_inferior = True
                    break
            
            if not is_inferior:
                selected_keys.add(key)
                kept_edges.append(effective_edges)
        
        tmp = dict()
        for s in selected_keys:
            tmp[s] = new_elites[s]
        new_elites = tmp
    
    
    print(f"DEBUG: new_elites size: {len(new_elites)}", file=sys.stderr)
    
    if len(new_elites.items()) > max_elites:
        if len(new_elites) > THRESHOLD_FACTOR * max_elites:
            print(f'WARNING: The number of elites {len(new_elites)} exceeds the limit {max_elites} x {THRESHOLD_FACTOR}', file=sys.stderr)
            
            if baseline is None:
                almost_best = greedy_search(
                    list(map(lambda item: (item[0], set(item[1][0]), item[1][1]), new_elites.items())),
                    max_elites
                )
                tmp = dict()
                for key, edges, size in almost_best:
                    tmp[key] = (list(edges), size)
                new_elites = tmp
            else:
                if len(interesting) < max_elites:
                    interesting_items = []
                    trivial_items = []
                    for k, item in new_elites.items():
                        if k in interesting:
                            interesting_items.append((k, item))
                        elif len(interesting) < max_elites:
                            trivial_items.append((k, item))
                    almost_best = greedy_search(
                        list(map(lambda item: (item[0], set(item[1][0]), item[1][1]), trivial_items)), 
                        max_elites - len(interesting)
                    )
                    tmp = dict()
                    for key, edges, size in almost_best:
                        tmp[key] = (list(edges), size)
                    for item in interesting_items:
                        tmp[item[0]] = item[1]
                    new_elites = tmp
                else:
                    almost_best = greedy_search(
                        list(map(lambda item: (item[0], set(item[1][0]), item[1][1]), new_elites.items())), 
                        max_elites, 
                        base_edges
                    )
                    tmp = dict()
                    for key, edges, size in almost_best:
                        tmp[key] = (list(edges), size)
                    new_elites = tmp
        else:
            print(f'WARNING: The number of elites {len(new_elites)} exceeds the limit {max_elites}', file=sys.stderr)
            if baseline is not None:
                interesting_items = []
                trivial_items = []
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
    
    final_output = {}
    for key, (edges, size) in new_elites.items():
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
        
        final_output[gen_part][state][filename] = [edges, size]
        
    output_elite_file.write(json.dumps(final_output))
    
    for elite_key, (elite_edges, _) in sorted(new_elites.items(), key=lambda item: (len(item[1][0]), -item[1][1])):
        try:
            parts = elite_key.split('-')
            if len(parts) >= 2:
                gen = parts[0]
                rest = '-'.join(parts[1:])
                if '/' in rest:
                    state, generator = rest.split('/', 1)
                else:
                    state = MODEL
                    generator = rest
            else:
                gen = generation
                state = MODEL
                generator = elite_key
        except:
            print(f'DEBUG: elite_key = {elite_key}', file=sys.stderr, flush=True)
            raise
        print(f'{len(elite_edges)} {gen} {state} {generator}', flush=True)
    
if __name__ == '__main__':
    main()
