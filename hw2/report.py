"""
AdTech campaign-performance report generator.

Connects to MySQL, runs seven analytical queries against the normalised schema,
and writes results to CSV files (one per query) plus a summary JSON manifest.

Usage:
    python report.py [--output-dir results] [--start 2024-10-01] [--end 2024-10-31]
"""

import csv
import json
import os
import argparse
from datetime import date, timedelta, datetime
from pathlib import Path

import mysql.connector
from dotenv import load_dotenv

load_dotenv()

# ── query catalogue ───────────────────────────────────────────────────────────
# Each entry holds:
#   title   – human-readable label for the report
#   sql     – parameterised query (%s placeholders)
#   params  – callable (start: str, end_excl: str) → tuple of bind values
#             end_excl is the day AFTER the desired end date (exclusive upper bound)

QUERIES: dict[str, dict] = {
    "q1_top_campaigns_by_ctr": {
        "title": "Top 5 Campaigns by Click-Through Rate",
        "sql": """
            SELECT
                c.campaign_name,
                a.name                                                AS advertiser,
                COUNT(*)                                              AS impressions,
                SUM(ae.was_clicked)                                   AS clicks,
                ROUND(100.0 * SUM(ae.was_clicked) / COUNT(*), 4)     AS ctr_pct
            FROM      ad_events   ae
            JOIN      campaigns   c  ON ae.campaign_id  = c.campaign_id
            JOIN      advertisers a  ON c.advertiser_id = a.advertiser_id
            WHERE     ae.timestamp >= %s
                  AND ae.timestamp  < %s
            GROUP BY  c.campaign_id, c.campaign_name, a.name
            HAVING    COUNT(*) >= 100
            ORDER BY  ctr_pct DESC
            LIMIT 5
        """,
        "params": lambda s, e: (s, e),
    },
    "q2_advertiser_spending": {
        "title": "Top 10 Advertisers by Ad Spend",
        "sql": """
            SELECT
                a.name                                                AS advertiser,
                COUNT(*)                                              AS impressions,
                SUM(ae.was_clicked)                                   AS total_clicks,
                ROUND(SUM(ae.ad_cost), 2)                             AS total_spend,
                ROUND(100.0 * SUM(ae.was_clicked) / COUNT(*), 4)     AS ctr_pct
            FROM      ad_events   ae
            JOIN      campaigns   c  ON ae.campaign_id  = c.campaign_id
            JOIN      advertisers a  ON c.advertiser_id = a.advertiser_id
            WHERE     ae.timestamp >= %s
                  AND ae.timestamp  < %s
            GROUP BY  a.advertiser_id, a.name
            ORDER BY  total_spend DESC
            LIMIT 10
        """,
        "params": lambda s, e: (s, e),
    },
    "q3_campaign_cpc_cpm": {
        "title": "Cost Per Click (CPC) and Cost Per Mille (CPM) per Campaign",
        "sql": """
            SELECT
                c.campaign_name,
                a.name                                                                AS advertiser,
                COUNT(*)                                                              AS impressions,
                SUM(ae.was_clicked)                                                   AS clicks,
                ROUND(SUM(ae.ad_cost), 2)                                             AS total_cost,
                ROUND(SUM(ae.ad_cost) / NULLIF(SUM(ae.was_clicked), 0), 4)           AS cpc,
                ROUND(1000.0 * SUM(ae.ad_cost) / COUNT(*), 4)                        AS cpm
            FROM      ad_events   ae
            JOIN      campaigns   c  ON ae.campaign_id  = c.campaign_id
            JOIN      advertisers a  ON c.advertiser_id = a.advertiser_id
            WHERE     ae.timestamp >= %s
                  AND ae.timestamp  < %s
            GROUP BY  c.campaign_id, c.campaign_name, a.name
            ORDER BY  cpc ASC
        """,
        "params": lambda s, e: (s, e),
    },
    "q4_top_locations_by_revenue": {
        "title": "Top 10 Locations by Ad Revenue (Clicks Only)",
        "sql": """
            SELECT
                l.country_name                    AS location,
                COUNT(*)                          AS click_events,
                ROUND(SUM(ae.ad_revenue), 2)      AS total_revenue
            FROM      ad_events ae
            JOIN      locations l  ON ae.location_id = l.country_id
            WHERE     ae.timestamp  >= %s
                  AND ae.timestamp   < %s
                  AND ae.was_clicked  = TRUE
            GROUP BY  l.country_id, l.country_name
            ORDER BY  total_revenue DESC
            LIMIT 10
        """,
        "params": lambda s, e: (s, e),
    },
    "q5_top_engaged_users": {
        "title": "Top 10 Most Engaged Users by Click Count",
        "sql": """
            SELECT
                u.user_id,
                u.age,
                u.gender,
                l.country_name                    AS country,
                COUNT(*)                          AS total_clicks
            FROM      ad_events  ae
            JOIN      users      u  ON ae.user_id    = u.user_id
            LEFT JOIN locations  l  ON u.country_id  = l.country_id
            WHERE     ae.timestamp  >= %s
                  AND ae.timestamp   < %s
                  AND ae.was_clicked  = TRUE
            GROUP BY  u.user_id, u.age, u.gender, l.country_name
            ORDER BY  total_clicks DESC
            LIMIT 10
        """,
        "params": lambda s, e: (s, e),
    },
    "q6_near_budget_exhaustion": {
        "title": "Campaigns with >80% Budget Consumed (All-Time)",
        "sql": """
            SELECT
                c.campaign_name,
                a.name                                                            AS advertiser,
                c.budget                                                          AS total_budget,
                ROUND(SUM(ae.ad_cost), 2)                                         AS total_spent,
                ROUND(100.0 * SUM(ae.ad_cost) / NULLIF(c.budget, 0), 2)          AS pct_budget_spent
            FROM      campaigns   c
            JOIN      advertisers a   ON c.advertiser_id = a.advertiser_id
            LEFT JOIN ad_events   ae  ON ae.campaign_id  = c.campaign_id
            WHERE     c.budget > 0
            GROUP BY  c.campaign_id, c.campaign_name, a.name, c.budget
            HAVING    pct_budget_spent > 80
            ORDER BY  pct_budget_spent DESC
        """,
        "params": lambda s, e: (),  # all-time — no date filter
    },
    "q7_ctr_by_device": {
        "title": "Click-Through Rate by Device Type",
        "sql": """
            SELECT
                d.device_name,
                COUNT(*)                                              AS impressions,
                SUM(ae.was_clicked)                                   AS clicks,
                ROUND(100.0 * SUM(ae.was_clicked) / COUNT(*), 4)     AS ctr_pct
            FROM      ad_events ae
            JOIN      devices   d   ON ae.device_id = d.device_id
            WHERE     ae.timestamp >= %s
                  AND ae.timestamp  < %s
            GROUP BY  d.device_id, d.device_name
            ORDER BY  ctr_pct DESC
        """,
        "params": lambda s, e: (s, e),
    },
}


