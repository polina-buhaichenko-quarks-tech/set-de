-- ============================================================
-- Cassandra Schema — Ad Analytics Platform
-- ============================================================
-- Source data:
--   ad_events  : 10 M rows (EventID, AdvertiserName, CampaignName,
--                CampaignTargetingCountry, UserID, Location,
--                Timestamp, AdCost, WasClicked, ClickTimestamp, AdRevenue …)
--   users      : 700 K rows (UserID, Age, Gender, Location, Interests …)
--   campaigns  : 1 K rows  (CampaignID, AdvertiserName, CampaignName,
--                TargetingCriteria, Budget …)
--
-- Every table is denormalized and pre-aggregated for exactly one
-- query pattern.  Cassandra's rule: model the table after the query,
-- not the entity.
-- ============================================================

CREATE KEYSPACE IF NOT EXISTS ad_analytics
    WITH replication = {
        'class': 'SimpleStrategy',
        'replication_factor': 3
    };

USE ad_analytics;


-- ============================================================
-- QUERY 1: Ad campaign performance over time
--   "For campaign X, return (date, total_impressions, total_clicks, CTR)
--    ordered newest-first."
--
-- Design rationale
--   Partition key  = campaign_name  → one partition holds ALL daily
--                    rows for one campaign; fits in memory, no fan-out.
--   Clustering key = event_date DESC → rows are physically sorted so
--                    Cassandra returns the most-recent day first with
--                    zero client-side sort.
--   CTR is stored as a pre-computed DOUBLE so reads never divide;
--   it is also kept as total_clicks / total_impressions for easy
--   recalculation if needed.
--   last_updated tracks when the ETL last refreshed this row, which
--   is useful when the ETL runs every 30 minutes: re-inserting the
--   same (campaign_name, event_date) row is a natural upsert in
--   Cassandra — today's numbers are overwritten in-place each run.
--   Loaded by ETL that aggregates ad_events on
--   (CampaignName, date(Timestamp)).
-- ============================================================

----------------------------------------
-- better approach when working not with static data
----------------------------------------
-- CREATE TABLE ad_campaign_performance (
--   campaign_id uuid,
--   day         date,
--   clicks      counter,
--   impressions counter,
--   PRIMARY KEY (campaign_id, day)
-- ) WITH CLUSTERING ORDER BY (day DESC);
--
-- --updating with
-- -- On every click
--
-- UPDATE ad_campaign_performance
-- SET clicks = clicks + 1
-- WHERE campaign_id = ? AND day = toDate(now());
--
-- -- On every impression
-- UPDATE ad_campaign_performance
-- SET impressions = impressions + 1
-- WHERE campaign_id = ? AND day = toDate(now());

-- but below is my approach for static data from owr csv

CREATE TABLE IF NOT EXISTS campaign_performance_by_day (
    campaign_name       TEXT,
    event_date          DATE,
    total_impressions   BIGINT,
    total_clicks        BIGINT,
    ctr                 DOUBLE,     -- total_clicks / total_impressions
    total_ad_cost       DECIMAL,    -- SUM(AdCost) for the day
    total_ad_revenue    DECIMAL,    -- SUM(AdRevenue) for the day
    PRIMARY KEY (campaign_name, event_date)
) WITH CLUSTERING ORDER BY (event_date DESC)
  AND comment = 'Q1: daily CTR/impressions/clicks per campaign, refreshed every 30 min';

-- Example query:
-- SELECT event_date, total_impressions, total_clicks, ctr, last_updated
-- FROM campaign_performance_by_day
-- WHERE campaign_name = 'Campaign_278'
-- LIMIT 30;


-- ============================================================
-- QUERY 2: Top advertisers by total ad spend in the past 30 days
--   "For each advertiser return daily spend/impressions/clicks,
--    so the application can sum the last 30 days and rank."
--
-- Design rationale
--   Partition key  = advertiser_name → all daily rows for one
--                    advertiser live in one partition; querying
--                    the last 30 days never touches other partitions.
--   Clustering key = event_date DESC → rows returned newest-first;
--                    a date range filter (>= today-30) is a fast
--                    slice on already-sorted data.
--   Daily granularity lets the application (or a materialised view)
--   sum any arbitrary window without recomputing from raw events.
--   Loaded by ETL aggregating ad_events on (AdvertiserName, date).
-- ============================================================

CREATE TABLE IF NOT EXISTS advertiser_spend_by_day (
    advertiser_name     TEXT,
    event_date          DATE,
    total_spend         DECIMAL,    -- SUM(AdCost) for the day
    total_impressions   BIGINT,
    total_clicks        BIGINT,
    total_revenue       DECIMAL,    -- SUM(AdRevenue) for the day
    PRIMARY KEY (advertiser_name, event_date)
) WITH CLUSTERING ORDER BY (event_date DESC)
  AND comment = 'Q2: daily spend/impressions/clicks per advertiser';

