#!/usr/bin/env python
"""
Analyze comparison data for a session to see which songs are under-compared.
"""
import asyncio
import sys
from collections import defaultdict
from app.clients.supabase_db import supabase_client


async def analyze_session(session_id: str):
    """Analyze comparison distribution for a session."""
    
    # Fetch data
    songs, comparisons = await asyncio.gather(
        supabase_client.get_session_songs(session_id),
        supabase_client.get_session_comparisons(session_id)
    )
    
    print(f"\n{'='*70}")
    print(f"Session Analysis: {session_id}")
    print(f"{'='*70}")
    print(f"Total songs: {len(songs)}, Total comparisons: {len(comparisons)}")
    print(f"Average comparisons per song: {len(comparisons) * 2 / len(songs):.1f}\n")
    
    # Build lookup
    id_to_name = {str(s["song_id"]): s.get("name", "?") for s in songs}
    
    # Count comparisons and wins per song
    comp_count = defaultdict(int)
    win_count = defaultdict(int)
    loss_count = defaultdict(int)
    tie_count = defaultdict(int)
    idc_count = defaultdict(int)  # "I don't care" responses
    
    for comp in comparisons:
        a = str(comp.get("song_a_id", ""))
        b = str(comp.get("song_b_id", ""))
        winner = str(comp.get("winner_id") or "")
        is_tie = comp.get("is_tie", False)
        
        comp_count[a] += 1
        comp_count[b] += 1
        
        if is_tie:
            tie_count[a] += 1
            tie_count[b] += 1
        elif winner == a:
            win_count[a] += 1
            loss_count[b] += 1
        elif winner == b:
            win_count[b] += 1
            loss_count[a] += 1
        else:
            # IDC - no winner, not a tie
            idc_count[a] += 1
            idc_count[b] += 1
    
    # Sort by comparison count (ascending to show under-compared first)
    sorted_songs = sorted(
        [(sid, comp_count[sid]) for sid in id_to_name.keys()],
        key=lambda x: x[1]
    )
    
    # Show under-compared songs
    print("UNDER-COMPARED SONGS (< 4 comparisons):")
    print("-" * 70)
    under_compared = [(sid, cnt) for sid, cnt in sorted_songs if cnt < 4]
    if under_compared:
        for sid, cnt in under_compared:
            name = id_to_name[sid][:40]
            w, l, t = win_count[sid], loss_count[sid], tie_count[sid]
            print(f"  {name:40} comps={cnt} W={w} L={l} T={t}")
    else:
        print("  None! All songs have 4+ comparisons.")
    
    print(f"\n{'='*70}")
    print("FULL BREAKDOWN (sorted by comparison count):")
    print("-" * 70)
    print(f"{'Song':<40} {'Comps':>6} {'Wins':>5} {'Loss':>5} {'Ties':>5} {'IDC':>5} {'Win%':>6}")
    print("-" * 70)
    
    for sid, cnt in sorted_songs:
        name = id_to_name[sid][:40]
        w, l, t, i = win_count[sid], loss_count[sid], tie_count[sid], idc_count[sid]
        meaningful = w + l + t
        win_pct = (w + t * 0.5) / meaningful * 100 if meaningful > 0 else 0
        print(f"{name:<40} {cnt:>6} {w:>5} {l:>5} {t:>5} {i:>5} {win_pct:>5.1f}%")
    
    # Specifically check the songs user mentioned (11-14)
    print(f"\n{'='*70}")
    print("SONGS OF INTEREST (ranks 11-14 in new algo):")
    print("-" * 70)
    
    target_songs = ["leavemealone", "adore u", "ten", "Victory Lap"]
    for target in target_songs:
        # Find by partial match
        for sid, name in id_to_name.items():
            if target.lower() in name.lower():
                cnt = comp_count[sid]
                w, l, t = win_count[sid], loss_count[sid], tie_count[sid]
                meaningful = w + l + t
                win_pct = (w + t * 0.5) / meaningful * 100 if meaningful > 0 else 0
                status = "⚠️ UNDER-COMPARED" if cnt < 4 else "✓ OK"
                print(f"  {name[:35]:35} comps={cnt:2} W={w} L={l} T={t} ({win_pct:.0f}% win) {status}")
                break


async def main():
    session_id = sys.argv[1] if len(sys.argv) > 1 else "c30f49c7-82ca-419b-956a-95b426ddad23"
    await analyze_session(session_id)


if __name__ == "__main__":
    asyncio.run(main())
