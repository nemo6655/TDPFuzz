import click
import tempfile
import shutil
import sys
import subprocess
import os
import os.path
import re
import tarfile
from util import *
import logging
import json
from idontwannadoresearch import MailLogger, watch

logger = logging.getLogger(__file__)
mailogger = MailLogger.load_from_config(__file__, "/home/appuser/elmfuzz/cli/config.toml", chained_logger=logger)

def on_nsf_access() -> dict[str, str] | None:
    if not 'ACCESS_INFO' in os.environ:
        return None
    endpoint = os.environ['ACCESS_INFO']
    sif_root = os.environ['SIF_ROOT']
    return {
        'endpoint': endpoint,
        'sif_root': sif_root,
    }

@click.command()
@click.option('--image', type=str, required=True)
@click.option('--input', type=str, required=True)
@click.option('--output', type=str, required=False)
@click.option('--persist/--no-persist', type=bool, default=False)
@click.option('--covfile', type=str, default='./cov.json')
@click.option('--next_gen', type=int, default=1)
@click.option('-j', 'parallel_num', type=int, default=64, required=False)
@watch(mailogger)
def main(image: str, input: str,output:str, persist: bool, covfile: str, parallel_num: int, next_gen: int):
    covbin = get_config('target.covbin')
    options = get_config('target.options')
    # Normalize options to a single string for command-line usage
    if isinstance(options, list):
        options = ' '.join(options)
    if options is None:
        options = ''
    
    if isinstance(covbin, list):
        covbin_str = ' '.join(covbin)
    else:
        covbin_str = covbin
    access_info = on_nsf_access()
    real_feedback = get_config('cli.getcov.real_feedback') == 'true'
    afl_timeout = int(get_config('cli.getcov.afl_timeout'))
    
    cwd = os.path.dirname(os.path.abspath(__file__))
    # if access_info is not None:
    #     prefix = os.path.join(cwd, 'tmp', 'fuzzdata') + '/'
    # elif bool(os.environ.get('REPROUDCE_MODE', 'false')):
    prefix = '/tmp/host/fuzzdata/'
    # else:
    #     prefix = '/tmp/fuzzdata/'
    # if not os.path.exists(prefix):
    #     os.makedirs(prefix)
    dest_dir = output if output else os.path.join(tmpdir, 'out')
    os.makedirs(dest_dir, exist_ok=True)
    aflout_path = os.path.join(dest_dir, 'aflnetout.tar.gz')
    
    with tempfile.TemporaryDirectory(prefix=prefix) as tmpdir:
        target_dir = os.path.join(tmpdir, 'input')
        os.makedirs(target_dir, exist_ok=True)
        # Build worklist: if input dir has subdirectories, treat each subdir as a separate job
        worklist = []
        use_0000 = False
        if os.path.isdir(input):
            # find subdirectories
            entries = [os.path.join(input, name) for name in os.listdir(input)]
            subdirs = [p for p in entries if os.path.isdir(p)]
            if subdirs:
                worklist = subdirs
            else:
                # no subdirs: use the whole input dir as single job
                worklist = [input]
                use_0000 = True
        else:
            # single file provided
            worklist = [input]
        
        # If there are multiple work items, run them in parallel (one docker container per item)
        if access_info is None:
            from concurrent.futures import ThreadPoolExecutor, as_completed

            def start_container_for_job(job_path, idx):
                run_tmp = os.path.join(tmpdir, f'run_{idx}')
                os.makedirs(run_tmp, exist_ok=True)
                # copy job input into work tmp input
                dest_input = os.path.join(run_tmp, 'input')
                os.makedirs(dest_input, exist_ok=True)
                if os.path.isdir(job_path):
                    for name in os.listdir(job_path):
                        s = os.path.join(job_path, name)
                        d = os.path.join(dest_input, name)
                        if os.path.isdir(s):
                            shutil.copytree(s, d)
                        else:
                            shutil.copy2(s, d)
                else:
                    shutil.copy2(job_path, os.path.join(dest_input, os.path.basename(job_path)))

                # sanitize job name to produce a safe artifact name
                job_base = os.path.basename(job_path.rstrip(os.path.sep))
                safe_job = re.sub(r'[^A-Za-z0-9_.-]', '_', job_base)
                output_base = f'aflnetout_{safe_job}'

                cmd = [
                    'docker', 'run', '-d', '--cpus=1',
                    '-v', f'{run_tmp}:/tmp',
                    image,
                    '/bin/bash', '-c', f'cd /home/ubuntu/experiments && run aflnet /tmp/input {output_base} "{options}" {next_gen * 600} 5'
                ]
                # start and return container id and run_tmp
                res = subprocess.run(cmd, capture_output=True, text=True, check=True)
                cid = res.stdout.strip()
                print(f"Started container for job {idx} (job={job_base}): {cid}")
                return cid, run_tmp, output_base, idx

            # start all jobs in parallel
            futures = []
            cids = []
            runmap = {}
            with ThreadPoolExecutor(max_workers=min(len(worklist), parallel_num or len(worklist))) as ex:
                for i, job in enumerate(worklist, start=1):
                    futures.append(ex.submit(start_container_for_job, job, i))
                for fut in as_completed(futures):
                    cid, run_tmp, output_base, idx = fut.result()
                    cids.append(cid)
                    runmap[cid] = (run_tmp, output_base)

            # Wait for all containers
            if cids:
                subprocess.run(['docker', 'wait'] + cids, check=True)

            all_cov_data = {str(next_gen): {}}

            # Collect outputs from each container
            for cid in cids:
                run_tmp, output_base = runmap.get(cid)
                dest_dir = output if output else os.path.join(tmpdir, 'out')
                os.makedirs(dest_dir, exist_ok=True)
                aflout_path = os.path.join(dest_dir, f'{output_base}.tar.gz')
                try:
                    subprocess.run(['docker', 'cp', f'{cid}:/home/ubuntu/experiments/{output_base}.tar.gz', aflout_path], check=True)
                except subprocess.CalledProcessError:
                    print(f"Warning: could not copy {output_base}.tar.gz from container {cid}")

                # If the tarball was copied, extract files under 'queue/' into a safe per-job dir
                if os.path.exists(aflout_path):
                    try:
                        safe_job = output_base[len('aflnetout_'):] if output_base.startswith('aflnetout_') else output_base
                        if use_0000:
                            safe_job = '0000'
                        extract_root = os.path.join(dest_dir, safe_job)
                        os.makedirs(extract_root, exist_ok=True)
                        with tarfile.open(aflout_path, 'r:*') as tf:
                            for member in tf.getmembers():
                                # normalize member name
                                name = member.name.lstrip('./')
                                parts = name.split('/')
                                
                                target_path = None
                                if '.state' in parts and 'seed_cov' in parts:
                                    si = parts.index('seed_cov')
                                    rel_parts = parts[si+1:]
                                    if rel_parts:
                                        target_path = os.path.join(extract_root, 'seed_cov', *rel_parts)
                                elif 'queue' in parts:
                                    if '.state' in parts:
                                        continue
                                    qi = parts.index('queue')
                                    rel_parts = parts[qi+1:]
                                    if rel_parts:
                                        target_path = os.path.join(extract_root, *rel_parts)
                                
                                if target_path:
                                    # create directories as needed
                                    parent = os.path.dirname(target_path)
                                    if parent:
                                        os.makedirs(parent, exist_ok=True)
                                    if member.isdir():
                                        os.makedirs(target_path, exist_ok=True)
                                    else:
                                        f = tf.extractfile(member)
                                        if f is None:
                                            continue
                                        with open(target_path, 'wb') as out_f:
                                            shutil.copyfileobj(f, out_f)
                        
                        # Process coverage files
                        seed_cov_dir = os.path.join(extract_root, 'seed_cov')
                        job_cov = {}
                        if os.path.exists(seed_cov_dir):
                            for cov_file in os.listdir(seed_cov_dir):
                                cov_path = os.path.join(seed_cov_dir, cov_file)
                                if os.path.isfile(cov_path):
                                    with open(cov_path, 'r', encoding='utf-8', errors='ignore') as f:
                                        content = [line.strip() for line in f if line.strip()]
                                    job_cov[cov_file] = content
                        
                        # Save per-job json
                        with open(os.path.join(dest_dir, f'cov_{safe_job}.json'), 'w') as f:
                            json.dump(job_cov, f)
                        
                        if safe_job not in all_cov_data[str(next_gen)]:
                            all_cov_data[str(next_gen)][safe_job] = {}

                        for k, v in job_cov.items():
                            edges_only = [item.split(':')[0] for item in v]
                            all_cov_data[str(next_gen)][safe_job][k] = edges_only

                    except Exception as e:
                        print(f"Warning: failed to extract/process files from {aflout_path}: {e}")
                
                # copy cov if present in bound dir
                host_cov = os.path.join(run_tmp, 'cov')
                if os.path.exists(host_cov):
                    out_cov = covfile if len(cids) == 1 else f"{covfile.rstrip('.json')}_{cid[:12]}.json"
                    shutil.copy(host_cov, out_cov)
            
            # Write aggregated coverage to covfile
            if all_cov_data:
                with open(covfile, 'w') as f:
                    json.dump(all_cov_data, f)
        else:
            # Apptainer/sif path: run serially for the combined input
            cmd = [
                'apptainer', 'exec',
                '--cleanenv',
                '--bind', f'{tmpdir}:/tmp:rw',
                os.path.join(access_info['sif_root'], image),
                '/usr/bin/bash', '-c', f'python3 /src/elm_getcov_inside_docker.py --input {target_dir} --output /tmp/out -j {parallel_num} --prog="{covbin_str}" --real-feedback {real_feedback} --afl-timeout={afl_timeout}'
            ]
            subprocess.run(cmd, check=True, stdout=sys.stdout, stderr=sys.stderr)

    if os.path.exists(tmpdir):
        shutil.rmtree(tmpdir, ignore_errors=True)


if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO)
    main()
