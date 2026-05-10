"""
Reads filtered page-create events from Kafka topic 'processed'
and writes them into the Cassandra table wiki.page_creates.
"""
from pyspark.sql import DataFrame, SparkSession
from pyspark.sql.functions import col, from_json, to_timestamp
from pyspark.sql.types import LongType, StringType, StructField, StructType

KAFKA_BOOTSTRAP = "kafka:9092"
PROCESSED_TOPIC = "processed"
CHECKPOINT_DIR = "/tmp/checkpoints/cassandra"
CASSANDRA_HOST = "cassandra"
KEYSPACE = "wiki"
TABLE = "page_creates"

EVENT_SCHEMA = StructType([
    StructField("domain", StringType(), True),
    StructField("created_at", StringType(), True),
    StructField("page_title", StringType(), True),
    StructField("user_id", LongType(), True),
])


def write_batch(batch_df: DataFrame, _batch_id: int) -> None:
    (
        batch_df
        .write
        .format("org.apache.spark.sql.cassandra")
        .mode("append")
        .options(table=TABLE, keyspace=KEYSPACE)
        .save()
    )


def main():
    spark = (
        SparkSession.builder
        .appName("WikiCassandraWriter")
        .config("spark.cassandra.connection.host", CASSANDRA_HOST)
        .config("spark.cassandra.connection.port", "9042")
        .getOrCreate()
    )
    spark.sparkContext.setLogLevel("WARN")

    raw_df = (
        spark.readStream
        .format("kafka")
        .option("kafka.bootstrap.servers", KAFKA_BOOTSTRAP)
        .option("subscribe", PROCESSED_TOPIC)
        .option("startingOffsets", "latest")
        .option("failOnDataLoss", "false")
        .load()
    )

    parsed_df = raw_df.select(
        from_json(col("value").cast("string"), EVENT_SCHEMA).alias("e")
    ).select(
        col("e.domain").alias("domain"),
        to_timestamp(col("e.created_at")).alias("created_at"),
        col("e.page_title").alias("page_title"),
        col("e.user_id").alias("user_id"),
    )

    query = (
        parsed_df.writeStream
        .foreachBatch(write_batch)
        .option("checkpointLocation", CHECKPOINT_DIR)
        .start()
    )

    query.awaitTermination()


if __name__ == "__main__":
    main()