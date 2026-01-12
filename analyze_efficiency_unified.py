import os
import argparse
import matplotlib.pyplot as plt
import numpy as np
import sys

# Set plotting style
plt.style.use('default') # Use default style (white background) instead of ggplot

TARGET_DISPLAY_NAMES = {
    'live555': 'Live555',
    'proftpd': 'ProFTPD',
    'pureftpd': 'PureFTPD',
    'kamailio': 'Kamailio',
    'exim': 'Exim',
    'forkeddaapd': 'forked-daapd'
}

BASE_SPCM_PATH = "/home/pzst/LLM-PROTOCOL-FUZZ/TDPFuzz/evaluation/SPCM"
GENERATIONS = ["gen0", "gen1", "gen2", "gen3", "gen4", "gen5"]

def get_last_metric_from_csv(filepath):
    """
    Robustly reads the last numeric value from the last column of a CSV.
    Iterates backwards to skip empty lines or headers relative to data.
    """
    if not os.path.exists(filepath):
        return 0.0
    try:
        with open(filepath, 'r') as f:
            lines = f.readlines()
            for line in reversed(lines):
                line = line.strip()
                if not line:
                    continue
                parts = line.split(',')
                if not parts:
                    continue
                val_str = parts[-1]
                # specific check to avoid reading header "b_abs" as 0.0 if caught by exception or similar logic
                # though float("b_abs") raises ValueError
                try:
                    return float(val_str)
                except ValueError:
                    continue # Likely header or malformed line, keep looking backwards
    except Exception as e:
        print(f"Error reading {filepath}: {e}")
    return 0.0

def get_target_metrics(target_name):
    target_base = os.path.join(BASE_SPCM_PATH, target_name)
    if not os.path.exists(target_base):
        print(f"Warning: Target path {target_base} does not exist.")
        return None

    metrics = {
        'all_seeds': [], 'elite_seeds': [],
        'all_cov': [], 'elite_cov': [],
        'srr': [], 'crr': [],
        'efficiency': []
    }

    print(f"DEBUG: Processing {target_name}...")

    for gen in GENERATIONS:
        gen_path = os.path.join(target_base, gen)
        
        # Paths
        all_queue = os.path.join(gen_path, "replayable_all", "replayable-queue")
        elite_queue = os.path.join(gen_path, "replayable_elites", "replayable-queue")
        cov_all_file = os.path.join(gen_path, "cov_all.csv")
        cov_elite_file = os.path.join(gen_path, "cov_elites.csv")

        # Count seeds
        n_all, n_elite = 0, 0
        try:
            if os.path.exists(all_queue):
                n_all = len([n for n in os.listdir(all_queue) if os.path.isfile(os.path.join(all_queue, n))])
            if os.path.exists(elite_queue):
                n_elite = len([n for n in os.listdir(elite_queue) if os.path.isfile(os.path.join(elite_queue, n))])
        except Exception:
            pass

        # Get coverage using robust function
        c_all = get_last_metric_from_csv(cov_all_file)
        c_elite = get_last_metric_from_csv(cov_elite_file)
        
        if target_name == 'exim' and gen == 'gen1':
            print(f"  [DEBUG] Exim Gen1: c_elite read from {cov_elite_file} -> {c_elite}")

        # Calculate Ratios
        safe_n_all = n_all if n_all > 0 else 1
        safe_c_all = c_all if c_all > 0 else 1
        
        srr = n_elite / safe_n_all
        crr = c_elite / safe_c_all
        eff = crr / srr if srr > 0 else 0

        metrics['all_seeds'].append(n_all)
        metrics['elite_seeds'].append(n_elite)
        metrics['all_cov'].append(c_all)
        metrics['elite_cov'].append(c_elite)
        metrics['srr'].append(srr)
        metrics['crr'].append(crr)
        metrics['efficiency'].append(eff)

    return metrics

