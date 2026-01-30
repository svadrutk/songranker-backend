# Global Ranking Update Flow

## Overview

Global rankings aggregate comparisons across all user sessions to create a unified leaderboard for each artist. The system uses a two-way trigger mechanism to keep rankings up-to-date.

## Two-Way Trigger System

### 1. Active Ranking Trigger (Primary)

**When:** User completes comparisons
**Flow:**
```
User completes comparison 
  → Every 5th comparison triggers session ranking update
  → Session ranking completes
  → Check: "Has it been 10+ minutes since last global update?"
    → YES: Enqueue global ranking update
    → NO:  Skip (comparisons become "pending")
```

**Example:**
```
User does 25 comparisons in 5 minutes:
- Comparison 5:  Session ranking ✓, Global ranking ✓ (first update)
- Comparison 10: Session ranking ✓, Global ranking ✗ (only 5 min passed)
- Comparison 15: Session ranking ✓, Global ranking ✗ (only 10 min passed)
- Comparison 20: Session ranking ✓, Global ranking ✓ (15 min passed)
- Comparison 25: Session ranking ✓, Global ranking ✗ (only 5 min since last)

Result: 2 global updates, 10 comparisons pending
```

### 2. Leaderboard View Trigger (Fallback)

**When:** User views the leaderboard
**Flow:**
```
User views /leaderboard/{artist}
  → API returns current ranking + pending count
  → Check: "Are there pending comparisons?"
    → NO: Done
    → YES: Check "Has it been 10+ minutes since last update?"
      → YES: Enqueue global ranking update in background
      → NO:  Skip
```

**Example:**
```
Scenario: User does 55 comparisons and stops
- Last comparison: 3:30 PM
- Last global update: 3:20 PM (10 comparisons processed)
- Pending comparisons: 45

Timeline:
3:30 PM - User stops ranking
3:35 PM - Someone views leaderboard → No update (only 5 min passed)
3:40 PM - Someone views leaderboard → Update triggered! (10+ min passed)
3:41 PM - Global ranking update completes (all 55 comparisons now processed)
```

## Why the 10-Minute Throttle?

### Problem Without Throttle
- Every 5th comparison triggers a global update
- 100 active users = 20+ global updates per minute
- Each update processes ALL comparisons for that artist (expensive)
- Database gets hammered

### Solution: Time-Based Throttle
- Global updates limited to once per 10 minutes per artist
- Session rankings still update every 5 comparisons (fast, local)
- Global rankings update periodically (slower, comprehensive)
- Pending comparisons tracked so users know data is fresh or stale

## Data Freshness

### Session Ranking (Always Fresh)
- Updates every 5 comparisons
- Only processes songs in YOUR session
- Fast (<100ms)
- Powers the ranking UI during active play

### Global Ranking (Periodic)
- Updates every 10+ minutes
- Processes ALL comparisons across ALL sessions
- Slower (~500ms-2s for popular artists)
- Powers the public leaderboard

## API Response Structure

```json
{
  "artist": "Ariana Grande",
  "songs": [...],
  "total_comparisons": 5,        // Comparisons in global ranking (processed)
  "pending_comparisons": 55,     // Comparisons waiting to be processed
  "last_updated": "2024-01-20T15:30:45.123Z"
}
```

**Interpreting the Data:**
- `pending_comparisons = 0`: Ranking is up-to-date
- `pending_comparisons > 0`: New comparisons since last update
- If `pending_comparisons > 0` AND `last_updated` is 10+ minutes ago:
  - The view just triggered an update
  - Ranking will be fresh in ~30 seconds
  - Tell user: "Updating... refresh in a moment!"

## Frontend Recommendations

### 1. Show Freshness Indicator

```tsx
const getFreshnessStatus = (lastUpdated: string, pending: number) => {
  if (pending === 0) {
    return { status: 'fresh', color: 'green', text: 'Up to date' };
  }
  
  const minutesAgo = differenceInMinutes(new Date(), new Date(lastUpdated));
  
  if (minutesAgo < 10) {
    return { 
      status: 'stale', 
      color: 'yellow', 
      text: `${pending} pending • Updates in ${10 - minutesAgo} min` 
    };
  } else {
    return { 
      status: 'updating', 
      color: 'blue', 
      text: `Updating ${pending} comparisons...` 
    };
  }
};
```

### 2. Auto-Refresh When Updating

