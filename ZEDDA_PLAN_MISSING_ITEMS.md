# Zedda CI/CD Plan — Missing Items & Corrections

**Date:** 2026-07-18
**Subject:** Critical gaps in the proposed `implementation_plan.md` that must be addressed before execution
**Verdict:** Architecture is correct, but 5 critical items are missing and the execution order is dangerous

---

## Executive Summary

Your `implementation_plan.md` has the **right architecture** (umbrella + reusable workflows + consolidation pattern — same as pandas/NumPy). But it has:

- **5 critical missing items** that will cause user-facing failures or security risks
- **Dangerous execution order** (delete-first-then-build leaves a window with zero CI)
- **No acknowledgment of PR #43's progress** (cp314, ARM64, pyarrow-optional already done)
- **No mention of the 7 library bugs** that block v0.4.6 release

This file lists everything missing, with exact code/config to add.

---

## Missing Item 1: The 7 Critical Library Bugs (Highest Priority)

### What's Missing

Your plan jumps straight to CI/CD without mentioning that **the library itself has 7 critical bugs** that will crash users on first use. No amount of CI/CD perfection fixes these — they're code bugs in `__init__.py`, `cli.py`, `ai_insights.py`, and `pyproject.toml`.

### The 7 Bugs

| # | Bug | File | Impact |
|---|---|---|---|
| 1 | `requests` used but not declared in deps | `pyproject.toml` | `zd.ask()` crashes on clean installs |
| 2 | `ai_insights.py` is a 32-line stub | `python/zedda/ai_insights.py` | `zedda run --ai` prints "not implemented" |
| 3 | CLI reads `OPENAI_API_KEY`, code reads `ZEDDA_AI_KEY` | `cli.py` lines 50, 319, 321 | `--ai` flag never works |
| 4 | CLI claims "Excel, JSON" but `scan()` rejects them | `cli.py` lines 48, 63 | `zedda run sales.xlsx` crashes |
| 5 | `openai` declared but code uses Groq + `requests` | `pyproject.toml` line 56 | `[ai]` extra installs wrong package |
| 6 | No `to_json()`/`to_dict()` on profile objects | `__init__.py` | Can't export results programmatically |
| 7 | `sys.path.insert` in `cli.py` (security risk) | `cli.py` lines 23-28 | Attacker can shadow stdlib modules |

### Why This Matters Before CI/CD

If you ship v0.4.6 tomorrow with marketing:
- User tries `zedda run data.csv --ai` → sees "not fully implemented" → uninstalls
- User tries `zedda run sales.xlsx` → sees "Unsupported format" → uninstalls
- User runs `pip install zedda[ai]` → gets wrong package → `zd.ask()` crashes → uninstalls

**First impressions matter. A user who hits a bug in the first 5 minutes never comes back.**

### What to Add to the Plan

Add **Step 0** before the CI/CD work:

```markdown
## Step 0: Fix 7 Critical Library Bugs ( BEFORE CI/CD work)

### Fix 1: pyproject.toml — declare requests, remove openai
- Line 56: change `ai = ["openai>=1.0,<3.0"]` to `ai = ["requests>=2.28"]`

### Fix 2: cli.py — fix env var name (3 locations)
- Line 50: help text "OPENAI_API_KEY" → "ZEDDA_AI_KEY"
- Line 319: `os.environ.get("OPENAI_API_KEY")` → `os.environ.get("ZEDDA_AI_KEY")`
- Line 321: tip message "OPENAI_API_KEY" → "ZEDDA_AI_KEY"

### Fix 3: cli.py — remove false Excel/JSON claim
- Line 48: "CSV, Excel, JSON, or Parquet" → "CSV, Parquet, or Arrow"
- Line 63: example `sales.xlsx` → `sales.parquet`

### Fix 4: ai_insights.py — replace stub with real implementation
- Replace entire file with code that calls `_ask_zedda_ai()` backend

### Fix 5: Test locally before tagging v0.4.6
- pip install . in clean venv
- Run zedda run data.csv --ai (without key → should show tip)
- Run with ZEDDA_AI_KEY set → should generate real insights
- Run zedda run sales.xlsx → should fail with clear error (not crash)
```

