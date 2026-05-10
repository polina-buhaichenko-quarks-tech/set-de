"""
MySQL connection pool and query functions for the three API endpoints.

The pool is created lazily so the module can be imported without a live
database connection.
"""
import os
from datetime import date, datetime
from decimal import Decimal

import mysql.connector
from mysql.connector import pooling

_pool: pooling.MySQLConnectionPool | None = None


def _get_pool() -> pooling.MySQLConnectionPool:
    global _pool
    if _pool is None:
        _pool = pooling.MySQLConnectionPool(
            pool_name="hw5",
            pool_size=10,
            host=os.getenv("DB_HOST", "localhost"),
            port=int(os.getenv("DB_PORT", 3306)),
            database=os.getenv("DB_NAME", "ad_analytics"),
            user=os.getenv("DB_USER", "polinus"),
            password=os.getenv("DB_PASSWORD", "adpass"),
        )
    return _pool


def _conn():
    return _get_pool().get_connection()


# Converts MySQL types that aren't JSON-serialisable to Python primitives.
def _jsonify(v):
    if isinstance(v, Decimal):
        return float(v)
    if isinstance(v, (datetime, date)):
        return v.isoformat()
    return v


def _serialize(row: dict) -> dict:
    return {k: _jsonify(v) for k, v in row.items()}


# ── endpoint queries ──────────────────────────────────────────────────────────

def get_campaign_performance(campaign_id: int) -> dict | None:
    """
    Returns CTR, clicks, impressions, and ad spend for one campaign.
    Returns None if campaign_id does not exist.
    """
    conn = _conn()
    try:
        cur = conn.cursor(dictionary=True)
        cur.execute(
            """
            SELECT
                c.campaign_id,
                c.campaign_name,
                COUNT(e.event_id)                                      AS impressions,
                COALESCE(SUM(e.was_clicked), 0)                        AS clicks,
                ROUND(
                    COALESCE(SUM(e.was_clicked), 0) /
                    NULLIF(COUNT(e.event_id), 0),
                4)                                                     AS ctr,
                ROUND(COALESCE(SUM(e.ad_cost), 0), 2)                 AS total_ad_spend
            FROM campaigns c
            LEFT JOIN ad_events e ON e.campaign_id = c.campaign_id
            WHERE c.campaign_id = %s
            GROUP BY c.campaign_id, c.campaign_name
            """,
            (campaign_id,),
        )
        row = cur.fetchone()
        cur.close()
        return _serialize(row) if row else None
    finally:
        conn.close()


def get_advertiser_spending(advertiser_id: int) -> dict | None:
    """
    Returns total ad spend, impressions, clicks, and revenue for one advertiser.
    Returns None if advertiser_id does not exist.
    """
    conn = _conn()
    try:
        cur = conn.cursor(dictionary=True)
        cur.execute(
            """
            SELECT
                a.advertiser_id,
                a.name                                                 AS advertiser_name,
                ROUND(COALESCE(SUM(e.ad_cost), 0), 2)                 AS total_ad_spend,
                COUNT(e.event_id)                                      AS total_impressions,
                COALESCE(SUM(e.was_clicked), 0)                       AS total_clicks,
                ROUND(COALESCE(SUM(e.ad_revenue), 0), 2)              AS total_ad_revenue
            FROM advertisers a
            LEFT JOIN campaigns c ON c.advertiser_id = a.advertiser_id
            LEFT JOIN ad_events e ON e.campaign_id   = c.campaign_id
            WHERE a.advertiser_id = %s
            GROUP BY a.advertiser_id, a.name
            """,
            (advertiser_id,),
        )
        row = cur.fetchone()
        cur.close()
        return _serialize(row) if row else None
    finally:
        conn.close()


def get_user_engagements(user_id: int) -> dict | None:
    """
    Returns the 50 most recent ad events for a user (both impressions and clicks).
    Returns None if the user does not exist in the users table.
    """
    conn = _conn()
    try:
        cur = conn.cursor(dictionary=True)

        # Check user existence before the heavier join query.
        cur.execute("SELECT user_id FROM users WHERE user_id = %s", (user_id,))
        if cur.fetchone() is None:
            cur.close()
            return None

        cur.execute(
            """
            SELECT
                e.event_id,
                c.campaign_name,
                a.name                         AS advertiser_name,
                e.timestamp,
                e.was_clicked,
                e.click_timestamp,
                ROUND(e.ad_cost, 2)            AS ad_cost,
                ROUND(e.ad_revenue, 2)         AS ad_revenue
            FROM ad_events e
            JOIN campaigns   c ON c.campaign_id   = e.campaign_id
            JOIN advertisers a ON a.advertiser_id = c.advertiser_id
            WHERE e.user_id = %s
            ORDER BY e.timestamp DESC
            LIMIT 50
            """,
            (user_id,),
        )
        rows = cur.fetchall()
        cur.close()
        return {
            "user_id": user_id,
            "count": len(rows),
            "engagements": [_serialize(r) for r in rows],
        }
    finally:
        conn.close()