# Leaderboard API Update - Pending Comparisons

## Summary

The leaderboard API now shows **pending comparisons** to provide real-time feedback about how many duels are waiting to be processed into the global ranking.

## Problem

Previously, the leaderboard would show outdated comparison counts because:
- Global rankings only update every 10 minutes (to reduce database load)
- If users did 55 duels in 5 minutes, the leaderboard still showed "5 comparisons"
- No way to tell if the ranking was fresh or stale

## Solution

The API now returns:
1. **`total_comparisons`**: Number of comparisons in the current global ranking (processed)
2. **`pending_comparisons`**: Number of comparisons waiting to be processed
3. **`last_updated`**: ISO 8601 timestamp of when the global ranking was last updated

## API Changes

### GET `/leaderboard/{artist}`

**Before:**
```json
{
  "artist": "Ariana Grande",
  "songs": [...],
  "total_comparisons": 5,
  "last_updated": "2024-01-20"
}
```

**After:**
```json
{
  "artist": "Ariana Grande",
  "songs": [...],
  "total_comparisons": 5,
  "pending_comparisons": 55,
  "last_updated": "2024-01-20T15:30:45.123Z"
}
```

### GET `/leaderboard/{artist}/stats`

**Before:**
```json
{
  "artist": "Ariana Grande",
  "total_comparisons": 5,
  "last_updated": "2024-01-20",
  "created_at": "2024-01-15"
}
```

**After:**
```json
{
  "artist": "Ariana Grande",
  "total_comparisons": 5,
  "pending_comparisons": 55,
  "last_updated": "2024-01-20T15:30:45.123Z",
  "created_at": "2024-01-15T10:00:00.000Z"
}
```

## Frontend Implementation

### 1. Display Pending Comparisons

Show users that there are more comparisons being processed:

```tsx
// Example UI
<div>
  <h3>Global Ranking</h3>
  <p>{totalComparisons} comparisons</p>
  {pendingComparisons > 0 && (
    <Badge variant="warning">
      +{pendingComparisons} pending
    </Badge>
  )}
</div>
```

**Suggested copy:**
- `"5 comparisons (55 pending)"` 
- `"5 processed · 55 pending"`
- `"60 total comparisons (55 processing...)"` 

### 2. Show Accurate Timestamps

The `last_updated` field is now an ISO 8601 timestamp. Use a library like `date-fns` or `dayjs` to format it properly:

```tsx
import { formatDistanceToNow, format } from 'date-fns';

// Relative time: "Updated 5 minutes ago"
const relativeTime = formatDistanceToNow(new Date(lastUpdated), { 
  addSuffix: true 
});

// Absolute time: "Jan 20, 2024 at 3:30 PM"
const absoluteTime = format(new Date(lastUpdated), 'PPp');
```

**Suggested UI:**
```tsx
<div className="text-sm text-gray-500">
  Last updated {formatDistanceToNow(new Date(lastUpdated))} ago
  {pendingComparisons > 0 && (
    <span className="text-orange-600">
      {' '}· Next update in ~{10 - minutesSinceUpdate} min
    </span>
  )}
</div>
```

### 3. Show "Freshness" Indicator

Use colors to indicate data freshness:

```tsx
const getStatusColor = (lastUpdated: string, pending: number) => {
  if (pending === 0) return 'green'; // All caught up
  
  const minutesAgo = differenceInMinutes(new Date(), new Date(lastUpdated));
  if (minutesAgo < 2) return 'green';   // Very fresh
  if (minutesAgo < 5) return 'yellow';  // Slightly stale
  return 'orange';                      // Update coming soon
};
```

### 4. Auto-Refresh When Pending

If there are pending comparisons, poll the API more frequently:

```tsx
const pollInterval = pendingComparisons > 0 
  ? 30000  // 30 seconds when pending
  : 120000; // 2 minutes when caught up

useEffect(() => {
  const interval = setInterval(fetchLeaderboard, pollInterval);
  return () => clearInterval(interval);
}, [pendingComparisons]);
```

