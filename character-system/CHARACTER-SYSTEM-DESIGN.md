# F1 Character System - Technical Design

## Overview

The Character System powers consistent, satirical AI-generated F1 content by defining:
- **Personality profiles** - Who each character IS
- **Relationship dynamics** - How characters interact with each other
- **Dialogue patterns** - How each character SPEAKS
- **Visual consistency** - How each character LOOKS
- **Mood/state tracking** - Current emotional state based on events

---

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                     CHARACTER ENGINE                         │
├─────────────────────────────────────────────────────────────┤
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐          │
│  │  Personality │  │ Relationship │  │  Dialogue   │          │
│  │   Profiles   │  │    Graph     │  │   Engine    │          │
│  └──────┬──────┘  └──────┬──────┘  └──────┬──────┘          │
│         │                │                │                  │
│         └────────────────┼────────────────┘                  │
│                          │                                   │
│                 ┌────────▼────────┐                          │
│                 │  Context Builder │                          │
│                 └────────┬────────┘                          │
│                          │                                   │
├──────────────────────────┼───────────────────────────────────┤
│                          ▼                                   │
│  ┌─────────────────────────────────────────────────────────┐│
│  │           Storyline Generation Pipeline                 ││
│  │  (Provides character context to GPT-4 for consistency)  ││
│  └─────────────────────────────────────────────────────────┘│
└─────────────────────────────────────────────────────────────┘
```

---

## 1. Personality Profiles

### Personality Dimensions (OCEAN + Custom)

Each character is scored on these dimensions (1-10 scale):

| Dimension | Low (1-3) | Medium (4-6) | High (7-10) |
|-----------|-----------|--------------|-------------|
| **Ego** | Humble, self-deprecating | Confident | Arrogant, self-obsessed |
| **Aggression** | Passive, yielding | Assertive | Combative, hostile |
| **Humor** | Serious, dry | Witty | Comedic, playful |
| **Drama** | Understated | Measured | Theatrical, explosive |
| **Intelligence** | Simplistic | Strategic | Genius, calculating |
| **Charm** | Awkward | Personable | Magnetic, charismatic |
| **Intensity** | Relaxed | Focused | Obsessive |
| **Authenticity** | Corporate/scripted | Balanced | Raw, unfiltered |

### Exaggeration Rules

For satirical content, personality traits are amplified:
- **Core traits** (top 2-3) → Exaggerated to 11
- **Weak traits** (bottom 2) → Become comedic blind spots
- **Contradictions** → Source of humor

---

## 2. Relationship Graph

### Relationship Types

| Type | Description | Interaction Style |
|------|-------------|-------------------|
| **Rivalry (Intense)** | Active competitors, personal beef | Confrontational, cutting remarks |
| **Rivalry (Respectful)** | Competitors who respect each other | Competitive but cordial |
| **Friendship** | Genuine allies | Supportive, inside jokes |
| **Mentorship** | Senior guiding junior | Advice, encouragement |
| **Tension** | Underlying conflict | Passive-aggressive, cold |
| **Indifference** | No strong feelings | Minimal interaction |
| **Team Dynamic** | Teammate relationship | Varies (support/competition) |

### Relationship Attributes

```json
{
  "character_a": "max_verstappen",
  "character_b": "lewis_hamilton",
  "type": "rivalry_intense",
  "backstory": "2021 championship battle, Abu Dhabi finale",
  "intensity": 9,
  "public_face": "professional respect",
  "private_reality": "mutual respect but competitive fire",
  "comedy_angle": "passive-aggressive compliments",
  "trigger_topics": ["2021", "racing hard", "track limits"]
}
```

---

## 3. Dialogue Engine

### Voice Patterns

Each character has defined:

```json
{
  "speaking_style": {
    "formality": "casual|formal|mixed",
    "vocabulary": ["signature words/phrases"],
    "sentence_structure": "short_punchy|long_explanatory|varied",
    "filler_words": ["simply", "honestly", "you know"],
    "accent_hints": "Dutch directness|British reserve|Italian passion"
  },
  "catchphrases": [
    "Simply lovely",
    "For sure",
    "It is what it is"
  ],
  "topics_of_passion": ["racing", "family", "engineering"],
  "humor_style": "deadpan|sarcastic|self-deprecating|physical",
  "signature_reactions": {
    "victory": "calm satisfaction, points up",
    "defeat": "stoic, analytical",
    "controversy": "dismissive shrug"
  }
}
```

### Dialogue Generation Rules

1. **Stay in character** - Each line must feel like that person wrote it
2. **Use signature phrases** - Sprinkle catchphrases naturally
3. **Match mood to situation** - Current emotional state affects tone
4. **Relationship-aware** - Different tone for rivals vs friends
5. **Comedy escalation** - Build to exaggerated moments

---

## 4. Visual Consistency

### Character Visual Profile

```json
{
  "physical": {
    "height_category": "tall|average|short",
    "build": "athletic|slim|stocky",
    "distinguishing_features": ["curly hair", "sharp jawline"],
    "signature_gestures": ["finger wag", "helmet tap"]
  },
  "style": {
    "helmet_design": "description of helmet pattern",
    "personal_brand": ["colors", "sponsor style"],
    "fashion_notes": "casual streetwear|formal suits|team gear always"
  },
  "animation_notes": {
    "posture": "confident stride|nervous energy|relaxed slouch",
    "facial_expression_default": "intense focus|easy smile|stern look",
    "comedy_exaggeration": "giant helmet|oversized ego visual|etc"
  }
}
```

---

## 5. Mood/State System

### State Tracking

Current mood is influenced by:
- **Recent race results**
- **Championship position**
- **Team announcements**
- **Media incidents**
- **Relationship events**

### Mood Categories

| Mood | Behavioral Changes |
|------|-------------------|
| **Triumphant** | Confident, generous to rivals, magnanimous |
| **Frustrated** | Short-tempered, sarcastic, blame-shifting |
| **Focused** | Minimal emotion, pure racing talk |
| **Playful** | Jokes, pranks, lighthearted |
| **Defensive** | Deflecting, PR-speak, guarded |
| **Relaxed** | Open, casual, off-topic chats |

---

## 6. Database Schema

See `schema/character_tables.sql` for full implementation.

---

## 7. Files Structure

```
character-system/
├── CHARACTER-SYSTEM-DESIGN.md      # This document
├── personalities/
│   ├── drivers/
│   │   ├── max_verstappen.json
│   │   └── ... (all 20 drivers)
│   └── principals/
│       ├── christian_horner.json
│       └── ... (all 10 principals)
├── relationships/
│   └── relationship_graph.json     # All character relationships
├── templates/
│   ├── personality_template.json   # Template for new characters
│   └── relationship_template.json  # Template for new relationships
├── schema/
│   └── character_tables.sql        # Database schema
└── scripts/
    ├── seed_database.py            # Populate DB with character data
    └── update_states.py            # Update moods from race results
```

---

*Last Updated: 2026-01-29*
*Author: Xoltrix*
