# Zedda — Architecture Reference (v0.4.8 → v1.0)

> **Purpose of this document:** This is the canonical architecture and engineering-contract reference for the Zedda codebase. It is written for both human contributors and AI coding assistants (e.g. Antigravity, Claude Code) to consult before writing, reviewing, or refactoring any code in this repository. If a proposed change conflicts with a rule in this document, the rule wins unless this document is explicitly updated first.
>
> **Baseline audited:** v0.4.8, branch `pr-82-check`, HEAD `a61257f`
> **Status:** Pre-production. Do not represent Zedda's current trust/safety/performance claims as production-grade until the P0 items in Section 6 are closed.

---

## 1. What Zedda Is (and Is Not)

**Zedda is:** a fast, statistically honest data-profiling, validation, drift-detection, and cleaning-assistance engine, built on a C++ core with Python bindings.

**Zedda is not:** a general-purpose dataframe/query engine. It does not compete with Polars or Pandas on joins, groupby, lazy query planning, or transformation algebra. Do not add query-engine features to this codebase. Zedda's competitive set is `ydata-profiling`, `Great Expectations`, `whylogs`, `evidently.ai` — trust and evidence tooling, not dataframe engines.

**Core differentiator to protect in every design decision:** every number Zedda reports must be traceable — exact vs. approximate, what was actually scanned, what was unsupported, and how reproducible it is. Speed matters, but never at the cost of a silently wrong or fabricated result.

---

## 2. Non-Negotiable Architectural Rules

These rules apply to every PR, every module, every AI-assisted code change:

1. **No silent wrongness.** If a value cannot be computed exactly or a format/type isn't supported, the system must say so explicitly (`UNSUPPORTED`, `INDETERMINATE`, `ERROR`) — never quietly substitute a plausible-looking default (e.g. `NULL`, `PASS`, `0`).
2. **One canonical implementation per capability.** No parallel "public API" vs. "internal module" implementations of the same feature (this caused F-021, F-026, F-040–F-043 in the audit). Public functions are thin wrappers around one canonical engine call.
3. **Evidence and policy are separate.** Profiling/validation/drift produce *evidence*. Policy engines (ML-readiness, cleaning, warnings) *interpret* evidence. Policy engines must never re-read raw data or invent evidence not present in the `ProfileResult`.
4. **Cleaning never mutates directly.** All cleaning goes through: Plan (pure, no I/O) → Approval → Transactional Executor (temp file → verify → fsync → atomic replace → versioned backup/manifest).
5. **Streaming by default.** Canonical record streams are iterators, not fully materialized in-memory structures, unless a stage explicitly requires a full pass (and that must be documented and bounded).
6. **Correlation and other O(n²)-class analyses are opt-in**, resource-bounded, and operate only on explicitly selected columns — never part of the default profiling path.
7. **Every metric in a `ProfileResult` carries provenance**: value, exact/approximate, coverage, sample size, method, confidence, parse-error count, unsupported-field list.
8. **Benchmarks must benchmark the production code path.** Never benchmark an alternate/faster internal path (e.g. mmap/SIMD reader) and present it as representative of the public API's performance, and never change scanner-selection env vars after the scanner has already been cached for that process.
9. **No fabricated report content.** Reports render only measured values or explicitly labeled estimates. No synthetic histogram shapes, no hard-coded competitor comparisons.

---

## 3. Target Architecture — Layered View

