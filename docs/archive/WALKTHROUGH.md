# Antikythera F1 Video Generator - Complete Walkthrough

This guide walks you through the entire workflow for creating satirical F1 videos from start to finish.

## Table of Contents

1. [Overview](#overview)
2. [Storylines](#1-storylines)
3. [Episodes](#2-episodes)
4. [Characters](#3-characters)
5. [Scenes & Video Generation](#4-scenes--video-generation)
6. [Scheduler](#5-scheduler)
7. [Final Output](#6-final-output)
8. [Troubleshooting](#troubleshooting)

---

## Overview

### Pipeline Flow

```
NEWS SCRAPING → STORYLINE → EPISODE → 24 SCENES → VIDEO CLIPS → FINAL VIDEO → YOUTUBE
      ↓              ↓           ↓          ↓            ↓            ↓
   F1.com RSS    Claude AI   Database   Gemini +    Ovi Space    ffmpeg
                                         Ovi
```

### Access Points

| Service | URL | Purpose |
|---------|-----|---------|
| Dashboard | https://f1.antikythera.co.za | Main control interface |
| API Docs | https://f1.antikythera.co.za:8001/docs | Backend API documentation |
| MinIO | minio.antikythera.co.za:9000 | Asset storage |

---

## 1. Storylines

Storylines are the narrative foundation for episodes. They define the main plot and comedic angle.

### Creating a Storyline

1. Navigate to **Storylines** page in the dashboard
2. Click **"New Storyline"**
3. Fill in required fields:

| Field | Required | Description |
|-------|----------|-------------|
| Main Storyline | ✅ | Primary narrative (e.g., "Hamilton's first race at Ferrari") |
| Secondary Storylines | ❌ | Supporting narratives (array) |
| Comedic Angle | ❌ | The satirical twist |
| Key Facts | ❌ | JSON object with factual basis |

### Example Storyline

```json
{
  "main_storyline": "Max Verstappen dominates another weekend while Ferrari strategists struggle with basic mathematics",
  "secondary_storylines": [
    "Lando Norris continues his quest for first win",
    "Alonso reminds everyone he's still got it"
  ],
  "comedic_angle": "Ferrari pit wall becomes a comedy of errors"
}
```

### Storyline Sources

Storylines can be:
- **Manual**: Created by hand in the dashboard
- **Auto-generated**: Created from scraped news articles by Claude AI
- **Hybrid**: News-based but manually edited

---

## 2. Episodes

Episodes are the main content unit - a 2-minute satirical video with 24 scenes.

### Episode Types

| Type | Trigger | Timing |
|------|---------|--------|
| `post-fp2` | After Friday Practice 2 | ~30 min after session |
| `post-sprint` | After Sprint Race | ~60 min after session |
| `post-race` | After Main Race | ~60 min after session |
| `weekly-recap` | Off-week | Monday morning |

### Creating an Episode

1. Navigate to **Episodes** → **New Episode**
2. Select:
   - **Race** (from calendar)
   - **Episode Type** (post-fp2, post-race, etc.)
   - **Storyline** (optional - or auto-generate)
3. Click **Generate**

### Episode Status Flow

```
PENDING → GENERATING → STITCHING → UPLOADING → PUBLISHED
                 ↓
              FAILED (retry up to 3 times)
```

### Episode Structure

Each episode contains:
- **24 scenes** × 5 seconds = 2 minutes total
- **Title** (auto-generated)
- **Description** (for YouTube)
- **Cost tracking** (API usage)

---

## 3. Characters

Characters are the visual personalities that appear in videos.

### Character Types

1. **Drivers** (20 on 2026 grid)
2. **Team Principals** (10 teams)
3. **Commentators** (Sky Sports team)
4. **Others** (FIA officials, etc.)

### Character Data Model

```typescript
interface Character {
  name: string;           // "max_verstappen"
  display_name: string;   // "Max Verstappen"
  description: string;    // Role and background
  personality: string;    // How they speak/act
  voice_description: string; // For TTS
  primary_image_path: string; // MinIO path
  is_active: boolean;
}
```

### Managing Characters

1. Navigate to **Characters** page
2. Click on a character to view/edit
3. Update personality or voice description as needed

### Character Images

- **Location**: MinIO bucket `f1-characters/characters/`
- **Format**: JPEG or PNG
- **Style**: Pixar/DreamWorks 3D animation style
- **Size**: ~2-3MB each

---

## 4. Scenes & Video Generation

Each episode has 24 scenes, each generating a 5-second video clip.

### Scene Generation Pipeline

```
1. SCRIPT (Claude AI)
   ↓
   Generates scene descriptions with:
   - Character assignment
   - Dialogue (<S>...<E>)
   - Action description
   - Audio description (<AUDCAP>...<ENDAUDCAP>)

2. IMAGE (Gemini Imagen 4.0)
   ↓
   Generates scene image from:
   - Character reference image
   - Action description
   - Visual style guide

3. VIDEO (Ovi HuggingFace Space)
   ↓
   Generates 5-second clip from:
   - Scene image
   - Text prompt with dialogue/audio tokens
   - Sample steps (quality level)
```

### Ovi Prompt Format

```
Character speaking to camera. <S>Hello F1 fans, welcome to the race weekend!<E> <AUDCAP>Studio ambiance, professional voice<ENDAUDCAP>
```

### Video Quality Settings

| Quality | Sample Steps | Time | Use Case |
|---------|--------------|------|----------|
| draft | 15 | ~30s | Quick tests |
| standard | 30 | ~50s | Normal production |
| high | 50 | ~90s | High quality |
| ultra | 75 | ~150s | Best quality |

---

## 5. Scheduler

The scheduler automates video generation based on F1 calendar events.

### How It Works

1. **Race Calendar** loaded from F1 API
2. **Jobs scheduled** based on session times
3. **Auto-trigger** after sessions end
4. **News scraping** gathers relevant articles
5. **Pipeline runs** unattended

### Scheduler Configuration

Navigate to **Scheduler** page to:
- View upcoming jobs
- Enable/disable auto-generation
- Manually trigger jobs
- View job history

### Timing Configuration

```python
# In settings
PRE_RACE_DELAY_MINUTES = 30    # Buffer before checking
POST_RACE_DELAY_MINUTES = 60   # Delay after race end
TRIGGER_CHECK_INTERVAL = 15    # Poll frequency (minutes)
```

---

## 6. Final Output

### Video Stitching

After all 24 clips are generated:

1. **Download** clips from MinIO
2. **Stitch** with ffmpeg (crossfade transitions)
3. **Add audio track** (if needed)
4. **Upload** final video to MinIO

### YouTube Upload

1. **Title** from episode data
2. **Description** with race info, hashtags
3. **Tags** for SEO
4. **Thumbnail** (first frame or custom)

### Storage Locations

| Asset | Bucket | Path Pattern |
|-------|--------|--------------|
| Character Images | f1-characters | `/characters/{name}_{team}.jpg` |
| Scene Images | f1-scene-images | `/race_{id}/episode_{id}/scene_{n}.png` |
| Video Clips | f1-video-clips | `/race_{id}/episode_{id}/clip_{n}.mp4` |
| Final Videos | f1-final-videos | `/race_{id}/episode_{id}/final.mp4` |

---

## Creating Your First Video (Step-by-Step)

### Prerequisites

1. ✅ Dashboard accessible at https://f1.antikythera.co.za
2. ✅ Backend healthy at https://f1.antikythera.co.za:8001/health
3. ✅ At least one race in calendar
4. ✅ Characters loaded with images

### Steps

1. **Check Characters**
   - Go to Characters page
   - Verify images are loading
   - Note any missing/broken images

2. **Create Storyline** (Optional)
   - Go to Storylines page
   - Create a test storyline
   - Or let the system auto-generate

3. **Create Episode**
   - Go to Episodes → New Episode
   - Select race (e.g., Australian Grand Prix)
   - Select type (e.g., post-race)
   - Click Generate

4. **Monitor Progress**
   - Watch status change: PENDING → GENERATING
   - Each scene takes ~1 minute
   - 24 scenes ≈ 25-30 minutes total

5. **Review Output**
   - Once PUBLISHED, check YouTube URL
   - Or download from MinIO

---

## Troubleshooting

### Common Issues

| Issue | Cause | Solution |
|-------|-------|----------|
| Scenes failing | Ovi space sleeping | Space auto-wakes, retry |
| Image generation error | API quota | Check Gemini dashboard |
| News scraping empty | F1.com changed | Check RSS URL |
| Character not found | Missing image | Upload to MinIO |

### Logs

```bash
# Backend logs
docker logs f1-generator-backend -f

# Check specific episode
GET /api/v1/episodes/{id}/logs
```

### Health Checks

```bash
# Backend
curl https://f1.antikythera.co.za:8001/health

# Ovi Space
curl https://huggingface.co/api/spaces/alexnasa/Ovi-ZEROGPU
```

---

## API Quick Reference

### Key Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/v1/episodes` | GET/POST | List/create episodes |
| `/api/v1/episodes/{id}` | GET | Episode details |
| `/api/v1/characters` | GET | List all characters |
| `/api/v1/races` | GET | List races |
| `/api/v1/races/sync` | POST | Sync F1 calendar |

### Full API docs: https://f1.antikythera.co.za:8001/docs
