import json

with open('/Users/soumyadebnath16/Downloads/hostshift 3/runs/unified_benchmark_results.json') as f:
    data = json.load(f)

runs = data.get('runs', [])
models = {}
for r in runs:
    m = r['model']
    c = r['condition']
    rend = r['hosts']['web']['renderable']
    if m not in models:
        models[m] = {'A_tot': 0, 'A_rend': 0, 'B_tot': 0, 'B_rend': 0}
    
    if c == 'A':
        models[m]['A_tot'] += 1
        if rend: models[m]['A_rend'] += 1
    elif c == 'B':
        models[m]['B_tot'] += 1
        if rend: models[m]['B_rend'] += 1

for m, stats in models.items():
    print(f"{m}:")
    if stats['A_tot'] > 0:
        print(f"  Cond A Rend: {stats['A_rend']}/{stats['A_tot']} ({stats['A_rend']/stats['A_tot']:.1%})")
    if stats['B_tot'] > 0:
        print(f"  Cond B Rend: {stats['B_rend']}/{stats['B_tot']} ({stats['B_rend']/stats['B_tot']:.1%})")
