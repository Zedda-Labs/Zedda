# Contributing to Zedda

Thank you for your interest in contributing to Zedda! 🎉

We welcome all forms of contribution — from fixing a typo in docs to implementing a new algorithm in C++. Every contribution matters.

## Table of Contents

- [Code of Conduct](#code-of-conduct)
- [How to Report Issues](#how-to-report-issues)
- [Development Setup](#development-setup)
- [Project Structure](#project-structure)
- [Making Changes](#making-changes)
- [Running Tests](#running-tests)
- [Submitting a Pull Request](#submitting-a-pull-request)
- [Coding Standards](#coding-standards)
- [Where to Get Help](#where-to-get-help)

---

## Code of Conduct

By participating in this project, you agree to abide by our [Code of Conduct](CODE_OF_CONDUCT.md). Please read it before contributing.

---

## How to Report Issues

- **Bug reports**: Use the [Bug Report template](.github/ISSUE_TEMPLATE/bug_report.md).
- **Feature requests**: Use the [Feature Request template](.github/ISSUE_TEMPLATE/feature_request.md).
- **Security vulnerabilities**: **Do NOT open a public issue.** See [SECURITY.md](SECURITY.md) for responsible disclosure instructions.

---

## Development Setup

### Prerequisites

| Tool | Minimum Version | Notes |
| :--- | :--- | :--- |
| Python | 3.9+ | Required |
| C++ Compiler | C++17 support | GCC 9+, Clang 10+, or MSVC 2019+ |
| CMake | 3.21+ | For building the C++ core |
| Git | Any | For cloning with submodules |

### Step-by-Step Setup

**1. Fork and clone the repository**

```bash
git clone https://github.com/<your-username>/Zedda.git --recursive
cd Zedda
```

> The `--recursive` flag is required to pull in `nanobind` and `arrow` as git submodules.

**2. Create a virtual environment (recommended)**

```bash
python -m venv .venv

# Activate it
# On Windows:
.venv\Scripts\activate
# On macOS/Linux:
source .venv/bin/activate
```

**3. Install in editable/development mode**

This compiles the C++ core and installs the Python package:

```bash
pip install -e ".[dev]"
```

> If you only want to change Python code (not the C++ core), this step builds the native extension once and subsequent Python changes are reflected immediately.

**4. Verify your setup**

```python
import zedda as zd
zd.profile("tests/data/titanic.csv")
```

---

## Project Structure

```
Zedda/
├── src/                     # C++ source files
│   └── core/
│       ├── arrow_profiler.cpp   # Parquet/Arrow scanning via Arrow C Data Interface
│       ├── csv_profiler.cpp     # CSV streaming engine
│       └── correlation_engine.cpp # Pearson correlation (single-pass)
├── include/
│   └── zedda/               # C++ header files
├── python/
│   └── zedda/               # Python package
│       ├── __init__.py          # Public API: scan, profile, compare, fix, ml_ready
│       ├── cli.py               # CLI (Typer app: `zedda run`, `zedda compare`)
│       ├── report.py            # HTML report utilities (XSS-safe templates)
│       └── ai_insights.py       # OpenAI integration (optional)
├── tests/                   # Python tests (pytest)
├── docs/                    # Documentation and assets
├── extern/                  # Git submodules (nanobind, etc.)
├── CMakeLists.txt           # C++ build configuration
└── pyproject.toml           # Python project metadata (scikit-build-core)
```

---

## Making Changes

### Python-only changes

For changes to `python/zedda/*.py`, you don't need to rebuild the C++ extension. Just edit the files and your changes are live.

### C++ changes

After editing any file in `src/` or `include/`, you need to recompile:

```bash
pip install -e ".[dev]"
```

Or if you have CMake set up directly:

```bash
cmake -B build -DCMAKE_BUILD_TYPE=Release
cmake --build build --parallel
```

---

## Running Tests

```bash
# Run the full test suite
pytest tests/

# Run a specific test file
pytest tests/test_profile.py -v

# Run with coverage
pytest tests/ --cov=zedda --cov-report=term-missing
```

All tests must pass before submitting a PR.

---

## Submitting a Pull Request

1. **Create a feature branch** from `main`:
   ```bash
   git checkout -b feat/your-feature-name
   ```

2. **Make your changes**, following the [Coding Standards](#coding-standards) below.

3. **Add or update tests** for any changed behavior.

4. **Ensure all tests pass**:
   ```bash
   pytest tests/
   ```

5. **Commit with a clear message**:
   ```bash
   git commit -m "feat: add HLL cardinality estimation for string columns"
   ```
   We follow [Conventional Commits](https://www.conventionalcommits.org/) (`feat:`, `fix:`, `docs:`, `test:`, `refactor:`).

6. **Push your branch** and open a Pull Request against `main`.

7. **Fill in the PR template** — describe what you changed and why.

---

## Coding Standards

### Python

- Follow [PEP 8](https://pep8.org/).
- Add type hints to all new public functions.
- Write Google-style or NumPy-style docstrings for all public functions.
- Avoid adding new heavy dependencies without discussion.

### C++

- Use C++17 features; target compatibility with GCC 9+, Clang 10+, and MSVC 2019+.
- Prefer `const` references and `std::string_view` over copies.
- Write memory-safe code — no raw `new`/`delete` (use `std::unique_ptr`).
- Document non-obvious algorithms with inline comments referencing the source paper.

### Security

- **Never** interpolate raw user data (e.g., column names from CSV files) into HTML, SQL, or generated code without proper escaping. See the patterns in `python/zedda/report.py`.
- Always use `repr()` when embedding column names in generated Python code (see `_safe_col_name()` in `__init__.py`).

---

## Where to Get Help

- **GitHub Discussions** — for questions, ideas, and general discussion.
- **GitHub Issues** — for confirmed bugs and feature requests.
- **Pull Request comments** — for review feedback on specific changes.

We aim to respond to all issues and PRs within **3 business days**.

---

Thank you for helping make Zedda better! ⚡
