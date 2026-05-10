import json
import time
import logging
import requests
import sseclient
from kafka import KafkaProducer

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s %(levelname)s %(message)s',
)
logger = logging.getLogger(__name__)

KAFKA_BOOTSTRAP = 'kafka:9092'
INPUT_TOPIC = 'input'
STREAM_URL = 'https://stream.wikimedia.org/v2/stream/page-create'


def create_producer() -> KafkaProducer:
    while True:
        try:
            producer = KafkaProducer(
                bootstrap_servers=KAFKA_BOOTSTRAP,
                value_serializer=lambda v: json.dumps(v).encode('utf-8'),
                retries=5,
            )
            logger.info("Connected to Kafka at %s", KAFKA_BOOTSTRAP)
            return producer
        except Exception as exc:
            logger.warning("Kafka not ready (%s), retrying in 5s...", exc)
            time.sleep(5)


def main() -> None:
    producer = create_producer()

    while True:
        try:
            logger.info("Connecting to Wikipedia stream: %s", STREAM_URL)
            response = requests.get(STREAM_URL, stream=True, timeout=60)
            response.raise_for_status()
            client = sseclient.SSEClient(response)

            for event in client.events():
                if not event.data or not event.data.strip():
                    continue
                try:
                    data = json.loads(event.data)
                    producer.send(INPUT_TOPIC, value=data)
                    domain = data.get('meta', {}).get('domain', 'unknown')
                    title = data.get('page_title', 'unknown')
                    logger.info("[%s] %s", domain, title)
                except json.JSONDecodeError:
                    pass
                except Exception as exc:
                    logger.error("Failed to send message: %s", exc)

        except Exception as exc:
            logger.error("Stream error: %s — reconnecting in 5s...", exc)
            time.sleep(5)


if __name__ == '__main__':
    main()