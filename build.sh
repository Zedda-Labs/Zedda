#!/bin/bash
# fasteda build script
# Usage: bash build.sh

echo "Building fasteda_core.pyd..."

g++ -std=c++17 -O2 -shared \
  -I include \
  -I "C:/Program Files/Python312/Include" \
  -I "C:/Users/ADMIN/AppData/Roaming/Python/Python312/site-packages/nanobind/include" \
  -I extern/nanobind/include \
  -I extern/nanobind/src \
  -I extern/nanobind/ext/robin_map/include \
  src/core/stream_reader.cpp \
  src/core/profile_builder.cpp \
  src/bindings/bindings.cpp \
  extern/nanobind/src/nb_combined.cpp \
  -L "C:/Program Files/Python312" \
  -lpython312 \
  -o python/fasteda/fasteda_core.pyd

if [ $? -eq 0 ]; then
    echo "SUCCESS! fasteda_core.pyd built!"
    echo ""
    echo "Now run:"
    echo "  python -c \"import sys; sys.path.insert(0, 'python'); import fasteda as fe; fe.profile('profile_test.csv')\""
else
    echo "FAILED! Check errors above."
fi