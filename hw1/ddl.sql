-- DICTIONARIES

CREATE TABLE IF NOT EXISTS advertisers (
    advertiser_id   INT UNSIGNED    AUTO_INCREMENT PRIMARY KEY,
    name            VARCHAR(150)    NOT NULL UNIQUE,
    country_id         VARCHAR(100)
);

CREATE TABLE IF NOT EXISTS locations (
    country_id     INT UNSIGNED    AUTO_INCREMENT PRIMARY KEY,
    country_name         VARCHAR(50)    NOT NULL,
);

CREATE TABLE IF NOT EXISTS interests (
    interest_id     INT UNSIGNED    AUTO_INCREMENT PRIMARY KEY,
    interest_name            VARCHAR(100)    NOT NULL UNIQUE,
);

CREATE TABLE IF NOT EXISTS devices (
    device_id       INT UNSIGNED    AUTO_INCREMENT PRIMARY KEY,
    device_name            VARCHAR(50)     NOT NULL UNIQUE   -- Mobile, Desktop, Tablet
);

CREATE TABLE IF NOT EXISTS ad_slot_sizes (
    slot_id         INT UNSIGNED    AUTO_INCREMENT PRIMARY KEY,
    width           INT UNSIGNED,
    height          INT UNSIGNED
);


-- CORE

CREATE TABLE IF NOT EXISTS campaigns (
    campaign_id         INT UNSIGNED    AUTO_INCREMENT PRIMARY KEY,
    advertiser_id       INT UNSIGNED    NOT NULL,
    slot_id             INT UNSIGNED,
    campaign_name                VARCHAR(100)    NOT NULL,
    start_date          DATE,
    end_date            DATE,
    target_age_range  VARCHAR(255),
    target_interest  VARCHAR(255),
    target_country_id VARCHAR(255),
    budget              DECIMAL(12,2)   NOT NULL DEFAULT 0.00,
    CONSTRAINT fk_camp_advertiser  FOREIGN KEY (advertiser_id) REFERENCES advertisers(advertiser_id),
    CONSTRAINT fk_camp_slot        FOREIGN KEY (slot_id)       REFERENCES ad_slot_sizes(slot_id)
);

CREATE TABLE IF NOT EXISTS users (
    user_id         INT UNSIGNED    PRIMARY KEY,      -- kept as-is from source CSV
    age             TINYINT UNSIGNED,
    gender          VARCHAR(10),
    country_id      INT,
    signup_date     DATE
);

-- JUNCTION

CREATE TABLE IF NOT EXISTS user_interests (
    user_id         INT UNSIGNED    NOT NULL,
    interest_id     INT UNSIGNED    NOT NULL,
    PRIMARY KEY (user_id, interest_id),
    CONSTRAINT fk_ui_user     FOREIGN KEY (user_id)     REFERENCES users(user_id)     ON DELETE CASCADE,
    CONSTRAINT fk_ui_interest FOREIGN KEY (interest_id) REFERENCES interests(interest_id) ON DELETE CASCADE
);

-- EVENT

CREATE TABLE IF NOT EXISTS ad_events (
    event_id            CHAR(36)        PRIMARY KEY,           -- UUID IF POSSIBLE IN DB VERSION
    campaign_id         INT UNSIGNED    NOT NULL,
    user_id             INT UNSIGNED,
    location_id         INT UNSIGNED,
    device_id           INT UNSIGNED,
    timestamp           DATETIME        NOT NULL,
    bid_amount          DECIMAL(10,2),
    ad_cost             DECIMAL(10,2),
    was_clicked         BOOLEAN         NOT NULL DEFAULT FALSE,
    click_timestamp     DATETIME,
    ad_revenue          DECIMAL(10,2),
    CONSTRAINT fk_event_campaign  FOREIGN KEY (campaign_id) REFERENCES campaigns(campaign_id),
    CONSTRAINT fk_event_user      FOREIGN KEY (user_id)     REFERENCES users(user_id),
);