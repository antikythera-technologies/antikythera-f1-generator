## What This Workspace Does
Utility scripts for deployment, setup, batch operations, and GPU management.

## Scripts
| Script | Purpose | Usage |
|--------|---------|-------|
| `install.sh` | Install backend + dashboard dependencies | `./scripts/install.sh` |
| `startup.sh` | Start services (all, backend, dashboard) | `./scripts/startup.sh [backend\|dashboard]` |
| `prime.sh` | Run migrations + seed data | `./scripts/prime.sh [--reset]` |
| `deploy.sh` | Deploy to production VPS | `./scripts/deploy.sh` |
| `generate_all_characters.py` | Batch generate caricatures for all 42 characters | `uv run scripts/generate_all_characters.py --phase all` |
| `sync_character_db.py` | Sync PostgreSQL character table with MinIO image paths | `uv run scripts/sync_character_db.py` |
| `gpu_manager.py` | RunPod GPU lifecycle HTTP server (port 7777) | Runs on RunPod pod |
| `generate_episode_script.py` | Generate episode script standalone (outside pipeline) | `uv run scripts/generate_episode_script.py` |
| `generate_episode_images.py` | Generate all images for an episode standalone | `uv run scripts/generate_episode_images.py` |
| `generate_scene_video.py` | Generate video for a single scene (RunPod) | `uv run scripts/generate_scene_video.py` |
| `generate_scene_video_fal.py` | Generate video for a single scene (fal.ai) | `uv run scripts/generate_scene_video_fal.py` |
| `regenerate_scene_images.py` | Batch regenerate scene images via fal.ai | `uv run scripts/regenerate_scene_images.py` |
| `regenerate_episode_scripts.py` | Regenerate scripts for existing episodes | `uv run scripts/regenerate_episode_scripts.py` |
| `seed_teams_2026.py` | Seed 2026 F1 teams into database | `uv run scripts/seed_teams_2026.py` |
| `refresh_youtube_token.py` | Refresh YouTube OAuth2 token | `uv run scripts/refresh_youtube_token.py` |
| `update_youtube_video.py` | Update metadata on existing YouTube video | `uv run scripts/update_youtube_video.py` |

## experiments/ Directory
Test scripts for R&D work. See `experiments/CONTEXT.md` for details.