## Example UI Mockups

### Option 1: Badge Style
```
┌─────────────────────────────────────┐
│ Global Leaderboard                  │
│ 5 comparisons  [+55 pending]        │
│ Updated 2 minutes ago               │
└─────────────────────────────────────┘
```

### Option 2: Progress Bar Style
```
┌─────────────────────────────────────┐
│ Global Leaderboard                  │
│ 60 total comparisons                │
│ [████████░░░░░░░░] 5/60 processed   │
│ Updated 2 minutes ago               │
└─────────────────────────────────────┘
```

### Option 3: Status Banner
```
┌─────────────────────────────────────┐
│ ⚠️ Rankings updating...             │
│ 55 new comparisons are being        │
│ processed. Check back in 8 minutes! │
└─────────────────────────────────────┘
│ Global Leaderboard (5 comparisons)  │
│ Last updated: Jan 20 at 3:30 PM     │
└─────────────────────────────────────┘
```

## Benefits

1. **Transparency**: Users know their comparisons are being processed
2. **Expectations**: Clear when the next update will happen (~10 min intervals)
3. **Engagement**: Users can come back to see updated rankings
4. **Trust**: Shows the system is working, not broken

## Technical Details

### How Pending is Calculated

```python
# In the backend
total_comparisons = count_all_comparisons_for_artist()
processed_comparisons = artist_stats.total_comparisons_count
pending_comparisons = total_comparisons - processed_comparisons
```

### Global Update Trigger

Global rankings update when:
1. A session ranking completes (every 5 duels)
2. AND it's been 10+ minutes since the last global update for that artist

So if you do 55 duels in 5 minutes:
- Session rankings update 11 times (5, 10, 15, ..., 55)
- Global ranking updates once (at the 10-minute mark)
- The "pending" counter shows 50 comparisons waiting

### Caching

The leaderboard response is cached for **2 minutes** to handle traffic bursts. This means:
- If pending comparisons increase during cache time, they won't show until cache expires
- This is acceptable since updates happen every 10 minutes anyway
- Use cache busting (query params or manual refresh) if you need immediate data

## Migration Guide

### Step 1: Update TypeScript Types

```typescript
// Before
interface LeaderboardResponse {
  artist: string;
  songs: LeaderboardSong[];
  total_comparisons: number;
  last_updated?: string;
}

// After
interface LeaderboardResponse {
  artist: string;
  songs: LeaderboardSong[];
  total_comparisons: number;
  pending_comparisons: number;  // NEW
  last_updated?: string;         // Now ISO 8601 format
}
```

### Step 2: Update UI Components

Replace all instances of:
```tsx
{totalComparisons} comparisons
```

With:
```tsx
{totalComparisons} comparisons
{pendingComparisons > 0 && ` (+${pendingComparisons} pending)`}
```

### Step 3: Update Timestamp Formatting

Replace:
```tsx
// Old: Just showing date
{lastUpdated}
```

With:
```tsx
// New: Showing relative time
{formatDistanceToNow(new Date(lastUpdated))} ago
```

## Testing

Use the backend test script:

```bash
cd songranker-backend
uv run python test_leaderboard_pending.py
```

This will show:
- Processed comparisons
- Pending comparisons  
- Last updated timestamp
- Number of songs in leaderboard

## Questions?

- **Q: Why 10 minute intervals?**
  A: Balance between freshness and database load. Can be adjusted if needed.

- **Q: Can we force an immediate update?**
  A: Not currently, but we could add a "Refresh Now" button that triggers a global update.

- **Q: What if pending_comparisons is negative?**
  A: The backend returns `max(0, calculated_pending)` so it will never be negative.

- **Q: Does this affect session rankings?**
  A: No, session rankings still update every 5 duels as before. This only affects the global leaderboard.
