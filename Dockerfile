# ──────────────────────────────────────────────────────────────────────────────
# Multi-stage Dockerfile for Zedda
#
# Stage 1 (builder): Compiles the C++ extension from source
# Stage 2 (runtime): Slim image with only the installed wheel
#
# This reduces the final image from ~1.5 GB to ~200 MB by excluding
# compilers, headers, and build artifacts from the production image.
# ──────────────────────────────────────────────────────────────────────────────

# ── Stage 1: Builder ─────────────────────────────────────────────────────────
FROM python:3.12-slim AS builder

RUN apt-get update && \
    apt-get install -y --no-install-recommends \
    build-essential \
    cmake \
    ninja-build \
    git \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /build

# Copy only what's needed for the build (respects .dockerignore)
COPY . /build

# Build the wheel
# FIX M-04: Pin build deps to match cibuildwheel config
# (scikit-build-core==0.10.7, nanobind==2.4.0)
RUN pip install --no-cache-dir build scikit-build-core==0.10.7 nanobind==2.4.0 && \
    python -m build --wheel --outdir /wheels

# ── Stage 2: Runtime ─────────────────────────────────────────────────────────
FROM python:3.12-slim AS runtime

LABEL maintainer="Zedda-Labs <zeddalabs@gmail.com>"
LABEL description="Zedda — Zero Effort Data Analysis. C++ parallel core."
LABEL org.opencontainers.image.source="https://github.com/Zedda-Labs/Zedda"

# Install the pre-built wheel (no compiler needed)
COPY --from=builder /wheels/*.whl /tmp/
RUN pip install --no-cache-dir /tmp/*.whl && \
    rm -rf /tmp/*.whl

# FIX CI-H4: Create a non-root user and switch to it. Running as root
# is a container-escape privilege-escalation risk.
RUN useradd --create-home --shell /bin/bash --uid 1000 zedda && \
    mkdir -p /data && chown -R zedda:zedda /data

# Create a data directory for users to mount their datasets
WORKDIR /data
USER zedda

# FIX L-07: Add a HEALTHCHECK so orchestrators can detect a wedged container.
HEALTHCHECK --interval=5m --timeout=10s --start-period=10s --retries=3 \
    CMD python -c "import zedda" || exit 1

# By default, open a Python shell. Users can override with:
#   docker run zedda python -m zedda.cli run data.csv
CMD ["python"]
