#!/usr/bin/env python3
"""
Extract state transitions from AFLNet seed_cov files and compare ALL vs ELITE seeds.

For each generation N:
  - ALL seeds: all seed_cov files from gen N/aflnetout/<pool>/seed_cov/
  - ELITE seeds: seed_cov files from gen N+1/aflnetout/0000/seed_cov/
    (gen N's elite seeds become gen N+1's pool 0000 initial seeds)

The first line of each seed_cov file contains: state:S1-S2-S3-...-Sn::::
From this, state transitions __TRANS_S1_S2__, __TRANS_S2_S3__, etc. are extracted.
"""

import os
import sys
import json
import argparse
from collections import defaultdict


def extract_state_sequence(filepath):
    """Read the first line of a seed_cov file and return the state sequence list."""
    try:
        with open(filepath, 'r', errors='ignore') as f:
            first_line = f.readline().strip()
        if first_line.startswith('state:') and '::::' in first_line:
            state_part = first_line.split('state:', 1)[1].split('::::', 1)[0]
            states = [s for s in state_part.split('-') if s]
            return states
        return None
    except Exception:
        return None


def states_to_transitions(states):
    """Convert a state sequence [S1, S2, S3, ...] to a set of __TRANS_Si_Sj__."""
    transitions = set()
    for i in range(len(states) - 1):
        src, dst = states[i], states[i + 1]
        transitions.add(f"__TRANS_{src}_{dst}__")
    return transitions


def collect_seed_cov_dir(seed_cov_dir):
    """Collect all seed_cov files from a directory, return {seed_name: transitions_set}."""
    results = {}
    if not os.path.isdir(seed_cov_dir):
        return results
    for fname in os.listdir(seed_cov_dir):
        fpath = os.path.join(seed_cov_dir, fname)
        if not os.path.isfile(fpath):
            continue
        states = extract_state_sequence(fpath)
        if states and len(states) >= 2:
            results[fname] = states_to_transitions(states)
    return results


def collect_all_seeds(gen_dir):
    """Collect ALL seeds from gen_dir/aflnetout/<all_pools>/seed_cov/"""
    aflnetout = os.path.join(gen_dir, 'aflnetout')
    all_transitions = {}  # seed_name -> transitions set
    all_unique = set()

    if not os.path.isdir(aflnetout):
        return all_transitions, all_unique

    for pool_name in sorted(os.listdir(aflnetout)):
        pool_path = os.path.join(aflnetout, pool_name)
        if not os.path.isdir(pool_path):
            continue
        seed_cov_dir = os.path.join(pool_path, 'seed_cov')
        seeds = collect_seed_cov_dir(seed_cov_dir)
        all_transitions.update(seeds)
        for transitions in seeds.values():
            all_unique.update(transitions)

    return all_transitions, all_unique


def collect_elite_seeds(next_gen_dir):
    """Collect ELITE seeds from next_gen_dir/aflnetout/<all_pools>/seed_cov/"""
    aflnetout = os.path.join(next_gen_dir, 'aflnetout')
    all_seeds = {}
    elite_unique = set()

    if not os.path.isdir(aflnetout):
        return all_seeds, elite_unique

    for pool_name in sorted(os.listdir(aflnetout)):
        pool_path = os.path.join(aflnetout, pool_name)
        if not os.path.isdir(pool_path):
            continue
        seed_cov_dir = os.path.join(pool_path, 'seed_cov')
        seeds = collect_seed_cov_dir(seed_cov_dir)
        all_seeds.update(seeds)
        for transitions in seeds.values():
            elite_unique.update(transitions)

    return all_seeds, elite_unique


