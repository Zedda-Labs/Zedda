"""
Comprehensive test for zd.ask() patterns.
Uses mock profile objects so the C++ core is NOT required.
"""

import sys

sys.path.insert(0, "python")


# ── Mock objects ──────────────────────────────────────────────────
class MockCol:
    def __init__(
        self,
        name,
        type_str,
        null_pct,
        null_count,
        unique_approx,
        unique_pct=0.0,
        mean=0.0,
        stddev=0.0,
        val_min=0.0,
        val_max=0.0,
        skewness=0.0,
        is_constant=False,
        has_high_nulls=False,
        is_high_cardinality=False,
    ):
        self.name = name
        self.type_str = type_str
        self.null_pct = null_pct
        self.null_count = null_count
        self.unique_approx = unique_approx
        self.unique_pct = unique_pct
        self.mean = mean
        self.stddev = stddev
        self.val_min = val_min
        self.val_max = val_max
        self.skewness = skewness
        self.is_constant = is_constant
        self.has_high_nulls = has_high_nulls
        self.is_high_cardinality = is_high_cardinality


class MockCorr:
    def __init__(self, col_a, col_b, r, direction="negative", strength="STRONG"):
        self.col_a = col_a
        self.col_b = col_b
        self.r = r
        self.direction = direction
        self.strength = strength


class MockProfile:
    file_name = "titanic_test.csv"
    file_path = "tests/titanic_test.csv"
    num_rows = 1000
    num_cols = 7
    num_numeric = 4
    num_string = 3
    overall_null_pct = 8.5
    total_null_cells = 595
    total_cells = 7000
    scan_time_ms = 42.3
    is_sampled = False
    columns = [
        MockCol(
            "PassengerId",
            "int",
            0.0,
            0,
            1000,
            unique_pct=100.0,
            mean=500.0,
            val_min=0,
            val_max=999,
        ),
        MockCol("Name", "str", 0.0, 0, 1000, unique_pct=100.0),
        MockCol(
            "Pclass", "int", 0.0, 0, 3, unique_pct=0.3, mean=2.1, val_min=1, val_max=3
        ),
        MockCol(
            "Survived", "int", 0.0, 0, 2, unique_pct=0.2, mean=0.5, val_min=0, val_max=1
        ),
        MockCol(
            "Age",
            "float",
            6.5,
            65,
            74,
            unique_pct=7.4,
            mean=29.6,
            val_min=1,
            val_max=80,
            skewness=0.4,
        ),
        MockCol(
            "Fare",
            "float",
            0.0,
            0,
            300,
            unique_pct=30.0,
            mean=35.0,
            val_min=5,
            val_max=5000,
            skewness=3.8,
        ),
        MockCol("Cabin", "str", 75.0, 750, 100, unique_pct=75.0, has_high_nulls=True),
    ]
    correlations = [MockCorr("Pclass", "Fare", -0.83, "negative", "STRONG")]


p = MockProfile()

from zedda import (
    _ask_pattern_a,
    _ask_pattern_b,
    _ask_pattern_d,
    _ask_sanitize_question,
    _ask_validate_path,
)

PASS = 0
FAIL = 0


def check(name, result, expect_none=False, must_contain=None):
    global PASS, FAIL
    if expect_none:
        if result is not None:
            print(f"  FAIL [{name}]: expected None, got: {str(result)[:80]}")
            FAIL += 1
        else:
            print(f"  PASS [{name}]")
            PASS += 1
        return
    if result is None:
        print(f"  FAIL [{name}]: got None (expected a result)")
        FAIL += 1
        return
    if must_contain:
        ans = result[0].lower() if isinstance(result, tuple) else str(result).lower()
        for kw in must_contain:
            if kw.lower() not in ans:
                print(f'  FAIL [{name}]: answer missing "{kw}" in: {ans[:160]}')
                FAIL += 1
                return
    print(f"  PASS [{name}]")
    PASS += 1


# ══════════════════════════════════════════════════════════════════
print("\n=== PATTERN A: Null threshold ===")
# ══════════════════════════════════════════════════════════════════
check(
    "A1: >5% nulls finds Age + Cabin",
    _ask_pattern_a(p, "which columns have more than 5% nulls?", "x.csv"),
    must_contain=["cabin", "age"],
)

