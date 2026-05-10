"""
Amazon Reviews REST API
Cassandra backend + Redis caching (TTL 5 min)
"""
import json
import os
from collections import defaultdict
from contextlib import asynccontextmanager
from datetime import date
from typing import Optional

import redis as redis_lib
from cassandra.cluster import Cluster, ExecutionProfile, EXEC_PROFILE_DEFAULT
from cassandra.policies import DCAwareRoundRobinPolicy
from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import JSONResponse

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
CASSANDRA_HOST = os.getenv("CASSANDRA_HOST", "localhost")
CASSANDRA_DC   = os.getenv("CASSANDRA_DC",   "datacenter1")
REDIS_HOST     = os.getenv("REDIS_HOST",     "localhost")
REDIS_PORT     = int(os.getenv("REDIS_PORT", "6379"))
KEYSPACE       = "amazon_reviews"
CACHE_TTL      = 300  # 5 minutes

# ---------------------------------------------------------------------------
# Globals (initialised in lifespan)
# ---------------------------------------------------------------------------
cass_session = None
redis_client  = None

stmts: dict = {}

# ---------------------------------------------------------------------------
# Schema (created at startup so the API works before ETL runs)
# ---------------------------------------------------------------------------
DDL_KEYSPACE = f"""
    CREATE KEYSPACE IF NOT EXISTS {KEYSPACE}
    WITH replication = {{'class': 'SimpleStrategy', 'replication_factor': 1}}
"""
DDL_TABLES = [
    """
    CREATE TABLE IF NOT EXISTS reviews_by_product (
        product_id text, star_rating int, review_date date, review_id text,
        customer_id text, marketplace text, product_title text,
        product_category text, helpful_votes int, total_votes int,
        vine int, verified_purchase int, review_headline text, review_body text,
        PRIMARY KEY ((product_id), star_rating, review_date, review_id)
    ) WITH CLUSTERING ORDER BY (star_rating ASC, review_date DESC, review_id ASC)
    """,
    """
    CREATE TABLE IF NOT EXISTS reviews_by_customer (
        customer_id text, review_date date, review_id text,
        product_id text, product_title text, star_rating int,
        verified_purchase int, marketplace text,
        review_headline text, review_body text,
        PRIMARY KEY ((customer_id), review_date, review_id)
    ) WITH CLUSTERING ORDER BY (review_date DESC, review_id ASC)
    """,
    """
    CREATE TABLE IF NOT EXISTS product_monthly_counts (
        year int, month int, review_count int, product_id text, product_title text,
        PRIMARY KEY ((year, month), review_count, product_id)
    ) WITH CLUSTERING ORDER BY (review_count DESC, product_id ASC)
    """,
    """
    CREATE TABLE IF NOT EXISTS customer_verified_monthly (
        year int, month int, review_count int, customer_id text,
        PRIMARY KEY ((year, month), review_count, customer_id)
    ) WITH CLUSTERING ORDER BY (review_count DESC, customer_id ASC)
    """,
    """
    CREATE TABLE IF NOT EXISTS customer_hater_monthly (
        year int, month int, review_count int, customer_id text,
        PRIMARY KEY ((year, month), review_count, customer_id)
    ) WITH CLUSTERING ORDER BY (review_count DESC, customer_id ASC)
    """,
    """
    CREATE TABLE IF NOT EXISTS customer_backer_monthly (
        year int, month int, review_count int, customer_id text,
        PRIMARY KEY ((year, month), review_count, customer_id)
    ) WITH CLUSTERING ORDER BY (review_count DESC, customer_id ASC)
    """,
]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def months_in_range(start: date, end: date) -> list[tuple[int, int]]:
    months = []
    y, m = start.year, start.month
    ey, em = end.year, end.month
    while (y, m) <= (ey, em):
        months.append((y, m))
        m += 1
        if m > 12:
            m, y = 1, y + 1
    return months


def row_to_dict(row) -> dict:
    d = {}
    for field in row._fields:
        val = getattr(row, field)
        if isinstance(val, date):
            val = val.isoformat()
        d[field] = val
    return d


def cache_get(key: str):
    raw = redis_client.get(key)
    return json.loads(raw) if raw else None


