import json
import glob
import os
import sys

def load_json(filepath):
    with open(filepath, 'r') as f:
        try:
            return json.load(f)
        except:
            return None

def load_jsonl(filepath):
    data = []
    with open(filepath, 'r') as f:
        for line in f:
            try:
                data.append(json.loads(line))
            except:
                pass
    return data

directory = "/Users/soumyadebnath16/Downloads/hostshift 3/runs/"
files = [
    "unified_benchmark_results.json",
    "experiment_comprehensive.json",
    "experiment_multimodel.json",
    "experiment_ab.json",
    "experiment_ab_v2.json",
    "experiment_v3_unified.json",
    "runs.jsonl",
    "real_experiment.json"
]

print("=== 2. DATA SOURCE SUMMARY ===")
all_runs = []
for file in files:
    filepath = os.path.join(directory, file)
    if not os.path.exists(filepath):
        print(f"File not found: {file}")
        continue
    
    if file.endswith('.jsonl'):
        data = load_jsonl(filepath)
    else:
        data = load_json(filepath)
    
    if data is None:
        print(f"Error loading {file}")
        continue
        
    records = data if isinstance(data, list) else data.get('runs', data.get('results', []))
    if isinstance(data, dict) and not records and 'experiments' in data:
        records = data['experiments']
    if not isinstance(records, list):
        records = [data] # maybe it's just one object
        
    if isinstance(records, list) and len(records) > 0 and isinstance(records[0], list):
        # Flatten
        records = [item for sublist in records for item in sublist]

    tasks = set()
    models = set()
    conditions = {'A': 0, 'B': 0, 'Reference': 0, 'Other': 0}
    renderable_a = 0
    renderable_b = 0
    task_pass_a = 0
    task_pass_b = 0
    
    for r in records:
        if not isinstance(r, dict):
            continue
        all_runs.append(r)
        
        task = r.get('task_id', r.get('task', 'unknown'))
        tasks.add(task)
        model = r.get('model_name', r.get('model', 'unknown'))
        models.add(model)
        
        cond = r.get('condition', 'unknown')
        if cond == 'A' or 'freeform' in str(cond).lower():
            conditions['A'] += 1
            if r.get('renderable', r.get('metrics', {}).get('renderable', False)):
                renderable_a += 1
            if r.get('task_pass', r.get('metrics', {}).get('task_pass', False)):
                task_pass_a += 1
        elif cond == 'B' or 'schema' in str(cond).lower():
            conditions['B'] += 1
            if r.get('renderable', r.get('metrics', {}).get('renderable', False)):
                renderable_b += 1
            if r.get('task_pass', r.get('metrics', {}).get('task_pass', False)):
                task_pass_b += 1
        elif cond == 'Reference' or cond == 'ref':
            conditions['Reference'] += 1
        else:
            conditions['Other'] += 1

    print(f"\nFile: {file}")
    print(f"Total records: {len(records)}")
    print(f"Unique tasks covered: {len(tasks)}")
    print(f"Unique models used: {len(models)}")
    print(f"Condition Breakdown: {conditions}")
    
    rend_a_rate = renderable_a / conditions['A'] if conditions['A'] > 0 else 0
    rend_b_rate = renderable_b / conditions['B'] if conditions['B'] > 0 else 0
    print(f"Renderable rate: Cond A = {rend_a_rate:.2%}, Cond B = {rend_b_rate:.2%}")
    
    pass_a_rate = task_pass_a / conditions['A'] if conditions['A'] > 0 else 0
    pass_b_rate = task_pass_b / conditions['B'] if conditions['B'] > 0 else 0
    print(f"Task completion rate: Cond A = {pass_a_rate:.2%}, Cond B = {pass_b_rate:.2%}")

print("\n=== DUPLICATE ANALYSIS ===")
run_ids = [r.get('run_id', r.get('id')) for r in all_runs if isinstance(r, dict) and (r.get('run_id') or r.get('id'))]
unique_run_ids = set(run_ids)
print(f"Total runs with IDs: {len(run_ids)}")
print(f"Unique run IDs: {len(unique_run_ids)}")
if len(run_ids) > len(unique_run_ids):
    print(f"Found {len(run_ids) - len(unique_run_ids)} duplicate runs!")

print("\n=== 5. DATA INTEGRITY ===")
impossible_rp = 0
impossible_ap = 0
suspicious_uniform = 0
for i, r in enumerate(all_runs):
    if not isinstance(r, dict): continue
    metrics = r.get('metrics', r)
    if not metrics:
        metrics = {}
    rp = metrics.get('render_parity', metrics.get('rp'))
    if rp is not None and (isinstance(rp, (int, float))) and (rp > 1.0 or rp < 0.0):
        impossible_rp += 1
    
    ap = metrics.get('accessibility_parity', metrics.get('ap'))
    if ap is not None and (isinstance(ap, (int, float))) and (ap > 1.0 or ap < 0.0):
        impossible_ap += 1
print(f"Impossible RP values (>1.0 or <0): {impossible_rp}")
print(f"Impossible AP values (>1.0 or <0): {impossible_ap}")

# Also let's check cross-validation of 125 total runs
print("\n=== PAPER CLAIMS CROSS VALIDATION ===")
# Count 125 runs for unified experiment runs
unified = []
for file in files:
    filepath = os.path.join(directory, file)
    if not os.path.exists(filepath): continue
    if file == 'unified_benchmark_results.json':
        data = load_json(filepath)
        unified = data.get('runs', [])
        break
        
print(f"Unified benchmark runs total: {len(unified)}")
tasks = set([r.get('task') for r in unified])
categories = set([r.get('category') for r in unified])
print(f"Unified task specifications: {len(tasks)}")
print(f"Unified task categories: {len(categories)}")

cond_stats = {'A': 0, 'B': 0, 'Reference': 0}
for r in unified:
    cond = r.get('condition', 'unknown')
    if 'A' in cond: cond_stats['A'] += 1
    elif 'B' in cond: cond_stats['B'] += 1
    elif 'ref' in cond.lower() or 'Reference' in cond: cond_stats['Reference'] += 1

print(f"Unified condition breakdown: {cond_stats}")