**Reference file:** `ZEDDA_PRE_RELEASE_CRITICAL_FIXES.md` has full code for all 7 fixes.

---

## Missing Item 2: SHA-pin `pypa/gh-action-pypi-publish`

### What's Missing

Your plan mentions "TestPyPI Safety Gate" but doesn't address the **single most important supply-chain fix** in your release pipeline.

### Current State (verified on `main`)

`.github/workflows/build_wheels.yml` lines 172 and 218:
```yaml
uses: pypa/gh-action-pypi-publish@release/v1
```

This is the **only non-SHA-pinned action** in your entire repo. Every other action (22 of them) is SHA-pinned.

### Why This Is Critical

- The PyPI publish action has `id-token: write` permission (trusted publishing)
- If the `release/v1` branch is ever compromised, every release ships a backdoored package under your name
- OpenSSF Scorecard deducts points for this
- This is the highest-risk supply-chain vulnerability in your pipeline

### What to Add to the Plan

Add to the release workflow section:

```markdown
### Critical: SHA-pin the PyPI publish action

The action `pypa/gh-action-pypi-publish` is the ONLY non-SHA-pinned action
in the repo. This is a supply-chain risk.

Get the current SHA:
\`\`\`bash
curl -sSL https://api.github.com/repos/pypa/gh-action-pypi-publish/commits/release/v1 | \
  python3 -c "import sys,json;print(json.load(sys.stdin)['sha'])"
\`\`\`

Replace BOTH occurrences of `@release/v1` with `@<SHA> # v1.12.4` in release.yml.
```

**Exact fix in `release.yml`:**
```diff
- uses: pypa/gh-action-pypi-publish@release/v1
+ uses: pypa/gh-action-pypi-publish@76f52bc884231f62b9a034ebfe128415bbaabdfc # v1.12.4
```

(Verify the SHA at https://github.com/pypa/gh-action-pypi-publish/commits/release/v1 before pinning)

---

## Missing Item 3: Remove `continue-on-error: true` from TestPyPI

### What's Missing

Your plan claims "TestPyPI Safety Gate" but doesn't address that the current gate is a **no-op**.

### Current State (verified on `main`)

`.github/workflows/build_wheels.yml` line 146:
```yaml
publish_test:
    name: Publish to TestPyPI
    needs: [build_wheels, build_sdist]
    runs-on: ubuntu-latest
    timeout-minutes: 10
    continue-on-error: true        # ← THIS MAKES THE GATE A NO-OP
    environment: testpypi
```

### Why This Is Critical

`continue-on-error: true` means:
- If TestPyPI publish fails → job is marked "successful" (with warning)
- `publish_pypi` has `needs: [publish_test]` → sees success → proceeds
- **Bad packages can ship to production PyPI even if TestPyPI failed**

This is the exact bug your plan's "Safety Gate" claims to fix — but the fix isn't mentioned.

### What to Add to the Plan

```markdown
### Critical: Make TestPyPI a REAL gate

Current `publish_test` job has `continue-on-error: true`, making the gate
a no-op. TestPyPI failures don't block production PyPI.

Fix: Delete the `continue-on-error: true` line from `publish_test` job
in release.yml.

\`\`\`diff
  publish_test:
      name: Publish to TestPyPI
      needs: [build_wheels, build_sdist]
      runs-on: ubuntu-latest
      timeout-minutes: 10
-     continue-on-error: true
      environment: testpypi
\`\`\`
```

---

## Missing Item 4: Post-Publish PyPI Verification Job

### What's Missing

Your plan has no **post-publish verification** — the most valuable addition I recommended for Phase 1.

### What It Does

After `publish_pypi` succeeds, a new job `verify_pypi`:
1. Waits 60s for PyPI to propagate
2. On 3 OSes (Ubuntu, Windows, macOS), in a clean environment:
   - `pip install zedda==<version>` (from real PyPI, not local)
   - `python -c "import zedda; print(zedda.__version__)"`
   - `zedda --help`
   - `zd.scan("test.csv")` (creates a test CSV and scans it)
3. If ANY step fails → opens a critical GitHub issue automatically

