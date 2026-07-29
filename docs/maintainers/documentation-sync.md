# Documentation Synchronization Architecture

This document provides a comprehensive overview of the automated documentation synchronization system between **Zedda** (the main C++ engine & Python project repository) and **zedda-docs** (the static documentation website repository).

---

## 1. Documentation Synchronization Overview

### Single Source of Truth
The **`Zedda`** main repository (`Zedda-Labs/Zedda`) is the **single source of truth** for all project documentation. All user guides, API specifications, architecture documents, changelogs, installation guides, and visual assets are authored and version-controlled inside `Zedda`.

### Repository Separation Rationale
- **Main Repository (`Zedda-Labs/Zedda`)**: Focuses exclusively on source code, C++ engine algorithms, Python bindings, unit test suites, performance benchmarks, and raw documentation source files (`docs/**`, `README.md`, `CHANGELOG.md`, `examples/**`).
- **Docs Repository (`Zedda-Labs/Zedda-Documentation`)**: Acts purely as a **documentation renderer**, static site compiler (Node.js site generator), and **GitHub Pages host**.

> [!CAUTION]
> **Maintainer Rule**: Never edit documentation content directly inside the `zedda-docs` repository. Any manual edits made in `zedda-docs` will be overwritten when the automated synchronization workflow runs. All documentation changes must be committed directly to `Zedda`.

---

## 2. Architecture Overview

```
Developer
    │
    ▼
Push documentation changes to main
    │
    ▼
Zedda Repository (Main)
    │
    ▼
.github/workflows/docs-dispatch.yml
    │
    ▼ (POST /repos/Zedda-Labs/Zedda-Documentation/dispatches)
repository_dispatch (event: zedda_docs_updated)
    │
    ▼
zedda-docs Repository (Docs)
    │
    ▼
.github/workflows/docs-ci.yml
    │
    ├── Step 1: Checkout zedda-docs (Builder)
    ├── Step 2: Checkout Zedda at dispatched commit_sha
    ├── Step 3: Copy fresh docs/** into static-src/content/
    ├── Step 4: Run Node site generator (node scripts/build-docs.js)
    └── Step 5: Deploy HTML artifact to GitHub Pages
    │
    ▼
GitHub Pages Website (LIVE)
```

### Stage-by-Stage Breakdown

1. **Commit & Push**: A developer pushes changes to `main` in `Zedda` affecting documentation-relevant files.
2. **Path Filtering & Event Dispatch**: `.github/workflows/docs-dispatch.yml` detects the change, constructs a structured JSON payload (containing `source_repo`, `ref`, `commit_sha`, `triggered_by`, and `trigger_event`), and sends a secure `repository_dispatch` call to GitHub API using `DOCS_TRIGGER_TOKEN`.
3. **Dispatch Reception**: `.github/workflows/docs-ci.yml` in `zedda-docs` receives the `zedda_docs_updated` event type.
4. **Source Checkout & Synchronization**: The `docs-ci.yml` job checks out `zedda-docs`, then checks out `Zedda-Labs/Zedda` at the **exact commit SHA** sent in the dispatch payload into a temporary directory `zedda-source/`. It copies the updated Markdown documentation into `static-src/content/`.
5. **Static Site Build**: Executes `node scripts/build-docs.js` to compile the 49 HTML static pages, search index, and assets into `public/docs/`.
6. **GitHub Pages Deployment**: Deploys the built HTML pages to GitHub Pages via `actions/upload-pages-artifact@v3` and `actions/deploy-pages@v4`.

---

## 3. Trigger Conditions

Documentation synchronization is **path-filtered** to run strictly when content that impacts the website is updated.

### Paths That Trigger Synchronization

| Path Pattern | Description |
| :--- | :--- |
| `docs/**` | User guides, API reference specs, architecture docs, and visual assets. |
| `README.md` | Top-level project landing page and overview. |
| `CHANGELOG.md` | Version release history and change logs. |
| `CONTRIBUTING.md` | Contributor setup and coding standards. |
| `CODE_OF_CONDUCT.md` | Community standards policy. |
| `RELEASING.md` | Maintainer release procedure. |
| `SECURITY.md` | Security vulnerability disclosure policy. |
| `LICENSE` | Open-source software license. |
| `examples/**` | Code examples and Jupyter notebooks. |
| `pyproject.toml` | Package version metadata and doc link references. |

### Excluded Paths
Pure C++ engine code (`src/**`, `include/**`), Python bindings (`python/zedda/**`), unit tests (`tests/**`), performance benchmarks (`benchmarks/**`), and container configs (`Dockerfile`, `CMakeLists.txt`) do **NOT** trigger documentation builds. This prevents unnecessary GitHub Actions runner usage on internal code refactoring.

---

## 4. Workflow Overview

### 1. `docs-dispatch.yml` (`Zedda` Main Repo)
- **Location**: `.github/workflows/docs-dispatch.yml`
- **Responsibility**: Listens for pushes to `main` matching documentation paths. Validates secret `DOCS_TRIGGER_TOKEN`, constructs JSON metadata payload, sends `repository_dispatch` POST request to `Zedda-Labs/Zedda-Documentation`, and verifies HTTP status code 204.
- **Permissions**: `permissions: contents: read` (strict least privilege).

