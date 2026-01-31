-- ============================================
-- ANTIKYTHERA F1 VIDEO GENERATOR
-- Fix F1.com RSS Feed URL
-- Version: 003
-- Date: 2026-01-31
-- ============================================

-- F1.com changed their RSS URL structure (301 redirect to new location)
-- Old: https://www.formula1.com/content/fom-website/en/latest.xml
-- New: https://www.formula1.com/en/latest/all.xml

UPDATE news_sources 
SET feed_url = 'https://www.formula1.com/en/latest/all.xml'
WHERE name = 'Formula1.com' 
AND feed_url = 'https://www.formula1.com/content/fom-website/en/latest.xml';

-- Also update the main URL to match
UPDATE news_sources 
SET url = 'https://www.formula1.com/en/latest/all'
WHERE name = 'Formula1.com';

-- Log this migration
INSERT INTO schema_migrations (version, description) 
VALUES ('003', 'Fix F1.com RSS feed URL after site restructure')
ON CONFLICT (version) DO NOTHING;
