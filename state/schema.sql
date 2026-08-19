-- Harvest state database schema.
--
-- The live database (state/harvest.db) is gitignored and auto-created from this
-- file on first run. This schema is the committed, blank starting point so every
-- clone of the harvester begins with an empty, well-defined DB; each instance's
-- real rows stay local (ignored) to that instance.
--
-- All statements are IF NOT EXISTS so re-running against an existing DB is a
-- safe no-op (acts as a lightweight migration).

CREATE TABLE IF NOT EXISTS emails (
    message_id        TEXT PRIMARY KEY,   -- RFC822 Message-ID (stable across runs)
    subject           TEXT,
    sender            TEXT,
    recipient         TEXT,
    email_date        TEXT,               -- raw Date header
    mailbox           TEXT,
    was_unread        INTEGER,            -- 1 if unread when first accessed, else 0
    first_accessed_at TEXT NOT NULL       -- ISO timestamp this tool first saw it
);

CREATE TABLE IF NOT EXISTS downloads (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    message_id       TEXT NOT NULL,
    filename         TEXT NOT NULL,
    saved_path       TEXT,
    size_bytes       INTEGER,
    sha256           TEXT,
    downloaded_at    TEXT NOT NULL,       -- ISO timestamp of download
    processed_at     TEXT,               -- NULL until the downstream sync marks it processed
    processed_result TEXT,                -- free-text outcome recorded by --mark-processed
    FOREIGN KEY (message_id) REFERENCES emails(message_id)
);

CREATE INDEX IF NOT EXISTS idx_downloads_message ON downloads(message_id);
CREATE INDEX IF NOT EXISTS idx_downloads_downloaded_at ON downloads(downloaded_at);
CREATE INDEX IF NOT EXISTS idx_downloads_saved_path ON downloads(saved_path);
