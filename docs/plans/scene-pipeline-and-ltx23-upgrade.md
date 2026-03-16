# Scene Pipeline & Dual Video Engine Plan

**Date**: 2026-03-11 (updated 2026-03-13)
**Status**: In Progress — Australian GP episode production
**Author**: Wian Koch + Claude

---

## Executive Summary

Automated weekly F1 satirical video production. The pipeline turns a race weekend into a 2-minute animated commentary video (24 × 5-second scenes) and publishes to YouTube. Two video engines are supported — **Ovi** (active, tested) and **LTX 2.3** (blocked, under audit). The system is designed to run fully automated via scheduler, but is currently being validated step-by-step.

**Ultimate goal**: Scheduler fires after each race → pipeline runs autonomously → video published to YouTube. No human intervention required once validated.

---

## Weekly Production Workflow

This is what happens every race week, either manually or via the scheduled job:

### Step 1 — Calendar Check
- Sync F1 calendar: `POST /api/v1/scheduler/sync`
- Verify the next race is in the DB with correct dates
- Scheduler creates a job timed to race finish + buffer

### Step 2 — Content Gathering
- Scrape news sources: `POST /api/v1/news/scrape`
- Review storylines (multi-episode arcs): `/api/v1/storylines`
- Check running gags and cooldowns: `/api/v1/gags`
- These feed into the script generator as creative context

### Step 3 — Episode & Script Generation
- Create episode for the race: `POST /api/v1/episodes/generate`
- Haiku generates 24 scene scripts with full cinematographic direction
- Each scene gets: dialogue, audio_description, start_frame_prompt, end_frame_prompt, camera_direction, video_prompt
- All stored in `episode_scenes` table

### Step 4 — Scene-by-Scene Production (Phase 2a + 2b + 2c)
For each scene (1–24):
1. **Image gen** (Phase 2a): ComfyUI generates start frame image (Flux + LoRA + PuLID)
2. **Video gen** (Phase 2b): Selected engine creates 5-second video clip from image
   - **Ovi**: Gradio API, generates video + audio natively, ~16 min/clip with cpu_offload
   - **LTX**: ComfyUI workflow, generates video + audio via AV mode (BLOCKED)
3. **TTS + audio mux** (Phase 2c): Edge TTS generates dialogue audio, ffmpeg muxes onto video
   - Ovi path: TTS replaces/supplements native audio
   - LTX path: Skipped if AV mode produces acceptable audio
4. DB commit after each scene (crash recovery)

### Step 5 — Stitching (Phase 3)
- ffmpeg concatenates 24 clips into final 2-minute video
- libx264, CRF 23, AAC audio

### Step 6 — YouTube Upload (Phase 4)
- OAuth2 resumable upload
- Auto-generated title, description, tags from episode metadata
- Thumbnail from scene 1 start frame

### Step 7 — Cleanup (Phase 5)
- Delete MinIO assets older than 3 races
- Archive generation logs

---

## Video Engine Selection

Selected via dashboard Settings page or `VIDEO_GENERATOR_DEFAULT` in config.

| Engine | Status | Output | Time/clip | Audio | Notes |
|--------|--------|--------|-----------|-------|-------|
| **Ovi** | **ACTIVE** | .mp4 (h264 + AAC) | ~16 min (cpu_offload) | Native + TTS overlay | Production engine |
| **LTX 2.3** | BLOCKED | .webm / .mp4 | ~60-130s | Native AV mode | Under audit — see `docs/runpod-setup/ltx-audit.md` |

**GPU sharing**: ComfyUI and Ovi share 1× RTX A6000 48GB. Cannot run simultaneously. Pipeline orchestrates: stop ComfyUI → start Ovi → generate videos → stop Ovi.

**Future vision**: Once LTX is fixed, compare both engines side-by-side per scene. Mix and match — use whichever produces better output for each scene type. Or if one is clearly superior, use it exclusively.

---

## Australian GP — Progress Tracker

Race: Round 1, Albert Park, 2026-03-16

| Step | Status | Notes |
|------|--------|-------|
| 1. Calendar synced | DONE | Australian GP in DB with correct dates |
| 2. News scraped | **NOT DONE** | 0 articles in DB — need to run scraper |
| 3. Storylines created | DONE | Active storylines exist |
| 4. Running gags | DONE | Gags seeded |
| 5. Episode created | DONE | Episode 1 exists with 24 scene scripts |
| 6. Scene images generated | DONE | All 24 start frame images in MinIO |
| 7. Scene 01 video (Ovi) | DONE | `test-output/ovi-scene1/` — 16 min gen time |
| 8. Scenes 02–24 video | **NOT DONE** | Need to generate remaining 23 scenes |
| 9. TTS audio mux | DONE (scene 01) | Edge TTS working, audio muxed via ffmpeg |
| 10. Stitching | **NOT DONE** | ffmpeg concat not yet tested |
| 11. YouTube upload | **NOT DONE** | OAuth flow not yet tested |

**Blocking issue**: Generating 23 remaining scenes at ~16 min each = ~6 hours. Need to batch this.

---

## Completed Work

### Workstream 1: Rich Scene Pipeline (DONE)

