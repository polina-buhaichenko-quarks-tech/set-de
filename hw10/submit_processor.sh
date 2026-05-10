#!/usr/bin/env bash
set -e

echo "Submitting Stream Processor (input -> processed)..."

docker exec -d spark-master bash -c "
  spark-submit \
    --master spark://spark-master:7077 \
    --packages org.apache.spark:spark-sql-kafka-0-10_2.12:3.5.0 \
    --conf spark.driver.memory=1g \
    --conf spark.executor.memory=1g \
    /opt/spark-apps/stream_processor.py \
    > /tmp/processor.log 2>&1
"

echo "Stream Processor submitted."
echo "Logs: docker exec spark-master tail -f /tmp/processor.log"