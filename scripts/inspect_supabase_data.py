"""
Inspect Supabase tables to verify schema and data availability.
Used to assess feasibility of global dashboard visualizations.
Run from repo root: cd songranker-backend && uv run python scripts/inspect_supabase_data.py
"""
import asyncio
import os
import sys
from pathlib import Path

# Ensure backend root is on path and load .env
backend_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(backend_root))
os.chdir(backend_root)

from dotenv import load_dotenv
load_dotenv()

from app.clients.supabase_db import supabase_client
from postgrest.types import CountMethod


async def main():
    client = await supabase_client.get_client()

    report = []

    # --- Table counts ---
    report.append("=== TABLE ROW COUNTS ===\n")
    for table in ["songs", "artist_stats", "comparisons", "sessions", "session_songs", "feedback", "rankings"]:
        try:
            r = await client.table(table).select("*", count=CountMethod.exact).limit(1).execute()
            count = r.count if r.count is not None else "?"
            report.append(f"  {table}: {count} rows")
        except Exception as e:
            report.append(f"  {table}: ERROR - {e}")

    # --- songs: columns needed for leaderboard viz (global_elo, global_votes_count, etc.) ---
    report.append("\n=== SONGS (sample + column check) ===")
    try:
        r = await client.table("songs").select(
            "id, name, artist, album, cover_url, global_elo, global_bt_strength, global_votes_count"
        ).limit(3).execute()
        if r.data and len(r.data) > 0:
            report.append(f"  Sample columns present: {list(r.data[0].keys())}")
            for i, row in enumerate(r.data[:2]):
                report.append(f"  Sample {i+1}: artist={row.get('artist')} global_elo={row.get('global_elo')} global_votes_count={row.get('global_votes_count')}")
        else:
            report.append("  No rows in songs.")
    except Exception as e:
        report.append(f"  ERROR: {e}")

    # --- artist_stats: for "comparisons per artist" and "last updated" ---
    report.append("\n=== ARTIST_STATS (for dashboard artists list) ===")
    try:
        r = await client.table("artist_stats").select(
            "artist, total_comparisons_count, last_global_update_at"
        ).order("total_comparisons_count", desc=True).limit(5).execute()
        if r.data and len(r.data) > 0:
            report.append(f"  Top 5 artists by comparisons: {[(x['artist'], x['total_comparisons_count']) for x in r.data]}")
        else:
            report.append("  No rows in artist_stats.")
    except Exception as e:
        report.append(f"  ERROR: {e}")

    # --- comparisons: decision_time_ms for "decision time" viz ---
    report.append("\n=== COMPARISONS (decision_time_ms present?) ===")
    try:
        r = await client.table("comparisons").select(
            "session_id, song_a_id, song_b_id, winner_id, is_tie, decision_time_ms"
        ).limit(3).execute()
        if r.data and len(r.data) > 0:
            report.append(f"  Columns: {list(r.data[0].keys())}")
            with_dt = sum(1 for x in r.data if x.get("decision_time_ms") is not None)
            report.append(f"  Sample: {len(r.data)} rows, {with_dt} with decision_time_ms set")
        else:
            report.append("  No rows in comparisons.")
    except Exception as e:
        report.append(f"  ERROR: {e}")

    # --- sessions: convergence_score, created_at, user_id for "your activity" viz ---
    report.append("\n=== SESSIONS (convergence_score, created_at) ===")
    try:
        r = await client.table("sessions").select(
            "id, status, user_id, created_at, convergence_score, last_active_at"
        ).order("created_at", desc=True).limit(5).execute()
        if r.data and len(r.data) > 0:
            report.append(f"  Columns: {list(r.data[0].keys())}")
            for i, row in enumerate(r.data[:3]):
                report.append(f"  Session {i+1}: created_at={row.get('created_at')} convergence_score={row.get('convergence_score')} user_id={row.get('user_id')}")
        else:
            report.append("  No rows in sessions.")
    except Exception as e:
        report.append(f"  ERROR: {e}")

    # --- RPC: get_artist_songs (for leaderboard data) ---
    report.append("\n=== RPC get_artist_songs (sample artist) ===")
    try:
        # Use first artist from artist_stats if any, else hardcode
        arts = await client.table("artist_stats").select("artist").limit(1).execute()
        artist = arts.data[0]["artist"] if arts.data else "Taylor Swift"
        r = await client.rpc("get_artist_songs", {"p_artist": artist}).execute()
        data = r.data or []
        report.append(f"  Artist '{artist}': {len(data)} songs returned")
        if data and len(data) > 0:
            report.append(f"  RPC columns: {list(data[0].keys())}")
    except Exception as e:
        report.append(f"  ERROR: {e}")

    # --- RPC: get_artist_comparisons ---
    report.append("\n=== RPC get_artist_comparisons (count) ===")
    try:
        arts = await client.table("artist_stats").select("artist").limit(1).execute()
        artist = arts.data[0]["artist"] if arts.data else "Taylor Swift"
        r = await client.rpc("get_artist_comparisons", {"p_artist": artist}).execute()
        data = r.data or []
        report.append(f"  Artist '{artist}': {len(data)} comparisons")
    except Exception as e:
        report.append(f"  ERROR: {e}")

    # --- RPC: get_user_session_summaries (needs a real user_id if any) ---
    report.append("\n=== RPC get_user_session_summaries ===")
    try:
        # Get a user_id from sessions if any
        sess = await client.table("sessions").select("user_id").not_.is_("user_id", "null").limit(1).execute()
        user_id = sess.data[0]["user_id"] if sess.data and sess.data[0].get("user_id") else None
        if user_id:
            r = await client.rpc("get_user_session_summaries", {"p_user_id": str(user_id)}).execute()
            data = r.data or []
            report.append(f"  User {user_id[:8]}...: {len(data)} session summaries")
            if data and len(data) > 0:
                report.append(f"  Summary keys: {list(data[0].keys())}")
        else:
            report.append("  No sessions with user_id found; RPC not exercised.")
    except Exception as e:
        report.append(f"  ERROR: {e}")

    text = "\n".join(report)
    print(text)
    return text


if __name__ == "__main__":
    asyncio.run(main())
