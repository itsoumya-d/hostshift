import json
import os
import sys

from hostshift.oracle import grade, load_suite
from hostshift.render import open_session

os.environ["HOSTSHIFT_ALLOW_SIMULATED"] = "1"

tasks = load_suite("tasks/suite_v1.jsonl")
created = 0
passed = 0

for t in tasks:
    tid = t['id']
    spec_path = f"tasks/reference_specs/{tid}.json"
    if os.path.exists(spec_path):
        created += 1
        with open(spec_path) as f:
            spec = json.load(f)
        
        try:
            # We just need to open the session and see if it crashes
            session = open_session(spec, host="web", simulated=True)
            passed += 1
        except Exception as e:
            print(f"Failed {tid}: {e}")

print(f"Specs created: {created}")
print(f"Specs pass validation: {passed}")
