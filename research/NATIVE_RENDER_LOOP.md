# Research Log: Native Render Layer, GenUI Convergence, and the Road Ahead

**Cycle 1 — 2026-08-24.** Standing research loop over the HostShift render
layer (Swift/Kotlin/native), the generative-AI interface ecosystem, and how
this benchmark stays best-in-class. Each cycle: research → implement → test →
push → record findings here and in the README.

---

## 1. Ecosystem scan (verified 2026-08-24)

The generative-UI world converged hard on **declarative specs rendered natively
by the host** in late 2025–2026. HostShift's UISpec is squarely in this family,
which means its measurement question ("does a generated spec survive a change of
host?") is now an industry question, not just an academic one.

| Protocol / format | Owner | Shape | Status |
|---|---|---|---|
| **A2UI v0.9** | Google | JSONL stream of component descriptions against a host-advertised catalog; renderers for Flutter/Lit/Angular/React; Python Agent SDK; runs over AG-UI, MCP, A2A, REST | Apache-2.0, production |
| **MCP-Apps (SEP-1865)** | Anthropic + OpenAI | `ui://` resource = self-contained HTML/JS/CSS in sandboxed iframe | First official MCP extension, stable since Jan 2026 |
| **AG-UI** | CopilotKit | Event-stream transport between agent and UI | Widely adopted |
| Open-JSON-UI / json-render | OpenAI / Vercel | Declarative JSON trees | Shipping |

Key takeaways for this repo:

1. **Declarative won the middle of the freedom axis.** Static tool-calls are too
   rigid; raw HTML is untrusted and visually foreign. Every major vendor now
   ships "agent composes primitives, host renders natively" — exactly the
   Condition-B arm of this benchmark.
2. **Nobody in that stack measures portability.** A2UI advertises four renderer
   implementations but no parity metric; MCP-Apps sandboxed iframes sidestep the
   native-realization question entirely. The HLI/RP/AP/IP measurement is the
   missing instrument for all of them. This is a positioning gift: *HostShift can
   become the conformance harness the GenUI protocols lack.*
3. **A2UI's failure mode is ours to measure.** Its docs admit declarative
   composition lets agents "compose bad structure — a form with the submit
   button above the fields." Structural fidelity under composition pressure is
   measurable with our TED + oracle machinery today.

## 2. What the native layer looked like before this cycle

The README disclosed it honestly: Swift numbers carried an implementation
confound because only the JavaScript runtime had a cross-implementation
agreement harness (`test_crossimpl.py`). Kotlin was "structurally validated"
by brace-counting. No emitted Kotlin had ever met a real compiler inside this
repo, and no CI machine without Xcode could even check Swift syntax.

## 3. What was done this cycle

1. **`hostshift/native_conformance.py` + `hostshift render-check`.**
   - Compiles every emitted `GeneratedApp.swift` with `swiftc -parse`
     (99 fixtures on this machine) and a representative `MainActivity.kt`
     with a real `kotlinc` — discovered on PATH or inside Android Studio
     (app bundles ship non-executable scripts, so we probe with `sh` +
     Android Studio's bundled JBR).
   - Kotlin compile errors are classified: classpath noise (unresolved
     Compose/Android symbols outside Gradle) is tolerated and reported;
     anything else fails. Filter validated empirically: healthy template →
     zero residual errors.
   - Differential semantic checks assert each native runtime's observable
     contract (realized-tree instrumentation, explicit Compose field labels,
     `$state.` resolution, route navigation) against its declared
     `HostProfile`, so profile/source drift becomes a named finding instead
     of an unattributed "host gap."
2. **Found and fixed a real defect.** The Compose renderer interpolated the
   spec JSON into a Kotlin triple-quoted literal unescaped. UISpec state
   references *are* `$state.x` / `$row.x` — Kotlin interpolates `$name` inside
   `"""…"""`. Every filterWhen task would have failed to compile (or silently
   mangled its predicate) on device. Fix: escape dollars in `emit()`;
   pinned by `test_kotlin_escapes_state_dollars`.
3. Also fixed: `const val SPEC_JSON` rejected non-constant JSON strings by
   newer kotlinc → `val`.

Result: 215 pytest assertions green locally (was 211); `render-check` exits 0
with 100/100 toolchain checks and 41/41 differential checks across all 100
reference specs.

## 4. Findings worth carrying forward

- **Compile gates catch what golden-string tests cannot.** Brace-balancing
  passed while every filter spec was uncompilable. Real toolchains are cheap to
  probe and belong in dev-loop and pre-experiment checklists, not just CI.
- **Escaping seams are the top bug class for template-based emitters.**
  Spec content flows into string literals of three different languages
  (Kotlin interpolation, Swift raw literals, JS template literals) plus
  Python `.format()` braces in two templates. A systematic audit of the other
  seams (JS backticks, Python `{}`) should be a future cycle.
- **kotlinc-without-Gradle is usable if you classify errors.** Full Android
  type-checking needs the SDK classpath, but syntax + local-semantic errors
  surface fine. The noise-filter list doubles as documentation of which error
  classes are classpath artifacts.

## 5. Where this goes next (bigger than Kotlin/Swift)

The thesis: **any host that can express state + a11y tree + actions can join
the benchmark**, and any generated code can be measured by it:

- **New hosts:** Flutter (huge GenUI share via A2UI), React Native,
  Wear OS / watchOS (same schema, radically degraded realization — the
  strongest possible HLI demonstration), voice interfaces (the a11y tree maps
  naturally onto utterance transcripts), AR surfaces.
- **New generators:** point condition A at open-weight models and structured-
  output APIs; measure whether constrained decoding narrows the A↔B gap.
- **Streaming specs:** UISpec is currently whole-document. A2UI streams JSONL;
  adding incremental patch semantics would let HostShift measure *streaming*
  portability (does a partially-arrived spec render usefully?), which no
  benchmark does.
- **Protocol adapters as first-class arms:** translate UISpec ↔ A2UI and run
  their renderers through our oracle — turning the benchmark into a
  cross-protocol conformance suite.
- **CI without simulators:** the compile gate added here is the template; a
  GitHub Actions job with kotlinc + swiftc gives every fork native-toolchain
  verification with zero emulator cost.

## 6. Verification checklist for the next cycle

- [x] ~~Audit remaining escaping seams (web.py JS, tui.py Python format)~~ — done, cycle 2 below.
- [ ] Check `vpbydesign/ame` activity again before submission (nearest
      competitor per README novelty notes).
- [ ] Re-scan A2UI / MCP-Apps changelogs for portability-metric work (if any
      appears, cite and differentiate immediately).

---

# Cycle 2 — 2026-08-24: escaping-seam audit

**Second real defect found.** The web renderer interpolated the spec JSON into
the emitted page's `<script>` block unescaped. Any spec whose text contains a
literal `</script>` — trivially producible by an LLM generator asked for, say,
an HTML-formatting help panel — terminated the script element mid-JSON:
truncating the spec (render parity would score the loss as a host gap) and
forming an XSS vector. Fix: escape `</` → `<\/` (valid JS string syntax) and
`<!--` → `<\!\--`; round-trip verified through JSON parsing; pinned by
`test_web_escapes_script_closing_tags`.

The TUI seam was audited and is **safe**: the spec rides in an `r"""…"""`
raw string, `json.dumps` quotes backslashes so no `"""` sequence can form from
spec content, and Python's parser reads it back byte-exact. Verified against
hostile inputs (embedded triple-quotes, quotes, backslashes);
pinned by `test_tui_raw_string_survives_hostile_spec`.

**Generalized finding — escaping seams are systematic, not incidental.** A
template-based emitter has one seam per embedding language: Swift raw literals
(safe), Kotlin triple-quote interpolation (fixed cycle 1), HTML script blocks
(fixed this cycle), Python raw strings (safe). Any future host template must be
added to this audit list at birth. Proposed rule for CONTRIBUTING: *every new
renderer lands with (a) a hostile-spec fixture exercising its worst-case
embedding and (b) a compile-or-parse gate in `native_conformance.py`.*

Status after cycle 2: 217 assertions green, render-check 100/100 + 41/41,
both fixes pushed.
