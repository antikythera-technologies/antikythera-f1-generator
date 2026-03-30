-- Migration 006: Add post-qualifying episode type and trigger type
-- Every non-sprint weekend now produces 2 videos: post-qualifying + post-race
-- Sprint weekends remain: post-sprint + post-race

-- Add post-qualifying to episode_type enum
ALTER TYPE episode_type ADD VALUE IF NOT EXISTS 'post-qualifying';

-- Add post-qualifying to job_trigger_type enum
ALTER TYPE job_trigger_type ADD VALUE IF NOT EXISTS 'post-qualifying';