| Phase | What | Status |
|-------|------|--------|
| 1A | DB migration — dual frame columns + video_generator + audio_clip_path | DONE (migrations 002 + 003) |
| 1B | Script generator — full cinematographic direction per scene | DONE |
| 1C | Image generator — scene-context images (not just portraits) | DONE |
| 1D | Pipeline integration — dual frame gen, video gen, TTS, intermediate commits | DONE |
| 1E | Scenes API — CRUD, prompt editing, regeneration endpoints | DONE |
| 1F | Dashboard scene viewer — SceneCard, SceneDetailModal | DONE |

### Workstream 2: Video Engine Infrastructure (PARTIAL)

| Phase | What | Status |
|-------|------|--------|
| 2A | Config & settings — LTX23_* and OVI_* config, dashboard selector | DONE |
| 2B | ComfyUI shared client | DONE |
| 2C | LTX video generator service | DONE (code written, not producing valid output) |
| 2D | RunPod installation — LTX 2.3 models, custom nodes | DONE (installed, not working) |
| 2E | Pipeline video generator factory (Ovi/LTX selection) | DONE |
| 2F | Pipeline settings API + dashboard selector | DONE |

### Additional (not in original plan)

| What | Status |
|------|--------|
| TTS generator — Edge TTS with 42 character voice mappings | DONE |
| Audio mixer — ffmpeg mux TTS onto video clips | DONE |
| Ovi video generator — quality presets, Gradio integration | DONE |
| GPU sharing protocol — orchestrated ComfyUI/Ovi switching | DONE |
| RunPod server documentation — full audit trail | DONE (`docs/runpod-setup/`) |
| 9 pundit personality JSONs | DONE |

---

## Remaining Work

### Priority 1: Ship Australian GP Video (TODAY)

1. ~~Verify scene 01 output quality~~ → DONE
2. **Batch generate scenes 02–24 with Ovi** (~6 hours)
3. **Test stitching** — ffmpeg concat all 24 clips
4. **Test YouTube upload** — OAuth flow, metadata generation
5. **Scrape news** — 0 articles, should have context for script quality

### Priority 2: Production Hardening

- [ ] Batch scene generation (run all 24 in sequence, handle failures/retries)
- [ ] Scheduler integration — auto-trigger after race finish
- [ ] YouTube metadata templates (title, description, tags per race)
- [ ] Monitoring/alerting for failed generations
- [ ] Cost tracking per episode (API calls, GPU time)

### Priority 3: LTX 2.3 Audit (DEFERRED)

Three-phase audit plan documented in `docs/runpod-setup/ltx-audit.md`:

**Phase 1 — Fix the Obvious**:
1. Fix model name mismatch: config says `ltx-2-19b-dev-fp8` but server has `ltx-2.3-22b-dev-fp8`
2. Test official ComfyUI workflow template unmodified
3. Test with simple prompt and photo input

**Phase 2 — Isolate the Problem**:
4. Test LTX outside ComfyUI (HuggingFace Space or direct Python)
5. Compare ComfyUI-LTXVideo node versions vs model version
6. Check ComfyUI v0.16.4 compatibility

**Phase 3 — Rebuild if Needed**:
7. If LTX works outside ComfyUI, rebuild workflow from official template
8. If LTX doesn't work at all, evaluate alternatives

### Priority 4: Engine Comparison & Optimization

- [ ] A/B comparison endpoint: generate same scene with both Ovi and LTX
- [ ] Side-by-side viewer in dashboard
- [ ] Quality scoring rubric (motion smoothness, face consistency, lip sync, audio clarity)
- [ ] Per-scene engine selection (mix Ovi and LTX in same episode)
- [ ] If one engine is clearly better, simplify to single engine

---

## Key Files

| File | Purpose |
|------|---------|
| `backend/app/pipeline/video_pipeline.py` | Orchestrator — runs all 5 phases |
| `backend/app/services/ovi_video_generator.py` | Ovi video engine (**ACTIVE**) |
| `backend/app/services/ltx_video_generator.py` | LTX 2.3 video engine (BLOCKED) |
| `backend/app/services/image_generator.py` | ComfyUI image gen (Flux + LoRA + PuLID) |
| `backend/app/services/tts_generator.py` | Edge TTS speech generation |
| `backend/app/services/audio_mixer.py` | ffmpeg TTS audio mux |
| `backend/app/services/script_generator.py` | Anthropic Haiku script generation |
| `backend/app/config.py` | All settings (VIDEO_GENERATOR_DEFAULT, LTX23_*, OVI_*) |
| `backend/app/api/pipeline_settings.py` | Runtime settings API |
| `dashboard/src/app/settings/page.tsx` | Video provider selector UI |
| `docs/runpod-setup/ltx-audit.md` | LTX 2.3 debugging plan |

---

## Risk Considerations

| Risk | Impact | Mitigation |
|------|--------|------------|
| 23 scenes × 16 min = 6h generation time | May not finish today | Start batch early; consider draft quality (fewer steps) |
| Ovi OOM during long batch | Kills pod, loses progress | Pipeline commits after each scene; resume picks up where left off |
| News scraper has 0 articles | Script quality may suffer | Run scraper before next episode; current episode already has scripts |
| YouTube OAuth not tested | Can't publish | Test OAuth flow separately; manual upload as fallback |
| LTX may never work via ComfyUI | Permanent engine gap | Ovi is production-viable; LTX audit may find root cause |
| Pod restart mid-batch | SSH port changes, services down | Auto-resume; check pod status via RunPod API |
