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
3. Run the test suite (`bash scripts/run_tests.sh`) — every assertion must pass; the count is printed by the script
4. Submit a Pull Request

### Adding Tasks
New tasks should be added to `tasks/suite_v1.jsonl`. Each task must:
- Have a unique `id` matching `<category>-<number>`
- Reference a valid category
- Include a `goal` that can be evaluated by the state oracle
- Include `criteria` as JSON path assertions on application state
- Include a `reference_spec` path

### Adding Host Support
New hosts require:
1. A renderer in `hostshift/render/<host>.py` that emits source files
2. A session class implementing the `Session` protocol
3. A `HostProfile` in `hostshift/render/base.py`
4. Cross-implementation verification tests

## License

By contributing, you agree that your contributions will be licensed under:
- **AGPL-3.0** for code
- **CC BY-NC-SA 4.0** for data/benchmark artifacts

## Code of Conduct

Be respectful, constructive, and inclusive. We follow the
[Contributor Covenant](https://www.contributor-covenant.org/).
