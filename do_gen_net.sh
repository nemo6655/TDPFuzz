#!/bin/bash

# Be strict about failures
set -euo pipefail

prev_gen="$1"
next_gen="$2"
num_gens=$(./elmconfig.py get run.num_generations)

# MODELS="codellama starcoder starcoder_diff"
MODELS=$(./elmconfig.py get model.names)
NUM_VARIANTS=$(./elmconfig.py get cli.genvariants_parallel.num_variants)
LOGDIR=$(./elmconfig.py get run.logdir -s GEN=${next_gen})
NUM_SELECTED=$(./elmconfig.py get run.num_selected)
STATE_POOLS=($(./elmconfig.py get run.state_pools))
PROTOCOL_TYPE=$(./elmconfig.py get protocol_type)


COLOR_RED='\033[0;31m'
COLOR_GREEN='\033[0;32m'
COLOR_RESET='\033[0m'

# Discover existing state directories under the previous generation's seeds
# and store their basenames into the STATE array.
STATE=()
prev_seeds_dir="$ELMFUZZ_RUNDIR/${prev_gen}/seeds"
if [ -d "$prev_seeds_dir" ]; then
    while IFS= read -r -d '' dir; do
        STATE+=("$(basename "$dir")")
    done < <(find "$prev_seeds_dir" -mindepth 1 -maxdepth 1 -type d -print0)