-- Example query (last 30 days for one advertiser):
-- SELECT event_date, total_spend, total_impressions, total_clicks
-- FROM advertiser_spend_by_day
-- WHERE advertiser_name = 'Advertiser_1'
--   AND event_date >= '2024-10-11'
-- ORDER BY event_date DESC;


-- ============================================================
-- QUERY 3: User engagement history
--   "For user X, return every ad event (impression and/or click)
--    with its timestamp, campaign, and whether it was clicked."
--
-- Design rationale
--   Partition key  = user_id       → all events for one user in one
--                    partition; no scatter-gather.
--   Clustering key = event_timestamp DESC, event_id ASC → newest
--                    events first; event_id breaks timestamp ties.
--   Denormalized columns from ad_events; no joins required at read time.
--   Loaded directly from ad_events (one row per raw event — no
--   aggregation needed).
-- ============================================================

CREATE TABLE IF NOT EXISTS user_engagement_history (
    user_id             INT,
    event_timestamp     TIMESTAMP,
    event_id            UUID,
    campaign_name       TEXT,
    advertiser_name     TEXT,
    ad_slot_size        TEXT,
    device              TEXT,
    location            TEXT,
    was_clicked         BOOLEAN,
    click_timestamp     TIMESTAMP,  -- NULL when was_clicked = false
    ad_cost             DECIMAL,
    ad_revenue          DECIMAL,
    PRIMARY KEY (user_id, event_timestamp, event_id)
) WITH CLUSTERING ORDER BY (event_timestamp DESC, event_id ASC)
  AND comment = 'Q3: full ad engagement timeline per user';

-- Example query:
-- SELECT event_timestamp, campaign_name, advertiser_name,
--        was_clicked, click_timestamp
-- FROM user_engagement_history
-- WHERE user_id = 289903
-- LIMIT 50;


-- ============================================================
-- QUERY 4: Most active users
--   "Return the top-N users by total ad interactions
--    (impressions + clicks)."
--
-- Design rationale
--   Same single-bucket pattern as Query 2.
--   Partition key  = activity_bucket ('global').
--   Clustering key = total_interactions DESC, user_id ASC — stored in
--                    rank order; a LIMIT N query is O(N).
--   total_interactions = total_impressions + total_clicks so the
--                    column captures both passive views and active clicks.
--   Loaded by ETL that aggregates ad_events on UserID.
-- ============================================================

CREATE TABLE IF NOT EXISTS most_active_users (
    activity_bucket     TEXT,       -- always 'global'
    total_interactions  BIGINT,     -- impressions + clicks
    user_id             INT,
    total_impressions   BIGINT,
    total_clicks        BIGINT,
    PRIMARY KEY (activity_bucket, total_interactions, user_id)
) WITH CLUSTERING ORDER BY (total_interactions DESC, user_id ASC)
  AND comment = 'Q4: global user ranking by ad interaction count';

-- Example query:
-- SELECT user_id, total_interactions, total_impressions, total_clicks
-- FROM most_active_users
-- WHERE activity_bucket = 'global'
-- LIMIT 20;


-- ============================================================
-- QUERY 5: High-spending advertisers by Region
--   "In region R, return advertisers ranked by total ad spend."
--
-- Design rationale
--   Region is sourced from CampaignTargetingCountry in ad_events
--   (the geographic market the campaign was aimed at).
--   Partition key  = region          → one partition per country;
--                    cardinality ~10–50 countries → balanced load.
--   Clustering key = total_spend DESC, advertiser_name ASC → rows
--                    in rank order within the region partition.
--   Loaded by ETL that aggregates ad_events on
--   (CampaignTargetingCountry, AdvertiserName).
-- ============================================================

CREATE TABLE IF NOT EXISTS high_spending_advertisers_by_region (
    region              TEXT,       -- CampaignTargetingCountry (e.g. 'USA')
    total_spend         DECIMAL,
    advertiser_name     TEXT,
    total_impressions   BIGINT,
    total_clicks        BIGINT,
    total_revenue       DECIMAL,
    PRIMARY KEY (region, total_spend, advertiser_name)
) WITH CLUSTERING ORDER BY (total_spend DESC, advertiser_name ASC)
  AND comment = 'Q5: per-region advertiser ranking by ad spend';

-- Example query:
-- SELECT advertiser_name, total_spend, total_impressions
-- FROM high_spending_advertisers_by_region
-- WHERE region = 'USA'
-- LIMIT 10;