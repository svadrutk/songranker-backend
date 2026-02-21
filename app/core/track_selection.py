from __future__ import annotations

import hashlib
import random
from typing import Any, Dict, Iterable, List, Optional, Tuple

from app.core.utils import normalize_title


def _stable_seed_int(seed: str) -> int:
    digest = hashlib.sha256(seed.encode("utf-8")).digest()
    return int.from_bytes(digest[:8], "big", signed=False)


def _track_key(track: Dict[str, Any]) -> Tuple[str, str]:
    """Key for deduping tracks before quick-rank selection.

    Priority:
    - ISRC (best cross-release / cross-platform identifier)
    - Spotify track ID
    - Apple Music catalog ID
    - (normalized title, lowercased primary artist)
    """
    isrc = track.get("isrc")
    if isrc:
        return ("isrc", str(isrc))

    spotify_id = track.get("spotify_id")
    if spotify_id:
        return ("spotify_id", str(spotify_id))

    apple_music_id = track.get("apple_music_id")
    if apple_music_id:
        return ("apple_music_id", str(apple_music_id))

    name = normalize_title(str(track.get("name") or ""))
    artist = str(track.get("artist") or "").lower()
    return ("fallback", f"{artist}:{name}")


def dedupe_tracks_for_selection(tracks: Iterable[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Return a deduped list of tracks, preferring the most-informative entry.

    For collisions, we keep the entry with higher popularity. This is important
    for quick-rank anchor selection.
    """
    best: Dict[Tuple[str, str], Dict[str, Any]] = {}
    order: List[Tuple[str, str]] = []

    for t in tracks:
        if not isinstance(t, dict):
            continue

        if not t.get("name") or not t.get("artist"):
            continue

        key = _track_key(t)
        existing = best.get(key)
        if existing is None:
            best[key] = t
            order.append(key)
            continue

        existing_pop = int(existing.get("popularity") or 0)
        new_pop = int(t.get("popularity") or 0)
        if new_pop > existing_pop:
            best[key] = t

    return [best[k] for k in order if k in best]


def select_anchor_variance_quick_rank(
    tracks: Iterable[Dict[str, Any]],
    *,
    anchors: int = 30,
    wildcards: int = 20,
    seed: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """Pick quick-rank tracks using Anchor & Variance.

    - Anchors: top N by popularity
    - Wildcards: random sample from the remainder
    - Result is shuffled to avoid position bias

    If seed is provided, selection is deterministic for the same inputs.
    """
    deduped = dedupe_tracks_for_selection(tracks)
    target = anchors + wildcards
    if len(deduped) <= target:
        return deduped

    sorted_by_pop = sorted(deduped, key=lambda t: int(t.get("popularity") or 0), reverse=True)
    anchor_list = sorted_by_pop[:anchors]
    remaining = sorted_by_pop[anchors:]

    rng = random.Random(_stable_seed_int(seed)) if seed else random
    wildcard_list = rng.sample(remaining, k=min(wildcards, len(remaining)))

    result = anchor_list + wildcard_list
    rng.shuffle(result)
    return result
