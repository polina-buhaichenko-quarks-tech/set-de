#!/usr/bin/env python3
"""
ETL: extract ad analytics CSVs and load into Cassandra.

Tables populated:
  1. campaign_performance_by_day          (aggregated from ad_events)
  2. top_advertisers_by_spend             (aggregated from ad_events)
  3. user_engagement_history              (raw rows from ad_events)
  4. most_active_users                    (aggregated from ad_events)
  5. high_spending_advertisers_by_region  (aggregated from ad_events)

users.csv and campaigns.csv are fully denormalized into ad_events already,
so only ad_events is needed for the five target tables.
"""

import os
import uuid
import logging
from collections import defaultdict
from datetime import datetime, timezone

import pandas as pd
from cassandra.cluster import Cluster
from cassandra.concurrent import execute_concurrent_with_args

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
)
log = logging.getLogger(__name__)

# ── paths ─────────────────────────────────────────────────────────────────────
BASE_DIR     = os.path.dirname(os.path.abspath(__file__))
DATA_DIR     = os.path.join(BASE_DIR, "..", "data")
AD_EVENTS_CSV = os.path.join(DATA_DIR, "(USE THIS)ad_events_header_updated(2).csv")

# ── settings ──────────────────────────────────────────────────────────────────
CASSANDRA_HOSTS = ["127.0.0.1"]
KEYSPACE        = "ad_analytics"
CHUNK_SIZE      = 100_000   # rows read from CSV at a time
CONCURRENCY     = 500       # parallel in-flight Cassandra requests


# ── connection ────────────────────────────────────────────────────────────────
def connect():
    cluster = Cluster(CASSANDRA_HOSTS)
    session = cluster.connect(KEYSPACE)
    session.default_timeout = 120
    return cluster, session


def prepare_statements(session):
    return {
        "campaign_perf": session.prepare(
            """INSERT INTO campaign_performance_by_day
               (campaign_name, event_date, total_impressions, total_clicks,
                ctr, total_ad_cost, total_ad_revenue, last_updated)
               VALUES (?, ?, ?, ?, ?, ?, ?)"""
        ),
        "top_advertisers": session.prepare(
            """INSERT INTO advertiser_spend_by_day
               (advertiser_name, event_date, total_spend,
                total_impressions, total_clicks, total_revenue)
               VALUES (?, ?, ?, ?, ?, ?)"""
        ),
        "user_history": session.prepare(
            """INSERT INTO user_engagement_history
               (user_id, event_timestamp, event_id, campaign_name,
                advertiser_name, ad_slot_size, device, location,
                was_clicked, click_timestamp, ad_cost, ad_revenue)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)"""
        ),
        "active_users": session.prepare(
            """INSERT INTO most_active_users
               (activity_bucket, total_interactions, user_id,
                total_impressions, total_clicks)
               VALUES (?, ?, ?, ?, ?)"""
        ),
        "region_spend": session.prepare(
            """INSERT INTO high_spending_advertisers_by_region
               (region, total_spend, advertiser_name,
                total_impressions, total_clicks, total_revenue)
               VALUES (?, ?, ?, ?, ?, ?)"""
        ),
    }


# ── helpers ───────────────────────────────────────────────────────────────────
def _zero_agg():
    return {"impressions": 0, "clicks": 0, "spend": 0.0, "revenue": 0.0}


def _accumulate(target, key, impressions, clicks, spend, revenue):
    entry = target[key]
    entry["impressions"] += impressions
    entry["clicks"]      += clicks
    entry["spend"]       += spend
    entry["revenue"]     += revenue


def _parse_uuid(value):
    try:
        return uuid.UUID(str(value))
    except (ValueError, AttributeError):
        return uuid.uuid4()


