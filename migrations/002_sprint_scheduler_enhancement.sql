-- ============================================
-- ANTIKYTHERA F1 VIDEO GENERATOR
-- Sprint Race & Scheduler Enhancement Migration
-- Version: 002
-- Date: 2026-01-29
-- ============================================

-- This migration adds:
-- 1. Sprint weekend support to races table
-- 2. Expanded episode types (post-fp2, post-sprint, post-race, weekly-recap)
-- 3. Scheduled jobs table for scheduler service
-- 4. News sources and articles tables

-- ============================================
-- UPDATE EPISODE_TYPE ENUM
-- ============================================

-- Add new episode types to the enum
ALTER TYPE episode_type ADD VALUE IF NOT EXISTS 'post-fp2';
ALTER TYPE episode_type ADD VALUE IF NOT EXISTS 'post-sprint';
ALTER TYPE episode_type ADD VALUE IF NOT EXISTS 'weekly-recap';

-- ============================================
-- ADD SPRINT FIELDS TO RACES TABLE
-- ============================================

ALTER TABLE races 
ADD COLUMN IF NOT EXISTS is_sprint_weekend BOOLEAN DEFAULT FALSE,
ADD COLUMN IF NOT EXISTS sprint_qualifying_datetime TIMESTAMP,
ADD COLUMN IF NOT EXISTS sprint_race_datetime TIMESTAMP;

-- Add index for sprint weekends
CREATE INDEX IF NOT EXISTS idx_races_sprint ON races(is_sprint_weekend) WHERE is_sprint_weekend = TRUE;

COMMENT ON COLUMN races.is_sprint_weekend IS 'Whether this race weekend includes a sprint race';
COMMENT ON COLUMN races.sprint_qualifying_datetime IS 'Sprint shootout qualifying time (usually Friday)';
COMMENT ON COLUMN races.sprint_race_datetime IS 'Sprint race time (usually Saturday)';

-- ============================================
-- SCHEDULED_JOBS TABLE
-- ============================================
-- Track scheduled episode generation jobs

DO $$ BEGIN
    CREATE TYPE job_status AS ENUM ('scheduled', 'running', 'completed', 'failed', 'cancelled');
EXCEPTION
    WHEN duplicate_object THEN null;
END $$;

DO $$ BEGIN
    CREATE TYPE job_trigger_type AS ENUM ('post-fp2', 'post-sprint', 'post-race', 'weekly-recap', 'manual');
EXCEPTION
    WHEN duplicate_object THEN null;
END $$;

