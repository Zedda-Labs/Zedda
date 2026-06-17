# Use the official Python 3.12 slim image as the base
FROM python:3.12-slim

# Install system dependencies needed for building the C++ extension
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
    build-essential \
    cmake \
    git \
    && rm -rf /var/lib/apt/lists/*

# Set the working directory
WORKDIR /app

# Copy the source code into the container
COPY . /app

# Install Zedda
# We install from the local source so it builds the C++ extension during the image build
RUN pip install --no-cache-dir .

# Create a data directory for users to mount their datasets
RUN mkdir /data
WORKDIR /data

# By default, running the container will open a python shell,
# but users can override this to run 'python -m zedda.cli' or scripts
CMD ["python"]
