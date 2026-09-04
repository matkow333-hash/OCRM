-- Schema Postgres dla aplikacji OCRM. Odpowiednik schemy SQLite skanera.
-- Uruchamiana przez `npm run migrate`, idempotentna.

CREATE TABLE IF NOT EXISTS listings (
  id                BIGSERIAL PRIMARY KEY,
  source            TEXT NOT NULL,
  source_id         TEXT NOT NULL,
  url               TEXT NOT NULL,
  deal_type         TEXT NOT NULL,
  city              TEXT,
  district          TEXT,
  street            TEXT,
  price             BIGINT,
  area_m2           REAL,
  rooms             INTEGER,
  floor             INTEGER,
  title             TEXT,
  description       TEXT,
  content_hash      TEXT,
  phone_e164        TEXT,
  seller_type       TEXT NOT NULL DEFAULT 'unknown',
  agency_score      REAL NOT NULL DEFAULT 0,
  dedup_group       TEXT,
  first_seen_at     TIMESTAMPTZ NOT NULL,
  last_seen_at      TIMESTAMPTZ NOT NULL,
  is_active         BOOLEAN NOT NULL DEFAULT TRUE,
  UNIQUE (source, source_id)
);

CREATE TABLE IF NOT EXISTS contacts (
  id                BIGSERIAL PRIMARY KEY,
  phone_e164        TEXT NOT NULL UNIQUE,
  name              TEXT,
  do_not_call       BOOLEAN NOT NULL DEFAULT FALSE,
  do_not_call_at    TIMESTAMPTZ,
  note              TEXT,
  created_at        TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS leads (
  id                BIGSERIAL PRIMARY KEY,
  contact_id        BIGINT NOT NULL REFERENCES contacts(id) ON DELETE CASCADE,
  listing_id        BIGINT REFERENCES listings(id) ON DELETE SET NULL,
  status            TEXT NOT NULL DEFAULT 'new',
  next_step         TEXT,
  next_step_at      TIMESTAMPTZ,
  lost_reason       TEXT,
  contract_ends_at  TIMESTAMPTZ,
  created_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE (contact_id, listing_id)
);

CREATE TABLE IF NOT EXISTS call_log (
  id                BIGSERIAL PRIMARY KEY,
  lead_id           BIGINT NOT NULL REFERENCES leads(id) ON DELETE CASCADE,
  called_at         TIMESTAMPTZ NOT NULL DEFAULT now(),
  outcome           TEXT NOT NULL,
  opener_used       TEXT,
  objection         TEXT,
  note              TEXT
);

CREATE TABLE IF NOT EXISTS daily_stats (
  day               DATE PRIMARY KEY,
  calls_made        INTEGER NOT NULL DEFAULT 0,
  target            INTEGER NOT NULL DEFAULT 10,
  meetings_booked   INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS debrief (
  day               DATE PRIMARY KEY,
  calls             INTEGER NOT NULL DEFAULT 0,
  stuck_phrase      TEXT,
  tomorrow_fix      TEXT,
  created_at        TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS scan_log (
  id                BIGSERIAL PRIMARY KEY,
  source            TEXT NOT NULL,
  started_at        TIMESTAMPTZ NOT NULL,
  finished_at       TIMESTAMPTZ,
  pages             INTEGER,
  found             INTEGER,
  new               INTEGER,
  status            TEXT NOT NULL,
  detail            TEXT
);

CREATE INDEX IF NOT EXISTS idx_listings_phone ON listings (phone_e164);
CREATE INDEX IF NOT EXISTS idx_listings_active ON listings (is_active, seller_type);
CREATE INDEX IF NOT EXISTS idx_listings_seen ON listings (first_seen_at DESC);
CREATE INDEX IF NOT EXISTS idx_listings_dedup ON listings (dedup_group);
CREATE INDEX IF NOT EXISTS idx_leads_next_step ON leads (next_step_at);
CREATE INDEX IF NOT EXISTS idx_leads_status ON leads (status);
CREATE INDEX IF NOT EXISTS idx_call_log_lead ON call_log (lead_id, called_at DESC);
