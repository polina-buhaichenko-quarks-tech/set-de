#!/bin/bash
set -e
docker build -t kafka-producer "$(dirname "$0")"