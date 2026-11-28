# Evaluate UI Portability

Use this skill when evaluating whether LLM-generated user interfaces survive a change of host platform across Web, iOS (SwiftUI), Android (Jetpack Compose), Flutter, and Terminal (Textual), or when running validation, cost estimation, coverage checks, and synthetic benchmark pipelines on the HostShift suite.

## Steps

1. Validate the task suite structure and integrity:
   Run: `python -m hostshift lint`
   Expected result: Outputs task count, category breakdown, and concludes with "suite is well formed".

2. Estimate the experiment execution footprint and API costs:
   Run: `python -m hostshift plan --generators gemini,claude,gpt --repeats 2`
   Expected result: Shows matrix of tasks, generator calls, operator runs, and estimated API dollar cost.

3. Verify schema expressiveness and coverage across reference specs:
   Run: `python -m hostshift coverage`
   Expected result: Displays expressiveness rate (e.g. >= 65%) and breakdowns across widget categories.

4. Check native renderer code generation gates for mobile and web targets:
   Run: `python -m hostshift render-check --specs tasks/reference_specs/filter-001.json`
   Expected result: Verifies compiler syntax and semantic emission across SwiftUI, Compose, and Flutter fixtures.

5. Execute a synthetic end-to-end benchmark run in an isolated store:
   Run: `python -m hostshift demo --repeats 2 --out runs/demo`
   Expected result: Simulates benchmark evaluations without making external API calls and writes logs to `runs/demo`. Note: Stop for user confirmation before running non-synthetic live experiments that mutate production stores.

6. Aggregate results into evaluation tables and summary metrics:
   Run: `python -m hostshift report --runs runs/demo --json`
   Expected result: Outputs JSON object with Interaction Parity, Host Lock Index, and reliability metrics.