```
DATA SOURCES
  CSV | Parquet | JSON | Excel | Arrow IPC | Feather | DataFrame
  (Database adapter: explicitly DEFERRED — P3+ scope, not current priority)
        │
        ▼  [P1]
INPUT ADAPTER REGISTRY
  - One InputAdapter contract implemented per format
  - Declares explicit supported / unsupported type list (never silently drops types)
  - Emits a LOGICAL record stream — not a physical-line stream
  - CSV adapter specifically: two-pass, quote-aware record boundary detection
      Pass 1: scan for safe record boundaries (tracks quote state across the file)
      Pass 2: assign boundary-aligned chunks to worker threads
  - Attaches schema + coverage metadata at the source, before any profiling occurs
        │  (streaming iterator — never fully materialized)
        ▼  [P1]
CANONICAL LOGICAL RECORD STREAM
  - DatasetSchema, ColumnSchema, DataTypes
  - Row-level and source-level metadata
  - Per-record validity flags (malformed width, parse error, etc. tagged at this layer)
        │
        ▼  [P1]
VERIFIED PROFILING KERNEL (C++)
  - Streaming, SIMD, mmap-backed, typed aggregation state (not Python-side mutation)
  - Computes: null counts, type inference, core stats, cardinality (HLL with ±0.0
    canonicalization), quantiles, distribution sketches
  - Denominators tracked SEPARATELY: valid_count, missing_count, invalid_count,
    parse_error_count, type_mismatch_count — statistics must state which
    denominator they used
  - Correlation is NOT in this default path — separate opt-in module (see Rule 6)
        │
        ▼  [P1]
TRUSTED PROFILE RESULT (immutable)
  - Every metric = { value, exact_or_approximate, coverage, sample_size, method,
    confidence, parse_errors, unsupported_fields }
  - This object must be able to answer: What was examined? How was it computed?
    What was invalid/unsupported? How reproducible is this?
        │
   ┌────┼─────────────────┬─────────────────────┐
   ▼ [P2]                 ▼ [P2]                ▼ [P2]
VALIDATION            COMPARE / DRIFT        DATA QUALITY
- Rule execution       - Shared baseline       - Missingness
  against evidence       bins/sketches         - Duplicates
- Tri-state result:    - Category evidence     - Outliers
  PASS / FAIL /          (bindings must         - "Health score" is a labeled
  INDETERMINATE           expose distinct         heuristic, never presented
  (never PASS an          values — see F-014)     as an objective/calibrated
  unevaluated rule)      - Explicit uncertainty    metric
- Violating-row           labels on drift
  evidence returned        verdicts
   │                     │                     │
   └─────────────────────┼─────────────────────┘
                          ▼
                  POLICY ENGINE
  - Pure function: Evidence -> Decision (typed, not string/print-based)
  - Domain-specific "policy packs" rather than one universal heuristic set
  - Confidence + threshold + target/task awareness required
  - HARD RULE: policy engines cannot invent evidence. If the ProfileResult
    lacks sufficient information, return INDETERMINATE — do not guess.
                          │
        ┌─────────────────┼─────────────────┐
        ▼ [P2]            ▼ [P2]            ▼ [P2]
   ML READINESS       CLEAN PLAN         WARNINGS
   - Target must be   - Pure, no I/O     - Evidence-backed
     explicit, never    (see Rule 4)       suggestions only
     silently picked                     - Never phrased as
   - Encoding maps                         verdicts
     persisted as
     train/serve
     artifacts
        │                  │
        │                  ▼
        │         CLEAN EXECUTOR
        │         - Approval gate (explicit user/CI confirmation)
        │         - temp output -> validate -> fsync -> atomic replace
        │         - versioned backup + rollback manifest
        │         - post-write verification pass
        └──────────────────┼──────────────────┘
                            ▼
                     OUTPUT LAYER
  - Python API, CLI, JSON, HTML/Reports
  - Renderers consume ProfileResult/Plan objects only — no business logic here
  - No fabricated comparisons or synthetic visualizations (Rule 9)
                            ▼
                 PRODUCT / DEVELOPER LAYER
  - Docs, examples, PyPI, GitHub, release gates, community, DX

CROSS-CUTTING (applies to every layer above):
  - Regression + Fuzz Corpus: CSV boundary cases, Arrow type/lifetime cases,
    sampling edge cases, drift fixtures, clean crash-recovery — runs on every merge
  - Security & Observability: structured logs, phase timings, memory limits,
    explicit error taxonomy
  - CI/CD: SHA-pinned GitHub Actions (not tag-pinned), installed-wheel functional
    tests, a real pre-production gate (not comment-only), ABI/platform matrix,
    native sanitizers
  - Benchmarks: production code path only (Rule 8)
```

**Ownership tiers:**
- **P1 = Data Engine + Core** — adapters, C++ kernel, canonical stream contract, performance
- **P2 = Intelligence Engine** — validation, drift, quality, policy engine, ML-readiness, cleaning, merge
- **P3 = Platform + Product** — Python API, CLI, reports, CI/CD, packaging, docs, community

