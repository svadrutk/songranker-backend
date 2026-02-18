import asyncio
import os
import io
import sys
from PIL import Image
from playwright.async_api import async_playwright

# Setup paths
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.append(PROJECT_ROOT)

# Mock some dependencies if needed, but here we can just import
from app.clients.spotify import spotify_client
from app.api.v1.image_generation import render_receipt_html, ReceiptRequest, SongData
from app.core.config import settings

# Output directory
OUTPUT_DIR = os.path.join(PROJECT_ROOT, "..", "songranker-frontend", "public", "assets", "marquee")

# Artists to showcase
ARTIST_QUERIES = [
    "Radiohead", "Taylor Swift", "Kendrick Lamar", "Daft Punk", "The Weeknd",
    "SZA", "Arctic Monkeys", "Frank Ocean", "Lana Del Rey", "Tyler, The Creator",
    "Kanye West", "Billie Eilish", "Drake", "Olivia Rodrigo", "Harry Styles",
    "Tame Impala", "Gorillaz", "Pink Floyd", "The Beatles", "Fleetwood Mac",
    "Nirvana", "David Bowie", "Prince", "Michael Jackson"
]

async def generate_artist_receipt(artist_name: str, index: int, browser):
    try:
        print(f"[{index}] Processing {artist_name}...")
        
        # 1. Search for artist albums
        albums = await spotify_client.search_artist_albums(artist_name)
        if not albums:
            print(f"  ! No albums found for {artist_name}")
            return
        
        # Pick the most popular/first one
        album = albums[0]
        album_id = album["id"]
        cover_url = album["cover_art"]["url"]
        
        # 2. Get tracks for this album
        track_names = await spotify_client.get_album_tracks(album_id)
        if not track_names:
            print(f"  ! No tracks found for album {album['title']}")
            return
        
        # 3. Construct SongData
        songs = []
        for i, name in enumerate(track_names[:10]):
            songs.append(SongData(
                song_id=f"{album_id}-{i}",
                name=name,
                artist=artist_name,
                cover_url=cover_url
            ))
            
        # 4. Construct ReceiptRequest
        request = ReceiptRequest(
            songs=songs,
            orderId=1000 + index,
            dateStr="FEB 18 2026",
            timeStr="12:00PM"
        )
        
        # 5. Render HTML
        html_content = await render_receipt_html(request)
        
        # 6. Screenshot with Playwright
        page = await browser.new_page(viewport={"width": 1080, "height": 1200})
        await page.set_content(html_content, wait_until="networkidle", timeout=10000)
        await page.evaluate("document.fonts.ready")
        
        element = await page.query_selector("body")
        if not element:
            print(f"  ! Could not find body for {artist_name}")
            await page.close()
            return
            
        png_bytes = await element.screenshot(type="png", timeout=10000)
        await page.close()
        
        # 7. Convert to WebP using Pillow
        img = Image.open(io.BytesIO(png_bytes))
        # Optimize for 400px width
        aspect_ratio = img.height / img.width
        img = img.resize((400, int(400 * aspect_ratio)), Image.Resampling.LANCZOS)
        
        output_path = os.path.join(OUTPUT_DIR, f"receipt_{index}.webp")
        img.save(output_path, "WEBP", quality=75)
        print(f"  ✓ Saved to {output_path}")
        
    except Exception as e:
        print(f"  ! Error processing {artist_name}: {e}")

async def main():
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    
    async with async_playwright() as p:
        # Launch browser with specific flags for reliability in various environments
        browser = await p.chromium.launch(args=["--no-sandbox", "--disable-setuid-sandbox"])
        
        # Run in batches to avoid overwhelming the Spotify API or local resources
        batch_size = 4
        for i in range(0, len(ARTIST_QUERIES), batch_size):
            batch = ARTIST_QUERIES[i:i+batch_size]
            tasks = [generate_artist_receipt(name, i + j, browser) for j, name in enumerate(batch)]
            await asyncio.gather(*tasks)
            
        await browser.close()

if __name__ == "__main__":
    asyncio.run(main())
