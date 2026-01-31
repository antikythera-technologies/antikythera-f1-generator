# Character Style Guide

## Overview

All F1 character images must follow a consistent Pixar/DreamWorks 3D animation style for visual cohesion across videos.

---

## Style Requirements

### ✅ CORRECT Style (Reference Examples)

The following characters have the **correct** style and should be used as references:

| Character | File | What Makes It Good |
|-----------|------|-------------------|
| Max Verstappen | `max_verstappen_red_bull_racing.jpg` | Full 3D render, stylized proportions, vibrant colors |
| Lewis Hamilton | `lewis_hamilton_ferrari.jpg` | Clean cartoon aesthetics, proper team colors |
| Lando Norris | `lando_norris_mclaren.jpg` | Expressive face, consistent lighting |
| George Russell | `george_russell_mercedes.jpg` | Proportional caricature, team branding |
| Fernando Alonso | `fernando_alonso_aston_martin.jpg` | Good balance of likeness and cartoon style |
| Charles Leclerc | `charles_leclerc_ferrari.jpg` | Animated movie quality |
| Pierre Gasly | `pierre_gasly_alpine.jpg` | Consistent with other drivers |
| Nico Hülkenberg | `nico_hülkenberg_kick_sauber.jpg` | Good team colors, proper style |
| Franco Colapinto | `franco_colapinto_alpine.jpg` | Modern Pixar aesthetic |
| Gabriel Bortoleto | `gabriel_bortoleto_kick_sauber.jpg` | Consistent with grid |
| Frédéric Vasseur | `fred_vasseur_ferrari.jpg` | Team principal style works |
| Toto Wolff | `toto_wolff_mercedes.jpg` | Good caricature of real person |

### Key Visual Elements of CORRECT Style

1. **3D Rendering**: Full CGI quality, not 2D or semi-realistic
2. **Stylized Proportions**: Slightly exaggerated features (larger head, expressive eyes)
3. **Clean Textures**: Smooth skin, clean fabrics, no photorealistic details
4. **Vibrant Colors**: Team colors are bright and saturated
5. **Consistent Lighting**: Studio-style lighting with soft shadows
6. **Racing Suit Details**: Team logos and sponsors visible but stylized
7. **Background**: Clean, often studio or gradient background

---

## ❌ INCORRECT Style (Needs Regeneration)

The following characters have inconsistent or overly realistic images:

### Characters to Regenerate

| Character | Current File | Issue |
|-----------|--------------|-------|
| Arvid Lindblad | `arvid_lindblad_red_bull_racing.jpg` | Too realistic/photographic |
| Jack Doohan | `jack_doohan_alpine.png` | PNG format, different style |
| Jenson Button | `jenson_button_sky_sports.png` | PNG, too realistic |
| Karun Chandhok | `karun_chandhok_sky_sports.png` | PNG, inconsistent style |
| Liam Lawson | `liam_lawson_red_bull_racing.png` | PNG, different rendering |
| Martin Brundle | `martin_brundle_sky_sports.png` | PNG, too realistic |
| Mattia Binotto | `mattia_binotto_kick_sauber.png` | PNG, inconsistent |
| Michael Andretti | `michael_andretti_cadillac.jpg` | Different art style |
| Nico Rosberg | `nico_rosberg_sky_sports.png` | PNG, realistic/different |
| Natalie Pinkham | `natalie_pinkham_sky_sports.png` | PNG, inconsistent |
| Oliver Oakes | `oliver_oakes_alpine.png` | PNG, different style |
| Sergio Pérez | `sergio_perez_red_bull_racing.jpg` | Outdated team (RB not Cadillac) |
| Sam Collins | (check if exists) | May need generation |
| Simon Lazenby | `simon_lazenby_sky_sports.png` | PNG, different style |
| Stefano Domenicali | `stefano_domenicali_f1.png` | PNG, inconsistent |
| Ted Kravitz | `ted_kravitz_sky_sports.png` | PNG, different style |
| Valtteri Bottas | `valtteri_bottas_kick_sauber.jpg` | Check if outdated team |
| David Croft | `david_croft_sky_sports.png` | PNG, check style |