def cache_set(key: str, data):
    redis_client.setex(key, CACHE_TTL, json.dumps(data, default=str))


def parse_dates(start_str: str, end_str: str) -> tuple[date, date]:
    try:
        start = date.fromisoformat(start_str)
        end   = date.fromisoformat(end_str)
    except ValueError:
        raise HTTPException(status_code=400, detail="Dates must be YYYY-MM-DD")
    if start > end:
        raise HTTPException(status_code=400, detail="start_date must be <= end_date")
    return start, end


def aggregate_monthly(stmt, months: list, key_field: str) -> dict[str, int]:
    totals: dict[str, int] = defaultdict(int)
    for y, m in months:
        for row in cass_session.execute(stmt, (y, m)):
            totals[getattr(row, key_field)] += row.review_count
    return totals


# ---------------------------------------------------------------------------
# Lifespan
# ---------------------------------------------------------------------------

@asynccontextmanager
async def lifespan(app: FastAPI):
    global cass_session, redis_client, stmts

    profile = ExecutionProfile(
        load_balancing_policy=DCAwareRoundRobinPolicy(local_dc=CASSANDRA_DC),
    )
    cluster = Cluster(
        contact_points=[CASSANDRA_HOST],
        execution_profiles={EXEC_PROFILE_DEFAULT: profile},
    )
    cass_session = cluster.connect()
    cass_session.execute(DDL_KEYSPACE)
    cass_session.set_keyspace(KEYSPACE)
    for ddl in DDL_TABLES:
        cass_session.execute(ddl)

    stmts["reviews_by_product"] = cass_session.prepare(
        "SELECT * FROM reviews_by_product WHERE product_id = ?"
    )
    stmts["reviews_by_product_rated"] = cass_session.prepare(
        "SELECT * FROM reviews_by_product WHERE product_id = ? AND star_rating = ?"
    )
    stmts["reviews_by_customer"] = cass_session.prepare(
        "SELECT * FROM reviews_by_customer WHERE customer_id = ?"
    )
    stmts["product_monthly"] = cass_session.prepare(
        "SELECT product_id, product_title, review_count "
        "FROM product_monthly_counts WHERE year = ? AND month = ?"
    )
    stmts["customer_verified_monthly"] = cass_session.prepare(
        "SELECT customer_id, review_count "
        "FROM customer_verified_monthly WHERE year = ? AND month = ?"
    )
    stmts["customer_hater_monthly"] = cass_session.prepare(
        "SELECT customer_id, review_count "
        "FROM customer_hater_monthly WHERE year = ? AND month = ?"
    )
    stmts["customer_backer_monthly"] = cass_session.prepare(
        "SELECT customer_id, review_count "
        "FROM customer_backer_monthly WHERE year = ? AND month = ?"
    )

    redis_client = redis_lib.Redis(host=REDIS_HOST, port=REDIS_PORT, decode_responses=True)

    yield

    cluster.shutdown()


app = FastAPI(title="Amazon Reviews API", version="1.0.0", lifespan=lifespan)


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@app.get("/products/{product_id}/reviews",
         summary="All reviews for a product (optionally filtered by star_rating)")
async def get_product_reviews(
    product_id: str,
    star_rating: Optional[int] = Query(None, ge=1, le=5,
                                       description="Filter by star rating (1-5)"),
):
    key = f"product_reviews:{product_id}:{star_rating}"
    cached = cache_get(key)
    if cached is not None:
        return JSONResponse(content=cached)

    if star_rating is not None:
        rows = cass_session.execute(stmts["reviews_by_product_rated"], (product_id, star_rating))
    else:
        rows = cass_session.execute(stmts["reviews_by_product"], (product_id,))

    result = [row_to_dict(r) for r in rows]
    cache_set(key, result)
    return JSONResponse(content=result)


@app.get("/customers/{customer_id}/reviews",
         summary="All reviews by a customer")
async def get_customer_reviews(customer_id: str):
    key = f"customer_reviews:{customer_id}"
    cached = cache_get(key)
    if cached is not None:
        return JSONResponse(content=cached)

    rows = cass_session.execute(stmts["reviews_by_customer"], (customer_id,))
    result = [row_to_dict(r) for r in rows]
    cache_set(key, result)
    return JSONResponse(content=result)


