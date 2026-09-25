-- Migration 001: Initial schema (idempotent — managed by SQLAlchemy create_all)
-- This file documents the canonical schema for manual reference/restore.

-- Storage layer ----------------------------------------------------------------
CREATE TABLE IF NOT EXISTS page (
    id              VARCHAR(32) PRIMARY KEY,
    url             TEXT NOT NULL UNIQUE,
    canonical_url   TEXT NOT NULL,
    content_type    VARCHAR(255),
    status_code     INTEGER,
    etag            VARCHAR(255),
    last_modified   VARCHAR(255),
    content_hash    VARCHAR(64),
    archive_path    TEXT,
    last_fetched    TIMESTAMP WITH TIME ZONE,
    last_changed    TIMESTAMP WITH TIME ZONE,
    fetch_failures  INTEGER NOT NULL DEFAULT 0,
    is_complete     BOOLEAN NOT NULL DEFAULT TRUE,
    created_at      TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS ix_page_url            ON page (url);
CREATE INDEX IF NOT EXISTS ix_page_canonical_url ON page (canonical_url);
CREATE INDEX IF NOT EXISTS ix_page_content_hash  ON page (content_hash);
CREATE INDEX IF NOT EXISTS ix_page_last_changed  ON page (last_changed);

CREATE TABLE IF NOT EXISTS page_version (
    id            VARCHAR(32) PRIMARY KEY,
    page_id       VARCHAR(32) NOT NULL REFERENCES page(id) ON DELETE CASCADE,
    version_no    INTEGER NOT NULL,
    content_html  TEXT,
    content_text  TEXT,
    sha256        VARCHAR(64) NOT NULL,
    fetched_at    TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
    is_current    BOOLEAN NOT NULL DEFAULT FALSE,
    is_complete   BOOLEAN NOT NULL DEFAULT TRUE,
    byte_size     INTEGER,
    UNIQUE (page_id, version_no)
);
CREATE INDEX IF NOT EXISTS ix_page_version_page_id ON page_version (page_id);

CREATE TABLE IF NOT EXISTS asset (
    id            VARCHAR(32) PRIMARY KEY,
    page_id       VARCHAR(32) REFERENCES page(id) ON DELETE SET NULL,
    asset_url     TEXT NOT NULL UNIQUE,
    local_path    TEXT,
    content_type  VARCHAR(255),
    sha256        VARCHAR(64),
    size_bytes    INTEGER,
    fetched_at    TIMESTAMP WITH TIME ZONE
);

-- Semantic layer --------------------------------------------------------------
CREATE TABLE IF NOT EXISTS country_region (
    id          VARCHAR(32) PRIMARY KEY,
    name        VARCHAR(255) NOT NULL,
    slug        VARCHAR(255) NOT NULL UNIQUE,
    type        VARCHAR(50) NOT NULL,
    parent_id   VARCHAR(32) REFERENCES country_region(id),
    source_url  TEXT
);
CREATE INDEX IF NOT EXISTS ix_country_region_slug   ON country_region (slug);
CREATE INDEX IF NOT EXISTS ix_country_region_parent ON country_region (parent_id);

CREATE TABLE IF NOT EXISTS contest (
    id                  VARCHAR(32) PRIMARY KEY,
    country_region_id   VARCHAR(32) REFERENCES country_region(id),
    name                VARCHAR(255) NOT NULL,
    slug                VARCHAR(255) NOT NULL UNIQUE,
    category            VARCHAR(100),
    is_international    BOOLEAN NOT NULL DEFAULT FALSE,
    source_url          TEXT,
    archive_url         TEXT,
    page_id             VARCHAR(32) REFERENCES page(id),
    last_synced         TIMESTAMP WITH TIME ZONE,
    created_at          TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS ix_contest_country_region ON contest (country_region_id);
CREATE INDEX IF NOT EXISTS ix_contest_category       ON contest (category);

CREATE TABLE IF NOT EXISTS contest_year (
    id            VARCHAR(32) PRIMARY KEY,
    contest_id    VARCHAR(32) NOT NULL REFERENCES contest(id) ON DELETE CASCADE,
    year          INTEGER NOT NULL,
    round         VARCHAR(100),
    date          VARCHAR(50),
    duration      VARCHAR(50),
    problem_count INTEGER,
    source_url    TEXT,
    archive_url   TEXT,
    page_id       VARCHAR(32) REFERENCES page(id),
    last_synced   TIMESTAMP WITH TIME ZONE,
    UNIQUE (contest_id, year, round)
);
CREATE INDEX IF NOT EXISTS ix_contest_year_contest ON contest_year (contest_id);
CREATE INDEX IF NOT EXISTS ix_contest_year_year    ON contest_year (year);

CREATE TABLE IF NOT EXISTS problem_set (
    id               VARCHAR(32) PRIMARY KEY,
    contest_year_id  VARCHAR(32) NOT NULL REFERENCES contest_year(id) ON DELETE CASCADE,
    type             VARCHAR(50) NOT NULL,
    name             VARCHAR(255),
    source_url       TEXT NOT NULL,
    asset_id         VARCHAR(32) REFERENCES asset(id),
    archive_path     TEXT,
    last_synced      TIMESTAMP WITH TIME ZONE
);
CREATE INDEX IF NOT EXISTS ix_problem_set_year ON problem_set (contest_year_id);

CREATE TABLE IF NOT EXISTS problem (
    id                    VARCHAR(32) PRIMARY KEY,
    contest_year_id       VARCHAR(32) NOT NULL REFERENCES contest_year(id) ON DELETE CASCADE,
    number                VARCHAR(50),
    title                 VARCHAR(500),
    statement_html        TEXT,
    statement_text        TEXT,
    source_url            TEXT,
    archive_url           TEXT,
    page_id               VARCHAR(32) REFERENCES page(id),
    last_synced           TIMESTAMP WITH TIME ZONE,
    solution_available    BOOLEAN NOT NULL DEFAULT FALSE,
    discussion_available  BOOLEAN NOT NULL DEFAULT FALSE,
    archive_status        VARCHAR(50) NOT NULL DEFAULT 'not_archived',
    created_at            TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS ix_problem_contest_year ON problem (contest_year_id);
CREATE INDEX IF NOT EXISTS ix_problem_number        ON problem (number);
CREATE INDEX IF NOT EXISTS ix_problem_source_url   ON problem (source_url);

CREATE TABLE IF NOT EXISTS tag (
    id    VARCHAR(32) PRIMARY KEY,
    name  VARCHAR(100) NOT NULL UNIQUE,
    slug  VARCHAR(100) NOT NULL UNIQUE
);
CREATE INDEX IF NOT EXISTS ix_tag_slug ON tag (slug);

CREATE TABLE IF NOT EXISTS problem_tag (
    problem_id  VARCHAR(32) NOT NULL REFERENCES problem(id) ON DELETE CASCADE,
    tag_id      VARCHAR(32) NOT NULL REFERENCES tag(id) ON DELETE CASCADE,
    PRIMARY KEY (problem_id, tag_id)
);

CREATE TABLE IF NOT EXISTS discussion (
    id          VARCHAR(32) PRIMARY KEY,
    problem_id  VARCHAR(32) REFERENCES problem(id) ON DELETE CASCADE,
    page_id     VARCHAR(32) REFERENCES page(id) ON DELETE CASCADE,
    source_url  TEXT,
    title       VARCHAR(500),
    last_synced TIMESTAMP WITH TIME ZONE
);
CREATE INDEX IF NOT EXISTS ix_discussion_problem ON discussion (problem_id);

CREATE TABLE IF NOT EXISTS post (
    id             VARCHAR(32) PRIMARY KEY,
    discussion_id  VARCHAR(32) NOT NULL REFERENCES discussion(id) ON DELETE CASCADE,
    parent_post_id VARCHAR(32) REFERENCES post(id),
    author_name    VARCHAR(255),
    posted_at      TIMESTAMP WITH TIME ZONE,
    content_html   TEXT,
    content_text   TEXT,
    source_url     TEXT,
    fetched_at     TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS ix_post_discussion ON post (discussion_id);
CREATE INDEX IF NOT EXISTS ix_post_posted_at  ON post (posted_at);

-- Crawl run metadata ----------------------------------------------------------
CREATE TABLE IF NOT EXISTS crawl_run (
    id                VARCHAR(32) PRIMARY KEY,
    started_at        TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
    finished_at       TIMESTAMP WITH TIME ZONE,
    status            VARCHAR(20) NOT NULL DEFAULT 'running',
    trigger           VARCHAR(20) NOT NULL DEFAULT 'manual',
    pages_discovered  INTEGER NOT NULL DEFAULT 0,
    pages_new         INTEGER NOT NULL DEFAULT 0,
    pages_changed     INTEGER NOT NULL DEFAULT 0,
    pages_unchanged   INTEGER NOT NULL DEFAULT 0,
    pages_failed      INTEGER NOT NULL DEFAULT 0,
    pages_blocked     INTEGER NOT NULL DEFAULT 0,
    bytes_downloaded  INTEGER NOT NULL DEFAULT 0,
    error_message     TEXT,
    dry_run           BOOLEAN NOT NULL DEFAULT FALSE
);
CREATE INDEX IF NOT EXISTS ix_crawl_run_started ON crawl_run (started_at);
CREATE INDEX IF NOT EXISTS ix_crawl_run_status  ON crawl_run (status);

CREATE TABLE IF NOT EXISTS crawl_error (
    id             VARCHAR(32) PRIMARY KEY,
    crawl_run_id   VARCHAR(32) NOT NULL REFERENCES crawl_run(id) ON DELETE CASCADE,
    url            TEXT NOT NULL,
    error_type     VARCHAR(100) NOT NULL,
    message        TEXT NOT NULL,
    http_status    INTEGER,
    occurred_at    TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
    retry_count    INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS ix_crawl_error_run ON crawl_error (crawl_run_id);

-- Blocked URLs — access-control mechanisms encountered during crawl.
-- NEVER bypassed; recorded so the crawler can continue and the user can see
-- what wasn't archived and why.
CREATE TABLE IF NOT EXISTS blocked_url (
    id                  VARCHAR(32) PRIMARY KEY,
    url                 TEXT NOT NULL UNIQUE,
    canonical_url       TEXT NOT NULL,
    reason              VARCHAR(50) NOT NULL,
    detail              TEXT,
    http_status         INTEGER,
    first_detected      TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
    last_attempted      TIMESTAMP WITH TIME ZONE,
    retry_count         INTEGER NOT NULL DEFAULT 0,
    last_crawl_run_id   VARCHAR(32) REFERENCES crawl_run(id) ON DELETE SET NULL
);
CREATE INDEX IF NOT EXISTS ix_blocked_url_url      ON blocked_url (url);
CREATE INDEX IF NOT EXISTS ix_blocked_url_canon   ON blocked_url (canonical_url);
CREATE INDEX IF NOT EXISTS ix_blocked_url_reason  ON blocked_url (reason);
CREATE INDEX IF NOT EXISTS ix_blocked_url_first   ON blocked_url (first_detected);

-- Search index ----------------------------------------------------------------
CREATE TABLE IF NOT EXISTS search_doc (
    id           VARCHAR(32) PRIMARY KEY,
    doc_type     VARCHAR(20) NOT NULL,
    ref_id       VARCHAR(32) NOT NULL,
    title        VARCHAR(500),
    body         TEXT,
    contest_name VARCHAR(255),
    year         INTEGER,
    country      VARCHAR(255),
    tags         TEXT,
    url          TEXT,
    last_synced  TIMESTAMP WITH TIME ZONE,
    updated_at   TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (doc_type, ref_id)
);
CREATE INDEX IF NOT EXISTS ix_search_doc_type ON search_doc (doc_type);
CREATE INDEX IF NOT EXISTS ix_search_doc_ref  ON search_doc (ref_id);

-- Site Graph ------------------------------------------------------------------
-- Each resource the crawler discovers or archives is a SiteNode.
-- Typed directional relationships are stored in SiteEdge.
-- LocalUrlMapping tracks source → local URL for offline navigation.

CREATE TABLE IF NOT EXISTS site_node (
    id               VARCHAR(32) PRIMARY KEY,
    node_type        VARCHAR(50) NOT NULL,
    name             VARCHAR(500),
    slug             VARCHAR(500),
    source_url       TEXT,
    local_url        TEXT,
    page_id          VARCHAR(32) REFERENCES page(id),
    asset_id         VARCHAR(32) REFERENCES asset(id),
    contest_id       VARCHAR(32) REFERENCES contest(id),
    contest_year_id  VARCHAR(32) REFERENCES contest_year(id),
    problem_id       VARCHAR(32) REFERENCES problem(id),
    problem_set_id   VARCHAR(32) REFERENCES problem_set(id),
    discussion_id    VARCHAR(32) REFERENCES discussion(id),
    post_id          VARCHAR(32) REFERENCES post(id),
    status           VARCHAR(20) NOT NULL DEFAULT 'not_verified',
    first_seen       TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
    last_seen        TIMESTAMP WITH TIME ZONE,
    last_archived    TIMESTAMP WITH TIME ZONE,
    depth            INTEGER,
    UNIQUE (node_type, source_url)
);
CREATE INDEX IF NOT EXISTS ix_site_node_type       ON site_node (node_type);
CREATE INDEX IF NOT EXISTS ix_site_node_slug      ON site_node (slug);
CREATE INDEX IF NOT EXISTS ix_site_node_source_url ON site_node (source_url);
CREATE INDEX IF NOT EXISTS ix_site_node_status     ON site_node (status);
CREATE INDEX IF NOT EXISTS ix_site_node_status_type ON site_node (status, node_type);

CREATE TABLE IF NOT EXISTS site_edge (
    id              VARCHAR(32) PRIMARY KEY,
    source_node_id  VARCHAR(32) NOT NULL REFERENCES site_node(id) ON DELETE CASCADE,
    target_node_id  VARCHAR(32) NOT NULL REFERENCES site_node(id) ON DELETE CASCADE,
    edge_type       VARCHAR(50) NOT NULL,
    weight          INTEGER,
    discovered_at   TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (source_node_id, target_node_id, edge_type)
);
CREATE INDEX IF NOT EXISTS ix_site_edge_source     ON site_edge (source_node_id);
CREATE INDEX IF NOT EXISTS ix_site_edge_target     ON site_edge (target_node_id);
CREATE INDEX IF NOT EXISTS ix_site_edge_type       ON site_edge (edge_type);
CREATE INDEX IF NOT EXISTS ix_site_edge_type_source ON site_edge (edge_type, source_node_id);
CREATE INDEX IF NOT EXISTS ix_site_edge_type_target ON site_edge (edge_type, target_node_id);

CREATE TABLE IF NOT EXISTS local_url_mapping (
    id                   VARCHAR(32) PRIMARY KEY,
    source_url           TEXT NOT NULL UNIQUE,
    canonical_source_url TEXT NOT NULL,
    local_url            TEXT,
    node_id              VARCHAR(32) REFERENCES site_node(id),
    archived             BOOLEAN NOT NULL DEFAULT FALSE,
    last_updated         TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS ix_local_url_mapping_source   ON local_url_mapping (source_url);
CREATE INDEX IF NOT EXISTS ix_local_url_mapping_canon    ON local_url_mapping (canonical_source_url);
CREATE INDEX IF NOT EXISTS ix_local_url_mapping_archived ON local_url_mapping (archived);

-- SQLite FTS5 virtual table (no-op on PostgreSQL)
-- Created programmatically in database/session._init_sqlite_fts()