### Pattern Identified

**PNG files** (1.1-1.2MB) = Generally inconsistent style
**JPG files** (2.5-3.0MB) = Generally correct Pixar style

---

## Image Generation Prompt Template

When regenerating characters, use this prompt template for Gemini Imagen 4.0:

```
Create a 3D animated character portrait in Pixar/DreamWorks animation style:

Subject: [CHARACTER NAME], [ROLE] (e.g., "Sky Sports F1 commentator" or "Ferrari F1 driver")

Style Requirements:
- High-quality 3D CGI render, similar to modern Pixar films
- Slightly stylized proportions with expressive features
- Clean, smooth textures (not photorealistic)
- Vibrant, saturated colors
- Professional studio lighting with soft shadows
- [TEAM COLOR] racing suit/attire with visible team branding
- Friendly, approachable expression
- Clean studio or gradient background

Character Details:
- [SPECIFIC FEATURES: hair color, facial hair, distinctive traits]
- [TEAM/ORGANIZATION]: [specific colors and logos]

Resolution: 1024x1024
Output: High quality PNG/JPEG
```

### Example Prompt (Ted Kravitz)

```
Create a 3D animated character portrait in Pixar/DreamWorks animation style:

Subject: Ted Kravitz, Sky Sports F1 pit lane reporter

Style Requirements:
- High-quality 3D CGI render, similar to modern Pixar films
- Slightly stylized proportions with expressive features
- Clean, smooth textures (not photorealistic)
- Vibrant, saturated colors
- Professional studio lighting with soft shadows
- Sky Sports branded attire (dark blue with Sky logo)
- Friendly, enthusiastic expression
- Clean studio background

Character Details:
- British male, middle-aged
- Dark hair, clean shaven
- Holding microphone or notepad
- Known for his notebook and technical knowledge

Resolution: 1024x1024
```

---

## Team Colors Reference

| Team | Primary Color | Secondary Color | Hex Codes |
|------|---------------|-----------------|-----------|
| Red Bull | Navy Blue | Yellow | #1E3A5F, #FFD700 |
| Ferrari | Racing Red | Yellow | #DC0000, #FFD700 |
| McLaren | Papaya Orange | Blue | #FF8000, #0090D0 |
| Mercedes | Silver/Black | Teal | #00D2BE, #000000 |
| Aston Martin | British Racing Green | Yellow | #006F62, #D4AF37 |
| Williams | Blue | White | #005AFF, #FFFFFF |
| Racing Bulls | Navy Blue | Red | #2B4562, #FF0000 |
| Kick Sauber/Audi | Green | Black | #00E701, #000000 |
| Haas | White | Red | #FFFFFF, #BD0F0F |
| Alpine | Pink/Blue | Black | #FF87BC, #0090FF |
| Cadillac | Black | Gold | #000000, #D4AF37 |

---

## Quality Checklist

Before uploading a character image, verify:

- [ ] 3D CGI render quality (not 2D or realistic)
- [ ] Consistent with other character images
- [ ] Correct team colors and branding
- [ ] Clean background (no distracting elements)
- [ ] Proper file format (JPEG preferred, 2-3MB)
- [ ] Correct naming convention: `{firstname}_{lastname}_{team}.jpg`
- [ ] Uploaded to MinIO: `f1-characters/characters/`

---

## Regeneration Priority

### High Priority (Active Drivers/Principals)
1. Sergio Pérez (wrong team in image)
2. Liam Lawson (PNG, different style)
3. Valtteri Bottas (check team)

### Medium Priority (Sky Sports Commentators)
4. Martin Brundle
5. Ted Kravitz
6. David Croft
7. Jenson Button
8. Nico Rosberg

### Lower Priority (Other)
9. Karun Chandhok
10. Simon Lazenby
11. Natalie Pinkham
12. Stefano Domenicali
13. Jack Doohan
14. Oliver Oakes
15. Mattia Binotto
16. Michael Andretti
17. Arvid Lindblad

---

## Notes

- **DO NOT** regenerate images without approval
- Use reference images from the "CORRECT" list
- Test new images with a sample video before full replacement
- Keep original images backed up before replacing