### Why This Is Critical

This catches the **worst-case scenario**: a broken package ships to PyPI. Without this, you only find out when users report "pip install zedda is broken" — by then, 1000+ users may have hit the bug.

**Real-world example:** This would have caught the `venv_*` sdist bloat bug instantly. It would have caught the pyarrow `<20` ceiling bug. It catches what humans miss.

### What to Add to the Plan

Add to `release.yml` after `publish_pypi`:

```yaml
  # ── CRITICAL: Post-Publish Verification ────────────────────
  verify_pypi:
    name: Verify PyPI Install
    needs: [publish_pypi]
    runs-on: ${{ matrix.os }}
    timeout-minutes: 10
    strategy:
      fail-fast: false
      matrix:
        os: [ubuntu-latest, windows-latest, macos-latest]
        python-version: ["3.13"]

    steps:
      - name: Harden Runner
        uses: step-security/harden-runner@bf7454d06d71f1098171f2acdf0cd4708d7b5920 # v2
        with:
          egress-policy: audit

      - uses: actions/setup-python@a26af69be951a213d495a4c3e4e4022e16d87065 # v5.6.0
        with:
          python-version: ${{ matrix.python-version }}

      - name: Wait for PyPI propagation
        run: sleep 60

      - name: Install from PyPI
        run: |
          python -m pip install --upgrade pip
          pip install zedda==${{ github.ref_name }}

      - name: Verify import
        run: python -c "import zedda; print(f'zedda {zedda.__version__} from PyPI')"

      - name: Verify CLI
        run: zedda --help

      - name: Verify scan works
        run: |
          python -c "
          import pandas as pd
          df = pd.DataFrame({'a':[1,2,3], 'b':['x','y','z']})
          df.to_csv('test.csv', index=False)
          import zedda as zd
          p = zd.scan('test.csv')
          print(f'Scan OK: {p.num_rows} rows, {p.num_cols} cols')
          "

      - name: Notify on failure
        if: failure()
        uses: actions/github-script@60a0d83039c74a4aee543508d2ffcb082ae3997d # v7.0.1
        with:
          script: |
            github.rest.issues.create({
              owner: context.repo.owner,
              repo: context.repo.repo,
              title: `🚨 PyPI release ${{ github.ref_name }} verification FAILED`,
              body: `Post-publish verification failed.

              **The published package may be broken on PyPI.**

              Action required:
              1. Check logs: ${{ github.server_url }}/${{ github.repository }}/actions/runs/${{ github.run_id }}
              2. If broken, yank the release immediately
              3. Fix and cut a patch release

              Matrix OS: ${{ matrix.os }}
              Python: ${{ matrix.python-version }}`,
              labels: ['security', 'bug', 'priority:critical']
            });
```

---

## Missing Item 5: Docker Workflow + Composite Action

### What's Missing

Your plan doesn't mention:
1. **`docker.yml`** — Zedda already publishes Docker images to GHCR + Docker Hub. This workflow must be preserved.
2. **`.github/actions/setup-zedda/action.yml`** — composite action that deduplicates checkout + Python setup + build deps across all workflows.

### Why These Matter

**Docker workflow:**
- Zedda has a `Dockerfile` and `docker_publish.yml` already
- Users pull `ghcr.io/zedda-labs/zedda:latest` and `docker.io/zeddalabs/zedda:latest`
- Deleting this workflow breaks Docker distribution with no warning

**Composite action:**
- Every workflow currently repeats: checkout → setup-python → install build deps (5+ lines each)
- A composite action collapses this to 1 line: `- uses: ./.github/actions/setup-zedda`
- Easier to maintain (change once, all workflows benefit)
- Industry standard (pandas, NumPy, pyarrow all use composite actions)

### What to Add to the Plan

```markdown
### Additional Workflows

#### docker.yml (preserve existing Docker publishing)
- Triggers on tag push (multi-arch: amd64 + arm64)
- Pipeline: build amd64 → smoke test → Trivy scan → push multi-arch → arm64 smoke test
- Publishes to GHCR (via GITHUB_TOKEN) + Docker Hub (via PAT)

#### .github/actions/setup-zedda/action.yml (composite action)
- Inputs: python-version, install-dev-deps
- Steps: Harden Runner → checkout (with submodules) → setup-python (with cache) → install build tools
- Used by: _reusable-tests.yml, _reusable-quality.yml, _reusable-build.yml, release.yml
```

