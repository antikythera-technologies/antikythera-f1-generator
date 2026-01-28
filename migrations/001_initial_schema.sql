-- ============================================
-- ANTIKYTHERA F1 VIDEO GENERATOR
-- Initial Database Schema Migration
-- Version: 001
-- Date: 2025-01-28
-- ============================================

-- Run this against database: AntikytheraF1Series
-- Host: postgres.antikythera.co.za:5432

-- NOTE: Table 'episode_scenes' used instead of 'scenes' to avoid 
-- conflict with existing 'scenes' table in this database.

-- ============================================
-- ENUM TYPES
-- ============================================

DO $$ BEGIN
    CREATE TYPE episode_type AS ENUM ('pre-race', 'post-race');
EXCEPTION
    WHEN duplicate_object THEN null;
END $$;

DO $$ BEGIN
    CREATE TYPE episode_status AS ENUM ('pending', 'generating', 'stitching', 'uploading', 'published', 'failed');
EXCEPTION
    WHEN duplicate_object THEN null;
END $$;

DO $$ BEGIN
    CREATE TYPE scene_status AS ENUM ('pending', 'generating', 'completed', 'failed');
EXCEPTION
    WHEN duplicate_object THEN null;
END $$;

DO $$ BEGIN
    CREATE TYPE log_level AS ENUM ('DEBUG', 'INFO', 'WARN', 'ERROR');
EXCEPTION
    WHEN duplicate_object THEN null;
END $$;

DO $$ BEGIN
    CREATE TYPE log_component AS ENUM ('trigger', 'script', 'image', 'video', 'stitch', 'upload', 'cleanup');
EXCEPTION
    WHEN duplicate_object THEN null;
END $$;

DO $$ BEGIN
    CREATE TYPE api_provider AS ENUM ('anthropic', 'ovi', 'youtube', 'minio', 'nano_banana');
EXCEPTION
    WHEN duplicate_object THEN null;
END $$;

-- ============================================
-- CHARACTERS TABLE
-- ============================================
-- Stores character metadata and reference images
-- ============================================

CREATE TABLE IF NOT EXISTS characters (
    id SERIAL PRIMARY KEY,
    name VARCHAR(100) NOT NULL UNIQUE,
    display_name VARCHAR(100) NOT NULL,
    description TEXT,
    voice_description VARCHAR(255),  -- e.g., "British male, confident, deep"
    personality TEXT,                -- For script generation context
    primary_image_path VARCHAR(500), -- MinIO path to main reference image
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW(),
    is_active BOOLEAN DEFAULT TRUE
);

-- Index for active character queries
CREATE INDEX IF NOT EXISTS idx_characters_active ON characters(is_active) WHERE is_active = TRUE;

COMMENT ON TABLE characters IS 'F1 character definitions with voice/personality for consistent generation';

-- ============================================
-- CHARACTER_IMAGES TABLE
-- ============================================
-- Multiple reference images per character for variety
-- ============================================

