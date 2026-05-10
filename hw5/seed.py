#!/usr/bin/env python3
"""
Seeds MySQL with a sample of ad events from the CSV files.

Run this once after 'docker compose up' to populate the database:

    python seed.py              # loads 100 000 rows (default)
    SEED_ROWS=50000 python seed.py

The script reads from ../../data/ (relative to hw5/) which is where the
existing CSVs live.  The MySQL port is 3307 by default because docker-compose
maps the container's 3306 → host 3307 to avoid conflicts with a local MySQL.
"""
import os
import uuid
from pathlib import Path

import mysql.connector
import pandas as pd
from dotenv import load_dotenv

load_dotenv()

DATA_DIR = Path(__file__).parent.parent / "data"
EVENTS_CSV = DATA_DIR / "(USE THIS)ad_events_header_updated(2).csv"
SAMPLE = int(os.getenv("SEED_ROWS", 100_000))

CFG = dict(
    host=os.getenv("DB_HOST", "localhost"),
    port=int(os.getenv("DB_PORT", 3307)),
    database=os.getenv("DB_NAME", "ad_analytics"),
    user=os.getenv("DB_USER", "aduser"),
    password=os.getenv("DB_PASSWORD", "adpass"),
)


def seed() -> None:
    print(f"Connecting to MySQL at {CFG['host']}:{CFG['port']} ...")
    conn = mysql.connector.connect(**CFG)
    cur = conn.cursor()

    print(f"Reading {SAMPLE:,} rows from {EVENTS_CSV.name} ...")
    events = pd.read_csv(EVENTS_CSV, nrows=SAMPLE, low_memory=False)
    events["Timestamp"] = pd.to_datetime(events["Timestamp"], errors="coerce")
    events["ClickTimestamp"] = pd.to_datetime(events["ClickTimestamp"], errors="coerce")
    events["WasClicked"] = events["WasClicked"].astype(str).str.lower().eq("true")
    events["AdCost"] = pd.to_numeric(events["AdCost"], errors="coerce").fillna(0.0)
    events["AdRevenue"] = pd.to_numeric(events["AdRevenue"], errors="coerce").fillna(0.0)
    events["AdvertiserName"] = events["AdvertiserName"].astype(str).str.strip()
    events["CampaignName"] = events["CampaignName"].astype(str).str.strip()
    events = events[events["Timestamp"].notna()]
    print(f"  {len(events):,} valid rows after parsing.")

    # ── advertisers ──────────────────────────────────────────────────────────
    adv_names = events["AdvertiserName"].unique()
    print(f"Inserting {len(adv_names)} advertisers ...")
    cur.executemany(
        "INSERT IGNORE INTO advertisers (name) VALUES (%s)",
        [(n,) for n in adv_names],
    )
    conn.commit()
    cur.execute("SELECT advertiser_id, name FROM advertisers")
    adv_map: dict[str, int] = {name: aid for aid, name in cur.fetchall()}

    # ── campaigns ────────────────────────────────────────────────────────────
    camp_pairs = (
        events[["CampaignName", "AdvertiserName"]]
        .drop_duplicates()
        .itertuples(index=False)
    )
    camp_rows = [
        (row.CampaignName, adv_map[row.AdvertiserName], 0.0)
        for row in camp_pairs
        if row.AdvertiserName in adv_map
    ]
    print(f"Inserting {len(camp_rows)} campaigns ...")
    cur.executemany(
        "INSERT IGNORE INTO campaigns (campaign_name, advertiser_id, budget) VALUES (%s, %s, %s)",
        camp_rows,
    )
    conn.commit()
    cur.execute("SELECT campaign_id, campaign_name FROM campaigns")
    camp_map: dict[str, int] = {name: cid for cid, name in cur.fetchall()}

    # ── users ────────────────────────────────────────────────────────────────
    user_ids = events["UserID"].dropna().astype(int).unique()
    print(f"Inserting {len(user_ids):,} users ...")
    cur.executemany(
        "INSERT IGNORE INTO users (user_id) VALUES (%s)",
        [(int(uid),) for uid in user_ids],
    )
    conn.commit()

    # ── ad events ────────────────────────────────────────────────────────────
    print("Inserting ad events in batches of 1 000 ...")
    batch: list[tuple] = []
    total = 0

    INSERT_SQL = """
        INSERT IGNORE INTO ad_events
            (event_id, campaign_id, user_id, timestamp,
             ad_cost, was_clicked, click_timestamp, ad_revenue)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
    """

    for row in events.itertuples(index=False):
        cid = camp_map.get(str(row.CampaignName).strip())
        if cid is None:
            continue

        eid = str(row.EventID) if hasattr(row, "EventID") and pd.notna(row.EventID) else str(uuid.uuid4())
        uid = int(row.UserID) if pd.notna(row.UserID) else None
        click_ts = row.ClickTimestamp.to_pydatetime() if pd.notna(row.ClickTimestamp) else None

        batch.append((
            eid,
            cid,
            uid,
            row.Timestamp.to_pydatetime(),
            float(row.AdCost),
            int(row.WasClicked),
            click_ts,
            float(row.AdRevenue),
        ))

        if len(batch) == 1000:
            cur.executemany(INSERT_SQL, batch)
            conn.commit()
            total += len(batch)
            batch = []
            print(f"  {total:,} events inserted ...")

    if batch:
        cur.executemany(INSERT_SQL, batch)
        conn.commit()
        total += len(batch)

    print(f"\nDone — {total:,} ad events loaded.")
    cur.close()
    conn.close()


if __name__ == "__main__":
    seed()