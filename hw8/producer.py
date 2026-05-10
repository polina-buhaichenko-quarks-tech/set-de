import csv
import json
import os
import random
import time
from datetime import datetime, timezone

from kafka import KafkaProducer
from kafka.errors import NoBrokersAvailable

BOOTSTRAP = os.getenv("KAFKA_BOOTSTRAP", "kafka:9092")
TOPIC = "tweets"
DATA_PATH = os.getenv("DATA_PATH", "/data/amazon_reviews.csv")
RATE_MIN = 10
RATE_MAX = 15


def connect(retries: int = 30, delay: float = 2.0) -> KafkaProducer:
    for attempt in range(1, retries + 1):
        try:
            producer = KafkaProducer(
                bootstrap_servers=BOOTSTRAP,
                value_serializer=lambda v: json.dumps(v).encode("utf-8"),
                acks="all",
            )
            print(f"Connected to Kafka at {BOOTSTRAP}")
            return producer
        except NoBrokersAvailable:
            print(f"Kafka not ready (attempt {attempt}/{retries}), retrying in {delay}s…")
            time.sleep(delay)
    raise RuntimeError(f"Could not connect to Kafka after {retries} attempts")


def main() -> None:
    producer = connect()
    sent = 0

    with open(DATA_PATH, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            row["review_date"] = datetime.now(timezone.utc).isoformat()
            producer.send(TOPIC, value=row)
            sent += 1
            if sent % 500 == 0:
                print(f"Sent {sent} messages to '{TOPIC}'")
            time.sleep(1.0 / random.uniform(RATE_MIN, RATE_MAX))

    producer.flush()
    producer.close()
    print(f"Done. Total messages sent: {sent}")


if __name__ == "__main__":
    main()