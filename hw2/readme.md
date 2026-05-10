# Homework 2 – AdTech SQL Analytics

Analytical SQL queries on the normalised AdTech schema from Homework 1, plus a Python report generator.

## Files

| File | Purpose |
|---|---|
| `docker-compose.yml` | Spins up MySQL 8.0 with the schema pre-loaded |
| `init.sql` | Fixed schema (DDL) + performance indexes |
| `queries.sql` | Seven standalone analytical SQL queries |
| `report.py` | Connects to MySQL, runs all queries, writes CSV + JSON |
| `.env.example` | Environment variable template |

## Setup

### 1. Start MySQL

```bash
cd hw2
docker-compose up -d
# wait ~30 s for the health-check to pass
docker-compose ps
```

### 2. Load data (ETL from Homework 1)

```bash
cd ../hw1
cp ../.env.example .env   # or reuse your existing .env
python main.py \
  --events    "../data/(USE THIS)ad_events_header_updated(2).csv" \
  --campaigns "../data/campaigns.csv" \
  --users     "../data/users.csv"
```

### 3. Run the report

```bash
cd ../hw2
cp .env.example .env      # edit if your credentials differ
pip install -r ../requirements.txt

python report.py                          # defaults: Oct 2024, ./results
python report.py --start 2024-10-01 --end 2024-10-31 --output-dir results
```

Results land in `results/`:
- `q1_top_campaigns_by_ctr.csv` … `q7_ctr_by_device.csv`
- `report.json` — full manifest with all rows

## Queries

| # | Question | Analysis window |
|---|---|---|
| Q1 | Top 5 campaigns by CTR | 30-day |
| Q2 | Advertisers by total spend | 30-day |
| Q3 | CPC and CPM per campaign | 30-day |
| Q4 | Top locations by click revenue | 30-day |
| Q5 | Top 10 most engaged users | 30-day |
| Q6 | Campaigns with >80 % budget consumed | All-time |
| Q7 | CTR by device type (mobile/desktop/tablet) | 30-day |

## Performance indexes

Six composite indexes are created on `ad_events` at schema init time:

| Index | Covers |
|---|---|
| `idx_ae_campaign_ts` | Q1, Q3 – campaign + time range scan |
| `idx_ae_ts` | Q2 – time-only range scan |
| `idx_ae_clicked_ts_loc` | Q4 – clicked events by location |
| `idx_ae_clicked_ts_usr` | Q5 – clicked events by user |
| `idx_ae_device_ts` | Q7 – device + time range scan |
| `idx_camp_advertiser` | Q2 – campaigns → advertisers join |