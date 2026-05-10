CREATE KEYSPACE IF NOT EXISTS wiki
WITH replication = {'class': 'SimpleStrategy', 'replication_factor': 1};

CREATE TABLE IF NOT EXISTS wiki.page_creates (
    domain     TEXT,
    created_at TIMESTAMP,
    page_title TEXT,
    user_id    BIGINT,
    PRIMARY KEY ((domain), created_at, page_title)
) WITH CLUSTERING ORDER BY (created_at DESC);