CREATE TABLE IF NOT EXISTS character_images (
    id SERIAL PRIMARY KEY,
    character_id INTEGER NOT NULL REFERENCES characters(id) ON DELETE CASCADE,
    image_path VARCHAR(500) NOT NULL,  -- MinIO path
    image_type VARCHAR(50) DEFAULT 'reference',  -- reference, action, emotion
    pose_description VARCHAR(255),
    is_primary BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_character_images_char ON character_images(character_id);

COMMENT ON TABLE character_images IS 'Multiple reference images per character for variety in scene generation';

-- ============================================
-- RACES TABLE
-- ============================================
-- F1 race calendar and metadata
-- ============================================

CREATE TABLE IF NOT EXISTS races (
    id SERIAL PRIMARY KEY,
    season INTEGER NOT NULL,
    round_number INTEGER NOT NULL,
    race_name VARCHAR(100) NOT NULL,
    circuit_name VARCHAR(100),
    country VARCHAR(100),
    race_date DATE NOT NULL,
    fp1_datetime TIMESTAMP,
    fp2_datetime TIMESTAMP,
    fp3_datetime TIMESTAMP,
    qualifying_datetime TIMESTAMP,
    race_datetime TIMESTAMP,
    created_at TIMESTAMP DEFAULT NOW(),
    
    UNIQUE(season, round_number)
);

CREATE INDEX IF NOT EXISTS idx_races_date ON races(race_date);
CREATE INDEX IF NOT EXISTS idx_races_season ON races(season);

COMMENT ON TABLE races IS 'F1 race calendar - used for scheduling and content context';

-- ============================================
-- EPISODES TABLE
-- ============================================
-- Generated video episodes
-- ============================================

CREATE TABLE IF NOT EXISTS episodes (
    id SERIAL PRIMARY KEY,
    race_id INTEGER REFERENCES races(id),
    episode_type episode_type NOT NULL,
    title VARCHAR(255) NOT NULL,
    description TEXT,
    status episode_status DEFAULT 'pending',
    
    -- Timing
    triggered_at TIMESTAMP DEFAULT NOW(),
    generation_started_at TIMESTAMP,
    generation_completed_at TIMESTAMP,
    upload_started_at TIMESTAMP,
    published_at TIMESTAMP,
    
    -- Output
    final_video_path VARCHAR(500),  -- MinIO path
    youtube_video_id VARCHAR(50),
    youtube_url VARCHAR(255),
    
    -- Metrics
    duration_seconds INTEGER,
    scene_count INTEGER DEFAULT 24,
    generation_time_seconds INTEGER,
    
    -- Cost tracking
    anthropic_tokens_used INTEGER DEFAULT 0,
    anthropic_cost_usd DECIMAL(10, 6) DEFAULT 0,
    ovi_calls INTEGER DEFAULT 0,
    total_cost_usd DECIMAL(10, 6) DEFAULT 0,
    
    -- Error handling
    retry_count INTEGER DEFAULT 0,
    last_error TEXT,
    
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_episodes_race ON episodes(race_id);
CREATE INDEX IF NOT EXISTS idx_episodes_status ON episodes(status);
CREATE INDEX IF NOT EXISTS idx_episodes_type ON episodes(episode_type);

COMMENT ON TABLE episodes IS 'Generated video episodes with full lifecycle tracking';

-- ============================================
-- EPISODE_SCENES TABLE
-- ============================================
-- Individual scenes within an episode
-- NOTE: Named 'episode_scenes' to avoid conflict with existing 'scenes' table
-- ============================================

CREATE TABLE IF NOT EXISTS episode_scenes (
    id SERIAL PRIMARY KEY,
    episode_id INTEGER NOT NULL REFERENCES episodes(id) ON DELETE CASCADE,
    scene_number INTEGER NOT NULL,  -- 1-24
    
    -- Character info
    character_id INTEGER REFERENCES characters(id),
    character_image_id INTEGER REFERENCES character_images(id),
    
    -- Prompts (for traceability)
    script_prompt TEXT,           -- What Haiku was asked
    script_response TEXT,         -- What Haiku returned
    ovi_prompt TEXT,              -- Final prompt sent to Ovi
    
    -- Content
    dialogue TEXT,                -- Extracted speech content
    action_description TEXT,      -- What happens in scene
    audio_description TEXT,       -- Ambient audio description
    
    -- Output
    status scene_status DEFAULT 'pending',
    source_image_path VARCHAR(500),   -- MinIO path to input image
    video_clip_path VARCHAR(500),     -- MinIO path to 5-sec clip
    duration_seconds DECIMAL(5, 2) DEFAULT 5.0,
    
    -- Timing
    generation_started_at TIMESTAMP,
    generation_completed_at TIMESTAMP,
    generation_time_ms INTEGER,
    
    -- Error handling
    retry_count INTEGER DEFAULT 0,
    last_error TEXT,
    
    created_at TIMESTAMP DEFAULT NOW(),
    
    UNIQUE(episode_id, scene_number)
);

CREATE INDEX IF NOT EXISTS idx_episode_scenes_episode ON episode_scenes(episode_id);
CREATE INDEX IF NOT EXISTS idx_episode_scenes_status ON episode_scenes(status);
CREATE INDEX IF NOT EXISTS idx_episode_scenes_character ON episode_scenes(character_id);

COMMENT ON TABLE episode_scenes IS 'Individual 5-second scenes with full prompt traceability';

-- ============================================
-- GENERATION_LOGS TABLE
-- ============================================
-- Detailed logging for debugging and analysis
-- ============================================

CREATE TABLE IF NOT EXISTS generation_logs (
    id SERIAL PRIMARY KEY,
    episode_id INTEGER REFERENCES episodes(id) ON DELETE CASCADE,
    scene_id INTEGER REFERENCES episode_scenes(id) ON DELETE CASCADE,
    
    level log_level NOT NULL,
    component log_component NOT NULL,
    message TEXT NOT NULL,
    details JSONB,  -- Structured data (API responses, errors, timing)
    
    created_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_logs_episode ON generation_logs(episode_id);
CREATE INDEX IF NOT EXISTS idx_logs_scene ON generation_logs(scene_id);
CREATE INDEX IF NOT EXISTS idx_logs_level ON generation_logs(level);
CREATE INDEX IF NOT EXISTS idx_logs_component ON generation_logs(component);
CREATE INDEX IF NOT EXISTS idx_logs_created ON generation_logs(created_at);

COMMENT ON TABLE generation_logs IS 'Comprehensive logging for debugging and observability';

-- ============================================
-- API_USAGE TABLE
-- ============================================
-- Track all external API calls for cost analysis
-- ============================================

CREATE TABLE IF NOT EXISTS api_usage (
    id SERIAL PRIMARY KEY,
    episode_id INTEGER REFERENCES episodes(id) ON DELETE CASCADE,
    scene_id INTEGER REFERENCES episode_scenes(id) ON DELETE CASCADE,
    
    provider api_provider NOT NULL,
    endpoint VARCHAR(255),
    
    -- Request details
    request_payload_size INTEGER,  -- bytes
    
    -- Response details
    response_status INTEGER,
    response_time_ms INTEGER,
    
    -- Cost tracking (Anthropic specific)
    input_tokens INTEGER,
    output_tokens INTEGER,
    cost_usd DECIMAL(10, 6),
    
    created_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_api_usage_episode ON api_usage(episode_id);
CREATE INDEX IF NOT EXISTS idx_api_usage_provider ON api_usage(provider);
CREATE INDEX IF NOT EXISTS idx_api_usage_date ON api_usage(created_at);

COMMENT ON TABLE api_usage IS 'External API call tracking for cost analysis';

-- ============================================
-- CLEANUP_LOGS TABLE
-- ============================================
-- Track storage cleanup operations
-- ============================================

CREATE TABLE IF NOT EXISTS cleanup_logs (
    id SERIAL PRIMARY KEY,
    race_id INTEGER REFERENCES races(id),
    episode_id INTEGER REFERENCES episodes(id),
    
    files_deleted INTEGER,
    bytes_freed BIGINT,
    cleanup_type VARCHAR(50),  -- 'scene_images', 'video_clips', 'both'
    
    started_at TIMESTAMP,
    completed_at TIMESTAMP,
    
    created_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_cleanup_race ON cleanup_logs(race_id);

COMMENT ON TABLE cleanup_logs IS 'Storage cleanup audit trail';

-- ============================================
-- VIEWS
-- ============================================

-- Episode summary with costs
CREATE OR REPLACE VIEW episode_summary AS
SELECT 
    e.id,
    e.title,
    e.episode_type,
    e.status,
    r.race_name,
    r.race_date,
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
    COUNT(s.id) FILTER (WHERE s.status = 'failed') as scenes_failed
FROM episodes e
LEFT JOIN races r ON e.race_id = r.id
LEFT JOIN episode_scenes s ON e.id = s.episode_id
GROUP BY e.id, r.race_name, r.race_date;

COMMENT ON VIEW episode_summary IS 'Episode overview with race info and scene statistics';

-- Daily cost summary
CREATE OR REPLACE VIEW daily_cost_summary AS
SELECT 
    DATE(created_at) as date,
    provider,
    COUNT(*) as api_calls,
    SUM(cost_usd) as total_cost_usd,
    SUM(input_tokens) as total_input_tokens,
    SUM(output_tokens) as total_output_tokens,
    AVG(response_time_ms) as avg_response_time_ms
FROM api_usage
GROUP BY DATE(created_at), provider
ORDER BY date DESC, provider;

COMMENT ON VIEW daily_cost_summary IS 'Daily API usage and cost breakdown by provider';

-- ============================================
-- MIGRATION RECORD
-- ============================================

CREATE TABLE IF NOT EXISTS schema_migrations (
    version VARCHAR(50) PRIMARY KEY,
    applied_at TIMESTAMP DEFAULT NOW(),
    description TEXT
);

INSERT INTO schema_migrations (version, description) 
VALUES ('001', 'Initial video generator schema - characters, races, episodes, episode_scenes, logs, api_usage, cleanup_logs')
ON CONFLICT (version) DO NOTHING;
