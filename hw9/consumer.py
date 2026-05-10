import csv
import json
import os
import time
from datetime import datetime, timezone

from kafka import KafkaConsumer
from kafka.errors import NoBrokersAvailable

BOOTSTRAP = os.getenv("KAFKA_BOOTSTRAP", "kafka:9092")
TOPIC = "tweets"
OUTPUT_DIR = os.getenv("OUTPUT_DIR", "/output")
GROUP_ID = "tweet-consumer-group"


def connect(retries: int = 30, delay: float = 2.0) -> KafkaConsumer:
    for attempt in range(1, retries + 1):
        try:
            consumer = KafkaConsumer(
                TOPIC,
                bootstrap_servers=BOOTSTRAP,
                value_deserializer=lambda v: json.loads(v.decode("utf-8")),
                auto_offset_reset="earliest",
                group_id=GROUP_ID,
                enable_auto_commit=True,
            )
            print(f"Connected to Kafka at {BOOTSTRAP}")
            return consumer
        except NoBrokersAvailable:
            print(f"Kafka not ready (attempt {attempt}/{retries}), retrying in {delay}s…")
            time.sleep(delay)
    raise RuntimeError(f"Could not connect to Kafka after {retries} attempts")


def filename_for(created_at: str) -> str:
    dt = datetime.fromisoformat(created_at)
    return f"tweets_{dt.strftime('%d_%m_%Y_%H_%M')}.csv"


def main() -> None:
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    consumer = connect()

    # filename -> (file_handle, csv_writer)
    open_files: dict[str, tuple] = {}
    processed = 0

    try:
        for message in consumer:
            row = message.value

            author_id = row.get("customer_id", "")
            created_at = row.get("review_date", datetime.now(timezone.utc).isoformat())
            text = row.get("review_body", "")

            fname = filename_for(created_at)
            filepath = os.path.join(OUTPUT_DIR, fname)

            if fname not in open_files:
                is_new = not os.path.exists(filepath)
                fh = open(filepath, "a", newline="", encoding="utf-8")
                writer = csv.DictWriter(fh, fieldnames=["author_id", "created_at", "text"])
                if is_new:
                    writer.writeheader()
                open_files[fname] = (fh, writer)
                print(f"Opened new file: {fname}")

            fh, writer = open_files[fname]
            writer.writerow({"author_id": author_id, "created_at": created_at, "text": text})

            processed += 1
            if processed % 500 == 0:
                for fh, _ in open_files.values():
                    fh.flush()
                print(f"Processed {processed} messages across {len(open_files)} file(s)")

    finally:
        for fh, _ in open_files.values():
            fh.close()
        consumer.close()


if __name__ == "__main__":
    main()