### 2. `docs-ci.yml` (`zedda-docs` Docs Repo)
- **Location**: `.github/workflows/docs-ci.yml`
- **Responsibility**: Handles local pushes, pull requests, releases, and `repository_dispatch` events. Performs multi-repo source checkout, content synchronization, Node.js static site compilation (`node scripts/build-docs.js`), and GitHub Pages deployment.
- **Permissions**: `permissions: contents: read`, `pages: write`, `id-token: write`.

---

## 5. Security Architecture & Secret Management

### `DOCS_TRIGGER_TOKEN`
Cross-repository Actions events (`repository_dispatch`) require authentication to the target repository API.

- **Purpose**: Authenticates the `Zedda` workflow when sending `repository_dispatch` requests to `Zedda-Labs/Zedda-Documentation`.
- **Secret Location**: Stored as a Repository Secret in `Zedda` (`Settings -> Secrets and variables -> Actions -> DOCS_TRIGGER_TOKEN`).
- **Token Type**: **Fine-Grained Personal Access Token (PAT)**.
- **Scope & Least Privilege**:
  - Target Repository: `Zedda-Labs/Zedda-Documentation` **ONLY**.
  - Permissions: `Contents: Read and write` (or `Actions: Read and write`).
- **Security Enforcement**: The workflow passes `DOCS_TRIGGER_TOKEN` strictly via environment variables (`DISPATCH_TOKEN: ${{ secrets.DOCS_TRIGGER_TOKEN }}`) and masks credentials from build logs.

---

## 6. Manual Rebuild Procedure

Maintainers can trigger a manual documentation build and deployment at any time via the GitHub Actions web interface:

### Option A: Triggering from `Zedda` (Main Repo)
1. Navigate to `https://github.com/Zedda-Labs/Zedda/actions`.
2. Select **Dispatch Documentation Update** from the left sidebar.
3. Click **Run workflow** -> Select branch `main` -> Click **Run workflow**.

### Option B: Triggering from `zedda-docs` (Docs Repo)
1. Navigate to `https://github.com/Zedda-Labs/Zedda-Documentation/actions`.
2. Select **Documentation CI/CD & Security Audit** from the left sidebar.
3. Click **Run workflow** -> (Optional) enter a target commit SHA from `Zedda` -> Click **Run workflow**.

---

## 7. Failure Diagnostics & Recovery

| Failure Scenario | Root Cause | Diagnosis & Recovery Step |
| :--- | :--- | :--- |
| `DOCS_TRIGGER_TOKEN` missing or expired | PAT token deleted or expired in repository settings. | Workflow outputs `::error::Secret 'DOCS_TRIGGER_TOKEN' is missing`. Regenerate Fine-Grained PAT for `Zedda-Documentation` and update repository secret in `Zedda`. |
| `repository_dispatch` fails (HTTP 404 / 403) | API permission error or target repo renamed. | Verify target repository name is `Zedda-Labs/Zedda-Documentation` and PAT has `Contents: Read & write` access to the docs repo. |
| Checkout failure in `zedda-docs` | Invalid commit SHA dispatched. | Check `docs-ci.yml` logs. If a bad SHA was passed, trigger a manual `workflow_dispatch` without inputs to build from `main`. |
| `build-docs.js` compilation error | Broken Markdown syntax or invalid `navigation.js` route. | Run `node scripts/build-docs.js` locally in `zedda-docs` to debug parsing or routing syntax errors. |
| GitHub Pages deployment fails | Missing OIDC permissions or Pages environment error. | Verify `permissions: pages: write, id-token: write` is present in `docs-ci.yml` and Pages source is set to `GitHub Actions` in repo settings. |

---

## 8. Repository Structure & Ownership Matrix

| Function / Component | Owned by `Zedda` | Owned by `zedda-docs` |
| :--- | :---: | :---: |
| **Documentation Source Files** (`docs/*`, `README.md`) | ✅ **Source of Truth** | ❌ (Synced dynamically) |
| **Static Site Generator** (`scripts/build-docs.js`) | ❌ | ✅ **Owner** |
| **Design System & CSS** (`static-src/assets/`) | ❌ | ✅ **Owner** |
| **Site Layout Template** (`templates/layout.html`) | ❌ | ✅ **Owner** |
| **GitHub Pages Host & Environment** | ❌ | ✅ **Host** |

---

## 9. Future Maintenance Guidelines

1. **Single Source of Truth**: Always edit and commit documentation inside the main `Zedda` repository. Never edit `.md` content directly in `zedda-docs`.
2. **Keep Generator Logic Decoupled**: Static site compiler logic (`scripts/build-docs.js`) and design system CSS remain inside `zedda-docs`.
3. **Single Deployment Path**: Maintain **exactly ONE** GitHub Pages deployment path (`actions/deploy-pages@v4`) in `docs-ci.yml`. Do not re-introduce legacy third-party deployment actions.
4. **Deterministic Dependencies**: Always use `npm ci` for dependency installation in `zedda-docs`.

---

## 10. Maintainer Troubleshooting Checklist

- [ ] Is `DOCS_TRIGGER_TOKEN` active and non-expired in `Zedda` secrets?
- [ ] Does `DOCS_TRIGGER_TOKEN` have `Contents: Read & write` access to `Zedda-Documentation`?
- [ ] Is the GitHub Pages build source set to **GitHub Actions** in `Zedda-Documentation` -> Settings -> Pages?
- [ ] Did `docs-dispatch.yml` run successfully on the last commit in `Zedda`?
- [ ] Does `node scripts/build-docs.js` execute cleanly with zero errors locally?
