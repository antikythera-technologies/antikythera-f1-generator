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

## experiments/ Directory
Test scripts for R&D work. See `experiments/CONTEXT.md` for details.