**Full code for both is in `ZEDDA_CICD_COMPLETE_A_TO_Z.md`.**

---

## Missing Item 6: Correct Execution Order

### What's Missing

Your plan says:
> 1. **Clean Slate:** Delete the 10 chaotic files currently sitting in `.github/workflows/`.
> 2. **Phase 1 Implementation:** Create the streamlined `ci.yml`...
> 3. **Verify:** Open a test Pull Request.

**This order is dangerous.** If you delete first, there's a window where:
- No PR checks are running
- Anyone who pushes to main has zero CI
- If the new files have bugs, you're debugging in the dark

### Correct Execution Order

```
Step 1: Create new workflow files (don't touch old ones yet)
   ↓
Step 2: Open a PR that ADDS the new files
   ↓ (old files still run alongside new ones — safe)
Step 3: Verify the new files work (4 checks appear on PR)
   ↓
Step 4: Merge the PR (now both old + new files exist)
   ↓
Step 5: Open a SECOND PR that DELETES the old files
   ↓ (clean, easy to revert if something breaks)
Step 6: Merge the deletion PR
   ↓
Step 7: Configure branch protection (require only ci-status)
```

### Why This Order Is Safe

- **Old workflows keep running** until new ones are verified
- **No CI gap** — there's never a moment where zero checks run
- **Easy rollback** — if new workflows have bugs, just revert the PR
- **Separation of concerns** — adding new vs deleting old are separate PRs

### What to Add to the Plan

Replace the "Execution Plan" section with:

```markdown
## Execution Plan (Corrected)

### Step 1: Create new workflow files 
Create these files in a new branch:
- .github/workflows/ci.yml
- .github/workflows/_reusable-tests.yml
- .github/workflows/_reusable-quality.yml
- .github/workflows/_reusable-build.yml
- .github/workflows/release.yml (with verify_pypi job)
- .github/workflows/docker.yml
- .github/workflows/nightly.yml
- .github/workflows/maintenance.yml
- .github/actions/setup-zedda/action.yml
- .github/codeql-config.yml

DO NOT delete old files yet.

### Step 2: Open PR adding new files (15 min)
Open PR from feature branch to main.
- Old workflows still run (safe)
- New workflows also run on this PR
- Verify only 4 checks appear from the new ci.yml
- Verify matrix jobs run inside each check

### Step 3: Merge the PR (5 min)
After Prince reviews and approves.
Now both old + new workflows coexist on main.

### Step 4: Open PR deleting old files (10 min)
Open a SECOND PR that removes:
- .github/workflows/tests.yml
- .github/workflows/build_wheels.yml
- .github/workflows/codeql.yml
- .github/workflows/dependency-review.yml
- .github/workflows/scorecard.yml
- .github/workflows/sanitizers.yml
- .github/workflows/fuzz.yml
- .github/workflows/docker_publish.yml
- .github/workflows/stale.yml
- .github/workflows/release-drafter.yml

### Step 5: Merge deletion PR (5 min)
Clean removal, easy to revert if something breaks.

### Step 6: Configure branch protection (10 min)
Settings → Branches → main → Edit:
- Require status checks: ONLY "CI" (the ci-status consolidation job)
- Require approvals: 1
- Require review from Code Owners
- DO NOT allow admin bypass

### Step 7: Configure GitHub security features (10 min)
Settings → Code security and analysis:
- Enable Dependency graph
- Enable Dependabot alerts
- Enable Code scanning (CodeQL)
- Enable Secret scanning
- Enable Secret scanning push protection

### Step 8: Create environments (5 min)
Settings → Environments:
- Create "testpypi" (no required reviewers)
- Create "pypi-production" (add Tirth + Prince as required reviewers)

### Step 9: Tag v0.4.6 (5 min + 60 min wait)
git tag v0.4.6 && git push origin v0.4.6
Monitor release.yml workflow.
Approve pypi-production environment when prompted.
Verify verify_pypi job passes on all 3 OSes.
```