---

## 4. Canonical Data Contracts (reference shapes)

Use these shapes as the target schema when refactoring. Exact language/type syntax can adapt to C++/Python as needed — the *fields* are what matter.

### 4.1 ProfileResult metric shape

```
Metric {
  value: any
  status: EXACT | APPROXIMATE | SAMPLED | UNSUPPORTED | ERROR
  coverage: { rows_examined: int, rows_total: int | UNKNOWN }
  sample_size: int | null
  method: string            // e.g. "HLL cardinality", "first-N reservoir", "footer stat"
  confidence: float | null
  parse_errors: int
  unsupported_fields: [string]
}
```

### 4.2 Validation rule result (tri-state, never binary)

```
RuleResult {
  status: PASS | FAIL | INDETERMINATE
  evaluated: bool           // false => status MUST be INDETERMINATE, never PASS
  violating_row_sample: [row] | null
  violating_row_count: int | null
  reason: string            // required when status != PASS
}
```

### 4.3 CleaningPlan (pure, no side effects)

```
CleaningPlan {
  proposed_changes: [Change]
  generated_from: ProfileResult (reference/id, not a copy)
  requires_approval: bool = true
  dry_run: bool = true      // default MUST be true
}

Change {
  column: string
  operation: string
  rationale: string          // must cite the evidence metric it came from
  reversible: bool
}
```

### 4.4 Clean execution transaction

```
CleanExecution {
  plan_id: string
  approved_by: string | "cli-flag" | "ci-policy"
  steps: [
    "write_temp_output",
    "post_write_validate",
    "fsync",
    "atomic_replace",
    "write_versioned_backup",
    "write_rollback_manifest"
  ]
  status: PENDING | COMPLETE | ROLLED_BACK | FAILED
}
```

---

## 5. Root Causes (from audit) → Architectural Fix

| Root Cause | Symptom | Fix Direction |
|---|---|---|
| R-001: Multiple ingestion implementations | Different type inference/sampling/perf depending on entry point | One `InputAdapter` contract; one canonical ingestion pipeline |
| R-002: No canonical evidence/provenance model | Can't tell exact vs. sampled vs. invalid | Immutable `ProfileResult` + per-metric provenance (Section 4.1) |
| R-003: Half-completed Python modularization | Tests pass against code users never actually call | One canonical implementation; public API = thin wrapper only |
| R-004: Evidence, policy, mutation coupled | Heuristics directly trigger destructive mutation | Evidence → Policy → Plan → Execute, with an approval gate between Plan and Execute |
| R-005: Weak type semantics | int64/uint64 → double precision loss; date32/time32/timestamp conflated | Typed value adapters; typed aggregation state per Arrow logical type |
| R-006: Failure semantics not fail-closed | Unsupported/invalid data becomes plausible success | Explicit `PASS/FAIL/INDETERMINATE/UNSUPPORTED/ERROR` states everywhere |
| R-007: Presentation owns product claims | Reports contain fabricated comparisons | Renderers only render measured `ProfileResult`/`Plan` data |

---

## 6. P0 — Must Fix Before Any "Production-Ready" Claim

These correspond to confirmed, reproduced findings in the audit (see finding IDs in parentheses).

