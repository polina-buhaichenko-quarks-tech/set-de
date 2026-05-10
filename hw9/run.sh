#!/bin/bash
set -e
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

mkdir -p "$SCRIPT_DIR/output"

docker run --rm \
  --network kafka-net \
  -v "$SCRIPT_DIR/output:/output" \
  -e KAFKA_BOOTSTRAP=kafka:9092 \
  kafka-consumer