# Contributing to HostShift

Thank you for your interest in contributing to HostShift!

## How to Contribute

### Reporting Issues
- Use GitHub Issues for bug reports and feature requests
- Include reproduction steps for bugs
- For benchmark design discussions, open a Discussion instead

### Code Contributions
1. Fork the repository
2. Create a feature branch (`git checkout -b feature/your-feature`)
3. Install dev tooling: `pip install -e .[dev]`
4. Run the test suite — every assertion must pass; the count is printed by the script:
   ```bash
   bash scripts/run_tests.sh   # bare-Python compatible, no pytest needed
   pytest                      # same tests via pytest (scoped to tests/)
   ruff check hostshift/ tests/ scripts/ experiments/
   ```
5. Submit a Pull Request using the PR template

CI runs the same gates on Python 3.11–3.14 plus a wheel-build smoke test that
proves the `hostshift` console script works from a real install.

### Adding Tasks
New tasks should be added to `tasks/suite_v1.jsonl`. Each task must:
- Have a unique `id` matching `<category>-<number>`
- Reference a valid category
- Include a `goal` that can be evaluated by the state oracle
- Include `criteria` as JSON path assertions on application state
- Include a `reference_spec` path

After editing the suite, run `hostshift lint` **and** copy the suite to
`hostshift/data/suite_v1.jsonl` (`cp tasks/suite_v1.jsonl hostshift/data/`) —
that shipped copy is what installed wheels use, and a sync-check test fails
if the two drift apart.

### Adding Host Support
New hosts require:
1. A renderer in `hostshift/render/<host>.py` that emits source files
2. A session class implementing the `Session` protocol
3. A `HostProfile` in `hostshift/render/base.py`
4. Cross-implementation verification tests

**Renderer embedding rule (mandatory).** Every renderer embeds the spec inside
string literals of another language, and every such seam is a defect class of
its own — unescaped metacharacters have already broken emitted Kotlin (`$state`
interpolation) and web (`</script>` truncation) apps here. A new renderer must
land with:

a. a **hostile-spec fixture** exercising its worst-case embedding (script-closing
   tags, dollar signs, triple-quotes, backslashes) in
   `tests/test_embedding_roundtrip.py`, and
b. an **embedding round-trip entry** in
   `hostshift/native_conformance.embedding_roundtrip()` proving the payload the
   running app sees equals the spec byte-for-byte semantically.

Run before submitting:
```bash
python3 -m hostshift render-check --specs tasks/reference_specs
```

See [docs/CUSTOMIZING.md](docs/CUSTOMIZING.md) for the full walkthrough,
including wiring generators and running experiments from GitHub Actions.

## License

By contributing, you agree that your contributions will be licensed under:
- **AGPL-3.0** for code
- **CC BY-NC-SA 4.0** for data/benchmark artifacts

## Code of Conduct

Be respectful, constructive, and inclusive. We follow the
[Contributor Covenant](https://www.contributor-covenant.org/).