def process_target(target_dir, output_dir):
    """
    Process one target's run directory.
    target_dir: path to the extracted run (e.g., .../exim/exim_260121/)
    output_dir: path to SPCM/<target>/ for output
    """
    # Find all gen directories
    gen_dirs = sorted(
        [d for d in os.listdir(target_dir)
         if d.startswith('gen') and os.path.isdir(os.path.join(target_dir, d))],
        key=lambda x: int(x.replace('gen', ''))
    )

    if not gen_dirs:
        print(f"No gen directories found in {target_dir}")
        return

    target_name = os.path.basename(os.path.dirname(target_dir))
    os.makedirs(output_dir, exist_ok=True)

    all_summary = []
    total_gens = len(gen_dirs)

    for i, gen_name in enumerate(gen_dirs):
        gen_path = os.path.join(target_dir, gen_name)
        gen_out_dir = os.path.join(output_dir, gen_name)
        os.makedirs(gen_out_dir, exist_ok=True)

        # --- ALL seeds: from this gen's own aflnetout ---
        all_seeds, all_transitions = collect_all_seeds(gen_path)
        n_all_seeds = len(all_seeds)
        n_all_trans = len(all_transitions)

        # Skip generations with no seed_cov data
        if n_all_seeds == 0:
            print(f"  {gen_name}: no seed_cov data, skipping")
            continue

        # --- ELITE seeds: gen N's elites are re-executed in gen N+1's pool 0000 ---
        # Look up gen N's elite seed transitions from gen N+1/aflnetout/0000/seed_cov/
        elite_seeds = {}
        elite_transitions = set()
        elite_source = None

        if i + 1 < total_gens:
            next_gen = gen_dirs[i + 1]
            next_gen_path = os.path.join(target_dir, next_gen)
            elite_seeds, elite_transitions = collect_elite_seeds(next_gen_path)
            if len(elite_seeds) > 0:
                elite_source = f"{next_gen}/aflnetout/*/seed_cov/"
            else:
                elite_source = f"{next_gen}/aflnetout/*/seed_cov/ (empty)"
        else:
            elite_source = "N/A (terminal generation)"

        n_elite_seeds = len(elite_seeds)
        n_elite_trans = len(elite_transitions)

        # --- Comparison ---
        shared = all_transitions & elite_transitions
        all_only = all_transitions - elite_transitions
        elite_only = elite_transitions - all_transitions

        # Coverage ratio: what fraction of ALL transitions do ELITE seeds cover?
        ratio = len(shared) / n_all_trans * 100 if n_all_trans > 0 else 0

        # --- Per-seed transition counts ---
        all_per_seed = {name: len(ts) for name, ts in all_seeds.items()}
        elite_per_seed = {name: len(ts) for name, ts in elite_seeds.items()}

        # --- Write detailed data ---
        result = {
            'generation': gen_name,
            'all': {
                'seed_count': n_all_seeds,
                'unique_transitions': n_all_trans,
                'transitions': sorted(all_transitions),
                'per_seed': all_per_seed,
            },
            'elite': {
                'seed_count': n_elite_seeds,
                'unique_transitions': n_elite_trans,
                'transitions': sorted(elite_transitions),
                'per_seed': elite_per_seed,
                'source': elite_source,
            },
            'comparison': {
                'shared': len(shared),
                'all_only': len(all_only),
                'elite_only': len(elite_only),
                'shared_transitions': sorted(shared),
                'all_only_transitions': sorted(all_only),
                'elite_only_transitions': sorted(elite_only),
            }
        }

        # Write per-gen JSON
        json_path = os.path.join(gen_out_dir, 'state_transitions.json')
        with open(json_path, 'w') as f:
            json.dump(result, f, indent=2)

        # Summary line
        all_summary.append({
            'generation': gen_name,
            'all_seeds': n_all_seeds,
            'all_transitions': n_all_trans,
            'elite_seeds': n_elite_seeds,
            'elite_transitions': n_elite_trans,
            'shared': len(shared),
            'all_only': len(all_only),
            'elite_only': len(elite_only),
            'coverage_pct': round(ratio, 1),
            'elite_source': elite_source,
        })

        print(f"  {gen_name}: ALL={n_all_seeds} seeds, {n_all_trans} trans | "
              f"ELITE={n_elite_seeds} seeds, {n_elite_trans} trans | "
              f"shared={len(shared)}, all_only={len(all_only)}, elite_only={len(elite_only)} | "
              f"coverage={ratio:.1f}%")

    # --- Write overall summary CSV ---
    csv_path = os.path.join(output_dir, 'state_transition_summary.csv')
    with open(csv_path, 'w') as f:
        f.write("generation,all_seeds,all_transitions,elite_seeds,elite_transitions,"
                "shared,all_only,elite_only,coverage_pct,elite_source\n")
        for row in all_summary:
            f.write(f"{row['generation']},{row['all_seeds']},{row['all_transitions']},"
                    f"{row['elite_seeds']},{row['elite_transitions']},"
                    f"{row['shared']},{row['all_only']},{row['elite_only']},"
                    f"{row['coverage_pct']},{row['elite_source']}\n")

    print(f"  Results written to {output_dir}")
    return all_summary


def main():
    parser = argparse.ArgumentParser(
        description='Extract state transitions from AFLNet seed_cov and compare ALL vs ELITE')
    parser.add_argument('--target-dir', '-t', required=True,
                        help='Path to extracted run directory (e.g., .../exim/exim_260121/)')
    parser.add_argument('--output', '-o', required=True,
                        help='Output directory for results (e.g., SPCM/exim/)')
    parser.add_argument('--target-name', '-n', default=None,
                        help='Target name for output subdirectory (default: derived from parent dir)')
    args = parser.parse_args()

    target_dir = os.path.abspath(args.target_dir)
    if not os.path.isdir(target_dir):
        print(f"Error: target directory not found: {target_dir}")
        sys.exit(1)

    output_dir = os.path.abspath(args.output)

    print(f"Processing: {target_dir}")
    print(f"Output:    {output_dir}")
    print()

    process_target(target_dir, output_dir)


if __name__ == '__main__':
    main()
