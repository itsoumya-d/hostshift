import json

with open('/Users/soumyadebnath16/Downloads/hostshift 3/runs/unified_benchmark_results.json') as f:
    data = json.load(f)

runs = data.get('runs', [])

# calculate average RP/AP when renderable == True
hosts = ['web', 'swiftui', 'compose', 'tui']
stats = {h: {'rp': [], 'ap': []} for h in hosts}

for r in runs:
    for h in hosts:
        if r['hosts'][h].get('renderable'):
            stats[h]['rp'].append(r['hosts'][h]['rp'])
            stats[h]['ap'].append(r['hosts'][h]['ap'])

for h in hosts:
    rp_avg = sum(stats[h]['rp']) / len(stats[h]['rp']) if stats[h]['rp'] else 0
    ap_avg = sum(stats[h]['ap']) / len(stats[h]['ap']) if stats[h]['ap'] else 0
    print(f"{h}: RP = {rp_avg:.3f}, AP = {ap_avg:.3f} (N={len(stats[h]['rp'])})")