@app.get("/analytics/most-reviewed",
         summary="Top N most reviewed products in a date range")
async def most_reviewed(
    start_date: str = Query(..., description="YYYY-MM-DD"),
    end_date:   str = Query(..., description="YYYY-MM-DD"),
    n:          int = Query(10, ge=1, le=500),
):
    key = f"most_reviewed:{start_date}:{end_date}:{n}"
    cached = cache_get(key)
    if cached is not None:
        return JSONResponse(content=cached)

    start, end = parse_dates(start_date, end_date)
    months = months_in_range(start, end)

    # Aggregate review counts per product across all months in range
    totals: dict[str, dict] = defaultdict(lambda: {"review_count": 0, "product_title": ""})
    for y, m in months:
        for row in cass_session.execute(stmts["product_monthly"], (y, m)):
            totals[row.product_id]["review_count"] += row.review_count
            totals[row.product_id]["product_title"] = row.product_title

    result = sorted(
        [{"product_id": pid, **v} for pid, v in totals.items()],
        key=lambda x: x["review_count"],
        reverse=True,
    )[:n]

    cache_set(key, result)
    return JSONResponse(content=result)


@app.get("/analytics/most-productive-customers",
         summary="Top N customers by verified-purchase review count in a date range")
async def most_productive_customers(
    start_date: str = Query(..., description="YYYY-MM-DD"),
    end_date:   str = Query(..., description="YYYY-MM-DD"),
    n:          int = Query(10, ge=1, le=500),
):
    key = f"most_productive_customers:{start_date}:{end_date}:{n}"
    cached = cache_get(key)
    if cached is not None:
        return JSONResponse(content=cached)

    start, end = parse_dates(start_date, end_date)
    months = months_in_range(start, end)
    totals = aggregate_monthly(stmts["customer_verified_monthly"], months, "customer_id")

    result = sorted(
        [{"customer_id": cid, "verified_review_count": cnt} for cid, cnt in totals.items()],
        key=lambda x: x["verified_review_count"],
        reverse=True,
    )[:n]

    cache_set(key, result)
    return JSONResponse(content=result)


@app.get("/analytics/most-productive-haters",
         summary="Top N customers by 1-or-2-star reviews in a date range")
async def most_productive_haters(
    start_date: str = Query(..., description="YYYY-MM-DD"),
    end_date:   str = Query(..., description="YYYY-MM-DD"),
    n:          int = Query(10, ge=1, le=500),
):
    key = f"most_productive_haters:{start_date}:{end_date}:{n}"
    cached = cache_get(key)
    if cached is not None:
        return JSONResponse(content=cached)

    start, end = parse_dates(start_date, end_date)
    months = months_in_range(start, end)
    totals = aggregate_monthly(stmts["customer_hater_monthly"], months, "customer_id")

    result = sorted(
        [{"customer_id": cid, "low_star_review_count": cnt} for cid, cnt in totals.items()],
        key=lambda x: x["low_star_review_count"],
        reverse=True,
    )[:n]

    cache_set(key, result)
    return JSONResponse(content=result)


@app.get("/analytics/most-productive-backers",
         summary="Top N customers by 4-or-5-star reviews in a date range")
async def most_productive_backers(
    start_date: str = Query(..., description="YYYY-MM-DD"),
    end_date:   str = Query(..., description="YYYY-MM-DD"),
    n:          int = Query(10, ge=1, le=500),
):
    key = f"most_productive_backers:{start_date}:{end_date}:{n}"
    cached = cache_get(key)
    if cached is not None:
        return JSONResponse(content=cached)

    start, end = parse_dates(start_date, end_date)
    months = months_in_range(start, end)
    totals = aggregate_monthly(stmts["customer_backer_monthly"], months, "customer_id")

    result = sorted(
        [{"customer_id": cid, "high_star_review_count": cnt} for cid, cnt in totals.items()],
        key=lambda x: x["high_star_review_count"],
        reverse=True,
    )[:n]

    cache_set(key, result)
    return JSONResponse(content=result)