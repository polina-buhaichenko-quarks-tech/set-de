"""
PySpark ETL: Amazon Reviews CSV → Cassandra

Schema design rationale:
  reviews_by_product        partition=product_id, cluster=(star_rating, review_date, review_id)
                            → serves GET /products/{id}/reviews  (all or filtered by star_rating)
  reviews_by_customer       partition=customer_id, cluster=(review_date, review_id)
                            → serves GET /customers/{id}/reviews
  product_monthly_counts    partition=(year, month), cluster=review_count DESC
                            → serves GET /analytics/most-reviewed  (multi-month → aggregate in API)
  customer_verified_monthly partition=(year, month), cluster=review_count DESC
                            → serves GET /analytics/most-productive-customers  (verified only)
  customer_hater_monthly    partition=(year, month), cluster=review_count DESC
                            → serves GET /analytics/most-productive-haters    (star 1-2)
  customer_backer_monthly   partition=(year, month), cluster=review_count DESC
                            → serves GET /analytics/most-productive-backers   (star 4-5)

No ALLOW FILTERING is used anywhere.
"""
import os

from cassandra.cluster import Cluster, ExecutionProfile, EXEC_PROFILE_DEFAULT
from cassandra.concurrent import execute_concurrent_with_args
from cassandra.policies import DCAwareRoundRobinPolicy
from pyspark.sql import SparkSession
from pyspark.sql.functions import (
    col, count, month as spark_month, year as spark_year, to_date,
)
from pyspark.sql.types import IntegerType

CASSANDRA_HOST = os.getenv("CASSANDRA_HOST", "localhost")
CASSANDRA_DC = os.getenv("CASSANDRA_DC", "datacenter1")
KEYSPACE = "amazon_reviews"
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_PATH = os.path.join(SCRIPT_DIR, "..", "data2", "amazon_reviews.csv")
CONCURRENCY = 200


# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------

DDL_KEYSPACE = f"""
    CREATE KEYSPACE IF NOT EXISTS {KEYSPACE}
    WITH replication = {{'class': 'SimpleStrategy', 'replication_factor': 1}}
"""

DDL_TABLES = [
    """
    CREATE TABLE IF NOT EXISTS reviews_by_product (
        product_id       text,
        star_rating      int,
        review_date      date,
        review_id        text,
        customer_id      text,
        marketplace      text,
        product_title    text,
        product_category text,
        helpful_votes    int,
        total_votes      int,
        vine             int,
        verified_purchase int,
        review_headline  text,
        review_body      text,
        PRIMARY KEY ((product_id), star_rating, review_date, review_id)
    ) WITH CLUSTERING ORDER BY (star_rating ASC, review_date DESC, review_id ASC)
    """,
    """
    CREATE TABLE IF NOT EXISTS reviews_by_customer (
        customer_id      text,
        review_date      date,
        review_id        text,
        product_id       text,
        product_title    text,
        star_rating      int,
        verified_purchase int,
        marketplace      text,
        review_headline  text,
        review_body      text,
        PRIMARY KEY ((customer_id), review_date, review_id)
    ) WITH CLUSTERING ORDER BY (review_date DESC, review_id ASC)
    """,
    """
    CREATE TABLE IF NOT EXISTS product_monthly_counts (
        year         int,
        month        int,
        review_count int,
        product_id   text,
        product_title text,
        PRIMARY KEY ((year, month), review_count, product_id)
    ) WITH CLUSTERING ORDER BY (review_count DESC, product_id ASC)
    """,
    """
    CREATE TABLE IF NOT EXISTS customer_verified_monthly (
        year         int,
        month        int,
        review_count int,
        customer_id  text,
        PRIMARY KEY ((year, month), review_count, customer_id)
    ) WITH CLUSTERING ORDER BY (review_count DESC, customer_id ASC)
    """,
    """
    CREATE TABLE IF NOT EXISTS customer_hater_monthly (
        year         int,
        month        int,
        review_count int,
        customer_id  text,
        PRIMARY KEY ((year, month), review_count, customer_id)
    ) WITH CLUSTERING ORDER BY (review_count DESC, customer_id ASC)
    """,
    """
    CREATE TABLE IF NOT EXISTS customer_backer_monthly (
        year         int,
        month        int,
        review_count int,
        customer_id  text,
        PRIMARY KEY ((year, month), review_count, customer_id)
    ) WITH CLUSTERING ORDER BY (review_count DESC, customer_id ASC)
    """,
]

TRUNCATE_TABLES = [
    "reviews_by_product",
    "reviews_by_customer",
    "product_monthly_counts",
    "customer_verified_monthly",
    "customer_hater_monthly",
    "customer_backer_monthly",
]


def connect_cassandra():
    profile = ExecutionProfile(
        load_balancing_policy=DCAwareRoundRobinPolicy(local_dc=CASSANDRA_DC),
    )
    cluster = Cluster(
        contact_points=[CASSANDRA_HOST],
        execution_profiles={EXEC_PROFILE_DEFAULT: profile},
    )
    return cluster, cluster.connect()


def create_schema(session):
    session.execute(DDL_KEYSPACE)
    session.set_keyspace(KEYSPACE)
    for ddl in DDL_TABLES:
        session.execute(ddl)
    for table in TRUNCATE_TABLES:
        session.execute(f"TRUNCATE {KEYSPACE}.{table}")


