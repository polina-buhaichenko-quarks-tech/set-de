# HW7 — Amazon Reviews: Cassandra + Redis REST API

PySpark ingestion into a Cassandra schema optimised for 7 query patterns, served through a FastAPI REST layer with Redis response caching (5-min TTL).

---

## Stack

| Component | Image / Tool |
|---|---|
| Cassandra | `cassandra:4.1` |
| Redis | `redis:7-alpine` |
| REST API | FastAPI + uvicorn (Python 3.11) |
| ETL | PySpark 3.5 + cassandra-driver |

---

## Cassandra Schema Design

Six tables, each denormalised for a specific access pattern. No `ALLOW FILTERING` is used anywhere.

### `reviews_by_product`
```
PRIMARY KEY ((product_id), star_rating, review_date, review_id)
CLUSTERING ORDER BY (star_rating ASC, review_date DESC, review_id ASC)
```
Serves:
- `GET /products/{id}/reviews` — full partition scan
- `GET /products/{id}/reviews?star_rating=X` — equality on first clustering column

### `reviews_by_customer`
```
PRIMARY KEY ((customer_id), review_date, review_id)
CLUSTERING ORDER BY (review_date DESC, review_id ASC)
```
Serves:
- `GET /customers/{id}/reviews`

### `product_monthly_counts`
```
PRIMARY KEY ((year, month), review_count, product_id)
CLUSTERING ORDER BY (review_count DESC, product_id ASC)
```
Serves:
- `GET /analytics/most-reviewed` — API queries each (year, month) partition in the requested range, then aggregates totals in Python and returns top N.

### `customer_verified_monthly`
```
PRIMARY KEY ((year, month), review_count, customer_id)
CLUSTERING ORDER BY (review_count DESC, customer_id ASC)
```
Serves:
- `GET /analytics/most-productive-customers` — counts only `verified_purchase = 1` reviews.

### `customer_hater_monthly`
```
PRIMARY KEY ((year, month), review_count, customer_id)
CLUSTERING ORDER BY (review_count DESC, customer_id ASC)
```
Serves:
- `GET /analytics/most-productive-haters` — counts `star_rating IN (1, 2)` reviews.

### `customer_backer_monthly`
```
PRIMARY KEY ((year, month), review_count, customer_id)
CLUSTERING ORDER BY (review_count DESC, customer_id ASC)
```
Serves:
- `GET /analytics/most-productive-backers` — counts `star_rating IN (4, 5)` reviews.

---

## Trade-offs

| Query | Cassandra calls | Reason |
|---|---|---|
| By product / customer | 1 partition read | Partition key is the filter |
| Analytics (date range) | 1 per month in range | Partition by (year, month) avoids ALLOW FILTERING; aggregation happens in Python |

---

## Quick Start

### 1. Prerequisites

Java 17 (for PySpark):
```bash
brew install openjdk@17
export JAVA_HOME=$(brew --prefix openjdk@17)
```

Python dependencies (ETL):
```bash
pip install -r hw7/requirements.txt
```

### 2. Start infrastructure + API

```bash
cd hw7
docker compose up -d
docker compose ps   # cassandra should be healthy (~90 s)
```

### 3. Run the ETL

```bash
python hw7/etl.py
```

Expected output:
```
Connecting to Cassandra...
Schema ready.
Starting Spark...
Loading .../amazon_reviews.csv...
  Raw rows: 396,000
  Clean rows: <N>
Writing reviews_by_product...
  [reviews_by_product] <N> rows  (0 errors)
Writing reviews_by_customer...
  [reviews_by_customer] <N> rows  (0 errors)
Writing product_monthly_counts...
  [product_monthly_counts] <N> rows  (0 errors)
...
ETL complete.
```

### 4. Use the API

Interactive docs: http://localhost:8000/docs

---

## Endpoints

| Method | Path | Description |
|---|---|---|
| GET | `/products/{product_id}/reviews` | All reviews for a product |
| GET | `/products/{product_id}/reviews?star_rating=5` | Reviews filtered by rating |
| GET | `/customers/{customer_id}/reviews` | All reviews by a customer |
| GET | `/analytics/most-reviewed?start_date=2015-01-01&end_date=2015-12-31&n=10` | Top N most reviewed products |
| GET | `/analytics/most-productive-customers?start_date=...&end_date=...&n=10` | Top N by verified review count |
| GET | `/analytics/most-productive-haters?start_date=...&end_date=...&n=10` | Top N by 1-2-star count |
| GET | `/analytics/most-productive-backers?start_date=...&end_date=...&n=10` | Top N by 4-5-star count |

All responses are cached in Redis for 5 minutes.

---

## Example curl calls

```bash
# Reviews for a product
curl "http://localhost:8000/products/0385730586/reviews"

# 5-star reviews only
curl "http://localhost:8000/products/0385730586/reviews?star_rating=5"

# Reviews by a customer
curl "http://localhost:8000/customers/12076615/reviews"

# Top 5 most reviewed in 2015
curl "http://localhost:8000/analytics/most-reviewed?start_date=2015-01-01&end_date=2015-12-31&n=5"

# Top 10 most productive customers all time
curl "http://localhost:8000/analytics/most-productive-customers?start_date=2000-01-01&end_date=2030-12-31&n=10"

# Top 5 haters in Q1 2015
curl "http://localhost:8000/analytics/most-productive-haters?start_date=2015-01-01&end_date=2015-03-31&n=5"

# Top 5 backers in Q1 2015
curl "http://localhost:8000/analytics/most-productive-backers?start_date=2015-01-01&end_date=2015-03-31&n=5"
```