def draw_efficiency_single(ax1, target_name, metrics, show_legend=True, show_labels=True):
    x = np.arange(len(GENERATIONS))
    width = 0.35

    # Bar chart (Seeds)
    all_seeds = metrics['all_seeds']
    elite_seeds = metrics['elite_seeds']
    
    ax1.bar(x - width/2, all_seeds, width, label='All Seeds', color='#A9A9A9', alpha=0.7)
    ax1.bar(x + width/2, elite_seeds, width, label='Elite Seeds', color='#4682B4', alpha=0.9)

    if show_labels:
        ax1.set_ylabel('Number of Seeds', fontsize=24, fontweight='bold', color='black')
    ax1.set_xlabel('Generation', fontsize=20, fontweight='bold')
    ax1.set_xticks(x)
    ax1.set_xticklabels([g.capitalize() for g in GENERATIONS], fontsize=20)
    ax1.tick_params(axis='y', labelcolor='black', labelsize=20)

    # Line chart (Coverage)
    ax2 = ax1.twinx()
    all_cov = metrics['all_cov']
    elite_cov = metrics['elite_cov']
    
    ax2.plot(x, all_cov, label='All Coverage', color='#D2222D', marker='o', linestyle='-', linewidth=3, markersize=10)
    ax2.plot(x, elite_cov, label='Elite Coverage', color='#228B22', marker='^', linestyle='--', linewidth=3, markersize=10)

    if show_labels:
        ax2.set_ylabel('Branch Coverage (Edges)', fontsize=24, fontweight='bold', color='black')
    ax2.tick_params(axis='y', labelcolor='black', labelsize=20)
    
    # Force Y-axis to start at 0 to prevent misleading visual scaling
    # Or simply let it autoscale but be aware of the range.
    # Dynamic scaling based on user request: Min value - 1000 to highlight growth
    if metrics['all_cov'] and metrics['elite_cov']:
        # Combine lists to find overall min/max
        combined_cov = metrics['all_cov'] + metrics['elite_cov']
        
        # Filter out 0 values (missing data) to keep the scale focused on relevant data
        valid_cov = [v for v in combined_cov if v > 0]
        
        if valid_cov:
            min_val = min(valid_cov)
            max_val = max(valid_cov)
            
            # Ensure lower bound doesn't go below 0
            # User request: Set Y-axis min to min_val * 0.9 (minus 10%)
            lower_bound = max(0, min_val * 0.9)
            upper_bound = max_val * 1.05 # 5% padding on top
            
            # print(f"[DEBUG] {target_name}: Min Valid Cov={min_val}, Max Valid Cov={max_val}, Setting Y-lim to [{lower_bound}, {upper_bound}]")
            
            ax2.set_ylim(bottom=lower_bound, top=upper_bound)

    # Legends - Return handles for global usage if needed
    lines, labels = ax1.get_legend_handles_labels()
    lines2, labels2 = ax2.get_legend_handles_labels()
    
    if show_legend:
        # Place legend at the bottom, outside the plot area
        ax2.legend(lines + lines2, labels + labels2, loc='upper center', bbox_to_anchor=(0.5, -0.2), 
                   frameon=True, facecolor='white', framealpha=0.9, fontsize=20, ncol=2)

    display_name = TARGET_DISPLAY_NAMES.get(target_name, target_name)
    ax1.set_title(f'Selection Efficiency ({display_name})', fontsize=28, pad=20)
    ax1.grid(True, linestyle='--', alpha=0.3, color='gray')
    return (lines + lines2), (labels + labels2)

def plot_efficiency(target_name, metrics, output_path):
    fig, ax1 = plt.subplots(figsize=(10, 6))
    draw_efficiency_single(ax1, target_name, metrics)
    plt.tight_layout()
    plt.savefig(output_path, dpi=300)
    print(f"Plot saved to {output_path}")
    plt.close()

