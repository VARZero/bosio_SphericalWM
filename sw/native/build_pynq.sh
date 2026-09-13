#!/bin/sh
set -eu
cd "$(dirname "$0")"
g++ -std=c++17 -O3 -DNDEBUG -fPIC -shared -mcpu=cortex-a9 -mfpu=neon-vfpv3 \
  -mfloat-abi=hard -ftree-vectorize -ffunction-sections -fdata-sections \
  -Wl,--gc-sections bosio_compositor.cpp -o ../libbosio_compositor.so
echo "built ../libbosio_compositor.so"
