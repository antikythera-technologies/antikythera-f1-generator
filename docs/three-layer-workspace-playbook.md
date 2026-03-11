# Three-Layer Workspace Playbook

A step-by-step guide for Claude Code to restructure any repository into a three-layer folder-as-workspace system. This was developed and tested on the antikythera-f1-generator repo. Copy this file into any repo and tell Claude to execute it.

---

## What This Is

A folder organization pattern that makes AI coding assistants dramatically more efficient. Instead of one monolithic CLAUDE.md that dumps everything into context, you create:

- **Layer 1 (The Router)**: Root `CLAUDE.md` — a map that loads on every task. Contains the folder structure, a routing table, naming conventions, and development state. Tells the AI *where to go*, not *how everything works*. Target: under 100 lines.
- **Layer 2 (The Context Files)**: `CONTEXT.md` files inside each major workspace. Only loaded when the AI is working in that area. Contains the deep knowledge needed for that specific domain. Each one is self-contained.
- **Layer 3 (The Workspaces)**: The actual code, files, and outputs. Organized with clear naming conventions so files are findable without databases or searching.

## Why This Works

- AI context windows are finite. A 200-line CLAUDE.md wastes tokens on pipeline internals when you're fixing a CSS bug.
- The routing table eliminates guessing. The AI reads one table, knows exactly what to load and what to skip.
- Each CONTEXT.md is independently editable. Change how the AI handles backend work without touching anything about the frontend.
- Naming conventions replace search. If files follow predictable patterns, the AI can find them by convention instead of grepping.

---

## Step-by-Step Process

### Phase 1: Investigate (DO NOT SKIP)

**This is the most critical phase. You MUST understand the codebase before writing any context files. Do NOT make assumptions based on file names or common patterns.**

#### 1.1 Map the folder structure

```
Find all directories (3-4 levels deep), excluding .git, node_modules, __pycache__, .next, .venv, etc.
```

Write down every top-level directory and what it appears to contain.

#### 1.2 Read the existing CLAUDE.md

If one exists, read it carefully. Note:
- What information is accurate vs outdated?
- What's bloated (architecture details that belong in a CONTEXT.md)?
- What's missing (no routing, no folder map)?

#### 1.3 Read the actual code — don't guess

For EACH major directory, read the key files to understand:
- What does this area actually do?
- What external services/APIs does it connect to?
- What's the current development state (working, in-progress, untested)?
- Are there deprecated/superseded files that should be archived?

**Concrete investigation steps:**
- Read every `__init__.py` or `index.ts` to see what's exported
- Read service/utility files to understand integrations
- Read config files to understand environment variables
- Read test files to understand what's been validated
- Check git status for untracked files that might be new features in progress
- Look for duplicate/versioned files (e.g., `foo.py` and `foo_v2.py`) — ask which is current

#### 1.4 Identify workspaces

A workspace is a distinct area of the codebase where you do a specific kind of work. Common patterns:

| Project Type | Typical Workspaces |
|-------------|-------------------|
| Full-stack web app | backend, frontend, database/migrations, deployment, tests |
| Monorepo | Each package/service, shared libs, deployment, docs |
| Data pipeline | Ingestion, processing, output, orchestration, monitoring |
| ML project | Data prep, training, inference, evaluation, deployment |
| CLI tool | Core logic, commands, config, tests, packaging |

Don't force it. A small project might only need 2-3 workspaces. A large one might need 8-10.

#### 1.5 Identify tasks

List every kind of work that gets done in this repo. Be specific to the project, not generic. Examples:
- "Add a new API endpoint" (not just "backend work")
- "Train a new model version" (not just "ML work")
- "Fix a dashboard component" (not just "frontend work")
- "Deploy to staging" (not just "deployment")
- "Run an experiment" (not just "testing")

For each task, note which files/folders are relevant and which are irrelevant.

#### 1.6 Identify cleanup needed

Look for:
- **Deprecated files** that have been superseded but never removed
- **Duplicate files** (old version + new version sitting side by side)
- **Scattered experiments** or test scripts that should be organized
- **Stale documentation** that describes how things used to work

**IMPORTANT: When you find deprecated/duplicate files, do NOT ask the user "is this deprecated?" if YOU created those files. Check git blame or the file contents. If you wrote it, you should know its status. Clean up your own mess.**

