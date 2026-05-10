#!/bin/bash
set -e
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
DATA_DIR="$SCRIPT_DIR/../data2"

docker run --rm \
  --network kafka-net \
  -v "$DATA_DIR:/data:ro" \
  -e KAFKA_BOOTSTRAP=kafka:9092 \
  kafka-producer