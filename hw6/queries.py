"""
Demo queries against the three MongoDB collections populated by etl.py.
Run after etl.py has completed.
"""
import os
import pymongo
from pprint import pprint

MONGO_URI = os.getenv("MONGO_URI", "mongodb://localhost:27017/")
DB_NAME = "amazon_reviews"

client = pymongo.MongoClient(MONGO_URI)
db = client[DB_NAME]


def separator(title):
    print(f"\n{'=' * 60}")
    print(f"  {title}")
    print('=' * 60)


# --- product_stats ---
separator("Top 10 products by review count (with avg rating)")
cursor = (
    db["product_stats"]
    .find({}, {"_id": 0})
    .sort("total_reviews", pymongo.DESCENDING)
    .limit(10)
)
for doc in cursor:
    print(f"  {doc['product_id']:15s}  reviews={doc['total_reviews']:>5}  "
          f"avg_rating={doc['avg_star_rating']:.2f}  {doc['product_title'][:50]}")

separator("Products with avg rating >= 4.5 (min 20 reviews)")
cursor = db["product_stats"].find(
    {"avg_star_rating": {"$gte": 4.5}, "total_reviews": {"$gte": 20}},
    {"_id": 0},
).sort("avg_star_rating", pymongo.DESCENDING).limit(10)
for doc in cursor:
    pprint(doc)


# --- customer_stats ---
separator("Top 10 most active reviewers")
cursor = (
    db["customer_stats"]
    .find({}, {"_id": 0})
    .sort("total_verified_reviews", pymongo.DESCENDING)
    .limit(10)
)
for doc in cursor:
    print(f"  customer={doc['customer_id']}  verified_reviews={doc['total_verified_reviews']}")

separator("Customers with more than 50 verified reviews")
count = db["customer_stats"].count_documents({"total_verified_reviews": {"$gt": 50}})
print(f"  Count: {count}")


# --- monthly_product_reviews ---
separator("Monthly review trend for the most-reviewed product")
top = db["product_stats"].find_one({}, sort=[("total_reviews", pymongo.DESCENDING)])
if top:
    product_id = top["product_id"]
    print(f"  Product: {top['product_title']} ({product_id})")
    cursor = db["monthly_product_reviews"].find(
        {"product_id": product_id},
        {"_id": 0},
    ).sort([("year", pymongo.ASCENDING), ("month", pymongo.ASCENDING)])
    for doc in cursor:
        print(f"  {doc['year']}-{doc['month']:02d}  reviews={doc['review_count']}")

separator("Total monthly review volume across all products (pipeline)")
pipeline = [
    {"$group": {"_id": {"year": "$year", "month": "$month"},
                "total": {"$sum": "$review_count"}}},
    {"$sort": {"_id.year": 1, "_id.month": 1}},
]
for doc in db["monthly_product_reviews"].aggregate(pipeline):
    ym = doc["_id"]
    print(f"  {ym['year']}-{ym['month']:02d}  total_reviews={doc['total']}")