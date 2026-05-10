
# HW5 — REST API with Redis Caching

FastAPI + MySQL + Redis read-through cache for the Ad Analytics dataset.

---

## File overview

| File | Purpose |
|---|---|
| `main.py` | FastAPI app — three endpoints |
| `db.py` | MySQL connection pool + query functions |
| `cache.py` | Redis helpers (get / set with TTL) |
| `seed.py` | Loads a sample from the CSVs into MySQL |
| `benchmark.py` | Measures cache-hit vs DB-only latency |
| `init.sql` | MySQL schema (runs automatically in Docker) |
| `docker-compose.yml` | MySQL 8 + Redis 7 + FastAPI container |
| `Dockerfile` | FastAPI container image |
| `.env` | Local dev settings (host ports) |

---

## Quick start

### 1. Start services
```bash
cd hw5
docker compose up --build -d
```
MySQL takes ~20 s to initialise on first run. Check health:
```bash
docker compose ps          # all three should be "healthy" / "running"
```

### 2. Seed the database
```bash
pip install mysql-connector-python pandas python-dotenv
python seed.py             # loads 100 000 ad events (≈ 30 s)
```
To load a different number of rows: `SEED_ROWS=50000 python seed.py`

### 3. Test the API
Swagger UI: http://localhost:8000/docs

```bash
curl http://localhost:8000/campaign/1/performance
curl http://localhost:8000/advertiser/1/spending
curl http://localhost:8000/user/100/engagements
```

Add `?no_cache=true` to bypass Redis and always hit MySQL:
```bash
curl "http://localhost:8000/campaign/1/performance?no_cache=true"
```

Every response includes a `"cache": "hit"` or `"cache": "miss"` field so you can see which path was taken.

### 4. Run the benchmark
```bash
pip install requests
python benchmark.py
```

Edit `CAMPAIGN_ID`, `ADVERTISER_ID`, `USER_ID` at the top of `benchmark.py`
to IDs that exist in your seeded data (use `/docs` or the MySQL shell to find valid IDs).

---

## Endpoints

### `GET /campaign/{campaign_id}/performance`
Returns CTR, total clicks, impressions, and ad spend.
**Cache TTL: 30 seconds.**

```json
{
  "campaign_id": 1,
  "campaign_name": "Campaign_278",
  "impressions": 48231,
  "clicks": 9647,
  "ctr": 0.1999,
  "total_ad_spend": 14307.45,
  "cache": "hit"
}
```

### `GET /advertiser/{advertiser_id}/spending`
Returns total ad spend, impressions, clicks, and revenue.
**Cache TTL: 5 minutes.**

```json
{
  "advertiser_id": 1,
  "advertiser_name": "Advertiser_12",
  "total_ad_spend": 82104.90,
  "total_impressions": 214000,
  "total_clicks": 42700,
  "total_ad_revenue": 91230.00,
  "cache": "miss"
}
```

### `GET /user/{user_id}/engagements`
Returns the 50 most recent ad events for a user.
**Cache TTL: 60 seconds.**

```json
{
  "user_id": 100,
  "count": 12,
  "engagements": [
    {
      "event_id": "abc123...",
      "campaign_name": "Campaign_45",
      "advertiser_name": "Advertiser_3",
      "timestamp": "2024-11-01T14:22:00",
      "was_clicked": 1,
      "click_timestamp": "2024-11-01T14:22:05",
      "ad_cost": 0.42,
      "ad_revenue": 0.55
    }
  ],
  "cache": "hit"
}
```

---

## How caching works

```
Client → FastAPI
            ↓
        Redis.GET(key)
         hit ↓        miss ↓
        return        MySQL query
        cached    →   Redis.SETEX(key, TTL, data)
        data          return data
```

TTL values:
- Campaign performance: **30 s** (changes frequently during live campaigns)
- Advertiser spending: **5 min** (slower-moving aggregate)
- User engagements: **60 s**

---

## Benchmark results (example)

```
+---------------------------+-------------+------------+------------+------------+
| Endpoint                  | Type        |    Mean ms |     Min ms |     Max ms |
+---------------------------+-------------+------------+------------+------------+
| Campaign Performance      | Cache hit   |       2.14 |       1.87 |       3.42 |
| Campaign Performance      | DB only     |      38.91 |      36.20 |      48.73 |
+---------------------------+-------------+------------+------------+------------+
| Advertiser Spending       | Cache hit   |       1.98 |       1.71 |       2.95 |
| Advertiser Spending       | DB only     |      52.44 |      49.08 |      64.21 |
+---------------------------+-------------+------------+------------+------------+
| User Engagements          | Cache hit   |       2.31 |       2.05 |       3.18 |
| User Engagements          | DB only     |      44.67 |      42.11 |      55.90 |
+---------------------------+-------------+------------+------------+------------+

Speedup  (DB only mean / Cache hit mean):
  Campaign Performance        18.2×
  Advertiser Spending         26.5×
  User Engagements            19.3×
```

*(Actual numbers will vary by machine and dataset size.)*