CREATE TABLE IF NOT EXISTS scheduled_jobs (
    id SERIAL PRIMARY KEY,
    race_id INTEGER REFERENCES races(id),
    
    -- Job configuration
    trigger_type job_trigger_type NOT NULL,
    scheduled_for TIMESTAMP NOT NULL,
    description TEXT,
    
    -- Execution tracking
    status job_status DEFAULT 'scheduled',
    started_at TIMESTAMP,
    completed_at TIMESTAMP,
    
    -- Result tracking
    episode_id INTEGER REFERENCES episodes(id),
    error_message TEXT,
    retry_count INTEGER DEFAULT 0,
    max_retries INTEGER DEFAULT 3,
    
    -- Metadata
    scrape_context JSONB,  -- What news context to scrape
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_scheduled_jobs_status ON scheduled_jobs(status);
CREATE INDEX IF NOT EXISTS idx_scheduled_jobs_scheduled ON scheduled_jobs(scheduled_for);
CREATE INDEX IF NOT EXISTS idx_scheduled_jobs_race ON scheduled_jobs(race_id);

COMMENT ON TABLE scheduled_jobs IS 'Scheduled video generation jobs with trigger timing';

-- ============================================
-- NEWS_SOURCES TABLE
-- ============================================
-- F1 news sources for scraping

CREATE TABLE IF NOT EXISTS news_sources (
    id SERIAL PRIMARY KEY,
    name VARCHAR(100) NOT NULL,
    url VARCHAR(500) NOT NULL,
    feed_url VARCHAR(500),  -- RSS feed if available
    scrape_selector VARCHAR(255),  -- CSS selector for articles
    is_active BOOLEAN DEFAULT TRUE,
    priority INTEGER DEFAULT 5,  -- 1-10, higher = more important
    last_scraped_at TIMESTAMP,
    created_at TIMESTAMP DEFAULT NOW()
);

-- Seed initial news sources
INSERT INTO news_sources (name, url, feed_url, priority) VALUES
    ('Formula1.com', 'https://www.formula1.com/en/latest/all', 'https://www.formula1.com/en/latest/all.xml', 10),
    ('Motorsport.com', 'https://www.motorsport.com/f1/news/', NULL, 9),
    ('Autosport', 'https://www.autosport.com/f1/news/', NULL, 8),
    ('RaceFans', 'https://www.racefans.net/category/f1-news/', NULL, 7),
    ('PlanetF1', 'https://www.planetf1.com/news/', NULL, 6),
    ('The Race', 'https://the-race.com/formula-1/', NULL, 8),
    ('GPFans', 'https://www.gpfans.com/en/f1-news/', NULL, 5)
ON CONFLICT DO NOTHING;

COMMENT ON TABLE news_sources IS 'F1 news sources for automated content scraping';

-- ============================================
-- NEWS_ARTICLES TABLE
-- ============================================
-- Scraped news articles cache

DO $$ BEGIN
    CREATE TYPE article_context AS ENUM ('race-weekend', 'off-week', 'breaking', 'feature');
EXCEPTION
    WHEN duplicate_object THEN null;
END $$;

CREATE TABLE IF NOT EXISTS news_articles (
    id SERIAL PRIMARY KEY,
    source_id INTEGER REFERENCES news_sources(id),
    
    -- Article content
    title VARCHAR(500) NOT NULL,
    url VARCHAR(1000) NOT NULL UNIQUE,
    summary TEXT,
    full_content TEXT,
    
    -- Categorization
    context article_context DEFAULT 'race-weekend',
    keywords TEXT[],  -- Array of extracted keywords
    mentioned_drivers TEXT[],  -- Driver names mentioned
    mentioned_teams TEXT[],  -- Team names mentioned
    sentiment_score DECIMAL(3, 2),  -- -1 to 1
    
    -- Usage tracking
    published_at TIMESTAMP,
    scraped_at TIMESTAMP DEFAULT NOW(),
    used_in_episode_id INTEGER REFERENCES episodes(id),
    used_at TIMESTAMP,
    
    -- Metadata
    is_processed BOOLEAN DEFAULT FALSE,
    processing_error TEXT,
    created_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_news_articles_source ON news_articles(source_id);
CREATE INDEX IF NOT EXISTS idx_news_articles_published ON news_articles(published_at);
CREATE INDEX IF NOT EXISTS idx_news_articles_context ON news_articles(context);
CREATE INDEX IF NOT EXISTS idx_news_articles_used ON news_articles(used_in_episode_id);
CREATE INDEX IF NOT EXISTS idx_news_articles_processed ON news_articles(is_processed);

COMMENT ON TABLE news_articles IS 'Cached news articles for content generation';

-- ============================================
-- EPISODE STORYLINE TABLE
-- ============================================
-- Track storyline development across episodes

CREATE TABLE IF NOT EXISTS episode_storylines (
    id SERIAL PRIMARY KEY,
    episode_id INTEGER NOT NULL REFERENCES episodes(id) ON DELETE CASCADE,
    
    -- Storyline metadata
    main_storyline TEXT NOT NULL,  -- Primary narrative thread
    secondary_storylines TEXT[],  -- Supporting narratives
    comedic_angle TEXT,  -- The satirical twist
    
    -- Source material
    news_article_ids INTEGER[],  -- Which articles informed this
    key_facts JSONB,  -- Extracted facts used
    
    -- Generation tracking
    prompt_used TEXT,  -- Full prompt sent to LLM
    model_used VARCHAR(100),
    tokens_used INTEGER,
    
    created_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_storylines_episode ON episode_storylines(episode_id);

COMMENT ON TABLE episode_storylines IS 'Storyline development and source tracking per episode';

-- ============================================
-- UPDATE EPISODE_SUMMARY VIEW
-- ============================================

CREATE OR REPLACE VIEW episode_summary AS
SELECT 
    e.id,
    e.title,
    e.episode_type,
    e.status,
    r.race_name,
    r.race_date,
    r.is_sprint_weekend,
    e.triggered_at,
    e.published_at,
    e.youtube_url,
    e.scene_count,
    e.generation_time_seconds,
    e.anthropic_tokens_used,
    e.anthropic_cost_usd,
    e.ovi_calls,
    e.total_cost_usd,
    COUNT(s.id) FILTER (WHERE s.status = 'completed') as scenes_completed,
    COUNT(s.id) FILTER (WHERE s.status = 'failed') as scenes_failed,
    sl.main_storyline
FROM episodes e
LEFT JOIN races r ON e.race_id = r.id
LEFT JOIN episode_scenes s ON e.id = s.episode_id
LEFT JOIN episode_storylines sl ON e.id = sl.episode_id
GROUP BY e.id, r.race_name, r.race_date, r.is_sprint_weekend, sl.main_storyline;

-- ============================================
-- SCHEDULER STATUS VIEW
-- ============================================

CREATE OR REPLACE VIEW scheduler_status AS
SELECT 
    sj.id,
    sj.trigger_type,
    sj.scheduled_for,
    sj.status,
    sj.description,
    r.race_name,
    r.country,
    r.is_sprint_weekend,
    e.title as episode_title,
    e.status as episode_status,
    e.youtube_url
FROM scheduled_jobs sj
LEFT JOIN races r ON sj.race_id = r.id
LEFT JOIN episodes e ON sj.episode_id = e.id
ORDER BY sj.scheduled_for DESC;

COMMENT ON VIEW scheduler_status IS 'Overview of scheduled and completed generation jobs';

-- ============================================
-- UPCOMING CONTENT VIEW
-- ============================================

CREATE OR REPLACE VIEW upcoming_content AS
SELECT 
    r.id as race_id,
    r.race_name,
    r.country,
    r.race_date,
    r.is_sprint_weekend,
    r.fp2_datetime,
    r.sprint_race_datetime,
    r.race_datetime,
    CASE 
        WHEN r.is_sprint_weekend THEN 3 
        ELSE 2 
    END as expected_episodes,
    COUNT(sj.id) as scheduled_jobs,
    COUNT(e.id) as episodes_generated
FROM races r
LEFT JOIN scheduled_jobs sj ON r.id = sj.race_id
LEFT JOIN episodes e ON r.id = e.race_id
WHERE r.race_date >= CURRENT_DATE - INTERVAL '1 day'
GROUP BY r.id
ORDER BY r.race_date ASC;

COMMENT ON VIEW upcoming_content IS 'Upcoming races with content generation status';

-- ============================================
-- MIGRATION RECORD
-- ============================================

INSERT INTO schema_migrations (version, description) 
VALUES ('002', 'Sprint race support, scheduler jobs, news scraping tables, storyline tracking')
ON CONFLICT (version) DO NOTHING;