# ── single-pass ETL over ad_events ───────────────────────────────────────────
def process_ad_events(session, stmts):
    """
    Reads ad_events in chunks.
    - Streams rows into user_engagement_history after each chunk.
    - Accumulates aggregates for the other four tables in memory.
    """
    campaign_day = defaultdict(_zero_agg)   # (campaign_name, date)      → agg
    advertiser   = defaultdict(_zero_agg)   # (advertiser_name, date)    → agg
    user_act     = defaultdict(_zero_agg)   # user_id                    → agg
    region_adv   = defaultdict(_zero_agg)   # (region, advertiser)       → agg

    total_rows = 0

    for chunk_num, chunk in enumerate(
        pd.read_csv(AD_EVENTS_CSV, chunksize=CHUNK_SIZE, low_memory=False)
    ):
        # ── normalise columns ─────────────────────────────────────────────
        chunk["Timestamp"]  = pd.to_datetime(chunk["Timestamp"],  errors="coerce")
        chunk["ClickTimestamp"] = pd.to_datetime(chunk["ClickTimestamp"], errors="coerce")
        chunk["WasClicked"] = chunk["WasClicked"].astype(str).str.strip().str.lower() == "true"
        chunk["AdCost"]     = pd.to_numeric(chunk["AdCost"],    errors="coerce").fillna(0.0)
        chunk["AdRevenue"]  = pd.to_numeric(chunk["AdRevenue"], errors="coerce").fillna(0.0)
        chunk["AdvertiserName"]            = chunk["AdvertiserName"].astype(str).str.strip()
        chunk["CampaignName"]              = chunk["CampaignName"].astype(str).str.strip()
        chunk["CampaignTargetingCountry"]  = chunk["CampaignTargetingCountry"].astype(str).str.strip()
        chunk["Location"]   = chunk["Location"].astype(str).str.strip()
        chunk["Device"]     = chunk["Device"].astype(str).str.strip()
        chunk["AdSlotSize"] = chunk["AdSlotSize"].astype(str).str.strip()
        chunk["event_date"] = chunk["Timestamp"].dt.date

        # ── table 1: campaign × day ───────────────────────────────────────
        grp1 = chunk.groupby(["CampaignName", "event_date"], dropna=True).agg(
            impressions=("EventID",    "count"),
            clicks     =("WasClicked", "sum"),
            spend      =("AdCost",     "sum"),
            revenue    =("AdRevenue",  "sum"),
        )
        for (campaign, ev_date), row in grp1.iterrows():
            _accumulate(campaign_day, (campaign, ev_date),
                        int(row.impressions), int(row.clicks),
                        float(row.spend),     float(row.revenue))

        # ── table 2: advertiser spend per day ────────────────────────────
        grp2 = chunk.groupby(["AdvertiserName", "event_date"], dropna=True).agg(
            impressions=("EventID",    "count"),
            clicks     =("WasClicked", "sum"),
            spend      =("AdCost",     "sum"),
            revenue    =("AdRevenue",  "sum"),
        )
        for (adv_name, ev_date), row in grp2.iterrows():
            _accumulate(advertiser, (adv_name, ev_date),
                        int(row.impressions), int(row.clicks),
                        float(row.spend),     float(row.revenue))

        # ── table 4: user activity ────────────────────────────────────────
        grp4 = chunk.groupby("UserID").agg(
            impressions=("EventID",    "count"),
            clicks     =("WasClicked", "sum"),
        )
        for user_id, row in grp4.iterrows():
            _accumulate(user_act, int(user_id),
                        int(row.impressions), int(row.clicks), 0.0, 0.0)

        # ── table 5: region × advertiser spend ────────────────────────────
        grp5 = chunk.groupby(["CampaignTargetingCountry", "AdvertiserName"]).agg(
            impressions=("EventID",    "count"),
            clicks     =("WasClicked", "sum"),
            spend      =("AdCost",     "sum"),
            revenue    =("AdRevenue",  "sum"),
        )
        for (region, adv_name), row in grp5.iterrows():
            _accumulate(region_adv, (region, adv_name),
                        int(row.impressions), int(row.clicks),
                        float(row.spend),     float(row.revenue))

        # ── table 3: raw engagement history — flush each chunk ────────────
        valid = chunk[chunk["Timestamp"].notna()]
        user_history_params = [
            (
                int(r.UserID),
                r.Timestamp.to_pydatetime(),
                _parse_uuid(r.EventID),
                r.CampaignName,
                r.AdvertiserName,
                r.AdSlotSize,
                r.Device,
                r.Location,
                bool(r.WasClicked),
                r.ClickTimestamp.to_pydatetime() if pd.notna(r.ClickTimestamp) else None,
                float(r.AdCost),
                float(r.AdRevenue),
            )
            for r in valid.itertuples(index=False)
        ]
        if user_history_params:
            execute_concurrent_with_args(
                session, stmts["user_history"],
                user_history_params,
                concurrency=CONCURRENCY,
                raise_on_first_error=False,
            )

        total_rows += len(chunk)
        log.info("chunk %d done — %d rows processed so far", chunk_num + 1, total_rows)

    return campaign_day, advertiser, user_act, region_adv


