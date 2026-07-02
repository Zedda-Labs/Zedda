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
RUN pip install --no-cache-dir build scikit-build-core nanobind && \
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

# Create a data directory for users to mount their datasets
RUN mkdir /data
WORKDIR /data

# By default, open a Python shell. Users can override with:
#   docker run zedda python -m zedda.cli run data.csv
CMD ["python"]
