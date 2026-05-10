"""
Reads raw page-create events from Kafka topic 'input',
filters by allowed domains and non-bot users,
and writes the result to Kafka topic 'processed'.
"""
from pyspark.sql import SparkSession
from pyspark.sql.functions import col, from_json, struct, to_json
from pyspark.sql.types import (
    BooleanType,
    LongType,
    StringType,
    StructField,
    StructType,
)

KAFKA_BOOTSTRAP = "kafka:9092"
INPUT_TOPIC = "input"
OUTPUT_TOPIC = "processed"
CHECKPOINT_DIR = "/tmp/checkpoints/processor"

ALLOWED_DOMAINS = ["en.wikipedia.org", "www.wikidata.org", "commons.wikimedia.org"]

EVENT_SCHEMA = StructType([
    StructField("meta", StructType([
        StructField("domain", StringType(), True),
        StructField("dt", StringType(), True),
    ]), True),
    StructField("page_title", StringType(), True),
    StructField("performer", StructType([
        StructField("user_id", LongType(), True),
        StructField("user_is_bot", BooleanType(), True),
    ]), True),
])


def main():
    spark = (
        SparkSession.builder
        .appName("WikiStreamProcessor")
        .getOrCreate()
    )
    spark.sparkContext.setLogLevel("WARN")

    raw_df = (
        spark.readStream
        .format("kafka")
        .option("kafka.bootstrap.servers", KAFKA_BOOTSTRAP)
        .option("subscribe", INPUT_TOPIC)
        .option("startingOffsets", "latest")
        .option("failOnDataLoss", "false")
        .load()
    )

    parsed_df = raw_df.select(
        from_json(col("value").cast("string"), EVENT_SCHEMA).alias("e")
    ).select(
        col("e.meta.domain").alias("domain"),
        col("e.meta.dt").alias("created_at"),
        col("e.page_title").alias("page_title"),
        col("e.performer.user_id").alias("user_id"),
        col("e.performer.user_is_bot").alias("user_is_bot"),
    )

    filtered_df = (
        parsed_df
        .filter(col("domain").isin(ALLOWED_DOMAINS))
        .filter(col("user_is_bot") == False)  # noqa: E712
    )

    output_df = filtered_df.select(
        to_json(struct(
            col("domain"),
            col("created_at"),
            col("page_title"),
            col("user_id"),
        )).alias("value")
    )

    query = (
        output_df.writeStream
        .format("kafka")
        .option("kafka.bootstrap.servers", KAFKA_BOOTSTRAP)
        .option("topic", OUTPUT_TOPIC)
        .option("checkpointLocation", CHECKPOINT_DIR)
        .start()
    )

    query.awaitTermination()


if __name__ == "__main__":
    main()