---

## Missing Item 7: Acknowledge PR #43's Progress

### What's Missing

Your plan says "10 chaotic files" as if nothing has been fixed. But PR #43 (already merged) accomplished:

| Fix | Status |
|---|---|
| cp314 added to build matrix | ✅ Done |
| ARM64 Linux wheels (aarch64) | ✅ Done |
| ARM64 Windows wheels | ✅ Done |
| musllinux ARM64 wheels | ✅ Done |
| pyarrow made optional `[parquet]` extra | ✅ Done |
| `requires-python = ">=3.9,<3.15"` | ✅ Done |
| Upper bounds on openai/pandas/numpy/polars | ✅ Done |
| `venv_*/` excluded from sdist | ✅ Done |
| `conda-recipe/meta.yaml` scaffold | ✅ Done |
| Python 3.14 classifier | ✅ Done |
| Python 3.14 in test matrix | ✅ Done |
| SECURITY.md, CONTRIBUTING.md, CODE_OF_CONDUCT.md | ✅ Done |

### Why This Matters

The new CI/CD workflows must **preserve these configurations**, not undo them. Specifically:

- `build_wheels.yml` matrix must include `cp314` and ARM64 archs
- `pyproject.toml` must keep pyarrow as optional `[parquet]` extra
- `requires-python` must keep `<3.15` upper bound
- sdist.exclude must keep `venv_*/`

### What to Add to the Plan

```markdown
## PR #43 Acknowledgment

The new CI/CD workflows MUST preserve the following configurations
that PR #43 already implemented:

### build_wheels.yml / release.yml must include:
- cibw_python: ["cp39", "cp310", "cp311", "cp312", "cp313", "cp314"]  ← cp314 added by PR #43
- CIBW_ARCHS_LINUX: "x86_64 aarch64"  ← ARM64 added by PR #43
- CIBW_ARCHS_WINDOWS: "AMD64 ARM64"  ← ARM64 added by PR #43
- CIBW_MUSLLINUX_X86_64_IMAGE: musllinux_1_2  ← added by PR #43
- CIBW_MUSLLINUX_AARCH64_IMAGE: musllinux_1_2  ← added by PR #43
- CIBW_MANYLINUX_X86_64_IMAGE: manylinux_2_28  ← UPGRADE from deprecated manylinux2014

### pyproject.toml must keep:
- requires-python = ">=3.9,<3.15"  ← added by PR #43
- dependencies = ["rich>=13.0,<20", "typer>=0.12,<2.0"]  ← pyarrow NOT in core (PR #43)
- [project.optional-dependencies] parquet = ["pyarrow>=14.0.1,<27"]  ← PR #43
- sdist.exclude includes "venv_*/", ".venv/"  ← PR #43
```

---

## Missing Item 8: Branch Protection Setup

### What's Missing

Your plan mentions the `ci-status` consolidation job but doesn't explain the **manual GitHub settings** required to make it work.

### Why This Matters

The consolidation pattern only works if branch protection is configured to require `ci-status` (not the individual matrix jobs). Without this setup, the consolidation is cosmetic — PRs can merge even if tests fail.

### What to Add to the Plan

```markdown
## Branch Protection Setup (Manual — GitHub Settings)

Go to: Settings → Branches → main → Edit rule

Required settings:
- ✅ Require a pull request before merging
  - ✅ Require approvals: 1
  - ✅ Require review from Code Owners
  - ✅ Dismiss stale pull request approvals when new commits are pushed
- ✅ Require status checks to pass before merging
  - ✅ Require branches to be up to date before merging
  - Required status checks: "CI" (ONLY this — the consolidation job)
- ✅ Require conversation resolution before merging
- ✅ Require linear history
- ✅ Do not allow bypassing the above settings

Settings to KEEP OFF:
- ❌ Allow administrators to bypass (admins must follow same rules)
- ❌ Allow force pushes
- ❌ Allow deletions
```

---

## Missing Item 9: mypy Caveat

### What's Missing

Your plan lists mypy as a quality check without mentioning it's currently advisory-only.

### Current State

