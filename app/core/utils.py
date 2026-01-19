import re

from typing import Optional, TypedDict

class CoverArtInfo(TypedDict):
    front: bool
    url: Optional[str]

class ReleaseGroupData(TypedDict):
    id: str
    title: str
    artist: str
    type: str
    cover_art: CoverArtInfo

DELUXE_KEYWORDS = [
    "deluxe", "expanded", "platinum", "special", "edition", 
    "complete", "remastered", "3am", "til dawn", "paradise",
    "gold", "diamond", "anniversary", "collector", "limited",
    "super", "ultra", "mega", "ultimate", "bonus", "extra", "track", "plus"
]

SKIP_KEYWORDS = ["karaoke", "instrumental", "tour", "live", "sessions", "demos", "remixes", "remix"]

def is_spotify_id(resource_id: str) -> bool:
    """Check if the ID looks like a Spotify ID (22 chars, alphanumeric)."""
    return len(resource_id) == 22 and "-" not in resource_id and ":" not in resource_id

def normalize_title(title: str) -> str:
    if not title:
        return ""
    # Remove parenthetical info which often contains "Deluxe Edition"
    base = title.lower()
    base = re.sub(r'[\(\[\{].*?[\)\]\}]', '', base)
    # Remove non-alphanumeric
    return re.sub(r'[^a-z0-9]', '', base).strip()

def get_type_priority(rg_type: str) -> int:
    if rg_type == "Album":
        return 0
    if rg_type == "EP":
        return 1
    if rg_type == "Single":
        return 2
    return 3

def calculate_elo(rating_a: float, rating_b: float, score_a: float, k_factor: int = 32) -> tuple[float, float]:
    """
    Calculate new Elo ratings for two players.
    score_a: 1.0 for win, 0.5 for tie, 0.0 for loss
    """
    expected_a = 1 / (1 + 10 ** ((rating_b - rating_a) / 400))
    expected_b = 1 - expected_a
    
    return (
        rating_a + k_factor * (score_a - expected_a),
        rating_b + k_factor * (1.0 - score_a - expected_b)
    )
