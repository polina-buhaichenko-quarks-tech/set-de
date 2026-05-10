# HW6 — Amazon Reviews ETL with PySpark + MongoDB

PySpark ingestion, cleaning, and aggregation of the Amazon reviews dataset, with results stored in MongoDB for efficient querying.

---

## File overview

| File | Purpose |
|---|---|
| `etl.py` | PySpark script — ingest, clean, aggregate, write to MongoDB |
| `queries.py` | Demo queries against the three MongoDB collections |
| `docker-compose.yml` | MongoDB 7 + mongo-express (web UI) |
| `requirements.txt` | Python dependencies |

---

## Prerequisites

PySpark requires a JVM. Install Java 17 if not already present:

```bash
brew install openjdk@17
export JAVA_HOME=$(brew --prefix openjdk@17)
```

Install Python dependencies:

```bash
pip install -r requirements.txt
```

---

## Quick start

### 1. Start MongoDB

```bash
cd hw6
docker compose up -d
docker compose ps          # mongo should be "healthy"
```

Mongo Express UI (optional): http://localhost:8081

### 2. Run the ETL

```bash
python etl.py
```

Expected output:

```
Loading CSV...
  Raw rows: 396,000
Cleaning...
  Verified-purchase rows: <N>
Writing to MongoDB...
  [product_stats] X,XXX documents written
  [customer_stats] X,XXX documents written
  [monthly_product_reviews] X,XXX documents written
ETL complete.
```

### 3. Run the demo queries

```bash
python queries.py
```

---

## Pipeline

```
amazon_reviews.csv
       │
       ▼
  Spark DataFrame
       │  dropna(review_id, product_id, star_rating, review_date)
       │  review_date → DateType
       │  filter verified_purchase == 1
       ▼
  Cleaned DataFrame (cached)
       │
       ├──► groupBy product_id        → product_stats
       ├──► groupBy customer_id       → customer_stats
       └──► groupBy product, year, month → monthly_product_reviews
                                              │
                                              ▼
                                         MongoDB
```

---

## MongoDB collections

### `product_stats`
One document per product. Index on `product_id`.

```json
{
  "product_id": "0385730586",
  "product_title": "Sisterhood of the Traveling Pants",
  "total_reviews": 142,
  "avg_star_rating": 4.31
}
```

Use case: quickly retrieve review count and average rating for any product.

### `customer_stats`
One document per customer. Index on `customer_id`.

```json
{
  "customer_id": 12076615,
  "total_verified_reviews": 7
}
```

Use case: efficiently query how many verified reviews a customer has submitted.

### `monthly_product_reviews`
One document per (product, year, month). Compound index on `(product_id, year, month)`.

```json
{
  "product_id": "0385730586",
  "year": 2015,
  "month": 3,
  "review_count": 14
}
```

Use case: trend analysis — monthly review volume per product.

---

## Example mongosh queries

```js
// connect
mongosh mongodb://localhost:27017/amazon_reviews

// top 5 products by review count
db.product_stats.find({}, {_id:0}).sort({total_reviews:-1}).limit(5)

// highly rated products (avg >= 4.5, at least 20 reviews)
db.product_stats.find(
  {avg_star_rating:{$gte:4.5}, total_reviews:{$gte:20}},
  {_id:0}
).sort({avg_star_rating:-1}).limit(5)

// top 5 customers by verified reviews
db.customer_stats.find({}, {_id:0}).sort({total_verified_reviews:-1}).limit(5)

// monthly trend for a specific product
db.monthly_product_reviews.find(
  {product_id:"0385730586"},
  {_id:0}
).sort({year:1, month:1})

// total reviews per month across all products
db.monthly_product_reviews.aggregate([
  {$group:{_id:{year:"$year",month:"$month"}, total:{$sum:"$review_count"}}},
  {$sort:{"_id.year":1,"_id.month":1}}
])
```