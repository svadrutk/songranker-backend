import asyncio
import httpx
from app.core.config import settings

async def inspect_lastfm():
    url = "http://ws.audioscrobbler.com/2.0/"
    params = {
        "method": "artist.gettopalbums",
        "artist": "Taylor Swift",
        "api_key": settings.LASTFM_API_KEY,
        "format": "json",
        "limit": 5
    }
    
    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.get(url, params=params)
        data = resp.json()
        print("Top Albums structure:")
        albums = data.get("topalbums", {}).get("album", [])
        if albums:
            print(f"Sample keys: {albums[0].keys()}")
            # Check if any album has a type-like field
            for a in albums:
                print(f"Album: {a.get('name')}")
                # Look for anything suggesting type
                potential_types = {k: v for k, v in a.items() if "type" in k.lower() or "tag" in k.lower()}
                print(f"  Type-related fields: {potential_types}")

        # Inspect album.getInfo
        if albums:
            params["method"] = "album.getinfo"
            params["album"] = albums[0].get("name")
            resp = await client.get(url, params=params)
            info = resp.json().get("album", {})
            print("\nAlbum Info structure:")
            print(f"Sample keys: {info.keys()}")
            potential_types = {k: v for k, v in info.items() if "type" in k.lower() or "tag" in k.lower()}
            print(f"  Type-related fields: {potential_types}")
            if "tags" in info:
                print(f"  Tags: {info['tags']}")

if __name__ == "__main__":
    asyncio.run(inspect_lastfm())
