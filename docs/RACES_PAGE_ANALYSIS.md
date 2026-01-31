# Races Page Analysis & Improvement Plan

## Current State

### What's Working ✅

1. **Race calendar loaded** - 24 races for 2026 season
2. **Basic card display** - Shows race name, circuit, country, date
3. **Upcoming/Past separation** - Clear visual distinction
4. **Days until race** - Countdown for upcoming races
5. **Sync button** - Can refresh from F1 API

### Data Available in Database

The `races` table has the following columns:

| Column | Type | Used in UI |
|--------|------|------------|
| `id` | int | No |
| `season` | int | Yes (filter) |
| `round_number` | int | Yes |
| `race_name` | string | Yes |
| `circuit_name` | string | Yes |
| `country` | string | Yes |
| `race_date` | date | Yes |
| `fp1_datetime` | datetime | **No** ❌ |
| `fp2_datetime` | datetime | **No** ❌ |
| `fp3_datetime` | datetime | **No** ❌ |
| `qualifying_datetime` | datetime | Yes (partial) |
| `race_datetime` | datetime | Yes (partial) |
| `is_sprint_weekend` | boolean | **No** ❌ |
| `sprint_qualifying_datetime` | datetime | **No** ❌ |
| `sprint_race_datetime` | datetime | **No** ❌ |

---

## Issues Identified

### 1. Missing Session Types in UI

**Problem**: Only showing Qualifying and Race times. Missing:
- Practice 1 (FP1)
- Practice 2 (FP2)
- Practice 3 (FP3)
- Sprint Qualifying (for sprint weekends)
- Sprint Race (for sprint weekends)

**Impact**: Users can't see full weekend schedule.

### 2. No Sprint Weekend Indicator

**Problem**: `is_sprint_weekend` flag exists but not displayed.

**Impact**: Users don't know which weekends have different schedules.

### 3. No Track Layout Images

**Problem**: No circuit diagrams/layouts shown.

**Impact**: Visual appeal and context missing.

### 4. Limited Session Detail

**Problem**: Only showing time, not full datetime with timezone.

**Impact**: Confusing for international users.

---

## Proposed Improvements

### Phase 1: Show All Session Times

Update the `RaceCard` component to display all sessions:

```tsx
// Current (only 2 sessions)
{race.qualifying_datetime && (
  <div>
    <p className="text-white/40">Qualifying</p>
    <p>{formatDate(race.qualifying_datetime)}</p>
  </div>
)}

// Proposed (all sessions)
<SessionTimeline race={race} />
```

#### New SessionTimeline Component

```tsx
interface SessionTimelineProps {
  race: Race;
}

function SessionTimeline({ race }: SessionTimelineProps) {
  const sessions = [
    { key: 'fp1', label: 'FP1', datetime: race.fp1_datetime },
    { key: 'fp2', label: 'FP2', datetime: race.fp2_datetime },
    { key: 'fp3', label: 'FP3', datetime: race.fp3_datetime },
    { key: 'sprint_qualifying', label: 'Sprint Quali', datetime: race.sprint_qualifying_datetime },
    { key: 'sprint', label: 'Sprint Race', datetime: race.sprint_race_datetime },
    { key: 'qualifying', label: 'Qualifying', datetime: race.qualifying_datetime },
    { key: 'race', label: 'Race', datetime: race.race_datetime },
  ].filter(s => s.datetime);

  return (
    <div className="space-y-2">
      {sessions.map(session => (
        <div key={session.key} className="flex justify-between text-sm">
          <span className="text-white/60">{session.label}</span>
          <span className="text-white/80">
            {formatDateTime(session.datetime)}
          </span>
        </div>
      ))}
    </div>
  );
}
```

### Phase 2: Sprint Weekend Badge

Add visual indicator for sprint weekends:

```tsx
{race.is_sprint_weekend && (
  <div className="absolute top-2 right-2 rounded-full bg-racing-red px-2 py-0.5 text-xs font-bold text-white">
    SPRINT
  </div>
)}
```

### Phase 3: Track Layout Images

#### Option A: Static Assets