def bulk_insert(session, stmt, params, label):
    results = execute_concurrent_with_args(
        session, stmt, params, concurrency=CONCURRENCY, raise_on_first_error=False,
    )
    errors = sum(1 for ok, _ in results if not ok)
    print(f"  [{label}] {len(params):,} rows  ({errors} errors)")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    # -- Cassandra --
    print("Connecting to Cassandra...")
    cluster, session = connect_cassandra()
    create_schema(session)
    print("Schema ready.")

    # -- Spark --
    print("Starting Spark...")
    spark = SparkSession.builder.appName("AmazonReviewsETL_hw7").getOrCreate()
    spark.sparkContext.setLogLevel("WARN")

    print(f"Loading {DATA_PATH}...")
    raw = spark.read.csv(DATA_PATH, header=True, inferSchema=True)
    print(f"  Raw rows: {raw.count():,}")

    # Clean
    df = raw.dropna(subset=["review_id", "product_id", "customer_id", "star_rating", "review_date"])
    df = (
        df
        .withColumn("star_rating",       col("star_rating").cast(IntegerType()))
        .withColumn("helpful_votes",     col("helpful_votes").cast(IntegerType()))
        .withColumn("total_votes",       col("total_votes").cast(IntegerType()))
        .withColumn("vine",              col("vine").cast(IntegerType()))
        .withColumn("verified_purchase", col("verified_purchase").cast(IntegerType()))
        .withColumn("customer_id",       col("customer_id").cast("string"))
        .withColumn("review_date",       to_date(col("review_date"), "yyyy-MM-dd"))
        .filter(col("star_rating").between(1, 5))
    )
    df.cache()
    print(f"  Clean rows: {df.count():,}")

    df_t = df.withColumn("year",  spark_year("review_date")) \
             .withColumn("month", spark_month("review_date"))

    # ---- reviews_by_product ------------------------------------------------
    print("Writing reviews_by_product...")
    stmt = session.prepare("""
        INSERT INTO reviews_by_product
          (product_id, star_rating, review_date, review_id, customer_id,
           marketplace, product_title, product_category, helpful_votes,
           total_votes, vine, verified_purchase, review_headline, review_body)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """)
    rows = df.select(
        "product_id", "star_rating", "review_date", "review_id", "customer_id",
        "marketplace", "product_title", "product_category", "helpful_votes",
        "total_votes", "vine", "verified_purchase", "review_headline", "review_body",
    ).collect()
    params = [
        (r.product_id, r.star_rating, r.review_date, r.review_id, r.customer_id,
         r.marketplace, r.product_title, r.product_category, r.helpful_votes,
         r.total_votes, r.vine, r.verified_purchase, r.review_headline, r.review_body)
        for r in rows
    ]
    bulk_insert(session, stmt, params, "reviews_by_product")

    # ---- reviews_by_customer -----------------------------------------------
    print("Writing reviews_by_customer...")
    stmt = session.prepare("""
        INSERT INTO reviews_by_customer
          (customer_id, review_date, review_id, product_id, product_title,
           star_rating, verified_purchase, marketplace, review_headline, review_body)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """)
    rows = df.select(
        "customer_id", "review_date", "review_id", "product_id", "product_title",
        "star_rating", "verified_purchase", "marketplace", "review_headline", "review_body",
    ).collect()
    params = [
        (r.customer_id, r.review_date, r.review_id, r.product_id, r.product_title,
         r.star_rating, r.verified_purchase, r.marketplace, r.review_headline, r.review_body)
        for r in rows
    ]
    bulk_insert(session, stmt, params, "reviews_by_customer")

    # ---- product_monthly_counts --------------------------------------------
    print("Writing product_monthly_counts...")
    stmt = session.prepare("""
        INSERT INTO product_monthly_counts (year, month, review_count, product_id, product_title)
        VALUES (?, ?, ?, ?, ?)
    """)
    agg = (
        df_t.groupBy("year", "month", "product_id", "product_title")
            .agg(count("review_id").alias("review_count"))
            .collect()
    )
    params = [(r.year, r.month, r.review_count, r.product_id, r.product_title) for r in agg]
    bulk_insert(session, stmt, params, "product_monthly_counts")

    # ---- customer_verified_monthly -----------------------------------------
    print("Writing customer_verified_monthly...")
    stmt = session.prepare("""
        INSERT INTO customer_verified_monthly (year, month, review_count, customer_id)
        VALUES (?, ?, ?, ?)
    """)
    agg = (
        df_t.filter(col("verified_purchase") == 1)
            .groupBy("year", "month", "customer_id")
            .agg(count("review_id").alias("review_count"))
            .collect()
    )
    params = [(r.year, r.month, r.review_count, r.customer_id) for r in agg]
    bulk_insert(session, stmt, params, "customer_verified_monthly")

    # ---- customer_hater_monthly --------------------------------------------
    print("Writing customer_hater_monthly...")
    stmt = session.prepare("""
        INSERT INTO customer_hater_monthly (year, month, review_count, customer_id)
        VALUES (?, ?, ?, ?)
    """)
    agg = (
        df_t.filter(col("star_rating").isin(1, 2))
            .groupBy("year", "month", "customer_id")
            .agg(count("review_id").alias("review_count"))
            .collect()
    )
    params = [(r.year, r.month, r.review_count, r.customer_id) for r in agg]
    bulk_insert(session, stmt, params, "customer_hater_monthly")

    # ---- customer_backer_monthly -------------------------------------------
    print("Writing customer_backer_monthly...")
    stmt = session.prepare("""
        INSERT INTO customer_backer_monthly (year, month, review_count, customer_id)
        VALUES (?, ?, ?, ?)
    """)
    agg = (
        df_t.filter(col("star_rating").isin(4, 5))
            .groupBy("year", "month", "customer_id")
            .agg(count("review_id").alias("review_count"))
            .collect()
    )
    params = [(r.year, r.month, r.review_count, r.customer_id) for r in agg]
    bulk_insert(session, stmt, params, "customer_backer_monthly")

    print("ETL complete.")
    spark.stop()
    cluster.shutdown()


if __name__ == "__main__":
    main()