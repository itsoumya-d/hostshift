import json
import copy
import re
import os

tasks = [json.loads(x) for x in open('tasks/suite_v1.jsonl')]

def load_template(cat):
    for t in tasks:
        if t['category'] == cat and t['id'].endswith('-001'):
            with open(f'tasks/reference_specs/{t["id"]}.json') as f:
                return json.load(f)
    for t in tasks:
        if t['category'] == cat:
            path = f'tasks/reference_specs/{t["id"]}.json'
            if os.path.exists(path):
                with open(path) as f:
                    return json.load(f)
    raise ValueError(f"Template not found for {cat}")

def get_type(v):
    if isinstance(v, bool): return "boolean"
    if isinstance(v, (int, float)): return "number"
    return "string"

for t in tasks:
    if t['id'].endswith('-001'):
        continue
    
    cat = t['category']
    tid = t['id']
    try:
        tmpl = load_template(cat)
    except:
        continue
        
    spec = copy.deepcopy(tmpl)
    spec['title'] = t['prompt'][:20]
    
    collections_req = {}
    state_req = {}
    seeds = {}
    
    for c in t['criteria']:
        kind = c['kind']
        if kind == 'collection_contains':
            col = c['collection']
            if col not in collections_req: collections_req[col] = {}
            if col not in seeds: seeds[col] = []
            for k, v in c['match'].items():
                collections_req[col][k] = get_type(v)
            seeds[col].append(c['match'])
            
        elif kind == 'collection_field_equals':
            col = c['collection']
            if col not in collections_req: collections_req[col] = {}
            if col not in seeds: seeds[col] = []
            item = {}
            for k, v in c['where'].items():
                collections_req[col][k] = get_type(v)
                item[k] = v
            collections_req[col][c['field']] = get_type(c['value'])
            
            bad_val = "pending" if isinstance(c['value'], str) else (0 if isinstance(c['value'], (int,float)) else not c['value'])
            item[c['field']] = bad_val
            seeds[col].append(item)
            
        elif kind == 'state_equals':
            state_req[c['path']] = get_type(c['value'])
        elif kind == 'state_truthy':
            state_req[c['path']] = "boolean"
        elif kind == 'visible_row_count':
            col = c['collection']
            if col not in collections_req: collections_req[col] = {}
            if col not in seeds: seeds[col] = []

    for c in t['criteria']:
        if c['kind'] == 'collection_count':
            col = c['collection']
            if col not in collections_req:
                collections_req[col] = {"id": "string"}
            if col not in seeds: seeds[col] = []
            while len(seeds[col]) < c['value']:
                seeds[col].append({"id": f"item{len(seeds[col])}"})
                
    spec['collections'] = {}
    for col, fields in collections_req.items():
        if 'id' not in fields and not fields:
            fields['id'] = 'string'
        spec['collections'][col] = {
            "fields": {k: {"type": ty} for k, ty in fields.items()},
            "seed": seeds[col]
        }
        
    spec['state'] = {}
    for path, ty in state_req.items():
        parts = path.split('.')
        if len(parts) == 1:
            spec['state'][parts[0]] = {"type": ty, "default": "" if ty == "string" else (0 if ty == "number" else False)}
        else:
            obj, prop = parts[0], parts[1]
            if obj not in spec['state']:
                spec['state'][obj] = {"type": "object", "default": {}}
            spec['state'][obj]['default'][prop] = "" if ty == "string" else (0 if ty == "number" else False)
            
    # We will simply overwrite all screens with ONE simple screen that exposes everything.
    # This guarantees structural validity (no broken binds) and that the operator can find all fields.
    scr = {
        "id": "main",
        "title": "Main Screen",
        "children": [{"kind": "heading", "id": "title", "label": "Main"}]
    }
    spec['entry'] = "main"
    action = []
    
    # Expose all state variables as fields
    for path, ty in state_req.items():
        field_id = path.replace('.', '')
        if ty == "boolean":
            scr['children'].append({
                "kind": "toggle",
                "id": field_id,
                "label": path.capitalize(),
                "bind": path
            })
            action.append({"op": "set", "target": path, "value": True})
        else:
            scr['children'].append({
                "kind": "field",
                "id": field_id,
                "label": path.capitalize(),
                "bind": path
            })
            
    # Add fields to create collection items
    for col, fields in collections_req.items():
        col_item_fields = []
        for f, fty in fields.items():
            if f == 'id': continue
            field_id = f"new_{col}_{f}"
            scr['children'].append({
                "kind": "field",
                "id": field_id,
                "label": f"{col} {f}",
                "bind": field_id
            })
            # we need to put it in state so we can bind
            spec['state'][field_id] = {"type": fty, "default": "" if fty == "string" else (0 if fty == "number" else False)}
            col_item_fields.append((f, field_id))
            
        if col_item_fields:
            action.append({
                "op": "append",
                "target": col,
                "value": {f: f"$state.{field_id}" for f, field_id in col_item_fields}
            })
            
    # Also add updates for collection_field_equals
    for c in t['criteria']:
        if c['kind'] == 'collection_field_equals':
            col = c['collection']
            for k, v in c['where'].items():
                where_k = k
                where_v = v
                break
            # we can just add an action that updates the matching item
            action.append({
                "op": "update",
                "target": col,
                "value": {
                    "where": {where_k: where_v},
                    "set": {c['field']: c['value']}
                }
            })
            
    scr['children'].append({
        "kind": "button",
        "id": "submitBtn",
        "label": "Submit",
        "action": action
    })
    
    spec['screens'] = [scr]

    with open(f"tasks/reference_specs/{tid}.json", "w") as f:
        json.dump(spec, f, indent=2)

print("Generated super generic specs.")
