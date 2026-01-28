# Antikythera F1 Dashboard

Next.js 16 / React 19 / Tailwind CSS 4 dashboard for managing F1 video generation.

## Status

🚧 **Placeholder** - Dashboard implementation pending.

## Planned Structure

```
dashboard/
├── app/
│   ├── layout.tsx
│   ├── page.tsx
│   ├── episodes/
│   │   ├── page.tsx
│   │   └── [id]/page.tsx
│   ├── characters/
│   │   └── page.tsx
│   ├── races/
│   │   └── page.tsx
│   └── analytics/
│       └── page.tsx
├── components/
│   ├── ui/
│   ├── episodes/
│   ├── characters/
│   └── charts/
├── lib/
│   ├── api.ts
│   └── utils.ts
├── public/
├── package.json
├── next.config.js
├── tailwind.config.js
└── tsconfig.json
```

## Features (Planned)

### Episode Management
- View all episodes with status
- Trigger new episode generation
- Retry failed episodes/scenes
- View generation logs
- Preview generated videos

### Character Management
- List all characters
- Upload reference images
- Configure voice/personality

### Race Calendar
- View F1 race calendar
- Sync with external API
- Trigger pre/post-race episodes

### Analytics
- Cost tracking dashboard
- Performance metrics
- API usage charts

## Setup (Once Implemented)

```bash
cd dashboard
npm install
npm run dev
```

## API Connection

Dashboard connects to backend at `http://localhost:8000` (configurable via `NEXT_PUBLIC_API_URL`).