# ── helpers ───────────────────────────────────────────────────────────────────

def get_connection():
    return mysql.connector.connect(
        host=os.getenv("DB_HOST", "localhost"),
        port=int(os.getenv("DB_PORT", 3306)),
        database=os.getenv("DB_NAME", "polinus_db"),
        user=os.getenv("DB_USER", "polinus"),
        password=os.getenv("DB_PASSWORD", "adpassword"),
    )


def run_query(cursor, sql: str, params: tuple) -> tuple[list[str], list[tuple]]:
    cursor.execute(sql, params)
    columns = [d[0] for d in cursor.description]
    rows = cursor.fetchall()
    return columns, rows


def write_csv(path: Path, columns: list[str], rows: list[tuple]) -> None:
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(columns)
        writer.writerows(rows)


def rows_to_dicts(columns: list[str], rows: list[tuple]) -> list[dict]:
    return [
        {col: (val.isoformat() if isinstance(val, (date, datetime)) else val)
         for col, val in zip(columns, row)}
        for row in rows
    ]


# ── main ──────────────────────────────────────────────────────────────────────

def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="AdTech campaign-performance report")
    p.add_argument("--start",      default="2024-10-01", help="Analysis window start (YYYY-MM-DD)")
    p.add_argument("--end",        default="2024-10-31", help="Analysis window end, inclusive (YYYY-MM-DD)")
    p.add_argument("--output-dir", default="results",   help="Directory for output files")
    return p.parse_args()


def main() -> None:
    args = parse_args()

    start_date = args.start
    # Make the upper bound exclusive (timestamps use < instead of <=)
    end_excl = (date.fromisoformat(args.end) + timedelta(days=1)).isoformat()

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    print(f"Analysis window : {start_date} – {args.end}")
    print(f"Output directory: {output_dir.resolve()}\n")

    conn = get_connection()
    cursor = conn.cursor()

    manifest = {
        "generated_at": datetime.utcnow().isoformat() + "Z",
        "analysis_window": {"start": start_date, "end": args.end},
        "queries": {},
    }

    try:
        for key, meta in QUERIES.items():
            params = meta["params"](start_date, end_excl)
            print(f"  Running {key} …", end=" ", flush=True)
            columns, rows = run_query(cursor, meta["sql"], params)

            csv_path = output_dir / f"{key}.csv"
            write_csv(csv_path, columns, rows)

            manifest["queries"][key] = {
                "title":    meta["title"],
                "csv_file": str(csv_path),
                "columns":  columns,
                "row_count": len(rows),
                "rows":     rows_to_dicts(columns, rows),
            }

            print(f"{len(rows)} rows  →  {csv_path}")

    finally:
        cursor.close()
        conn.close()

    manifest_path = output_dir / "report.json"
    with open(manifest_path, "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2, default=str)

    print(f"\nManifest written to {manifest_path}")


if __name__ == "__main__":
    main()