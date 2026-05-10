# HW10: Wikipedia Real-Time Stream Processing

Real-time pipeline: Wikipedia SSE stream → Kafka → Spark Streaming → Cassandra.

## Architecture

```
https://stream.wikimedia.org/v2/stream/page-create
                    ↓
              [Generator]           (Docker container)
                    ↓
          Kafka topic: input
                    ↓
      [Spark: stream_processor]     (filter by domain + non-bot)
                    ↓
         Kafka topic: processed
                    ↓
      [Spark: cassandra_writer]
                    ↓
     Cassandra: wiki.page_creates
```

**Filtering logic (stream_processor.py):**
- Keeps only events where `meta.domain` is one of:
  `en.wikipedia.org`, `www.wikidata.org`, `commons.wikimedia.org`
- Keeps only events where `performer.user_is_bot` is `false`

**Cassandra table fields:** `domain`, `created_at`, `user_id`, `page_title`

---

## File Structure

```
hw10/
├── docker-compose.kafka.yml        # Kafka broker (KRaft) + topic init
├── docker-compose.cassandra.yml    # Single-node Cassandra + schema init
├── docker-compose.spark.yml        # Spark master + worker
├── docker-compose.generator.yml    # Wikipedia SSE → Kafka producer
├── cassandra-init/
│   └── init.cql                    # Keyspace + table DDL
├── generator/
│   ├── Dockerfile
│   ├── requirements.txt
│   └── generator.py                # SSE reader → Kafka producer
├── spark-apps/
│   ├── stream_processor.py         # input → filter → processed
│   └── cassandra_writer.py         # processed → Cassandra
├── submit_processor.sh
└── submit_cassandra_writer.sh
```

---

## Prerequisites

- Docker Engine + Docker Compose v2
- Internet access (Wikipedia SSE stream + Maven Central for Spark packages)

---

## Step-by-Step Setup

### 1. Create shared Docker network

```bash
docker network create hw10-network
```

### 2. Start Kafka

```bash
docker-compose -f docker-compose.kafka.yml up -d
```

Wait ~30s. Verify topics were created:

```bash
docker exec kafka kafka-topics.sh --bootstrap-server localhost:9092 --list
# Expected output:
# input
# processed
```

### 3. Start Cassandra

```bash
docker-compose -f docker-compose.cassandra.yml up -d
```

Wait ~90s for Cassandra to initialize (the `cassandra-init` container runs the schema automatically). Verify:

```bash
docker exec cassandra cqlsh -e "DESCRIBE wiki.page_creates;"
```

### 4. Start Spark

```bash
docker-compose -f docker-compose.spark.yml up -d
```

Spark Master UI: http://localhost:8080

### 5. Start Generator

```bash
docker-compose -f docker-compose.generator.yml up -d
```

Check it's producing events:

```bash
docker logs -f wiki-generator
```

### 6. Submit Spark Streaming Jobs

> **Note:** First run downloads Maven packages (~1–2 min). Package cache is reused on subsequent runs.

```bash
./submit_processor.sh
./submit_cassandra_writer.sh
```

Allow the pipeline to run for **3–5 minutes**.

---

## Verify Results

### Kafka — input topic (raw events from Wikipedia)

```bash
docker exec kafka kafka-console-consumer.sh \
  --bootstrap-server localhost:9092 \
  --topic input \
  --max-messages 5
```

### Kafka — processed topic (filtered: 3 domains, non-bot only)

```bash
docker exec kafka kafka-console-consumer.sh \
  --bootstrap-server localhost:9092 \
  --topic processed \
  --max-messages 5
```

### Cassandra

```bash
docker exec -it cassandra cqlsh
```

Inside cqlsh:

```cql
SELECT user_id, domain, created_at, page_title
FROM wiki.page_creates
LIMIT 10;

SELECT COUNT(*) FROM wiki.page_creates;
```

### Spark job logs

```bash
docker exec spark-master tail -f /tmp/processor.log
docker exec spark-master tail -f /tmp/cassandra_writer.log
```

### Spark Web UI

Open http://localhost:8080 to see running applications and workers.

---

## Teardown

```bash
# Stop Spark jobs (if needed)
docker exec spark-master bash -c "kill \$(pgrep -f stream_processor) 2>/dev/null; kill \$(pgrep -f cassandra_writer) 2>/dev/null"

# Remove all services
docker-compose -f docker-compose.generator.yml down
docker-compose -f docker-compose.spark.yml down
docker-compose -f docker-compose.cassandra.yml down -v   # -v removes Cassandra data volume
docker-compose -f docker-compose.kafka.yml down -v

# Remove network
docker network rm hw10-network
```

---

## Troubleshooting

| Problem | Fix |
|---------|-----|
| `kafka-init` exits immediately | Kafka not healthy yet — run `docker-compose -f docker-compose.kafka.yml up kafka-init` again |
| `cassandra-init` keeps waiting | Cassandra needs more time — wait 2 min, then check `docker logs cassandra` |
| Spark submit hangs on packages | Maven download in progress — check logs, wait |
| No data in Cassandra | Confirm `processed` topic has messages first; check `cassandra_writer.log` for errors |