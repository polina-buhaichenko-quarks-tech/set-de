#!/bin/bash
set -e
docker build -t kafka-consumer "$(dirname "$0")"