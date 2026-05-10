# HW8 — Amazon Reviews: Kafka Tweet Stream

Simulates a live tweet stream by reading `amazon_reviews.csv` row-by-row,
replacing each `review_date` with the current UTC timestamp, and publishing
every row as a JSON message to the `tweets` Kafka topic at 10–15 msg/s.

---

## Stack

| Component | Image |
|---|---|
| Kafka (KRaft, no ZooKeeper) | `bitnami/kafka:3.7` |
| Producer | Python 3.11 + kafka-python (custom container) |

---

## Quick Start

### 1. Start Kafka

```bash
cd hw8
docker compose up -d
docker compose ps   # wait until kafka is healthy (~30 s)
```

### 2. Build the producer image

```bash
bash hw8/build.sh
```

### 3. Run the producer

```bash
bash hw8/run.sh
```

The producer mounts `data2/amazon_reviews.csv` read-only and streams
messages to the `tweets` topic.  Progress is printed every 500 messages.

### 4. Verify with the console consumer

```bash
docker exec -it kafka kafka-console-consumer.sh \
  --bootstrap-server localhost:9092 \
  --topic tweets \
  --from-beginning \
  --max-messages 20
```

---

## Files

| File | Purpose |
|---|---|
| `docker-compose.yml` | Kafka broker (KRaft mode), network `kafka-net` |
| `producer.py` | Reads CSV, replaces timestamps, sends to Kafka |
| `Dockerfile` | Builds the producer container |
| `requirements.txt` | `kafka-python` dependency |
| `build.sh` | `docker build -t kafka-producer` |
| `run.sh` | `docker run` on `kafka-net` with `data2` mounted |