#!/usr/bin/env bash
set -e

echo "Submitting Cassandra Writer (processed -> Cassandra)..."

docker exec -d spark-master bash -c "
  spark-submit \
    --master spark://spark-master:7077 \
    --packages org.apache.spark:spark-sql-kafka-0-10_2.12:3.5.0,com.datastax.spark:spark-cassandra-connector_2.12:3.5.0 \
    --conf spark.driver.memory=1g \
    --conf spark.executor.memory=1g \
    --conf spark.cassandra.connection.host=cassandra \
    /opt/spark-apps/cassandra_writer.py \
    > /tmp/cassandra_writer.log 2>&1
"

echo "Cassandra Writer submitted."
echo "Logs: docker exec spark-master tail -f /tmp/cassandra_writer.log"