import os
import glob
import statistics
import re

base_path = "/home/pzst/LLM-PROTOCOL-FUZZ/TDPFuzz/evaluation"
targets = ['exim', 'forkeddaapd', 'kamailio', 'live555', 'proftpd', 'pureftpd']
tools = ['aflnet', 'chatafl', 'nsfuzz', 'tdpfuzz']

def count_files(directory):
    if not os.path.exists(directory):
        return 0
    return len([name for name in os.listdir(directory) if os.path.isfile(os.path.join(directory, name)) and name != "README.txt"])

def find_queue_dir(start_dir):
    direct = os.path.join(start_dir, "replayable-queue")
    if os.path.exists(direct):
        return direct
    for name in os.listdir(start_dir):
        sub = os.path.join(start_dir, name)
        if os.path.isdir(sub):
            nested = os.path.join(sub, "replayable-queue")
            if os.path.exists(nested):
                return nested
    return None

def get_throughput(tool, target):
    throughputs = []
    target_path = os.path.join(base_path, tool, target)
    if not os.path.exists(target_path):
        return []

    if tool == 'tdpfuzz':
        run_dirs = []
        for d in os.listdir(target_path):
            if d.startswith("run") and os.path.isdir(os.path.join(target_path, d)):
                run_dirs.append(d)
        run_dirs.sort(key=lambda x: int(x.replace("run", "")) if x.replace("run", "").isdigit() else 999)
        
        for run_dir_name in run_dirs:
            run_path = os.path.join(target_path, run_dir_name)
            target_subdir = None
            if os.path.exists(run_path):
                subdirs = [d for d in os.listdir(run_path) if os.path.isdir(os.path.join(run_path, d))]
                for sub in subdirs:
                    if os.path.exists(os.path.join(run_path, sub, "gen5")):
                        target_subdir = sub
                        break
            if target_subdir:
                queue_path = os.path.join(run_path, target_subdir, "gen5", "aflnetout", "gen5_all", "replayable-queue")
                if os.path.exists(queue_path):
                    count = count_files(queue_path)
                    throughput = count / (9.0 * 3600)
                    throughputs.append(throughput)
    else:
        all_dirs = [d for d in os.listdir(target_path) if os.path.isdir(os.path.join(target_path, d))]
        valid_runs = []
        for d in all_dirs:
            match = re.search(r'_(\d+)$', d)
            if match:
                run_id = int(match.group(1))
                valid_runs.append((run_id, d))
        if not valid_runs:
             for d in all_dirs:
                 nums = re.findall(r'\d+', d)
                 if nums:
                     run_id = int(nums[-1])
                     valid_runs.append((run_id, d))
        valid_runs.sort()
        for run_id, dir_name in valid_runs:
            run_path = os.path.join(target_path, dir_name)
            queue_path = find_queue_dir(run_path)
            if queue_path:
                count = count_files(queue_path)
                throughput = count / (24.0 * 3600)
                throughputs.append(throughput)
    return throughputs

# Data Collection
data = {}
for target in targets:
    data[target] = {}
    for tool in tools:
        runs = get_throughput(tool, target)
        # Pad to 4
        display_runs = runs[:4]
        while len(display_runs) < 4:
            display_runs.append(None)
        
        avg = 0.0
        if runs:
            avg = statistics.mean(runs[:4])
        
        data[target][tool] = {
            'runs': display_runs,
            'avg': avg
        }

# Text Output
# Text Output
print(f"{'Target':<12} | {'AFLNet':<12} | {'ChatAFL':<12} | {'NSFuzz':<12} | {'TDPFuzz':<12}")
print("-" * 70)

improvements = {'chatafl': [], 'nsfuzz': [], 'tdpfuzz': []}

for target in targets:
    aflnet_avg = data[target]['aflnet']['avg']
    
    row_vals = []
    for tool in tools:
        avg_val = data[target][tool]['avg']
        if tool == 'aflnet':
            row_vals.append(f"{avg_val:.4f}")
        else:
            if aflnet_avg > 0:
                improvement = ((avg_val - aflnet_avg) / aflnet_avg) * 100
                improvements[tool].append(improvement)
                row_vals.append(f"{improvement:+.2f}%")
            else:
                row_vals.append("N/A")
    
    print(f"{target:<12} | {row_vals[0]:<12} | {row_vals[1]:<12} | {row_vals[2]:<12} | {row_vals[3]:<12}")

# Calculate Average Improvements
avg_improvements = {}
for tool in ['chatafl', 'nsfuzz', 'tdpfuzz']:
    if improvements[tool]:
        avg_improvements[tool] = statistics.mean(improvements[tool])
    else:
        avg_improvements[tool] = 0.0

print("-" * 70)
print(f"{'Average':<12} | {'':<12} | {avg_improvements['chatafl']:+.2f}%      | {avg_improvements['nsfuzz']:+.2f}%      | {avg_improvements['tdpfuzz']:+.2f}%")


print("\n" + "="*30 + " LaTeX Code " + "="*30 + "\n")

