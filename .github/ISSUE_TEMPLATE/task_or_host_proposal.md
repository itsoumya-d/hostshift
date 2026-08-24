---
name: Task or host proposal
about: Propose a new benchmark task, category, host, or schema extension
title: '[suite] '
labels: benchmark-design
assignees: ''
---

**What to add**

A task row, a task category, a new host, or a UISpec language extension.

**Why it belongs**

- What real-world interface pattern does it cover?
- Is it expressible in UISpec 0.2? Run
  `hostshift coverage --corpus your-request.jsonl` if unsure.
- If it is *not* expressible: is that a gap worth closing (like
  `list.filterWhen` was), or an honest out-of-scope case?

**State-based criteria sketch**

The oracle grades application state, never pixels. Draft the criteria you
expect:

```json
{"kind": "...", "path": "...", "value": "..."}
```

**Willingness to contribute it**

Tasks land with reference specs + solver verification
(`scripts/verify_filter_specs.py`). Can you author those?
