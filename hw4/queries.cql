USE ad_analytics;

-- ============================================================
-- Query 1: CTR per campaign per day
--   For a given campaign returns one row per day with
--   impressions, clicks, and pre-computed CTR, newest day first.
--
--   campaign_name is the partition key so the entire daily
--   history for one campaign lives in a single partition —
--   this query never touches any other partition.
--   event_date DESC clustering means no client-side sort.
-- ============================================================

SELECT
    campaign_name,
    event_date,
    total_impressions,
    total_clicks,
    ctr,
    total_ad_cost,
    total_ad_revenue
FROM campaign_performance_by_day
WHERE campaign_name = 'Campaign_278'
ORDER BY event_date DESC;


-- ============================================================
-- Query 2: Top 5 advertisers by total ad spend in the past 30 days
--   Sums spend/impressions/clicks per advertiser over the last 30 days,
--   orders by total spend descending, and returns the top 5.
--   Note: Cassandra does not support ORDER BY on aggregate functions —
--   the ORDER BY + LIMIT must be applied by the application after
--   receiving the GROUP BY result set.
--   ALLOW FILTERING is required because event_date is a clustering
--   key, not a partition key, so Cassandra scans all partitions.
-- ============================================================

SELECT
    advertiser_name,
    SUM(total_spend)       AS total_30d_spend,
    SUM(total_impressions) AS total_30d_impressions,
    SUM(total_clicks)      AS total_30d_clicks,
    SUM(total_revenue)     AS total_30d_revenue
FROM advertiser_spend_by_day
WHERE event_date >= toDate(now()) - 30
GROUP BY advertiser_name
ORDER BY SUM(total_spend) DESC
LIMIT 5
ALLOW FILTERING;


-- ============================================================
-- Query 3: Last 10 ads seen by a user and whether they clicked
--   Returns the 10 most recent ad impressions for a given user,
--   with the campaign, advertiser, timestamp, and click status.
--
--   user_id is the partition key so all events for one user are
--   co-located — no cross-partition reads.
--   event_timestamp DESC clustering returns newest events first,
--   so LIMIT 10 reads exactly 10 rows from the partition head.
-- ============================================================

SELECT
    event_timestamp,
    campaign_name,
    advertiser_name,
    was_clicked,
    click_timestamp
FROM user_engagement_history
WHERE user_id = 289903
ORDER BY event_timestamp DESC
LIMIT 10;


-- ============================================================
-- Query 4: Top 10 users by ad clicks in the past 30 days
--   Counts click events per user for the last 30 days and returns
--   the users with the highest click counts.
--
--   Source: user_engagement_history (raw events with timestamps).
--   was_clicked = true filters impressions out, keeping only clicks.
--   event_timestamp cutoff (now - 30 days) is computed by the
--   application and passed as a bound parameter.
--   ALLOW FILTERING is required because neither was_clicked nor
--   event_timestamp is a partition key.
--   Same Cassandra limitation as Query 2: ORDER BY on COUNT(*)
--   is not supported — the application sorts and takes top 10.
-- ============================================================

SELECT
    user_id,
    COUNT(*) AS total_clicks_30d
FROM user_engagement_history
WHERE was_clicked = true
  AND event_timestamp >= toTimestamp(toDate(now()) - 30)
GROUP BY user_id
ORDER BY COUNT(*) DESC
LIMIT 10
ALLOW FILTERING;


-- ============================================================
-- Query 5: Top 5 advertisers by spend in a specific region over the last 30 days
--   Sums ad_cost per advertiser filtered by location and date,
--   then returns the top 5 spenders in that region.
--
--   Source: user_engagement_history — contains both location
--   (where the ad event occurred) and ad_cost per event.
--   ALLOW FILTERING is required because location and
--   event_timestamp are not partition keys.
--   Same Cassandra limitation as queries 2 and 4: GROUP BY is
--   only supported on primary key columns, and ORDER BY on
--   an aggregate is not supported — the application sorts
--   the result and takes the top 5.
-- ============================================================

SELECT
    advertiser_name,
    SUM(ad_cost) AS total_30d_spend
FROM user_engagement_history
WHERE location = 'USA'
  AND event_timestamp >= toTimestamp(toDate(now()) - 30)
GROUP BY advertiser_name
ORDER BY SUM(ad_cost) DESC
LIMIT 5
ALLOW FILTERING;