check(
    "A2: >80% nulls finds nothing",
    _ask_pattern_a(p, "columns with more than 80% nulls?", "x.csv"),
    must_contain=["no columns"],
)

check(
    "A3: no % sign → None (falls through)",
    _ask_pattern_a(p, "how many rows are there?", "x.csv"),
    expect_none=True,
)

check(
    "A4: no null/missing keyword → None",
    _ask_pattern_a(p, "what is the mean of Age?", "x.csv"),
    expect_none=True,
)

# ══════════════════════════════════════════════════════════════════
print("\n=== PATTERN B: Domain suitability ===")
# ══════════════════════════════════════════════════════════════════
check(
    "B1: fraud → No (no fraud col, no amount, no timestamp)",
    _ask_pattern_b(p, "is this dataset good for fraud detection?"),
    must_contain=["no"],
)

check(
    "B2: classification → Yes (has binary Survived col)",
    _ask_pattern_b(p, "is this suitable for classification?"),
    must_contain=["yes", "survived"],
)

check(
    "B3: churn → No (no churn col)",
    _ask_pattern_b(p, "is this good for churn prediction?"),
    must_contain=["no"],
)

check(
    "B4: no intent phrase → None",
    _ask_pattern_b(p, "how many rows are there?"),
    expect_none=True,
)

check(
    "B5: unknown domain → None (falls to LLM)",
    _ask_pattern_b(p, "is this good for quantum computing?"),
    expect_none=True,
)

# ══════════════════════════════════════════════════════════════════
print("\n=== PATTERN D: General profile lookups ===")
# ══════════════════════════════════════════════════════════════════
check(
    "D01: row count",
    _ask_pattern_d(p, "how many rows are there?"),
    must_contain=["1,000"],
)

check(
    "D02: column count",
    _ask_pattern_d(p, "how many columns does this have?"),
    must_contain=["7"],
)

check(
    "D03: quality score",
    _ask_pattern_d(p, "what is the data quality score?"),
    must_contain=["score"],
)

check(
    "D04: outliers (Fare max=5000, mean=35 → 142x)",
    _ask_pattern_d(p, "which columns have outliers?"),
    must_contain=["fare"],
)

check(
    "D05: binary col (Survived 0/1)",
    _ask_pattern_d(p, "binary columns?"),
    must_contain=["survived"],
)

check(
    "D06: id column (PassengerId 100% unique)",
    _ask_pattern_d(p, "which are the id columns?"),
    must_contain=["passengerid"],
)

check(
    "D07: correlated columns",
    _ask_pattern_d(p, "are there correlated columns?"),
    must_contain=["pclass", "fare"],
)

check("D08: mean of Age", _ask_pattern_d(p, "mean of Age"), must_contain=["29.6"])

check(
    "D09: null rate of Cabin",
    _ask_pattern_d(p, "null rate of Cabin"),
    must_contain=["75.0"],
)

check(
    "D10: type of Survived", _ask_pattern_d(p, "type of Survived"), must_contain=["int"]
)

check("D11: min of Fare", _ask_pattern_d(p, "minimum of Fare"), must_contain=["5"])

check("D12: max of Fare", _ask_pattern_d(p, "maximum of Fare"), must_contain=["5000"])

check(
    "D13: drop suggestions (PassengerId ID + Cabin 75% null)",
    _ask_pattern_d(p, "what should I drop?"),
    must_contain=["passengerid", "cabin"],
)

check(
    "D14: skewed columns (Fare skewness=3.8 > 2.0 for 1000 rows)",
    _ask_pattern_d(p, "skewed columns"),
    must_contain=["fare"],
)

check(
    "D15: scan time",
    _ask_pattern_d(p, "how long did the scan take?"),
    must_contain=["ms"],
)

check(
    "D16: most null column",
    _ask_pattern_d(p, "most null column?"),
    must_contain=["cabin"],
)

check(
    "D17: nulls/missing list",
    _ask_pattern_d(p, "which columns have missing values?"),
    must_contain=["cabin", "age"],
)

check(
    "D18: string/categorical columns",
    _ask_pattern_d(p, "text columns"),
    must_contain=["name", "cabin"],
)

check(
    "D19: numeric columns",
    _ask_pattern_d(p, "numeric columns"),
    must_contain=["fare", "age"],
)

check(
    "D20: high cardinality",
    _ask_pattern_d(p, "high cardinality columns"),
    must_contain=["passengerid"],
)

