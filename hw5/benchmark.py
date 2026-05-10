#!/usr/bin/env python3
"""
Benchmarks the three API endpoints:
  - Cache hit  : Redis answers (after the cache has been primed by one miss)
  - DB only    : ?no_cache=true forces every request to hit MySQL

Prints a comparison table and per-endpoint speedup factor.

Usage:
    python benchmark.py                  # API at http://localhost:8000
    API_URL=http://localhost:8000 python benchmark.py

Edit CAMPAIGN_ID, ADVERTISER_ID, USER_ID to IDs that exist in your database
(run seed.py first, then pick IDs from the /docs Swagger UI or the MySQL shell).
"""
import os
import statistics
import time

import requests

BASE_URL = os.getenv("API_URL", "http://localhost:8000")
RUNS = 30  # requests per scenario

# IDs to benchmark — adjust if these do not exist in your seeded data.
CAMPAIGN_ID = 1
ADVERTISER_ID = 1
USER_ID = 100  # change to a user_id that has ad events

ENDPOINTS = [
    (f"/campaign/{CAMPAIGN_ID}/performance", "Campaign Performance"),
    (f"/advertiser/{ADVERTISER_ID}/spending", "Advertiser Spending"),
    (f"/user/{USER_ID}/engagements", "User Engagements"),
]


def _measure(path: str, n: int, no_cache: bool = False) -> list[float]:
    url = BASE_URL + path + ("?no_cache=true" if no_cache else "")
    times = []
    for _ in range(n):
        t0 = time.perf_counter()
        r = requests.get(url, timeout=15)
        elapsed_ms = (time.perf_counter() - t0) * 1000
        r.raise_for_status()
        times.append(elapsed_ms)
    return times


def _stats(times: list[float]) -> tuple[float, float, float]:
    return statistics.mean(times), min(times), max(times)


def benchmark() -> None:
    print(f"API: {BASE_URL}   runs per scenario: {RUNS}\n")

    rows: list[tuple] = []

    for path, label in ENDPOINTS:
        print(f"Benchmarking: {label} ...")

        # Prime the cache (one intentional miss)
        requests.get(BASE_URL + path, timeout=15)

        hit_times = _measure(path, RUNS, no_cache=False)
        db_times = _measure(path, RUNS, no_cache=True)

        rows.append((label, "Cache hit", *_stats(hit_times)))
        rows.append((label, "DB only",   *_stats(db_times)))

    # ── table ─────────────────────────────────────────────────────────────────
    col_w = [25, 11, 10, 10, 10]
    sep = "+" + "+".join("-" * (w + 2) for w in col_w) + "+"
    header = "| {:<{w0}} | {:<{w1}} | {:>{w2}} | {:>{w3}} | {:>{w4}} |".format(
        "Endpoint", "Type", "Mean ms", "Min ms", "Max ms",
        w0=col_w[0], w1=col_w[1], w2=col_w[2], w3=col_w[3], w4=col_w[4],
    )

    print("\n" + sep)
    print(header)
    print(sep)

    prev_label = None
    for label, type_, mean, mn, mx in rows:
        if prev_label and label != prev_label:
            print(sep)
        prev_label = label
        print("| {:<{w0}} | {:<{w1}} | {:>{w2}.2f} | {:>{w3}.2f} | {:>{w4}.2f} |".format(
            label, type_, mean, mn, mx,
            w0=col_w[0], w1=col_w[1], w2=col_w[2], w3=col_w[3], w4=col_w[4],
        ))

    print(sep)

    # ── speedup ───────────────────────────────────────────────────────────────
    print("\nSpeedup  (DB only mean / Cache hit mean):")
    it = iter(rows)
    for hit_row, db_row in zip(it, it):
        speedup = db_row[2] / hit_row[2] if hit_row[2] > 0 else float("inf")
        print(f"  {hit_row[0]:<25}  {speedup:.1f}×")


if __name__ == "__main__":
    benchmark()