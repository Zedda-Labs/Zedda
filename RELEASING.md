# Releasing Zedda

This document describes the step-by-step process for publishing a new release of Zedda.

## Prerequisites

- You must be a member of `@Zedda-Labs/core` with push access to `main`.
- The `pypi` and `testpypi` GitHub Environments must be configured with OIDC trusted publishing.
- Docker Hub secrets (`DOCKER_USERNAME`, `DOCKER_PASSWORD`) must be set in the repository.

## Release Process

### 1. Prepare the Release

```bash
# Ensure you're on main and up to date
git checkout main
git pull origin main

# Verify all tests pass
pytest tests/

# Update the version in python/zedda/__init__.py
# Example: __version__ = "0.3.0"
```

### 2. Update the Changelog

Edit `CHANGELOG.md`:
- Move items from `[Unreleased]` to a new version header: `## [0.3.0] - YYYY-MM-DD`
- Add a fresh empty `[Unreleased]` section at the top.

### 3. Commit and Tag

```bash
git add python/zedda/__init__.py CHANGELOG.md
git commit -m "release: v0.3.0"

# Create an annotated tag
git tag -a v0.3.0 -m "Release v0.3.0"

# Push both the commit and the tag
git push origin main --follow-tags
```

### 4. Automated Pipeline

Pushing the `v*.*.*` tag triggers the following automated pipeline:

```
Tag push (vX.Y.Z)
    │
    ├── build_wheels.yml
    │   ├── build_wheels (20 matrix jobs: 4 OS × 5 Python versions)
    │   ├── build_sdist
    │   ├── publish_test → TestPyPI
    │   └── publish_pypi → Production PyPI (only if TestPyPI succeeds)
    │
    └── docker_publish.yml
        ├── Build Docker image (amd64)
        ├── Smoke test (import zedda)
        └── Push to GHCR + Docker Hub (amd64 + arm64)
```

### 5. Verify the Release

After the pipeline completes (~15-30 minutes):

```bash
# Verify PyPI
pip install zedda==0.3.0
python -c "import zedda; print(zedda.__version__)"

# Verify Docker
docker pull ghcr.io/zedda-labs/zedda:0.3.0
docker run --rm ghcr.io/zedda-labs/zedda:0.3.0 python -c "import zedda; print(zedda.__version__)"
```

### 6. Create the GitHub Release

The **Release Drafter** workflow automatically maintains a draft release with categorized changes from merged PRs. After verifying the release:

1. Go to [GitHub Releases](https://github.com/Zedda-Labs/Zedda/releases).
2. Find the draft release created by Release Drafter.
3. Edit it: set the tag to `v0.3.0`, review the auto-generated notes.
4. Click **Publish release**.

## Emergency Hotfix Process

For critical security patches (e.g., CVE in `pyarrow`):

1. Branch from the latest tag: `git checkout -b hotfix/v0.2.1 v0.2.0`
2. Apply the minimal fix.
3. Bump version to `0.2.1`.
4. Tag and push: `git tag -a v0.2.1 -m "Security hotfix"`.
5. The same automated pipeline runs.
6. Cherry-pick the fix back to `main`.

## Version Numbering

Zedda follows [Semantic Versioning](https://semver.org/):

| Change Type | Version Bump | Example |
|:---|:---|:---|
| Breaking API change | Major (`X.0.0`) | Removing `zd.scan()` |
| New feature (backward-compatible) | Minor (`0.X.0`) | Adding `zd.compare()` |
| Bug fix / security patch | Patch (`0.0.X`) | Fixing CVE in pyarrow pin |