# ── insert aggregated tables ──────────────────────────────────────────────────
def insert_campaign_performance(session, stmt, campaign_day):
    log.info("inserting campaign_performance_by_day (%d rows) …", len(campaign_day))
    params = []
    for (campaign, ev_date), agg in campaign_day.items():
        imp    = agg["impressions"]
        clicks = agg["clicks"]
        ctr    = round(clicks / imp, 6) if imp else 0.0
        params.append((campaign, ev_date, imp, clicks, ctr,
                        agg["spend"], agg["revenue"]))
    execute_concurrent_with_args(session, stmt, params, concurrency=CONCURRENCY)
    log.info("campaign_performance_by_day — done.")


def insert_top_advertisers(session, stmt, advertiser):
    log.info("inserting advertiser_spend_by_day (%d rows) …", len(advertiser))
    params = [
        (adv_name, ev_date, agg["spend"],
         agg["impressions"], agg["clicks"], agg["revenue"])
        for (adv_name, ev_date), agg in advertiser.items()
    ]
    execute_concurrent_with_args(session, stmt, params, concurrency=CONCURRENCY)
    log.info("advertiser_spend_by_day — done.")


def insert_most_active_users(session, stmt, user_act):
    log.info("inserting most_active_users (%d rows) …", len(user_act))
    params = [
        ("global",
         agg["impressions"] + agg["clicks"],
         uid,
         agg["impressions"],
         agg["clicks"])
        for uid, agg in user_act.items()
    ]
    execute_concurrent_with_args(session, stmt, params, concurrency=CONCURRENCY)
    log.info("most_active_users — done.")


def insert_region_spend(session, stmt, region_adv):
    log.info("inserting high_spending_advertisers_by_region (%d rows) …", len(region_adv))
    params = [
        (region, agg["spend"], adv,
         agg["impressions"], agg["clicks"], agg["revenue"])
        for (region, adv), agg in region_adv.items()
    ]
    execute_concurrent_with_args(session, stmt, params, concurrency=CONCURRENCY)
    log.info("high_spending_advertisers_by_region — done.")


# ── entry point ───────────────────────────────────────────────────────────────
def main():
    log.info("connecting to Cassandra at %s …", CASSANDRA_HOSTS)
    cluster, session = connect()
    stmts = prepare_statements(session)

    log.info("starting single-pass ETL over ad_events …")
    campaign_day, advertiser, user_act, region_adv = process_ad_events(session, stmts)

    insert_campaign_performance(session, stmts["campaign_perf"],   campaign_day)
    insert_top_advertisers     (session, stmts["top_advertisers"], advertiser)
    insert_most_active_users   (session, stmts["active_users"],    user_act)
    insert_region_spend        (session, stmts["region_spend"],    region_adv)

    log.info("ETL complete.")
    cluster.shutdown()


if __name__ == "__main__":
    main()