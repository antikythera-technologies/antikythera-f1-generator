# Character Assets Documentation

## Overview

This document describes the 3D character assets used for Antikythera F1 video generation. These are pre-rendered Pixar/DreamWorks-style CGI character images that serve as the visual foundation for AI-generated video content.

## Asset Location

**Windows Path:**
```
C:\Users\WianK\Desktop\Andre AI\F1\F1 Story Line\3D F1 Charracters\
```

**WSL Path:**
```
/mnt/c/Users/WianK/Desktop/Andre AI/F1/F1 Story Line/3D F1 Charracters/
```

## Directory Structure

```
3D F1 Charracters/
├── 09-24-2025-13-59-32_files_list/     # Main character images
│   ├── alessandro_alunni_bravi_kick_sauber.jpg
│   ├── alex_albon_williams.jpg
│   ├── andrea_kimi_antonelli_mercedes.jpg
│   ├── andrea_stella_mclaren.jpg
│   ├── ayao_komatsu_haas.jpg
│   ├── bruno_famin_alpine.jpg
│   ├── carlos_sainz_williams.jpg
│   ├── charles_leclerc_ferrari.jpg
│   ├── christian_horner_red_bull_racing.jpg
│   ├── esteban_ocon_haas.jpg
│   ├── fernando_alonso_aston_martin.jpg
│   ├── franco_colapinto_alpine.jpg
│   ├── fred_vasseur_ferrari.jpg
│   ├── gabriel_bortoleto_kick_sauber.jpg
│   ├── george_russell_mercedes.jpg
│   ├── isack_hadjar_racing_bulls.jpg
│   ├── james_vowles_williams.jpg
│   ├── lance_stroll_aston_martin.jpg
│   ├── lando_norris_mclaren.jpg
│   ├── laurent_mekies_racing_bulls.jpg
│   ├── lewis_hamilton_ferrari.jpg
│   ├── liam_lawson_racing_bulls.jpg
│   ├── max_verstappen_red_bull_racing.jpg
│   ├── mike_krack_aston_martin.jpg
│   ├── nico_hülkenberg_kick_sauber.jpg
│   ├── oliver_bearman_haas.jpg
│   ├── oscar_piastri_mclaren.jpg
│   └── ... (29+ characters total)
├── Clips/                               # Video clips
├── 09-24-2025-13-59-32_files_list.zip  # Original archive
├── Pistry Chrash.mp4                    # Crash clip
└── Verstappen smilesmp4.mp4             # Reaction clip
```

## Character Coverage

### 2026 Season Grid

| Team | Driver 1 | Driver 2 | Principal |
|------|----------|----------|-----------|
| Red Bull | Max Verstappen ✅ | Liam Lawson ✅ | Christian Horner ✅ |
| Ferrari | Lewis Hamilton ✅ | Charles Leclerc ✅ | Fred Vasseur ✅ |
| McLaren | Lando Norris ✅ | Oscar Piastri ✅ | Andrea Stella ✅ |
| Mercedes | George Russell ✅ | Kimi Antonelli ✅ | - |
| Aston Martin | Fernando Alonso ✅ | Lance Stroll ✅ | Mike Krack ✅ |
| Williams | Carlos Sainz ✅ | Alex Albon ✅ | James Vowles ✅ |
| Racing Bulls | Isack Hadjar ✅ | Liam Lawson* | Laurent Mekies ✅ |
| Kick Sauber | Nico Hülkenberg ✅ | Gabriel Bortoleto ✅ | Alessandro Bravi ✅ |
| Haas | Esteban Ocon ✅ | Oliver Bearman ✅ | Ayao Komatsu ✅ |
| Alpine | Franco Colapinto ✅ | Pierre Gasly* | Bruno Famin ✅ |

*Some characters may need to be generated/added

## Image Specifications

- **Format:** JPEG
- **Style:** Pixar/DreamWorks CGI, satirical caricatures
- **Resolution:** High-res (2-3MB per image)
- **Consistency:** All characters share the same art style for visual cohesion
- **Naming Convention:** `{firstname_lastname}_{team}.jpg`

## Usage in Video Generation

### Image-to-Video Pipeline

1. **Scene Description** → AI generates storyline with character assignments
2. **Character Selection** → System selects appropriate character image
3. **Image Processing** → Character image used as input to Ovi (image-to-video)
4. **Video Generation** → 5-second clips generated per scene
5. **Stitching** → ffmpeg combines clips into final 2-minute video

### Character Matching

The character system matches storyline characters to images using:
- Exact name match (primary)
- Team affiliation (fallback)
- Role (driver/principal)

## MinIO Storage

Production assets are uploaded to MinIO bucket:
- **Bucket:** `f1-characters`
- **Endpoint:** `s3.antikythera.co.za`

### Upload Script

```bash
# Upload all characters to MinIO
cd /home/wkoch/github-repos/antikythera-f1-generator
python scripts/upload_characters.py
```

## Adding New Characters

1. Generate/obtain new character image in matching style
2. Save to `09-24-2025-13-59-32_files_list/` with naming convention
3. Upload to MinIO `f1-characters` bucket
4. Add personality profile in `character-system/personalities/`

## Related Files

- `/character-system/CHARACTER-SYSTEM-DESIGN.md` - Full character system architecture
- `/character-system/personalities/` - Individual character personality profiles
- `/character-system/relationships/` - Character relationship definitions
- `/docs/VIDEO_GENERATION.md` - Video generation pipeline docs
