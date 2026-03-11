# Dashboard — Layer 2 Context

This is a Layer 2 context file for when working on the dashboard UI — components, pages, styling, API integration. NOT for backend or pipeline work.

## What This Workspace Does

Next.js 15 dashboard for monitoring and controlling the F1 video generation system. React 19, Tailwind CSS v4, cyberpunk theme.

## Pages

| Route | Page | Purpose |
|-------|------|---------|
| `/` | Mission Control | Stats grid, recent episodes, quick actions |
| `/episodes` | Episodes List | Browse episodes with status filters |
| `/episodes/[id]` | Episode Detail | Full episode view, scene breakdown, retry button |
| `/episodes/new` | New Episode | Select race + type, trigger generation |
| `/characters` | Characters | Grid view, face ref uploads, caricature gen |
| `/characters/[id]` | Character Detail | View character + images |
| `/characters/[id]/edit` | Character Edit | Update metadata, manage images |
| `/races` | Races | 2026 F1 calendar, sync button |
| `/scheduler` | Scheduler | Job timeline, sync, manual trigger, cancel |
| `/news` | News | Article browser, source management, scrape |
| `/gags` | Running Gags | CRUD, categories, usage tracking |
| `/storylines` | Storylines | Narrative arcs, beat management |
| `/storylines/[id]` | Storyline Detail | Beat progress, linked episodes |
| `/settings` | Settings | Placeholder for API keys |

## API Client (src/lib/api.ts)

Centralized API client with 9 modules:

- `episodesApi` — list, get, generate, retry
- `scenesApi` — list, get, updatePrompts, regenerateStartFrame/EndFrame/Video/All
- `charactersApi` — list, get, getPersonality, getFaceReference, uploadFaceReference, create, update
- `racesApi` — list, get, sync
- `analyticsApi` — costs, stats
- `schedulerApi` — sync, listJobs, getUpcoming, getPending, getJob, createJob, cancelJob, triggerJob
- `newsApi` — listSources, createSource, updateSource, listArticles, getArticle, fetchContent, scrape, getForEpisode
- `gagsApi` — list, get, create, update, delete, recordUsage, forEpisode
- `storylinesApi` — list, get, getActive, create, update, delete, advance, linkEpisode

## Theme

Cyberpunk aesthetic via Tailwind CSS v4 custom properties in `globals.css`:

- `--deep-space` — dark background
- `--neon-cyan` — primary accent
- `--racing-red` — danger/alert
- Additional: `--podium-gold`, `--pit-orange`, etc.

## Component Structure

- `components/layout/` — Sidebar, layout shell
- `components/episodes/` — SceneCard, SceneDetailModal
- `components/characters/` — Character card, image upload
- `components/ui/` — Shared UI primitives

## Env Vars

- `NEXT_PUBLIC_API_URL` — Backend API base (default: `http://localhost:8001/api/v1`)
- `NEXT_PUBLIC_MINIO_URL` — MinIO base URL for image/video assets

## Commands

```bash
cd dashboard
npm run dev    # Dev server on :3000
npm run build  # Production build
npm run lint   # ESLint
```

## Patterns

- All pages are `"use client"` with React hooks (no global state manager)
- Status badges for episode/scene/job states
- Loading states and error boundaries
- Polling for long-running job status

## Current Development State

Dashboard is functional. The Scenes page/modal was just built to enable scene-by-scene review during testing. Not all features have been thoroughly tested yet.