`tests.yml` line 213:
```yaml
- name: Run mypy
  run: mypy python/zedda/ --ignore-missing-imports
  continue-on-error: true  # TODO: make blocking once mypy baseline established
```

There are 16 pre-existing type errors that prevent mypy from being blocking.

### What to Add to the Plan

```markdown
### mypy Status

mypy is currently advisory-only (continue-on-error: true) because of
16 pre-existing type errors. Keep it advisory in the new _reusable-quality.yml.

TODO: Fix the 16 errors (mostly `def f(x: int = None)` → `def f(x: int | None = None)`)
Then remove continue-on-error to make mypy a real blocking gate.
```

---

## Summary: What Your Plan Is Missing

| # | Missing Item | Severity | Fix Time |
|---|---|---|---|
| 1 | 7 critical library bugs not mentioned | 🔴 Critical | 1 hour |
| 2 | `pypa/gh-action-pypi-publish` SHA-pinning | 🔴 Critical | 5 min |
| 3 | Remove `continue-on-error: true` from TestPyPI | 🔴 Critical | 1 min |
| 4 | Post-publish `verify_pypi` job | 🔴 Critical | 30 min |
| 5 | `docker.yml` + composite action | 🟠 High | 45 min |
| 6 | Correct execution order (build-first, delete-second) | 🔴 Critical | 0 min (just reorder) |
| 7 | Acknowledge PR #43's progress | 🟡 Medium | 5 min (documentation) |
| 8 | Branch protection setup steps | 🟠 High | 10 min (manual) |
| 9 | mypy advisory-only caveat | 🟡 Low | 1 min (documentation) |

**Total missing: ~2.5 hours of work + critical execution order fix**

---

## Corrected Plan Summary

### Step 0: Fix 7 Library Bugs (1 hour) ← NEW
- pyproject.toml: `openai` → `requests` in `[ai]` extra
- cli.py: `OPENAI_API_KEY` → `ZEDDA_AI_KEY` (3 locations)
- cli.py: Remove "Excel, JSON" from help
- ai_insights.py: Replace stub with real implementation

### Step 1: Create New Workflow Files (2 hours) ← EXPANDED
- `ci.yml` (umbrella)
- `_reusable-tests.yml`, `_reusable-quality.yml`, `_reusable-build.yml`
- `release.yml` **with SHA-pinned publish + verify_pypi job** ← NEW
- `docker.yml` ← NEW
- `nightly.yml`, `maintenance.yml`
- `setup-zedda/action.yml` (composite) ← NEW
- `codeql-config.yml`
- **Preserve PR #43's configs** (cp314, ARM64, pyarrow-optional) ← NEW

### Step 2: Open PR Adding New Files (15 min) ← REORDERED
- Old workflows still run (safe)
- Verify 4 checks appear
- Merge

### Step 3: Open PR Deleting Old Files (10 min) ← REORDERED
- Clean removal
- Easy to revert
- Merge

### Step 4: Configure Branch Protection (10 min) ← NEW
- Require only `CI` check
- No admin bypass

### Step 5: Configure GitHub Security Features (10 min) ← NEW
- Dependency graph, Dependabot, CodeQL, Secret scanning

### Step 6: Create Environments (5 min) ← NEW
- `testpypi` (no reviewers)
- `pypi-production` (Tirth + Prince required)

### Step 7: Tag v0.4.6 (5 min + 60 min wait)
- Monitor release.yml
- Approve PyPI publish
- **Verify `verify_pypi` job passes on 3 OSes** ← NEW

---

## Final Verdict

| Question | Answer |
|---|---|
| Is the architecture correct? | ✅ Yes — umbrella + reusable + consolidation is right |
| Is the plan complete? | ❌ No — 5 critical items missing |
| Is the execution order safe? | ❌ No — delete-first is dangerous |
| Should you implement now? | 🟡 Only after adding the 9 missing items above |
| Where is the complete correct plan? | `ZEDDA_CICD_COMPLETE_A_TO_Z.md` has full YAML with all fixes |

**Update your `implementation_plan.md` with these 9 additions, then execute.** The architecture is sound — it just needs these critical gaps filled before implementation.