check(
    "D21: single-col not found returns helpful message",
    _ask_pattern_d(p, "mean of XYZ_nonexistent"),
    must_contain=["not found", "available"],
)

check(
    "D22: unrecognized question → None",
    _ask_pattern_d(p, "tell me a joke"),
    expect_none=True,
)

# ══════════════════════════════════════════════════════════════════
print("\n=== SECURITY: question sanitization ===")
# ══════════════════════════════════════════════════════════════════
q = _ask_sanitize_question("which columns have more than 10% nulls?")
assert "10%" in q
print(f"  PASS [SEC1: normal question preserved]: {q!r}")
PASS += 1

q = _ask_sanitize_question("\x00\x1f<>{}`test\x7f")
assert "\x00" not in q and "<" not in q and "{" not in q and "`" not in q
print(f"  PASS [SEC2: control/injection chars stripped]: {q!r}")
PASS += 1

q = _ask_sanitize_question('"""inject"""')
assert '"""' not in q
print(f"  PASS [SEC3: triple-quote stripped]: {q!r}")
PASS += 1

q = _ask_sanitize_question("a" * 600)
assert len(q) <= 500
print(f"  PASS [SEC4: 600-char truncated to <=500]: len={len(q)}")
PASS += 1

try:
    _ask_sanitize_question("")
    print("  FAIL [SEC5: empty should raise ValueError]")
    FAIL += 1
except ValueError as e:
    print(f"  PASS [SEC5: empty question raises ValueError]: {e}")
    PASS += 1

try:
    _ask_sanitize_question("   ")
    print("  FAIL [SEC6: whitespace-only should raise ValueError]")
    FAIL += 1
except ValueError as e:
    print(f"  PASS [SEC6: whitespace-only raises ValueError]: {e}")
    PASS += 1

# ══════════════════════════════════════════════════════════════════
print("\n=== SECURITY: path validation ===")
# ══════════════════════════════════════════════════════════════════
try:
    _ask_validate_path("nonexistent_file_xyz.csv")
    print("  FAIL [SEC7: missing file should raise FileNotFoundError]")
    FAIL += 1
except FileNotFoundError:
    print("  PASS [SEC7: missing file raises FileNotFoundError]")
    PASS += 1

try:
    _ask_validate_path(".")  # directory
    print("  FAIL [SEC8: directory should raise ValueError]")
    FAIL += 1
except ValueError as e:
    print(f"  PASS [SEC8: directory raises ValueError]: {e}")
    PASS += 1

try:
    _ask_validate_path("python/zedda/__init__.py")  # .py not in allowlist
    print("  FAIL [SEC9: .py extension should raise ValueError]")
    FAIL += 1
except ValueError as e:
    print(f"  PASS [SEC9: .py extension raises ValueError]: {e}")
    PASS += 1

# ══════════════════════════════════════════════════════════════════
print("\n=== BRANDING: no Groq in user-facing output ===")
# ══════════════════════════════════════════════════════════════════
src = open("python/zedda/__init__.py", encoding="utf-8").read()
# Find any console.print or _console.print lines that contain "groq" (case insensitive)
# excluding comment lines and the URL
bad_lines = []
for i, line in enumerate(src.split("\n"), 1):
    stripped = line.strip()
    if "groq" in stripped.lower() and "groq" in stripped.lower():
        # skip comments, the URL, the internal pricing dict key in header, and variable names
        if stripped.startswith("#"):
            continue
        if "api.groq.com" in stripped:
            continue
        if (
            "_AI_PRICING" in stripped
            or "_AI_DEFAULT_MODEL" in stripped
            or "_ask_zedda_ai" in stripped
        ):
            continue
        if "print" in stripped.lower() and "groq" in stripped.lower():
            bad_lines.append((i, stripped))
if bad_lines:
    print(f'  WARN: "Groq" found in {len(bad_lines)} print lines: {bad_lines[:3]}')
else:
    print("  PASS [BRAND: no Groq in any console.print() output]")
    PASS += 1

# ══════════════════════════════════════════════════════════════════
print(f"\n{'=' * 60}")
print(f"RESULTS: {PASS} PASSED  |  {FAIL} FAILED")
print(f"{'=' * 60}\n")
if FAIL > 0:
    sys.exit(1)
