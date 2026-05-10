-- hw5 MySQL schema
-- Simplified from hw1/ddl.sql — only the tables the three API endpoints touch.
-- Trailing-comma syntax errors from the hw1 skeleton are fixed here.

USE ad_analytics;

CREATE TABLE IF NOT EXISTS advertisers (
    advertiser_id INT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    name          VARCHAR(150) NOT NULL UNIQUE,
    country       VARCHAR(100)
);

CREATE TABLE IF NOT EXISTS campaigns (
    campaign_id   INT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    advertiser_id INT UNSIGNED NOT NULL,
    campaign_name VARCHAR(100) NOT NULL,
    start_date    DATE,
    end_date      DATE,
    budget        DECIMAL(12,2) NOT NULL DEFAULT 0.00,
    CONSTRAINT fk_camp_adv FOREIGN KEY (advertiser_id)
        REFERENCES advertisers(advertiser_id)
);

CREATE TABLE IF NOT EXISTS users (
    user_id     INT UNSIGNED PRIMARY KEY,
    age         TINYINT UNSIGNED,
    gender      VARCHAR(10),
    signup_date DATE
);

CREATE TABLE IF NOT EXISTS ad_events (
    event_id        CHAR(36)      PRIMARY KEY,
    campaign_id     INT UNSIGNED  NOT NULL,
    user_id         INT UNSIGNED,
    timestamp       DATETIME      NOT NULL,
    ad_cost         DECIMAL(10,2),
    was_clicked     TINYINT(1)    NOT NULL DEFAULT 0,
    click_timestamp DATETIME,
    ad_revenue      DECIMAL(10,2),
    CONSTRAINT fk_ev_camp FOREIGN KEY (campaign_id) REFERENCES campaigns(campaign_id),
    CONSTRAINT fk_ev_user FOREIGN KEY (user_id)     REFERENCES users(user_id)
);

CREATE INDEX idx_ae_campaign ON ad_events(campaign_id);
CREATE INDEX idx_ae_user     ON ad_events(user_id);