-- ============================================
-- ANTIKYTHERA F1 VIDEO GENERATOR
-- Running Gags & Character History System
-- Version: 005
-- Date: 2026-02-06
-- ============================================
-- Tracks running jokes, character gags, and memorable
-- events that carry across races throughout the season.
-- Examples: Lance Stroll's dad paying for everything,
-- Fernando's incidents referenced 5 races later.
-- ============================================

-- ============================================
-- GAG STATUS ENUM
-- ============================================

DO $$ BEGIN
    CREATE TYPE gag_status AS ENUM ('active', 'cooling_down', 'exhausted', 'retired');
EXCEPTION
    WHEN duplicate_object THEN null;
END $$;

DO $$ BEGIN
    CREATE TYPE gag_category AS ENUM (
        'personality_trait',    -- Ongoing character trait (Toto's rage, Lando's humor)
        'incident',            -- Specific event that can be referenced (crash, mistake, radio outburst)
        'rivalry',             -- Ongoing rivalry between characters
        'catchphrase',         -- Recurring phrase or verbal tic
        'running_joke',        -- Pure comedy bit that repeats
        'relationship',        -- Ongoing dynamic between characters
        'legacy'               -- Historical reference (past championships, career moves)
    );
EXCEPTION
    WHEN duplicate_object THEN null;
END $$;

-- ============================================
-- RUNNING_GAGS TABLE
-- ============================================

CREATE TABLE IF NOT EXISTS running_gags (
    id SERIAL PRIMARY KEY,

    -- Core gag definition
    title VARCHAR(200) NOT NULL,
    description TEXT NOT NULL,
    category gag_category NOT NULL DEFAULT 'running_joke',

    -- Character associations (can involve 1-2 characters)
    primary_character_id INTEGER REFERENCES characters(id),
    secondary_character_id INTEGER REFERENCES characters(id),

    -- Comedy details
    setup TEXT,              -- How to set up the joke
    punchline TEXT,          -- The payoff
    variations TEXT,         -- Different ways to deliver it
    context_needed TEXT,     -- What context makes this gag relevant

    -- Origin
    origin_race VARCHAR(100),       -- Which race/event created this gag
    origin_episode_id INTEGER REFERENCES episodes(id),
    origin_date DATE,
    origin_description TEXT,        -- What actually happened

    -- Usage tracking
    status gag_status DEFAULT 'active',
    times_used INTEGER DEFAULT 0,
    max_uses INTEGER,               -- NULL = unlimited
    cooldown_races INTEGER DEFAULT 2,  -- Min races between uses
    last_used_in_episode_id INTEGER REFERENCES episodes(id),
    last_used_at TIMESTAMP,
    last_used_in_race VARCHAR(100),

    -- Relevance
    humor_rating INTEGER DEFAULT 5,    -- 1-10, how funny is this gag
    audience_familiarity INTEGER DEFAULT 1,  -- 1-10, how well known (increases with use)

    -- Metadata
    tags TEXT[],            -- Searchable tags
    is_active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_running_gags_primary_char ON running_gags(primary_character_id);
CREATE INDEX IF NOT EXISTS idx_running_gags_secondary_char ON running_gags(secondary_character_id);
CREATE INDEX IF NOT EXISTS idx_running_gags_status ON running_gags(status);
CREATE INDEX IF NOT EXISTS idx_running_gags_category ON running_gags(category);
CREATE INDEX IF NOT EXISTS idx_running_gags_active ON running_gags(is_active) WHERE is_active = TRUE;

COMMENT ON TABLE running_gags IS 'Running jokes and character gags that carry across races throughout the F1 season';

-- ============================================
-- GAG_USAGE TABLE
-- ============================================
-- Tracks every time a gag is used in an episode

CREATE TABLE IF NOT EXISTS gag_usage (
    id SERIAL PRIMARY KEY,
    gag_id INTEGER NOT NULL REFERENCES running_gags(id) ON DELETE CASCADE,
    episode_id INTEGER NOT NULL REFERENCES episodes(id) ON DELETE CASCADE,
    scene_id INTEGER REFERENCES episode_scenes(id),

    -- How it was used
    usage_context TEXT,     -- Brief description of how the gag was used
    dialogue_excerpt TEXT,  -- The actual line that referenced the gag

    -- Audience reaction tracking (for future use)
    effectiveness_rating INTEGER,  -- 1-10, post-publish assessment

    created_at TIMESTAMP DEFAULT NOW(),

    UNIQUE(gag_id, episode_id, scene_id)
);

CREATE INDEX IF NOT EXISTS idx_gag_usage_gag ON gag_usage(gag_id);
CREATE INDEX IF NOT EXISTS idx_gag_usage_episode ON gag_usage(episode_id);

COMMENT ON TABLE gag_usage IS 'Tracks every instance of a running gag being used in an episode';

-- ============================================
-- MIGRATION RECORD
-- ============================================

INSERT INTO schema_migrations (version, description)
VALUES ('005', 'Running gags and character history system for cross-race comedy continuity')
ON CONFLICT (version) DO NOTHING;
