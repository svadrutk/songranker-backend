import logging
import os
import base64
from typing import List, Optional, Any
from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from jinja2 import Environment, FileSystemLoader
from playwright.async_api import async_playwright
import io

router = APIRouter()

logger = logging.getLogger(__name__)

# Setup Jinja2 environment
TEMPLATES_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "templates")
STATIC_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "static")
FONTS_DIR = os.path.join(STATIC_DIR, "fonts")

# Load and encode fonts as base64
def load_font_base64(font_path: str) -> str:
    with open(font_path, 'rb') as f:
        return base64.b64encode(f.read()).decode('utf-8')

GEIST_FONT_BASE64 = load_font_base64(os.path.join(FONTS_DIR, "Geist/variable/Geist[wght].ttf"))
GEIST_MONO_FONT_BASE64 = load_font_base64(os.path.join(FONTS_DIR, "GeistMono-Bold.woff2"))

env = Environment(loader=FileSystemLoader(TEMPLATES_DIR))

class SongData(BaseModel):
    song_id: str
    name: str
    artist: str
    cover_url: Optional[str] = None

class ReceiptRequest(BaseModel):
    songs: List[SongData]
    orderId: int
    dateStr: str
    timeStr: str

def generate_barcode_pattern(songs: List[SongData]) -> List[dict[str, Any]]:
    # Generate a pseudo-random but stable pattern based on the songs
    seed = sum(len(s.name) for s in songs)
    pattern = []
    widths = [1, 2, 4, 6]
    
    for i in range(80):
        width = widths[(seed + i) % 4]
        # logic: ((seed * (i + 1)) % 10) > 1
        visible = ((seed * (i + 1)) % 10) > 1
        pattern.append({"width": width, "visible": visible})
        
    return pattern

@router.post("/generate-receipt")
async def generate_receipt(request: ReceiptRequest):
    try:
        # Log the full request for debugging
        logger.info(f"Generating receipt for Order: {request.orderId}, Date: {request.dateStr}, Time: {request.timeStr}")
        
        template = env.get_template("receipt.html")
        
        # Take top 10 songs
        top_10_songs = request.songs[:10]
        
        barcode_pattern = generate_barcode_pattern(request.songs)
        
        # Explicitly cast to string and prepare context
        context = {
            "songs": top_10_songs,
            "order_id": str(request.orderId),
            "date_str": str(request.dateStr),
            "time_str": str(request.timeStr),
            "barcode_pattern": barcode_pattern,
            "geist_font_base64": GEIST_FONT_BASE64,
            "geist_mono_font_base64": GEIST_MONO_FONT_BASE64
        }
        
        logger.info(f"Rendering template with context keys: {list(context.keys())}")
        logger.info(f"Order ID value: '{context['order_id']}'")
        
        html_content = template.render(**context)
        
        async with async_playwright() as p:
            browser = await p.chromium.launch(args=["--no-sandbox", "--disable-setuid-sandbox"])
            page = await browser.new_page(viewport={"width": 1080, "height": 1200})
            
            # Load HTML content
            await page.set_content(html_content, wait_until="networkidle")
            
            # Wait for fonts to load (using document.fonts.ready)
            await page.evaluate("document.fonts.ready")
            
            # Debug: Check what fonts are loaded
            loaded_fonts = await page.evaluate("""
                Array.from(document.fonts).map(f => ({
                    family: f.family,
                    weight: f.weight,
                    style: f.style,
                    status: f.status
                }))
            """)
            logger.info(f"Loaded fonts: {loaded_fonts}")
            
            # Get the actual height of the content to ensure we capture everything
            # Although the design is fixed width/min-height, let's just grab the element
            element = await page.query_selector("body")
            if not element:
                 raise HTTPException(status_code=500, detail="Could not render receipt")
            
            screenshot_bytes = await element.screenshot(type="png")
            
            await browser.close()
            
            return StreamingResponse(io.BytesIO(screenshot_bytes), media_type="image/png")
            
    except Exception as e:
        logger.error(f"Error generating receipt: {e}")
        raise HTTPException(status_code=500, detail=str(e))
