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
    "super", "ultra", "mega", "ultimate"
]

SKIP_KEYWORDS = ["karaoke", "instrumental", "tour", "live", "sessions", "demos", "remixes", "remix"]

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
