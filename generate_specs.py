import json
import copy
import re

tasks = [json.loads(x) for x in open('tasks/suite_v1.jsonl')]

def load_template(cat):
    for t in tasks:
        if t['category'] == cat and t['id'].endswith('-001'):
            with open(f'tasks/reference_specs/{t["id"]}.json') as f:
                return json.load(f)
    raise ValueError(cat)

def generate_form_spec(t, tmpl):
    spec = copy.deepcopy(tmpl)
    spec['title'] = t['prompt'].split(' form')[0].strip('A ').capitalize()
    
    # find collection
    c_contains = next((c for c in t['criteria'] if c['kind'] == 'collection_contains'), None)
    c_count = next((c for c in t['criteria'] if c['kind'] == 'collection_count'), None)
    s_equals = [c for c in t['criteria'] if c['kind'] == 'state_equals']
    s_truthy = next((c for c in t['criteria'] if c['kind'] == 'state_truthy'), None)
    
    if c_contains:
        col_name = c_contains['collection']
        match = c_contains['match']
        
        # update collections
        spec['collections'] = {
            col_name: {
                "fields": {k: {"type": "number" if isinstance(v, (int, float)) else "string"} for k, v in match.items()},
                "seed": []
            }
        }
        
        # update state
        spec['state'] = {k: {"type": "number" if isinstance(v, (int, float)) else "string", "default": 0 if isinstance(v, (int, float)) else ""} for k, v in match.items()}
        if s_truthy:
            spec['state'][s_truthy['path']] = {"type": "boolean", "default": False}
            
        # update screens
        scr = spec['screens'][0]
        scr['id'] = 'home'
        scr['title'] = spec['title']
        
        children = [{"kind": "heading", "id": "title", "label": spec['title']}]
        
        for k, v in match.items():
            children.append({
                "kind": "field",
                "id": k,
                "label": k.capitalize(),
                "bind": k
            })
            
        action = [
            {
                "op": "append",
                "target": col_name,
                "value": {k: f"$state.{k}" for k in match.keys()}
            }
        ]
        if s_truthy:
            action.append({"op": "set", "target": s_truthy['path'], "value": True})
            
        children.append({
            "kind": "button",
            "id": "submit",
            "label": "Submit",
            "action": action
        })
        
        if s_truthy:
            children.append({
                "kind": "banner",
                "id": "confirmation",
                "tone": "success",
                "label": "Success",
                "visibleWhen": {"op": "truthy", "left": s_truthy['path']}
            })
            
        scr['children'] = children
        
    elif s_equals:
        # no collection, just state updates
        spec['collections'] = {}
        spec['state'] = {}
        for s in s_equals:
            spec['state'][s['path']] = {"type": "number" if isinstance(s['value'], (int, float)) else "string", "default": 0 if isinstance(s['value'], (int, float)) else ""}
        if s_truthy:
            spec['state'][s_truthy['path']] = {"type": "boolean", "default": False}
            
        scr = spec['screens'][0]
        scr['id'] = 'home'
        scr['title'] = spec['title']
        
        children = [{"kind": "heading", "id": "title", "label": spec['title']}]
        
        action = []
        for s in s_equals:
            path = s['path'].split('.')[-1]
            children.append({
                "kind": "field",
                "id": path,
                "label": path.capitalize(),
                "bind": s['path']
            })
        
        if s_truthy:
            action.append({"op": "set", "target": s_truthy['path'], "value": True})
            children.append({
                "kind": "button",
                "id": "submit",
                "label": "Submit",
                "action": action
            })
            children.append({
                "kind": "banner",
                "id": "confirmation",
                "tone": "success",
                "label": "Success",
                "visibleWhen": {"op": "truthy", "left": s_truthy['path']}
            })
        
        scr['children'] = children

    return spec

