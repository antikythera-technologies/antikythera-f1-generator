-- ============================================
-- ANTIKYTHERA F1 VIDEO GENERATOR
-- Character Caricature Traits Migration
-- Version: 004
-- Date: 2026-02-06
-- ============================================
-- Adds caricature-specific fields to characters table
-- for consistent satirical image generation with
-- reference image support (Nano Banana Pro / Gemini).
-- ============================================

-- ============================================
-- ADD CARICATURE TRAIT COLUMNS TO CHARACTERS
-- ============================================

-- Role in the F1 world
ALTER TABLE characters ADD COLUMN IF NOT EXISTS role VARCHAR(50);
COMMENT ON COLUMN characters.role IS 'F1 role: driver, team_principal, commentator, presenter, pundit, executive';

-- Team affiliation
ALTER TABLE characters ADD COLUMN IF NOT EXISTS team VARCHAR(100);
COMMENT ON COLUMN characters.team IS 'Team or organization name, e.g. Red Bull Racing, Sky Sports';

-- Nationality for likeness
ALTER TABLE characters ADD COLUMN IF NOT EXISTS nationality VARCHAR(100);
COMMENT ON COLUMN characters.nationality IS 'Nationality for facial likeness context';

-- Detailed physical features for likeness accuracy
ALTER TABLE characters ADD COLUMN IF NOT EXISTS physical_features TEXT;
COMMENT ON COLUMN characters.physical_features IS 'Detailed physical description: face shape, hair, eyes, skin tone, build, age, distinguishing marks';

-- Comedy angle - what makes this character funny
ALTER TABLE characters ADD COLUMN IF NOT EXISTS comedy_angle TEXT;
COMMENT ON COLUMN characters.comedy_angle IS 'The satirical/comedic angle: what personality trait or behavior to exaggerate';

-- Signature expression
ALTER TABLE characters ADD COLUMN IF NOT EXISTS signature_expression TEXT;
COMMENT ON COLUMN characters.signature_expression IS 'Their typical facial expression in the caricature, e.g. screaming rage, devilish smirk';

-- Signature pose and action
ALTER TABLE characters ADD COLUMN IF NOT EXISTS signature_pose TEXT;
COMMENT ON COLUMN characters.signature_pose IS 'Their typical pose/action, e.g. slamming fists on table, holding stopwatch';

-- Props they hold or interact with
ALTER TABLE characters ADD COLUMN IF NOT EXISTS props TEXT;
COMMENT ON COLUMN characters.props IS 'Props in the image, e.g. stopwatch, headphones, table';

-- Background style
ALTER TABLE characters ADD COLUMN IF NOT EXISTS background_type VARCHAR(50) DEFAULT 'orange_gradient';
COMMENT ON COLUMN characters.background_type IS 'Background type: orange_gradient, team_logo, custom';

-- Background detail for custom backgrounds
ALTER TABLE characters ADD COLUMN IF NOT EXISTS background_detail TEXT;
COMMENT ON COLUMN characters.background_detail IS 'Specific background description if not standard orange gradient';

-- Clothing description
ALTER TABLE characters ADD COLUMN IF NOT EXISTS clothing_description TEXT;
COMMENT ON COLUMN characters.clothing_description IS 'What they wear: racing suit, team polo, broadcast suit. Include team colors and sponsor logos.';

-- The full assembled prompt (saved for reproducibility)
ALTER TABLE characters ADD COLUMN IF NOT EXISTS caricature_prompt TEXT;
COMMENT ON COLUMN characters.caricature_prompt IS 'The complete assembled generation prompt, saved so we can reproduce the exact same image';

-- ============================================
-- ADD STYLE REFERENCE SUPPORT TO CHARACTER_IMAGES
-- ============================================

-- Add a 'style_reference' image type option
-- (existing image_type column already supports arbitrary strings,
--  but let's add a flag for images used as style references)
ALTER TABLE character_images ADD COLUMN IF NOT EXISTS is_style_reference BOOLEAN DEFAULT FALSE;
COMMENT ON COLUMN character_images.is_style_reference IS 'If true, this image is used as a style reference for generating other characters';

-- ============================================
-- MIGRATION RECORD
-- ============================================

INSERT INTO schema_migrations (version, description)
VALUES ('004', 'Add caricature trait columns to characters table for satirical image generation with reference image support')
ON CONFLICT (version) DO NOTHING;
