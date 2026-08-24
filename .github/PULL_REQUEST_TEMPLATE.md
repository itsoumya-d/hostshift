<!-- What does this PR change? One line. -->

## Summary

## Kind of change

- [ ] Benchmark measurement code (`hostshift/`)
- [ ] Renderers / sessions / hosts (`hostshift/render/`)
- [ ] Tasks or reference specs (`tasks/`, `schema/`)
- [ ] Tests only
- [ ] Docs only
- [ ] CI / packaging

## Checklist

- [ ] `bash scripts/run_tests.sh` green (count printed at the end)
- [ ] `ruff check hostshift/ tests/ scripts/ experiments/` clean
- [ ] If tasks/suite changed: copied to `hostshift/data/suite_v1.jsonl` (sync test enforces)
- [ ] If metrics changed: both HLI and per-task lock still reported together
- [ ] No simulated-session numbers presented as measurements
- [ ] README/docs updated for user-visible changes

## Measurement-integrity note

Does this PR touch anything that could let simulated results pass as
measured ones? If yes, explain why the rails still hold
(`tests/test_guards.py` must stay green).