If the leaderboard just triggered an update, poll more frequently:

```tsx
const [isUpdating, setIsUpdating] = useState(false);

useEffect(() => {
  const minutesAgo = differenceInMinutes(new Date(), new Date(lastUpdated));
  const shouldBeUpdating = pending > 0 && minutesAgo >= 10;
  
  if (shouldBeUpdating && !isUpdating) {
    setIsUpdating(true);
    // Poll every 5 seconds for 1 minute
    const interval = setInterval(fetchLeaderboard, 5000);
    setTimeout(() => {
      clearInterval(interval);
      setIsUpdating(false);
    }, 60000);
  }
}, [pending, lastUpdated]);
```

### 3. Visual Feedback

```tsx
{isUpdating && (
  <div className="bg-blue-50 border-l-4 border-blue-400 p-4">
    <div className="flex">
      <Spinner />
      <div className="ml-3">
        <p className="text-sm text-blue-700">
          Processing {pending} new comparisons...
        </p>
        <p className="text-xs text-blue-600 mt-1">
          This may take up to a minute. The page will update automatically.
        </p>
      </div>
    </div>
  </div>
)}
```

## Edge Cases

### Multiple Users Viewing Simultaneously
- First request triggers update and sets in-memory lock
- Subsequent requests see lock and skip triggering
- All users see pending count until update completes

### User Leaves During Update
- Update completes in background worker
- Next view shows fresh data (pending = 0)

### Very Popular Artist (1000+ comparisons)
- Global update might take 2-3 seconds
- Background task ensures API stays responsive
- Users see old ranking + pending count during update

### No One Views Leaderboard for Days
- Comparisons stay pending indefinitely
- This is acceptable - data is frozen in time
- Next view will trigger update and process all pending

## Monitoring

### Key Metrics to Track
1. **Pending Comparisons**: Average and max per artist
2. **Time Since Last Update**: Distribution across artists
3. **Update Trigger Source**: Active ranking vs. view trigger
4. **Update Duration**: How long global updates take

### Alerts to Set Up
- Pending comparisons > 1000 for any artist
- Time since update > 30 minutes for top 10 artists
- Global update taking > 5 seconds

## Troubleshooting

### "Pending comparisons never decrease"

**Cause:** Worker not running or global update failing

**Debug:**
```bash
# Check worker is running
docker-compose logs worker_leaderboard

# Check queue
redis-cli LLEN rq:queue:leaderboard

# Check for failed jobs
redis-cli LRANGE rq:queue:failed 0 -1
```

### "Leaderboard shows 0 comparisons but I just ranked"

**Cause:** Viewing leaderboard immediately after ranking (session not updated yet)

**Expected Behavior:**
- Session ranking queued (processing)
- Global ranking hasn't run yet
- View after 5-10 seconds and session data will show

### "Pending comparisons showing negative numbers"

**Cause:** This should never happen - backend returns `max(0, pending)`

**If it does happen:**
- Bug in calculation logic
- Database inconsistency (comparisons deleted but stats not updated)

## Future Improvements

### 1. WebSocket Updates
Push updates to connected clients when global ranking completes:
```typescript
socket.on('ranking_updated', ({ artist, comparisons }) => {
  if (currentArtist === artist) {
    refetchLeaderboard();
  }
});
```

### 2. Scheduled Background Job
Run every 10 minutes to update all artists with pending comparisons:
```python
@scheduler.scheduled_job('interval', minutes=10)
def update_all_stale_rankings():
    artists = get_artists_with_pending_comparisons()
    for artist in artists:
        if time_since_update(artist) >= 10:
            leaderboard_queue.enqueue(run_global_ranking_update, artist)
```

### 3. Smart Throttling
Adjust throttle based on artist popularity:
```python
# Popular artists update more frequently
throttle = 5 if total_sessions > 100 else 10
```

### 4. Immediate Update Button
Let users force an update:
```tsx
<button onClick={forceUpdate}>
  Refresh Rankings Now ({pending} pending)
</button>
```

## Summary

The two-way trigger system ensures:
1. **Active sessions** trigger updates regularly (every 10+ minutes)
2. **Dormant leaderboards** update when viewed (if stale)
3. **Users always see** how fresh the data is (pending count)
4. **Database load** stays reasonable (throttled updates)

This balances freshness with performance, giving users transparency about data staleness while keeping the system scalable.
