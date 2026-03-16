# Face Consistency Experiment — Tracking Document

## Problem
Characters don't look consistent across scenes. We use LoRA for art style (ANTKF1STYLE) but rely on text prompts only for face identity. Each scene generates a different-looking face for the same character.

## Goal
Find a method to use face reference images so characters look the same across all 24 scenes in an episode and across episodes throughout the season.

## Previous Attempts

### Attempt 1: fal-ai/flux-general with IP-Adapter (2026-03-14)
- **What**: Used `reference_image_url` with `reference_strength=0.65`
- **Result**: FAILED — face reference bled into background. Entire scene took on face skin tone/features
- **Code**: `_async_scene_image` in jobs.py, disabled with comment "flux-general IP-Adapter warps faces badly"

### Attempt 2: RunPod ComfyUI with PuLID (2026-03-11 to 2026-03-12)
- **What**: ApplyPulidFlux node in ComfyUI workflow on RunPod, used with Flux + ANTKF1STYLE LoRA
- **Result**: WORKED for face consistency but RunPod has been deprecated (moved to fal.ai)
- **Key settings**: PuLID required separate EvaClipLoader + InsightFace, forward_orig patched
- **Notes**: PuLID gave good face identity preservation while maintaining LoRA style

## Options to Test

### Option A: fal-ai/instant-character (RECOMMENDED — Test First)
- **What**: Purpose-built identity-preserving generation. Takes face reference + text prompt
- **Supports LoRA**: YES (has LoraWeight parameter with path, trigger_word, scale)
- **Key param**: `scale` (0-2) controls face reference prominence
- **Why promising**: Designed specifically for "consistent characters" — exactly our use case
- **Test plan**:
  1. Upload face reference to fal CDN
  2. Generate scene with ANTKF1STYLE LoRA + face reference + scene prompt
  3. Test scale values: 0.5, 0.8, 1.0, 1.2
  4. Compare face consistency vs style preservation

### Option B: fal-ai/flux-general with lower reference_strength
- **What**: Retry the IP-Adapter approach with gentler settings
- **Key param**: `reference_strength` — try 0.25, 0.30, 0.35 (was 0.65 before)
- **Risk**: May still bleed at any strength, or face identity too weak at low values
- **Test plan**:
  1. Same scene, same face reference
  2. Test reference_strength: 0.25, 0.30, 0.35, 0.40
  3. Check if face bleeds at each level

### Option C: Two-step pipeline (generate scene → face swap)
- **What**: Generate scene image with LoRA only (current working approach), then run a face-swap model
- **Candidates**:
  - Easel AI face swap on fal.ai (maintains likeness across body)
  - IP Adapter Face ID on fal.ai (zero-shot personalization)
- **Cost**: Double the image generation cost (~$0.035 scene + ~$0.04 face swap = $0.075/image)
- **Advantage**: Separates concerns — scene composition stays perfect, face gets stamped on
- **Test plan**:
  1. Generate scene image (current working method)
  2. Run face swap with reference image
  3. Check if caricature style survives the face swap

### Option D: FLUX Kontext (edit existing image)
- **What**: Take generated scene image, use Kontext to "edit" the face to match reference
- **Cost**: $0.04/image
- **How**: Pass generated scene image + prompt like "Make this character's face look like [reference]"
- **Risk**: May not preserve caricature style, designed more for photo editing
- **Test plan**: Quick test with one scene

## Experiment Protocol
1. Use Episode 2, Scene 1 (Gabriel Bortoleto) as test scene
2. Generate with each method
3. Save outputs to MinIO: `f1-experiments/face-consistency/`
4. Compare: face similarity, style preservation, background quality
5. Document results in this file

## Results Log

### Test 1: [pending]
- Method:
- Date:
- Settings:
- Result:
- Face similarity: /10
- Style preservation: /10
- Notes:

---
*Last updated: 2026-03-16*
