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
    raise ValueError(f"Template not found for {cat}")

def get_type(v):
    if isinstance(v, bool): return "boolean"
    if isinstance(v, (int, float)): return "number"
    return "string"

def build_seed(fields_and_values):
    # fields_and_values is a list of dicts. We merge them.
    # We create one matching seed and one non-matching.
    match_seed = {}
    for k, v in fields_and_values.items():
        match_seed[k] = v
    
    non_match_seed = {}
    for k, v in fields_and_values.items():
        non_match_seed[k] = f"Other {v}" if isinstance(v, str) else (0 if isinstance(v, (int, float)) else not v)
        
    return [match_seed, non_match_seed]

for t in tasks:
    if t['id'].endswith('-001'):
        continue
    
    cat = t['category']
    tid = t['id']
    tmpl = load_template(cat)
    spec = copy.deepcopy(tmpl)
    
    # Simple strategy: find all state accesses in template and modify them.
    # Actually, the user says "The state variable paths MUST exactly match the criteria paths... Collection names MUST exactly match".
    # We will clear collections and states, and build them from criteria.
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
            
            # seed requires an item that needs to be updated. So we put an incorrect value for the field.
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
            
    # For list_detail, maybe we have collection_count but no field_equals (like list-003)
    # We need to make sure the collections are populated.
    for c in t['criteria']:
        if c['kind'] == 'collection_count':
            col = c['collection']
            if col not in collections_req:
                collections_req[col] = {"id": "string"}
            if col not in seeds: seeds[col] = []
            while len(seeds[col]) < c['value']:
                seeds[col].append({"id": f"item{len(seeds[col])}"})
                
    # Rebuild collections in spec
    spec['collections'] = {}
    for col, fields in collections_req.items():
        if 'id' not in fields and not fields:
            fields['id'] = 'string'
        spec['collections'][col] = {
            "fields": {k: {"type": ty} for k, ty in fields.items()},
            "seed": seeds[col]
        }
        
    # Rebuild state in spec
    spec['state'] = {}
    for path, ty in state_req.items():
        # Handle nested paths like address.country by putting them in object
        parts = path.split('.')
        if len(parts) == 1:
            spec['state'][parts[0]] = {"type": ty, "default": "" if ty == "string" else (0 if ty == "number" else False)}
        else:
            obj, prop = parts[0], parts[1]
            if obj not in spec['state']:
                spec['state'][obj] = {"type": "object", "default": {}}
            spec['state'][obj]['default'][prop] = "" if ty == "string" else (0 if ty == "number" else False)
            
    # Write to file
    with open(f"tasks/reference_specs/{tid}.json", "w") as f:
        json.dump(spec, f, indent=2)

print("Generated rough specs. Needs fixing UI elements.")
