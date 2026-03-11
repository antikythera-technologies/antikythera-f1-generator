## What This Workspace Does
R&D test scripts for validating image and video generation approaches before committing to the production pipeline.

## Current Experiments (Active)
| Script | What It Tests | Status |
|--------|--------------|--------|
| `test_pulid_lora_v2.py` | Final PuLID + LoRA parameter tuning (LoRA 1.2/1.4, PuLID 0.7) | DONE — optimal settings: LoRA 1.4, PuLID 0.7, 20 steps, euler/simple |
| `test_scene_image.py` | Full scene images with environmental context (landscape 1344×768) | DONE — workflow works for environmental scenes |
| `test_ltx_scene1.py` | LTX 2.3 video from scene 1 image (dual start/end frame) | READY — coded and verified, awaiting first test run |
| `test_video_comparison.py` | Comprehensive parameter sweep: Ovi vs LTX, denoise/conditioning/guidance sweeps | READY — identifies caricature presets for each engine |
| `train_style_lora.py` | Train Flux LoRA on caricature dataset via fal.ai | DONE — produced ANTKF1STYLE LoRA (86MB) |

## Archived Experiments (archive/)
Superseded scripts from the experimentation progression:
- Nano Banana tests — superseded by LoRA approach
- Two-reference style transfer — superseded by LoRA
- JSON prompt routing (v8-v11) — superseded by LoRA
- Early LoRA/PuLID tests — superseded by v2

## Running Experiments
All experiment scripts are standalone. They connect directly to ComfyUI/Ovi on RunPod.
```
cd backend
uv run python ../scripts/experiments/test_ltx_scene1.py
```
Output goes to `test-output/` directory.