def save_combined_pdf(all_targets_data, output_path):
    targets = list(all_targets_data.keys())
    n = len(targets)
    if n == 0: return

    cols = 2
    rows = (n + 1) // 2
    
    # Increase figure size appropriately
    fig, axes = plt.subplots(rows, cols, figsize=(18, 6 * rows))
    
    # Flatten axes for easy iteration
    if n == 1:
        axes_flat = [axes] if cols == 1 else axes.flatten()
    else:
        axes_flat = axes.flatten()

    global_handles = []
    global_labels = []

    for i, target in enumerate(targets):
        metrics = all_targets_data[target]
        # Disable individual legends and labels for combined plot
        handles, labels = draw_efficiency_single(axes_flat[i], target, metrics, show_legend=False, show_labels=False)
        if i == 0:
            global_handles = handles
            global_labels = labels
    
    # Hide unused subplots
    for j in range(i + 1, len(axes_flat)):
        axes_flat[j].axis('off')

    # Add global figure elements (Legend and Text centered)
    # Adjust layout to preserve footer space
    # Footer area: 0.0 to 0.12
    
    # Global Legend (Right aligned relative to anchor, placed left of center)
    fig.legend(global_handles, global_labels, loc='center right', bbox_to_anchor=(0.48, 0.06),
               fontsize=20, ncol=2, frameon=True, facecolor='white', framealpha=0.9)

    # Axis Descriptions (Left aligned relative to anchor, placed right of center)
    fig.text(0.52, 0.075, "Left Axis: Number of Seeds", 
             ha='left', va='center', fontsize=20, fontweight='bold', color='black')
    fig.text(0.52, 0.045, "Right Axis: Branch Coverage (Edges)", 
             ha='left', va='center', fontsize=20, fontweight='bold', color='black')

    plt.tight_layout(rect=[0, 0.12, 1, 1]) # Make room for footer
    plt.savefig(output_path)
    print(f"Combined PDF saved to {output_path}")
    plt.close()

def print_table(targets_data):
    # Header
    # Target | Gen0 (SRR/CRR) | ...
    
    header = f"{'Target':<12} | " + " | ".join([f"{gen.capitalize()}: SRR / CRR" for gen in GENERATIONS])
    print("\n" + "=" * len(header))
    print(header)
    print("-" * len(header))

    for target, metrics in targets_data.items():
        display_name = TARGET_DISPLAY_NAMES.get(target, target)
        row_str = f"{display_name:<12} | "
        gen_strs = []
        for i in range(len(GENERATIONS)):
            srr = metrics['srr'][i]
            crr = metrics['crr'][i]
            # Format: 12.3% / 99.8%
            cell = f"{srr:6.2%} / {crr:6.2%}"
            gen_strs.append(cell)
        row_str += " | ".join(gen_strs)
        print(row_str)
    print("=" * len(header) + "\n")
    print("Legend: SRR = Seed Retention Rate (Elites/All), CRR = Coverage Retention Ratio (EliteCov/AllCov)")


def main():
    parser = argparse.ArgumentParser(description="Analyze SPCM efficiency metrics.")
    parser.add_argument('targets', nargs='*', default=[], 
                        help='List of targets to analyze (default: all found in SPCM folder)')
    parser.add_argument('--plot-dir', default='/home/pzst/LLM-PROTOCOL-FUZZ/TDPFuzz/plot', help='Directory to save plots')
    
    args = parser.parse_args()
    
    if not args.targets:
        if os.path.exists(BASE_SPCM_PATH):
            args.targets = sorted([d for d in os.listdir(BASE_SPCM_PATH) 
                                   if os.path.isdir(os.path.join(BASE_SPCM_PATH, d))])
        else:
            print(f"Error: Path {BASE_SPCM_PATH} not found.")
            return

    if not os.path.exists(args.plot_dir):
        os.makedirs(args.plot_dir)

    all_targets_data = {}
    
    for target in args.targets:
        print(f"Analyzing {target}...")
        metrics = get_target_metrics(target)
        if metrics:
            all_targets_data[target] = metrics
            # Generate plot
            plot_path = os.path.join(args.plot_dir, f"seed_efficiency_{target}.png")
            plot_efficiency(target, metrics, plot_path)

    # Save combined PDF
    if all_targets_data:
        pdf_path = os.path.join(args.plot_dir, "efficiency_summary.pdf")
        save_combined_pdf(all_targets_data, pdf_path)

    # Print summary table
    if all_targets_data:

        print_table(all_targets_data)
    else:
        print("No data found for specified targets.")

if __name__ == "__main__":
    main()