1. **(F-001, F-003)** Disable or constrain parallel CSV processing until logical-record (quote-aware) boundary correctness is implemented and fuzz-tested. Physical-newline chunking on quoted multiline CSVs is a silent data-corruption bug.
2. **(F-004)** Separate valid/missing/invalid/parse-error/type-mismatch counts. Never let an invalid value silently distort a mean/variance denominator.
3. **(F-005, F-010)** Do not route exact integer identity through `double`. uint64/int64 must retain precision; do not use double as the universal numeric intermediate.
4. **(F-009, F-011)** Reject unsupported Arrow types explicitly rather than converting to `NULL`. Fix date32/time32/timestamp — they are not interchangeable physical widths.
5. **(F-024, F-025, F-038)** Validation must fail closed — `PASS` only after a rule is actually evaluated against real data. Approximate uniqueness must not pass an exact-uniqueness contract.
6. **(F-014)** Categorical drift depends on binding fields (`distinct_values`, `distinct_overflowed`) not currently exposed by `bindings.cpp`. Either expose them or disable the categorical-drift verdict — do not let it silently return empty/misleading results.
7. **(F-015, F-016, F-051, F-052)** `clean()` needs a transactional plan/execute boundary (Section 4.3/4.4) with dry-run default, versioned backup, and rollback manifest. No direct mutation.
8. **(F-021, F-022)** Public profiling path and benchmarked path must be the same code. Benchmark switching must not rely on env vars changed after scanner caching.
9. **(F-023, F-047)** Remove hard-coded/fabricated report comparisons (e.g. "21× faster than pandas," synthetic histogram shapes).
10. **(F-026, F-040)** Eliminate competing public vs. extracted-module implementations — one canonical implementation per capability, no exceptions.
11. **(F-036)** Fix conda recipe placeholder SHA256 / stale version metadata before any release claiming conda support.

---

## 7. P1 — High Priority (after P0 is closed)

- Replace first-N/first-seen distribution sampling with deterministic representative sampling or mergeable sketches (KLL/t-digest). Current PSI/KS-style outputs are not statistically valid (non-shared bins, biased samples).
- Make correlation opt-in, resource-bounded, operating only on user-selected numeric columns (not all columns pre-selection).
- Merge: fail closed by default on unreadable inputs; make schema/dedup policy explicit; do not silently skip failed inputs; do not let all-input-failure surface as a raw `IndexError`.
- Arrow: schema-compatibility checks across batches; fix `finalize()` idempotency (audit found sanitizer-reproduced invalid access on repeated finalize).
- Persist categorical encoding maps as versioned train/serve artifacts with an explicit unknown-category policy.
- Fix benchmark methodology to test the actual production path exclusively.
- Expand fuzzing to cover CSV chunk boundaries, Arrow type/lifetime edge cases, sampling edge cases.
- Installed-wheel functional tests (not import-only) across the supported ABI/platform matrix.
- Pin GitHub Actions to immutable commit SHAs, not mutable tags.

---

## 8. Required Regression / Test Coverage

| Area | Must cover |
|---|---|
| CSV | Quoted multiline records crossing worker boundaries; malformed row widths; BOM; empty rows; escaped quotes; very large records; deterministic sampling |
| Statistics | Invalid values, denominator correctness, int64/uint64 precision at boundary values, ±0 canonicalization, exact vs. approximate uniqueness |
| Arrow | date32/time32/timestamp, uint64/int64, decimal, dictionary, binary/nested unsupported types, sliced arrays, batch schema changes, lifetime + repeated `finalize()` |
| Validation | Unevaluable rule → INDETERMINATE (never PASS); exact uniqueness; regex/allowed-values streaming validation; violating-row evidence returned |
| Cleaning | Dry-run plan, approval gate, crash-during-write recovery, backup preservation, rollback, post-write verification, manifest recovery |
| Merge | Unreadable-input behavior, all-input-failure behavior, schema conflicts, duplicate policy, large-file memory bounds |
| Drift | Shared bins, representative sampling, category add/remove detection, uncertainty labeling, baseline registration |
| CI/CD | Installed-wheel functional tests, release staging gate, ABI/platform matrix, native sanitizers, dependency integrity |

**Rule for AI-assisted changes:** any PR touching CSV parsing, Arrow conversion, validation logic, or cleaning must add or update a test in the corresponding row above before merge.

---

## 9. Migration Strategy (strangler pattern — do not big-bang rewrite)

1. Freeze current behavior with regression fixtures; record known-good outputs.
2. Introduce typed `ProfileResult` + provenance schema (Section 4.1) alongside existing code.
3. Introduce `InputAdapter` interface; migrate CSV first (highest-risk area).
4. Move Arrow/Parquet/Feather onto the same evidence contract.
5. Make public `scan()`/`profile()` thin orchestration wrappers around the canonical kernel.
6. Migrate validation and compare/drift to consume only canonical `ProfileResult` evidence.
7. Split cleaning into planner/executor; add transaction manifest.
8. Migrate merge and ML-readiness to explicit typed policies.
9. Delete duplicated implementations from `__init__.py`.
10. Enforce installed-wheel + regression correctness as CI/release gates.

