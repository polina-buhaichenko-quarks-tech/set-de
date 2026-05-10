-- ─────────────────────────────────────────────────────────────────────────────
-- AdTech analytical queries  –  Homework 2
--
-- Analysis window: 2024-10-01 … 2024-10-31  (inclusive, October 2024)
-- The same window is used for every time-scoped question (Q1–Q5, Q7).
-- Q6 (budget consumption) operates on all-time spend data.
-- ─────────────────────────────────────────────────────────────────────────────

-- ── Q1: Top 5 campaigns by Click-Through Rate ─────────────────────────────────
-- Which campaigns are the most effective at driving user engagement?
-- CTR = clicks / impressions × 100.  Campaigns with fewer than 100 impressions
-- are excluded to avoid statistical noise from tiny samples.

SELECT
    c.campaign_name,
    a.name                                                AS advertiser,
    COUNT(*)                                              AS impressions,
    SUM(ae.was_clicked)                                   AS clicks,
    ROUND(100.0 * SUM(ae.was_clicked) / COUNT(*), 4)     AS ctr_pct
FROM      ad_events   ae
JOIN      campaigns   c  ON ae.campaign_id  = c.campaign_id
JOIN      advertisers a  ON c.advertiser_id = a.advertiser_id
WHERE     ae.timestamp >= '2024-10-01'
      AND ae.timestamp  < '2024-11-01'
GROUP BY  c.campaign_id, c.campaign_name, a.name
HAVING    impressions >= 100
ORDER BY  ctr_pct DESC
LIMIT 5;


-- ── Q2: Advertiser spending & engagement ──────────────────────────────────────
-- Which advertisers are the biggest spenders, and does higher spend correlate
-- with more clicks?

SELECT
    a.name                                                AS advertiser,
    COUNT(*)                                              AS impressions,
    SUM(ae.was_clicked)                                   AS total_clicks,
    ROUND(SUM(ae.ad_cost), 2)                             AS total_spend,
    ROUND(100.0 * SUM(ae.was_clicked) / COUNT(*), 4)     AS ctr_pct
FROM      ad_events   ae
JOIN      campaigns   c  ON ae.campaign_id  = c.campaign_id
JOIN      advertisers a  ON c.advertiser_id = a.advertiser_id
WHERE     ae.timestamp >= '2024-10-01'
      AND ae.timestamp  < '2024-11-01'
GROUP BY  a.advertiser_id, a.name
ORDER BY  total_spend DESC
LIMIT 10;


-- ── Q3: Cost Per Click (CPC) and Cost Per Mille (CPM) per campaign ────────────
-- How efficiently is each campaign spending its budget?
-- CPC  = total_cost / clicks
-- CPM  = total_cost / impressions × 1 000

SELECT
    c.campaign_name,
    a.name                                                                   AS advertiser,
    COUNT(*)                                                                 AS impressions,
    SUM(ae.was_clicked)                                                      AS clicks,
    ROUND(SUM(ae.ad_cost), 2)                                                AS total_cost,
    ROUND(SUM(ae.ad_cost) / NULLIF(SUM(ae.was_clicked), 0), 4)              AS cpc,
    ROUND(1000.0 * SUM(ae.ad_cost) / COUNT(*), 4)                           AS cpm
FROM      ad_events   ae
JOIN      campaigns   c  ON ae.campaign_id  = c.campaign_id
JOIN      advertisers a  ON c.advertiser_id = a.advertiser_id
WHERE     ae.timestamp >= '2024-10-01'
      AND ae.timestamp  < '2024-11-01'
GROUP BY  c.campaign_id, c.campaign_name, a.name
ORDER BY  cpc ASC;


-- ── Q4: Top locations by ad revenue from clicks ───────────────────────────────
-- Where in the world do ads generate the highest revenue?
-- Only events where the ad was actually clicked contribute revenue.

SELECT
    l.country_name                    AS location,
    COUNT(*)                          AS click_events,
    ROUND(SUM(ae.ad_revenue), 2)      AS total_revenue
FROM      ad_events ae
JOIN      locations l  ON ae.location_id = l.country_id
WHERE     ae.timestamp  >= '2024-10-01'
      AND ae.timestamp   < '2024-11-01'
      AND ae.was_clicked  = TRUE
GROUP BY  l.country_id, l.country_name
ORDER BY  total_revenue DESC
LIMIT 10;


-- ── Q5: Top 10 most engaged users ─────────────────────────────────────────────
-- Which users clicked the most ads during the analysis period?

SELECT
    u.user_id,
    u.age,
    u.gender,
    l.country_name                    AS country,
    COUNT(*)                          AS total_clicks
FROM      ad_events  ae
JOIN      users      u  ON ae.user_id    = u.user_id
LEFT JOIN locations  l  ON u.country_id  = l.country_id
WHERE     ae.timestamp  >= '2024-10-01'
      AND ae.timestamp   < '2024-11-01'
      AND ae.was_clicked  = TRUE
GROUP BY  u.user_id, u.age, u.gender, l.country_name
ORDER BY  total_clicks DESC
LIMIT 10;


-- ── Q6: Campaigns close to budget exhaustion (all-time) ───────────────────────
-- Which campaigns have consumed more than 80 % of their total budget?
-- Uses cumulative ad_cost from all events, not limited to the 30-day window,
-- because budget depletion is a campaign-lifetime metric.

SELECT
    c.campaign_name,
    a.name                                                                         AS advertiser,
    c.budget                                                                       AS total_budget,
    ROUND(SUM(ae.ad_cost), 2)                                                      AS total_spent,
    ROUND(100.0 * SUM(ae.ad_cost) / NULLIF(c.budget, 0), 2)                       AS pct_budget_spent
FROM      campaigns   c
JOIN      advertisers a   ON c.advertiser_id = a.advertiser_id
LEFT JOIN ad_events   ae  ON ae.campaign_id  = c.campaign_id
WHERE     c.budget > 0
GROUP BY  c.campaign_id, c.campaign_name, a.name, c.budget
HAVING    pct_budget_spent > 80
ORDER BY  pct_budget_spent DESC;


-- ── Q7: CTR by device type ────────────────────────────────────────────────────
-- Do mobile, desktop, or tablet users engage more with ads?
-- Helps advertisers decide where to concentrate creative effort.

SELECT
    d.device_name,
    COUNT(*)                                              AS impressions,
    SUM(ae.was_clicked)                                   AS clicks,
    ROUND(100.0 * SUM(ae.was_clicked) / COUNT(*), 4)     AS ctr_pct
FROM      ad_events ae
JOIN      devices   d   ON ae.device_id = d.device_id
WHERE     ae.timestamp >= '2024-10-01'
      AND ae.timestamp  < '2024-11-01'
GROUP BY  d.device_id, d.device_name
ORDER BY  ctr_pct DESC;