Store track SVGs in `/public/tracks/`:
```
/public/tracks/
├── albert_park.svg
├── bahrain_international.svg
├── jeddah_corniche.svg
├── ...
```

Add to race card:
```tsx
<img 
  src={`/tracks/${race.circuit_slug}.svg`} 
  alt={race.circuit_name}
  className="h-24 w-auto opacity-50"
/>
```

#### Option B: MinIO Storage

Store in MinIO bucket `f1-tracks/`:
- More flexible
- Can update without code deploy
- Requires API endpoint

#### Option C: Third-Party API

Use F1 API or track layout service:
- Less maintenance
- May have licensing issues

**Recommendation**: Option A (static assets) for simplicity, with fallback to placeholder.

### Phase 4: Expanded Race Detail View

Create a full race detail page `/races/[id]`:

```
/races/1 - Australian Grand Prix

┌─────────────────────────────────────────────────────────┐
│ 🏁 Australian Grand Prix                    [UPCOMING]  │
│ Albert Park Circuit, Melbourne              Round 1     │
├─────────────────────────────────────────────────────────┤
│                                                         │
│  [TRACK LAYOUT SVG]                                    │
│                                                         │
├─────────────────────────────────────────────────────────┤
│ SCHEDULE (Local Time: AEDT)                            │
│                                                         │
│ Friday 13 March                                         │
│  ├─ FP1: 12:30                                         │
│  └─ FP2: 16:00                                         │
│                                                         │
│ Saturday 14 March                                       │
│  ├─ FP3: 12:30                                         │
│  └─ Qualifying: 16:00                                  │
│                                                         │
│ Sunday 15 March                                         │
│  └─ Race: 15:00                                        │
│                                                         │
├─────────────────────────────────────────────────────────┤
│ EPISODES                                                │
│  • Post-FP2 Episode: [Not generated]                   │
│  • Post-Race Episode: [Not generated]                  │
│                                                         │
│ [Generate Post-FP2] [Generate Post-Race]               │
└─────────────────────────────────────────────────────────┘
```

---

## Track Layout Sources

### Free/Open Sources

1. **Wikipedia Commons** - Many tracks have SVG layouts
   - https://commons.wikimedia.org/wiki/Category:Circuit_diagrams
   - License: Usually CC BY-SA

2. **OpenStreetMap** - Extract from map data
   - Custom rendering needed

3. **Manual Creation** - Create simple SVGs
   - Most control over style
   - Time-consuming

### Commercial Sources

1. **F1 Official** - Would need licensing
2. **Motorsport Images** - Professional quality

### Recommended Approach

1. Create simple, stylized SVG layouts
2. Match our brand colors (#337596 teal, #B87333 bronze)
3. Store in `/public/tracks/` directory
4. Use circuit slug for filename matching

---

## Implementation Plan

### PR 1: Session Times Display
- Update `RaceCard` to show all sessions
- Add sprint weekend badge
- Update API types if needed

### PR 2: Race Detail Page
- Create `/races/[id]/page.tsx`
- Full schedule view
- Episode generation links

### PR 3: Track Layouts
- Add placeholder track SVGs
- Integrate into race cards
- Create track layout component

---

## API Type Updates Needed

```typescript
// Current Race type in lib/api.ts
interface Race {
  id: number;
  season: number;
  round_number: number;
  race_name: string;
  circuit_name: string;
  country: string;
  race_date: string;
  qualifying_datetime: string | null;
  race_datetime: string | null;
  // Missing fields:
  // fp1_datetime
  // fp2_datetime
  // fp3_datetime
  // is_sprint_weekend
  // sprint_qualifying_datetime
  // sprint_race_datetime
}
```

Update to include all session fields.

---

## Summary

| Improvement | Priority | Effort | Impact |
|-------------|----------|--------|--------|
| All session times | High | Low | High |
| Sprint badge | High | Low | Medium |
| Track layouts | Medium | Medium | High |
| Race detail page | Medium | High | High |

**Recommendation**: Start with session times and sprint badge (quick wins), then add track layouts.