**Do not skip ahead** — e.g. do not build the Policy Engine (Section 3) before `ProfileResult` provenance (step 2) exists, since policy correctness depends on evidence completeness.

---

## 10. Definition of Done — v0.5 Milestone

- [ ] Same logical dataset produces semantically consistent profiles across all supported input adapters.
- [ ] No unsupported input value is silently converted into a valid-looking `NULL`.
- [ ] All statistics have explicit denominators and provenance.
- [ ] Validation cannot `PASS` without evaluating the rule.
- [ ] Cleaning is dry-run by default and transactional when executed.
- [ ] Public APIs delegate to one canonical implementation per capability.
- [ ] Drift outputs are statistically defensible and explicitly uncertain when evidence is insufficient.
- [ ] Reports contain only measured data or clearly labeled estimates.
- [ ] Installed wheels execute functional tests on supported platforms.
- [ ] Critical regression corpus runs on every merge and release.

---

## 11. Solo-Developer Governance Model

The audit's ideal review model (Owner → Build, Second person → Review, Third person → Test, all-3 approval on critical changes) assumes a team. Current reality: single maintainer. Adapted process:

1. **Build** the change on a feature branch.
2. **24-hour cool-down** — do not self-review immediately after writing code.
3. **Self-review pass** against a checklist derived from Section 2 (Non-Negotiable Rules) and the relevant row in Section 8 (Test Coverage).
4. **Separate test-writing session** — write/extend tests in a distinct sitting, ideally attacking the change adversarially (as if trying to break it), not confirming it.
5. **Merge** only after 3–4 pass.
6. For P0-severity areas (CSV parsing, cleaning, validation correctness), treat step 3–4 as mandatory, not optional, regardless of time pressure.
7. As the project grows, label "good first issue" items to start attracting real second-reviewer contributors — this is a stated long-term goal, not just a review-model gap-filler.

**No direct pushes to `main`.** Feature branch → PR (even solo) → checklist pass → tests green → merge. This creates an audit trail and forces the cool-down step.

---

## 12. Instructions for AI Coding Assistants Working in This Repo

If you are an AI assistant (Antigravity, Claude Code, or similar) making changes to Zedda:

1. **Check Section 2 first.** Any change that violates a Non-Negotiable Rule should be flagged to the user, not silently implemented.
2. **Do not add features outside Zedda's scope** (Section 1) — no query engines, no groupby/join APIs, no general dataframe transformation surface.
3. **Never introduce a second implementation of an existing capability.** If you find `_scan.py` and `scan()` in `__init__.py` diverging, that itself is a bug to report (see F-040), not a pattern to extend.
4. **When touching CSV, Arrow, validation, or cleaning code**, cross-check against Section 8 and add the missing test before considering the change complete.
5. **When generating profiling output, reports, or benchmark code**, apply Rule 8 and Rule 9 (Section 2) strictly — no fabricated comparisons, no benchmarking a non-production path.
6. **Default new destructive operations to dry-run.** If asked to implement any data-mutating feature, implement the Plan/Execute split (Section 4.3/4.4) rather than direct mutation, even if not explicitly requested — then flag the design choice to the user.
7. **If a requested change would make a metric's provenance ambiguous** (exact vs. approximate unclear, sample coverage unclear), stop and ask, rather than defaulting to whichever is easier to code.

---

## Appendix — Audit Traceability

This document synthesizes two audit passes:
- Original co-founder audit (10 executive findings, severity-tagged)
- Independent verification audit (v0.4.8, branch `pr-82-check`, HEAD `a61257f`) — 56 findings (F-001 to F-056), 7 root causes (R-001 to R-007), full severity model (P0/P1/P2/P3)

All finding IDs referenced in Sections 5–7 map to the independent verification audit's Master Finding Register. Keep this document updated as findings are closed — move closed items from Section 6/7 into a "Resolved" appendix with the PR/commit reference, rather than deleting them, to preserve audit history.