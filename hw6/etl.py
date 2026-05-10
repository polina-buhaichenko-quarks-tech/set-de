import os
import pymongo
from pyspark.sql import SparkSession
from pyspark.sql.functions import (
    col, avg, count, month, year, to_date,
    round as spark_round,
)
from pyspark.sql.types import IntegerType

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_PATH = os.path.join(SCRIPT_DIR, "..", "data2", "amazon_reviews.csv")
MONGO_URI = os.getenv("MONGO_URI", "mongodb://localhost:27017/")
DB_NAME = "amazon_reviews"


def write_collection(db, name, spark_df, index_keys):
    records = [row.asDict() for row in spark_df.collect()]
    coll = db[name]
    coll.drop()
    if records:
        coll.insert_many(records)
    coll.create_index(index_keys)
    print(f"  [{name}] {len(records):,} documents written")


def main():
    spark = (
        SparkSession.builder
        .appName("AmazonReviewsETL")
        .getOrCreate()
    )
    spark.sparkContext.setLogLevel("WARN")

    # --- 1. Ingest ---
    print("Loading CSV...")
    df = spark.read.csv(DATA_PATH, header=True, inferSchema=True)
    print(f"  Raw rows: {df.count():,}")

    # --- 2. Clean ---
    print("Cleaning...")
    df = df.dropna(subset=["review_id", "product_id", "star_rating", "review_date"])
    df = df.withColumn("review_date", to_date(col("review_date"), "yyyy-MM-dd"))
    df = df.withColumn("star_rating", col("star_rating").cast(IntegerType()))
    df = df.withColumn("verified_purchase", col("verified_purchase").cast(IntegerType()))
    df = df.filter(col("verified_purchase") == 1)
    df.cache()
    verified_count = df.count()
    print(f"  Verified-purchase rows: {verified_count:,}")

    # --- 3. Aggregations ---

    # 3a. Total reviews + avg star rating per product
    product_stats = (
        df.groupBy("product_id", "product_title")
        .agg(
            count("review_id").alias("total_reviews"),
            spark_round(avg("star_rating"), 2).alias("avg_star_rating"),
        )
    )

    # 3b. Total verified reviews per customer
    customer_stats = (
        df.groupBy("customer_id")
        .agg(count("review_id").alias("total_verified_reviews"))
    )

    # 3c. Monthly review count per product
    monthly_reviews = (
        df
        .withColumn("year", year(col("review_date")))
        .withColumn("month", month(col("review_date")))
        .groupBy("product_id", "year", "month")
        .agg(count("review_id").alias("review_count"))
        .orderBy("product_id", "year", "month")
    )

    # --- 4. Write to MongoDB ---
    print("Writing to MongoDB...")
    client = pymongo.MongoClient(MONGO_URI)
    db = client[DB_NAME]

    write_collection(
        db, "product_stats", product_stats,
        [("product_id", pymongo.ASCENDING)],
    )
    write_collection(
        db, "customer_stats", customer_stats,
        [("customer_id", pymongo.ASCENDING)],
    )
    write_collection(
        db, "monthly_product_reviews", monthly_reviews,
        [("product_id", pymongo.ASCENDING), ("year", pymongo.ASCENDING), ("month", pymongo.ASCENDING)],
    )

    print("ETL complete.")
    spark.stop()


if __name__ == "__main__":
    main()