fi
echo "Discovered state directories from ${prev_gen}: ${STATE[*]}"
# If no state directories were found, exit with error
if [ ${#STATE[@]} -eq 0 ]; then
    echo "Error: no state directories found under ${prev_seeds_dir}; aborting." >&2
    exit 1
fi


printf "$COLOR_GREEN"'============> %s: %6s -> %6s of %3d <============'"$COLOR_RESET"'\n' $ELMFUZZ_RUN_NAME $prev_gen $next_gen $num_gens
echo "Running generation $next_gen using $MODELS with $NUM_VARIANTS variants per seed"

# Create the next generation directory
mkdir -p "$ELMFUZZ_RUNDIR"/${next_gen}/{variants,seeds,logs,aflnetout}
AFLNET_OUT="$ELMFUZZ_RUNDIR"/${next_gen}/aflnetout

# For each state pool, create corresponding subdirectories under seeds and variants
for pool in "${STATE_POOLS[@]}"; do
    echo "Creating state pool directories for '$pool' in generation ${next_gen}"
    mkdir -p "$ELMFUZZ_RUNDIR"/${next_gen}/seeds/${pool}
    mkdir -p "$ELMFUZZ_RUNDIR"/${next_gen}/variants/${pool}
done



seed_num=1

# Select the seeds for the next generation based on coverage
# If this is the first generation, just use the seed
if [ "$prev_gen" == "initial" ]; then
    echo "First generation; using seed(s):" "$ELMFUZZ_RUNDIR"/init_seeds/*.raw
    
    # cp "$ELMFUZZ_RUNDIR"/initial/seeds/*.py "$ELMFUZZ_RUNDIR"/${next_gen}/seeds/
else
    # Selection
    # Check if SELECTION_STRATEGY environment variable is set, otherwise use config
    if [ -n "${SELECTION_STRATEGY:-}" ]; then
        selection_strategy="$SELECTION_STRATEGY"
    else
        selection_strategy=$(./elmconfig.py get run.selection_strategy)
    fi
    # If strategy is elites, select best coverage across all generations
    # If it's best_of_generation, select best coverage from the previous generation
    # Hopefully eventually we will also have MAP-Elites
    if [ "$selection_strategy" == "elites" ]; then
        echo "$selection_strategy: Selecting best seeds from all generations"
        cov_files=("$ELMFUZZ_RUNDIR"/*/logs/coverage.json)
    elif [ "$selection_strategy" == "best_of_generation" ]; then
        echo "$selection_strategy: Selecting best seeds from previous generation"
        cov_files=("$ELMFUZZ_RUNDIR/${prev_gen}/logs/coverage.json")
    elif [ "$selection_strategy" == "lattice" ]; then
        echo "$selection_strategy: Selecting seeds from the lattice"
    else
        echo "Unknown selection strategy $selection_strategy; exiting"
        exit 1
    fi
    if [ "$selection_strategy" == "lattice" ]; then
        cov_file="$ELMFUZZ_RUNDIR"/${prev_gen}/logs/coverage.json
        input_elite_file="$ELMFUZZ_RUNDIR"/${prev_gen}/logs/elites.json
        output_elite_file="$ELMFUZZ_RUNDIR"/${next_gen}/logs/elites.json
        # Ensure the input elites file exists (create empty file if missing)
        if [ ! -f "$input_elite_file" ]; then
            mkdir -p "$(dirname "$input_elite_file")"
            : > "$input_elite_file"
        fi
        # baseline="$ELMFUZZ_RUNDIR"/baseedges
        # python select_seeds.py -g $prev_gen -n $NUM_SELECTED -c $cov_file -i $input_elite_file -o $output_elite_file -b $baseline | \
        #     while read cov gen model generator ; do
        #         echo "Selecting $generator from $gen/$model with $cov edges covered"
        #         cp "$ELMFUZZ_RUNDIR"/${gen}/variants/${model}/${generator}.py \
        #         "$ELMFUZZ_RUNDIR"/${next_gen}/seeds/${gen}_${model}_${generator}.py
        #     done
        python select_seeds_net.py -g $prev_gen -n $NUM_SELECTED -c $cov_file -i $input_elite_file -o $output_elite_file 
        python select_states_net.py -c $cov_file -e $output_elite_file -g $next_gen
        # python select_seeds_net.py -g $prev_gen -n $NUM_SELECTED -c $cov_file -i $input_elite_file -o $output_elite_file | \
        #     while read cov gen model generator ; do
        #         echo "Selecting $generator from $gen/$model with $cov edges covered"
        #         cp "$ELMFUZZ_RUNDIR"/${gen}/variants/${model}/${generator}.py \
        #         "$ELMFUZZ_RUNDIR"/${next_gen}/seeds/${gen}_${model}_${generator}.py
        #     done
    else
        python analyze_cov.py "${cov_files[@]}" | sort -n | tail -n $NUM_SELECTED | \
            while read cov gen model generator ; do
                echo "Selecting $generator from $gen/$model with $cov edges covered"
                cp "$ELMFUZZ_RUNDIR"/${gen}/variants/${model}/${generator}.py \
                "$ELMFUZZ_RUNDIR"/${next_gen}/seeds/${gen}_${model}_${generator}.py
            done
    fi
    seed_num="$(find "${ELMFUZZ_RUNDIR}/${next_gen}/seeds" -maxdepth 1 -type f -printf x | wc -c)"
fi

# Generate the next generation. If this is the first generation, create 10xNUM_VARIANTS variants
# for each seed with each model. Otherwise, create NUM_VARIANTS variants for each seed with each model.
# if [ "$prev_gen" == "initial" ] || [ "$seed_num" -eq 1 ]; then
#     NUM_VARIANTS=$((NUM_VARIANTS * 10))
#     VARIANT_ARGS="-n ${NUM_VARIANTS}"
# elif [ "$seed_num" -eq 2 ]; then
#     NUM_VARIANTS=$((NUM_VARIANTS * 5))
#     VARIANT_ARGS="-n ${NUM_VARIANTS}"
# elif [ "$seed_num" -eq 3 ]; then
#     NUM_VARIANTS=$((NUM_VARIANTS * 3))
#     VARIANT_ARGS="-n ${NUM_VARIANTS}"
# else
#     VARIANT_ARGS=""
# fi
VARIANT_ARGS="-n ${NUM_VARIANTS}"


echo "Generating next generation: ${NUM_VARIANTS} variants for each seed with each model"



for model_name in $MODELS ; do
    for state_name in "${STATE[@]}"; do
        MODEL=$(basename "$model_name")
        GVLOG="${LOGDIR}/meta"
        GOLOG="${LOGDIR}/outputgen_${MODEL}.jsonl"
        GVOUT=$(./elmconfig.py get run.genvariant_dir -s MODEL=${MODEL} -s GEN=${prev_gen})
        GOOUT=$(./elmconfig.py get run.genoutput_dir -s MODEL=${MODEL} -s GEN=${prev_gen})
        python "$ELMFUZZ_RUNDIR"/seed_gen_${PROTOCOL_TYPE}.py \
            --input_seeds "${GOOUT}/${state_name}/" \
            --init_variants "${GVOUT}/${state_name}/"
        echo "====================== $model_name:$state_name ======================"
        # TODO: have genvariants_parallel.py do all the models at once
        # Will have to add in model-specific args to the config and merge
        # in the starcoder_diff script
        python genvariants_parallel_net.py \
            $VARIANT_ARGS \
            -M "${model_name}" \
            -O "${GVOUT}/${state_name}/" \
            -L "${GVLOG}" \
            "$ELMFUZZ_RUNDIR"/${prev_gen}/variants/${state_name}/*.py \
        | python genoutputs_net.py \
            -L "${GOLOG}" \
            -O "${GOOUT}/${state_name}/" \
            -g "${prev_gen}"
        # rm "$GOLOG"
        # python shrink_variants_in_dir.py --source-dir "${GVOUT}"
    done
done

# Collect the coverage of the generators
echo "Collecting coverage of the generators"
all_models_genout_dir=$(realpath -m "$GOOUT")

if [ $TYPE == "fuzzbench" ] || [ $TYPE == "oss-fuzz" ] || [ $TYPE == "docker" || [ $TYPE == "profuzzbench" ] ]; then
    python getcov_fuzzbench_net.py --image tdpfuzz/"$PROJECT_NAME" --input "$all_models_genout_dir" --output "${AFLNET_OUT}" --covfile "${LOGDIR}/coverage.json" --next_gen "${next_gen#gen}"
else
    python getcov.py -O "${LOGDIR}/coverage.json" "$all_models_genout_dir"
fi


# for model_name in $MODELS ; do
#     GOOUT=$(./elmconfig.py get run.genoutput_dir -s MODEL=${MODEL} -s GEN=${next_gen})
#     rm -rf "$GOOUT"
# done

# Plot coverage
python analyze_cov.py -m $num_gens -p "$ELMFUZZ_RUNDIR"/*/logs/coverage.json

# Create a stamp file to indicate that this generation is finished
touch "$ELMFUZZ_RUNDIR"/stamps/${next_gen}.stamp