# LaTeX Output
print(r"\begin{table*}[]")
print(r"\centering")
print(r"\caption{Fuzzing Throughput (replayable-queue/s) comparison. AFLNet is the baseline, others show percentage improvement.}")
print(r"\label{tab:throughput_comparison}")
print(r"\resizebox{\textwidth}{!}{%")
print(r"\begin{tabular}{|l|c|c|c|c|}")
print(r"\hline")
print(r"\multirow{2}{*}{\textbf{Target}} & \multicolumn{4}{c|}{\textbf{Fuzzing Throughput (replayable-queue/s)}} \ \cline{2-5}")
print(r" & \textbf{AFLNet} & \textbf{ChatAFL} & \textbf{NSFuzz} & \textbf{TDPFuzz} \ \hline")

for target in targets:
    aflnet_avg = data[target]['aflnet']['avg']
    
    row_vals = []
    for tool in tools:
        avg_val = data[target][tool]['avg']
        if tool == 'aflnet':
            row_vals.append(f"{avg_val:.4f}")
        else:
            if aflnet_avg > 0:
                improvement = ((avg_val - aflnet_avg) / aflnet_avg) * 100
                row_vals.append(f"{improvement:+.2f}\%")
            else:
                row_vals.append("N/A")
    
    print(f"{target.capitalize()} & {row_vals[0]} & {row_vals[1]} & {row_vals[2]} & {row_vals[3]} \ \hline")

print(r"\textbf{Average} & - & \textbf{" + f"{avg_improvements['chatafl']:+.2f}\%" + r"} & \textbf{" + f"{avg_improvements['nsfuzz']:+.2f}\%" + r"} & \textbf{" + f"{avg_improvements['tdpfuzz']:+.2f}\%" + r"} \ \hline")
print(r"\end{tabular}%")
print(r"}")
print(r"\end{table*}")

print("\n" + "="*30 + " LaTeX Code " + "="*30 + "\n")

# LaTeX Output
print(r"\begin{table*}[]")
print(r"\centering")
print(r"\caption{Throughput (exec/s) comparison and speedup of TDPFuzz against other tools.}")
print(r"\label{tab:throughput_full}")
print(r"\resizebox{\textwidth}{!}{%")
print(r"\begin{tabular}{|l|l|c|c|c|c|c|c|}")
print(r"\hline")
print(r"\textbf{Target} & \textbf{Tool} & \textbf{Run 1} & \textbf{Run 2} & \textbf{Run 3} & \textbf{Run 4} & \textbf{Avg} & \textbf{Speedup} \\ \hline")

for target in targets:
    first_row = True
    tdpfuzz_avg = data[target]['tdpfuzz']['avg']

    for tool in tools:
        info = data[target][tool]
        runs_str = [f"{r:.4f}" if r is not None else "N/A" for r in info['runs']]
        avg_val = info['avg']
        
        speedup_str = "-"
        if tool != 'tdpfuzz':
            if avg_val > 0:
                speedup = tdpfuzz_avg / avg_val
                speedup_str = f"{speedup:.2f}x"
            else:
                speedup_str = "N/A"
        else:
            speedup_str = "1.00x"
            
        target_display = f"\\multirow{{4}}{{*}}{{{target.capitalize()}}}" if first_row else ""
        
        print(f"{target_display} & {tool} & {runs_str[0]} & {runs_str[1]} & {runs_str[2]} & {runs_str[3]} & {avg_val:.4f} & {speedup_str} \\ ")

print("\n" + "="*30 + " LaTeX Code " + "="*30 + "\n")

# LaTeX Output
print(r"\begin{table*}[]")
print(r"\centering")
print(r"\caption{Throughput (exec/s) comparison and speedup of TDPFuzz against other tools.}")
print(r"\label{tab:throughput_full}")
print(r"\resizebox{\textwidth}{!}{%")
print(r"\begin{tabular}{|l|l|c|c|c|c|c|c|}")
print(r"\hline")
print(r"\textbf{Target} & \textbf{Tool} & \textbf{Run 1} & \textbf{Run 2} & \textbf{Run 3} & \textbf{Run 4} & \textbf{Avg} & \textbf{Speedup} \\ \hline")

for target in targets:
    first_row = True
    tdpfuzz_avg = data[target]['tdpfuzz']['avg']

    for tool in tools:
        info = data[target][tool]
        runs_str = [f"{r:.4f}" if r is not None else "N/A" for r in info['runs']]
        avg_val = info['avg']
        
        speedup_str = "-"
        if tool != 'tdpfuzz':
            if avg_val > 0:
                speedup = tdpfuzz_avg / avg_val
                speedup_str = f"{speedup:.2f}x"
            else:
                speedup_str = "N/A"
        else:
            speedup_str = "1.00x"
            
        target_display = f"\\multirow{{4}}{{*}}{{{target.capitalize()}}}" if first_row else ""
        
        print(f"{target_display} & {tool} & {runs_str[0]} & {runs_str[1]} & {runs_str[2]} & {runs_str[3]} & {avg_val:.4f} & {speedup_str} \\\\")
        if tool == tools[-1]:
            print(r"\hline")
        else:
            print(r"\cline{2-8}")
            
        first_row = False

print(r"\end{tabular}%")
print(r"}")
print(r"\end{table*}")
