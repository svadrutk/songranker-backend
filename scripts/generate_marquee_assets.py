import asyncio
from io import BytesIO
import sys
from pathlib import Path
from PIL import Image
from playwright.async_api import async_playwright, Browser

# Setup paths
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.append(str(PROJECT_ROOT))

# Mock some dependencies if needed, but here we can just import
from app.clients.spotify import spotify_client # noqa: E402
from app.api.v1.image_generation import render_receipt_html, ReceiptRequest, SongData # noqa: E402

# Output directory
OUTPUT_DIR = PROJECT_ROOT.parent / "songranker-frontend" / "public" / "assets" / "marquee"

# Artists to showcase
ARTIST_QUERIES = [
    "Radiohead", "Taylor Swift", "Kendrick Lamar", "Daft Punk", "The Weeknd",
    "SZA", "Arctic Monkeys", "Frank Ocean", "Lana Del Rey", "Tyler, The Creator",
    "Kanye West", "Billie Eilish", "Drake", "Olivia Rodrigo", "Harry Styles",
    "Tame Impala", "Gorillaz", "Pink Floyd", "The Beatles", "Fleetwood Mac",
    "Nirvana", "David Bowie", "Prince", "Michael Jackson"
]

async def generate_artist_receipt(artist_name: str, index: int, browser: Browser) -> None:
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
        songs = [
            SongData(
                song_id=f"{album_id}-{i}",
                name=name,
                artist=artist_name,
                cover_url=cover_url
            ) for i, name in enumerate(track_names[:10])
        ]
            
        # 4. Construct ReceiptRequest
        request = ReceiptRequest(
            songs=songs,
            orderId=1000 + index,
            dateStr="FEB 18 2026",
            timeStr="12:00PM"
        )
        
        # 5. Render HTML
        html_content = render_receipt_html(request)
        
        # 6. Screenshot with Playwright
        async with await browser.new_page(viewport={"width": 900, "height": 1200}) as page:
            await page.set_content(html_content, wait_until="networkidle", timeout=10000)
            
            element = await page.query_selector(".receipt-container")
            if not element:
                print(f"  ! Could not find receipt-container for {artist_name}")
                return
                
            png_bytes = await element.screenshot(type="png", timeout=10000, omit_background=True)
        
        # 7. Convert to WebP using Pillow
        img = Image.open(BytesIO(png_bytes))
        
        # Resize to 400px width to reduce VRAM usage (performance-oracle)
        target_width = 400
        w_percent = (target_width / float(img.size[0]))
        h_size = int((float(img.size[1]) * float(w_percent)))
        img = img.resize((target_width, h_size), Image.Resampling.LANCZOS)
        
        output_path = OUTPUT_DIR / f"receipt_{index}.webp"
        img.save(output_path, "WEBP", quality=60)
        print(f"  ✓ Saved to {output_path}")
        
    except Exception as e:
        print(f"  ! Error processing {artist_name}: {e}")

async def main() -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    
    async with async_playwright() as p:
        # NOTE: --no-sandbox is required for Playwright to run in most Docker/Linux environments
        # without CAP_SYS_ADMIN. Security is maintained by container isolation and input sanitization.
        browser = await p.chromium.launch(args=["--no-sandbox", "--disable-setuid-sandbox"])
        
        # Run all tasks concurrently for simplicity
        tasks = [generate_artist_receipt(name, i, browser) for i, name in enumerate(ARTIST_QUERIES)]
        await asyncio.gather(*tasks)
            
        await browser.close()

if __name__ == "__main__":
    asyncio.run(main())