---

### Phase 2: Clean Up

Before building the context system, clean the house.

#### 2.1 Archive deprecated files

Create `archive/` directories where needed. Move superseded files there. Don't delete — archive.

```
services/archive/         ← deprecated service files
scripts/experiments/archive/  ← superseded experiment scripts
docs/archive/            ← outdated design docs
```

#### 2.2 Rename for clarity

If files have ambiguous names, rename them. The file name should tell you what it does at a glance.

Example from our F1 project:
- `video_generator.py` → `ovi_video_generator.py` (it's the Ovi engine)
- `ltx23_video_generator.py` → `ltx_video_generator.py` (it's the LTX engine, the "23" version number is noise)

When renaming:
1. Rename the file
2. Rename the classes inside to match
3. Update ALL imports across the codebase (grep thoroughly)
4. Update ALL string references (config values, DB fields, comments)
5. Run tests to verify nothing broke

#### 2.3 Organize loose files

Move scattered scripts, test files, or configs into their proper homes. Every file should have a logical place in the folder structure.

---

### Phase 3: Build Layer 1 (Root CLAUDE.md)

The root CLAUDE.md is the router. It should contain ONLY:

1. **One-line project description** — what this project is
2. **Folder map** — annotated directory tree showing what each area contains
3. **Task routing table** — the critical piece. For each task type: what to read, what to skip
4. **Quick commands** — how to start, test, build, deploy (just the commands, not explanations)
5. **Naming conventions** — file naming patterns so the AI can find things by convention
6. **Development state** — one paragraph on where the project is right now
7. **Credentials note** — where secrets live (never in CLAUDE.md itself)

**Template:**

```markdown
# CLAUDE.md — [Project Name]

[One-line description of the project.]

## Folder Map

```
[Annotated directory tree — 2-3 levels deep, with → descriptions]
```

## Task Routing

Read the CONTEXT.md in the workspace BEFORE starting work. Skip everything else.

| Task | Read This Context | Skip |
|------|------------------|------|
| [Task 1] | `[path/CONTEXT.md]` | `[irrelevant dirs]` |
| [Task 2] | `[path/CONTEXT.md]` | `[irrelevant dirs]` |
| ... | ... | ... |

## Quick Commands

```bash
[Just the commands — install, start, test, build, deploy]
```

## Naming Conventions

| Type | Pattern | Example |
|------|---------|---------|
| [File type] | `[pattern]` | `[example]` |

## Development State

[1-2 sentences on current status and what's being worked on.]

## Credentials

[Where secrets live. Never store them here.]
```

**Rules:**
- Keep it under 100 lines
- No architecture explanations (that goes in CONTEXT.md files)
- No API endpoint lists (that goes in backend/CONTEXT.md)
- No component documentation (that goes in frontend/CONTEXT.md)
- The routing table is the most important part — get it right

---

### Phase 4: Build Layer 2 (CONTEXT.md Files)

Create a `CONTEXT.md` in each workspace identified in Phase 1.5.

**Each CONTEXT.md should contain:**

1. **What This Workspace Does** — 1-2 sentences
2. **Key concepts** — whatever the AI needs to know to work here effectively
3. **File inventory** — important files with one-line descriptions
4. **Commands** — workspace-specific commands (not duplicating root CLAUDE.md)
5. **Current state** — what's working, what's in progress, what's untested
6. **Integration points** — how this workspace connects to others (if relevant)

**Rules:**
- Write from investigation findings — not from assumptions
- Be specific to THIS project. Generic advice like "use best practices" is useless
- Include gotchas and hard-won knowledge (e.g., "this API requires X header" or "this config value must be int not float")
- Include deprecated/forbidden patterns (e.g., "do NOT use node X — it doesn't exist")
- Keep each CONTEXT.md under 120 lines. If it's longer, split into sub-workspaces
- Every fact should be verified against the actual code before writing

**Common CONTEXT.md files by project type:**

| Full-stack app | ML project | Data pipeline |
|---------------|------------|---------------|
| `backend/CONTEXT.md` | `training/CONTEXT.md` | `ingestion/CONTEXT.md` |
| `frontend/CONTEXT.md` | `inference/CONTEXT.md` | `processing/CONTEXT.md` |
| `backend/app/pipeline/CONTEXT.md` | `data/CONTEXT.md` | `output/CONTEXT.md` |
| `scripts/CONTEXT.md` | `evaluation/CONTEXT.md` | `orchestration/CONTEXT.md` |
| `infrastructure/CONTEXT.md` | `deployment/CONTEXT.md` | `monitoring/CONTEXT.md` |

---

### Phase 5: Update MEMORY.md

If the project has a `.claude/` memory directory with a `MEMORY.md`:

1. **Remove information that now lives in CONTEXT.md files** — no duplication
2. **Keep only cross-cutting notes** — things that apply everywhere, gotchas, fixes that don't belong in any single workspace
3. **Add a note about the new structure** — so future sessions know the three-layer system exists

---

### Phase 6: Verify

1. **Run tests** — make sure no renames or moves broke anything
2. **Check imports** — grep for old file/class names across the entire codebase
3. **Read each CONTEXT.md** — does it make sense standalone? Could the AI work in that area with only this file?
4. **Read the routing table** — for each task, is the routing correct? Does the "Skip" column actually exclude irrelevant files?
5. **Count lines** — root CLAUDE.md under 100? Each CONTEXT.md under 120?

---

## Anti-Patterns to Avoid

1. **Don't guess at the codebase.** Read the actual files. The biggest failure mode is writing CONTEXT.md files based on what you THINK the code does rather than what it ACTUALLY does.

2. **Don't create generic context files.** "This is a FastAPI backend" is useless. "This backend has 9 API routers, uses Redis+RQ for job queuing, and the Scene API was just built and is still being tested" is useful.

3. **Don't duplicate information across layers.** If it's in a CONTEXT.md, it shouldn't also be in the root CLAUDE.md or MEMORY.md.

4. **Don't create files you'll abandon.** If you create `foo_v2.py` alongside `foo.py`, rename the old one and update all references. Don't leave both sitting there.

5. **Don't over-split.** A workspace needs a CONTEXT.md only if it has enough distinct knowledge to justify one. A simple `scripts/` directory with 3 shell scripts might only need 10 lines.

6. **Don't write aspirational context.** Write about what EXISTS, not what you plan to build. Mark in-progress and untested features clearly.

---

## Real Example: Before and After

### Before (F1 Generator)

```
CLAUDE.md (98 lines) — monolith with architecture, data models, docker setup, testing
MEMORY.md (108 lines) — accumulated session knowledge, much duplicated
backend/app/services/
  video_generator.py          ← ambiguous name (it's the Ovi engine)
  ltx_video_generator.py      ← broken, uses non-existent nodes
  ltx23_video_generator.py    ← the actual working LTX engine
scripts/experiments/
  17 scripts, no indication which are current vs superseded
```

Every task loaded 98 lines of CLAUDE.md + 108 lines of MEMORY.md regardless of what you were doing.

### After

```
CLAUDE.md (92 lines) — router with folder map + task routing table
backend/CONTEXT.md (94 lines) — API, models, testing, job queue
backend/app/pipeline/CONTEXT.md (107 lines) — pipeline phases, GPU sharing, ComfyUI workflow
dashboard/CONTEXT.md (81 lines) — pages, API client, theme, components
character-system/CONTEXT.md (53 lines) — personalities, face refs, caricatures
scripts/CONTEXT.md (16 lines) — utility scripts
scripts/experiments/CONTEXT.md (26 lines) — R&D experiments with status
MEMORY.md (55 lines) — cross-cutting notes only

backend/app/services/
  ovi_video_generator.py      ← clear name: Ovi engine
  ltx_video_generator.py      ← clear name: LTX engine (the working one)
  archive/ltx_video_generator_old.py  ← broken one, archived

scripts/experiments/
  5 current scripts
  archive/ (11 superseded scripts)
```

Working on the dashboard? AI reads 92 (router) + 81 (dashboard context) = 173 lines.
Working on the pipeline? AI reads 92 (router) + 107 (pipeline context) = 199 lines.
Never reads both unless the task explicitly spans them.

---

## How to Use This Playbook

Copy this file into any repo. Then tell Claude:

> Read `docs/three-layer-workspace-playbook.md` and execute it on this repository. Start with Phase 1 (investigate) and show me your findings before proceeding to any changes.

The investigation phase is critical. If Claude skips it and starts making assumptions, stop it and insist on reading the actual code first.