def generate_list_spec(t, tmpl):
    spec = copy.deepcopy(tmpl)
    spec['title'] = t['prompt'].split(' list')[0].capitalize()
    
    c_field_eq = [c for c in t['criteria'] if c['kind'] == 'collection_field_equals']
    c_count = next((c for c in t['criteria'] if c['kind'] == 'collection_count'), None)
    
    if c_field_eq:
        col_name = c_field_eq[0]['collection']
        where = c_field_eq[0]['where']
        field = c_field_eq[0]['field']
        val = c_field_eq[0]['value']
        
        where_k, where_v = list(where.items())[0]
        
        spec['state'] = {"selectedId": {"type": "string", "default": ""}}
        
        # determine seed
        seed_items = []
        # Need to allow the criteria to pass! If operator drives correctly, they will change `field` to `val` for the item matching `where`.
        # So we need an item matching `where` with `field` not equal to `val`.
        seed_items.append({where_k: where_v, field: "pending"})
        # We need more items to match collection_count, if any. But count is typically after deletion or something?
        # Actually in list-001 count is just 5, implying 5 items.
        target_count = c_count['value'] if c_count else 5
        for i in range(1, target_count):
            seed_items.append({where_k: f"Other {i}", field: "pending"})
            
        spec['collections'] = {
            col_name: {
                "fields": {where_k: {"type": "string"}, field: {"type": "string"}},
                "seed": seed_items
            }
        }
        
        # screens
        list_scr = spec['screens'][0]
        list_scr['id'] = 'list'
        list_scr['title'] = spec['title']
        list_scr['children'] = [
            {"kind": "heading", "id": "listtitle", "label": spec['title']},
            {
                "kind": "list",
                "id": "items",
                "of": col_name,
                "rowLabel": where_k,
                "rowAction": [
                    {"op": "set", "target": "selectedId", "value": f"$row.{where_k}"},
                    {"op": "navigate", "target": "detail"}
                ]
            }
        ]
        
        det_scr = spec['screens'][1]
        det_scr['id'] = 'detail'
        det_scr['title'] = 'Detail'
        det_scr['children'] = [
            {"kind": "heading", "id": "detailtitle", "label": "Detail"},
            {"kind": "text", "id": "detailname", "label": "Selected", "bind": "selectedId"},
            {
                "kind": "button",
                "id": "actionBtn",
                "label": "Action",
                "action": [
                    {
                        "op": "update",
                        "target": col_name,
                        "value": {
                            "where": {where_k: "$state.selectedId"},
                            "set": {field: val}
                        }
                    },
                    {"op": "navigate", "target": "list"}
                ]
            }
        ]
    return spec

def generate_filter_spec(t, tmpl):
    spec = copy.deepcopy(tmpl)
    spec['title'] = "Filterable Data"
    
    s_eqs = [c for c in t['criteria'] if c['kind'] == 'state_equals']
    vis_count = next((c for c in t['criteria'] if c['kind'] == 'visible_row_count'), None)
    
    col_name = vis_count['collection'] if vis_count else "items"
    
    spec['state'] = {}
    for s in s_eqs:
        path = s['path']
        spec['state'][path] = {"type": "string", "default": ""}
        
    # extract filter fields
    filter_fields = []
    for s in s_eqs:
        if s['path'].startswith('filter.'):
            filter_fields.append((s['path'], s['value']))
            
    # We must seed data such that filtering leads to vis_count rows.
    # To be safe, we will add vis_count rows that match the filter, and a few that don't.
    seed = []
    tcount = vis_count['value'] if vis_count else 3
    for i in range(tcount):
        item = {"name": f"Match {i}"}
        for path, val in filter_fields:
            field = path.split('.')[1]
            item[field] = val
        seed.append(item)
    for i in range(3):
        item = {"name": f"NoMatch {i}"}
        for path, val in filter_fields:
            field = path.split('.')[1]
            item[field] = f"Other {val}"
        seed.append(item)
        
    spec['collections'] = {
        col_name: {
            "fields": {k: {"type": "string"} for k in seed[0].keys()},
            "seed": seed
        }
    }
    
    # screens
    scr = spec['screens'][0]
    children = [{"kind": "heading", "id": "title", "label": spec['title']}]
    for path, val in filter_fields:
        field = path.split('.')[1]
        children.append({
            "kind": "field",
            "id": f"filter_{field}",
            "label": f"Filter {field}",
            "bind": path
        })
    # Add sort toggles if any
    sort_fields = [s for s in s_eqs if s['path'].startswith('sort.')]
    if sort_fields:
        children.append({
            "kind": "button",
            "id": "sortbtn",
            "label": "Sort",
            "action": [
                {"op": "set", "target": s['path'], "value": s['value']} for s in sort_fields
            ]
        })
        
    # The list needs a visibleWhen that evaluates the filter! But hostshift filtering logic might be implicit if we just use a list. 
    # Wait, in filter-001, filtering is done via list 'filter' prop. Let's look at it.
    
    return spec

for t in tasks:
    if t['id'].endswith('-001'):
        continue
        
    cat = t['category']
    tmpl = load_template(cat)
    
    spec = None
    if cat == 'form_validation':
        spec = generate_form_spec(t, tmpl)
    elif cat == 'list_detail':
        spec = generate_list_spec(t, tmpl)
        
    if spec:
        with open(f"tasks/reference_specs/{t['id']}.json", "w") as f:
            json.dump(spec, f, indent=2)

print("Done generating simple specs.")
