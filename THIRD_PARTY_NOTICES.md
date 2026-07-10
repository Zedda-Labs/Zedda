# Third-Party Notices

Zedda relies on the following excellent open-source libraries:

## fast_float
- **Version:** v8.0.0
- **License:** Apache 2.0 / MIT
- **URL:** https://github.com/fastfloat/fast_float
- **Modifications:** None. Included directly in `include/zedda/fast_float/`.

## nanobind
- **Version / Commit:** 2deac96697d1b304f3c973cef7de5f94cbad5a57
- **License:** BSD-3-Clause
- **URL:** https://github.com/wjakob/nanobind

## BS::thread_pool
- **Version / Commit:** bd4533f1f70c2b975cbd5769a60d8eaaea1d2233
- **License:** MIT
- **URL:** https://github.com/bshoshany/thread-pool

## PyArrow
- **License:** Apache 2.0
- **URL:** https://github.com/apache/arrow
- **Usage:** Optional runtime dependency for Parquet/Arrow file profiling.

## Rich
- **License:** MIT
- **URL:** https://github.com/Textualize/rich
- **Usage:** Runtime dependency for terminal UI rendering.

## Typer
- **License:** MIT
- **URL:** https://github.com/fastapi/typer
- **Usage:** Runtime dependency for the CLI (`zedda` command).
