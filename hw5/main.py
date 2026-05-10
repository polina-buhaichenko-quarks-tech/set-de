"""
Ad Analytics REST API  —  hw5
FastAPI + MySQL + Redis read-through cache.

Endpoints
---------
GET /campaign/{campaign_id}/performance   TTL 30 s
GET /advertiser/{advertiser_id}/spending  TTL 5 min
GET /user/{user_id}/engagements           TTL 60 s

Add ?no_cache=true to any endpoint to bypass Redis and always hit MySQL.
This is used by benchmark.py to measure uncached latency.
"""
from fastapi import FastAPI, HTTPException, Query

from cache import get_cached, set_cached
from db import get_advertiser_spending, get_campaign_performance, get_user_engagements

# TTLs in seconds
CAMPAIGN_TTL = 30
ADVERTISER_TTL = 300  # 5 minutes
USER_TTL = 60

app = FastAPI(title="Ad Analytics API", version="1.0")


# ── health ────────────────────────────────────────────────────────────────────

@app.get("/health")
def health():
    return {"status": "ok"}


# ── campaign performance ──────────────────────────────────────────────────────

@app.get("/campaign/{campaign_id}/performance")
def campaign_performance(
    campaign_id: int,
    no_cache: bool = Query(False, description="Bypass Redis and query MySQL directly"),
):
    """
    Returns CTR, total clicks, total impressions, and total ad spend for a campaign.

    Read-through cache:
      1. Check Redis (key: campaign:{id}:performance).
      2. On miss, query MySQL and store the result with a 30-second TTL.
    """
    key = f"campaign:{campaign_id}:performance"

    if not no_cache:
        hit = get_cached(key)
        if hit:
            return {**hit, "cache": "hit"}

    data = get_campaign_performance(campaign_id)
    if data is None:
        raise HTTPException(status_code=404, detail=f"Campaign {campaign_id} not found")

    if not no_cache:
        set_cached(key, data, CAMPAIGN_TTL)

    return {**data, "cache": "miss"}


# ── advertiser spending ───────────────────────────────────────────────────────

@app.get("/advertiser/{advertiser_id}/spending")
def advertiser_spending(
    advertiser_id: int,
    no_cache: bool = Query(False, description="Bypass Redis and query MySQL directly"),
):
    """
    Returns total ad spend, impressions, clicks, and revenue for an advertiser.

    Read-through cache:
      1. Check Redis (key: advertiser:{id}:spending).
      2. On miss, query MySQL and store the result with a 5-minute TTL.
    """
    key = f"advertiser:{advertiser_id}:spending"

    if not no_cache:
        hit = get_cached(key)
        if hit:
            return {**hit, "cache": "hit"}

    data = get_advertiser_spending(advertiser_id)
    if data is None:
        raise HTTPException(status_code=404, detail=f"Advertiser {advertiser_id} not found")

    if not no_cache:
        set_cached(key, data, ADVERTISER_TTL)

    return {**data, "cache": "miss"}


# ── user engagements ──────────────────────────────────────────────────────────

@app.get("/user/{user_id}/engagements")
def user_engagements(
    user_id: int,
    no_cache: bool = Query(False, description="Bypass Redis and query MySQL directly"),
):
    """
    Returns the 50 most recent ad events for a user (impressions and clicks).

    Read-through cache:
      1. Check Redis (key: user:{id}:engagements).
      2. On miss, query MySQL and store the result with a 60-second TTL.
    """
    key = f"user:{user_id}:engagements"

    if not no_cache:
        hit = get_cached(key)
        if hit:
            return {**hit, "cache": "hit"}

    data = get_user_engagements(user_id)
    if data is None:
        raise HTTPException(status_code=404, detail=f"User {user_id} not found")

    if not no_cache:
        set_cached(key, data, USER_TTL)

    return {**data, "cache": "miss"}